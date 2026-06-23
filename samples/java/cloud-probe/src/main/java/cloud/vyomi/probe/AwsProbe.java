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
import software.amazon.awssdk.core.SdkBytes;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.CreateQueueRequest;
import software.amazon.awssdk.services.sqs.model.CreateQueueResponse;
import software.amazon.awssdk.services.sqs.model.DeleteMessageRequest;
import software.amazon.awssdk.services.sqs.model.DeleteQueueRequest;
import software.amazon.awssdk.services.sqs.model.ReceiveMessageRequest;
import software.amazon.awssdk.services.sqs.model.ReceiveMessageResponse;
import software.amazon.awssdk.services.sqs.model.SendMessageRequest;
import software.amazon.awssdk.services.secretsmanager.SecretsManagerClient;
import software.amazon.awssdk.services.secretsmanager.model.CreateSecretRequest;
import software.amazon.awssdk.services.secretsmanager.model.DeleteSecretRequest;
import software.amazon.awssdk.services.secretsmanager.model.GetSecretValueRequest;
import software.amazon.awssdk.services.secretsmanager.model.GetSecretValueResponse;
import software.amazon.awssdk.services.ec2.Ec2Client;
import software.amazon.awssdk.services.ec2.model.RunInstancesResponse;
import software.amazon.awssdk.services.ec2.model.DescribeInstancesResponse;
import software.amazon.awssdk.services.ec2.model.InstanceType;
import software.amazon.awssdk.services.rds.RdsClient;
import software.amazon.awssdk.services.rds.model.DescribeDbInstancesResponse;
import software.amazon.awssdk.services.kms.KmsClient;
import software.amazon.awssdk.services.kms.model.CreateKeyRequest;
import software.amazon.awssdk.services.kms.model.CreateKeyResponse;
import software.amazon.awssdk.services.kms.model.DecryptRequest;
import software.amazon.awssdk.services.kms.model.DecryptResponse;
import software.amazon.awssdk.services.kms.model.EncryptRequest;
import software.amazon.awssdk.services.kms.model.EncryptResponse;
import software.amazon.awssdk.services.kms.model.ScheduleKeyDeletionRequest;

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

    private Ec2Client ec2() {
        return Ec2Client.builder()
                .endpointOverride(URI.create(endpoint))
                .region(region)
                .credentialsProvider(creds)
                .build();
    }

    private RdsClient rds() {
        return RdsClient.builder()
                .endpointOverride(URI.create(endpoint))
                .region(region)
                .credentialsProvider(creds)
                .build();
    }

    // ── EC2 (compute) lifecycle via native SDK ──────────────────────────────
    // RunInstances launches a real instance on the appliance's compute backend
    // (Multipass/LXD on CloudMax, Docker on CloudLite+). We verify via
    // DescribeInstances and always terminate. We do NOT wait for "running"
    // (compute provisioning takes minutes) — the API round-trip + a live
    // instance record is the conformance signal.
    @Override
    public Map<String, Object> probeCompute() {
        Report r = new Report("aws");
        r.step("endpoint", true, endpoint);
        String amiId = System.getenv().getOrDefault("CLOUDPROBE_EC2_AMI", "ami-amzn2023-x86_64");
        String instanceId = null;
        try (Ec2Client ec2 = ec2()) {
            ec2.describeInstances();
            r.step("ec2.describeInstances", true, "");
            RunInstancesResponse run = ec2.runInstances(b -> b
                    .imageId(amiId).instanceType(InstanceType.T3_MICRO)
                    .minCount(1).maxCount(1));
            instanceId = run.instances().isEmpty() ? null : run.instances().get(0).instanceId();
            r.step("ec2.runInstances", instanceId != null && !instanceId.isBlank(), String.valueOf(instanceId));
            if (instanceId != null) {
                final String iid = instanceId;
                DescribeInstancesResponse d = ec2.describeInstances(b -> b.instanceIds(iid));
                boolean found = d.reservations().stream().anyMatch(res -> !res.instances().isEmpty());
                r.step("ec2.describeInstances.verify", found, instanceId);
            }
        } catch (Exception e) {
            r.step("ec2.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (instanceId != null) {
                final String id = instanceId;
                try (Ec2Client ec2 = ec2()) {
                    ec2.terminateInstances(b -> b.instanceIds(id));
                    r.step("ec2.terminateInstances", true, id);
                } catch (Exception e) {
                    r.step("ec2.terminateInstances", false, e.getMessage());
                }
            }
        }
        return r.toMap();
    }

    // ── RDS (managed DB) lifecycle via native SDK ───────────────────────────
    // CreateDBInstance provisions a managed Postgres on the appliance; verify
    // via DescribeDBInstances and always delete (skipFinalSnapshot). Like EC2,
    // we don't block on "available" — create/describe/delete is the conformance.
    @Override
    public Map<String, Object> probeDatabase() {
        Report r = new Report("aws");
        r.step("endpoint", true, endpoint);
        String dbId = "cloud-probe-" + UUID.randomUUID().toString().substring(0, 8);
        boolean created = false;
        try (RdsClient rds = rds()) {
            rds.describeDBInstances();
            r.step("rds.describeDBInstances", true, "");
            rds.createDBInstance(b -> b
                    .dbInstanceIdentifier(dbId).engine("postgres")
                    .dbInstanceClass("db.t3.micro").allocatedStorage(20)
                    .masterUsername("vyomi").masterUserPassword("Probe-passw0rd-1"));
            created = true;
            r.step("rds.createDBInstance", true, dbId);
            DescribeDbInstancesResponse d = rds.describeDBInstances(b -> b.dbInstanceIdentifier(dbId));
            r.step("rds.describeDBInstances.verify", !d.dbInstances().isEmpty(), dbId);
        } catch (Exception e) {
            r.step("rds.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (created) {
                try (RdsClient rds = rds()) {
                    rds.deleteDBInstance(b -> b.dbInstanceIdentifier(dbId)
                            .skipFinalSnapshot(true).deleteAutomatedBackups(true));
                    r.step("rds.deleteDBInstance", true, dbId);
                } catch (Exception e) {
                    r.step("rds.deleteDBInstance", false, e.getMessage());
                }
            }
        }
        return r.toMap();
    }

    @Override
    public Map<String, Object> probe() {
        Report r = new Report("aws");
        r.step("endpoint", true, endpoint);
        s3Lifecycle(r);
        dynamoLifecycle(r);
        return r.toMap();
    }

    @Override
    public Map<String, Object> getObject(String bucket, String key) {
        try (S3Client s3 = s3()) {
            ResponseBytes<GetObjectResponse> got = s3.getObjectAsBytes(
                    GetObjectRequest.builder().bucket(bucket).key(key).build());
            return ObjectResult.of("aws", bucket, key, got.asByteArray(), got.response().contentType());
        } catch (Exception e) {
            return ObjectResult.error("aws", bucket, key, e);
        }
    }

    // ── DynamoDB (NoSQL) read/write via native SDK ──────────────────────────
    @Override
    public Map<String, Object> getItem(String table, String id, String namespace) {
        try (DynamoDbClient ddb = ddb()) {
            GetItemResponse got = ddb.getItem(GetItemRequest.builder().tableName(table)
                    .key(Map.of("id", AttributeValue.fromS(id))).consistentRead(true).build());
            if (!got.hasItem() || got.item().isEmpty())
                return NoSqlResult.error("aws", table, id, new RuntimeException("item not found"));
            return NoSqlResult.of("aws", table, id, flattenItem(got.item()));
        } catch (Exception e) {
            return NoSqlResult.error("aws", table, id, e);
        }
    }

    @Override
    public Map<String, Object> putItem(String table, String id, String namespace) {
        try (DynamoDbClient ddb = ddb()) {
            ensureTable(ddb, table);
            ddb.putItem(PutItemRequest.builder().tableName(table).item(Map.of(
                    "id",  AttributeValue.fromS(id),
                    "msg", AttributeValue.fromS("hello-vyomi"),
                    "n",   AttributeValue.fromN("1"))).build());
            return getItem(table, id, namespace);
        } catch (Exception e) {
            return NoSqlResult.error("aws", table, id, e);
        }
    }

    private void ensureTable(DynamoDbClient ddb, String table) {
        try {
            ddb.describeTable(DescribeTableRequest.builder().tableName(table).build());
        } catch (ResourceNotFoundException nf) {
            ddb.createTable(CreateTableRequest.builder().tableName(table)
                    .billingMode(BillingMode.PAY_PER_REQUEST)
                    .attributeDefinitions(AttributeDefinition.builder()
                            .attributeName("id").attributeType(ScalarAttributeType.S).build())
                    .keySchema(KeySchemaElement.builder()
                            .attributeName("id").keyType(KeyType.HASH).build())
                    .build());
            ddb.waiter().waitUntilTableExists(DescribeTableRequest.builder().tableName(table).build());
        }
    }

    private static Map<String, Object> flattenItem(Map<String, AttributeValue> item) {
        Map<String, Object> out = new java.util.LinkedHashMap<>();
        item.forEach((k, v) -> {
            if (v.s() != null) out.put(k, v.s());
            else if (v.n() != null) out.put(k, v.n());
            else if (v.bool() != null) out.put(k, v.bool());
            else out.put(k, v.toString());
        });
        return out;
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

    // ── SQS / Secrets Manager / KMS clients (all HTTP+SigV4 via endpointOverride) ─
    private SqsClient sqs() {
        return SqsClient.builder().endpointOverride(URI.create(endpoint))
                .region(region).credentialsProvider(creds).build();
    }
    private SecretsManagerClient secrets() {
        return SecretsManagerClient.builder().endpointOverride(URI.create(endpoint))
                .region(region).credentialsProvider(creds).build();
    }
    private KmsClient kms() {
        return KmsClient.builder().endpointOverride(URI.create(endpoint))
                .region(region).credentialsProvider(creds).build();
    }

    // ── SQS (messaging) ─────────────────────────────────────────────────────
    @Override
    public Map<String, Object> probeQueue() {
        Report r = new Report("aws");
        r.step("endpoint", true, endpoint);
        String qname = "cloud-probe-" + UUID.randomUUID().toString().substring(0, 12);
        SqsClient sqs = null;
        String queueUrl = null;
        try {
            sqs = sqs();
            CreateQueueResponse cq = sqs.createQueue(CreateQueueRequest.builder().queueName(qname).build());
            queueUrl = cq.queueUrl();
            r.step("sqs.createQueue", true, queueUrl);

            String body = "hello-vyomi-" + UUID.randomUUID();
            sqs.sendMessage(SendMessageRequest.builder().queueUrl(queueUrl).messageBody(body).build());
            r.step("sqs.sendMessage", true, body);

            ReceiveMessageResponse rcv = sqs.receiveMessage(ReceiveMessageRequest.builder()
                    .queueUrl(queueUrl).maxNumberOfMessages(1).waitTimeSeconds(2).build());
            boolean got = !rcv.messages().isEmpty() && body.equals(rcv.messages().get(0).body());
            r.step("sqs.receiveMessage+verify", got, got ? "body matches" : "MISMATCH/empty");

            if (got) {
                sqs.deleteMessage(DeleteMessageRequest.builder().queueUrl(queueUrl)
                        .receiptHandle(rcv.messages().get(0).receiptHandle()).build());
                r.step("sqs.deleteMessage", true, "acked");
            }
        } catch (Exception e) {
            r.step("sqs.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (sqs != null) {
                if (queueUrl != null) try { sqs.deleteQueue(DeleteQueueRequest.builder().queueUrl(queueUrl).build());
                      r.step("sqs.deleteQueue", true, "cleaned up"); }
                    catch (Exception e) { r.step("sqs.deleteQueue", false, e.getMessage()); }
                sqs.close();
            }
        }
        return r.toMap();
    }

    // ── Secrets Manager ─────────────────────────────────────────────────────
    @Override
    public Map<String, Object> probeSecret() {
        Report r = new Report("aws");
        r.step("endpoint", true, endpoint);
        String name = "cloud-probe-" + UUID.randomUUID().toString().substring(0, 12);
        SecretsManagerClient sm = null;
        boolean created = false;
        try {
            sm = secrets();
            sm.createSecret(CreateSecretRequest.builder().name(name).secretString("hello-vyomi").build());
            created = true;
            r.step("secretsmanager.createSecret", true, name);

            GetSecretValueResponse got = sm.getSecretValue(
                    GetSecretValueRequest.builder().secretId(name).build());
            boolean match = "hello-vyomi".equals(got.secretString());
            r.step("secretsmanager.getSecretValue+verify", match, match ? "value matches" : "MISMATCH");
        } catch (Exception e) {
            r.step("secretsmanager.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (sm != null) {
                if (created) try { sm.deleteSecret(DeleteSecretRequest.builder()
                        .secretId(name).forceDeleteWithoutRecovery(true).build());
                      r.step("secretsmanager.deleteSecret", true, "cleaned up"); }
                    catch (Exception e) { r.step("secretsmanager.deleteSecret", false, e.getMessage()); }
                sm.close();
            }
        }
        return r.toMap();
    }

    // ── KMS ─────────────────────────────────────────────────────────────────
    @Override
    public Map<String, Object> probeKms() {
        Report r = new Report("aws");
        r.step("endpoint", true, endpoint);
        KmsClient kms = null;
        String keyId = null;
        try {
            kms = kms();
            CreateKeyResponse ck = kms.createKey(CreateKeyRequest.builder().description("cloud-probe").build());
            keyId = ck.keyMetadata().keyId();
            r.step("kms.createKey", true, keyId);

            SdkBytes plaintext = SdkBytes.fromUtf8String("hello-vyomi");
            EncryptResponse enc = kms.encrypt(EncryptRequest.builder().keyId(keyId).plaintext(plaintext).build());
            int ctLen = enc.ciphertextBlob() == null ? 0 : enc.ciphertextBlob().asByteArray().length;
            r.step("kms.encrypt", ctLen > 0, "ciphertext=" + ctLen + "B");

            DecryptResponse dec = kms.decrypt(DecryptRequest.builder()
                    .keyId(keyId).ciphertextBlob(enc.ciphertextBlob()).build());
            boolean match = "hello-vyomi".equals(dec.plaintext().asUtf8String());
            r.step("kms.decrypt+verify", match, match ? "plaintext round-trips" : "MISMATCH");
        } catch (Exception e) {
            r.step("kms.lifecycle", false, e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            if (kms != null) {
                if (keyId != null) try { kms.scheduleKeyDeletion(ScheduleKeyDeletionRequest.builder()
                        .keyId(keyId).pendingWindowInDays(7).build());
                      r.step("kms.scheduleKeyDeletion", true, "scheduled (7d)"); }
                    catch (Exception e) { r.step("kms.scheduleKeyDeletion", false, e.getMessage()); }
                kms.close();
            }
        }
        return r.toMap();
    }
}
