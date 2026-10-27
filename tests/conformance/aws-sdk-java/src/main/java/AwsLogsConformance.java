// Real aws-sdk-java-v2 CloudWatch Logs conformance against Vyomi (endpoint override only).
// Runs inside the AWS SDK runner (AwsSdkConformance.main) and standalone:
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=AwsLogsConformance
// One [PASS]/[FAIL] line per check; exits non-zero on any failure when run standalone.

import java.net.URI;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.cloudwatchlogs.CloudWatchLogsClient;
import software.amazon.awssdk.services.cloudwatchlogs.model.*;

public class AwsLogsConformance {
    static int failed = 0;

    static void check(String name, Callable<Boolean> body) {
        try {
            if (body.call()) System.out.println("[PASS] " + name);
            else { failed++; System.out.println("[FAIL] " + name + " :: assertion false"); }
        } catch (Throwable t) {
            failed++;
            System.out.println("[FAIL] " + name + " :: " + t);
        }
    }

    /** Returns the number of failed checks. */
    public static int run(String endpoint) {
        failed = 0;
        CloudWatchLogsClient c = CloudWatchLogsClient.builder()
                .endpointOverride(URI.create(endpoint)).region(Region.US_EAST_1)
                .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test"))).build();
        String group = "/vyomi/java-" + System.nanoTime();
        String stream = "app-1";
        long now = System.currentTimeMillis();

        check("CreateLogGroup", () -> { c.createLogGroup(b -> b.logGroupName(group).tags(Map.of("env", "dev"))); return true; });
        check("duplicate CreateLogGroup → ResourceAlreadyExistsException", () -> {
            try { c.createLogGroup(b -> b.logGroupName(group)); return false; }
            catch (ResourceAlreadyExistsException e) { return true; }
        });
        check("DescribeLogGroups", () -> {
            List<LogGroup> g = c.describeLogGroups(b -> b.logGroupNamePrefix(group)).logGroups();
            return g.size() == 1 && g.get(0).logGroupName().equals(group) && g.get(0).arn().endsWith(":*");
        });
        check("PutRetentionPolicy + visible", () -> {
            c.putRetentionPolicy(b -> b.logGroupName(group).retentionInDays(30));
            return c.describeLogGroups(b -> b.logGroupNamePrefix(group)).logGroups().get(0).retentionInDays() == 30;
        });
        check("CreateLogStream", () -> { c.createLogStream(b -> b.logGroupName(group).logStreamName(stream)); return true; });
        check("PutLogEvents", () -> {
            PutLogEventsResponse r = c.putLogEvents(b -> b.logGroupName(group).logStreamName(stream).logEvents(
                    InputLogEvent.builder().timestamp(now).message("request ok").build(),
                    InputLogEvent.builder().timestamp(now + 1).message("request failed ERROR 500").build()));
            return r.nextSequenceToken() != null;
        });
        check("GetLogEvents", () -> {
            List<OutputLogEvent> ev = c.getLogEvents(b -> b.logGroupName(group).logStreamName(stream).startFromHead(true)).events();
            return ev.size() == 2 && ev.get(0).message().equals("request ok");
        });
        check("FilterLogEvents", () -> {
            List<FilteredLogEvent> ev = c.filterLogEvents(b -> b.logGroupName(group).filterPattern("ERROR")).events();
            return ev.size() == 1 && ev.get(0).message().contains("500");
        });
        check("DescribeLogStreams", () -> {
            List<LogStream> s = c.describeLogStreams(b -> b.logGroupName(group)).logStreams();
            return s.size() == 1 && s.get(0).storedBytes() > 0;
        });
        check("PutMetricFilter + DescribeMetricFilters", () -> {
            c.putMetricFilter(b -> b.logGroupName(group).filterName("errors").filterPattern("ERROR").metricTransformations(
                    MetricTransformation.builder().metricName("Errors").metricNamespace("Vyomi").metricValue("1").build()));
            return c.describeMetricFilters(b -> b.logGroupName(group)).metricFilters().size() == 1;
        });
        check("PutSubscriptionFilter + DescribeSubscriptionFilters", () -> {
            c.putSubscriptionFilter(b -> b.logGroupName(group).filterName("fwd").filterPattern("")
                    .destinationArn("arn:aws:lambda:us-east-1:123456789012:function:sink"));
            return c.describeSubscriptionFilters(b -> b.logGroupName(group)).subscriptionFilters().size() == 1;
        });
        check("TagLogGroup + ListTagsLogGroup", () -> {
            c.tagLogGroup(b -> b.logGroupName(group).tags(Map.of("team", "obs")));
            Map<String, String> t = c.listTagsLogGroup(b -> b.logGroupName(group)).tags();
            return "obs".equals(t.get("team")) && "dev".equals(t.get("env"));
        });
        check("StartQuery + GetQueryResults", () -> {
            String qid = c.startQuery(b -> b.logGroupName(group).startTime(now / 1000 - 60).endTime(now / 1000 + 60)
                    .queryString("fields @message | filter @message like /ERROR/")).queryId();
            GetQueryResultsResponse r = c.getQueryResults(b -> b.queryId(qid));
            return r.status() == QueryStatus.COMPLETE && r.results().size() == 1;
        });
        check("DeleteLogStream", () -> { c.deleteLogStream(b -> b.logGroupName(group).logStreamName(stream)); return true; });
        check("DeleteLogGroup", () -> { c.deleteLogGroup(b -> b.logGroupName(group)); return true; });
        check("deleted group → ResourceNotFoundException", () -> {
            try { c.deleteLogGroup(b -> b.logGroupName(group)); return false; }
            catch (ResourceNotFoundException e) { return true; }
        });
        c.close();
        return failed;
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        System.out.println("== aws-sdk-java-v2 CloudWatch Logs against " + endpoint + " ==");
        System.exit(run(endpoint) > 0 ? 1 : 0);
    }
}
