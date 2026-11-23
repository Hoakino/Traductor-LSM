/*
 * Click nbfs://nbhost/SystemFileSystem/Templates/Licenses/license-default.txt to change this license
 * Click nbfs://nbhost/SystemFileSystem/Templates/GUIForms/JFrame.java to edit this template
 */
package com.mycompany.traductorlsm;
import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.io.*;
import javax.imageio.ImageIO;
import org.json.JSONObject;
import java.io.PrintWriter;
import java.net.Socket;
import java.awt.KeyboardFocusManager;


/**
 *
 * @author joaqu
 */
public class TraductorLSM extends javax.swing.JFrame {
  
    
    private String manoActual = "DERECHA";
    private Socket           socket;
    private DataInputStream  entrada;
    private Thread           hiloSocket;
    private volatile boolean corriendo = false;
    private String textoDetectado   = "";   // letras acumuladas
    //private String ultimaLetraRecibida = "";
    private Process procesoPython;
    private String modoActual = "ABECEDARIO";
    private java.util.Timer timerTraduccion = null;
    
//
//private void reproducirBienvenida() {
//    try {
////        // La ruta debe coincidir exactamente con tu paquete
////        java.net.URL url = getClass().getResource("/resources/Imagenes/v1.wav");
////        
//        if (url != null) {
//            javax.sound.sampled.AudioInputStream audioStream = javax.sound.sampled.AudioSystem.getAudioInputStream(url);
//            javax.sound.sampled.Clip clip = javax.sound.sampled.AudioSystem.getClip();
//            clip.open(audioStream);
//            clip.start();
//        } else {
//            System.err.println("¡Error! No se encontró el archivo bienvenida.wav en la ruta especificada.");
//        }
//    } catch (Exception e) {
//        System.err.println("Error al reproducir el audio: " + e.getMessage());
//    }
//}
    
 

    /**
     * Creates new form TraductorLSM
     */
    public TraductorLSM() {
        initComponents();
        // 1. Definimos el tipo de letra (Georgia se adapta muy bien y viene en todas las PC)
// El tamaño 24 lo puedes cambiar según el espacio que tengas en tu diseño
java.awt.Font fuenteBienestar = new java.awt.Font("Georgia", java.awt.Font.BOLD, 18);
jLabelBienestar.setFont(fuenteBienestar);

// 2. Aplicamos el color Guinda Institucional exacto (RGB: 159, 34, 65)
jLabelBienestar.setForeground(new java.awt.Color(19, 46, 112));

// 3. Escribimos el texto tal cual (en MAYÚSCULAS)
jLabelBienestar.setText("TECNM");
        
        
        
        
        try {
            try {
    // === ANUNCIO 1 ===
    // 1. Buscamos la imagen del primer anuncio (cambia 'anuncio1.png' por el nombre de tu archivo)
    java.net.URL urlAnuncio1 = getClass().getResource("/resources/Imagenes/logo2.png");
    if (urlAnuncio1 != null) {
        ImageIcon icon1 = new ImageIcon(urlAnuncio1);
        // Se acopla al tamaño exacto que le diste al jLabelAnuncio1 en el diseño
        Image img1 = icon1.getImage().getScaledInstance(jLabelAnuncio1.getWidth(), jLabelAnuncio1.getHeight(), Image.SCALE_SMOOTH);
        jLabelAnuncio1.setIcon(new ImageIcon(img1));
        jLabelAnuncio1.setText(""); // Borra el texto por defecto
    }

    // === ANUNCIO 2 ===
    // 2. Buscamos la imagen del segundo anuncio (cambia 'anuncio2.png')
    java.net.URL urlAnuncio2 = getClass().getResource("/resources/Imagenes/anun2 - copia.png");
    if (urlAnuncio2 != null) {
        ImageIcon icon2 = new ImageIcon(urlAnuncio2);
        // Se acopla al tamaño exacto que le diste al jLabelAnuncio2 en el diseño
//        Image img2 = icon2.getImage().getScaledInstance(jLabelAnuncio2.getWidth(), jLabelAnuncio2.getHeight(), Image.SCALE_SMOOTH);
//        jLabelAnuncio2.setIcon(new ImageIcon(img2));
//        jLabelAnuncio2.setText(""); // Borra el texto por defecto
    }

} catch (Exception e) {
    System.out.println("Error al cargar los anuncios: " + e.getMessage());
}
    // Si la imagen está en esa ruta, la cargará
    java.net.URL imgUrl = getClass().getResource("/resources/Imagenes/marca.png");
    
    if (imgUrl != null) {
        ImageIcon original = new ImageIcon(imgUrl);
        // Ajuste automático al tamaño del Label
        Image escalada = original.getImage().getScaledInstance(jLabel4.getWidth(), jLabel4.getHeight(), Image.SCALE_SMOOTH);
        jLabel4.setIcon(new ImageIcon(escalada));
        jLabel4.setText(""); 
    } else {
        System.out.println("Error: No se encontró el archivo marca.png en la ruta especificada.");
    }
} catch (Exception e) {
    System.out.println("Error: " + e.getMessage());
}

        
        
        
        
        
        
        configurarUI();
        lanzarPython();
        iniciarConexion();
//        reproducirBienvenida();
        
        try {
            setIconImage(new javax.swing.ImageIcon(getClass().getResource("/Imagenes/mano.png")).getImage());
        } catch (Exception e) {
            System.err.println("No se pudo cargar el icono: " + e.getMessage());
        }
        
        
        
        
        Borrar_Letra.addActionListener(e -> borrarUltimaLetra());
        Borrar_Todo.addActionListener(e -> borrarTodo());
        
        
        String Texo= "Cambiar\n Modo";
          Modo.setText("<html><center>" + Texo.replace("\n", "<br>") + "</center></html");
        String Texo2= "Borrar\n Todo";
          Borrar_Todo.setText("<html><center>" + Texo2.replace("\n", "<br>") + "</center></html");
        
  
    }
    
    private void configurarUI() {
        // Camara_Señas: fondo negro mientras no hay frame
        Camara_Señas.setBackground(Color.BLACK);
        Camara_Señas.setOpaque(true);
        Camara_Señas.setHorizontalAlignment(SwingConstants.CENTER);
        Camara_Señas.setText("Esperando conexión con Python...");
        Camara_Señas.setForeground(Color.WHITE);

        // TextAreas: no editables desde teclado
        Deteccion.setEditable(false);
        Tradu_Deteccion.setEditable(false);

        // Fuentes
        Deteccion.setFont(new Font("Monospaced", Font.PLAIN, 18));
        Tradu_Deteccion.setFont(new Font("Monospaced", Font.PLAIN, 16));
        
        // Tecla retroceso para borrar última letra
            KeyboardFocusManager.getCurrentKeyboardFocusManager()
                .addKeyEventDispatcher(e -> {
                    if (e.getID() == java.awt.event.KeyEvent.KEY_PRESSED
                            && e.getKeyCode() == java.awt.event.KeyEvent.VK_BACK_SPACE) {
                        borrarUltimaLetra();
                        return true;
                    }
                    return false;
                });
        

        addWindowListener(new java.awt.event.WindowAdapter() {
    @Override
    public void windowClosing(java.awt.event.WindowEvent e) {
        corriendo = false;
        cerrarSocket();
        if (procesoPython != null) {
            // Matar Python Y todos sus procesos hijos
            procesoPython.toHandle()
                .descendants()
                .forEach(ProcessHandle::destroy);
            procesoPython.destroyForcibly();
            try {
                procesoPython.waitFor();
            } catch (InterruptedException ignored) {}
        }
        System.exit(0);
        }
    });
    // Borrar con tecla Retroceso
    KeyStroke backspace = KeyStroke.getKeyStroke(java.awt.event.KeyEvent.VK_BACK_SPACE, 0);
    getRootPane().getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW).put(backspace, "borrar");
    getRootPane().getActionMap().put("borrar", new javax.swing.AbstractAction() {
        @Override
        public void actionPerformed(java.awt.event.ActionEvent e) {
            borrarUltimaLetra();
        }
    });
    
    
    
    
    
    
}
    
//    
//        // ── Conexión socket en hilo separado ────────────────────
//    private void iniciarConexion() {
//        corriendo = true;
//        hiloSocket = new Thread(() -> {
//            while (corriendo) {
//                try {
//                    actualizarEstado("Conectando con Python en localhost:9999...");
//                    socket  = new Socket("localhost",9999);
//                    entrada = new DataInputStream(new BufferedInputStream(socket.getInputStream()));
//                    actualizarEstado("Conectado");  
//                    textoDetectado = "";
//                    SwingUtilities.invokeLater(() -> {
//                    Deteccion.setText("");
//                    Tradu_Deteccion.setText("");
//                    });
//
//                    while (corriendo) {
//                        // ── Leer frame JPEG ──────────────────
//                        int tamFrame = entrada.readInt();
//                        byte[] frameBytes = leerBytes(tamFrame);
//
//                        // ── Leer JSON ────────────────────────
//                        int tamJson = entrada.readInt();
//                        byte[] jsonBytes = leerBytes(tamJson);
//
//                        // ── Parsear ──────────────────────────
//                        String jsonStr = new String(jsonBytes, "UTF-8");
//                        JSONObject obj = new JSONObject(jsonStr);
//
//                        String letra    = obj.optString("letra", "");
//                        String texto    = obj.optString("texto", "");
//                        double confianza = obj.optDouble("confianza", 0.0);
//                        
//                        //if (!letra.isEmpty()) {
//                        //  System.out.println("Detectado: " + letra);
//                        //}
//
//                        // ── Actualizar texto detectado ───────
//                        if (!texto.equals(textoDetectado)) {
//                            textoDetectado = texto;
//                            SwingUtilities.invokeLater(() ->
//                                Deteccion.setText(textoDetectado));
//                        }
//
//                        // ── Actualizar imagen ────────────────
//                        BufferedImage img = ImageIO.read(
//                            new ByteArrayInputStream(frameBytes));
//                        if (img != null) {
//                            Image scaled = img.getScaledInstance(
//                                Camara_Señas.getWidth(),
//                                Camara_Señas.getHeight(),
//                                Image.SCALE_FAST);
//                            SwingUtilities.invokeLater(() -> {
//                                Camara_Señas.setIcon(new ImageIcon(scaled));
//                                Camara_Señas.setText("");
//                            });
//                        }
//                        if (!texto.equals(textoDetectado)) {
//                        textoDetectado = texto;
//                        SwingUtilities.invokeLater(() -> Deteccion.setText(textoDetectado));
//
//                        // Traducción con delay
//                        if (timerTraduccion != null) timerTraduccion.cancel();
//                        String snapTexto = texto;
//                        timerTraduccion = new java.util.Timer();
//                        timerTraduccion.schedule(new java.util.TimerTask() {
//                            @Override
//                            public void run() {
//                                String traduccion = traducirTexto(snapTexto);
//                                SwingUtilities.invokeLater(() -> Tradu_Deteccion.setText(traduccion));
//                            }
//                        }, 800);
//                    }
//                    
//                        
//                    }
//
//                } catch (Exception ex) {
//                    cerrarSocket();
//                    actualizarEstado("Conectando Espere");
//                    try { Thread.sleep(1000); } catch (InterruptedException ignored) {}
//                }
//                
//            }
//        }, "hilo-socket");
//        hiloSocket.setDaemon(true);
//        hiloSocket.start();
//    }
    
    private void iniciarConexion() {
    corriendo = true;
    hiloSocket = new Thread(() -> {
        while (corriendo) {
            try {
                actualizarEstado("Conectando con Python en localhost:9999...");
                socket  = new Socket("localhost", 9999);
                entrada = new DataInputStream(new BufferedInputStream(socket.getInputStream()));
                actualizarEstado("Conectado");
                textoDetectado = "";
                SwingUtilities.invokeLater(() -> {
                    Deteccion.setText("");
                    Tradu_Deteccion.setText("");
                });

                while (corriendo) {
                    // ── Leer frame JPEG ──────────────────
                    int tamFrame = entrada.readInt();
                    byte[] frameBytes = leerBytes(tamFrame);

                    // ── Leer JSON ────────────────────────
                    int tamJson = entrada.readInt();
                    byte[] jsonBytes = leerBytes(tamJson);

                    // ── Parsear ──────────────────────────
                    String jsonStr = new String(jsonBytes, "UTF-8");
                    JSONObject obj = new JSONObject(jsonStr);

                    String letra    = obj.optString("letra", "");
                    String texto    = obj.optString("texto", "");
                    double confianza = obj.optDouble("confianza", 0.0);

                    // ── Actualizar texto + traducción ────
                    if (!texto.equals(textoDetectado)) {
                        textoDetectado = texto;
                        SwingUtilities.invokeLater(() -> Deteccion.setText(textoDetectado));

                        // Cancelar timer anterior y lanzar uno nuevo
                        if (timerTraduccion != null) timerTraduccion.cancel();
                        String snapTexto = texto;
                        timerTraduccion = new java.util.Timer();
                        timerTraduccion.schedule(new java.util.TimerTask() {
                            @Override
                            public void run() {
                                String traduccion = traducirTexto(snapTexto);
                                SwingUtilities.invokeLater(() -> Tradu_Deteccion.setText(traduccion));
                            }
                        }, 800);
                    }

                    // ── Actualizar imagen de cámara ──────
                    BufferedImage img = ImageIO.read(new ByteArrayInputStream(frameBytes));
                    if (img != null) {
                        Image scaled = img.getScaledInstance(
                            Camara_Señas.getWidth(),
                            Camara_Señas.getHeight(),
                            Image.SCALE_FAST);
                        SwingUtilities.invokeLater(() -> {
                            Camara_Señas.setIcon(new ImageIcon(scaled));
                            Camara_Señas.setText("");
                        });
                    }
                }

            } catch (Exception ex) {
                cerrarSocket();
                actualizarEstado("Conectando Espere");
                try { Thread.sleep(1000); } catch (InterruptedException ignored) {}
            }
        }
    }, "hilo-socket");
    hiloSocket.setDaemon(true);
    hiloSocket.start();
}
    
private String traducirTexto(String texto) {
    System.out.println("[TRADUCCION] Traduciendo: " + texto);
    if (texto == null || texto.trim().isEmpty()) return "";
    try {
        String encoded = java.net.URLEncoder.encode(texto.trim(), "UTF-8");
        java.net.URL url = new java.net.URL(
            "https://translate.googleapis.com/translate_a/single?client=gtx&sl=es&tl=en&dt=t&q=" + encoded
        );
        java.net.HttpURLConnection con = (java.net.HttpURLConnection) url.openConnection();
        con.setRequestMethod("GET");
        con.setConnectTimeout(5000);
        con.setReadTimeout(5000);

        BufferedReader br = new BufferedReader(
            new InputStreamReader(con.getInputStream(), "UTF-8"));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) sb.append(line);
        br.close();

        // Google regresa algo como: [[["hello","hola",...],...],...]
        String respuesta = sb.toString();
        System.out.println("[TRADUCCION] Respuesta: " + respuesta);
        
        // Extraer el texto traducido del primer elemento
        org.json.JSONArray arr = new org.json.JSONArray(respuesta);
        org.json.JSONArray inner = arr.getJSONArray(0).getJSONArray(0);
        String traduccion = inner.getString(0);
        System.out.println("[TRADUCCION] Resultado: " + traduccion);
        return traduccion;

    } catch (Exception e) {
        System.out.println("[TRADUCCION] ERROR: " + e.getMessage());
        return "";
    }
}
    
//private void lanzarPython() {
//    try {
//        ProcessBuilder pb = new ProcessBuilder(
//            "C:\\Users\\joaqu\\AppData\\Local\\Programs\\Python\\Python310\\python.exe",
//            "C:\\Users\\joaqu\\Documents\\LENGUAJE DE SEÑAS\\BACKEND_V4.py"
//        );
//        pb.directory(new java.io.File("C:\\Users\\joaqu\\Documents\\LENGUAJE DE SEÑAS"));
//
//        pb.redirectErrorStream(true);
//
//        procesoPython = pb.start();
//
//        // VER LOG DE PYTHON (MUY IMPORTANTE)
//        BufferedReader reader = new BufferedReader(
//            new InputStreamReader(procesoPython.getInputStream())
//        );
//
//        new Thread(() -> {
//            try {
//                String line;
//                while ((line = reader.readLine()) != null) {
//                    System.out.println("[PYTHON] " + line);
//                }
//            } catch (IOException e) {
//                e.printStackTrace();
//            }
//        }).start();
//
//        System.out.println("Python iniciado correctamente");
//
//    } catch (IOException e) {
//        System.err.println("Error al iniciar Python: " + e.getMessage());
//    }
//}
//private void lanzarPython() {
//    try {
//        // Obtiene la raíz del proyecto sin importar en qué máquina corra
//        File projectDir = new File(System.getProperty("user.dir"));
//        File scriptDir  = new File(projectDir, "python");
//        File script     = new File(scriptDir, "BACKEND_V4.py");
//
//        System.out.println("Buscando script en: " + script.getAbsolutePath()); // ← para debug
//
//        ProcessBuilder pb = new ProcessBuilder(
//            "python",
//            script.getAbsolutePath()
//        );
//        pb.directory(scriptDir);
//        pb.redirectErrorStream(true);
//
//        procesoPython = pb.start();
//
//        BufferedReader reader = new BufferedReader(
//            new InputStreamReader(procesoPython.getInputStream())
//        );
//        new Thread(() -> {
//            try {
//                String line;
//                while ((line = reader.readLine()) != null) {
//                    System.out.println("[PYTHON] " + line);
//                }
//            } catch (IOException e) {
//                e.printStackTrace();
//            }
//        }).start();
//
//        System.out.println("Python iniciado correctamente");
//
//    } catch (IOException e) {
//        System.err.println("Error al iniciar Python: " + e.getMessage());
//    }
//}
//    
private void lanzarPython() {
    try {
        File projectDir = new File(System.getProperty("user.dir"));
        File scriptDir  = new File(projectDir, "python");
        File script     = new File(scriptDir, "BACKEND_V4.py");

        ProcessBuilder pb = new ProcessBuilder("python", script.getAbsolutePath());
        pb.directory(scriptDir);
        pb.redirectErrorStream(true);
        procesoPython = pb.start();

        // ← ESTA PARTE ES LA QUE FALTABA
        BufferedReader reader = new BufferedReader(
            new InputStreamReader(procesoPython.getInputStream())
        );
        new Thread(() -> {
            try {
                String line;
                while ((line = reader.readLine()) != null) {
                    System.out.println("[PYTHON] " + line);
                }
            } catch (IOException e) {
                e.printStackTrace();
            }
        }).start();

        System.out.println("Python iniciado correctamente");

    } catch (IOException e) {
        System.err.println("Error al iniciar Python: " + e.getMessage());
    }
}   
    
      // ── Lee exactamente n bytes del stream ──────────────────
    private byte[] leerBytes(int n) throws IOException {
        byte[] buf = new byte[n];
        int leidos = 0;
        while (leidos < n) {
            int r = entrada.read(buf, leidos, n - leidos);
            if (r == -1) throw new IOException("Stream cerrado");
            leidos += r;
        }
        return buf;
    }

    // ── Actualiza el label de cámara con un mensaje de estado
    private void actualizarEstado(String msg) {
        SwingUtilities.invokeLater(() -> {
            Camara_Señas.setIcon(null);
            Camara_Señas.setText(msg);
            Camara_Señas.setForeground(Color.LIGHT_GRAY);
        });
    }

    private void cerrarSocket() {
        try { if (socket != null) socket.close(); } catch (Exception ignored) {}
    }

    // ── Acciones de botones ─────────────────────────────────
    private void borrarUltimaLetra() {
        enviarComando("BORRAR_LETRA");
    }

    private void borrarTodo() {
        enviarComando("BORRAR_TODO");
    }

    private void enviarComando(String comando) {
    try {
        Socket cmd = new Socket("localhost", 9998);
        PrintWriter pw = new PrintWriter(cmd.getOutputStream(), true);
        pw.println(comando);
        cmd.close();
    } catch (Exception e) {
        System.out.println("Error enviando comando: " + e.getMessage());
    }
}
    
    

        




    /**
     * This method is called from within the constructor to initialize the form.
     * WARNING: Do NOT modify this code. The content of this method is always
     * regenerated by the Form Editor.
     */
    @SuppressWarnings("unchecked")
    // <editor-fold defaultstate="collapsed" desc="Generated Code">//GEN-BEGIN:initComponents
    private void initComponents() {

        Camara_Señas = new javax.swing.JLabel();
        Borrar_Letra = new javax.swing.JButton();
        Borrar_Todo = new javax.swing.JButton();
        jLabel1 = new javax.swing.JLabel();
        jScrollPane1 = new javax.swing.JScrollPane();
        Deteccion = new javax.swing.JTextArea();
        jScrollPane2 = new javax.swing.JScrollPane();
        Tradu_Deteccion = new javax.swing.JTextArea();
        Modo = new javax.swing.JButton();
        Voz_Es = new javax.swing.JButton();
        Voz_May = new javax.swing.JButton();
        Ayuda = new javax.swing.JToggleButton();
        Seleccion_Traduccion = new javax.swing.JComboBox<>();
        Select_Mano = new javax.swing.JComboBox<>();
        jLabelBienestar = new javax.swing.JLabel();
        jLabelAnuncio1 = new javax.swing.JLabel();
        jLabel4 = new javax.swing.JLabel();
        jLabel3 = new javax.swing.JLabel();
        jLabel2 = new javax.swing.JLabel();
        jLabel5 = new javax.swing.JLabel();

        setDefaultCloseOperation(javax.swing.WindowConstants.EXIT_ON_CLOSE);
        getContentPane().setLayout(new org.netbeans.lib.awtextra.AbsoluteLayout());

        Camara_Señas.setBorder(javax.swing.BorderFactory.createLineBorder(new java.awt.Color(0, 0, 153), 2));
        getContentPane().add(Camara_Señas, new org.netbeans.lib.awtextra.AbsoluteConstraints(266, 57, 423, 245));

        Borrar_Letra.setBackground(new java.awt.Color(153, 153, 153));
        Borrar_Letra.setForeground(new java.awt.Color(255, 255, 255));
        Borrar_Letra.setIcon(new javax.swing.ImageIcon(getClass().getResource("/resources/Imagenes/backspace_outline_icon_139934.png"))); // NOI18N
        Borrar_Letra.setText("Borrar");
        Borrar_Letra.setBorder(new javax.swing.border.MatteBorder(null));
        Borrar_Letra.addActionListener(new java.awt.event.ActionListener() {
            public void actionPerformed(java.awt.event.ActionEvent evt) {
                Borrar_LetraActionPerformed(evt);
            }
        });
        getContentPane().add(Borrar_Letra, new org.netbeans.lib.awtextra.AbsoluteConstraints(395, 333, 146, 44));

        Borrar_Todo.setBackground(new java.awt.Color(153, 153, 153));
        Borrar_Todo.setForeground(new java.awt.Color(255, 255, 255));
        Borrar_Todo.setIcon(new javax.swing.ImageIcon(getClass().getResource("/resources/Imagenes/erase_icon_160907.png"))); // NOI18N
        Borrar_Todo.setText("Borrar Todo");
        getContentPane().add(Borrar_Todo, new org.netbeans.lib.awtextra.AbsoluteConstraints(395, 392, 146, 53));

        jLabel1.setFont(new java.awt.Font("Franklin Gothic Heavy", 0, 24)); // NOI18N
        jLabel1.setForeground(new java.awt.Color(0, 0, 153));
        jLabel1.setText("TRADUCTOR LSM");
        getContentPane().add(jLabel1, new org.netbeans.lib.awtextra.AbsoluteConstraints(380, 8, 206, -1));

        Deteccion.setBackground(new java.awt.Color(204, 204, 204));
        Deteccion.setColumns(20);
        Deteccion.setRows(5);
        jScrollPane1.setViewportView(Deteccion);

        getContentPane().add(jScrollPane1, new org.netbeans.lib.awtextra.AbsoluteConstraints(46, 333, 304, 210));

        Tradu_Deteccion.setBackground(new java.awt.Color(204, 204, 204));
        Tradu_Deteccion.setColumns(20);
        Tradu_Deteccion.setRows(5);
        jScrollPane2.setViewportView(Tradu_Deteccion);

        getContentPane().add(jScrollPane2, new org.netbeans.lib.awtextra.AbsoluteConstraints(560, 333, 310, 210));

        Modo.setBackground(new java.awt.Color(153, 153, 153));
        Modo.setForeground(new java.awt.Color(255, 255, 255));
        Modo.setIcon(new javax.swing.ImageIcon(getClass().getResource("/resources/Imagenes/twocirclingarrows1_120592.png"))); // NOI18N
        Modo.setText("Cambiar modo");
        Modo.addActionListener(new java.awt.event.ActionListener() {
            public void actionPerformed(java.awt.event.ActionEvent evt) {
                ModoActionPerformed(evt);
            }
        });
        getContentPane().add(Modo, new org.netbeans.lib.awtextra.AbsoluteConstraints(395, 463, 150, 43));

        Voz_Es.setBackground(new java.awt.Color(204, 204, 204));
        Voz_Es.setIcon(new javax.swing.ImageIcon(getClass().getResource("/resources/Imagenes/Audio (2).png"))); // NOI18N
        Voz_Es.addActionListener(new java.awt.event.ActionListener() {
            public void actionPerformed(java.awt.event.ActionEvent evt) {
                Voz_EsActionPerformed(evt);
            }
        });
        getContentPane().add(Voz_Es, new org.netbeans.lib.awtextra.AbsoluteConstraints(312, 555, -1, -1));

        Voz_May.setBackground(new java.awt.Color(204, 204, 204));
        Voz_May.setIcon(new javax.swing.ImageIcon(getClass().getResource("/resources/Imagenes/Audio (2).png"))); // NOI18N
        Voz_May.addActionListener(new java.awt.event.ActionListener() {
            public void actionPerformed(java.awt.event.ActionEvent evt) {
                Voz_MayActionPerformed(evt);
            }
        });
        getContentPane().add(Voz_May, new org.netbeans.lib.awtextra.AbsoluteConstraints(560, 555, -1, -1));

        Ayuda.setIcon(new javax.swing.ImageIcon(getClass().getResource("/resources/Imagenes/help-outline_119052.png"))); // NOI18N
        Ayuda.setText("Ayuda");
        Ayuda.addMouseListener(new java.awt.event.MouseAdapter() {
            public void mouseClicked(java.awt.event.MouseEvent evt) {
                AyudaMouseClicked(evt);
            }
        });
        Ayuda.addActionListener(new java.awt.event.ActionListener() {
            public void actionPerformed(java.awt.event.ActionEvent evt) {
                AyudaActionPerformed(evt);
            }
        });
        getContentPane().add(Ayuda, new org.netbeans.lib.awtextra.AbsoluteConstraints(830, 10, -1, -1));

        Seleccion_Traduccion.setBackground(new java.awt.Color(204, 204, 204));
        Seleccion_Traduccion.setModel(new javax.swing.DefaultComboBoxModel<>(new String[] { "Ingles", "Maya" }));
        getContentPane().add(Seleccion_Traduccion, new org.netbeans.lib.awtextra.AbsoluteConstraints(790, 560, 82, -1));

        Select_Mano.setBackground(new java.awt.Color(204, 204, 204));
        Select_Mano.setModel(new javax.swing.DefaultComboBoxModel<>(new String[] { "Derecha", "Izquierda" }));
        Select_Mano.addMouseListener(new java.awt.event.MouseAdapter() {
            public void mouseClicked(java.awt.event.MouseEvent evt) {
                Select_ManoMouseClicked(evt);
            }
        });
        Select_Mano.addActionListener(new java.awt.event.ActionListener() {
            public void actionPerformed(java.awt.event.ActionEvent evt) {
                Select_ManoActionPerformed(evt);
            }
        });
        getContentPane().add(Select_Mano, new org.netbeans.lib.awtextra.AbsoluteConstraints(46, 555, 80, -1));

        jLabelBienestar.setForeground(new java.awt.Color(0, 0, 153));
        jLabelBienestar.setText("jLabel6");
        getContentPane().add(jLabelBienestar, new org.netbeans.lib.awtextra.AbsoluteConstraints(80, 70, 260, 110));

        jLabelAnuncio1.setText("jLabel6");
        getContentPane().add(jLabelAnuncio1, new org.netbeans.lib.awtextra.AbsoluteConstraints(750, 0, 70, 60));

        jLabel4.setText("jLabel4");
        getContentPane().add(jLabel4, new org.netbeans.lib.awtextra.AbsoluteConstraints(0, 0, 170, 60));

        jLabel3.setBackground(new java.awt.Color(204, 204, 204));
        jLabel3.setOpaque(true);
        getContentPane().add(jLabel3, new org.netbeans.lib.awtextra.AbsoluteConstraints(0, -10, 930, 660));

        jLabel2.setIcon(new javax.swing.ImageIcon(getClass().getResource("/resources/Imagenes/qwqe.png"))); // NOI18N
        getContentPane().add(jLabel2, new org.netbeans.lib.awtextra.AbsoluteConstraints(750, 560, -1, 50));

        jLabel5.setText("jLabel5");
        getContentPane().add(jLabel5, new org.netbeans.lib.awtextra.AbsoluteConstraints(20, 20, 190, 130));

        pack();
    }// </editor-fold>//GEN-END:initComponents

    private void ModoActionPerformed(java.awt.event.ActionEvent evt) {//GEN-FIRST:event_ModoActionPerformed
       try {
        // IMPORTANTE: Python espera MAYÚSCULAS
        modoActual = modoActual.equals("ABECEDARIO") ? "VOCABULARIO" : "ABECEDARIO";

        Socket cmd = new Socket("localhost", 9998);
        PrintWriter pw = new PrintWriter(cmd.getOutputStream(), true);
        pw.println("MODO:" + modoActual);
        cmd.close();

        // Texto del botón en formato legible
        String etiqueta = modoActual.equals("ABECEDARIO") ? "Abecedario" : "Vocabulario";
        String texto = "Cambiar\n" + etiqueta;
        Modo.setText("<html><center>" + texto.replace("\n", "<br>") + "</center></html>");

    } catch (Exception e) {
        System.out.println("Error al cambiar modo: " + e.getMessage());
    
    }
        reproducirSonido("Cambiando modo - copia (2).wav");
        
    }//GEN-LAST:event_ModoActionPerformed

    private void AyudaMouseClicked(java.awt.event.MouseEvent evt) {//GEN-FIRST:event_AyudaMouseClicked
        // TODO add your handling code here:
        Ayuda ayudita = new Ayuda();
        ayudita.setVisible(true);
    }//GEN-LAST:event_AyudaMouseClicked

    private void Select_ManoMouseClicked(java.awt.event.MouseEvent evt) {//GEN-FIRST:event_Select_ManoMouseClicked
        // TODO add your handling code here
    }//GEN-LAST:event_Select_ManoMouseClicked

    private void Select_ManoActionPerformed(java.awt.event.ActionEvent evt) {//GEN-FIRST:event_Select_ManoActionPerformed
        // TODO add your handling code here:
        
    try {
        String seleccion = (String) Select_Mano.getSelectedItem();
        manoActual = seleccion.equals("Derecha") ? "DERECHA" : "IZQUIERDA";

        Socket cmd = new Socket("localhost", 9998);
        PrintWriter pw = new PrintWriter(cmd.getOutputStream(), true);
        pw.println("MANO:" + manoActual);
        cmd.close();

    } catch (Exception e) {
        System.out.println("Error al cambiar mano: " + e.getMessage());
    }
    }//GEN-LAST:event_Select_ManoActionPerformed

    private void Borrar_LetraActionPerformed(java.awt.event.ActionEvent evt) {//GEN-FIRST:event_Borrar_LetraActionPerformed
        
    }//GEN-LAST:event_Borrar_LetraActionPerformed

    private void AyudaActionPerformed(java.awt.event.ActionEvent evt) {//GEN-FIRST:event_AyudaActionPerformed
        // TODO add your handling code here:
    }//GEN-LAST:event_AyudaActionPerformed

    private void Voz_EsActionPerformed(java.awt.event.ActionEvent evt) {//GEN-FIRST:event_Voz_EsActionPerformed
                                      
    try {
        // 1. Obtenemos el texto limpiando saltos de línea
        String textoALeer = Deteccion.getText().replace("\n", " ").trim();
        
        // Si está vacío, le ponemos un texto por defecto para probar que el motor funciona
        if (textoALeer.isEmpty()) {
            textoALeer = "No hay texto para leer";
        }

        // 2. Comando corregido usando comillas simples para PowerShell
        String comando = "Add-Type -AssemblyName System.Speech; " +
                         "$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; " +
                         "$speak.Speak('" + textoALeer + "');";
        
        // 3. Arrancamos el proceso
        ProcessBuilder builder = new ProcessBuilder("powershell.exe", "-Command", comando);
        builder.start();
        
    } catch (Exception e) {
        System.err.println("Error al reproducir el texto: " + e.getMessage());
    }
    }//GEN-LAST:event_Voz_EsActionPerformed

    private void Voz_MayActionPerformed(java.awt.event.ActionEvent evt) {//GEN-FIRST:event_Voz_MayActionPerformed
      try {
    // 1. Obtenemos el texto del cuadro DERECHO (Cámbiale el nombre si tu variable no es 'EagleTextArea')
    // Nota: Revisa en tu diseño cómo se llama exactamente el cuadro de la derecha.
    String textoALeer = Tradu_Deteccion.getText().replace("\n", " ").trim();
    
    if (textoALeer.isEmpty()) {
        textoALeer = "No text to read";
    }

    // 2. Comando para PowerShell forzando la voz en Inglés usando un filtro de lenguaje (en-US / en-GB)
    String comando = "Add-Type -AssemblyName System.Speech; " +
                     "$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; " +
                     "$voice = $speak.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'en' } | Select-Object -First 1; " +
                     "if ($voice) { $speak.SelectVoice($voice.VoiceInfo.Name); } " +
                     "$speak.Speak('" + textoALeer + "');";
    
    // 3. Arrancamos el proceso
    ProcessBuilder builder = new ProcessBuilder("powershell.exe", "-Command", comando);
    builder.start();
    
} catch (Exception e) {
    System.err.println("Error al reproducir el texto en inglés: " + e.getMessage());
}
    }//GEN-LAST:event_Voz_MayActionPerformed

    /**
     * @param args the command line arguments
     */
public static void main(String args[]) {
        try {
            for (javax.swing.UIManager.LookAndFeelInfo info : javax.swing.UIManager.getInstalledLookAndFeels()) {
                if ("Nimbus".equals(info.getName())) {
                    javax.swing.UIManager.setLookAndFeel(info.getClassName());
                    break;
                }
            }
        } catch (Exception ex) {
            java.util.logging.Logger.getLogger(TraductorLSM.class.getName())
                .log(java.util.logging.Level.SEVERE, null, ex);
        }

        java.awt.EventQueue.invokeLater(() -> new TraductorLSM().setVisible(true));
    }


    // Variables declaration - do not modify//GEN-BEGIN:variables
    private javax.swing.JToggleButton Ayuda;
    private javax.swing.JButton Borrar_Letra;
    private javax.swing.JButton Borrar_Todo;
    private javax.swing.JLabel Camara_Señas;
    private javax.swing.JTextArea Deteccion;
    private javax.swing.JButton Modo;
    private javax.swing.JComboBox<String> Seleccion_Traduccion;
    private javax.swing.JComboBox<String> Select_Mano;
    private javax.swing.JTextArea Tradu_Deteccion;
    private javax.swing.JButton Voz_Es;
    private javax.swing.JButton Voz_May;
    private javax.swing.JLabel jLabel1;
    private javax.swing.JLabel jLabel2;
    private javax.swing.JLabel jLabel3;
    private javax.swing.JLabel jLabel4;
    private javax.swing.JLabel jLabel5;
    private javax.swing.JLabel jLabelAnuncio1;
    private javax.swing.JLabel jLabelBienestar;
    private javax.swing.JScrollPane jScrollPane1;
    private javax.swing.JScrollPane jScrollPane2;
    // End of variables declaration//GEN-END:variables

class FondoDegradado extends javax.swing.JPanel {
    @Override
    protected void paintComponent(java.awt.Graphics g) {
        super.paintComponent(g);
        java.awt.Graphics2D g2d = (java.awt.Graphics2D) g;
        int width = getWidth();
        int height = getHeight();

        // Color inicial (Arriba) y Color final (Abajo)
        java.awt.Color color1 = new java.awt.Color(44, 62, 80);  // Azul grisáceo
        java.awt.Color color2 = new java.awt.Color(20, 20, 20);  // Casi negro
        
        java.awt.GradientPaint gp = new java.awt.GradientPaint(0, 0, color1, 0, height, color2);
        g2d.setPaint(gp);
        g2d.fillRect(0, 0, width, height);
    }
}


public void reproducirSonido(String nombreArchivo) {
    try {
        java.net.URL url = getClass().getResource("/resources/Imagenes/" + nombreArchivo);
        javax.sound.sampled.AudioInputStream audioIn = javax.sound.sampled.AudioSystem.getAudioInputStream(url);
        javax.sound.sampled.Clip clip = javax.sound.sampled.AudioSystem.getClip();
        clip.open(audioIn);
        clip.start();
    } catch (Exception e) {
        System.err.println("Error al reproducir sonido: " + e.getMessage());
    }
}

}
