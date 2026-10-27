// Real aws-sdk-java-v2 Systems Manager conformance against Vyomi.
// Only the endpoint is overridden. One [PASS]/[FAIL] line per check; non-zero exit on any fail.
//
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=SsmConformance

import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.ssm.SsmClient;
import software.amazon.awssdk.services.ssm.model.*;

public class SsmConformance {
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
        SsmClient c = SsmClient.builder()
            .endpointOverride(URI.create(endpoint)).region(Region.US_EAST_1)
            .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
            .build();
        String sfx = Long.toString(System.nanoTime() % 1000000);
        String p = "/java-" + sfx + "/app";

        // ── Parameter Store ──
        PutParameterResponse put = step("PutParameter", () -> c.putParameter(b -> b.name(p + "/db/host").value("db.local")
            .type(ParameterType.STRING).description("conformance").tags(Tag.builder().key("env").value("test").build())));
        if (put == null) { System.exit(1); }
        chk("PutParameter returns version 1 / Standard tier", put.version() == 1 && put.tier() == ParameterTier.STANDARD, put.toString());
        expect("PutParameter without Overwrite → ParameterAlreadyExistsException", ParameterAlreadyExistsException.class,
            () -> c.putParameter(b -> b.name(p + "/db/host").value("x").type(ParameterType.STRING)));
        step("PutParameter Overwrite bumps version", () -> {
            PutParameterResponse r = c.putParameter(b -> b.name(p + "/db/host").value("db2.local").type(ParameterType.STRING).overwrite(true));
            return r.version() == 2 ? r : null;
        });
        step("GetParameter value/version/ARN", () -> {
            Parameter r = c.getParameter(b -> b.name(p + "/db/host")).parameter();
            return r.value().equals("db2.local") && r.version() == 2 && r.arn().equals("arn:aws:ssm:us-east-1:000000000000:parameter" + p + "/db/host") ? r : null;
        });
        step("GetParameter by version selector", () -> c.getParameter(b -> b.name(p + "/db/host:1")).parameter().value().equals("db.local") ? "ok" : null);
        expect("GetParameter unknown → ParameterNotFoundException", ParameterNotFoundException.class, () -> c.getParameter(b -> b.name("/nope-" + sfx)));
        step("PutParameter SecureString", () -> c.putParameter(b -> b.name(p + "/secret").value("s3cr3t").type(ParameterType.SECURE_STRING)));
        step("SecureString hidden without decryption, clear with it", () -> {
            String enc = c.getParameter(b -> b.name(p + "/secret")).parameter().value();
            String dec = c.getParameter(b -> b.name(p + "/secret").withDecryption(true)).parameter().value();
            return !enc.equals("s3cr3t") && dec.equals("s3cr3t") ? "ok" : null;
        });
        step("GetParametersByPath recursive", () -> c.getParametersByPath(b -> b.path(p).recursive(true)).parameters().size() == 2 ? "ok" : null);
        step("GetParameters splits InvalidParameters", () -> {
            GetParametersResponse r = c.getParameters(b -> b.names(p + "/db/host", "/missing-" + sfx));
            return r.parameters().size() == 1 && r.invalidParameters().size() == 1 ? r : null;
        });
        step("DescribeParameters paginates (MaxResults=1)", () -> {
            DescribeParametersResponse r = c.describeParameters(b -> b.maxResults(1).parameterFilters(
                ParameterStringFilter.builder().key("Name").option("BeginsWith").values(p).build()));
            return r.parameters().size() == 1 && r.nextToken() != null ? r : null;
        });
        step("LabelParameterVersion + GetParameter by label", () -> {
            LabelParameterVersionResponse l = c.labelParameterVersion(b -> b.name(p + "/db/host").parameterVersion(1L).labels("stable"));
            return l.invalidLabels().isEmpty() && c.getParameter(b -> b.name(p + "/db/host:stable")).parameter().version() == 1 ? l : null;
        });
        step("GetParameterHistory lists both versions", () -> {
            List<ParameterHistory> h = c.getParameterHistory(b -> b.name(p + "/db/host")).parameters();
            return h.size() == 2 && h.get(0).labels().contains("stable") ? h : null;
        });
        step("AddTagsToResource + ListTagsForResource", () -> {
            c.addTagsToResource(b -> b.resourceType(ResourceTypeForTagging.PARAMETER).resourceId(p + "/db/host").tags(Tag.builder().key("team").value("x").build()));
            return c.listTagsForResource(b -> b.resourceType(ResourceTypeForTagging.PARAMETER).resourceId(p + "/db/host")).tagList().size() == 2 ? "ok" : null;
        });
        step("RemoveTagsFromResource", () -> {
            c.removeTagsFromResource(b -> b.resourceType(ResourceTypeForTagging.PARAMETER).resourceId(p + "/db/host").tagKeys("team"));
            return c.listTagsForResource(b -> b.resourceType(ResourceTypeForTagging.PARAMETER).resourceId(p + "/db/host")).tagList().size() == 1 ? "ok" : null;
        });

        // ── Documents + Run Command ──
        String doc = "java-doc-" + sfx;
        step("CreateDocument", () -> c.createDocument(b -> b.name(doc).documentType(DocumentType.COMMAND).documentFormat(DocumentFormat.JSON)
            .content("{\"schemaVersion\":\"2.2\",\"description\":\"java\",\"mainSteps\":[]}")).documentDescription());
        expect("CreateDocument duplicate → DocumentAlreadyExistsException", DocumentAlreadyExistsException.class,
            () -> c.createDocument(b -> b.name(doc).content("{\"schemaVersion\":\"2.2\",\"mainSteps\":[]}")));
        step("UpdateDocument → version 2", () -> c.updateDocument(b -> b.name(doc).documentVersion("$LATEST")
            .content("{\"schemaVersion\":\"2.2\",\"description\":\"v2\",\"mainSteps\":[]}")).documentDescription().documentVersion().equals("2") ? "ok" : null);
        step("DescribeDocument", () -> c.describeDocument(b -> b.name(doc)).document().status() == DocumentStatus.ACTIVE ? "ok" : null);
        step("ListDocuments Owner=Self lists it", () -> c.listDocuments(b -> b.filters(DocumentKeyValuesFilter.builder().key("Owner").values("Self").build()))
            .documentIdentifiers().stream().anyMatch(d -> d.name().equals(doc)) ? "ok" : null);
        step("SendCommand + GetCommandInvocation → Success", () -> {
            SendCommandResponse r = c.sendCommand(b -> b.documentName("AWS-RunShellScript").instanceIds("i-0123456789abcdef0")
                .parameters(Map.of("commands", List.of("echo hi"))));
            return c.getCommandInvocation(b -> b.commandId(r.command().commandId()).instanceId("i-0123456789abcdef0")).status() == CommandInvocationStatus.SUCCESS ? "ok" : null;
        });
        expect("SendCommand unknown document → InvalidDocumentException", InvalidDocumentException.class,
            () -> c.sendCommand(b -> b.documentName("no-such-doc-" + sfx).instanceIds("i-0123456789abcdef0")));

        // ── Maintenance windows + patch baselines ──
        CreateMaintenanceWindowResponse mw = step("CreateMaintenanceWindow", () -> c.createMaintenanceWindow(b -> b.name("java-win-" + sfx)
            .schedule("cron(0 2 * * ? *)").duration(4).cutoff(1).allowUnassociatedTargets(false)));
        if (mw != null) {
            step("GetMaintenanceWindow", () -> c.getMaintenanceWindow(b -> b.windowId(mw.windowId())).name().equals("java-win-" + sfx) ? "ok" : null);
            step("DeleteMaintenanceWindow", () -> c.deleteMaintenanceWindow(b -> b.windowId(mw.windowId())));
            expect("GetMaintenanceWindow after delete → DoesNotExistException", DoesNotExistException.class, () -> c.getMaintenanceWindow(b -> b.windowId(mw.windowId())));
        }
        CreatePatchBaselineResponse pb = step("CreatePatchBaseline", () -> c.createPatchBaseline(b -> b.name("java-pb-" + sfx).operatingSystem(OperatingSystem.AMAZON_LINUX_2)));
        if (pb != null) step("DeletePatchBaseline", () -> c.deletePatchBaseline(b -> b.baselineId(pb.baselineId())));

        // ── cleanup ──
        step("DeleteDocument", () -> c.deleteDocument(b -> b.name(doc)));
        step("DeleteParameter", () -> c.deleteParameter(b -> b.name(p + "/db/host")));
        step("DeleteParameters", () -> {
            DeleteParametersResponse r = c.deleteParameters(b -> b.names(p + "/secret", p + "/gone"));
            return r.deletedParameters().size() == 1 && r.invalidParameters().size() == 1 ? r : null;
        });
        expect("GetParameter after delete → ParameterNotFoundException", ParameterNotFoundException.class, () -> c.getParameter(b -> b.name(p + "/db/host")));

        System.out.println("\n" + pass + " passed, " + fail + " failed");
        System.exit(fail == 0 ? 0 : 1);
    }
}
