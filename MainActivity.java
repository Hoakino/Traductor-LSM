package com.example.lsm;

import android.Manifest;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.util.Size;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;

import com.google.common.util.concurrent.ListenableFuture;
import com.google.mediapipe.framework.image.MPImage;
import com.google.mediapipe.framework.image.BitmapImageBuilder;
import com.google.mediapipe.tasks.core.BaseOptions;
import com.google.mediapipe.tasks.vision.core.ImageProcessingOptions;
import com.google.mediapipe.tasks.vision.core.RunningMode;
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarker;
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarkerResult;

import org.json.JSONArray;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends AppCompatActivity {
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService cameraExecutor = Executors.newSingleThreadExecutor();
    private final ExecutorService translationExecutor = Executors.newSingleThreadExecutor();
    private final StringBuilder recognizedText = new StringBuilder();

    private PreviewView previewView;
    private TextView statusView, modeView, currentSignView, textView, translationView;
    private Button modeButton;
    private volatile String mode = SignRecognizer.ALPHABET;
    private SignRecognizer recognizer;
    private HandLandmarker handLandmarker;
    private TextToSpeech textToSpeech;
    private long translationSequence = 0;
    private ActivityResultLauncher<String> cameraPermission;
    private volatile List<float[]> liveLandmarks = Collections.emptyList();
    private final List<float[][]> capturedSamples = new ArrayList<>();
    private final List<float[]> dynamicCapture = new ArrayList<>();
    private volatile boolean recordingDynamic = false;
    private long lastHandHintAt = 0;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildScreen();
        cameraPermission = registerForActivityResult(new ActivityResultContracts.RequestPermission(), granted -> {
            if (granted) startCamera();
            else status("Permite el acceso a la cámara para traducir señas.");
        });

        try {
            recognizer = new SignRecognizer(this);
            initializeHandLandmarker();
            status("Reconocimiento listo. Coloca una mano frente a la cámara.");
        } catch (Exception e) {
            status("No se pudo cargar el reconocedor: " + e.getMessage());
        }

        textToSpeech = new TextToSpeech(this, result -> {
            if (result == TextToSpeech.SUCCESS) textToSpeech.setLanguage(new Locale("es", "MX"));
        });
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
            startCamera();
        else cameraPermission.launch(Manifest.permission.CAMERA);
    }

    private void buildScreen() {
        int navy = Color.rgb(23, 45, 91), blue = Color.rgb(43, 91, 165), pale = Color.rgb(242, 246, 252);
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(18), dp(18), dp(18), dp(20));
        page.setBackgroundColor(pale);
        scroll.addView(page);

        TextView title = new TextView(this);
        title.setText("TRADUCTOR LSM"); title.setTextColor(navy); title.setTextSize(24); title.setGravity(Gravity.CENTER);
        title.setTypeface(null, android.graphics.Typeface.BOLD);
        page.addView(title, new LinearLayout.LayoutParams(-1, dp(42)));
        modeView = label("Modo: Abecedario", 15, blue, true);
        page.addView(modeView, margin(-1, dp(28), 0, 6));

        previewView = new PreviewView(this);
        previewView.setScaleType(PreviewView.ScaleType.FILL_CENTER);
        previewView.setImplementationMode(PreviewView.ImplementationMode.COMPATIBLE);
        previewView.setBackgroundColor(Color.BLACK);
        page.addView(previewView, margin(-1, dp(265), 0, 10));
        statusView = label("Preparando cámara…", 14, Color.DKGRAY, false);
        page.addView(statusView, margin(-1, -2, 0, 8));

        currentSignView = label("—", 32, navy, true);
        currentSignView.setBackgroundColor(Color.WHITE);
        page.addView(currentSignView, margin(-1, dp(58), 0, 8));
        page.addView(label("SEÑA DETECTADA", 12, Color.GRAY, true), margin(-1, dp(20), 0, 4));

        page.addView(label("Texto", 14, navy, true), margin(-1, dp(24), 0, 2));
        textView = label("", 22, Color.rgb(35, 42, 55), false);
        textView.setGravity(Gravity.TOP | Gravity.START);
        textView.setMinHeight(dp(60)); textView.setBackgroundColor(Color.WHITE); textView.setPadding(dp(12), dp(10), dp(12), dp(10));
        page.addView(textView, margin(-1, -2, 0, 8));

        page.addView(label("Traducción al inglés", 14, navy, true), margin(-1, dp(24), 0, 2));
        translationView = label("", 20, Color.rgb(35, 42, 55), false);
        translationView.setMinHeight(dp(50)); translationView.setBackgroundColor(Color.WHITE); translationView.setPadding(dp(12), dp(10), dp(12), dp(10));
        page.addView(translationView, margin(-1, -2, 0, 10));

        LinearLayout row = new LinearLayout(this); row.setOrientation(LinearLayout.HORIZONTAL);
        modeButton = button("Cambiar modo", blue);
        modeButton.setOnClickListener(v -> changeMode());
        row.addView(modeButton, weighted());
        Button clearLast = button("Borrar letra", navy);
        clearLast.setOnClickListener(v -> deleteLast());
        row.addView(clearLast, weighted());
        page.addView(row, margin(-1, dp(48), 0, 8));

        LinearLayout row2 = new LinearLayout(this); row2.setOrientation(LinearLayout.HORIZONTAL);
        Button clearAll = button("Borrar todo", navy);
        clearAll.setOnClickListener(v -> clearText());
        row2.addView(clearAll, weighted());
        Button speakSpanish = button("🔊 Español", blue);
        speakSpanish.setOnClickListener(v -> speak(recognizedText.toString(), new Locale("es", "MX")));
        row2.addView(speakSpanish, weighted());
        Button speakEnglish = button("🔊 English", blue);
        speakEnglish.setOnClickListener(v -> speak(translationView.getText().toString(), Locale.ENGLISH));
        row2.addView(speakEnglish, weighted());
        page.addView(row2, margin(-1, dp(48), 0, 8));

        Button help = button("Ayuda", Color.rgb(90, 103, 124));
        help.setOnClickListener(v -> new androidx.appcompat.app.AlertDialog.Builder(this)
                .setTitle("Cómo usar el traductor")
                .setMessage("Muestra una mano con buena iluminación y mantén la seña estable un instante. Cada seña estable se agrega al texto. En Abecedario se forman palabras letra por letra; en Vocabulario se separan las señas con espacios. Usa los botones para cambiar modo, borrar texto o escuchar las frases.")
                .setPositiveButton("Entendido", null).show());
        page.addView(help, margin(-1, dp(44), 0, 4));
        Button addSign = button("Agregar seña", Color.rgb(43, 91, 165));
        addSign.setOnClickListener(v -> showAddSignDialog());
        page.addView(addSign, margin(-1, dp(48), 0, 4));
        setContentView(scroll);
    }

    private void initializeHandLandmarker() throws Exception {
        BaseOptions baseOptions = BaseOptions.builder().setModelAssetPath("hand_landmarker.task").build();
        HandLandmarker.HandLandmarkerOptions options = HandLandmarker.HandLandmarkerOptions.builder()
                .setBaseOptions(baseOptions).setRunningMode(RunningMode.IMAGE).setNumHands(2)
                .setMinHandDetectionConfidence(0.65f).setMinHandPresenceConfidence(0.55f)
                .setMinTrackingConfidence(0.55f).build();
        handLandmarker = HandLandmarker.createFromOptions(this, options);
    }

    private void startCamera() {
        if (handLandmarker == null || recognizer == null) return;
        status("Abriendo cámara…");
        ListenableFuture<ProcessCameraProvider> future = ProcessCameraProvider.getInstance(this);
        future.addListener(() -> {
            try {
                ProcessCameraProvider provider = future.get();
                Preview preview = new Preview.Builder().build();
                preview.setSurfaceProvider(previewView.getSurfaceProvider());
                ImageAnalysis analysis = new ImageAnalysis.Builder().setTargetResolution(new Size(640, 480))
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888).build();
                analysis.setAnalyzer(cameraExecutor, this::analyzeFrame);
                CameraSelector selector = CameraSelector.DEFAULT_FRONT_CAMERA;
                provider.unbindAll();
                provider.bindToLifecycle(this, selector, preview, analysis);
                status("Cámara lista. Mantén la seña estable para agregarla.");
            } catch (Exception e) { status("No se pudo abrir la cámara: " + e.getMessage()); }
        }, ContextCompat.getMainExecutor(this));
    }

    private void analyzeFrame(@NonNull ImageProxy imageProxy) {
        MPImage mpImage = null;
        Bitmap frameBitmap = null;
        try {
            if (handLandmarker == null || recognizer == null) return;
            frameBitmap = rgbaFrameToBitmap(imageProxy);
            mpImage = new BitmapImageBuilder(frameBitmap).build();
            ImageProcessingOptions processing = ImageProcessingOptions.builder()
                    .setRotationDegrees(imageProxy.getImageInfo().getRotationDegrees()).build();
            HandLandmarkerResult result = handLandmarker.detect(mpImage, processing);
            List<float[]> points = new ArrayList<>(21);
            if (!result.landmarks().isEmpty()) {
                for (var landmark : result.landmarks().get(0)) {
                    // Match the desktop frontend, which flips the camera frame before inference.
                    points.add(new float[]{1f - landmark.x(), landmark.y()});
                }
                List<float[]> live = new ArrayList<>(points.size());
                for (float[] point : points) live.add(point.clone());
                liveLandmarks = Collections.unmodifiableList(live);
                float[] tip = points.get(8);
                synchronized (dynamicCapture) {
                    if (recordingDynamic) dynamicCapture.add(tip.clone());
                }
            } else {
                liveLandmarks = Collections.emptyList();
                long now = android.os.SystemClock.elapsedRealtime();
                if (now - lastHandHintAt > 1800) {
                    lastHandHintAt = now;
                    status("No detecto una mano. Centra la mano completa frente a la cámara.");
                }
            }
            SignRecognizer.Recognition prediction = recognizer.recognize(points, mode);
            String commit = recognizer.consumeStable(mode);
            if (points.size() == 21 && prediction.label.isEmpty()) {
                long now = android.os.SystemClock.elapsedRealtime();
                if (now - lastHandHintAt > 1800) {
                    lastHandHintAt = now;
                    status("Mano detectada; seña sin coincidencia. Agrégala con «Agregar seña».");
                }
            }
            mainHandler.post(() -> {
                currentSignView.setText(prediction.label.isEmpty() ? "—" : prediction.label);
                currentSignView.setTextColor(prediction.label.isEmpty() ? Color.GRAY : Color.rgb(26, 130, 79));
                if (!commit.isEmpty()) appendSign(commit);
            });
        } catch (Exception e) {
            mainHandler.post(() -> status("Error de reconocimiento: " + e.getMessage()));
        } finally {
            if (mpImage != null) mpImage.close();
            if (frameBitmap != null) frameBitmap.recycle();
            imageProxy.close();
        }
    }

    /** CameraX RGBA bytes are converted to Android's ARGB_8888 bitmap format. */
    private Bitmap rgbaFrameToBitmap(ImageProxy image) {
        ImageProxy.PlaneProxy plane = image.getPlanes()[0];
        ByteBuffer buffer = plane.getBuffer();
        int bufferStart = buffer.position();
        int width = image.getWidth();
        int height = image.getHeight();
        int rowStride = plane.getRowStride();
        int pixelStride = plane.getPixelStride();
        int[] pixels = new int[width * height];
        for (int y = 0; y < height; y++) {
            int rowStart = bufferStart + y * rowStride;
            for (int x = 0; x < width; x++) {
                int offset = rowStart + x * pixelStride;
                int red = buffer.get(offset) & 0xff;
                int green = buffer.get(offset + 1) & 0xff;
                int blue = buffer.get(offset + 2) & 0xff;
                int alpha = buffer.get(offset + 3) & 0xff;
                pixels[y * width + x] = Color.argb(alpha, red, green, blue);
            }
        }
        return Bitmap.createBitmap(pixels, width, height, Bitmap.Config.ARGB_8888);
    }

    private void showAddSignDialog() {
        if (recognizer == null) {
            Toast.makeText(this, "El reconocedor no está listo.", Toast.LENGTH_SHORT).show();
            return;
        }
        synchronized (capturedSamples) { capturedSamples.clear(); }
        synchronized (dynamicCapture) { dynamicCapture.clear(); }
        recordingDynamic = false;

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(22), dp(8), dp(22), dp(4));
        EditText labelInput = new EditText(this);
        labelInput.setSingleLine(true);
        labelInput.setHint("Nombre o letra de la seña");
        content.addView(labelInput, margin(-1, dp(54), 0, 6));

        Spinner modeSpinner = spinner(new String[]{"Abecedario", "Vocabulario"});
        modeSpinner.setSelection(SignRecognizer.ALPHABET.equals(mode) ? 0 : 1);
        content.addView(label("Guardar en modo", 14, Color.DKGRAY, true));
        content.addView(modeSpinner, margin(-1, dp(52), 0, 4));

        Spinner typeSpinner = spinner(new String[]{"Estática (pose fija)", "Dinámica (movimiento)"});
        content.addView(label("Tipo de seña", 14, Color.DKGRAY, true));
        content.addView(typeSpinner, margin(-1, dp(52), 0, 4));
        TextView counter = label("Muestras: 0/5", 14, Color.rgb(43, 91, 165), true);
        content.addView(counter, margin(-1, dp(28), 0, 2));
        TextView instructions = label("Estática: coloca la mano y pulsa Capturar muestra cinco veces. Dinámica: inicia la grabación, realiza la seña, detenla y repite cinco veces.", 13, Color.DKGRAY, false);
        content.addView(instructions, margin(-1, -2, 0, 6));

        Button capture = button("Capturar muestra", Color.rgb(43, 91, 165));
        content.addView(capture, margin(-1, dp(48), 0, 2));
        final androidx.appcompat.app.AlertDialog dialog = new androidx.appcompat.app.AlertDialog.Builder(this)
                .setTitle("Agregar seña propia")
                .setView(content)
                .setNegativeButton("Cancelar", (d, w) -> recordingDynamic = false)
                .setPositiveButton("Guardar", null)
                .create();

        capture.setOnClickListener(v -> {
            boolean dynamic = typeSpinner.getSelectedItemPosition() == 1;
            if (!dynamic) {
                List<float[]> landmarks = liveLandmarks;
                if (landmarks.size() < 21) {
                    Toast.makeText(this, "Primero coloca una mano frente a la cámara.", Toast.LENGTH_SHORT).show();
                    return;
                }
                int[] indices = {4, 8, 12, 16, 20, 6, 10, 14, 18};
                float[][] pose = new float[indices.length][2];
                for (int i = 0; i < indices.length; i++) pose[i] = landmarks.get(indices[i]).clone();
                synchronized (capturedSamples) { capturedSamples.add(pose); }
                updateCaptureCounter(counter, false);
            } else if (!recordingDynamic) {
                synchronized (dynamicCapture) { dynamicCapture.clear(); }
                recordingDynamic = true;
                capture.setText("Detener y guardar muestra");
                Toast.makeText(this, "Haz el movimiento ahora.", Toast.LENGTH_SHORT).show();
            } else {
                recordingDynamic = false;
                capture.setText("Grabar siguiente muestra");
                float[][] path;
                synchronized (dynamicCapture) {
                    path = dynamicCapture.toArray(new float[0][]);
                    dynamicCapture.clear();
                }
                if (path.length < 10) {
                    Toast.makeText(this, "No hubo suficientes cuadros con la mano visible; intenta de nuevo.", Toast.LENGTH_LONG).show();
                } else {
                    synchronized (capturedSamples) { capturedSamples.add(path); }
                    updateCaptureCounter(counter, true);
                }
            }
        });

        dialog.setOnShowListener(ignored -> dialog.getButton(androidx.appcompat.app.AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String sign = labelInput.getText().toString().trim();
            List<float[][]> samples;
            synchronized (capturedSamples) { samples = new ArrayList<>(capturedSamples); }
            if (sign.isEmpty() || samples.size() < 5) {
                Toast.makeText(this, "Escribe el nombre y captura al menos cinco muestras.", Toast.LENGTH_LONG).show();
                return;
            }
            try {
                String selectedMode = modeSpinner.getSelectedItemPosition() == 0
                        ? SignRecognizer.ALPHABET : SignRecognizer.VOCABULARY;
                String selectedType = typeSpinner.getSelectedItemPosition() == 0 ? "pose" : "trayectoria";
                recognizer.saveCustomSign(this, sign, selectedMode, selectedType, samples);
                recordingDynamic = false;
                recognizer.reset();
                Toast.makeText(this, "Seña guardada con " + samples.size() + " muestras.", Toast.LENGTH_LONG).show();
                dialog.dismiss();
            } catch (Exception e) {
                Toast.makeText(this, "No se pudo guardar: " + e.getMessage(), Toast.LENGTH_LONG).show();
            }
        }));
        dialog.show();
    }

    private Spinner spinner(String[] entries) {
        Spinner spinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, Arrays.asList(entries));
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setAdapter(adapter);
        return spinner;
    }

    private void updateCaptureCounter(TextView counter, boolean dynamic) {
        int count;
        synchronized (capturedSamples) { count = capturedSamples.size(); }
        String note = dynamic ? " (muestra de movimiento)" : "";
        counter.setText("Muestras: " + count + "/5" + note);
    }

    private void appendSign(String sign) {
        if (recognizedText.length() > 0 && SignRecognizer.VOCABULARY.equals(mode)) recognizedText.append(' ');
        recognizedText.append(sign);
        textView.setText(recognizedText.toString());
        requestTranslation(recognizedText.toString());
    }

    private void requestTranslation(String text) {
        long request = ++translationSequence;
        translationView.setText("Traduciendo…");
        mainHandler.postDelayed(() -> translationExecutor.execute(() -> {
            String result = translate(text);
            mainHandler.post(() -> { if (request == translationSequence) translationView.setText(result); });
        }), 500);
    }

    private String translate(String text) {
        HttpURLConnection connection = null;
        try {
            String query = URLEncoder.encode(text, "UTF-8");
            connection = (HttpURLConnection) new URL("https://translate.googleapis.com/translate_a/single?client=gtx&sl=es&tl=en&dt=t&q=" + query).openConnection();
            connection.setConnectTimeout(5000); connection.setReadTimeout(5000);
            StringBuilder body = new StringBuilder();
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream(), StandardCharsets.UTF_8))) {
                String line; while ((line = reader.readLine()) != null) body.append(line);
            }
            JSONArray first = new JSONArray(body.toString()).getJSONArray(0);
            StringBuilder translated = new StringBuilder();
            for (int i = 0; i < first.length(); i++) {
                JSONArray segment = first.optJSONArray(i);
                if (segment != null && !segment.isNull(0)) translated.append(segment.optString(0));
            }
            return translated.toString();
        } catch (Exception ignored) { return "Sin conexión para traducir"; }
        finally { if (connection != null) connection.disconnect(); }
    }

    private void changeMode() {
        mode = SignRecognizer.ALPHABET.equals(mode) ? SignRecognizer.VOCABULARY : SignRecognizer.ALPHABET;
        modeView.setText("Modo: " + (SignRecognizer.ALPHABET.equals(mode) ? "Abecedario" : "Vocabulario"));
        modeButton.setText(SignRecognizer.ALPHABET.equals(mode) ? "Modo vocabulario" : "Modo abecedario");
        recognizer.reset(); clearText(); currentSignView.setText("—");
    }

    private void deleteLast() {
        if (recognizedText.length() > 0) {
            int end = recognizedText.length();
            if (SignRecognizer.VOCABULARY.equals(mode) && recognizedText.charAt(end - 1) == ' ') end--;
            int start = end - 1;
            if (SignRecognizer.VOCABULARY.equals(mode)) {
                start = recognizedText.lastIndexOf(" ", end - 1) + 1;
            }
            recognizedText.delete(start, recognizedText.length());
            textView.setText(recognizedText.toString());
            if (recognizedText.length() > 0) requestTranslation(recognizedText.toString());
            else { translationSequence++; translationView.setText(""); }
        }
        recognizer.reset();
    }

    private void clearText() {
        recognizedText.setLength(0); textView.setText(""); translationSequence++; translationView.setText("");
        if (recognizer != null) recognizer.reset();
    }

    private void speak(String text, Locale locale) {
        if (text == null || text.trim().isEmpty() || textToSpeech == null) return;
        textToSpeech.setLanguage(locale);
        textToSpeech.speak(text, TextToSpeech.QUEUE_FLUSH, null, "lsm-speech");
    }

    private void status(String message) { runOnUiThread(() -> { if (statusView != null) statusView.setText(message); }); }
    private TextView label(String text, int size, int color, boolean bold) {
        TextView view = new TextView(this); view.setText(text); view.setTextSize(size); view.setTextColor(color);
        if (bold) view.setTypeface(null, android.graphics.Typeface.BOLD);
        return view;
    }
    private Button button(String text, int color) {
        Button button = new Button(this); button.setText(text); button.setTextColor(Color.WHITE);
        button.setTextSize(12); button.setBackgroundTintList(android.content.res.ColorStateList.valueOf(color));
        button.setAllCaps(false); return button;
    }
    private LinearLayout.LayoutParams weighted() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, -1, 1f);
        params.setMargins(dp(3), 0, dp(3), 0); return params;
    }
    private LinearLayout.LayoutParams margin(int width, int height, int left, int bottom) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(width, height);
        params.setMargins(dp(left), 0, dp(left), dp(bottom)); return params;
    }
    private int dp(int value) { return (int) (value * getResources().getDisplayMetrics().density + 0.5f); }

    @Override protected void onDestroy() {
        super.onDestroy();
        if (handLandmarker != null) handLandmarker.close();
        if (textToSpeech != null) { textToSpeech.stop(); textToSpeech.shutdown(); }
        cameraExecutor.shutdown(); translationExecutor.shutdown();
    }
}
