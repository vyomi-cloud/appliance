package cloud.vyomi.probe;

import org.springframework.stereotype.Component;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.core.ResponseBytes;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.services.dynamodb.model.*;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.*;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * AWS path — drives the native AWS SDK for Java v2 against the appliance's
 * S3 + DynamoDB surfaces. Exercises a wide slice of each SDK so a green run is
 * strong evidence of wire compatibility.
 */
@Component
public class AwsProbe implements CloudProbe {

    private final String endpoint = ProbeEnv.endpoint();   // http://<appliance>:9000
    private final Region region = Region.of(System.getenv().getOrDefault("AWS_REGION", "us-east-1"));
    private final StaticCredentialsProvider creds =
            StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test"));

    @Override public String cloud() { return "aws"; }

    private S3Client s3() {
        return S3Client.builder()
                .endpointOverride(URI.create(endpoint))
                .region(region)
                .credentialsProvider(creds)
                .forcePathStyle(true)   // S3-compatible (MinIO-backed) endpoint
                .build();
    }

    private DynamoDbClient ddb() {
        return DynamoDbClient.builder()
                .endpointOverride(URI.create(endpoint))
                .region(region)
                .credentialsProvider(creds)
                .build();
    }

    @Override
    public Map<String, Object> probe() {
        Report r = new Report("aws");
        r.step("endpoint", true, endpoint);
        s3Lifecycle(r);
        dynamoLifecycle(r);
        return r.toMap();
    }

    // ── S3 (object store) ───────────────────────────────────────────────────
    private void s3Lifecycle(Report r) {
        String bucket = "cloud-probe-" + UUID.randomUUID().toString().substring(0, 12);
        String key = "probe/obj-" + UUID.randomUUID() + ".bin";
        byte[] payload = ("vyomi-cloud-probe-" + UUID.randomUUID()).getBytes(StandardCharsets.UTF_8);
        S3Client s3 = null;
        boolean created = false, put = false;
        try {
            s3 = s3();
            s3.createBucket(CreateBucketRequest.builder().bucket(bucket).build());
            s3.waiter().waitUntilBucketExists(HeadBucketRequest.builder().bucket(bucket).build());
            created = true;
            r.step("s3.createBucket", true, bucket);

            s3.putObject(PutObjectRequest.builder().bucket(bucket).key(key)
                            .contentType("application/octet-stream").build(),
                    RequestBody.fromBytes(payload));
            put = true;
            r.step("s3.putObject", true, key + " (" + payload.length + "B)");

            ResponseBytes<GetObjectResponse> got = s3.getObjectAsBytes(
                    GetObjectRequest.builder().bucket(bucket).key(key).build());
            boolean match = Arrays.equals(payload, got.asByteArray());
            r.step("s3.getObject+verify", match, match ? "bytes match" : "BYTE MISMATCH");

            HeadObjectResponse head = s3.headObject(HeadObjectRequest.builder().bucket(bucket).key(key).build());
            r.step("s3.headObject", head.contentLength() == payload.length,
                    "contentLength=" + head.contentLength());

            ListObjectsV2Response list = s3.listObjectsV2(
                    ListObjectsV2Request.builder().bucket(bucket).prefix("probe/").build());
            boolean found = list.contents().stream().anyMatch(o -> o.key().equals(key));
            r.step("s3.listObjectsV2", found, "objects=" + list.keyCount());

            boolean bucketListed = s3.listBuckets().buckets().stream()
                    .anyMatch(b -> b.name().equals(bucket));
            r.step("s3.listBuckets", bucketListed, "bucket visible=" + bucketListed);
        } catch (Exception e) {
            r.step("s3.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (s3 != null) {
                if (put) try { s3.deleteObject(DeleteObjectRequest.builder().bucket(bucket).key(key).build());
                      r.step("s3.deleteObject", true, "cleaned up"); }
                    catch (Exception e) { r.step("s3.deleteObject", false, e.getMessage()); }
                if (created) try { s3.deleteBucket(DeleteBucketRequest.builder().bucket(bucket).build());
                      r.step("s3.deleteBucket", true, "cleaned up"); }
                    catch (Exception e) { r.step("s3.deleteBucket", false, e.getMessage()); }
                s3.close();
            }
        }
    }

    // ── DynamoDB (NoSQL) ────────────────────────────────────────────────────
    private void dynamoLifecycle(Report r) {
        String table = "cloud_probe_" + UUID.randomUUID().toString().substring(0, 12).replace('-', '_');
        String id = "item-" + UUID.randomUUID();
        DynamoDbClient ddb = null;
        boolean created = false, put = false;
        try {
            ddb = ddb();
            ddb.createTable(CreateTableRequest.builder().tableName(table)
                    .billingMode(BillingMode.PAY_PER_REQUEST)
                    .attributeDefinitions(AttributeDefinition.builder()
                            .attributeName("id").attributeType(ScalarAttributeType.S).build())
                    .keySchema(KeySchemaElement.builder()
                            .attributeName("id").keyType(KeyType.HASH).build())
                    .build());
            ddb.waiter().waitUntilTableExists(DescribeTableRequest.builder().tableName(table).build());
            created = true;
            r.step("dynamodb.createTable", true, table);

            ddb.putItem(PutItemRequest.builder().tableName(table).item(Map.of(
                    "id", AttributeValue.fromS(id),
                    "msg", AttributeValue.fromS("hello-vyomi"),
                    "n", AttributeValue.fromN("1"))).build());
            put = true;
            r.step("dynamodb.putItem", true, id);

            GetItemResponse get = ddb.getItem(GetItemRequest.builder().tableName(table)
                    .key(Map.of("id", AttributeValue.fromS(id))).consistentRead(true).build());
            boolean match = get.hasItem() && "hello-vyomi".equals(get.item().get("msg").s());
            r.step("dynamodb.getItem+verify", match, match ? "msg matches" : "MISMATCH/empty");

            ddb.updateItem(UpdateItemRequest.builder().tableName(table)
                    .key(Map.of("id", AttributeValue.fromS(id)))
                    .updateExpression("SET #n = :two")
                    .expressionAttributeNames(Map.of("#n", "n"))
                    .expressionAttributeValues(Map.of(":two", AttributeValue.fromN("2"))).build());
            GetItemResponse after = ddb.getItem(GetItemRequest.builder().tableName(table)
                    .key(Map.of("id", AttributeValue.fromS(id))).consistentRead(true).build());
            r.step("dynamodb.updateItem", "2".equals(after.item().get("n").n()),
                    "n=" + after.item().get("n").n());

            QueryResponse q = ddb.query(QueryRequest.builder().tableName(table)
                    .keyConditionExpression("id = :id")
                    .expressionAttributeValues(Map.of(":id", AttributeValue.fromS(id))).build());
            r.step("dynamodb.query", q.count() == 1, "count=" + q.count());

            ScanResponse scan = ddb.scan(ScanRequest.builder().tableName(table).build());
            r.step("dynamodb.scan", scan.count() >= 1, "scanned=" + scan.count());
        } catch (Exception e) {
            r.step("dynamodb.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (ddb != null) {
                if (put) try { ddb.deleteItem(DeleteItemRequest.builder().tableName(table)
                        .key(Map.of("id", AttributeValue.fromS(id))).build());
                      r.step("dynamodb.deleteItem", true, "cleaned up"); }
                    catch (Exception e) { r.step("dynamodb.deleteItem", false, e.getMessage()); }
                if (created) try { ddb.deleteTable(DeleteTableRequest.builder().tableName(table).build());
                      r.step("dynamodb.deleteTable", true, "cleaned up"); }
                    catch (Exception e) { r.step("dynamodb.deleteTable", false, e.getMessage()); }
                ddb.close();
            }
        }
    }
}
