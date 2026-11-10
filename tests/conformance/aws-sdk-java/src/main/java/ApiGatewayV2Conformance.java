// Real aws-sdk-java-v2 ApiGatewayV2 (HTTP/WebSocket APIs) conformance against Vyomi.
// Only the endpoint is overridden. One [PASS]/[FAIL] line per check; non-zero exit on any fail.
//
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=ApiGatewayV2Conformance

import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.apigatewayv2.ApiGatewayV2Client;
import software.amazon.awssdk.services.apigatewayv2.model.*;

public class ApiGatewayV2Conformance {
    static int pass = 0, fail = 0;

    static void chk(String name, boolean ok, String detail) {
        if (ok) { pass++; System.out.println("[PASS] " + name); }
        else { fail++; System.out.println("[FAIL] " + name + " :: " + detail); }
    }

    static <T> T step(String name, Callable<T> op) {
        try { T r = op.call(); chk(name, r != null, "null result"); return r; }
        catch (Throwable t) { chk(name, false, String.valueOf(t.getMessage())); return null; }
    }

    static void expect(String name, Class<? extends Throwable> cls, Runnable op) {
        try { op.run(); chk(name, false, "expected " + cls.getSimpleName()); }
        catch (Throwable t) { chk(name, cls.isInstance(t), t.getClass().getName() + ": " + t.getMessage()); }
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        ApiGatewayV2Client c = ApiGatewayV2Client.builder()
            .endpointOverride(URI.create(endpoint)).region(Region.US_EAST_1)
            .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
            .build();
        String suffix = Long.toString(System.nanoTime() % 100000);

        CreateApiResponse api = step("CreateApi (HTTP)", () -> c.createApi(b -> b
            .name("java-http-" + suffix).protocolType(ProtocolType.HTTP).description("conformance")
            .tags(Map.of("env", "test"))));
        if (api == null) { System.exit(1); }
        String id = api.apiId();
        chk("CreateApi returns apiEndpoint + HTTP protocol",
            api.apiEndpoint() != null && api.apiEndpoint().contains(id) && api.protocolType() == ProtocolType.HTTP, api.toString());
        step("GetApi", () -> { GetApiResponse r = c.getApi(b -> b.apiId(id)); return r.name().equals(api.name()) ? r : null; });
        step("GetApis lists the API", () -> c.getApis(b -> {}).items().stream().anyMatch(a -> a.apiId().equals(id)) ? "ok" : null);
        step("UpdateApi (name + CORS)", () -> {
            UpdateApiResponse r = c.updateApi(b -> b.apiId(id).name("java-http-renamed-" + suffix)
                .corsConfiguration(Cors.builder().allowOrigins("*").allowMethods("GET").build()));
            return r.name().startsWith("java-http-renamed") && r.corsConfiguration().allowOrigins().contains("*") ? r : null;
        });
        expect("GetApi unknown → NotFoundException", NotFoundException.class, () -> c.getApi(b -> b.apiId("doesnotexist")));
        expect("CreateApi without name → BadRequestException", BadRequestException.class,
            () -> c.createApi(b -> b.protocolType(ProtocolType.HTTP).name("")));

        CreateIntegrationResponse integ = step("CreateIntegration (HTTP_PROXY)", () -> c.createIntegration(b -> b
            .apiId(id).integrationType(IntegrationType.HTTP_PROXY).integrationUri("https://example.com")
            .integrationMethod("GET").payloadFormatVersion("1.0")));
        String iid = integ.integrationId();
        step("GetIntegration", () -> c.getIntegration(b -> b.apiId(id).integrationId(iid)).integrationUri().equals("https://example.com") ? "ok" : null);
        step("UpdateIntegration", () -> c.updateIntegration(b -> b.apiId(id).integrationId(iid).timeoutInMillis(10000)).timeoutInMillis() == 10000 ? "ok" : null);

        CreateRouteResponse route = step("CreateRoute", () -> c.createRoute(b -> b
            .apiId(id).routeKey("GET /items/{id}").target("integrations/" + iid)));
        String rid = route.routeId();
        step("GetRoutes", () -> c.getRoutes(b -> b.apiId(id)).items().stream().anyMatch(r -> r.routeKey().equals("GET /items/{id}")) ? "ok" : null);
        step("UpdateRoute", () -> c.updateRoute(b -> b.apiId(id).routeId(rid).operationName("getItem")).operationName().equals("getItem") ? "ok" : null);
        expect("CreateRoute duplicate key → ConflictException", ConflictException.class,
            () -> c.createRoute(b -> b.apiId(id).routeKey("GET /items/{id}")));
        step("CreateRouteResponse", () -> c.createRouteResponse(b -> b.apiId(id).routeId(rid).routeResponseKey("$default")).routeResponseId());
        step("GetRouteResponses", () -> c.getRouteResponses(b -> b.apiId(id).routeId(rid)).items().size() == 1 ? "ok" : null);

        step("CreateAuthorizer (JWT)", () -> c.createAuthorizer(b -> b.apiId(id).name("jwt")
            .authorizerType(AuthorizerType.JWT).identitySource("$request.header.Authorization")
            .jwtConfiguration(JWTConfiguration.builder().audience("aud").issuer("https://issuer.example.com").build())).authorizerId());
        step("CreateModel", () -> c.createModel(b -> b.apiId(id).name("Item").schema("{\"type\":\"object\"}")).modelId());

        step("CreateStage", () -> c.createStage(b -> b.apiId(id).stageName("prod").stageVariables(Map.of("k", "v"))).stageName());
        CreateDeploymentResponse dep = step("CreateDeployment (to stage)", () -> c.createDeployment(b -> b.apiId(id).stageName("prod").description("v1")));
        step("Stage points at the deployment", () -> c.getStage(b -> b.apiId(id).stageName("prod")).deploymentId().equals(dep.deploymentId()) ? "ok" : null);
        step("GetDeployments", () -> c.getDeployments(b -> b.apiId(id)).items().size() >= 1 ? "ok" : null);
        step("UpdateStage", () -> c.updateStage(b -> b.apiId(id).stageName("prod").description("prod stage")).description().equals("prod stage") ? "ok" : null);
        expect("CreateStage duplicate → ConflictException", ConflictException.class, () -> c.createStage(b -> b.apiId(id).stageName("prod")));

        String arn = "arn:aws:apigateway:us-east-1::/apis/" + id;
        step("TagResource", () -> { c.tagResource(b -> b.resourceArn(arn).tags(Map.of("team", "x"))); return "ok"; });
        step("GetTags", () -> c.getTags(b -> b.resourceArn(arn)).tags().get("team") != null ? "ok" : null);
        step("UntagResource", () -> { c.untagResource(b -> b.resourceArn(arn).tagKeys("team")); return c.getTags(b -> b.resourceArn(arn)).tags().containsKey("team") ? null : "ok"; });

        String dom = "java-" + suffix + ".example.com";
        step("CreateDomainName", () -> c.createDomainName(b -> b.domainName(dom)).domainName());
        step("CreateApiMapping", () -> c.createApiMapping(b -> b.domainName(dom).apiId(id).stage("prod")).apiMappingId());
        step("GetApiMappings", () -> c.getApiMappings(b -> b.domainName(dom)).items().size() == 1 ? "ok" : null);
        step("GetDomainNames", () -> c.getDomainNames(b -> {}).items().stream().anyMatch(d -> d.domainName().equals(dom)) ? "ok" : null);
        step("DeleteDomainName", () -> { c.deleteDomainName(b -> b.domainName(dom)); return "ok"; });

        CreateVpcLinkResponse vl = step("CreateVpcLink", () -> c.createVpcLink(b -> b.name("vl-" + suffix).subnetIds("subnet-12345")));
        step("GetVpcLink", () -> c.getVpcLink(b -> b.vpcLinkId(vl.vpcLinkId())).vpcLinkStatus() == VpcLinkStatus.AVAILABLE ? "ok" : null);
        step("DeleteVpcLink", () -> { c.deleteVpcLink(b -> b.vpcLinkId(vl.vpcLinkId())); return "ok"; });

        CreateApiResponse ws = step("CreateApi (WEBSOCKET)", () -> c.createApi(b -> b.name("java-ws-" + suffix)
            .protocolType(ProtocolType.WEBSOCKET).routeSelectionExpression("$request.body.action")));
        chk("WEBSOCKET apiEndpoint is wss://", ws != null && ws.apiEndpoint().startsWith("wss://"), String.valueOf(ws));
        CreateApiResponse quick = step("CreateApi quick-create (target)", () -> c.createApi(b -> b.name("java-quick-" + suffix)
            .protocolType(ProtocolType.HTTP).target("https://example.com")));
        step("Quick-create made a $default route + stage", () ->
            c.getRoutes(b -> b.apiId(quick.apiId())).items().size() == 1
                && c.getStage(b -> b.apiId(quick.apiId()).stageName("$default")).autoDeploy() ? "ok" : null);

        step("DeleteRoute", () -> { c.deleteRoute(b -> b.apiId(id).routeId(rid)); return "ok"; });
        step("DeleteIntegration", () -> { c.deleteIntegration(b -> b.apiId(id).integrationId(iid)); return "ok"; });
        step("DeleteStage", () -> { c.deleteStage(b -> b.apiId(id).stageName("prod")); return "ok"; });
        for (String x : List.of(id, ws.apiId(), quick.apiId())) {
            step("DeleteApi " + x, () -> { c.deleteApi(b -> b.apiId(x)); return "ok"; });
        }
        expect("GetApi after delete → NotFoundException", NotFoundException.class, () -> c.getApi(b -> b.apiId(id)));

        System.out.println("\n" + pass + " passed, " + fail + " failed");
        System.exit(fail == 0 ? 0 : 1);
    }
}
