package com.example.lsm;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Locale;

/** Ports the landmark classifiers and DTW templates from BACKEND_V4.py. */
final class SignRecognizer {
    static final String ALPHABET = "ABECEDARIO";
    static final String VOCABULARY = "VOCABULARIO";
    private static final int[] STATIC_INDICES = {4, 8, 12, 16, 20, 6, 10, 14, 18};
    private static final int BUFFER_LENGTH = 50;
    private static final String[] DYNAMIC_LETTERS = {"J", "K", "Q", "X", "Z"};

    static final class Recognition {
        final String label;
        final double score;
        Recognition(String label, double score) { this.label = label; this.score = score; }
    }

    private final Map<String, List<float[][]>> staticAlphabet = new HashMap<>();
    private final Map<String, List<float[][]>> staticVocabulary = new HashMap<>();
    private final Map<String, List<float[][]>> dynamicAlphabet = new HashMap<>();
    private final Map<String, List<float[][]>> dynamicVocabulary = new HashMap<>();
    private final Deque<float[]> trajectory = new ArrayDeque<>();
    private String lastLabel = "";
    private int stableFrames = 0;
    private boolean armed = true;

    SignRecognizer(Context context) throws Exception {
        loadPatterns(context);
    }

    private void loadPatterns(Context context) throws Exception {
        JSONObject root = readJson(new BufferedReader(new InputStreamReader(
                context.getAssets().open("patrones_capturados.json"), StandardCharsets.UTF_8)));
        loadPatternSet(root, ALPHABET, false);
        try (FileInputStream input = context.openFileInput("patrones_personalizados.json")) {
            loadPatternSet(new JSONObject(new String(readAll(input), StandardCharsets.UTF_8)), ALPHABET, true);
        } catch (java.io.FileNotFoundException ignored) { }
    }

    private static JSONObject readJson(BufferedReader reader) throws Exception {
        StringBuilder json = new StringBuilder();
        try (BufferedReader input = reader) {
            String line;
            while ((line = input.readLine()) != null) json.append(line);
        }
        return new JSONObject(json.toString());
    }

    private void loadPatternSet(JSONObject root, String defaultMode, boolean custom) {
        Iterator<String> keys = root.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            JSONObject item = root.optJSONObject(key);
            if (item == null) continue;
            String label = key.contains("__") ? key.substring(0, key.lastIndexOf("__")) : key;
            JSONArray samples = item.optJSONArray("muestras");
            if (samples == null) continue;
            boolean dynamic = "dinamica".equalsIgnoreCase(item.optString("tipo"));
            String itemMode = custom ? item.optString("modo", defaultMode) : defaultMode;
            for (int i = 0; i < samples.length(); i++) {
                JSONObject sample = samples.optJSONObject(i);
                if (sample == null || sample.optBoolean("sintetica", false)) continue;
                if (dynamic) {
                    JSONArray points = sample.optJSONArray("trayectoria");
                    if (points == null) continue;
                    float[][] template = readPoints(points);
                    if (template.length >= 2) {
                        Map<String, List<float[][]>> target = ALPHABET.equals(itemMode)
                                ? dynamicAlphabet : dynamicVocabulary;
                        target
                                .computeIfAbsent(label, ignored -> new ArrayList<>()).add(normalize(resample(template, 30)));
                    }
                } else {
                    JSONArray points = sample.optJSONArray("pose");
                    if (points == null || points.length() != STATIC_INDICES.length) continue;
                    float[][] vector = staticVector(readPoints(points));
                    Map<String, List<float[][]>> target = ALPHABET.equals(itemMode)
                            ? staticAlphabet : staticVocabulary;
                    target.computeIfAbsent(label, ignored -> new ArrayList<>()).add(vector);
                }
            }
        }
    }

    private static float[][] readPoints(JSONArray input) {
        float[][] points = new float[input.length()][2];
        for (int i = 0; i < input.length(); i++) {
            JSONArray p = input.optJSONArray(i);
            if (p != null && p.length() >= 2) {
                points[i][0] = (float) p.optDouble(0);
                points[i][1] = (float) p.optDouble(1);
            }
        }
        return points;
    }

    Recognition recognize(List<float[]> landmarks, String mode) {
        if (landmarks == null || landmarks.size() < 21) {
            trajectory.clear();
            lastLabel = "";
            stableFrames = 0;
            armed = true;
            return new Recognition("", 0);
        }

        float[][] pointArray = landmarks.toArray(new float[0][]);
        String label = "";
        double score = 0;
        Recognition stat = recognizeStatic(pointArray, mode);
        label = stat.label;
        score = stat.score;

        float[] tip = landmarks.get(8);
        trajectory.addLast(new float[]{tip[0], tip[1]});
        while (trajectory.size() > BUFFER_LENGTH) trajectory.removeFirst();
        if (label.isEmpty()) {
            Map<String, List<float[][]>> dynamic = ALPHABET.equals(mode) ? dynamicAlphabet : dynamicVocabulary;
            Recognition movement = recognizeDynamic(dynamic);
            label = movement.label;
            score = movement.score;
        }

        if (label.isEmpty()) {
            stableFrames = 0;
            lastLabel = "";
            armed = true;
        } else if (label.equals(lastLabel)) {
            stableFrames++;
        } else {
            lastLabel = label;
            stableFrames = 1;
        }
        return new Recognition(label, score);
    }

    /** Returns a sign once it has held for six frames; release/change rearms it. */
    String consumeStable(String mode) {
        if (!armed || stableFrames < 6 || lastLabel.isEmpty()) return "";
        armed = false;
        String result = lastLabel;
        if (ALPHABET.equals(mode)) trajectory.clear();
        else trajectory.clear();
        return result;
    }

    void reset() {
        trajectory.clear(); lastLabel = ""; stableFrames = 0; armed = true;
    }

    private Recognition recognizeStatic(float[][] raw, String mode) {
        float[][] points = new float[STATIC_INDICES.length][2];
        for (int i = 0; i < STATIC_INDICES.length; i++) points[i] = raw[STATIC_INDICES[i]].clone();
        float[] query = flatten(normalize(points));
        String bestLabel = "";
        double best = -1;
        Map<String, List<float[][]>> patterns = ALPHABET.equals(mode) ? staticAlphabet : staticVocabulary;
        for (Map.Entry<String, List<float[][]>> entry : patterns.entrySet()) {
            for (float[][] proto : entry.getValue()) {
                double similarity = cosine(query, flatten(proto));
                if (similarity > best) { best = similarity; bestLabel = entry.getKey(); }
            }
        }
        return best >= 0.82 ? new Recognition(bestLabel, best) : new Recognition("", best);
    }

    void saveCustomSign(Context context, String label, String mode, String type,
                        List<float[][]> capturedSamples) throws Exception {
        String normalizedLabel = label.trim().toUpperCase(Locale.ROOT);
        if (normalizedLabel.isEmpty() || capturedSamples.size() < 5)
            throw new IllegalArgumentException("Escribe un nombre y captura al menos 5 muestras.");

        JSONObject all = new JSONObject();
        try (FileInputStream input = context.openFileInput("patrones_personalizados.json")) {
            all = new JSONObject(new String(readAll(input), StandardCharsets.UTF_8));
        } catch (java.io.FileNotFoundException ignored) { }

        String key = normalizedLabel + "__DERECHA";
        JSONArray samples = new JSONArray();
        for (float[][] captured : capturedSamples) {
            JSONArray points = new JSONArray();
            for (float[] point : captured) points.put(new JSONArray().put(point[0]).put(point[1]));
            JSONObject sample = new JSONObject();
            sample.put("sintetica", false);
            sample.put("pose".equals(type) ? "pose" : "trayectoria", points);
            samples.put(sample);
        }
        JSONObject item = new JSONObject();
        item.put("tipo", "pose".equals(type) ? "estatica" : "dinamica");
        item.put("manos", 1);
        item.put("modo", mode);
        item.put("muestras", samples);
        all.put(key, item);

        try (java.io.FileOutputStream output = context.openFileOutput("patrones_personalizados.json", Context.MODE_PRIVATE)) {
            output.write(all.toString().getBytes(StandardCharsets.UTF_8));
        }
        loadPatternSet(new JSONObject().put(key, item), mode, true);
    }

    private static byte[] readAll(InputStream input) throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
        return output.toByteArray();
    }

    private static float[][] staticVector(float[][] points) {
        return normalize(points);
    }

    private Recognition recognizeDynamic(Map<String, List<float[][]>> patterns) {
        if (trajectory.size() < 10 || patterns.isEmpty()) return new Recognition("", 9999);
        float[][] raw = trajectory.toArray(new float[0][]);
        float[][] query = resample(raw, 30);
        if (query == null) return new Recognition("", 9999);
        query = normalize(query);
        String bestLabel = "";
        double best = Double.POSITIVE_INFINITY;
        for (Map.Entry<String, List<float[][]>> entry : patterns.entrySet()) {
            for (float[][] template : entry.getValue()) {
                double distance = dtw(query, template);
                if (distance < best) { best = distance; bestLabel = entry.getKey(); }
            }
        }
        return best <= 2.5 ? new Recognition(bestLabel, best) : new Recognition("", best);
    }

    private static float[][] resample(float[][] points, int count) {
        if (points.length < 2) return null;
        double[] cumulative = new double[points.length];
        for (int i = 1; i < points.length; i++) {
            double dx = points[i][0] - points[i - 1][0], dy = points[i][1] - points[i - 1][1];
            cumulative[i] = cumulative[i - 1] + Math.sqrt(dx * dx + dy * dy);
        }
        double total = cumulative[cumulative.length - 1];
        if (total < 1e-4) return null;
        float[][] result = new float[count][2];
        for (int i = 0; i < count; i++) {
            double target = total * i / (count - 1.0);
            int right = 1;
            while (right < cumulative.length - 1 && cumulative[right] < target) right++;
            double span = cumulative[right] - cumulative[right - 1];
            double ratio = span == 0 ? 0 : (target - cumulative[right - 1]) / span;
            for (int axis = 0; axis < 2; axis++)
                result[i][axis] = (float) (points[right - 1][axis] + ratio * (points[right][axis] - points[right - 1][axis]));
        }
        return result;
    }

    private static float[][] normalize(float[][] points) {
        if (points == null) return null;
        double mx = 0, my = 0;
        for (float[] p : points) { mx += p[0]; my += p[1]; }
        mx /= points.length; my /= points.length;
        double variance = 0;
        for (float[] p : points) variance += Math.pow(p[0] - mx, 2) + Math.pow(p[1] - my, 2);
        double std = Math.sqrt(variance / (points.length * 2.0)) + 1e-6;
        float[][] result = new float[points.length][2];
        for (int i = 0; i < points.length; i++) {
            result[i][0] = (float) ((points[i][0] - mx) / std);
            result[i][1] = (float) ((points[i][1] - my) / std);
        }
        return result;
    }

    private static double dtw(float[][] a, float[][] b) {
        double[][] table = new double[a.length + 1][b.length + 1];
        for (int i = 0; i <= a.length; i++) java.util.Arrays.fill(table[i], Double.POSITIVE_INFINITY);
        table[0][0] = 0;
        for (int i = 1; i <= a.length; i++) for (int j = 1; j <= b.length; j++) {
            double dx = a[i - 1][0] - b[j - 1][0], dy = a[i - 1][1] - b[j - 1][1];
            table[i][j] = Math.sqrt(dx * dx + dy * dy) + Math.min(table[i - 1][j],
                    Math.min(table[i][j - 1], table[i - 1][j - 1]));
        }
        return table[a.length][b.length] / (a.length + b.length);
    }

    private static float[] flatten(float[][] points) {
        float[] values = new float[points.length * 2];
        for (int i = 0; i < points.length; i++) { values[i * 2] = points[i][0]; values[i * 2 + 1] = points[i][1]; }
        return values;
    }

    private static double cosine(float[] a, float[] b) {
        double dot = 0, aa = 0, bb = 0;
        for (int i = 0; i < a.length; i++) { dot += a[i] * b[i]; aa += a[i] * a[i]; bb += b[i] * b[i]; }
        return dot / (Math.sqrt(aa * bb) + 1e-9);
    }
}
