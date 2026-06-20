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
        SpringApplication.run(Application.class, args);
    }
}
