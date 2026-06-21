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

    /** Firestore is the native gRPC emulator — a SEPARATE container
     *  ({@code cloudlearn-firestore:8080}), NOT the simulator endpoint.
     *
     *  Deriving this host from CLOUDPROBE_ENDPOINT was the {@code NoRouteToHost}
     *  bug: the simulator is reached via caddy / the VM gateway, but neither
     *  exposes :8080 — only the emulator's own service name (or its published
     *  port) does. So the derived {@code <sim-host>:8080} pointed at an
     *  unroutable address while {@code curl cloudlearn-firestore:8080} (the
     *  real target) worked, which looked like a gRPC failure but was a
     *  wrong-host failure.
     *
     *  Resolution order: FIRESTORE_EMULATOR_HOST (also what the SDK itself
     *  honors) > CLOUDPROBE_FIRESTORE_HOST > the co-located service-name
     *  default. For VM host-networking, set FIRESTORE_EMULATOR_HOST to
     *  {@code <vm-ip>:8080} (the published port). */
    public static String firestoreEmulatorHost() {
        return firstNonBlank(
            System.getenv("FIRESTORE_EMULATOR_HOST"),
            System.getenv("CLOUDPROBE_FIRESTORE_HOST"),
            "cloudlearn-firestore:8080").trim();
    }

    public static String gcpProject() {
        return firstNonBlank(System.getenv("GCP_PROJECT"), "cloudlearn");
    }

    /** GCP Secret Manager + Cloud KMS have NO Google emulator (unlike
     *  Pub/Sub/Firestore) and default to gRPC. Their Java SDKs support a REST
     *  (HttpJson) transport, which gax builds as an HTTPS URL — so this must be
     *  an https {@code host:port} (the appliance's caddy terminator, same target
     *  as Cosmos), NOT the plaintext sim :9000. Format is host:port with NO
     *  scheme/path — the SDK appends the {@code /v1/...} path from the proto
     *  annotations. The caddy cert must be trusted by the JVM (same requirement
     *  the Cosmos probe documents). Override via CLOUDPROBE_GCP_REST_ENDPOINT. */
    public static String gcpRestEndpoint() {
        return firstNonBlank(System.getenv("CLOUDPROBE_GCP_REST_ENDPOINT"),
                "127.0.0.1:9443").trim();
    }

    /** GCP KMS location (key ring location). Cloud KMS uses "global" or a region
     *  like "us-east1"; the appliance treats it as an opaque path segment. */
    public static String gcpLocation() {
        return firstNonBlank(System.getenv("GCP_LOCATION"), "global");
    }

    /** GCP Pub/Sub emulator host:port (gRPC) — like Firestore, a SEPARATE
     *  container, not the sim. The SDK also honors PUBSUB_EMULATOR_HOST directly. */
    public static String pubsubEmulatorHost() {
        return firstNonBlank(System.getenv("PUBSUB_EMULATOR_HOST"),
                System.getenv("CLOUDLEARN_PUBSUB_EMULATOR_HOST"),
                "cloudlearn-pubsub:8085").trim();
    }

    // ── Messaging (Azure Storage Queue) ──────────────────────────────────────
    /** Azure Storage Queue endpoint. Native azure-storage-queue rides the
     *  appliance's Azurite-backed queue surface — the AMQP→HTTP substitution for
     *  Service Bus — under the dedicated {@code /azure-data/queue/{account}}
     *  prefix (a dispatch passthrough, so it never collides with the blob
     *  handler, which shares the x-ms-version signature). */
    public static String azureQueueEndpointFor(String account) {
        // Host-based: real Azure addresses each account as
        // {account}.queue.core.windows.net and the SDK rebuilds /{queue} from the
        // HOST (dropping any path prefix). *.queue.localtest.me resolves to
        // 127.0.0.1 (no DNS/hosts edits); the appliance host-routing middleware
        // maps it onto /azure-data/queue/{account}.
        String e = endpoint("azure");
        String scheme = e.startsWith("https") ? "https" : "http";
        return scheme + "://" + account + ".queue.localtest.me:"
             + _portOf(e, scheme.equals("https") ? "443" : "80");
    }
    /** Azurite-style connection string with an explicit QueueEndpoint so the SDK
     *  addresses path-style ({@code /{account}/{queue}}); the appliance bridges
     *  it onto the Azure queue handler (never the S3 catch-all). */
    public static String azureQueueConnectionString(String account) {
        return "DefaultEndpointsProtocol=http;AccountName=" + account
             + ";AccountKey=" + azureKey()
             + ";QueueEndpoint=" + azureQueueEndpointFor(account) + ";";
    }

    // ── Key Vault (Secrets + Keys) ───────────────────────────────────────────
    /** The appliance's HTTPS (caddy) host:port — shared by every native SDK that
     *  insists on TLS: Cosmos, GCP HttpJson, and Azure Key Vault. */
    public static String caddyHost() {
        return firstNonBlank(System.getenv("CLOUDPROBE_CADDY_HOST"),
                System.getenv("CLOUDPROBE_GCP_REST_ENDPOINT"), "127.0.0.1:9443").trim();
    }

    /** Azure Key Vault data-plane base, e.g.
     *  https://host:9443/azure-data/keyvault/{vault}. The Key Vault SDKs enforce
     *  HTTPS and append {@code /secrets}|{@code /keys} themselves, so this is the
     *  caddy endpoint (same TLS/cert requirement the Cosmos probe documents).
     *  Override the whole base via CLOUDPROBE_KEYVAULT_ENDPOINT. */
    public static String azureKeyVaultEndpoint(String vault) {
        String base = System.getenv("CLOUDPROBE_KEYVAULT_ENDPOINT");
        if (base != null && !base.isBlank()) return base.trim();
        // Host-based ({vault}.vault.localtest.me → 127.0.0.1); the appliance's
        // host-routing middleware maps it onto /azure-data/keyvault/{vault}. HTTPS
        // via caddy — the CryptographyClient rebuilds /keys/... from the host, so a
        // path prefix can't survive.
        return "https://" + vault + ".vault.localtest.me:" + _portOf(caddyHost(), "9443");
    }
    public static String azureVaultName() {
        return firstNonBlank(System.getenv("AZURE_KEYVAULT_NAME"), "cloudlearn");
    }

    // ── Azure ───────────────────────────────────────────────────────────────
    // Data planes live under /azure-data/{blob,cosmos}/{account}. The sim
    // ignores the SharedKey/master-key signature, so the well-known
    // Azurite / Cosmos-emulator keys are fine.
    public static String azureAccount() {
        return firstNonBlank(System.getenv("AZURE_STORAGE_ACCOUNT"), "devstoreaccount1");
    }
    public static String azureBlobEndpoint() {
        return azureBlobEndpointFor(azureAccount());
    }
    /** Per-account blob service endpoint, Azurite-style: http://host:9000/{account}.
     *  The account is the FIRST path segment — the only shape the azure-storage
     *  SDK preserves when it builds container/blob URLs. The appliance routes it
     *  to the Azure blob handler by the x-ms-version header (see
     *  azure_blob_dispatch_middleware), so it never collides with S3 on :9000. */
    public static String azureBlobEndpointFor(String account) {
        return endpoint("azure") + "/" + account;
    }
    /** Azurite-style connection string. The explicit {@code BlobEndpoint} keeps
     *  the SDK addressing path-style ({@code /{account}/{container}/{blob}}); the
     *  appliance bridges that onto its Azure blob handler via the x-ms-version
     *  signature, so requests never fall through to the S3 handler. */
    public static String azureConnectionString(String account) {
        return "DefaultEndpointsProtocol=http;AccountName=" + account
             + ";AccountKey=" + azureKey()
             + ";BlobEndpoint=" + azureBlobEndpointFor(account) + ";";
    }
    public static String azureKey() {
        return firstNonBlank(System.getenv("AZURE_STORAGE_KEY"),
            "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==");
    }
    public static String azureCosmosAccount() {
        return firstNonBlank(System.getenv("AZURE_COSMOS_ACCOUNT"), "cloudlearn");
    }
    /** Cosmos endpoint. The Cosmos SDK always speaks TLS, so this should be an
     *  HTTPS URL (the appliance's caddy terminator, e.g.
     *  https://vyomi.local:9443/azure-data/cosmos/{account}); override via
     *  CLOUDPROBE_COSMOS_ENDPOINT. Falls back to the HTTP sim endpoint (which
     *  the SDK will reject with an SSL error — set the HTTPS override). */
    public static String azureCosmosEndpoint() {
        String o = System.getenv("CLOUDPROBE_COSMOS_ENDPOINT");
        if (o != null && !o.isBlank()) return o.trim();
        return endpoint("azure") + "/azure-data/cosmos/" + azureCosmosAccount();
    }
    public static String azureCosmosKey() {
        return firstNonBlank(System.getenv("AZURE_COSMOS_KEY"),
            "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==");
    }

    /** Port from a "host:port" or "scheme://host:port/path" string (else dflt). */
    private static String _portOf(String s, String dflt) {
        String hp = s.replaceFirst("^[a-zA-Z]+://", "").replaceFirst("/.*$", "");
        int i = hp.lastIndexOf(':');
        return i >= 0 ? hp.substring(i + 1) : dflt;
    }

    private static String firstNonBlank(String... vals) {
        for (String v : vals) if (v != null && !v.isBlank()) return v;
        return "";
    }
}
