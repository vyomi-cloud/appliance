// Real aws-sdk-java-v2 Amazon SNS conformance probe against Vyomi.
//
// Unmodified software.amazon.awssdk.services.sns with only the endpoint
// overridden. One [PASS]/[FAIL] line per check; exit code 1 on any failure.
//
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=SnsConformance

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.sns.SnsClient;
import software.amazon.awssdk.services.sns.model.*;

public class SnsConformance {

    static int pass = 0;
    static int fail = 0;

    static void chk(String name, boolean ok, String detail) {
        if (ok) {
            pass++;
            System.out.println("[PASS] " + name);
        } else {
            fail++;
            System.out.println("[FAIL] " + name + (detail == null || detail.isEmpty() ? "" : " :: " + detail));
        }
    }

    static void chk(String name, boolean ok) {
        chk(name, ok, "");
    }

    static <T> T run(String name, Supplier<T> fn) {
        try {
            T v = fn.get();
            chk(name, true, "");
            return v;
        } catch (Exception e) {
            chk(name, false, e.toString());
            return null;
        }
    }

    /** Expect the call to fail with the given error code. */
    static void expectError(String name, String code, Runnable fn) {
        try {
            fn.run();
            chk(name, false, "expected " + code + " but the call succeeded");
        } catch (SnsException e) {
            String got = e.awsErrorDetails() == null ? "" : e.awsErrorDetails().errorCode();
            chk(name, code.equals(got), "expected " + code + " got " + got);
        } catch (Exception e) {
            chk(name, false, e.toString());
        }
    }

    /** The appliance's SNS message log: where tokens / non-SQS deliveries are recorded. */
    static String deliveries(String endpoint) {
        try {
            HttpResponse<String> r = HttpClient.newHttpClient().send(
                    HttpRequest.newBuilder(URI.create(endpoint + "/api/aws/sns/deliveries")).build(),
                    HttpResponse.BodyHandlers.ofString());
            return r.body();
        } catch (Exception e) {
            return "";
        }
    }

    /** Token of the first log entry of this kind for this endpoint. */
    static String tokenFor(String log, String kind, String ep) {
        Matcher m = Pattern.compile("\\{[^{}]*\"kind\":\"" + kind + "\"[^{}]*\"endpoint\":\"" + Pattern.quote(ep)
                + "\"[^{}]*\"token\":\"([^\"]*)\"").matcher(log);
        return m.find() ? m.group(1) : "";
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        SnsClient sns = SnsClient.builder()
                .endpointOverride(URI.create(endpoint))
                .region(Region.US_EAST_1)
                .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
                .build();
        String sfx = Long.toString(System.currentTimeMillis() % 1000000);
        String name = "java-topic-" + sfx;

        // topics
        CreateTopicResponse ct = run("CreateTopic", () -> sns.createTopic(b -> b.name(name)
                .tags(Tag.builder().key("env").value("dev").build())));
        if (ct == null) System.exit(1);
        String arn = ct.topicArn();
        chk("topic ARN ends with the name", arn.endsWith(":" + name), arn);
        chk("CreateTopic is idempotent", sns.createTopic(b -> b.name(name)).topicArn().equals(arn));
        chk("ListTopics includes the topic", sns.listTopics().topics().stream().anyMatch(t -> t.topicArn().equals(arn)));
        Map<String, String> attrs = sns.getTopicAttributes(b -> b.topicArn(arn)).attributes();
        chk("GetTopicAttributes", arn.equals(attrs.get("TopicArn")) && attrs.get("Owner") != null && attrs.get("Policy") != null, attrs.toString());
        run("SetTopicAttributes DisplayName", () -> sns.setTopicAttributes(b -> b.topicArn(arn)
                .attributeName("DisplayName").attributeValue("Java topic")));
        chk("DisplayName stored", "Java topic".equals(sns.getTopicAttributes(b -> b.topicArn(arn)).attributes().get("DisplayName")));
        chk("tags from CreateTopic", sns.listTagsForResource(b -> b.resourceArn(arn)).tags().size() == 1);
        run("TagResource", () -> sns.tagResource(b -> b.resourceArn(arn).tags(Tag.builder().key("team").value("x").build())));
        run("UntagResource", () -> sns.untagResource(b -> b.resourceArn(arn).tagKeys("env")));
        List<Tag> tags = sns.listTagsForResource(b -> b.resourceArn(arn)).tags();
        chk("tags after tag/untag", tags.size() == 1 && tags.get(0).key().equals("team"), tags.toString());
        run("AddPermission", () -> sns.addPermission(b -> b.topicArn(arn).label("share")
                .awsAccountIds("111122223333").actionNames("Publish")));
        chk("policy has the new statement", sns.getTopicAttributes(b -> b.topicArn(arn)).attributes().get("Policy").contains("111122223333"));
        run("RemovePermission", () -> sns.removePermission(b -> b.topicArn(arn).label("share")));
        expectError("GetTopicAttributes on a missing topic", "NotFound", () -> sns.getTopicAttributes(b -> b.topicArn(arn + "-missing")));
        expectError("CreateTopic rejects a bad name", "InvalidParameter", () -> sns.createTopic(b -> b.name("bad name!")));
        String dp = "{\"Name\":\"p\",\"Version\":\"2021-06-01\",\"Statement\":[{\"DataDirection\":\"Inbound\",\"Principal\":[\"*\"],\"DataIdentifier\":[]}]}";
        run("PutDataProtectionPolicy", () -> sns.putDataProtectionPolicy(b -> b.resourceArn(arn).dataProtectionPolicy(dp)));
        chk("GetDataProtectionPolicy round-trips", sns.getDataProtectionPolicy(b -> b.resourceArn(arn)).dataProtectionPolicy().contains("\"Name\":\"p\""));

        // FIFO
        String fifo = "java-fifo-" + sfx + ".fifo";
        CreateTopicResponse cf = run("CreateTopic (FIFO)", () -> sns.createTopic(b -> b.name(fifo)
                .attributes(Map.of("FifoTopic", "true", "ContentBasedDeduplication", "true"))));
        if (cf != null) {
            String farn = cf.topicArn();
            expectError("FIFO publish needs MessageGroupId", "InvalidParameter", () -> sns.publish(b -> b.topicArn(farn).message("m")));
            PublishResponse p1 = sns.publish(b -> b.topicArn(farn).message("same").messageGroupId("g"));
            PublishResponse p2 = sns.publish(b -> b.topicArn(farn).message("same").messageGroupId("g"));
            chk("FIFO content-based dedup returns the same MessageId + SequenceNumber",
                    p1.messageId().equals(p2.messageId()) && p1.sequenceNumber() != null && !p1.sequenceNumber().isEmpty());
            run("DeleteTopic (FIFO)", () -> sns.deleteTopic(b -> b.topicArn(farn)));
        }

        // subscriptions: SQS endpoints are confirmed immediately
        String qarn = "arn:aws:sqs:us-east-1:123456789012:java-sns-q-" + sfx;
        SubscribeResponse sub = run("Subscribe (sqs)", () -> sns.subscribe(b -> b.topicArn(arn).protocol("sqs")
                .endpoint(qarn).returnSubscriptionArn(true)));
        if (sub != null) {
            String sarn = sub.subscriptionArn();
            chk("sqs subscription is confirmed", sarn.startsWith(arn + ":"), sarn);
            run("SetSubscriptionAttributes RawMessageDelivery", () -> sns.setSubscriptionAttributes(b -> b
                    .subscriptionArn(sarn).attributeName("RawMessageDelivery").attributeValue("true")));
            run("SetSubscriptionAttributes FilterPolicy", () -> sns.setSubscriptionAttributes(b -> b
                    .subscriptionArn(sarn).attributeName("FilterPolicy").attributeValue("{\"color\":[\"red\"]}")));
            Map<String, String> sa = sns.getSubscriptionAttributes(b -> b.subscriptionArn(sarn)).attributes();
            chk("GetSubscriptionAttributes", "sqs".equals(sa.get("Protocol")) && "true".equals(sa.get("RawMessageDelivery")) && sa.get("FilterPolicy") != null, sa.toString());
            expectError("SetSubscriptionAttributes rejects an unknown attribute", "InvalidParameter", () -> sns.setSubscriptionAttributes(b -> b
                    .subscriptionArn(sarn).attributeName("Nope").attributeValue("1")));
            List<Subscription> subs = sns.listSubscriptionsByTopic(b -> b.topicArn(arn)).subscriptions();
            chk("ListSubscriptionsByTopic", subs.size() == 1 && subs.get(0).protocol().equals("sqs"));
            run("Unsubscribe", () -> sns.unsubscribe(b -> b.subscriptionArn(sarn)));
            expectError("Unsubscribe twice", "NotFound", () -> sns.unsubscribe(b -> b.subscriptionArn(sarn)));
        }
        expectError("Subscribe rejects an unknown protocol", "InvalidParameter", () -> sns.subscribe(b -> b.topicArn(arn)
                .protocol("carrier-pigeon").endpoint("x")));

        // email: pending until the token from the message log is confirmed
        String email = "java-" + sfx + "@example.com";
        SubscribeResponse es = sns.subscribe(b -> b.topicArn(arn).protocol("email").endpoint(email));
        chk("Subscribe (email) is pending confirmation", "pending confirmation".equals(es.subscriptionArn()), es.subscriptionArn());
        String token = tokenFor(deliveries(endpoint), "SubscriptionConfirmation", email);
        chk("confirmation token is in the message log", !token.isEmpty());
        expectError("ConfirmSubscription with a wrong token", "InvalidParameter", () -> sns.confirmSubscription(b -> b.topicArn(arn).token("deadbeef")));
        ConfirmSubscriptionResponse cs = run("ConfirmSubscription", () -> sns.confirmSubscription(b -> b.topicArn(arn).token(token)));
        chk("confirmed subscription ARN", cs != null && cs.subscriptionArn().startsWith(arn + ":"));
        chk("ListSubscriptions includes the email subscription", sns.listSubscriptions().subscriptions().stream().anyMatch(s -> email.equals(s.endpoint())));

        // publish
        PublishResponse pub = run("Publish", () -> sns.publish(b -> b.topicArn(arn).message("java-hello").subject("greeting")
                .messageAttributes(Map.of("k", MessageAttributeValue.builder().dataType("String").stringValue("v").build()))));
        chk("Publish returns a MessageId", pub != null && !pub.messageId().isEmpty());
        chk("Publish was delivered to the email subscription (message log)",
                deliveries(endpoint).contains("\"message\":\"java-hello\""));
        expectError("Publish rejects an empty message", "InvalidParameter", () -> sns.publish(b -> b.topicArn(arn).message("")));
        expectError("Publish to a missing topic", "NotFound", () -> sns.publish(b -> b.topicArn(arn + "-missing").message("x")));
        PublishBatchResponse pb = sns.publishBatch(b -> b.topicArn(arn).publishBatchRequestEntries(
                PublishBatchRequestEntry.builder().id("a").message("m1").build(),
                PublishBatchRequestEntry.builder().id("b").message("").build()));
        chk("PublishBatch reports per-entry results", pb.successful().size() == 1 && pb.failed().size() == 1 && pb.failed().get(0).id().equals("b"));
        expectError("PublishBatch rejects duplicate ids", "BatchEntryIdsNotDistinct", () -> sns.publishBatch(b -> b.topicArn(arn).publishBatchRequestEntries(
                PublishBatchRequestEntry.builder().id("a").message("m1").build(),
                PublishBatchRequestEntry.builder().id("a").message("m2").build())));

        // mobile push
        CreatePlatformApplicationResponse pa = run("CreatePlatformApplication", () -> sns.createPlatformApplication(b -> b
                .name("java-app-" + sfx).platform("GCM").attributes(Map.of("PlatformCredential", "java-key"))));
        if (pa != null) {
            String paarn = pa.platformApplicationArn();
            Map<String, String> pat = sns.getPlatformApplicationAttributes(b -> b.platformApplicationArn(paarn)).attributes();
            chk("GetPlatformApplicationAttributes (credential not echoed)", !pat.containsKey("PlatformCredential") && "true".equals(pat.get("Enabled")));
            chk("ListPlatformApplications", sns.listPlatformApplications().platformApplications().stream().anyMatch(a -> a.platformApplicationArn().equals(paarn)));
            CreatePlatformEndpointResponse pe = run("CreatePlatformEndpoint", () -> sns.createPlatformEndpoint(b -> b
                    .platformApplicationArn(paarn).token("tok-" + sfx)));
            if (pe != null) {
                String earn = pe.endpointArn();
                chk("CreatePlatformEndpoint is idempotent per token", sns.createPlatformEndpoint(b -> b
                        .platformApplicationArn(paarn).token("tok-" + sfx)).endpointArn().equals(earn));
                chk("ListEndpointsByPlatformApplication", sns.listEndpointsByPlatformApplication(b -> b
                        .platformApplicationArn(paarn)).endpoints().size() == 1);
                run("Publish to the endpoint", () -> sns.publish(b -> b.targetArn(earn)
                        .message("{\"GCM\":\"{\\\"data\\\":{\\\"m\\\":1}}\"}").messageStructure("json")));
                run("SetEndpointAttributes Enabled=false", () -> sns.setEndpointAttributes(b -> b.endpointArn(earn)
                        .attributes(Map.of("Enabled", "false"))));
                Map<String, String> ea = sns.getEndpointAttributes(b -> b.endpointArn(earn)).attributes();
                chk("GetEndpointAttributes", "false".equals(ea.get("Enabled")) && ("tok-" + sfx).equals(ea.get("Token")), ea.toString());
                expectError("Publish to a disabled endpoint", "EndpointDisabled", () -> sns.publish(b -> b.targetArn(earn).message("x")));
                run("DeleteEndpoint", () -> sns.deleteEndpoint(b -> b.endpointArn(earn)));
            }
            run("SetPlatformApplicationAttributes", () -> sns.setPlatformApplicationAttributes(b -> b
                    .platformApplicationArn(paarn).attributes(Map.of("Enabled", "false"))));
            run("DeletePlatformApplication", () -> sns.deletePlatformApplication(b -> b.platformApplicationArn(paarn)));
        }

        // SMS
        run("SetSMSAttributes", () -> sns.setSMSAttributes(b -> b.attributes(Map.of("DefaultSMSType", "Transactional"))));
        chk("GetSMSAttributes", "Transactional".equals(sns.getSMSAttributes(b -> {}).attributes().get("DefaultSMSType")));
        chk("GetSMSSandboxAccountStatus", sns.getSMSSandboxAccountStatus(b -> {}).isInSandbox());
        String phone = "+1555555" + String.format("%04d", System.currentTimeMillis() % 10000);
        run("CreateSMSSandboxPhoneNumber", () -> sns.createSMSSandboxPhoneNumber(b -> b.phoneNumber(phone)));
        expectError("VerifySMSSandboxPhoneNumber with a wrong OTP", "VerificationException", () -> sns.verifySMSSandboxPhoneNumber(b -> b
                .phoneNumber(phone).oneTimePassword("000000")));
        String otp = tokenFor(deliveries(endpoint), "SMSSandboxVerification", phone);
        run("VerifySMSSandboxPhoneNumber", () -> sns.verifySMSSandboxPhoneNumber(b -> b.phoneNumber(phone).oneTimePassword(otp)));
        chk("ListSMSSandboxPhoneNumbers shows it verified", sns.listSMSSandboxPhoneNumbers(b -> {}).phoneNumbers().stream()
                .anyMatch(n -> phone.equals(n.phoneNumber()) && n.statusAsString().equals("Verified")));
        run("Publish an SMS to the verified number", () -> sns.publish(b -> b.phoneNumber(phone).message("hi")));
        chk("CheckIfPhoneNumberIsOptedOut", !sns.checkIfPhoneNumberIsOptedOut(b -> b.phoneNumber(phone)).isOptedOut());
        run("ListPhoneNumbersOptedOut", () -> sns.listPhoneNumbersOptedOut(b -> {}));
        run("OptInPhoneNumber", () -> sns.optInPhoneNumber(b -> b.phoneNumber(phone)));
        run("ListOriginationNumbers", () -> sns.listOriginationNumbers(b -> {}));
        run("DeleteSMSSandboxPhoneNumber", () -> sns.deleteSMSSandboxPhoneNumber(b -> b.phoneNumber(phone)));

        // delete
        run("DeleteTopic", () -> sns.deleteTopic(b -> b.topicArn(arn)));
        expectError("deleted topic is gone", "NotFound", () -> sns.getTopicAttributes(b -> b.topicArn(arn)));

        System.out.println("aws-sdk-java sns: " + pass + " passed, " + fail + " failed");
        System.exit(fail > 0 ? 1 : 0);
    }
}
