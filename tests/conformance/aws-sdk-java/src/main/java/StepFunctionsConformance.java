// Real aws-sdk-java-v2 Step Functions (SFN) conformance against Vyomi.
// Only the endpoint is overridden. (StartSyncExecution/TestState are not exercised: the SDK prepends the
// `sync-` host prefix to them, which cannot resolve against a bare endpoint override; the engine unit
// tests cover them.) One [PASS]/[FAIL] line per check; non-zero exit on any fail.
//
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=StepFunctionsConformance

import java.net.URI;
import java.util.List;
import java.util.concurrent.Callable;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.sfn.SfnClient;
import software.amazon.awssdk.services.sfn.model.*;

public class StepFunctionsConformance {
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

    static final String ROLE = "arn:aws:iam::000000000000:role/service-role/StepFunctions-ExecutionRole";
    static final String DEF = "{\"StartAt\":\"Add\",\"States\":{"
        + "\"Add\":{\"Type\":\"Pass\",\"Result\":{\"sum\":3},\"ResultPath\":\"$.calc\",\"Next\":\"Pick\"},"
        + "\"Pick\":{\"Type\":\"Choice\",\"Choices\":[{\"Variable\":\"$.go\",\"BooleanEquals\":true,\"Next\":\"Ok\"}],\"Default\":\"Bad\"},"
        + "\"Ok\":{\"Type\":\"Succeed\"},"
        + "\"Bad\":{\"Type\":\"Fail\",\"Error\":\"NotGo\",\"Cause\":\"go was false\"}}}";

    public static void main(String[] args) throws Exception {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        SfnClient c = SfnClient.builder()
            .endpointOverride(URI.create(endpoint)).region(Region.US_EAST_1)
            .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
            .build();
        String sfx = Long.toString(System.nanoTime() % 100000);
        String name = "java-sm-" + sfx;

        CreateStateMachineResponse sm = step("CreateStateMachine", () -> c.createStateMachine(b -> b
            .name(name).definition(DEF).roleArn(ROLE).type(StateMachineType.STANDARD)
            .tags(Tag.builder().key("env").value("test").build())));
        if (sm == null) { System.exit(1); }
        String arn = sm.stateMachineArn();
        chk("CreateStateMachine returns an ARN + creationDate",
            arn.endsWith(":stateMachine:" + name) && sm.creationDate() != null, arn);
        step("DescribeStateMachine", () -> {
            DescribeStateMachineResponse r = c.describeStateMachine(b -> b.stateMachineArn(arn));
            return r.name().equals(name) && r.status() == StateMachineStatus.ACTIVE && r.definition().contains("Choice") ? r : null; });
        step("ListStateMachines includes it", () -> c.listStateMachines().stateMachines().stream()
            .anyMatch(s -> s.stateMachineArn().equals(arn)) ? Boolean.TRUE : null);
        step("UpdateStateMachine", () -> c.updateStateMachine(b -> b.stateMachineArn(arn).roleArn(ROLE + "2")));
        step("DescribeStateMachine shows the new role", () -> c.describeStateMachine(b -> b.stateMachineArn(arn))
            .roleArn().endsWith("2") ? Boolean.TRUE : null);
        expect("DescribeStateMachine unknown → StateMachineDoesNotExistException", StateMachineDoesNotExistException.class,
            () -> c.describeStateMachine(b -> b.stateMachineArn(arn + "-nope")));
        expect("CreateStateMachine invalid definition → InvalidDefinitionException", InvalidDefinitionException.class,
            () -> c.createStateMachine(b -> b.name("bad-" + sfx).definition("{\"StartAt\":\"x\",\"States\":{}}").roleArn(ROLE)));

        StartExecutionResponse ok = step("StartExecution", () -> c.startExecution(b -> b
            .stateMachineArn(arn).name("ok-" + sfx).input("{\"go\":true}")));
        DescribeExecutionResponse okd = step("DescribeExecution (SUCCEEDED)", () -> {
            DescribeExecutionResponse r = c.describeExecution(b -> b.executionArn(ok.executionArn()));
            return r.status() == ExecutionStatus.SUCCEEDED ? r : null; });
        chk("output carries ResultPath data", okd != null && okd.output().contains("\"sum\":3"), String.valueOf(okd));
        StartExecutionResponse bad = step("StartExecution (failing path)", () -> c.startExecution(b -> b
            .stateMachineArn(arn).name("bad-" + sfx).input("{\"go\":false}")));
        DescribeExecutionResponse badd = c.describeExecution(b -> b.executionArn(bad.executionArn()));
        chk("Fail state → FAILED with error + cause",
            badd.status() == ExecutionStatus.FAILED && "NotGo".equals(badd.error()) && "go was false".equals(badd.cause()), badd.toString());
        step("ListExecutions filtered by status", () -> c.listExecutions(b -> b.stateMachineArn(arn).statusFilter(ExecutionStatus.FAILED))
            .executions().size() == 1 ? Boolean.TRUE : null);
        step("GetExecutionHistory", () -> {
            List<HistoryEvent> ev = c.getExecutionHistory(b -> b.executionArn(ok.executionArn())).events();
            return ev.get(0).type() == HistoryEventType.EXECUTION_STARTED
                && ev.get(ev.size() - 1).type() == HistoryEventType.EXECUTION_SUCCEEDED ? ev : null; });
        expect("StartExecution duplicate name → ExecutionAlreadyExistsException", ExecutionAlreadyExistsException.class,
            () -> c.startExecution(b -> b.stateMachineArn(arn).name("ok-" + sfx).input("{\"go\":false}")));

        // activity + callback
        CreateActivityResponse act = step("CreateActivity", () -> c.createActivity(b -> b.name("java-act-" + sfx)));
        step("ListActivities", () -> c.listActivities().activities().stream()
            .anyMatch(a -> a.activityArn().equals(act.activityArn())) ? Boolean.TRUE : null);
        String adef = "{\"StartAt\":\"W\",\"States\":{\"W\":{\"Type\":\"Task\",\"Resource\":\"" + act.activityArn() + "\",\"End\":true}}}";
        String aname = "java-act-sm-" + sfx;
        CreateStateMachineResponse asm = step("CreateStateMachine (activity task)", () -> c.createStateMachine(b -> b
            .name(aname).definition(adef).roleArn(ROLE)));
        StartExecutionResponse ae = step("StartExecution (parks on activity)", () -> c.startExecution(b -> b
            .stateMachineArn(asm.stateMachineArn()).input("{\"job\":7}")));
        chk("execution is RUNNING while the activity task is pending",
            c.describeExecution(b -> b.executionArn(ae.executionArn())).status() == ExecutionStatus.RUNNING, "");
        GetActivityTaskResponse task = step("GetActivityTask", () -> {
            GetActivityTaskResponse r = c.getActivityTask(b -> b.activityArn(act.activityArn()).workerName("w1"));
            return r.taskToken() != null && r.input().contains("\"job\":7") ? r : null; });
        step("SendTaskSuccess", () -> c.sendTaskSuccess(b -> b.taskToken(task.taskToken()).output("{\"done\":true}")));
        DescribeExecutionResponse ad = c.describeExecution(b -> b.executionArn(ae.executionArn()));
        chk("callback completes the execution", ad.status() == ExecutionStatus.SUCCEEDED && ad.output().contains("done"), ad.toString());
        StartExecutionResponse stop = step("StartExecution (to stop)", () -> c.startExecution(b -> b
            .stateMachineArn(asm.stateMachineArn()).input("{}")));
        step("StopExecution", () -> c.stopExecution(b -> b.executionArn(stop.executionArn()).error("E").cause("because")));
        chk("stopped execution is ABORTED",
            c.describeExecution(b -> b.executionArn(stop.executionArn())).status() == ExecutionStatus.ABORTED, "");

        // versions, aliases, tags, validate
        PublishStateMachineVersionResponse ver = step("PublishStateMachineVersion", () -> c.publishStateMachineVersion(b -> b.stateMachineArn(arn)));
        step("ListStateMachineVersions", () -> c.listStateMachineVersions(b -> b.stateMachineArn(arn)).stateMachineVersions().size() == 1 ? Boolean.TRUE : null);
        CreateStateMachineAliasResponse al = step("CreateStateMachineAlias", () -> c.createStateMachineAlias(b -> b.name("prod")
            .routingConfiguration(RoutingConfigurationListItem.builder().stateMachineVersionArn(ver.stateMachineVersionArn()).weight(100).build())));
        step("StartExecution via alias", () -> c.startExecution(b -> b.stateMachineArn(al.stateMachineAliasArn()).input("{\"go\":true}")));
        step("DeleteStateMachineAlias", () -> c.deleteStateMachineAlias(b -> b.stateMachineAliasArn(al.stateMachineAliasArn())));
        step("TagResource", () -> c.tagResource(b -> b.resourceArn(arn).tags(Tag.builder().key("team").value("x").build())));
        step("ListTagsForResource", () -> c.listTagsForResource(b -> b.resourceArn(arn)).tags().size() == 2 ? Boolean.TRUE : null);
        step("UntagResource", () -> c.untagResource(b -> b.resourceArn(arn).tagKeys("team")));
        step("ValidateStateMachineDefinition (FAIL)", () -> c.validateStateMachineDefinition(b -> b.definition("{\"StartAt\":\"x\",\"States\":{}}"))
            .result() == ValidateStateMachineDefinitionResultCode.FAIL ? Boolean.TRUE : null);
        step("ValidateStateMachineDefinition (OK)", () -> c.validateStateMachineDefinition(b -> b.definition(DEF))
            .result() == ValidateStateMachineDefinitionResultCode.OK ? Boolean.TRUE : null);

        step("DeleteActivity", () -> c.deleteActivity(b -> b.activityArn(act.activityArn())));
        step("DeleteStateMachine", () -> c.deleteStateMachine(b -> b.stateMachineArn(asm.stateMachineArn())));
        step("DeleteStateMachine (main)", () -> c.deleteStateMachine(b -> b.stateMachineArn(arn)));
        expect("DescribeStateMachine after delete → StateMachineDoesNotExistException", StateMachineDoesNotExistException.class,
            () -> c.describeStateMachine(b -> b.stateMachineArn(arn)));

        System.out.println("\n" + pass + " passed, " + fail + " failed");
        System.exit(fail == 0 ? 0 : 1);
    }
}
