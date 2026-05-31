package cloudlearn.orders;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

import software.amazon.awssdk.core.SdkBytes;
// software.amazon.awssdk.core.sync.RequestBody collides with Spring's
// @RequestBody annotation (imported via web.bind.annotation.*) — use the
// fully-qualified name at the call site instead.
import software.amazon.awssdk.services.eventbridge.EventBridgeClient;
import software.amazon.awssdk.services.eventbridge.model.PutEventsRequest;
import software.amazon.awssdk.services.eventbridge.model.PutEventsRequestEntry;
import software.amazon.awssdk.services.kms.KmsClient;
import software.amazon.awssdk.services.kms.model.EncryptRequest;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetUrlRequest;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.SendMessageRequest;

import java.util.*;

/**
 * HTTP API:
 *   POST /orders                         create an order (KMS+RDS+EventBridge+SQS)
 *   GET  /orders                         list all orders
 *   GET  /orders/{id}                    fetch one
 *   GET  /orders/{id}/receipt            generate HTML receipt → S3 → return URL
 *   GET  /health                         5-way readiness check
 *
 * Each route touches multiple AWS services so a green response proves the
 * whole stack is wired end-to-end.
 */
@RestController
public class OrdersController {

    private static final Logger log = LoggerFactory.getLogger(OrdersController.class);

    private final JdbcTemplate jdbc;
    private final S3Client s3;
    private final SqsClient sqs;
    private final KmsClient kms;
    private final EventBridgeClient eb;
    private final ObjectMapper mapper = new ObjectMapper();

    @Value("${cloudlearn.bucket}")
    private String bucket;
    @Value("${cloudlearn.queue-name}")
    private String queueName;
    @Value("${cloudlearn.event-bus}")
    private String eventBus;
    @Value("${cloudlearn.kms-key-id}")
    private String kmsKeyId;

    public OrdersController(JdbcTemplate jdbc, S3Client s3, SqsClient sqs,
                            KmsClient kms, EventBridgeClient eb) {
        this.jdbc = jdbc;
        this.s3 = s3;
        this.sqs = sqs;
        this.kms = kms;
        this.eb = eb;
    }

    // ---- POST /orders -----------------------------------------------------
    @PostMapping("/orders")
    public Map<String, Object> create(@RequestBody Map<String, Object> body) throws Exception {
        String customer = (String) body.getOrDefault("customer", "anonymous");
        long totalCents = ((Number) body.getOrDefault("total_cents", 0)).longValue();
        String cc = (String) body.getOrDefault("cc", "");

        // 1. Encrypt the credit card via KMS (Vault transit under the hood).
        String ccEnc = null;
        if (!cc.isEmpty()) {
            var encR = kms.encrypt(EncryptRequest.builder()
                    .keyId(kmsKeyId)
                    .plaintext(SdkBytes.fromUtf8String(cc))
                    .build());
            ccEnc = encR.ciphertextBlob().asString(java.nio.charset.StandardCharsets.UTF_8);
        }

        // 2. INSERT into RDS Postgres.
        final String ccEncFinal = ccEnc;
        long id = jdbc.queryForObject(
                "INSERT INTO orders(customer, total_cents, cc_enc) VALUES (?, ?, ?) RETURNING id",
                Long.class, customer, totalCents, ccEncFinal);

        // 3. Publish OrderCreated to EventBridge (NATS broker).
        eb.putEvents(PutEventsRequest.builder()
                .entries(PutEventsRequestEntry.builder()
                        .source("cloudlearn.orders")
                        .detailType("OrderCreated")
                        .eventBusName(eventBus)
                        .detail(mapper.writeValueAsString(Map.of(
                                "order_id", id,
                                "customer", customer,
                                "total_cents", totalCents)))
                        .build())
                .build());

        // 4. Enqueue async job to SQS (ElasticMQ).
        String qurl = ensureQueueUrl();
        sqs.sendMessage(SendMessageRequest.builder()
                .queueUrl(qurl)
                .messageBody(mapper.writeValueAsString(Map.of("order_id", id, "action", "process")))
                .build());

        log.info("Created order id={} customer={} total_cents={}", id, customer, totalCents);
        return Map.of("id", id, "customer", customer, "total_cents", totalCents);
    }

    // ---- GET /orders ------------------------------------------------------
    @GetMapping("/orders")
    public List<Map<String, Object>> list() {
        return jdbc.queryForList("SELECT id, customer, total_cents, created_at FROM orders ORDER BY id DESC");
    }

    @GetMapping("/orders/{id}")
    public ResponseEntity<Map<String, Object>> get(@PathVariable("id") long id) {
        var rows = jdbc.queryForList(
                "SELECT id, customer, total_cents, cc_enc, created_at FROM orders WHERE id = ?", id);
        if (rows.isEmpty()) return ResponseEntity.notFound().build();
        return ResponseEntity.ok(rows.get(0));
    }

    // ---- GET /orders/{id}/receipt → S3 ------------------------------------
    @GetMapping("/orders/{id}/receipt")
    public Map<String, Object> receipt(@PathVariable("id") long id) {
        var rows = jdbc.queryForList("SELECT customer, total_cents FROM orders WHERE id = ?", id);
        if (rows.isEmpty()) throw new RuntimeException("order not found: " + id);
        var row = rows.get(0);
        String html = String.format(
                "<!doctype html><html><body><h1>Receipt #%d</h1>" +
                "<p>Customer: <b>%s</b></p>" +
                "<p>Total: $%.2f</p></body></html>",
                id, row.get("customer"),
                ((Number) row.get("total_cents")).doubleValue() / 100.0);

        String key = "receipts/" + id + ".html";
        s3.putObject(PutObjectRequest.builder()
                        .bucket(bucket).key(key).contentType("text/html").build(),
                software.amazon.awssdk.core.sync.RequestBody.fromString(html));
        String url = s3.utilities().getUrl(GetUrlRequest.builder()
                .bucket(bucket).key(key).build()).toString();
        log.info("Receipt for order {} uploaded to s3://{}/{}", id, bucket, key);
        return Map.of("order_id", id, "receipt_url", url, "size_bytes", html.length());
    }

    // ---- GET /health → 5-way readiness ------------------------------------
    @GetMapping("/health")
    public Map<String, Object> health() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("db",            check("db",   () -> jdbc.queryForObject("SELECT 1", Integer.class) == 1));
        result.put("s3",            check("s3",   () -> { s3.headBucket(b -> b.bucket(bucket)); return true; }));
        result.put("kms",           check("kms",  () -> { kms.describeKey(d -> d.keyId(kmsKeyId)); return true; }));
        result.put("sqs",           check("sqs",  () -> { ensureQueueUrl(); return true; }));
        result.put("eventbridge",   check("eb",   () -> { eb.listEventBuses(b -> {}); return true; }));
        result.put("status", result.values().stream()
                .allMatch(v -> v instanceof Map<?, ?> m && Boolean.TRUE.equals(m.get("ok")))
                ? "UP" : "DEGRADED");
        return result;
    }

    private Map<String, Object> check(String name, java.util.concurrent.Callable<Boolean> probe) {
        try {
            boolean ok = probe.call();
            return Map.of("ok", ok);
        } catch (Exception e) {
            return Map.of("ok", false, "error", e.getMessage());
        }
    }

    private String ensureQueueUrl() {
        try {
            return sqs.getQueueUrl(b -> b.queueName(queueName)).queueUrl();
        } catch (software.amazon.awssdk.services.sqs.model.QueueDoesNotExistException e) {
            sqs.createQueue(b -> b.queueName(queueName));
            return sqs.getQueueUrl(b -> b.queueName(queueName)).queueUrl();
        }
    }
}
