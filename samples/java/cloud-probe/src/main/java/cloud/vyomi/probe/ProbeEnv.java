package cloud.vyomi.probe;

/** Resolves the Vyomi appliance endpoint the SDKs target. */
public final class ProbeEnv {
    private ProbeEnv() {}

    /** CLOUDPROBE_ENDPOINT wins; falls back to AWS_ENDPOINT_URL; default
     *  http://127.0.0.1:9000 (the appliance's simulator port). */
    public static String endpoint() {
        String e = firstNonBlank(System.getenv("CLOUDPROBE_ENDPOINT"),
                                 System.getenv("AWS_ENDPOINT_URL"),
                                 "http://127.0.0.1:9000");
        return e.trim();
    }

    /** Optional per-cloud override, e.g. CLOUDPROBE_ENDPOINT_GCP. */
    public static String endpoint(String cloud) {
        return firstNonBlank(System.getenv("CLOUDPROBE_ENDPOINT_" + cloud.toUpperCase()), endpoint());
    }

    /** GCS rides the simulator (same base as endpoint()). */
    public static String gcsHost() { return endpoint("gcp"); }

    /** Firestore is the native gRPC emulator — a different port (:8080, no
     *  scheme). FIRESTORE_EMULATOR_HOST wins; otherwise derive host:8080 from
     *  the endpoint. */
    public static String firestoreEmulatorHost() {
        String h = System.getenv("FIRESTORE_EMULATOR_HOST");
        if (h != null && !h.isBlank()) return h.trim();
        try {
            java.net.URI u = java.net.URI.create(endpoint("gcp"));
            return (u.getHost() == null ? "127.0.0.1" : u.getHost()) + ":8080";
        } catch (Exception e) { return "127.0.0.1:8080"; }
    }

    public static String gcpProject() {
        return firstNonBlank(System.getenv("GCP_PROJECT"), "cloudlearn");
    }

    private static String firstNonBlank(String... vals) {
        for (String v : vals) if (v != null && !v.isBlank()) return v;
        return "";
    }
}
