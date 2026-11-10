// Real AWS SDK for Java v2 CloudWatch conformance probe against Vyomi.
// Only the endpoint is overridden. One [PASS]/[FAIL] line per check; non-zero exit on failure.
//
//   ENDPOINT=http://127.0.0.1:9000 mvn -q -B compile exec:java -Dexec.mainClass=AwsCloudWatchConformance

import java.net.URI;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;

import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.cloudwatch.CloudWatchClient;
import software.amazon.awssdk.services.cloudwatch.model.*;

public class AwsCloudWatchConformance {
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
        return (e instanceof CloudWatchException c && c.awsErrorDetails() != null)
            ? c.awsErrorDetails().errorCode() : e.toString();
    }

    public static void main(String[] args) {
        String endpoint = System.getenv().getOrDefault("ENDPOINT", "http://127.0.0.1:9000");
        System.out.println("== aws-sdk-java-v2 cloudwatch against " + endpoint + " ==");
        CloudWatchClient cw = CloudWatchClient.builder()
            .endpointOverride(URI.create(endpoint)).region(Region.US_EAST_1)
            .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
            .build();
        String sfx = String.valueOf(System.nanoTime() % 1000000000L);
        String ns = "JavaApp" + sfx, alarm = "java-alarm-" + sfx, comp = "java-comp-" + sfx, dash = "java-dash-" + sfx;
        Dimension dim = Dimension.builder().name("Service").value("billing").build();
        Instant now = Instant.now();

        chk("PutMetricData (Value + Values/Counts + StatisticValues)", () -> {
            cw.putMetricData(PutMetricDataRequest.builder().namespace(ns).metricData(
                MetricDatum.builder().metricName("Latency").dimensions(dim).value(120.0).unit(StandardUnit.MILLISECONDS).timestamp(now).build(),
                MetricDatum.builder().metricName("Latency").dimensions(dim).values(10.0, 20.0).counts(1.0, 3.0).timestamp(now).build(),
                MetricDatum.builder().metricName("Errors").dimensions(dim).statisticValues(
                    StatisticSet.builder().sampleCount(4.0).sum(8.0).minimum(1.0).maximum(3.0).build()).build()).build());
            return true;
        });
        chk("PutMetricData into an AWS/ namespace is rejected", () -> {
            try {
                cw.putMetricData(PutMetricDataRequest.builder().namespace("AWS/EC2").metricData(
                    MetricDatum.builder().metricName("X").value(1.0).build()).build());
                return false;
            } catch (CloudWatchException e) { return "InvalidParameterValue".equals(code(e)); }
        });
        chk("ListMetrics returns the two metrics", () -> {
            List<Metric> ms = cw.listMetrics(ListMetricsRequest.builder().namespace(ns).build()).metrics();
            return ms.size() == 2 && ms.stream().allMatch(m -> m.dimensions().size() == 1 && m.dimensions().get(0).value().equals("billing"));
        });
        chk("ListMetrics filters by dimension", () ->
            cw.listMetrics(ListMetricsRequest.builder().namespace(ns).dimensions(
                DimensionFilter.builder().name("Service").value("nope").build()).build()).metrics().isEmpty());
        chk("GetMetricStatistics aggregates (Sum 190, SampleCount 5, Min 10, Max 120)", () -> {
            List<Datapoint> dps = cw.getMetricStatistics(GetMetricStatisticsRequest.builder().namespace(ns).metricName("Latency").dimensions(dim)
                .startTime(now.minus(10, ChronoUnit.MINUTES)).endTime(now.plus(1, ChronoUnit.MINUTES)).period(3600)
                .statistics(Statistic.SUM, Statistic.SAMPLE_COUNT, Statistic.MINIMUM, Statistic.MAXIMUM, Statistic.AVERAGE).build()).datapoints();
            double sum = dps.stream().mapToDouble(Datapoint::sum).sum(), cnt = dps.stream().mapToDouble(Datapoint::sampleCount).sum();
            return !dps.isEmpty() && sum == 190.0 && cnt == 5.0 && dps.stream().mapToDouble(Datapoint::minimum).min().getAsDouble() == 10.0
                && dps.stream().mapToDouble(Datapoint::maximum).max().getAsDouble() == 120.0;
        });
        chk("GetMetricStatistics without Statistics → InvalidParameterCombination", () -> {
            try {
                cw.getMetricStatistics(GetMetricStatisticsRequest.builder().namespace(ns).metricName("Latency")
                    .startTime(now.minus(1, ChronoUnit.HOURS)).endTime(now).period(60).build());
                return false;
            } catch (CloudWatchException e) { return "InvalidParameterCombination".equals(code(e)); }
        });
        chk("GetMetricData with a metric-math expression", () -> {
            List<MetricDataResult> rs = cw.getMetricData(GetMetricDataRequest.builder()
                .startTime(now.minus(10, ChronoUnit.MINUTES)).endTime(now.plus(1, ChronoUnit.MINUTES))
                .metricDataQueries(
                    MetricDataQuery.builder().id("e").metricStat(MetricStat.builder().period(3600).stat("Sum").metric(
                        Metric.builder().namespace(ns).metricName("Errors").dimensions(dim).build()).build()).returnData(false).build(),
                    MetricDataQuery.builder().id("tripled").expression("e * 3").label("Tripled").build()).build()).metricDataResults();
            return rs.size() == 1 && rs.get(0).id().equals("tripled") && rs.get(0).values().stream().mapToDouble(Double::doubleValue).sum() == 24.0
                && rs.get(0).statusCode() == StatusCode.COMPLETE;
        });

        chk("PutMetricAlarm", () -> {
            cw.putMetricAlarm(PutMetricAlarmRequest.builder().alarmName(alarm).namespace(ns).metricName("Latency").dimensions(dim)
                .statistic(Statistic.MAXIMUM).period(60).evaluationPeriods(1).threshold(100.0)
                .comparisonOperator(ComparisonOperator.GREATER_THAN_THRESHOLD).alarmActions("arn:aws:sns:us-east-1:123456789012:java-alerts")
                .tags(Tag.builder().key("team").value("sre").build()).build());
            return true;
        });
        chk("DescribeAlarms round-trips the alarm", () -> {
            MetricAlarm a = cw.describeAlarms(DescribeAlarmsRequest.builder().alarmNames(alarm).build()).metricAlarms().get(0);
            return a.threshold() == 100.0 && a.period() == 60 && a.comparisonOperator() == ComparisonOperator.GREATER_THAN_THRESHOLD
                && a.alarmArn().equals("arn:aws:cloudwatch:us-east-1:123456789012:alarm:" + alarm) && a.alarmActions().size() == 1 && a.actionsEnabled();
        });
        chk("a breaching datapoint moves the alarm to ALARM", () -> {
            cw.putMetricData(PutMetricDataRequest.builder().namespace(ns).metricData(
                MetricDatum.builder().metricName("Latency").dimensions(dim).value(900.0).build()).build());
            return cw.describeAlarms(DescribeAlarmsRequest.builder().alarmNames(alarm).build()).metricAlarms().get(0).stateValue() == StateValue.ALARM;
        });
        chk("DescribeAlarms StateValue filter", () ->
            cw.describeAlarms(DescribeAlarmsRequest.builder().stateValue(StateValue.ALARM).alarmNamePrefix("java-alarm-").build())
                .metricAlarms().stream().anyMatch(a -> a.alarmName().equals(alarm)));
        chk("DescribeAlarms rejects AlarmNames + AlarmNamePrefix", () -> {
            try { cw.describeAlarms(DescribeAlarmsRequest.builder().alarmNames(alarm).alarmNamePrefix("x").build()); return false; }
            catch (CloudWatchException e) { return "InvalidParameterCombination".equals(code(e)); }
        });
        chk("SetAlarmState OK with a reason", () -> {
            cw.setAlarmState(SetAlarmStateRequest.builder().alarmName(alarm).stateValue(StateValue.OK).stateReason("manual").build());
            MetricAlarm a = cw.describeAlarms(DescribeAlarmsRequest.builder().alarmNames(alarm).build()).metricAlarms().get(0);
            return a.stateValue() == StateValue.OK && "manual".equals(a.stateReason());
        });
        chk("SetAlarmState on a missing alarm → ResourceNotFound", () -> {
            try { cw.setAlarmState(SetAlarmStateRequest.builder().alarmName("missing-" + sfx).stateValue(StateValue.OK).stateReason("x").build()); return false; }
            catch (CloudWatchException e) { return "ResourceNotFound".equals(code(e)) && e.statusCode() == 404; }
        });
        chk("DescribeAlarmHistory has state-update items", () ->
            cw.describeAlarmHistory(DescribeAlarmHistoryRequest.builder().alarmName(alarm).historyItemType(HistoryItemType.STATE_UPDATE).build())
                .alarmHistoryItems().size() >= 2);
        chk("PutCompositeAlarm evaluates its rule", () -> {
            cw.putCompositeAlarm(PutCompositeAlarmRequest.builder().alarmName(comp).alarmRule("OK(\"" + alarm + "\")").build());
            CompositeAlarm c = cw.describeAlarms(DescribeAlarmsRequest.builder().alarmNames(comp).alarmTypes(AlarmType.COMPOSITE_ALARM).build()).compositeAlarms().get(0);
            return c.stateValue() == StateValue.ALARM && c.alarmRule().contains(alarm);
        });
        chk("DeleteAlarms protects an alarm used by a composite", () -> {
            try { cw.deleteAlarms(DeleteAlarmsRequest.builder().alarmNames(alarm).build()); return false; }
            catch (CloudWatchException e) { return "ResourceConflict".equals(code(e)); }
        });
        chk("Disable/EnableAlarmActions", () -> {
            cw.disableAlarmActions(DisableAlarmActionsRequest.builder().alarmNames(alarm).build());
            boolean off = !cw.describeAlarms(DescribeAlarmsRequest.builder().alarmNames(alarm).build()).metricAlarms().get(0).actionsEnabled();
            cw.enableAlarmActions(EnableAlarmActionsRequest.builder().alarmNames(alarm).build());
            return off && cw.describeAlarms(DescribeAlarmsRequest.builder().alarmNames(alarm).build()).metricAlarms().get(0).actionsEnabled();
        });
        chk("TagResource / ListTagsForResource / UntagResource", () -> {
            String arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:" + alarm;
            cw.tagResource(TagResourceRequest.builder().resourceARN(arn).tags(Tag.builder().key("env").value("test").build()).build());
            boolean two = cw.listTagsForResource(ListTagsForResourceRequest.builder().resourceARN(arn).build()).tags().size() == 2;
            cw.untagResource(UntagResourceRequest.builder().resourceARN(arn).tagKeys("env").build());
            return two && cw.listTagsForResource(ListTagsForResourceRequest.builder().resourceARN(arn).build()).tags().size() == 1;
        });

        chk("PutDashboard / GetDashboard / ListDashboards / DeleteDashboards", () -> {
            cw.putDashboard(PutDashboardRequest.builder().dashboardName(dash).dashboardBody("{\"widgets\":[]}").build());
            GetDashboardResponse g = cw.getDashboard(GetDashboardRequest.builder().dashboardName(dash).build());
            boolean listed = cw.listDashboards(ListDashboardsRequest.builder().dashboardNamePrefix(dash).build()).dashboardEntries().size() == 1;
            cw.deleteDashboards(DeleteDashboardsRequest.builder().dashboardNames(dash).build());
            return g.dashboardBody().equals("{\"widgets\":[]}") && g.dashboardArn().endsWith(":dashboard/" + dash) && listed;
        });
        chk("GetDashboard on a missing dashboard → ResourceNotFound", () -> {
            try { cw.getDashboard(GetDashboardRequest.builder().dashboardName(dash).build()); return false; }
            catch (CloudWatchException e) { return "ResourceNotFound".equals(code(e)); }
        });
        chk("PutDashboard with an invalid body → InvalidParameterInput", () -> {
            try { cw.putDashboard(PutDashboardRequest.builder().dashboardName(dash).dashboardBody("{bad").build()); return false; }
            catch (CloudWatchException e) { return "InvalidParameterInput".equals(code(e)); }
        });

        chk("PutAnomalyDetector / DescribeAnomalyDetectors / DeleteAnomalyDetector", () -> {
            cw.putAnomalyDetector(PutAnomalyDetectorRequest.builder().namespace(ns).metricName("Latency").dimensions(dim).stat("Average").build());
            List<AnomalyDetector> ds = cw.describeAnomalyDetectors(DescribeAnomalyDetectorsRequest.builder().namespace(ns).build()).anomalyDetectors();
            cw.deleteAnomalyDetector(DeleteAnomalyDetectorRequest.builder().namespace(ns).metricName("Latency").dimensions(dim).stat("Average").build());
            return ds.size() == 1 && ds.get(0).stateValue() == AnomalyDetectorStateValue.PENDING_TRAINING
                && cw.describeAnomalyDetectors(DescribeAnomalyDetectorsRequest.builder().namespace(ns).build()).anomalyDetectors().isEmpty();
        });
        chk("PutInsightRule / DescribeInsightRules / DeleteInsightRules", () -> {
            cw.putInsightRule(PutInsightRuleRequest.builder().ruleName("java-rule-" + sfx).ruleState("ENABLED").ruleDefinition(
                "{\"Schema\":{\"Name\":\"CloudWatchLogRule\",\"Version\":1},\"LogGroupNames\":[\"/x\"],\"LogFormat\":\"JSON\",\"Fields\":{},\"Contribution\":{\"Keys\":[\"$.ip\"],\"Filters\":[]},\"AggregateOn\":\"Count\"}").build());
            boolean listed = cw.describeInsightRules(DescribeInsightRulesRequest.builder().build()).insightRules().stream().anyMatch(r -> r.name().equals("java-rule-" + sfx));
            cw.disableInsightRules(DisableInsightRulesRequest.builder().ruleNames("java-rule-" + sfx).build());
            boolean off = cw.describeInsightRules(DescribeInsightRulesRequest.builder().build()).insightRules().stream().anyMatch(r -> r.name().equals("java-rule-" + sfx) && r.state().equals("DISABLED"));
            return listed && off && cw.deleteInsightRules(DeleteInsightRulesRequest.builder().ruleNames("java-rule-" + sfx).build()).failures().isEmpty();
        });
        chk("PutMetricStream / ListMetricStreams / Start / Stop / Delete", () -> {
            String n = "java-stream-" + sfx;
            String arn = cw.putMetricStream(PutMetricStreamRequest.builder().name(n).firehoseArn("arn:aws:firehose:us-east-1:123456789012:deliverystream/x")
                .roleArn("arn:aws:iam::123456789012:role/r").outputFormat(MetricStreamOutputFormat.JSON).build()).arn();
            boolean listed = cw.listMetricStreams(ListMetricStreamsRequest.builder().build()).entries().stream().anyMatch(e -> e.name().equals(n));
            cw.stopMetricStreams(StopMetricStreamsRequest.builder().names(n).build());
            boolean stopped = "stopped".equals(cw.getMetricStream(GetMetricStreamRequest.builder().name(n).build()).state());
            cw.startMetricStreams(StartMetricStreamsRequest.builder().names(n).build());
            boolean running = "running".equals(cw.getMetricStream(GetMetricStreamRequest.builder().name(n).build()).state());
            cw.deleteMetricStream(DeleteMetricStreamRequest.builder().name(n).build());
            return arn.endsWith(":metric-stream/" + n) && listed && stopped && running;
        });

        chk("DeleteAlarms removes composite + metric alarm", () -> {
            cw.deleteAlarms(DeleteAlarmsRequest.builder().alarmNames(comp, alarm).build());
            return cw.describeAlarms(DescribeAlarmsRequest.builder().alarmNamePrefix("java-").alarmTypes(AlarmType.METRIC_ALARM, AlarmType.COMPOSITE_ALARM).build())
                .metricAlarms().stream().noneMatch(a -> a.alarmName().endsWith(sfx));
        });

        System.out.println("\n" + pass + " passed, " + fail + " failed");
        System.exit(fail > 0 ? 1 : 0);
    }
}
