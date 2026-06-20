package cloud.vyomi.probe;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * cloud-probe — a microservice that drives the NATIVE AWS / GCP / Azure
 * object-store + NoSQL SDKs against a Vyomi appliance endpoint, to prove the
 * appliance is wire-compatible with the real vendor SDKs (and as an
 * integration-test harness).
 *
 * Endpoints:
 *   GET /healthz          → liveness + which clouds are wired
 *   GET /probe/{cloud}    → run the full object-store + NoSQL lifecycle for
 *                           cloud ∈ {aws, gcp, azure} and return a step report
 */
@SpringBootApplication
public class Application {
    public static void main(String[] args) {
        maybeTrustAllTls();
        SpringApplication.run(Application.class, args);
    }

    /** Install a permissive TLS trust manager so SDKs that honor the JVM-default
     *  SSLContext can reach the appliance's self-signed caddy terminator (the
     *  Cosmos SDK requires HTTPS). Gated by CLOUDPROBE_TRUST_ALL_TLS (default
     *  true). TEST HARNESS ONLY — never enable in production. */
    private static void maybeTrustAllTls() {
        if (!System.getenv().getOrDefault("CLOUDPROBE_TRUST_ALL_TLS", "true").equalsIgnoreCase("true")) return;
        try {
            javax.net.ssl.TrustManager[] trustAll = { new javax.net.ssl.X509TrustManager() {
                public void checkClientTrusted(java.security.cert.X509Certificate[] c, String a) {}
                public void checkServerTrusted(java.security.cert.X509Certificate[] c, String a) {}
                public java.security.cert.X509Certificate[] getAcceptedIssuers() {
                    return new java.security.cert.X509Certificate[0];
                }
            }};
            javax.net.ssl.SSLContext sc = javax.net.ssl.SSLContext.getInstance("TLS");
            sc.init(null, trustAll, new java.security.SecureRandom());
            javax.net.ssl.SSLContext.setDefault(sc);
            javax.net.ssl.HttpsURLConnection.setDefaultSSLSocketFactory(sc.getSocketFactory());
            javax.net.ssl.HttpsURLConnection.setDefaultHostnameVerifier((h, s) -> true);
        } catch (Exception ignore) {}
    }
}
