// Real AWS SDK for Java v2 CloudFormation conformance probe against Vyomi.
// Only the endpoint is overridden. One [PASS]/[FAIL] line per check; non-zero exit on failure.
//
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=AwsCloudFormationConformance

import java.net.URI;
import java.util.List;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.cloudformation.CloudFormationClient;
import software.amazon.awssdk.services.cloudformation.model.*;

public class AwsCloudFormationConformance {
    static int pass = 0, fail = 0;

    static void chk(String name, boolean ok, String detail) {
        if (ok) { pass++; System.out.println("[PASS] " + name); }
        else { fail++; System.out.println("[FAIL] " + name + " :: " + detail); }
    }

    interface Call { boolean run() throws Exception; }

    static void chk(String name, Call c) {
        try { chk(name, c.run(), "returned false"); }
        catch (Exception e) { chk(name, false, e.toString()); }
    }

    static String code(Exception e) {
        return (e instanceof CloudFormationException c && c.awsErrorDetails() != null)
            ? c.awsErrorDetails().errorCode() : e.toString();
    }

    static final String TEMPLATE = "{\"AWSTemplateFormatVersion\":\"2010-09-09\",\"Description\":\"java conformance stack\","
        + "\"Parameters\":{\"Env\":{\"Type\":\"String\",\"Default\":\"dev\",\"AllowedValues\":[\"dev\",\"prod\"]}},"
        + "\"Conditions\":{\"IsProd\":{\"Fn::Equals\":[{\"Ref\":\"Env\"},\"prod\"]}},"
        + "\"Resources\":{"
        + "\"Table\":{\"Type\":\"AWS::DynamoDB::Table\",\"Properties\":{\"TableName\":{\"Fn::Sub\":\"${AWS::StackName}-${Env}\"}}},"
        + "\"Queue\":{\"Type\":\"AWS::SQS::Queue\",\"DependsOn\":\"Table\"},"
        + "\"ProdTopic\":{\"Type\":\"AWS::SNS::Topic\",\"Condition\":\"IsProd\"}},"
        + "\"Outputs\":{\"TableArn\":{\"Value\":{\"Fn::GetAtt\":[\"Table\",\"Arn\"]},\"Export\":{\"Name\":{\"Fn::Sub\":\"${AWS::StackName}-table-arn\"}}},"
        + "\"Env\":{\"Value\":{\"Fn::FindInMap\":[\"M\",\"k\",\"v\"]}}},"
        + "\"Mappings\":{\"M\":{\"k\":{\"v\":\"mapped\"}}}}";

    static StackStatus status(CloudFormationClient cf, String name) {
        return cf.describeStacks(DescribeStacksRequest.builder().stackName(name).build()).stacks().get(0).stackStatus();
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        System.out.println("== aws-sdk-java-v2 cloudformation against " + endpoint + " ==");
        CloudFormationClient cf = CloudFormationClient.builder()
            .endpointOverride(URI.create(endpoint)).region(Region.US_EAST_1)
            .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
            .build();
        String name = "java-cfn-" + (System.nanoTime() % 1000000000L);

        chk("ValidateTemplate lists parameters", () -> {
            ValidateTemplateResponse v = cf.validateTemplate(ValidateTemplateRequest.builder().templateBody(TEMPLATE).build());
            return v.parameters().size() == 1 && v.parameters().get(0).defaultValue().equals("dev")
                && "java conformance stack".equals(v.description());
        });
        chk("ValidateTemplate rejects bad JSON", () -> {
            try { cf.validateTemplate(ValidateTemplateRequest.builder().templateBody("{oops").build()); return false; }
            catch (CloudFormationException e) { return "ValidationError".equals(code(e)); }
        });
        chk("CreateStack", () -> cf.createStack(CreateStackRequest.builder().stackName(name).templateBody(TEMPLATE)
            .tags(Tag.builder().key("owner").value("java").build()).build()).stackId().contains(":stack/" + name + "/"));
        chk("DescribeStacks → CREATE_COMPLETE", () -> status(cf, name) == StackStatus.CREATE_COMPLETE);
        chk("outputs: GetAtt + FindInMap", () -> {
            List<Output> o = cf.describeStacks(DescribeStacksRequest.builder().stackName(name).build()).stacks().get(0).outputs();
            return o.stream().anyMatch(x -> x.outputKey().equals("TableArn") && x.outputValue().endsWith(":table/" + name + "-dev"))
                && o.stream().anyMatch(x -> x.outputKey().equals("Env") && x.outputValue().equals("mapped"));
        });
        chk("ListStackResources (condition skips ProdTopic)", () ->
            cf.listStackResources(ListStackResourcesRequest.builder().stackName(name).build()).stackResourceSummaries().size() == 2);
        chk("DescribeStackResource Table = table name", () ->
            cf.describeStackResource(DescribeStackResourceRequest.builder().stackName(name).logicalResourceId("Table").build())
                .stackResourceDetail().physicalResourceId().equals(name + "-dev"));
        chk("DescribeStackEvents includes CREATE_IN_PROGRESS and CREATE_COMPLETE", () -> {
            List<StackEvent> ev = cf.describeStackEvents(DescribeStackEventsRequest.builder().stackName(name).build()).stackEvents();
            return ev.stream().anyMatch(e -> e.resourceStatus() == ResourceStatus.CREATE_IN_PROGRESS)
                && ev.stream().anyMatch(e -> e.resourceStatus() == ResourceStatus.CREATE_COMPLETE);
        });
        chk("GetTemplate", () -> cf.getTemplate(GetTemplateRequest.builder().stackName(name).build()).templateBody().contains("java conformance stack"));
        chk("GetTemplateSummary", () -> cf.getTemplateSummary(GetTemplateSummaryRequest.builder().stackName(name).build()).resourceTypes().size() == 3);
        chk("ListExports", () -> cf.listExports(ListExportsRequest.builder().build()).exports().stream().anyMatch(e -> e.name().equals(name + "-table-arn")));
        chk("duplicate CreateStack → AlreadyExistsException", () -> {
            try { cf.createStack(CreateStackRequest.builder().stackName(name).templateBody(TEMPLATE).build()); return false; }
            catch (AlreadyExistsException e) { return true; }
        });
        chk("UpdateStack no-op → ValidationError", () -> {
            try { cf.updateStack(UpdateStackRequest.builder().stackName(name).templateBody(TEMPLATE).build()); return false; }
            catch (CloudFormationException e) { return "ValidationError".equals(code(e)) && e.getMessage().contains("No updates"); }
        });
        chk("UpdateStack Env=prod → UPDATE_COMPLETE + 3 resources", () -> {
            cf.updateStack(UpdateStackRequest.builder().stackName(name).templateBody(TEMPLATE)
                .parameters(Parameter.builder().parameterKey("Env").parameterValue("prod").build()).build());
            return status(cf, name) == StackStatus.UPDATE_COMPLETE
                && cf.listStackResources(ListStackResourcesRequest.builder().stackName(name).build()).stackResourceSummaries().size() == 3;
        });
        chk("CreateChangeSet + DescribeChangeSet", () -> {
            cf.createChangeSet(CreateChangeSetRequest.builder().stackName(name).changeSetName("java-cs").templateBody(TEMPLATE)
                .parameters(Parameter.builder().parameterKey("Env").parameterValue("dev").build()).build());
            DescribeChangeSetResponse d = cf.describeChangeSet(DescribeChangeSetRequest.builder().stackName(name).changeSetName("java-cs").build());
            return d.status() == ChangeSetStatus.CREATE_COMPLETE && d.executionStatus() == ExecutionStatus.AVAILABLE
                && d.changes().stream().anyMatch(c -> c.resourceChange().action() == ChangeAction.REMOVE
                    && "ProdTopic".equals(c.resourceChange().logicalResourceId()));
        });
        chk("ListChangeSets", () -> cf.listChangeSets(ListChangeSetsRequest.builder().stackName(name).build()).summaries().size() == 1);
        chk("ExecuteChangeSet", () -> {
            cf.executeChangeSet(ExecuteChangeSetRequest.builder().stackName(name).changeSetName("java-cs").build());
            return status(cf, name) == StackStatus.UPDATE_COMPLETE
                && cf.listStackResources(ListStackResourcesRequest.builder().stackName(name).build()).stackResourceSummaries().size() == 2;
        });
        chk("CREATE change set leaves REVIEW_IN_PROGRESS until executed", () -> {
            String n2 = name + "-cs";
            cf.createChangeSet(CreateChangeSetRequest.builder().stackName(n2).changeSetName("first").changeSetType(ChangeSetType.CREATE).templateBody(TEMPLATE).build());
            boolean review = status(cf, n2) == StackStatus.REVIEW_IN_PROGRESS;
            cf.executeChangeSet(ExecuteChangeSetRequest.builder().stackName(n2).changeSetName("first").build());
            boolean done = status(cf, n2) == StackStatus.CREATE_COMPLETE;
            cf.deleteStack(DeleteStackRequest.builder().stackName(n2).build());
            return review && done;
        });
        chk("IAM template without capabilities → InsufficientCapabilitiesException", () -> {
            try {
                cf.createStack(CreateStackRequest.builder().stackName(name + "-iam").templateBody(
                    "{\"Resources\":{\"R\":{\"Type\":\"AWS::IAM::Role\",\"Properties\":{}}}}").build());
                return false;
            } catch (InsufficientCapabilitiesException e) { return true; }
        });
        chk("a failing resource type rolls the stack back (ROLLBACK_COMPLETE)", () -> {
            String n3 = name + "-bad";
            cf.createStack(CreateStackRequest.builder().stackName(n3).templateBody(
                "{\"Resources\":{\"X\":{\"Type\":\"NotAReal::Type\"}}}").build());
            boolean rb = status(cf, n3) == StackStatus.ROLLBACK_COMPLETE;
            cf.deleteStack(DeleteStackRequest.builder().stackName(n3).build());
            return rb;
        });
        chk("DeleteStack then DescribeStacks → does not exist", () -> {
            cf.deleteStack(DeleteStackRequest.builder().stackName(name).build());
            try { cf.describeStacks(DescribeStacksRequest.builder().stackName(name).build()); return false; }
            catch (CloudFormationException e) { return e.getMessage().contains("does not exist"); }
        });
        chk("ListStacks(DELETE_COMPLETE) keeps history", () ->
            cf.listStacks(ListStacksRequest.builder().stackStatusFilters(StackStatus.DELETE_COMPLETE).build())
                .stackSummaries().stream().anyMatch(s -> s.stackName().equals(name)));

        System.out.println("\n" + pass + " passed, " + fail + " failed");
        System.exit(fail > 0 ? 1 : 0);
    }
}
