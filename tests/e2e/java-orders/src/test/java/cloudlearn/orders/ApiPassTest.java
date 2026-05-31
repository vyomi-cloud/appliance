package cloudlearn.orders;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.core.SdkBytes;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.eventbridge.EventBridgeClient;
import software.amazon.awssdk.services.kms.KmsClient;
import software.amazon.awssdk.services.kms.model.CreateKeyRequest;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.S3Configuration;
import software.amazon.awssdk.services.s3.model.CreateBucketRequest;
import software.amazon.awssdk.services.secretsmanager.SecretsManagerClient;
import software.amazon.awssdk.services.secretsmanager.model.CreateSecretRequest;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.CreateQueueRequest;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.URI;
import java.time.Duration;

import static org.junit.jupiter.api.Assertions.*;

/**
 * API-pass: the JUnit5 counterpart to the Playwright console-pass spec.
 *
 *   - Uses unmodified aws-sdk-java-v2 (the same clients the app uses) to
 *     provision the 5 AWS resources directly against the simulator.
 *   - Then HTTP-pokes the running java-orders app's endpoints and asserts
 *     correctness.
 *
 * To run: have the app + simulator both reachable, then
 *
 *   ENDPOINT=http://192.168.252.7:9000 APP_BASE=http://192.168.252.7:8080 \
 *     mvn -Dtest=ApiPassTest test
 *
 * This test creates a Postgres DB via the Azure SQL path (since AWS RDS in
 * the simulator is metadata-only); the connection string + creds are stored
 * in Secrets Manager so the app reads them on startup.
 */
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class ApiPassTest {

    private static final String ENDPOINT = envOr("ENDPOINT", "http://192.168.252.7:9000");
    private static final String APP_BASE = envOr("APP_BASE", "http://192.168.252.7:8080");
    private static final String SECRET_NAME = "prod/orders/db";
    private static final String KMS_KEY     = "alias/orders-cc-key";
    private static final String BUCKET      = "orders-receipts";
    private static final String QUEUE_NAME  = "orders-processing-queue";

    private static final ObjectMapper M = new ObjectMapper();
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5)).build();

    private static StaticCredentialsProvider creds() {
        return StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test"));
    }

    @Test @Order(1)
    void provisionsRealPostgresViaAzureSqlPath() throws Exception {
        // Switch to an Azure space for the SQL create, then to AWS for the rest.
        switchToProviderSpace("azure");
        var api = "api-version=2023-08-01";
        var base = ENDPOINT + "/subscriptions/sub-e2e/resourceGroups/rg-e2e/providers/Microsoft.Sql/servers/orders-sql";

        // Server
        http("PUT", base + "?" + api, """
            {"location":"eastus","properties":{"administratorLogin":"azureadmin","administratorLoginPassword":"Password123!"}}""");
        // Database
        http("PUT", base + "/databases/orders?" + api, """
            {"location":"eastus","properties":{}}""");
        // GET-after-PUT surfaces connectionInfo
        var got = http("GET", base + "/databases/orders?" + api, null);
        JsonNode body = M.readTree(got.body());
        JsonNode conn = body.path("properties").path("connectionInfo");
        assertTrue(conn.path("engine").asText().contains("PostgreSQL"),
                "expected PostgreSQL engine in connectionInfo, got: " + body);

        // Switch back to AWS and store the JDBC URL in Secrets Manager.
        switchToProviderSpace("aws");
        String jdbcUrl = String.format("jdbc:postgresql://%s:%d/%s",
                conn.path("host").asText(),
                conn.path("port").asInt(),
                conn.path("database").asText());
        String secretJson = M.writeValueAsString(java.util.Map.of(
                "url", jdbcUrl,
                "user", conn.path("user").asText(),
                "password", conn.path("password").asText()));

        try (var sm = SecretsManagerClient.builder()
                .endpointOverride(URI.create(ENDPOINT))
                .region(Region.US_EAST_1)
                .credentialsProvider(creds()).build()) {
            try {
                sm.createSecret(CreateSecretRequest.builder()
                        .name(SECRET_NAME)
                        .secretString(secretJson)
                        .build());
            } catch (software.amazon.awssdk.services.secretsmanager.model.ResourceExistsException ignored) {
                sm.putSecretValue(b -> b.secretId(SECRET_NAME).secretString(secretJson));
            }
        }
    }

    @Test @Order(2)
    void provisionsKmsKey() {
        // AWS KMS CreateKey doesn't take a KeyId/alias — it generates one and
        // returns the metadata. Real AWS uses CreateAlias to attach an alias.
        // The simulator accepts whatever alias is passed at Encrypt time
        // (provisions Vault transit key lazily), so the description-only key
        // create here is enough — the app's first KMS.Encrypt with
        // alias/orders-cc-key triggers the lazy Vault key creation.
        try (var kms = KmsClient.builder()
                .endpointOverride(URI.create(ENDPOINT))
                .region(Region.US_EAST_1)
                .credentialsProvider(creds()).build()) {
            kms.createKey(CreateKeyRequest.builder()
                    .description("orders cc encryption")
                    .build());
        }
    }

    @Test @Order(3)
    void provisionsS3Bucket() {
        try (var s3 = S3Client.builder()
                .endpointOverride(URI.create(ENDPOINT))
                .region(Region.US_EAST_1)
                .credentialsProvider(creds())
                .serviceConfiguration(S3Configuration.builder()
                        .pathStyleAccessEnabled(true)
                        .chunkedEncodingEnabled(false).build())
                .build()) {
            try {
                s3.createBucket(CreateBucketRequest.builder().bucket(BUCKET).build());
            } catch (Exception ignored) { /* already exists */ }
        }
    }

    @Test @Order(4)
    void provisionsSqsQueue() {
        try (var sqs = SqsClient.builder()
                .endpointOverride(URI.create(ENDPOINT))
                .region(Region.US_EAST_1)
                .credentialsProvider(creds()).build()) {
            sqs.createQueue(CreateQueueRequest.builder().queueName(QUEUE_NAME).build());
        }
    }

    @Test @Order(5)
    void appHealthReturnsUp() throws Exception {
        // The app must already be running. Poll up to 90s for /health=UP.
        long deadline = System.currentTimeMillis() + 90_000;
        Exception last = null;
        while (System.currentTimeMillis() < deadline) {
            try {
                var r = http("GET", APP_BASE + "/health", null);
                if (r.statusCode() == 200) {
                    JsonNode h = M.readTree(r.body());
                    if ("UP".equals(h.path("status").asText())) {
                        for (String svc : new String[]{"db", "s3", "kms", "sqs", "eventbridge"}) {
                            assertTrue(h.path(svc).path("ok").asBoolean(),
                                    svc + " not OK: " + h.path(svc));
                        }
                        return;
                    }
                }
            } catch (Exception e) { last = e; }
            Thread.sleep(1500);
        }
        fail("app /health never became UP; last error: " + last);
    }

    @Test @Order(6)
    void postOrderRoundTrip() throws Exception {
        // POST /orders
        var post = http("POST", APP_BASE + "/orders",
                "{\"customer\":\"alice\",\"total_cents\":4999,\"cc\":\"4111111111111111\"}");
        assertEquals(200, post.statusCode(), "POST /orders body: " + post.body());
        JsonNode order = M.readTree(post.body());
        long orderId = order.path("id").asLong();
        assertTrue(orderId > 0);

        // GET /orders contains it
        var list = M.readTree(http("GET", APP_BASE + "/orders", null).body());
        boolean found = false;
        for (JsonNode o : list) if (o.path("id").asLong() == orderId) { found = true; break; }
        assertTrue(found, "newly-created order missing from GET /orders");

        // GET /orders/{id}/receipt → uploaded to S3
        var receipt = M.readTree(http("GET", APP_BASE + "/orders/" + orderId + "/receipt", null).body());
        assertTrue(receipt.path("receipt_url").asText().contains(BUCKET));
        assertTrue(receipt.path("size_bytes").asInt() > 0);

        // NATS inbox should have the OrderCreated event.
        var inbox = M.readTree(http("GET", ENDPOINT + "/__nats/inbox?prefix=aws.eventbridge.", null).body());
        boolean eventFound = false;
        for (JsonNode m : inbox.path("messages")) {
            if (m.toString().contains(String.valueOf(orderId))) { eventFound = true; break; }
        }
        assertTrue(eventFound, "OrderCreated event missing from NATS inbox");
    }

    // ---- helpers ----------------------------------------------------------
    private static String envOr(String k, String d) {
        String v = System.getenv(k); return (v == null || v.isEmpty()) ? d : v;
    }

    private static void switchToProviderSpace(String provider) throws Exception {
        var r = http("GET", ENDPOINT + "/api/spaces", null);
        JsonNode spaces = M.readTree(r.body()).path("spaces");
        String spaceId = "";
        for (JsonNode s : spaces) {
            if (provider.equals(s.path("provider").asText())) { spaceId = s.path("space_id").asText(); break; }
        }
        if (spaceId.isEmpty()) {
            var created = http("POST", ENDPOINT + "/api/spaces",
                    "{\"name\":\"e2e-" + provider + "\",\"provider\":\"" + provider + "\"}");
            spaceId = M.readTree(created.body()).path("space_id").asText();
        }
        http("POST", ENDPOINT + "/api/spaces/" + spaceId + "/switch", null);
    }

    private static HttpResponse<String> http(String method, String url, String body) throws Exception {
        var b = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(10));
        if (body != null) {
            b.method(method, HttpRequest.BodyPublishers.ofString(body));
            b.header("Content-Type", "application/json");
        } else {
            b.method(method, HttpRequest.BodyPublishers.noBody());
        }
        return HTTP.send(b.build(), HttpResponse.BodyHandlers.ofString());
    }
}
