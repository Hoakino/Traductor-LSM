import cv2
import mediapipe as mp
import numpy as np
import json
import os
import time
from collections import deque

# ════════════════════════════════════════════
#  CAPTURADOR LSM v3  —  exporta patrones a JSON
#  Modos: estático | dinámico | combinado
#  1 mano → letras (ahora pide explícitamente Derecha/Izquierda)
#  2 manos → palabras, adjetivos, adverbios, animales, etc.
#
#  NOVEDAD v3: para señas de 1 mano, ya no se confía en la
#  clasificación Right/Left de MediaPipe (que se confunde/parpadea).
#  El usuario indica la mano ANTES de capturar, y la muestra se
#  guarda con la clave "ETIQUETA__DERECHA" / "ETIQUETA__IZQUIERDA".
#  El backend usa esa clave para comparar contra el lado correcto,
#  sin depender de si MediaPipe etiquetó bien la mano en cada frame.
#
#  NOVEDADES heredadas de la v2:
#   - Cantidad de muestras configurable en vivo (antes fija en 3)
#   - Aumentación sintética automática (rotación/escala/ruido) por
#     cada muestra real capturada, para multiplicar el dataset
#     sin más sesiones de captura
#   - Reporte de calidad después de cada seña: consistencia interna
#     (qué tan parecidas fueron tus propias repeticiones) y
#     confusión potencial (si la nueva seña se parece demasiado a
#     otra ya guardada)
#   - Modo PRUEBA [T]: reconocimiento en vivo contra lo ya guardado,
#     sin escribir nada al JSON, para validar in situ durante la
#     sesión de captura (útil en IIPEDEY con la maestra de LSM)
# ════════════════════════════════════════════

mp_hands = mp.solutions.hands
mp_draw  = mp.solutions.drawing_utils

# max_num_hands=2 siempre; la lógica decide cuántas usar según el tipo.
hands = mp_hands.Hands(
    max_num_hands=2,
    min_detection_confidence=0.8,
    min_tracking_confidence=0.8
)

cap = cv2.VideoCapture(0)

ARCHIVO_SALIDA    = "patrones_capturados.json"
INDICES_ESTATICOS = [4, 8, 12, 16, 20, 6, 10, 14, 18]
DEDO_TRAYECTORIA  = 8   # índice rastreado para movimientos

# Opciones 1 mano vs 2 manos
TIPO_1_MANO  = {"1", "2"}
TIPO_2_MANOS = {"3", "4", "5"}

# Señas de 1 mano se guardan como "ETIQUETA__DERECHA" / "ETIQUETA__IZQUIERDA"
# para que el backend sepa, sin depender de MediaPipe, contra qué lado
# comparar. Señas de 2 manos NO llevan sufijo (se usan ambas siempre).
SUF_MANO = "__"

def clave_json(etiqueta, dos, mano_captura=None):
    if dos:
        return etiqueta
    return f"{etiqueta}{SUF_MANO}{mano_captura}"

def descomponer_clave(clave):
    """('A__DERECHA') -> ('A', 'DERECHA'); ('HOLA') -> ('HOLA', None)"""
    if SUF_MANO in clave:
        base, lado = clave.rsplit(SUF_MANO, 1)
        if lado in ("DERECHA", "IZQUIERDA"):
            return base, lado
    return clave, None

def etiqueta_legible(clave):
    base, lado = descomponer_clave(clave)
    if lado:
        return f"{base} ({'D' if lado=='DERECHA' else 'I'})"
    return base

# ── Configuración de muestras ──────────────────
NUM_MUESTRAS_DEFAULT = 15   # antes: 3
NUM_MUESTRAS_MIN     = 5
NUM_MUESTRAS_MAX     = 40
NUM_MUESTRAS_PASO    = 5

# ── Configuración de aumentación sintética ─────
GENERAR_AUMENTADAS   = True
AUMENTADAS_POR_REAL  = 4     # variantes sintéticas por cada muestra real
ROT_MAX_DEG          = 12    # rotación aleatoria +/- grados
ESCALA_JITTER        = 0.08  # +/- 8% de escala
RUIDO_POSE           = 0.012
RUIDO_TRAYECTORIA    = 0.015

# ── Umbrales de calidad (mismo orden de magnitud que el backend) ──
UMBRAL_DTW_1M           = 2.5
UMBRAL_DTW_2M           = 3.0
UMBRAL_CONSISTENCIA_SIM = 0.85   # similitud promedio mínima entre tus propias muestras
UMBRAL_CONFUSION_SIM    = 0.93   # similitud contra otra seña ya guardada → alerta

# ────────────────────────────────────────────
#  Colores UI  (BGR)
# ────────────────────────────────────────────
C_PANEL    = (30,  30,  30)
C_VERDE    = (80, 220, 100)
C_ROJO     = (60,  80, 220)
C_AMARILLO = (40, 210, 240)
C_AZUL     = (220,140,  50)
C_GRIS     = (160,160, 160)
C_BLANCO   = (240,240, 240)
C_TEAL     = (180,210,  80)
C_NARANJA  = (50, 165, 255)   # color distintivo para la segunda mano

# ════════════════════════════════════════════
#  ESTADO GLOBAL
# ════════════════════════════════════════════
estado = {
    "modo"              : "MENU",
    "tipo"              : "",
    "opcion"            : "",
    "dos_manos"         : False,
    "mano_captura"      : None,        # "DERECHA" | "IZQUIERDA", solo señas de 1 mano
    "etiqueta"          : "",
    "muestras"          : [],          # muestras reales de la captura en curso
    "muestras_aumentadas": [],         # sintéticas derivadas de las reales
    "num_muestras"      : NUM_MUESTRAS_DEFAULT,
    "trayectoria_d"     : [],
    "trayectoria_i"     : [],
    "input_text"        : "",
    "mensaje"           : "",
    "msg_color"         : C_VERDE,
    "msg_timer"         : 0,
    "reporte"           : None,        # dict con el resumen de calidad tras capturar
    "test_grabando"     : False,
    "test_resultado"    : None,
}

patrones = {}

# ════════════════════════════════════════════
#  HELPERS — IO y utilidades base (igual que v1)
# ════════════════════════════════════════════

def flash(msg, color=C_VERDE):
    estado["mensaje"]   = msg
    estado["msg_color"] = color
    estado["msg_timer"] = int(time.time() * 1000) + 2500

def cargar_existente():
    global patrones
    if os.path.exists(ARCHIVO_SALIDA):
        with open(ARCHIVO_SALIDA, "r", encoding="utf-8") as f:
            patrones = json.load(f)
        flash(f"Cargado: {ARCHIVO_SALIDA}  ({len(patrones)} señas)", C_TEAL)

def guardar():
    with open(ARCHIVO_SALIDA, "w", encoding="utf-8") as f:
        json.dump(patrones, f, indent=2, ensure_ascii=False)
    flash(f"Guardado  →  {ARCHIVO_SALIDA}", C_VERDE)

def extraer_pose(landmarks):
    return [[landmarks[i].x, landmarks[i].y] for i in INDICES_ESTATICOS]

def resamplear(traj, n=30):
    traj = np.array(traj, dtype=np.float32)
    if len(traj) < 2:
        return None
    deltas  = np.diff(traj, axis=0)
    dists   = np.sqrt((deltas**2).sum(axis=1))
    dists_c = np.concatenate([[0], np.cumsum(dists)])
    total   = dists_c[-1]
    if total < 1e-4:
        return None
    t_new = np.linspace(0, total, n)
    xs = np.interp(t_new, dists_c, traj[:, 0])
    ys = np.interp(t_new, dists_c, traj[:, 1])
    return np.stack([xs, ys], axis=1).tolist()

def normalizar_trayectoria(traj):
    pts = np.array(traj, dtype=np.float32)
    c   = pts.mean(axis=0)
    pts -= c
    s   = np.std(pts) + 1e-6
    pts /= s
    return pts.tolist()

def identificar_manos(multi_lm, multi_handedness):
    """
    Retorna (mano_der, mano_izq) según la perspectiva del usuario.
    Como el frame está volteado horizontalmente, los labels de MP
    quedan invertidos: 'Right' en MP = mano izquierda del usuario.
    """
    der, izq = None, None
    for lm, hd in zip(multi_lm, multi_handedness):
        label = hd.classification[0].label
        if label == "Right":
            izq = lm
        else:
            der = lm
    return der, izq

# ════════════════════════════════════════════
#  HELPERS — vectores, similitud y DTW
#  (para chequeo de calidad y modo prueba)
# ════════════════════════════════════════════

def pose_a_vector(pose):
    pts = np.array(pose, dtype=np.float32)
    c   = pts.mean(axis=0)
    pc  = pts - c
    s   = np.std(pc) + 1e-6
    return (pc / s).flatten()

def cosine_similarity(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

def vector_estatica_de_muestra(muestra, dos):
    """Vector normalizado de una muestra estática (o la parte de pose
    de una combinada). None si la muestra no trae pose."""
    if not dos:
        if "pose" not in muestra:
            return None
        return pose_a_vector(muestra["pose"])
    else:
        if "pose_der" not in muestra or "pose_izq" not in muestra:
            return None
        return np.concatenate([
            pose_a_vector(muestra["pose_der"]),
            pose_a_vector(muestra["pose_izq"]),
        ])

def dtw_distancia(a, b):
    a = np.array(a, dtype=np.float32)
    b = np.array(b, dtype=np.float32)
    n, m = len(a), len(b)
    D = np.full((n + 1, m + 1), np.inf, dtype=np.float32)
    D[0, 0] = 0
    for i in range(1, n + 1):
        ai = a[i - 1]
        for j in range(1, m + 1):
            costo = np.linalg.norm(ai - b[j - 1])
            D[i, j] = costo + min(D[i - 1, j], D[i, j - 1], D[i - 1, j - 1])
    return float(D[n, m])

def trayectorias_de_muestra(muestra, dos):
    """Devuelve una lista de trayectorias normalizadas contenidas en
    la muestra (1 elemento si es 1 mano, 2 si son 2 manos)."""
    if not dos:
        tr = muestra.get("trayectoria")
        return [tr] if tr else []
    else:
        tr_d = muestra.get("trayectoria_der")
        tr_i = muestra.get("trayectoria_izq")
        out = []
        if tr_d: out.append(tr_d)
        if tr_i: out.append(tr_i)
        return out

def dtw_distancia_muestra(m1, m2, dos):
    """Distancia DTW total entre dos muestras dinámicas (suma de
    ambas manos si aplica)."""
    tr1 = trayectorias_de_muestra(m1, dos)
    tr2 = trayectorias_de_muestra(m2, dos)
    if not tr1 or not tr2 or len(tr1) != len(tr2):
        return None
    return sum(dtw_distancia(a, b) for a, b in zip(tr1, tr2))

# ════════════════════════════════════════════
#  HELPERS — aumentación sintética
# ════════════════════════════════════════════

def rotar_puntos(pts, deg):
    pts = np.array(pts, dtype=np.float32)
    c   = pts.mean(axis=0)
    rad = np.radians(deg)
    rot = np.array([[np.cos(rad), -np.sin(rad)],
                     [np.sin(rad),  np.cos(rad)]], dtype=np.float32)
    return ((pts - c) @ rot.T + c)

def augmentar_pose(pose, n=AUMENTADAS_POR_REAL):
    variantes = []
    base = np.array(pose, dtype=np.float32)
    for _ in range(n):
        deg    = np.random.uniform(-ROT_MAX_DEG, ROT_MAX_DEG)
        escala = 1 + np.random.uniform(-ESCALA_JITTER, ESCALA_JITTER)
        c      = base.mean(axis=0)
        pts    = (base - c) * escala + c
        pts    = rotar_puntos(pts.tolist(), deg)
        pts    = pts + np.random.normal(0, RUIDO_POSE, pts.shape)
        variantes.append(pts.tolist())
    return variantes

def augmentar_trayectoria(traj_norm, n=AUMENTADAS_POR_REAL):
    variantes = []
    base = np.array(traj_norm, dtype=np.float32)
    for _ in range(n):
        deg    = np.random.uniform(-ROT_MAX_DEG, ROT_MAX_DEG)
        escala = 1 + np.random.uniform(-ESCALA_JITTER, ESCALA_JITTER)
        pts    = base * escala
        pts    = rotar_puntos(pts.tolist(), deg)
        pts    = pts + np.random.normal(0, RUIDO_TRAYECTORIA, pts.shape)
        variantes.append(pts.tolist())
    return variantes

def generar_muestra_aumentada(muestra_real, tipo, dos):
    """A partir de UNA muestra real ya guardada, genera
    AUMENTADAS_POR_REAL muestras sintéticas equivalentes."""
    sinteticas = []
    if tipo == "estatica":
        if not dos:
            for pose_v in augmentar_pose(muestra_real["pose"]):
                sinteticas.append({"pose": pose_v, "sintetica": True})
        else:
            der_variantes = augmentar_pose(muestra_real["pose_der"])
            izq_variantes = augmentar_pose(muestra_real["pose_izq"])
            for pd, pi in zip(der_variantes, izq_variantes):
                sinteticas.append({"pose_der": pd, "pose_izq": pi, "sintetica": True})

    elif tipo == "dinamica":
        if not dos:
            for tr_v in augmentar_trayectoria(muestra_real["trayectoria"]):
                sinteticas.append({"trayectoria": tr_v, "sintetica": True})
        else:
            der_variantes = augmentar_trayectoria(muestra_real["trayectoria_der"])
            izq_variantes = augmentar_trayectoria(muestra_real["trayectoria_izq"])
            for td, ti in zip(der_variantes, izq_variantes):
                sinteticas.append({"trayectoria_der": td, "trayectoria_izq": ti, "sintetica": True})

    elif tipo == "combinada":
        if not dos:
            tr_variantes = augmentar_trayectoria(muestra_real["trayectoria"])
            pose_variantes = augmentar_pose(muestra_real["pose"])
            for tr_v, pose_v in zip(tr_variantes, pose_variantes):
                sinteticas.append({"trayectoria": tr_v, "pose": pose_v, "sintetica": True})
        else:
            trd_v = augmentar_trayectoria(muestra_real["trayectoria_der"])
            tri_v = augmentar_trayectoria(muestra_real["trayectoria_izq"])
            pd_v  = augmentar_pose(muestra_real["pose_der"])
            pi_v  = augmentar_pose(muestra_real["pose_izq"])
            for td, ti, pd, pi in zip(trd_v, tri_v, pd_v, pi_v):
                sinteticas.append({
                    "trayectoria_der": td, "trayectoria_izq": ti,
                    "pose_der": pd, "pose_izq": pi, "sintetica": True,
                })
    return sinteticas

# ════════════════════════════════════════════
#  HELPERS — reporte de calidad tras capturar
# ════════════════════════════════════════════

def evaluar_calidad(label, tipo, dos, muestras_reales):
    """Devuelve un dict con consistencia interna y confusión
    potencial contra otras señas ya guardadas del mismo tipo/manos."""
    reporte = {
        "consistencia": None,       # 0..1, más alto = mejor (solo estática/combinada)
        "consistencia_ok": True,
        "consistencia_dtw": None,   # promedio DTW interno (solo dinámica/combinada), más bajo = mejor
        "confusion_con": None,      # etiqueta más parecida, si hay alerta
        "confusion_score": None,
    }

    usa_pose = tipo in ("estatica", "combinada")
    usa_traj = tipo in ("dinamica", "combinada")

    # ── Consistencia interna (pose) ──
    if usa_pose:
        vecs = [vector_estatica_de_muestra(m, dos) for m in muestras_reales]
        vecs = [v for v in vecs if v is not None]
        if len(vecs) >= 2:
            sims = [cosine_similarity(vecs[i], vecs[j])
                    for i in range(len(vecs)) for j in range(i + 1, len(vecs))]
            reporte["consistencia"] = float(np.mean(sims))
            reporte["consistencia_ok"] = reporte["consistencia"] >= UMBRAL_CONSISTENCIA_SIM

        # ── Confusión contra otras señas con pose ──
        if vecs:
            _, lado_nuevo = descomponer_clave(label)
            prom_nueva = np.mean(vecs, axis=0)
            mejor_label, mejor_sim = None, -1.0
            for k, v in patrones.items():
                if k == label or v.get("tipo") not in ("estatica", "combinada"):
                    continue
                if v.get("manos", 1) != (2 if dos else 1):
                    continue
                if not dos and descomponer_clave(k)[1] != lado_nuevo:
                    continue  # no comparar Derecha contra Izquierda: son geometrías espejo
                otros_vecs = [vector_estatica_de_muestra(m, dos) for m in v.get("muestras", [])
                              if not m.get("sintetica")]
                otros_vecs = [ov for ov in otros_vecs if ov is not None]
                if not otros_vecs:
                    continue
                prom_otro = np.mean(otros_vecs, axis=0)
                if len(prom_otro) != len(prom_nueva):
                    continue
                sim = cosine_similarity(prom_nueva, prom_otro)
                if sim > mejor_sim:
                    mejor_sim, mejor_label = sim, k
            if mejor_label is not None and mejor_sim >= UMBRAL_CONFUSION_SIM:
                reporte["confusion_con"]   = mejor_label
                reporte["confusion_score"] = mejor_sim

    # ── Consistencia interna (trayectoria, DTW) ──
    if usa_traj and not usa_pose:  # para "dinamica" pura; en "combinada" ya se reportó pose
        distancias = []
        for i in range(len(muestras_reales)):
            for j in range(i + 1, len(muestras_reales)):
                d = dtw_distancia_muestra(muestras_reales[i], muestras_reales[j], dos)
                if d is not None:
                    distancias.append(d)
        if distancias:
            reporte["consistencia_dtw"] = float(np.mean(distancias))
            umbral = UMBRAL_DTW_2M if dos else UMBRAL_DTW_1M
            reporte["consistencia_ok"] = reporte["consistencia_dtw"] <= umbral * 1.3

    return reporte

# ════════════════════════════════════════════
#  DIBUJO UI — helpers base (igual que v1)
# ════════════════════════════════════════════

def draw_panel(frame, x, y, w, h, alpha=0.55):
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x+w, y+h), C_PANEL, -1)
    cv2.addWeighted(overlay, alpha, frame, 1-alpha, 0, frame)
    cv2.rectangle(frame, (x, y), (x+w, y+h), (60,60,60), 1)

def put_text(frame, txt, pos, scale=0.55, color=C_BLANCO, thick=1,
             font=cv2.FONT_HERSHEY_SIMPLEX):
    cv2.putText(frame, txt, pos, font, scale, (0,0,0), thick+2)
    cv2.putText(frame, txt, pos, font, scale, color, thick)

def draw_badge(frame, txt, x, y, color, bg=(50,50,50)):
    (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    cv2.rectangle(frame, (x-6, y-th-4), (x+tw+6, y+4), bg, -1)
    cv2.rectangle(frame, (x-6, y-th-4), (x+tw+6, y+4), color, 1)
    put_text(frame, txt, (x, y), 0.45, color, 1)

def draw_progress(frame, actual, total, x, y, w=200):
    cv2.rectangle(frame, (x, y), (x+w, y+12), (50,50,50), -1)
    fill = int(w * actual / max(total, 1))
    cv2.rectangle(frame, (x, y), (x+fill, y+12), C_VERDE, -1)
    put_text(frame, f"{actual}/{total}", (x+w+8, y+10), 0.4, C_GRIS)

def draw_trayectoria(frame, traj, color_inicio, color_fin, grosor=2):
    fh, fw = frame.shape[:2]
    for i in range(1, len(traj)):
        a = i / len(traj)
        c = tuple(int(color_fin[k]*a + color_inicio[k]*(1-a)) for k in range(3))
        p1 = (int(traj[i-1][0]*fw), int(traj[i-1][1]*fh))
        p2 = (int(traj[i][0]*fw),   int(traj[i][1]*fh))
        cv2.line(frame, p1, p2, c, grosor)

def draw_landmarks_coloreado(frame, landmarks, color):
    fh, fw = frame.shape[:2]
    for i in INDICES_ESTATICOS:
        px = int(landmarks[i].x * fw)
        py = int(landmarks[i].y * fh)
        cv2.circle(frame, (px, py), 6, color, -1)

# ════════════════════════════════════════════
#  PANTALLAS
# ════════════════════════════════════════════

def pantalla_menu(frame):
    fh, fw = frame.shape[:2]
    draw_panel(frame, 0, 0, fw, 70)
    put_text(frame, "CAPTURADOR LSM v3", (20, 42), 1.1, C_AMARILLO, 2)
    put_text(frame, f"Señas guardadas: {len(patrones)}", (fw-220, 42), 0.55, C_GRIS)

    draw_panel(frame, fw//2-230, fh//2-180, 460, 390)
    opciones = [
        ("[N]  Nueva seña",           C_VERDE),
        ("[T]  Probar reconocimiento", C_TEAL),
        ("[L]  Ver señas guardadas",  C_AZUL),
        ("[E]  Exportar JSON",        C_AMARILLO),
        ("[B]  Borrar una seña",      C_ROJO),
        ("[ESC] Salir",               C_GRIS),
    ]
    cy = fh//2 - 140
    for txt, col in opciones:
        put_text(frame, txt, (fw//2-200, cy), 0.65, col, 1)
        cy += 50

def pantalla_tipo(frame):
    fh, fw = frame.shape[:2]
    draw_panel(frame, 0, 0, fw, 70)
    put_text(frame, "¿Qué tipo de seña?", (20, 42), 0.9, C_AMARILLO, 2)

    draw_panel(frame, fw//2-280, fh//2-210, 560, 440)
    grupos = [
        ("[1]  Letra  (estática)",              C_VERDE,    "1 mano"),
        ("[2]  Letra  (con movimiento)",         C_VERDE,    "1 mano"),
        ("[3]  Palabra / frase  (movimiento)",   C_AZUL,     "2 manos"),
        ("[4]  Palabra / frase  (pose + mov.)",  C_AMARILLO, "2 manos"),
        ("[5]  Animal / adjetivo / adverbio",    C_AZUL,     "2 manos"),
        ("[ESC] Volver",                         C_GRIS,     ""),
    ]
    cy = fh//2 - 170
    for txt, col, tag in grupos:
        put_text(frame, txt, (fw//2-260, cy), 0.6, col, 1)
        if tag:
            tag_col = C_VERDE if "1" in tag else C_NARANJA
            draw_badge(frame, tag, fw//2+80, cy, tag_col)
        cy += 58

def pantalla_mano_captura(frame):
    fh, fw = frame.shape[:2]
    draw_panel(frame, 0, 0, fw, 70)
    put_text(frame, "¿Con qué mano vas a hacer esta seña?", (20, 42), 0.85, C_AMARILLO, 2)

    draw_panel(frame, fw//2-260, fh//2-130, 520, 260)
    put_text(frame, "[D]  Mano DERECHA", (fw//2-220, fh//2-60), 0.75, C_VERDE, 1)
    put_text(frame, "[I]  Mano IZQUIERDA", (fw//2-220, fh//2-10), 0.75, C_NARANJA, 1)
    put_text(frame, "[ESC] Volver", (fw//2-220, fh//2+50), 0.6, C_GRIS)
    put_text(frame,
             "Esto define contra qué lado del JSON se comparará esta seña",
             (fw//2-220, fh//2+110), 0.42, C_GRIS)

def pantalla_nombre(frame):
    fh, fw = frame.shape[:2]
    dos = estado["dos_manos"]
    draw_panel(frame, 0, 0, fw, 70)
    put_text(frame, "Ingresa el nombre de la seña", (20, 42), 0.8, C_AMARILLO, 2)
    draw_badge(frame, "2 manos" if dos else "1 mano",
               fw-140, 42, C_NARANJA if dos else C_VERDE)
    if not dos and estado["mano_captura"]:
        draw_badge(frame, f"Mano: {estado['mano_captura'].capitalize()}", fw-140, 68,
                   C_VERDE if estado["mano_captura"] == "DERECHA" else C_NARANJA)

    draw_panel(frame, fw//2-260, fh//2-130, 520, 280)
    put_text(frame, "Nombre / etiqueta:", (fw//2-240, fh//2-90), 0.6, C_GRIS)
    inp = estado["input_text"] + "|"
    cv2.rectangle(frame, (fw//2-240, fh//2-50), (fw//2+240, fh//2), (50,50,50), -1)
    cv2.rectangle(frame, (fw//2-240, fh//2-50), (fw//2+240, fh//2), C_AMARILLO, 1)
    put_text(frame, inp, (fw//2-230, fh//2-14), 0.9, C_BLANCO, 2)

    put_text(frame, f"Muestras a capturar: {estado['num_muestras']}   [+ / -]",
             (fw//2-240, fh//2+40), 0.6, C_TEAL, 1)
    put_text(frame, "[`] Insertar Ñ", (fw//2-240, fh//2+65), 0.45, C_GRIS)
    put_text(frame, "[ENTER] Continuar    [ESC] Volver",
             (fw//2-200, fh//2+90), 0.5, C_GRIS)

def pantalla_capturando(frame, mano_der, mano_izq):
    fh, fw = frame.shape[:2]
    tipo   = estado["tipo"]
    dos    = estado["dos_manos"]
    label  = estado["etiqueta"]
    n_act  = len(estado["muestras"]) + 1
    total  = estado["num_muestras"]
    n_aum  = len(estado["muestras_aumentadas"])

    # Header
    draw_panel(frame, 0, 0, fw, 70)
    put_text(frame, f"Capturando: {label}", (20, 42), 1.0, C_AMARILLO, 2)
    draw_badge(frame, "2 manos" if dos else "1 mano",
               fw-130, 28, C_NARANJA if dos else C_VERDE)
    draw_badge(frame, tipo.upper(), fw-130, 55, C_AZUL)
    if not dos and estado["mano_captura"]:
        draw_badge(frame, f"Mano: {estado['mano_captura']}", 20, 95,
                   C_VERDE if estado["mano_captura"] == "DERECHA" else C_NARANJA)

    # Panel lateral
    draw_panel(frame, fw-265, 80, 255, 350, 0.6)
    put_text(frame, "Progreso (reales)", (fw-250, 108), 0.55, C_GRIS)
    draw_progress(frame, n_act-1, total, fw-250, 120)
    put_text(frame, f"Muestra {n_act} de {total}", (fw-250, 165), 0.55, C_BLANCO)
    if GENERAR_AUMENTADAS:
        put_text(frame, f"+ {n_aum} sintéticas generadas", (fw-250, 188), 0.45, C_TEAL)

    if tipo == "estatica":
        put_text(frame, "Mantén la pose fija",  (fw-250, 218), 0.48, C_GRIS)
        put_text(frame, "[SPACE] Capturar",      (fw-250, 248), 0.5,  C_VERDE)
        put_text(frame, "[ESC]   Cancelar",      (fw-250, 276), 0.5,  C_ROJO)
    else:
        put_text(frame, "Haz el movimiento",    (fw-250, 218), 0.48, C_GRIS)
        put_text(frame, "[SPACE] Confirmar",    (fw-250, 246), 0.5,  C_VERDE)
        put_text(frame, "[R]     Reiniciar",    (fw-250, 273), 0.5,  C_AMARILLO)
        put_text(frame, "[ESC]   Cancelar",     (fw-250, 300), 0.5,  C_ROJO)
        if tipo == "combinada":
            put_text(frame, "Termina en la pose", (fw-250, 326), 0.42, C_GRIS)

    # Indicador de manos detectadas
    if dos:
        col_d = C_VERDE if mano_der else C_ROJO
        col_i = C_VERDE if mano_izq else C_ROJO
        put_text(frame, "DER: " + ("OK" if mano_der else "--"), (20, fh-70), 0.6, col_d)
        put_text(frame, "IZQ: " + ("OK" if mano_izq else "--"), (130, fh-70), 0.6, col_i)
    else:
        mano_activa_ui = mano_der if mano_der else mano_izq
        col = C_VERDE if mano_activa_ui else C_ROJO
        lado = "DER" if mano_der else ("IZQ" if mano_izq else "--")
        put_text(frame, f"Mano ({lado}): " + ("OK" if mano_activa_ui else "--"), (20, fh-70), 0.6, col)

    # Trayectorias visualizadas
    if tipo in ("dinamica", "combinada"):
        draw_trayectoria(frame, estado["trayectoria_d"], C_ROJO,    C_AZUL,  2)
        if dos:
            draw_trayectoria(frame, estado["trayectoria_i"], C_NARANJA, C_TEAL, 2)
        pts_d = len(estado["trayectoria_d"])
        pts_i = len(estado["trayectoria_i"])
        if dos:
            ok = pts_d >= 8 and pts_i >= 8
            put_text(frame, f"Puntos  DER:{pts_d}  IZQ:{pts_i}",
                     (20, fh-40), 0.5, C_VERDE if ok else C_ROJO)
        else:
            put_text(frame, f"Puntos: {pts_d}",
                     (20, fh-40), 0.5, C_VERDE if pts_d >= 8 else C_ROJO)

    # Puntos clave coloreados por mano
    if dos:
        if mano_der:
            draw_landmarks_coloreado(frame, mano_der.landmark, C_VERDE)
        if mano_izq:
            draw_landmarks_coloreado(frame, mano_izq.landmark, C_NARANJA)
    else:
        mano_activa = mano_der if mano_der else mano_izq
        if mano_activa:
            draw_landmarks_coloreado(frame, mano_activa.landmark, C_VERDE)

def pantalla_reporte(frame):
    fh, fw = frame.shape[:2]
    r = estado["reporte"]
    draw_panel(frame, 0, 0, fw, fh, 0.78)
    put_text(frame, f"Resumen de captura: {estado['etiqueta']}", (30, 50), 0.9, C_AMARILLO, 2)

    cy = 100
    put_text(frame, f"Muestras reales: {r['n_reales']}   |   sintéticas: {r['n_aumentadas']}",
              (40, cy), 0.6, C_BLANCO)
    cy += 45

    if r["consistencia"] is not None:
        ok = r["consistencia_ok"]
        col = C_VERDE if ok else C_AMARILLO
        put_text(frame, f"Consistencia interna (pose): {r['consistencia']:.2f}",
                  (40, cy), 0.6, col)
        cy += 32
        if not ok:
            put_text(frame, "  → tus repeticiones variaron bastante; considera repetir la captura",
                      (40, cy), 0.48, C_AMARILLO)
            cy += 32

    if r["consistencia_dtw"] is not None:
        ok = r["consistencia_ok"]
        col = C_VERDE if ok else C_AMARILLO
        put_text(frame, f"Consistencia interna (movimiento, DTW): {r['consistencia_dtw']:.2f}",
                  (40, cy), 0.6, col)
        cy += 32
        if not ok:
            put_text(frame, "  → el movimiento no salió parecido entre repeticiones; considera repetir",
                      (40, cy), 0.48, C_AMARILLO)
            cy += 32

    cy += 10
    if r["confusion_con"]:
        put_text(frame, f"Posible confusión con: '{etiqueta_legible(r['confusion_con'])}'  (similitud {r['confusion_score']:.2f})",
                  (40, cy), 0.6, C_ROJO, 1)
        cy += 32
        put_text(frame, "  → revisa si ambas señas son lo bastante distintas para el sistema",
                  (40, cy), 0.48, C_ROJO)
    else:
        put_text(frame, "Sin conflictos detectados con otras señas guardadas", (40, cy), 0.6, C_VERDE)

    put_text(frame, "[ENTER] Continuar", (40, fh-40), 0.55, C_GRIS)

def pantalla_lista(frame):
    fh, fw = frame.shape[:2]
    draw_panel(frame, 0, 0, fw, fh, 0.75)
    put_text(frame, "Señas guardadas", (30, 45), 0.9, C_AMARILLO, 2)
    put_text(frame, "[ESC] Volver", (fw-180, 45), 0.5, C_GRIS)

    if not patrones:
        put_text(frame, "No hay señas aun.", (fw//2-100, fh//2), 0.7, C_GRIS)
        return

    cols  = 3
    col_w = (fw - 60) // cols
    for i, (key, val) in enumerate(patrones.items()):
        col = i % cols
        row = i // cols
        x   = 30 + col * col_w
        y   = 90 + row * 52
        if y > fh - 60:
            break
        tipo_str  = val.get("tipo", "?")
        manos     = val.get("manos", 1)
        muestras  = val.get("muestras", [])
        n_reales  = sum(1 for m in muestras if not m.get("sintetica"))
        n_sint    = len(muestras) - n_reales
        color     = C_VERDE if tipo_str == "estatica" else C_AZUL if tipo_str == "dinamica" else C_AMARILLO
        nombre    = etiqueta_legible(key)
        etiq      = f"{nombre}  [{tipo_str[0].upper()}{'×2m' if manos==2 else ''}  {n_reales}r+{n_sint}s]"
        draw_badge(frame, etiq, x, y, color)

def pantalla_borrar(frame):
    fh, fw = frame.shape[:2]
    draw_panel(frame, 0, 0, fw, 70)
    put_text(frame, "Escribe la etiqueta a borrar:", (20, 42), 0.8, C_ROJO, 2)
    inp = estado["input_text"] + "|"
    cv2.rectangle(frame, (fw//2-240, fh//2-20), (fw//2+240, fh//2+30), (50,50,50), -1)
    cv2.rectangle(frame, (fw//2-240, fh//2-20), (fw//2+240, fh//2+30), C_ROJO, 1)
    put_text(frame, inp, (fw//2-230, fh//2+16), 0.9, C_BLANCO, 2)
    put_text(frame, "[ENTER] Borrar    [ESC] Volver",
             (fw//2-180, fh//2+80), 0.5, C_GRIS)

def pantalla_test(frame, resultados_estaticas, mano_der, mano_izq):
    fh, fw = frame.shape[:2]
    draw_panel(frame, 0, 0, fw, 70)
    put_text(frame, "MODO PRUEBA  (no se guarda nada)", (20, 42), 0.9, C_TEAL, 2)
    put_text(frame, "[ESC] Salir", (fw-160, 42), 0.5, C_GRIS)

    # Panel de reconocimiento estático en vivo
    draw_panel(frame, 20, 90, 330, 170, 0.6)
    put_text(frame, "Pose actual — top 3", (35, 115), 0.55, C_GRIS)
    if resultados_estaticas:
        cy = 145
        for i, (nombre, sim) in enumerate(resultados_estaticas[:3]):
            col = C_VERDE if i == 0 and sim >= UMBRAL_CONFUSION_SIM * 0.85 else C_BLANCO
            put_text(frame, f"{i+1}. {nombre}   {sim:.2f}", (35, cy), 0.6, col, 1)
            cy += 32
    else:
        put_text(frame, "Sin coincidencias / sin mano visible", (35, 145), 0.5, C_GRIS)

    # Panel de prueba dinámica
    draw_panel(frame, fw-330, 90, 310, 170, 0.6)
    if estado["test_grabando"]:
        put_text(frame, "Grabando movimiento...", (fw-315, 115), 0.55, C_ROJO)
        put_text(frame, "[SPACE] Detener y clasificar", (fw-315, 145), 0.5, C_AMARILLO)
    else:
        put_text(frame, "Prueba de movimiento", (fw-315, 115), 0.55, C_GRIS)
        put_text(frame, "[SPACE] Iniciar grabación", (fw-315, 145), 0.5, C_VERDE)
    if estado["test_resultado"]:
        cy = 180
        for i, (nombre, dist) in enumerate(estado["test_resultado"][:3]):
            put_text(frame, f"{i+1}. {nombre}   d={dist:.2f}", (fw-315, cy), 0.55,
                      C_VERDE if i == 0 else C_BLANCO)
            cy += 27

    # Trayectoria en curso
    if estado["test_grabando"]:
        draw_trayectoria(frame, estado["trayectoria_d"], C_ROJO, C_AZUL, 2)
        draw_trayectoria(frame, estado["trayectoria_i"], C_NARANJA, C_TEAL, 2)

    if mano_der:
        draw_landmarks_coloreado(frame, mano_der.landmark, C_VERDE)
    if mano_izq:
        draw_landmarks_coloreado(frame, mano_izq.landmark, C_NARANJA)

# ════════════════════════════════════════════
#  CLASIFICACIÓN EN VIVO PARA EL MODO PRUEBA
# ════════════════════════════════════════════

def clasificar_estatica_en_vivo(mano_der, mano_izq):
    """Compara la pose actual contra todas las señas 'estatica'/'combinada'
    guardadas y regresa una lista [(etiqueta, similitud), ...] ordenada."""
    resultados = []

    # 1 mano
    mano_ref = mano_der if mano_der else mano_izq
    if mano_ref:
        vec_actual = pose_a_vector(extraer_pose(mano_ref.landmark))
        for k, v in patrones.items():
            if v.get("tipo") not in ("estatica", "combinada") or v.get("manos", 1) != 1:
                continue
            vecs = [vector_estatica_de_muestra(m, False) for m in v.get("muestras", [])
                    if not m.get("sintetica")]
            vecs = [x for x in vecs if x is not None]
            if not vecs:
                continue
            sim = max(cosine_similarity(vec_actual, x) for x in vecs)
            resultados.append((etiqueta_legible(k), sim))

    # 2 manos
    if mano_der and mano_izq:
        vec_der = pose_a_vector(extraer_pose(mano_der.landmark))
        vec_izq = pose_a_vector(extraer_pose(mano_izq.landmark))
        vec_actual = np.concatenate([vec_der, vec_izq])
        for k, v in patrones.items():
            if v.get("tipo") not in ("estatica", "combinada") or v.get("manos", 1) != 2:
                continue
            vecs = [vector_estatica_de_muestra(m, True) for m in v.get("muestras", [])
                    if not m.get("sintetica")]
            vecs = [x for x in vecs if x is not None]
            if not vecs:
                continue
            sim = max(cosine_similarity(vec_actual, x) for x in vecs)
            resultados.append((k, sim))

    resultados.sort(key=lambda t: t[1], reverse=True)
    return resultados

def clasificar_dinamica_test(traj_d, traj_i):
    """Clasifica una grabación de prueba (1 o 2 manos) contra todas las
    señas 'dinamica'/'combinada' guardadas, vía DTW. Regresa
    [(etiqueta, distancia), ...] ordenado ascendente (menor = mejor)."""
    dos = len(traj_d) >= 8 and len(traj_i) >= 8
    if dos:
        tr_d = normalizar_trayectoria(resamplear(traj_d, 30))
        tr_i = normalizar_trayectoria(resamplear(traj_i, 30))
    else:
        base = traj_d if len(traj_d) >= 8 else traj_i
        if len(base) < 8:
            return []
        tr_1 = normalizar_trayectoria(resamplear(base, 30))

    resultados = []
    for k, v in patrones.items():
        if v.get("tipo") not in ("dinamica", "combinada") or v.get("manos", 1) != (2 if dos else 1):
            continue
        mejor = None
        for m in v.get("muestras", []):
            if m.get("sintetica"):
                continue
            if dos:
                trs = trayectorias_de_muestra(m, True)
                if len(trs) != 2:
                    continue
                d = dtw_distancia(tr_d, trs[0]) + dtw_distancia(tr_i, trs[1])
            else:
                trs = trayectorias_de_muestra(m, False)
                if not trs:
                    continue
                d = dtw_distancia(tr_1, trs[0])
            if mejor is None or d < mejor:
                mejor = d
        if mejor is not None:
            resultados.append((etiqueta_legible(k), mejor))

    resultados.sort(key=lambda t: t[1])
    return resultados

# ════════════════════════════════════════════
#  MAIN LOOP
# ════════════════════════════════════════════

cargar_existente()

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame   = cv2.flip(frame, 1)
    fh, fw  = frame.shape[:2]
    rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands.process(rgb)

    mano_der = None
    mano_izq = None

    if results.multi_hand_landmarks:
        for hl in results.multi_hand_landmarks:
            mp_draw.draw_landmarks(
                frame, hl, mp_hands.HAND_CONNECTIONS,
                mp_draw.DrawingSpec(color=(80,80,80), thickness=1, circle_radius=2),
                mp_draw.DrawingSpec(color=(60,60,60), thickness=1)
            )

        mano_der, mano_izq = identificar_manos(
            results.multi_hand_landmarks,
            results.multi_handedness
        )

        # Acumular trayectorias — captura normal
        if estado["modo"] == "CAPTURANDO" and estado["tipo"] in ("dinamica", "combinada"):
            dos = estado["dos_manos"]
            if not dos:
                mano_activa = mano_der if mano_der else mano_izq
                if mano_activa:
                    pt = [mano_activa.landmark[DEDO_TRAYECTORIA].x,
                          mano_activa.landmark[DEDO_TRAYECTORIA].y]
                    estado["trayectoria_d"].append(pt)
            else:
                if mano_der:
                    pt = [mano_der.landmark[DEDO_TRAYECTORIA].x,
                          mano_der.landmark[DEDO_TRAYECTORIA].y]
                    estado["trayectoria_d"].append(pt)
                if mano_izq:
                    pt = [mano_izq.landmark[DEDO_TRAYECTORIA].x,
                          mano_izq.landmark[DEDO_TRAYECTORIA].y]
                    estado["trayectoria_i"].append(pt)

        # Acumular trayectorias — modo prueba
        if estado["modo"] == "TEST" and estado["test_grabando"]:
            if mano_der:
                pt = [mano_der.landmark[DEDO_TRAYECTORIA].x,
                      mano_der.landmark[DEDO_TRAYECTORIA].y]
                estado["trayectoria_d"].append(pt)
            if mano_izq:
                pt = [mano_izq.landmark[DEDO_TRAYECTORIA].x,
                      mano_izq.landmark[DEDO_TRAYECTORIA].y]
                estado["trayectoria_i"].append(pt)

    # Referencia para modo 1 mano
    mano_ref = mano_der if mano_der else mano_izq

    # Clasificación en vivo (solo en modo TEST, cuando no está grabando movimiento)
    resultados_test_estatica = []
    if estado["modo"] == "TEST" and not estado["test_grabando"]:
        resultados_test_estatica = clasificar_estatica_en_vivo(mano_der, mano_izq)

    # ── DIBUJAR ─────────────────────────────
    modo = estado["modo"]
    if   modo == "MENU":       pantalla_menu(frame)
    elif modo == "TIPO":       pantalla_tipo(frame)
    elif modo == "MANO_CAPTURA": pantalla_mano_captura(frame)
    elif modo == "NOMBRE":     pantalla_nombre(frame)
    elif modo == "CAPTURANDO": pantalla_capturando(frame, mano_der, mano_izq)
    elif modo == "REPORTE":    pantalla_reporte(frame)
    elif modo == "LISTA":      pantalla_lista(frame)
    elif modo == "BORRAR":     pantalla_borrar(frame)
    elif modo == "TEST":       pantalla_test(frame, resultados_test_estatica, mano_der, mano_izq)

    # ── FLASH ───────────────────────────────
    ahora_ms = int(time.time() * 1000)
    if estado["mensaje"] and ahora_ms < estado["msg_timer"]:
        draw_panel(frame, 0, fh-52, fw, 52, 0.7)
        put_text(frame, estado["mensaje"], (20, fh-18), 0.65,
                 estado.get("msg_color", C_VERDE), 1)
    elif ahora_ms >= estado["msg_timer"]:
        estado["mensaje"] = ""

    cv2.imshow("Capturador LSM v3", frame)

    # ════════════════════════════════════════
    #  TECLADO
    # ════════════════════════════════════════
    tecla = cv2.waitKey(1) & 0xFF

    if modo == "MENU":
        if   tecla == ord('n'):
            estado.update({"modo":"TIPO","muestras":[],"muestras_aumentadas":[],
                           "etiqueta":"","tipo":"","opcion":"","dos_manos":False,
                           "input_text":"","num_muestras":NUM_MUESTRAS_DEFAULT})
        elif tecla == ord('t'):
            estado.update({"modo":"TEST","trayectoria_d":[],"trayectoria_i":[],
                           "test_grabando":False,"test_resultado":None})
        elif tecla == ord('l'): estado["modo"] = "LISTA"
        elif tecla == ord('e'): guardar()
        elif tecla == ord('b'):
            estado["modo"] = "BORRAR"
            estado["input_text"] = ""
        elif tecla == 27: break

    elif modo == "TIPO":
        map_tipo = {'1':'estatica','2':'dinamica','3':'dinamica',
                    '4':'combinada','5':'dinamica'}
        c = chr(tecla) if 0 <= tecla <= 127 else ""
        if c in map_tipo:
            estado["tipo"]         = map_tipo[c]
            estado["opcion"]       = c
            estado["dos_manos"]    = c in TIPO_2_MANOS
            estado["mano_captura"] = None
            estado["input_text"]   = ""
            if c in TIPO_1_MANO:
                estado["modo"] = "MANO_CAPTURA"
            else:
                estado["modo"] = "NOMBRE"
        elif tecla == 27:
            estado["modo"] = "MENU"

    elif modo == "MANO_CAPTURA":
        if   tecla == ord('d'):
            estado["mano_captura"] = "DERECHA"
            estado["modo"] = "NOMBRE"
        elif tecla == ord('i'):
            estado["mano_captura"] = "IZQUIERDA"
            estado["modo"] = "NOMBRE"
        elif tecla == 27:
            estado["modo"] = "TIPO"

    elif modo == "NOMBRE":
        if tecla == 13:
            nombre = estado["input_text"].strip()
            if nombre:
                estado.update({"etiqueta":nombre,"modo":"CAPTURANDO",
                               "muestras":[],"muestras_aumentadas":[],
                               "trayectoria_d":[],"trayectoria_i":[]})
                mstr = "2 manos" if estado["dos_manos"] else "1 mano"
                flash(f"Capturando '{nombre}'  —  {estado['tipo']}  [{mstr}]", C_AMARILLO)
            else:
                flash("Escribe un nombre primero", C_ROJO)
        elif tecla == 27:
            estado["modo"] = "MANO_CAPTURA" if not estado["dos_manos"] else "TIPO"
        elif tecla == 8:  estado["input_text"] = estado["input_text"][:-1]
        elif tecla in (ord('+'), ord('=')):
            estado["num_muestras"] = min(NUM_MUESTRAS_MAX, estado["num_muestras"] + NUM_MUESTRAS_PASO)
        elif tecla == ord('-'):
            estado["num_muestras"] = max(NUM_MUESTRAS_MIN, estado["num_muestras"] - NUM_MUESTRAS_PASO)
        elif tecla == 96:  # ` (acento grave) — OpenCV no puede leer la Ñ
            estado["input_text"] += "Ñ"          # directamente del teclado; se usa este atajo
        elif 32 <= tecla <= 126: estado["input_text"] += chr(tecla)

    elif modo == "CAPTURANDO":
        tipo = estado["tipo"]
        dos  = estado["dos_manos"]

        if tecla == 27:
            estado["modo"] = "MENU"
            estado["muestras"] = []
            estado["muestras_aumentadas"] = []
            flash("Captura cancelada", C_ROJO)

        elif tecla == ord('r') and tipo in ("dinamica","combinada"):
            estado["trayectoria_d"] = []
            estado["trayectoria_i"] = []
            flash("Trayectorias reiniciadas", C_AMARILLO)

        elif tecla == ord(' '):
            muestra = {}

            # ── ESTÁTICA ──────────────────────
            if tipo == "estatica":
                if not dos:
                    if mano_ref is None:
                        flash("No se detecta mano", C_ROJO)
                    else:
                        muestra = {"pose": extraer_pose(mano_ref.landmark), "sintetica": False}
                else:
                    if mano_der is None or mano_izq is None:
                        flash(f"Falta mano {'derecha' if mano_der is None else 'izquierda'}", C_ROJO)
                    else:
                        muestra = {"pose_der": extraer_pose(mano_der.landmark),
                                   "pose_izq": extraer_pose(mano_izq.landmark),
                                   "sintetica": False}

            # ── DINÁMICA ──────────────────────
            elif tipo == "dinamica":
                traj_d = estado["trayectoria_d"]
                traj_i = estado["trayectoria_i"]
                if not dos:
                    if len(traj_d) < 8:
                        flash("Movimiento muy corto, intenta de nuevo", C_ROJO)
                        estado["trayectoria_d"] = []
                    else:
                        tr = resamplear(traj_d, 30)
                        muestra = {"trayectoria": normalizar_trayectoria(tr), "sintetica": False} if tr else {}
                        if not tr: flash("Error al procesar trayectoria", C_ROJO)
                        estado["trayectoria_d"] = []
                else:
                    if len(traj_d) < 8 or len(traj_i) < 8:
                        flash(f"Movimiento corto — {'DER' if len(traj_d)<8 else 'IZQ'}", C_ROJO)
                        estado["trayectoria_d"] = []
                        estado["trayectoria_i"] = []
                    else:
                        tr_d = resamplear(traj_d, 30)
                        tr_i = resamplear(traj_i, 30)
                        if tr_d and tr_i:
                            muestra = {"trayectoria_der": normalizar_trayectoria(tr_d),
                                       "trayectoria_izq": normalizar_trayectoria(tr_i),
                                       "sintetica": False}
                        else:
                            flash("Error al procesar trayectorias", C_ROJO)
                        estado["trayectoria_d"] = []
                        estado["trayectoria_i"] = []

            # ── COMBINADA ─────────────────────
            elif tipo == "combinada":
                traj_d = estado["trayectoria_d"]
                traj_i = estado["trayectoria_i"]
                if not dos:
                    if len(traj_d) < 8:
                        flash("Movimiento muy corto", C_ROJO)
                        estado["trayectoria_d"] = []
                    elif mano_ref is None:
                        flash("No se detecta mano al final", C_ROJO)
                    else:
                        tr = resamplear(traj_d, 30)
                        if tr:
                            muestra = {"trayectoria": normalizar_trayectoria(tr),
                                       "pose": extraer_pose(mano_ref.landmark),
                                       "sintetica": False}
                        else:
                            flash("Error al procesar", C_ROJO)
                        estado["trayectoria_d"] = []
                else:
                    if len(traj_d) < 8 or len(traj_i) < 8:
                        flash("Movimiento corto en alguna mano", C_ROJO)
                        estado["trayectoria_d"] = []
                        estado["trayectoria_i"] = []
                    elif mano_der is None or mano_izq is None:
                        flash("Necesito ver ambas manos al final", C_ROJO)
                    else:
                        tr_d = resamplear(traj_d, 30)
                        tr_i = resamplear(traj_i, 30)
                        if tr_d and tr_i:
                            muestra = {
                                "trayectoria_der": normalizar_trayectoria(tr_d),
                                "trayectoria_izq": normalizar_trayectoria(tr_i),
                                "pose_der": extraer_pose(mano_der.landmark),
                                "pose_izq": extraer_pose(mano_izq.landmark),
                                "sintetica": False,
                            }
                        else:
                            flash("Error al procesar trayectorias", C_ROJO)
                        estado["trayectoria_d"] = []
                        estado["trayectoria_i"] = []

            # ── GUARDAR MUESTRA REAL + GENERAR AUMENTADAS ──
            if muestra:
                estado["muestras"].append(muestra)
                if GENERAR_AUMENTADAS:
                    estado["muestras_aumentadas"].extend(
                        generar_muestra_aumentada(muestra, tipo, dos)
                    )

                n_act = len(estado["muestras"])
                total = estado["num_muestras"]
                flash(f"Muestra {n_act}/{total} guardada  ✓", C_VERDE)

                if n_act >= total:
                    label = estado["etiqueta"]
                    reales     = estado["muestras"]
                    aumentadas = estado["muestras_aumentadas"]

                    clave = clave_json(label, dos, estado["mano_captura"])
                    reporte = evaluar_calidad(clave, tipo, dos, reales)
                    reporte["n_reales"]     = len(reales)
                    reporte["n_aumentadas"] = len(aumentadas)

                    patrones[clave] = {
                        "tipo"    : tipo,
                        "manos"   : 2 if dos else 1,
                        "muestras": reales + aumentadas,
                    }
                    guardar()

                    estado["reporte"] = reporte
                    estado["modo"]    = "REPORTE"
                    estado["muestras"] = []
                    estado["muestras_aumentadas"] = []
                else:
                    estado["trayectoria_d"] = []
                    estado["trayectoria_i"] = []

    elif modo == "REPORTE":
        if tecla in (13, 27):
            estado["modo"] = "MENU"
            estado["reporte"] = None

    elif modo == "LISTA":
        if tecla == 27: estado["modo"] = "MENU"

    elif modo == "BORRAR":
        if tecla == 13:
            nombre = estado["input_text"].strip()
            if nombre in patrones:
                del patrones[nombre]
                guardar()
                flash(f"'{nombre}' eliminado", C_ROJO)
            else:
                flash(f"No existe: '{nombre}'", C_ROJO)
            estado["modo"] = "MENU"
        elif tecla == 27: estado["modo"] = "MENU"
        elif tecla == 8:  estado["input_text"] = estado["input_text"][:-1]
        elif 32 <= tecla <= 126: estado["input_text"] += chr(tecla)

    elif modo == "TEST":
        if tecla == 27:
            estado["modo"] = "MENU"
            estado["trayectoria_d"] = []
            estado["trayectoria_i"] = []
            estado["test_grabando"] = False
            estado["test_resultado"] = None
        elif tecla == ord(' '):
            if not estado["test_grabando"]:
                estado["trayectoria_d"] = []
                estado["trayectoria_i"] = []
                estado["test_grabando"] = True
                estado["test_resultado"] = None
            else:
                estado["test_grabando"] = False
                estado["test_resultado"] = clasificar_dinamica_test(
                    estado["trayectoria_d"], estado["trayectoria_i"]
                )
                if not estado["test_resultado"]:
                    flash("Movimiento muy corto o sin señas dinámicas guardadas", C_ROJO)

cap.release()
cv2.destroyAllWindows()

print(f"\nArchivo exportado: {ARCHIVO_SALIDA}")
print(f"Total de señas: {len(patrones)}")
for k, v in patrones.items():
    manos    = v.get("manos", 1)
    muestras = v.get("muestras", [])
    n_reales = sum(1 for m in muestras if not m.get("sintetica"))
    n_sint   = len(muestras) - n_reales
    print(f"  {etiqueta_legible(k):20s}  tipo={v['tipo']:10s}  manos={manos}  reales={n_reales}  sinteticas={n_sint}")