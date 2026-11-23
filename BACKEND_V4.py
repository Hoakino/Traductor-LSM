import cv2
import mediapipe as mp
import numpy as np
import json
import os
import socket
import threading
import struct
from collections import deque
from wordsegment import load, segment   

# ════════════════════════════════════════════
#  BACKEND V4
#  Puerto 9999 → frames + JSON al cliente Java
#  Puerto 9998 → comandos de Java
#
#  Comandos disponibles:
#    "MODO:ABECEDARIO"
#    "MODO:VOCABULARIO"
#    "MANO:DERECHA"
#    "MANO:IZQUIERDA"
#    "BORRAR_LETRA"
#    "BORRAR_TODO"
#
#  CAMBIOS (fix de mano derecha/izquierda):
#   - En modo ABECEDARIO solo se procesa UNA mano (la primera que
#     detecta MediaPipe), sin importar si aparece una segunda en el
#     cuadro. Ya NO se usa la clasificación Right/Left de MediaPipe
#     para decidir "cuál mano es cuál" en este modo — es justo esa
#     clasificación la que se confunde/parpadea. La única mano
#     detectada se compara contra los patrones del lado que el
#     usuario eligió desde el frontend (comando MANO:...), tanto
#     para letras estáticas como dinámicas (J,K,Q,X,Z).
#   - Los patrones estáticos ahora admiten VARIAS muestras por letra
#     y por lado (cargadas desde patrones_capturados.json, con clave
#     "LETRA__DERECHA" / "LETRA__IZQUIERDA" generadas por
#     capturador3.py), no solo el prototipo único de fábrica.
#   - En modo VOCABULARIO se mantiene la detección de las 2 manos
#     tal como antes (ahí sí se necesitan ambas simultáneamente).
# ════════════════════════════════════════════



BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load() 

def segmentar_texto(texto):
    if not texto.strip():
        return texto
    palabras = segment(texto.replace(" ", "").lower())
    return " ".join(palabras)

mp_hands = mp.solutions.hands
mp_draw  = mp.solutions.drawing_utils

# Dos instancias separadas en vez de una sola con max_num_hands=2:
# así, en modo ABECEDARIO, MediaPipe ni siquiera busca una segunda
# mano (no solo se ignora en el código) — de verdad detecta 1 sola.
hands_abecedario = mp_hands.Hands(
    max_num_hands=1,
    min_detection_confidence=0.8,
    min_tracking_confidence=0.8
)
hands_vocabulario = mp_hands.Hands(
    max_num_hands=2,
    min_detection_confidence=0.8,
    min_tracking_confidence=0.8
)

cap = cv2.VideoCapture(0)

# ════════════════════════════════════════════
#  ESTADO GLOBAL
# ════════════════════════════════════════════
modo         = "ABECEDARIO"
mano_activa  = "DERECHA"       # "DERECHA" | "IZQUIERDA"
modo_lock    = threading.Lock()

texto        = ""
ultima_seña  = ""
contador     = 0

BUFFER_LEN    = 50
UMBRAL_DTW    = 2.5 #2.5
UMBRAL_DTW_2M = 3.0 #3.0
DEDO          = 8

buf_der = deque(maxlen=BUFFER_LEN)
buf_izq = deque(maxlen=BUFFER_LEN)

INDICES_MP       = [4, 8, 12, 16, 20, 6, 10, 14, 18]
UMBRAL_SIMILITUD = 0.82

def proto_a_vector(proto):
    pts = np.array(proto)
    c   = pts.mean(axis=0)
    pc  = pts - c
    s   = np.std(pc) + 1e-6
    return (pc / s).flatten()

def query_a_vector(puntos_raw):
    puntos = np.array(puntos_raw)
    kp     = puntos[INDICES_MP]
    c      = kp.mean(axis=0)
    kpc    = kp - c
    s      = np.std(kpc) + 1e-6
    return (kpc / s).flatten()

# Cada letra guarda una LISTA de vectores, uno por muestra capturada.
# Se llenan completamente desde patrones_capturados.json (ver
# cargar_json más abajo) — ya no hay prototipos de fábrica en el
# código; si una letra/lado no ha sido capturada aún, simplemente no
# aparece aquí y el sistema no la reconoce hasta que la capturen.
VECS_DER = {}
VECS_IZQ = {}

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)

def reconocer_estatica(puntos_raw, vecs_proto):
    """vecs_proto: dict letra -> lista de vectores (1 o varios)."""
    vec = query_a_vector(puntos_raw)
    mejor, mejor_sim = "", -1.0
    for l, lista_vecs in vecs_proto.items():
        for vp in lista_vecs:
            sim = cosine_similarity(vec, vp)
            if sim > mejor_sim:
                mejor_sim = sim
                mejor     = l
    return (mejor, mejor_sim) if mejor_sim >= UMBRAL_SIMILITUD else ("", mejor_sim)

# ════════════════════════════════════════════
#  CARGA DE PATRONES DINÁMICOS DESDE JSON
# ════════════════════════════════════════════
# Dinámicas de 1 mano, separadas por lado. En este sistema, "1 mano"
# SIEMPRE significa letra del abecedario (las opciones 1/2 del
# capturador, que son las únicas que producen manos=1); las opciones
# de vocabulario siempre son de 2 manos. Por eso aquí ya no se filtra
# por una lista fija de letras — antes solo J,K,Q,X,Z caían aquí y
# cualquier otra letra dinámica (p.ej. "LL") se iba por error a
# vocabulario. Ahora CUALQUIER letra dinámica de 1 mano cae aquí.
abc_din_der = {}
abc_din_izq = {}
voc_2m      = {}

def _descomponer_clave(clave):
    """'A__DERECHA' -> ('A','DERECHA'); 'HOLA' -> ('HOLA', None)."""
    if "__" in clave:
        base, lado = clave.rsplit("__", 1)
        if lado in ("DERECHA", "IZQUIERDA"):
            return base, lado
    return clave, None

def cargar_json(archivo):
    if not os.path.exists(archivo):
        print(f"[WARN] No encontrado: {archivo}")
        return
    with open(archivo, "r", encoding="utf-8") as f:
        data = json.load(f)

    for clave, info in data.items():
        manos    = info.get("manos", 1)
        tipo     = info.get("tipo", "")
        etiqueta, lado = _descomponer_clave(clave)
        muestras = info.get("muestras", [])

        if manos == 2:
            # Vocabulario / palabras — sin split de lado, se usan las 2 manos.
            # Las sintéticas se omiten aquí: el DTW es caro por muestra y
            # las variantes sintéticas (ruido/rotación) no aportan tanto
            # como en las estáticas — solo suman comparaciones de más.
            for muestra in muestras:
                if muestra.get("sintetica"):
                    continue
                td = muestra.get("trayectoria_der")
                ti = muestra.get("trayectoria_izq")
                if td and ti:
                    voc_2m.setdefault(etiqueta, []).append({
                        "der": np.array(td),
                        "izq": np.array(ti),
                    })
            continue

        # ── manos == 1 ──
        if tipo == "estatica":
            for muestra in muestras:
                pose = muestra.get("pose")
                if not pose:
                    continue
                vec = proto_a_vector(pose)
                if lado == "DERECHA":
                    VECS_DER.setdefault(etiqueta, []).append(vec)
                elif lado == "IZQUIERDA":
                    VECS_IZQ.setdefault(etiqueta, []).append(vec)
                else:
                    # Dato viejo sin lado conocido: se agrega a ambos
                    # lados como candidato, mejor que perderlo.
                    VECS_DER.setdefault(etiqueta, []).append(vec)
                    VECS_IZQ.setdefault(etiqueta, []).append(vec)

        else:  # dinámica de 1 mano → SIEMPRE es letra de abecedario en
               # este sistema (manos=1 solo sale de las opciones 1/2 del
               # capturador). Ya no se filtra por una lista fija de
               # letras — así "LL" y cualquier otra letra dinámica caen
               # aquí correctamente, no en vocabulario.
            for muestra in muestras:
                if muestra.get("sintetica"):
                    continue
                traj = muestra.get("trayectoria")
                if not traj:
                    continue
                arr = np.array(traj)
                if lado == "DERECHA":
                    abc_din_der.setdefault(etiqueta, []).append(arr)
                elif lado == "IZQUIERDA":
                    abc_din_izq.setdefault(etiqueta, []).append(arr)
                else:
                    # Dato viejo sin lado: se agrega a ambos lados.
                    abc_din_der.setdefault(etiqueta, []).append(arr)
                    abc_din_izq.setdefault(etiqueta, []).append(arr.copy())

    print(f"[OK] JSON cargado: {archivo}")
    print(f"     Estáticas  DER (desde JSON) : {sorted(VECS_DER.keys())}")
    print(f"     Estáticas  IZQ (desde JSON) : {sorted(VECS_IZQ.keys())}")
    print(f"     Abecedario dinám. DER: {sorted(abc_din_der.keys())}")
    print(f"     Abecedario dinám. IZQ: {sorted(abc_din_izq.keys())}")
    print(f"     Vocabulario 2 manos  : {sorted(voc_2m.keys())}")

cargar_json(os.path.join(BASE_DIR, "patrones_capturados.json"))

if not VECS_DER and not VECS_IZQ:
    print("[AVISO] No hay ninguna letra estática cargada del JSON todavía "
          "— captúralas con capturador3.py antes de usar el modo ABECEDARIO.")

# ════════════════════════════════════════════
#  HELPERS DTW
# ════════════════════════════════════════════
def resamplear(traj, n=30):
    traj = np.array(traj, dtype=np.float32)
    if len(traj) < 2:
        return None
    d  = np.sqrt(((np.diff(traj, axis=0))**2).sum(axis=1))
    dc = np.concatenate([[0], np.cumsum(d)])
    if dc[-1] < 1e-4:
        return None
    t = np.linspace(0, dc[-1], n)
    return np.stack([np.interp(t, dc, traj[:,0]),
                     np.interp(t, dc, traj[:,1])], axis=1)

def normalizar(traj):
    pts = np.array(traj, dtype=np.float32)
    c   = pts.mean(axis=0)
    pts -= c
    s   = np.std(pts) + 1e-6
    return pts / s

def dtw(a, b):
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    n, m = len(a), len(b)
    # Matriz de costos completa en UNA sola operación vectorizada, en vez
    # de llamar np.linalg.norm() n*m veces dentro del ciclo (eso era lo
    # que trababa la cámara: con 30x30 puntos y ~15-75 muestras por
    # letra, eran cientos de miles de llamadas a numpy por cuadro).
    costo = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(axis=2))
    D = np.full((n + 1, m + 1), np.inf, dtype=np.float32)
    D[0, 0] = 0
    for i in range(1, n + 1):
        ci = costo[i - 1]
        Di = D[i]
        Dprev = D[i - 1]
        for j in range(1, m + 1):
            Di[j] = ci[j - 1] + min(Dprev[j], Di[j - 1], Dprev[j - 1])
    return D[n, m] / (n + m)

def preparar_buf(buf):
    lst = list(buf)
    if len(lst) < 10:
        return None
    r = resamplear(lst, 30)
    return normalizar(r) if r is not None else None

def reconocer_din_1m(buf, patrones, umbral):
    traj = preparar_buf(buf)
    if traj is None:
        return "", 9999.0
    mejor, best = "", 9999.0
    for etiq, muestras in patrones.items():
        for patron in muestras:
            d = dtw(traj, patron)
            if d < best:
                best, mejor = d, etiq
    return (mejor, best) if best <= umbral else ("", best)

def reconocer_din_2m(buf_d, buf_i, patrones, umbral):
    td = preparar_buf(buf_d)
    ti = preparar_buf(buf_i)
    if td is None or ti is None:
        return "", 9999.0
    mejor, best = "", 9999.0
    for etiq, muestras in patrones.items():
        for m in muestras:
            d = (dtw(td, m["der"]) + dtw(ti, m["izq"])) / 2
            if d < best:
                best, mejor = d, etiq
    return (mejor, best) if best <= umbral else ("", best)

# ════════════════════════════════════════════
#  SEGMENTACIÓN DE GESTOS (inicio/fin de movimiento)
#
#  Antes, la letra dinámica se comparaba CADA CUADRO contra una
#  ventana deslizante de los últimos 50 puntos, que mezclaba reposo +
#  gesto + reposo sin ningún corte — muy distinto a como se capturó
#  cada muestra en capturador3.py (inicio y fin marcados a mano con
#  SPACE). Eso explica que "cueste reconocer a la primera": la forma
#  de la trayectoria que se comparaba casi nunca era la trayectoria
#  "limpia" del gesto.
#
#  Ahora se detecta cuándo la mano EMPIEZA a moverse (se limpia el
#  buffer justo ahí, para no arrastrar reposo previo) y cuándo se
#  QUEDA QUIETA otra vez (ahí se dispara el reconocimiento UNA sola
#  vez, no en cada cuadro).
# ════════════════════════════════════════════
UMBRAL_MOVIMIENTO = 0.015   # desplazamiento mínimo entre cuadros para contar como "moviéndose"
FRAMES_QUIETO_FIN = 6       # cuadros quieto seguidos para dar el gesto por terminado

def _nueva_segmentacion():
    return {"activo": False, "quieto": 0, "listo": False, "ultimo_punto": None}

seg_der = _nueva_segmentacion()
seg_izq = _nueva_segmentacion()

def actualizar_segmentacion(seg, buf, punto_nuevo):
    """Actualiza el estado de movimiento/quietud de una mano y decide
    si hay que limpiar el buffer (inicio de gesto) o marcar 'listo'
    para reconocer (fin de gesto)."""
    if seg["ultimo_punto"] is not None:
        disp = float(np.linalg.norm(np.array(punto_nuevo) - np.array(seg["ultimo_punto"])))
    else:
        disp = 0.0
    seg["ultimo_punto"] = punto_nuevo

    if disp > UMBRAL_MOVIMIENTO:
        if not seg["activo"]:
            buf.clear()   # empieza un gesto nuevo: fuera lo viejo
        seg["activo"] = True
        seg["quieto"] = 0
    elif seg["activo"]:
        seg["quieto"] += 1
        if seg["quieto"] >= FRAMES_QUIETO_FIN:
            seg["listo"]  = True
            seg["activo"] = False

def resetear_segmentacion(seg):
    seg["activo"], seg["quieto"], seg["listo"], seg["ultimo_punto"] = False, 0, False, None

def identificar_manos(multi_lm, multi_hd):
    der, izq = None, None
    for lm, hd in zip(multi_lm, multi_hd):
        label = hd.classification[0].label
        if label == "Right":
            izq = lm
        else:
            der = lm
    return der, izq

# ════════════════════════════════════════════
#  SERVIDOR DE FRAMES → Java (puerto 9999)
# ════════════════════════════════════════════
PORT_FRAMES  = 9999
cliente_conn = None
cliente_lock = threading.Lock()

def enviar_paquete(conn, frame_jpg, datos_json):
    try:
        json_bytes = json.dumps(datos_json, ensure_ascii=False).encode("utf-8")
        conn.sendall(struct.pack(">I", len(frame_jpg)))
        conn.sendall(frame_jpg)
        conn.sendall(struct.pack(">I", len(json_bytes)))
        conn.sendall(json_bytes)
        return True
    except (BrokenPipeError, ConnectionResetError, OSError):
        return False

def hilo_servidor_frames():
    global cliente_conn
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT_FRAMES))
    srv.listen(1)
    print(f"[FRAMES] Esperando Java en puerto {PORT_FRAMES}...")
    while True:
        conn, addr = srv.accept()
        print(f"[FRAMES] Java conectado: {addr}")
        with cliente_lock:
            if cliente_conn:
                try:
                    cliente_conn.close()
                except:
                    pass
            cliente_conn = conn

threading.Thread(target=hilo_servidor_frames, daemon=True).start()

# ════════════════════════════════════════════
#  SERVIDOR DE COMANDOS ← Java (puerto 9998)
# ════════════════════════════════════════════
PORT_COMANDOS = 9998

def hilo_servidor_comandos():
    global modo, mano_activa, texto, ultima_seña, contador
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT_COMANDOS))
    srv.listen(5)
    print(f"[COMANDOS] Escuchando en puerto {PORT_COMANDOS}...")
    while True:
        try:
            conn, addr = srv.accept()
            with conn:
                data = conn.recv(256).decode("utf-8").strip()
                print(f"[COMANDO] Recibido: '{data}'")
                with modo_lock:
                    if data == "MODO:VOCABULARIO":
                        modo = "VOCABULARIO"
                        texto = ""; ultima_seña = ""; contador = 0
                        buf_der.clear(); buf_izq.clear()
                        resetear_segmentacion(seg_der); resetear_segmentacion(seg_izq)
                        print("[MODO] → VOCABULARIO")
                    elif data == "MODO:ABECEDARIO":
                        modo = "ABECEDARIO"
                        texto = ""; ultima_seña = ""; contador = 0
                        buf_der.clear(); buf_izq.clear()
                        resetear_segmentacion(seg_der); resetear_segmentacion(seg_izq)
                        print("[MODO] → ABECEDARIO")
                    elif data == "MANO:DERECHA":
                        mano_activa = "DERECHA"
                        buf_der.clear(); buf_izq.clear()
                        resetear_segmentacion(seg_der); resetear_segmentacion(seg_izq)
                        print("[MANO] → DERECHA")
                    elif data == "MANO:IZQUIERDA":
                        mano_activa = "IZQUIERDA"
                        buf_der.clear(); buf_izq.clear()
                        resetear_segmentacion(seg_der); resetear_segmentacion(seg_izq)
                        print("[MANO] → IZQUIERDA")
                    elif data == "BORRAR_LETRA":
                        if len(texto) > 0:
                            texto = texto[:-1]
                        print(f"[COMANDO] Borrar letra → '{texto}'")
                    elif data == "BORRAR_TODO":
                        texto = ""
                        print("[COMANDO] Borrar todo")
        except Exception as e:
            print(f"[COMANDOS] Error: {e}")

threading.Thread(target=hilo_servidor_comandos, daemon=True).start()

# ════════════════════════════════════════════
#  LOOP PRINCIPAL
# ════════════════════════════════════════════
while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame   = cv2.flip(frame, 1)
    rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    with modo_lock:
        modo_para_manos = modo

    # En ABECEDARIO usamos la instancia limitada a 1 mano: MediaPipe
    # ni siquiera intenta detectar una segunda, así que aunque aparezcan
    # 2 manos en el cuadro, solo una se procesa siempre.
    hands_activo = hands_abecedario if modo_para_manos == "ABECEDARIO" else hands_vocabulario
    results = hands_activo.process(rgb)

    mano_der = None
    mano_izq = None
    raw_der  = None
    raw_izq  = None

    if results.multi_hand_landmarks:
        for hl in results.multi_hand_landmarks:
            mp_draw.draw_landmarks(frame, hl, mp_hands.HAND_CONNECTIONS)

        if modo_para_manos == "ABECEDARIO":
            # Solo puede haber 1 mano aquí (hands_abecedario está limitado
            # a max_num_hands=1). "mano_der" es solo el contenedor que
            # reutiliza el resto del código; el lado real contra el que
            # se compara lo decide "mano_activa" (lo que el usuario
            # eligió desde el frontend), no MediaPipe.
            mano_der = results.multi_hand_landmarks[0]
            raw_der  = [[lm.x, lm.y] for lm in mano_der.landmark]
            punto = [mano_der.landmark[DEDO].x, mano_der.landmark[DEDO].y]
            buf_der.append(punto)
            actualizar_segmentacion(seg_der, buf_der, punto)
        else:
            # VOCABULARIO: aquí sí se necesitan ambas manos a la vez,
            # cada una con su propia trayectoria guardada en el JSON.
            mano_der, mano_izq = identificar_manos(
                results.multi_hand_landmarks,
                results.multi_handedness
            )
            if mano_der:
                raw_der = [[lm.x, lm.y] for lm in mano_der.landmark]
                punto = [mano_der.landmark[DEDO].x, mano_der.landmark[DEDO].y]
                buf_der.append(punto)
                actualizar_segmentacion(seg_der, buf_der, punto)
            if mano_izq:
                raw_izq = [[lm.x, lm.y] for lm in mano_izq.landmark]
                punto = [mano_izq.landmark[DEDO].x, mano_izq.landmark[DEDO].y]
                buf_izq.append(punto)
                actualizar_segmentacion(seg_izq, buf_izq, punto)

    with modo_lock:
        modo_actual  = modo
        mano_actual  = mano_activa

    seña      = ""
    confianza = 0.0
    dos_ok    = bool(mano_der and mano_izq)

    # ── Seleccionar prototipos según mano activa ──
    # La mano visible se usa siempre (cualquiera que MediaPipe detecte).
    # Solo los prototipos cambian según la preferencia del usuario.
    vecs_activo = VECS_DER if mano_actual == "DERECHA" else VECS_IZQ

    # raw_visible: landmarks de la primera mano detectada (der tiene prioridad)
    raw_visible = raw_der if raw_der else raw_izq

    # ── Reconocimiento según modo ──
    evento_dinamico = False   # True si "seña" viene de un gesto que ya
                               # terminó (se confirma al instante, no
                               # esperando a que se repita 12 cuadros)
    if modo_actual == "ABECEDARIO":
        # 1. Estática — usa los prototipos de la mano seleccionada
        if raw_visible:
            seña, confianza = reconocer_estatica(raw_visible, vecs_activo)
        # 2. Dinámica — solo se compara cuando el gesto ya terminó
        #    (seg_der["listo"]), no en cada cuadro contra una ventana
        #    deslizante que mezcla reposo con movimiento.
        if not seña and seg_der["listo"]:
            abc_din_activo = abc_din_der if mano_actual == "DERECHA" else abc_din_izq
            if abc_din_activo:
                seña, confianza = reconocer_din_1m(buf_der, abc_din_activo, UMBRAL_DTW)
                if seña:
                    evento_dinamico = True
            seg_der["listo"] = False
            buf_der.clear()
    else:  # VOCABULARIO
        # 1. Dinámicas 2 manos (prioridad) — se mantiene la comparación
        #    continua (coordinar el fin de gesto de ambas manos a la vez
        #    es más delicado; con muestras reales + DTW vectorizado ya
        #    no debería trabar la cámara).
        if dos_ok and voc_2m:
            seña, confianza = reconocer_din_2m(buf_der, buf_izq, voc_2m, UMBRAL_DTW_2M)

    # ── Filtro anti-repetición ──
    # Las letras dinámicas son un evento de una sola vez: se confirman
    # apenas se reconocen. Las estáticas siguen necesitando sostenerse
    # ~12 cuadros seguidos (evita que un parpadeo la escriba sola).
    sep = "" if modo_actual == "ABECEDARIO" else " "
    if evento_dinamico:
        texto      += seña + sep
        contador    = 0
        ultima_seña = ""
    else:
        if seña == ultima_seña and seña != "":
            contador += 1
        else:
            contador = 0

        if contador > 12:#frameesadsa
            texto      += seña + sep
            contador    = 0
            buf_der.clear()
            buf_izq.clear()

        ultima_seña = seña

    # ── Dibujar sobre el frame ANTES de enviarlo a Java ──
    color_seña = (0, 255, 0) if seña else (0, 100, 255)
    cv2.putText(frame, f"{modo_actual} | {mano_actual}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (200, 200, 200), 2)
    cv2.putText(frame, f"{seña}", (50, 100),
                cv2.FONT_HERSHEY_SIMPLEX, 2.5, color_seña, 3)
    cv2.putText(frame, f"Sim: {round(float(confianza), 2)}", (10, 140),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)
    # cv2.imshow("Traductor LSM", frame)  # comentado: la ventana la muestra Java

    # ── Enviar frame + datos a Java ──
    with cliente_lock:
        conn = cliente_conn

    if conn:
        _, jpg_buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
        datos = {
            "letra"    : seña,
            "confianza": round(float(confianza), 3),
            "texto"    : segmentar_texto(texto),   # ← solo cambia esto
            "modo"     : modo_actual,
            "mano"     : mano_actual
        }
        ok = enviar_paquete(conn, jpg_buf.tobytes(), datos)
        if not ok:
            print("[FRAMES] Cliente desconectado")
            with cliente_lock:
                cliente_conn = None

    tecla = cv2.waitKey(1)
    if tecla == 27:
        break
    elif tecla == ord('c'):
        texto = ""
        buf_der.clear()
        buf_izq.clear()
        resetear_segmentacion(seg_der); resetear_segmentacion(seg_izq)
    elif tecla == ord('m'):
        with modo_lock:
            modo        = "VOCABULARIO" if modo == "ABECEDARIO" else "ABECEDARIO"
            texto       = ""; ultima_seña = ""; contador = 0
            buf_der.clear(); buf_izq.clear()
            resetear_segmentacion(seg_der); resetear_segmentacion(seg_izq)
        print(f"[MODO] → {modo}")
    elif tecla == ord('h'):   # h de "hand"
        with modo_lock:
            mano_activa = "IZQUIERDA" if mano_activa == "DERECHA" else "DERECHA"
            buf_der.clear(); buf_izq.clear()
            resetear_segmentacion(seg_der); resetear_segmentacion(seg_izq)
        print(f"[MANO] → {mano_activa}")

cap.release()
cv2.destroyAllWindows()