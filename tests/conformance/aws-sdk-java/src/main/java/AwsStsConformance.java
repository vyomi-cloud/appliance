// Real aws-sdk-java-v2 STS conformance against the Vyomi appliance — an unmodified
// StsClient with only endpointOverride changed.
//
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=AwsStsConformance
//
// Prints one [PASS]/[FAIL] line per check; exits non-zero on any failure.

import java.net.URI;
import java.time.Instant;
import java.util.Base64;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.AwsSessionCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.sts.StsClient;
import software.amazon.awssdk.services.sts.model.*;

public class AwsStsConformance {
    static int pass = 0, fail = 0;

    static void chk(String name, boolean ok, String detail) {
        if (ok) { pass++; System.out.println("[PASS] " + name); }
        else { fail++; System.out.println("[FAIL] " + name + " :: " + detail); }
    }

    interface Check { void run() throws Exception; }

    static void t(String name, Check c) {
        try { c.run(); } catch (Throwable e) { chk(name, false, e.toString()); }
    }

    static StsClient client(String ep, software.amazon.awssdk.auth.credentials.AwsCredentials creds) {
        return StsClient.builder().endpointOverride(URI.create(ep)).region(Region.US_EAST_1)
                .credentialsProvider(StaticCredentialsProvider.create(creds)).build();
    }

    public static void main(String[] args) {
        String ep = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        StsClient sts = client(ep, AwsBasicCredentials.create("test", "test"));
        String roleArn = "arn:aws:iam::123456789012:role/java-sts-role";
        final String[] tmp = new String[3];

        t("GetCallerIdentity returns the account root", () -> {
            GetCallerIdentityResponse r = sts.getCallerIdentity();
            chk("GetCallerIdentity returns the account root",
                "123456789012".equals(r.account()) && r.arn().endsWith(":root"), r.arn());
        });
        t("AssumeRole returns temporary credentials", () -> {
            AssumeRoleResponse r = sts.assumeRole(b -> b.roleArn(roleArn).roleSessionName("java-session")
                    .durationSeconds(1800).externalId("ext-1"));
            tmp[0] = r.credentials().accessKeyId();
            tmp[1] = r.credentials().secretAccessKey();
            tmp[2] = r.credentials().sessionToken();
            chk("AssumeRole returns temporary credentials",
                tmp[0].startsWith("ASIA") && !tmp[2].isEmpty() && r.credentials().expiration().isAfter(Instant.now()),
                tmp[0]);
            chk("AssumeRole AssumedRoleUser ARN is assumed-role/<role>/<session>",
                r.assumedRoleUser().arn().equals("arn:aws:sts::123456789012:assumed-role/java-sts-role/java-session"),
                r.assumedRoleUser().arn());
        });
        t("GetCallerIdentity with the temporary credentials", () -> {
            StsClient s2 = client(ep, AwsSessionCredentials.create(tmp[0], tmp[1], tmp[2]));
            GetCallerIdentityResponse r = s2.getCallerIdentity();
            chk("GetCallerIdentity with the temporary credentials reports the assumed role",
                r.arn().equals("arn:aws:sts::123456789012:assumed-role/java-sts-role/java-session"), r.arn());
        });
        t("GetSessionToken", () -> {
            GetSessionTokenResponse r = sts.getSessionToken(b -> b.durationSeconds(3600));
            chk("GetSessionToken returns credentials", r.credentials().accessKeyId().startsWith("ASIA"),
                r.credentials().accessKeyId());
        });
        t("GetFederationToken", () -> {
            GetFederationTokenResponse r = sts.getFederationToken(b -> b.name("java-fed"));
            chk("GetFederationToken returns the federated user",
                r.federatedUser().arn().equals("arn:aws:sts::123456789012:federated-user/java-fed"),
                r.federatedUser().arn());
        });
        t("GetAccessKeyInfo", () -> {
            GetAccessKeyInfoResponse r = sts.getAccessKeyInfo(b -> b.accessKeyId(tmp[0]));
            chk("GetAccessKeyInfo returns the owning account", "123456789012".equals(r.account()), r.account());
        });
        t("AssumeRoleWithWebIdentity", () -> {
            String enc = Base64.getUrlEncoder().withoutPadding().encodeToString(
                    "{\"sub\":\"user-1\",\"aud\":\"app\",\"iss\":\"https://idp.example.com\"}".getBytes());
            AssumeRoleWithWebIdentityResponse r = sts.assumeRoleWithWebIdentity(b -> b.roleArn(roleArn)
                    .roleSessionName("web-session").webIdentityToken("e30." + enc + ".sig"));
            chk("AssumeRoleWithWebIdentity returns the token subject",
                "user-1".equals(r.subjectFromWebIdentityToken()), r.subjectFromWebIdentityToken());
        });
        t("DecodeAuthorizationMessage", () -> {
            String msg = Base64.getEncoder().encodeToString("{\"allowed\":false}".getBytes());
            DecodeAuthorizationMessageResponse r = sts.decodeAuthorizationMessage(b -> b.encodedMessage(msg));
            chk("DecodeAuthorizationMessage decodes the message", r.decodedMessage().contains("allowed"), r.decodedMessage());
        });
        try {
            sts.assumeRole(b -> b.roleArn(roleArn).roleSessionName("x y!"));
            chk("AssumeRole rejects an invalid session name", false, "no error");
        } catch (StsException e) {
            chk("AssumeRole rejects an invalid session name",
                "ValidationError".equals(e.awsErrorDetails().errorCode()) && e.statusCode() == 400,
                e.awsErrorDetails().errorCode());
        } catch (Throwable e) { chk("AssumeRole rejects an invalid session name", false, e.toString()); }
        try {
            sts.assumeRole(b -> b.roleArn(roleArn).roleSessionName("ok-name").durationSeconds(901).policy("{not json"));
            chk("AssumeRole rejects a malformed policy", false, "no error");
        } catch (MalformedPolicyDocumentException e) {
            chk("AssumeRole rejects a malformed policy", true, "");
        } catch (Throwable e) { chk("AssumeRole rejects a malformed policy", false, e.toString()); }
        try {
            sts.decodeAuthorizationMessage(b -> b.encodedMessage("!!notbase64!!"));
            chk("DecodeAuthorizationMessage rejects garbage", false, "no error");
        } catch (InvalidAuthorizationMessageException e) {
            chk("DecodeAuthorizationMessage rejects garbage", true, "");
        } catch (Throwable e) { chk("DecodeAuthorizationMessage rejects garbage", false, e.toString()); }

        System.out.println("== " + pass + " passed, " + fail + " failed ==");
        System.exit(fail == 0 ? 0 : 1);
    }
}
