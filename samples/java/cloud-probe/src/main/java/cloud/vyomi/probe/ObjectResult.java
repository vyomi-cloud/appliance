package cloud.vyomi.probe;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.Map;

/** JSON-friendly result of reading one object back through a native SDK. */
public final class ObjectResult {
    private ObjectResult() {}

    public static Map<String, Object> of(String cloud, String bucket, String key,
                                         byte[] bytes, String contentType) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ok", true);
        m.put("cloud", cloud);
        m.put("bucket", bucket);
        m.put("key", key);
        m.put("size", bytes.length);
        m.put("contentType", contentType == null ? "" : contentType);
        m.put("sha256", sha256(bytes));
        m.put("preview", preview(bytes));
        return m;
    }

    public static Map<String, Object> error(String cloud, String bucket, String key, Exception e) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ok", false);
        m.put("cloud", cloud);
        m.put("bucket", bucket);
        m.put("key", key);
        m.put("error", e.getClass().getSimpleName() + ": " + e.getMessage());
        return m;
    }

    private static String sha256(byte[] b) {
        try {
            byte[] d = MessageDigest.getInstance("SHA-256").digest(b);
            StringBuilder sb = new StringBuilder();
            for (byte x : d) sb.append(String.format("%02x", x));
            return sb.toString();
        } catch (Exception e) { return ""; }
    }

    /** First ~200 bytes as printable ASCII (non-printables → '.'). */
    private static String preview(byte[] b) {
        int n = Math.min(b.length, 200);
        String s = new String(b, 0, n, StandardCharsets.UTF_8);
        return s.replaceAll("[^\\x20-\\x7E]", ".");
    }
}
