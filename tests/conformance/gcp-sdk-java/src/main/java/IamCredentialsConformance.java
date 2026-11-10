import com.google.api.gax.core.NoCredentialsProvider;
import com.google.api.gax.rpc.ApiException;
import com.google.cloud.iam.credentials.v1.GenerateAccessTokenRequest;
import com.google.cloud.iam.credentials.v1.GenerateAccessTokenResponse;
import com.google.cloud.iam.credentials.v1.GenerateIdTokenRequest;
import com.google.cloud.iam.credentials.v1.GenerateIdTokenResponse;
import com.google.cloud.iam.credentials.v1.IamCredentialsClient;
import com.google.cloud.iam.credentials.v1.IamCredentialsSettings;
import com.google.cloud.iam.credentials.v1.ServiceAccountName;
import com.google.cloud.iam.credentials.v1.SignBlobRequest;
import com.google.cloud.iam.credentials.v1.SignBlobResponse;
import com.google.cloud.iam.credentials.v1.SignJwtRequest;
import com.google.cloud.iam.credentials.v1.SignJwtResponse;
import com.google.protobuf.ByteString;
import com.google.protobuf.Duration;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Base64;
import java.util.List;

/**
 * Real google-cloud-iamcredentials (Java, REST/httpjson transport) conformance against Vyomi's
 * IAM Service Account Credentials API. Endpoint comes from env ENDPOINT (default
 * http://127.0.0.1:9000), project from PROJECT. One [PASS]/[FAIL] line per check; exits
 * non-zero on any failure.
 */
public class IamCredentialsConformance {
  static int pass = 0, fail = 0;
  static final HttpClient HTTP = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();

  static void check(String name, boolean ok, String detail) {
    System.out.println("[" + (ok ? "PASS" : "FAIL") + "] " + name
        + (!ok && detail != null && !detail.isEmpty() ? " :: " + detail : ""));
    if (ok) pass++; else fail++;
  }

  static String http(String method, String url, String body) throws Exception {
    HttpRequest.Builder b = HttpRequest.newBuilder(URI.create(url)).header("content-type", "application/json");
    b = body == null ? b.method(method, HttpRequest.BodyPublishers.noBody())
                     : b.method(method, HttpRequest.BodyPublishers.ofString(body));
    HttpResponse<String> r = HTTP.send(b.build(), HttpResponse.BodyHandlers.ofString());
    return r.statusCode() + " " + r.body();
  }

  static String claimsOf(String jwt) {
    return new String(Base64.getUrlDecoder().decode(jwt.split("\\.")[1]));
  }

  static int code(Exception e) {
    return e instanceof ApiException ? ((ApiException) e).getStatusCode().getCode().getHttpStatusCode() : 0;
  }

  public static void main(String[] args) throws Exception {
    String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
    String project = System.getenv().getOrDefault("PROJECT", "vyomi-project");
    String sfx = String.valueOf(System.currentTimeMillis() % 1000000);
    System.out.println("== google-cloud-iamcredentials (Java) against " + endpoint + " project=" + project + " ==");

    // Service accounts come from the IAM API (a separate service).
    String[] ids = {"java-sa-" + sfx, "java-del-" + sfx};
    for (String id : ids) {
      String r = http("POST", endpoint + "/v1/projects/" + project + "/serviceAccounts", "{\"accountId\":\"" + id + "\"}");
      check("IAM: create service account " + id, r.startsWith("200") || r.startsWith("409"), r);
    }
    String sa = ServiceAccountName.of("-", ids[0] + "@" + project + ".iam.gserviceaccount.com").toString();
    String del = ServiceAccountName.of("-", ids[1] + "@" + project + ".iam.gserviceaccount.com").toString();
    String ghost = ServiceAccountName.of("-", "ghost-" + sfx + "@" + project + ".iam.gserviceaccount.com").toString();
    List<String> scope = List.of("https://www.googleapis.com/auth/cloud-platform");

    IamCredentialsSettings settings = IamCredentialsSettings.newHttpJsonBuilder()
        .setCredentialsProvider(NoCredentialsProvider.create())
        .setTransportChannelProvider(IamCredentialsSettings.defaultHttpJsonTransportProviderBuilder()
            .setEndpoint(endpoint).build())
        .build();

    try (IamCredentialsClient c = IamCredentialsClient.create(settings)) {
      try {
        GenerateAccessTokenResponse r = c.generateAccessToken(sa, List.of(), scope, Duration.newBuilder().setSeconds(600).build());
        long left = r.getExpireTime().getSeconds() - System.currentTimeMillis() / 1000;
        check("generateAccessToken (ya29 token, 10m lifetime honoured)",
            r.getAccessToken().startsWith("ya29.") && left > 540 && left <= 610, r.toString());
      } catch (Exception e) { check("generateAccessToken", false, e.toString()); }

      try {
        GenerateAccessTokenResponse r = c.generateAccessToken(sa, List.of(del), scope, Duration.getDefaultInstance());
        long left = r.getExpireTime().getSeconds() - System.currentTimeMillis() / 1000;
        check("generateAccessToken with delegate chain (default 1h)", !r.getAccessToken().isEmpty() && left > 3500, r.toString());
      } catch (Exception e) { check("generateAccessToken with delegate chain", false, e.toString()); }

      try {
        c.generateAccessToken(sa, List.of(), List.of(), Duration.getDefaultInstance());
        check("generateAccessToken without scope -> 400", false, "no error");
      } catch (Exception e) { check("generateAccessToken without scope -> 400", code(e) == 400, e.toString()); }

      try {
        c.generateAccessToken(ghost, List.of(), scope, Duration.getDefaultInstance());
        check("unknown service account -> 403", false, "no error");
      } catch (Exception e) { check("unknown service account -> 403", code(e) == 403, e.toString()); }

      try {
        GenerateIdTokenResponse r = c.generateIdToken(GenerateIdTokenRequest.newBuilder().setName(sa)
            .setAudience("https://svc.example.com").setIncludeEmail(true).build());
        String claims = claimsOf(r.getToken());
        check("generateIdToken (aud + email claims)", claims.contains("\"aud\":\"https://svc.example.com\"")
            && claims.contains(ids[0] + "@" + project), claims);
      } catch (Exception e) { check("generateIdToken", false, e.toString()); }

      try {
        SignBlobResponse r = c.signBlob(SignBlobRequest.newBuilder().setName(sa)
            .setPayload(ByteString.copyFromUtf8("sign these bytes")).build());
        check("signBlob (2048-bit signature, 40-hex key id)", r.getSignedBlob().size() == 256 && r.getKeyId().length() == 40, r.getKeyId());
      } catch (Exception e) { check("signBlob", false, e.toString()); }

      try {
        SignJwtResponse r = c.signJwt(SignJwtRequest.newBuilder().setName(sa)
            .setPayload("{\"iss\":\"" + ids[0] + "\",\"aud\":\"https://example.com\",\"exp\":9999999999}").build());
        check("signJwt (claims preserved)", claimsOf(r.getSignedJwt()).contains("\"aud\":\"https://example.com\"")
            && r.getSignedJwt().split("\\.").length == 3, r.getSignedJwt());
      } catch (Exception e) { check("signJwt", false, e.toString()); }

      try {
        c.signJwt(SignJwtRequest.newBuilder().setName(sa).setPayload("not json").build());
        check("signJwt non-JSON payload -> 400", false, "no error");
      } catch (Exception e) { check("signJwt non-JSON payload -> 400", code(e) == 400, e.toString()); }
    }

    String list = http("GET", endpoint + "/api/gcp/iamcredentials/credentials", null);
    check("console lists the issued credentials (no secrets)", list.startsWith("200") && list.contains(ids[0]) && !list.contains("ya29."), list.substring(0, Math.min(120, list.length())));

    System.out.println("RESULT pass=" + pass + " fail=" + fail);
    if (fail > 0) System.exit(1);
  }
}
