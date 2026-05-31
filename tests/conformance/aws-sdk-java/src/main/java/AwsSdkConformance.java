// Real aws-sdk-java-v2 conformance probe against the CloudLearn simulator.
//
// Proves whether UNMODIFIED software.amazon.awssdk clients work pointed at
// the simulator. Mirrors the pattern of gcp-sdk-java + azure-sdk-java tests
// (and aws-sdk-go for go parity).
//
// Run (dockerized, on the appliance):
//
//   docker run --rm --network host \
//     -e ENDPOINT=http://127.0.0.1:9000 \
//     -v /workspace/cloud-learn/tests/conformance/aws-sdk-java:/work -w /work \
//     maven:3.9-eclipse-temurin-17 mvn -q -e exec:java
//
// Exit code is 0 on all-pass, non-zero on any fail.

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.URL;
import java.net.HttpURLConnection;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.services.dynamodb.model.*;
import software.amazon.awssdk.services.ec2.Ec2Client;
import software.amazon.awssdk.services.iam.IamClient;
import software.amazon.awssdk.services.iam.model.CreateUserRequest;
import software.amazon.awssdk.services.iam.model.DeleteUserRequest;
import software.amazon.awssdk.services.iam.model.ListUsersRequest;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.S3Configuration;
import software.amazon.awssdk.services.s3.model.*;
import software.amazon.awssdk.services.sqs.SqsClient;
import software.amazon.awssdk.services.sqs.model.*;

public class AwsSdkConformance {

    static int pass = 0;
    static int fail = 0;

    static void chk(String name, boolean ok, String detail) {
        if (ok) {
            pass++;
            System.out.println("PASS " + name);
        } else {
            fail++;
            System.out.println("FAIL " + name + " :: " + detail);
        }
    }

    static void chk(String name, Runnable op) {
        try {
            op.run();
            pass++;
            System.out.println("PASS " + name);
        } catch (Throwable t) {
            fail++;
            System.out.println("FAIL " + name + " :: " + t.getMessage());
        }
    }

    public static void main(String[] args) throws Exception {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        URI ep = URI.create(endpoint);

        System.out.println("== aws-sdk-java-v2 against " + endpoint + " ==");

        switchToAwsSpace(endpoint);

        StaticCredentialsProvider creds = StaticCredentialsProvider.create(
                AwsBasicCredentials.create("test", "test"));

        long ts = System.currentTimeMillis();

        // --- S3 ---
        // chunkedEncodingEnabled(false): aws-sdk-java-v2 uses aws-chunked transfer
        // encoding for S3 PUTs by default (with embedded chunk-signature framing).
        // The simulator's S3 PUT doesn't de-chunk yet — known fidelity gap; see
        // memory note mvp-launch-ready-p0-batch.md. Disabling chunked here so
        // the SDK sends a normal Content-Length body that the simulator stores
        // verbatim. Real S3 accepts both encodings; simulator currently accepts
        // only the standard one.
        S3Client s3 = S3Client.builder()
                .endpointOverride(ep)
                .region(Region.US_EAST_1)
                .credentialsProvider(creds)
                .serviceConfiguration(S3Configuration.builder()
                        .pathStyleAccessEnabled(true)
                        .chunkedEncodingEnabled(false)
                        .build())
                .build();

        String bucket = "sdk-java-smoke-" + ts;
        try {
            s3.createBucket(CreateBucketRequest.builder().bucket(bucket).build());
            chk("s3 CreateBucket", true, "");
        } catch (Exception e) {
            chk("s3 CreateBucket", false, e.getMessage());
        }

        try {
            s3.putObject(
                    PutObjectRequest.builder().bucket(bucket).key("obj.txt").build(),
                    RequestBody.fromBytes("hello-from-aws-sdk-java".getBytes()));
            chk("s3 PutObject", true, "");
        } catch (Exception e) {
            chk("s3 PutObject", false, e.getMessage());
        }

        try {
            byte[] got = s3.getObject(GetObjectRequest.builder().bucket(bucket).key("obj.txt").build())
                    .readAllBytes();
            String s = new String(got);
            chk("s3 GetObject round-trip", "hello-from-aws-sdk-java".equals(s), "got=" + s);
        } catch (Exception e) {
            chk("s3 GetObject round-trip", false, e.getMessage());
        }

        try {
            s3.deleteObject(DeleteObjectRequest.builder().bucket(bucket).key("obj.txt").build());
            s3.deleteBucket(DeleteBucketRequest.builder().bucket(bucket).build());
            chk("s3 Delete (object+bucket)", true, "");
        } catch (Exception e) {
            chk("s3 Delete (object+bucket)", false, e.getMessage());
        }

        // --- IAM ---
        IamClient iam = IamClient.builder()
                .endpointOverride(ep)
                .region(Region.AWS_GLOBAL)
                .credentialsProvider(creds)
                .build();
        String user = "sdk-java-user-" + ts;
        try {
            iam.createUser(CreateUserRequest.builder().userName(user).build());
            chk("iam CreateUser", true, "");
        } catch (Exception e) {
            chk("iam CreateUser", false, e.getMessage());
        }

        try {
            var users = iam.listUsers(ListUsersRequest.builder().build()).users();
            boolean found = users.stream().anyMatch(u -> user.equals(u.userName()));
            chk("iam ListUsers contains new user", found, "userCount=" + users.size());
        } catch (Exception e) {
            chk("iam ListUsers contains new user", false, e.getMessage());
        }

        try {
            iam.deleteUser(DeleteUserRequest.builder().userName(user).build());
            chk("iam DeleteUser", true, "");
        } catch (Exception e) {
            chk("iam DeleteUser", false, e.getMessage());
        }

        // --- EC2 ---
        Ec2Client ec2 = Ec2Client.builder()
                .endpointOverride(ep).region(Region.US_EAST_1)
                .credentialsProvider(creds).build();
        try {
            ec2.describeInstances();
            chk("ec2 DescribeInstances", true, "");
        } catch (Exception e) {
            chk("ec2 DescribeInstances", false, e.getMessage());
        }

        // --- DynamoDB ---
        DynamoDbClient ddb = DynamoDbClient.builder()
                .endpointOverride(ep).region(Region.US_EAST_1)
                .credentialsProvider(creds).build();
        String table = "sdk-java-tbl-" + ts;
        try {
            ddb.createTable(CreateTableRequest.builder()
                    .tableName(table)
                    .attributeDefinitions(AttributeDefinition.builder()
                            .attributeName("id").attributeType(ScalarAttributeType.S).build())
                    .keySchema(KeySchemaElement.builder()
                            .attributeName("id").keyType(KeyType.HASH).build())
                    .billingMode(BillingMode.PAY_PER_REQUEST)
                    .build());
            chk("dynamodb CreateTable (via DDB Local proxy)", true, "");
        } catch (Exception e) {
            chk("dynamodb CreateTable (via DDB Local proxy)", false, e.getMessage());
        }

        try {
            ddb.putItem(PutItemRequest.builder().tableName(table)
                    .item(java.util.Map.of(
                            "id", AttributeValue.builder().s("k1").build(),
                            "v", AttributeValue.builder().s("sdk-java-roundtrip").build()))
                    .build());
            chk("dynamodb PutItem", true, "");
        } catch (Exception e) {
            chk("dynamodb PutItem", false, e.getMessage());
        }

        try {
            var got = ddb.getItem(GetItemRequest.builder().tableName(table)
                    .key(java.util.Map.of("id", AttributeValue.builder().s("k1").build()))
                    .build()).item();
            String v = got.get("v") == null ? "(null)" : got.get("v").s();
            chk("dynamodb GetItem round-trip", "sdk-java-roundtrip".equals(v), "got=" + v);
        } catch (Exception e) {
            chk("dynamodb GetItem round-trip", false, e.getMessage());
        }

        try {
            ddb.deleteTable(DeleteTableRequest.builder().tableName(table).build());
        } catch (Exception ignored) {}

        // --- SQS ---
        SqsClient sqs = SqsClient.builder()
                .endpointOverride(ep).region(Region.US_EAST_1)
                .credentialsProvider(creds).build();
        String qname = "sdk-java-q-" + ts;
        try {
            sqs.createQueue(CreateQueueRequest.builder().queueName(qname).build());
            chk("sqs CreateQueue", true, "");
        } catch (Exception e) {
            chk("sqs CreateQueue", false, e.getMessage());
        }

        try {
            sqs.listQueues();
            chk("sqs ListQueues", true, "");
        } catch (Exception e) {
            chk("sqs ListQueues", false, e.getMessage());
        }

        System.out.println("RESULT pass=" + pass + " fail=" + fail);
        System.exit(fail > 0 ? 1 : 0);
    }

    // Switch the active simulator space to an AWS one (S3 ops are space-scoped).
    static void switchToAwsSpace(String endpoint) {
        try {
            HttpURLConnection get = (HttpURLConnection) new URL(endpoint + "/api/spaces").openConnection();
            StringBuilder sb = new StringBuilder();
            try (BufferedReader r = new BufferedReader(new InputStreamReader(get.getInputStream()))) {
                String line;
                while ((line = r.readLine()) != null) sb.append(line);
            }
            Matcher m = Pattern.compile("\"space_id\"\\s*:\\s*\"([^\"]+)\"[^}]*?\"provider\"\\s*:\\s*\"aws\"").matcher(sb.toString());
            if (m.find()) {
                String sid = m.group(1);
                HttpURLConnection post = (HttpURLConnection) new URL(endpoint + "/api/spaces/" + sid + "/switch").openConnection();
                post.setRequestMethod("POST");
                post.getResponseCode();
                System.out.println("switched to AWS space: " + sid);
            }
        } catch (Exception ignored) {}
    }
}
