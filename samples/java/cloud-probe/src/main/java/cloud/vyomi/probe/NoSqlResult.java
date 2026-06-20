package cloud.vyomi.probe;

import java.util.LinkedHashMap;
import java.util.Map;

/** JSON-friendly result of reading/writing one NoSQL item through a native SDK.
 *  The NoSQL analog of {@link ObjectResult}. {@code table} is the DynamoDB
 *  table / Firestore collection / Cosmos container; {@code id} is the item id. */
public final class NoSqlResult {
    private NoSqlResult() {}

    public static Map<String, Object> of(String cloud, String table, String id,
                                         Map<String, Object> item) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ok", true);
        m.put("cloud", cloud);
        m.put("table", table);
        m.put("id", id);
        m.put("item", item);
        return m;
    }

    public static Map<String, Object> error(String cloud, String table, String id, Exception e) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ok", false);
        m.put("cloud", cloud);
        m.put("table", table);
        m.put("id", id);
        m.put("error", e.getClass().getSimpleName() + ": " + e.getMessage());
        m.put("rootCause", rootCause(e));
        return m;
    }

    /** Deepest cause (class + message) — surfaces the real gRPC/TLS/socket fault. */
    private static String rootCause(Throwable t) {
        Throwable r = t;
        while (r.getCause() != null && r.getCause() != r) r = r.getCause();
        return r.getClass().getName() + ": " + r.getMessage();
    }
}
