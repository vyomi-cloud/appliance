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

    private static String firstNonBlank(String... vals) {
        for (String v : vals) if (v != null && !v.isBlank()) return v;
        return "";
    }
}
