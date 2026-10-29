// Real aws-sdk-go-v2 CloudWatch conformance probe against Vyomi.
// Only the endpoint is overridden (current SDKs speak smithy-rpc-v2-cbor to CloudWatch).
// Prints one [PASS]/[FAIL] line per check and exits non-zero on any failure.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/cloudwatch"
	"github.com/aws/aws-sdk-go-v2/service/cloudwatch/types"
	"github.com/aws/smithy-go"
)

var pass, fail int

func chk(name string, ok bool, detail string) {
	if ok {
		pass++
		fmt.Printf("[PASS] %s\n", name)
		return
	}
	fail++
	fmt.Printf("[FAIL] %s :: %s\n", name, detail)
}

func code(err error) string {
	var ae smithy.APIError
	if errors.As(err, &ae) {
		return ae.ErrorCode()
	}
	if err != nil {
		return err.Error()
	}
	return ""
}

func main() {
	endpoint := os.Getenv("ENDPOINT")
	if endpoint == "" {
		endpoint = "http://127.0.0.1:9000"
	}
	ctx := context.Background()
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRegion("us-east-1"),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")))
	if err != nil {
		fmt.Println("[FAIL] load config ::", err)
		os.Exit(1)
	}
	cw := cloudwatch.NewFromConfig(cfg, func(o *cloudwatch.Options) { o.BaseEndpoint = aws.String(endpoint) })
	fmt.Printf("== aws-sdk-go-v2 cloudwatch against %s ==\n", endpoint)

	sfx := fmt.Sprintf("%d", time.Now().UnixNano()%1000000000)
	ns := "GoApp" + sfx
	alarm := "go-alarm-" + sfx
	comp := "go-composite-" + sfx
	dash := "go-dash-" + sfx
	dims := []types.Dimension{{Name: aws.String("Service"), Value: aws.String("checkout")}}
	now := time.Now()

	_, err = cw.PutMetricData(ctx, &cloudwatch.PutMetricDataInput{Namespace: aws.String(ns), MetricData: []types.MetricDatum{
		{MetricName: aws.String("Latency"), Dimensions: dims, Value: aws.Float64(120), Unit: types.StandardUnitMilliseconds, Timestamp: aws.Time(now)},
		{MetricName: aws.String("Latency"), Dimensions: dims, Values: []float64{10, 20}, Counts: []float64{1, 3}, Timestamp: aws.Time(now)},
		{MetricName: aws.String("Errors"), Dimensions: dims, StatisticValues: &types.StatisticSet{SampleCount: aws.Float64(4), Sum: aws.Float64(8), Minimum: aws.Float64(1), Maximum: aws.Float64(3)}},
	}})
	chk("PutMetricData (Value, Values+Counts, StatisticValues)", err == nil, code(err))

	_, err = cw.PutMetricData(ctx, &cloudwatch.PutMetricDataInput{Namespace: aws.String("AWS/EC2"), MetricData: []types.MetricDatum{{MetricName: aws.String("X"), Value: aws.Float64(1)}}})
	chk("PutMetricData into AWS/ is rejected (InvalidParameterValue)", code(err) == "InvalidParameterValue", code(err))

	lm, err := cw.ListMetrics(ctx, &cloudwatch.ListMetricsInput{Namespace: aws.String(ns)})
	names := map[string]bool{}
	if err == nil {
		for _, m := range lm.Metrics {
			names[aws.ToString(m.MetricName)] = len(m.Dimensions) == 1 && aws.ToString(m.Dimensions[0].Value) == "checkout"
		}
	}
	chk("ListMetrics returns both metrics with their dimensions", err == nil && names["Latency"] && names["Errors"], fmt.Sprint(err, names))

	st, err := cw.GetMetricStatistics(ctx, &cloudwatch.GetMetricStatisticsInput{Namespace: aws.String(ns), MetricName: aws.String("Latency"), Dimensions: dims,
		StartTime: aws.Time(now.Add(-10 * time.Minute)), EndTime: aws.Time(now.Add(time.Minute)), Period: aws.Int32(3600),
		Statistics: []types.Statistic{types.StatisticAverage, types.StatisticSum, types.StatisticSampleCount, types.StatisticMaximum, types.StatisticMinimum}})
	ok := err == nil && len(st.Datapoints) >= 1
	chk("GetMetricStatistics returns datapoints", ok, fmt.Sprint(err))
	if ok {
		var sum, cnt, maxv, minv float64
		minv = 1e18
		for _, d := range st.Datapoints {
			sum += aws.ToFloat64(d.Sum)
			cnt += aws.ToFloat64(d.SampleCount)
			if aws.ToFloat64(d.Maximum) > maxv {
				maxv = aws.ToFloat64(d.Maximum)
			}
			if aws.ToFloat64(d.Minimum) < minv {
				minv = aws.ToFloat64(d.Minimum)
			}
		}
		chk("statistics are aggregated (Sum=190, SampleCount=5, Min=10, Max=120)", sum == 190 && cnt == 5 && minv == 10 && maxv == 120, fmt.Sprint(sum, cnt, minv, maxv))
	}
	pc, err := cw.GetMetricStatistics(ctx, &cloudwatch.GetMetricStatisticsInput{Namespace: aws.String(ns), MetricName: aws.String("Latency"), Dimensions: dims,
		StartTime: aws.Time(now.Add(-10 * time.Minute)), EndTime: aws.Time(now.Add(time.Minute)), Period: aws.Int32(3600), ExtendedStatistics: []string{"p99"}})
	chk("GetMetricStatistics ExtendedStatistics p99", err == nil && len(pc.Datapoints) >= 1 && pc.Datapoints[0].ExtendedStatistics["p99"] == 120, fmt.Sprint(err))
	_, err = cw.GetMetricStatistics(ctx, &cloudwatch.GetMetricStatisticsInput{Namespace: aws.String(ns), MetricName: aws.String("Latency"),
		StartTime: aws.Time(now), EndTime: aws.Time(now.Add(-time.Hour)), Period: aws.Int32(60), Statistics: []types.Statistic{types.StatisticSum}})
	chk("GetMetricStatistics StartTime >= EndTime → InvalidParameterValue", code(err) == "InvalidParameterValue", code(err))

	md, err := cw.GetMetricData(ctx, &cloudwatch.GetMetricDataInput{StartTime: aws.Time(now.Add(-10 * time.Minute)), EndTime: aws.Time(now.Add(time.Minute)),
		MetricDataQueries: []types.MetricDataQuery{
			{Id: aws.String("lat"), MetricStat: &types.MetricStat{Metric: &types.Metric{Namespace: aws.String(ns), MetricName: aws.String("Latency"), Dimensions: dims}, Period: aws.Int32(3600), Stat: aws.String("Sum")}, ReturnData: aws.Bool(false)},
			{Id: aws.String("double"), Expression: aws.String("lat * 2"), Label: aws.String("DoubleLatency")},
		}})
	ok = err == nil && len(md.MetricDataResults) == 1 && aws.ToString(md.MetricDataResults[0].Id) == "double"
	chk("GetMetricData metric-math expression (ReturnData=false hides the input)", ok, fmt.Sprint(err))
	if ok {
		var tot float64
		for _, v := range md.MetricDataResults[0].Values {
			tot += v
		}
		chk("expression result is lat*2 (380)", tot == 380 && md.MetricDataResults[0].StatusCode == types.StatusCodeComplete, fmt.Sprint(tot, md.MetricDataResults[0].StatusCode))
	}

	_, err = cw.PutMetricAlarm(ctx, &cloudwatch.PutMetricAlarmInput{AlarmName: aws.String(alarm), Namespace: aws.String(ns), MetricName: aws.String("Latency"), Dimensions: dims,
		Statistic: types.StatisticMaximum, Period: aws.Int32(60), EvaluationPeriods: aws.Int32(1), Threshold: aws.Float64(100),
		ComparisonOperator: types.ComparisonOperatorGreaterThanThreshold, AlarmActions: []string{"arn:aws:sns:us-east-1:123456789012:go-alerts"},
		Tags: []types.Tag{{Key: aws.String("team"), Value: aws.String("sre")}}})
	chk("PutMetricAlarm", err == nil, code(err))
	da, err := cw.DescribeAlarms(ctx, &cloudwatch.DescribeAlarmsInput{AlarmNames: []string{alarm}})
	ok = err == nil && len(da.MetricAlarms) == 1
	chk("DescribeAlarms returns the alarm", ok, fmt.Sprint(err))
	if ok {
		a := da.MetricAlarms[0]
		chk("alarm fields round-trip", aws.ToFloat64(a.Threshold) == 100 && aws.ToInt32(a.Period) == 60 && a.ComparisonOperator == types.ComparisonOperatorGreaterThanThreshold &&
			aws.ToString(a.AlarmArn) == "arn:aws:cloudwatch:us-east-1:123456789012:alarm:"+alarm && len(a.AlarmActions) == 1, fmt.Sprint(a))
	}
	// data already in the window breaches; a new datapoint re-evaluates the alarm
	_, err = cw.PutMetricData(ctx, &cloudwatch.PutMetricDataInput{Namespace: aws.String(ns), MetricData: []types.MetricDatum{{MetricName: aws.String("Latency"), Dimensions: dims, Value: aws.Float64(500)}}})
	da, _ = cw.DescribeAlarms(ctx, &cloudwatch.DescribeAlarmsInput{AlarmNames: []string{alarm}})
	chk("alarm goes to ALARM when a datapoint breaches the threshold", err == nil && len(da.MetricAlarms) == 1 && da.MetricAlarms[0].StateValue == types.StateValueAlarm, fmt.Sprint(err))

	_, err = cw.SetAlarmState(ctx, &cloudwatch.SetAlarmStateInput{AlarmName: aws.String(alarm), StateValue: types.StateValueOk, StateReason: aws.String("manual test")})
	da, _ = cw.DescribeAlarms(ctx, &cloudwatch.DescribeAlarmsInput{AlarmNames: []string{alarm}})
	chk("SetAlarmState → OK", err == nil && len(da.MetricAlarms) == 1 && da.MetricAlarms[0].StateValue == types.StateValueOk && aws.ToString(da.MetricAlarms[0].StateReason) == "manual test", fmt.Sprint(err))
	_, err = cw.SetAlarmState(ctx, &cloudwatch.SetAlarmStateInput{AlarmName: aws.String("no-such-" + sfx), StateValue: types.StateValueOk, StateReason: aws.String("x")})
	chk("SetAlarmState on a missing alarm → ResourceNotFound", code(err) == "ResourceNotFound", code(err))

	h, err := cw.DescribeAlarmHistory(ctx, &cloudwatch.DescribeAlarmHistoryInput{AlarmName: aws.String(alarm)})
	kinds := map[types.HistoryItemType]int{}
	if err == nil {
		for _, it := range h.AlarmHistoryItems {
			kinds[it.HistoryItemType]++
		}
	}
	chk("DescribeAlarmHistory has configuration, state and action items", err == nil && kinds[types.HistoryItemTypeConfigurationUpdate] >= 1 && kinds[types.HistoryItemTypeStateUpdate] >= 2 && kinds[types.HistoryItemTypeAction] >= 1, fmt.Sprint(err, kinds))

	_, err = cw.PutCompositeAlarm(ctx, &cloudwatch.PutCompositeAlarmInput{AlarmName: aws.String(comp), AlarmRule: aws.String(`ALARM("` + alarm + `") OR OK("` + alarm + `")`)})
	dc, err2 := cw.DescribeAlarms(ctx, &cloudwatch.DescribeAlarmsInput{AlarmNames: []string{comp}, AlarmTypes: []types.AlarmType{types.AlarmTypeCompositeAlarm}})
	chk("PutCompositeAlarm + DescribeAlarms(CompositeAlarm)", err == nil && err2 == nil && len(dc.CompositeAlarms) == 1 && dc.CompositeAlarms[0].StateValue == types.StateValueAlarm, fmt.Sprint(err, err2))

	_, err = cw.DisableAlarmActions(ctx, &cloudwatch.DisableAlarmActionsInput{AlarmNames: []string{alarm}})
	da, _ = cw.DescribeAlarms(ctx, &cloudwatch.DescribeAlarmsInput{AlarmNames: []string{alarm}})
	chk("DisableAlarmActions", err == nil && len(da.MetricAlarms) == 1 && !aws.ToBool(da.MetricAlarms[0].ActionsEnabled), fmt.Sprint(err))
	_, err = cw.EnableAlarmActions(ctx, &cloudwatch.EnableAlarmActionsInput{AlarmNames: []string{alarm}})
	chk("EnableAlarmActions", err == nil, code(err))

	tg, err := cw.ListTagsForResource(ctx, &cloudwatch.ListTagsForResourceInput{ResourceARN: aws.String("arn:aws:cloudwatch:us-east-1:123456789012:alarm:" + alarm)})
	chk("ListTagsForResource returns the alarm's tags", err == nil && len(tg.Tags) == 1 && aws.ToString(tg.Tags[0].Key) == "team", fmt.Sprint(err))
	_, err = cw.TagResource(ctx, &cloudwatch.TagResourceInput{ResourceARN: aws.String("arn:aws:cloudwatch:us-east-1:123456789012:alarm:" + alarm), Tags: []types.Tag{{Key: aws.String("env"), Value: aws.String("test")}}})
	tg, _ = cw.ListTagsForResource(ctx, &cloudwatch.ListTagsForResourceInput{ResourceARN: aws.String("arn:aws:cloudwatch:us-east-1:123456789012:alarm:" + alarm)})
	chk("TagResource adds a tag", err == nil && len(tg.Tags) == 2, fmt.Sprint(err))
	_, err = cw.UntagResource(ctx, &cloudwatch.UntagResourceInput{ResourceARN: aws.String("arn:aws:cloudwatch:us-east-1:123456789012:alarm:" + alarm), TagKeys: []string{"env"}})
	tg, _ = cw.ListTagsForResource(ctx, &cloudwatch.ListTagsForResourceInput{ResourceARN: aws.String("arn:aws:cloudwatch:us-east-1:123456789012:alarm:" + alarm)})
	chk("UntagResource removes it", err == nil && len(tg.Tags) == 1, fmt.Sprint(err))

	_, err = cw.PutDashboard(ctx, &cloudwatch.PutDashboardInput{DashboardName: aws.String(dash), DashboardBody: aws.String(`{"widgets":[{"type":"text","x":0,"y":0,"width":6,"height":3,"properties":{"markdown":"hi"}}]}`)})
	chk("PutDashboard", err == nil, code(err))
	_, err = cw.PutDashboard(ctx, &cloudwatch.PutDashboardInput{DashboardName: aws.String(dash + "-bad"), DashboardBody: aws.String(`{not json`)})
	chk("PutDashboard with a bad body → InvalidParameterInput", code(err) == "InvalidParameterInput", code(err))
	gd, err := cw.GetDashboard(ctx, &cloudwatch.GetDashboardInput{DashboardName: aws.String(dash)})
	chk("GetDashboard returns the body and ARN", err == nil && strings.Contains(aws.ToString(gd.DashboardBody), "markdown") && strings.HasSuffix(aws.ToString(gd.DashboardArn), ":dashboard/"+dash), fmt.Sprint(err))
	ld, err := cw.ListDashboards(ctx, &cloudwatch.ListDashboardsInput{DashboardNamePrefix: aws.String("go-dash-" + sfx)})
	chk("ListDashboards by prefix", err == nil && len(ld.DashboardEntries) == 1 && aws.ToInt64(ld.DashboardEntries[0].Size) > 0, fmt.Sprint(err))
	_, err = cw.DeleteDashboards(ctx, &cloudwatch.DeleteDashboardsInput{DashboardNames: []string{dash}})
	chk("DeleteDashboards", err == nil, code(err))
	_, err = cw.GetDashboard(ctx, &cloudwatch.GetDashboardInput{DashboardName: aws.String(dash)})
	chk("GetDashboard after delete → ResourceNotFound", code(err) == "ResourceNotFound", code(err))

	_, err = cw.PutAnomalyDetector(ctx, &cloudwatch.PutAnomalyDetectorInput{Namespace: aws.String(ns), MetricName: aws.String("Latency"), Dimensions: dims, Stat: aws.String("Average")})
	ad, err2 := cw.DescribeAnomalyDetectors(ctx, &cloudwatch.DescribeAnomalyDetectorsInput{Namespace: aws.String(ns)})
	chk("PutAnomalyDetector + DescribeAnomalyDetectors", err == nil && err2 == nil && len(ad.AnomalyDetectors) == 1 && ad.AnomalyDetectors[0].StateValue == types.AnomalyDetectorStateValuePendingTraining, fmt.Sprint(err, err2))
	_, err = cw.DeleteAnomalyDetector(ctx, &cloudwatch.DeleteAnomalyDetectorInput{Namespace: aws.String(ns), MetricName: aws.String("Latency"), Dimensions: dims, Stat: aws.String("Average")})
	chk("DeleteAnomalyDetector", err == nil, code(err))

	_, err = cw.PutInsightRule(ctx, &cloudwatch.PutInsightRuleInput{RuleName: aws.String("go-rule-" + sfx), RuleState: aws.String("ENABLED"),
		RuleDefinition: aws.String(`{"Schema":{"Name":"CloudWatchLogRule","Version":1},"LogGroupNames":["/x"],"LogFormat":"JSON","Fields":{},"Contribution":{"Keys":["$.ip"],"Filters":[]},"AggregateOn":"Count"}`)})
	ir, err2 := cw.DescribeInsightRules(ctx, &cloudwatch.DescribeInsightRulesInput{})
	found := false
	if err2 == nil {
		for _, r := range ir.InsightRules {
			found = found || aws.ToString(r.Name) == "go-rule-"+sfx
		}
	}
	chk("PutInsightRule + DescribeInsightRules", err == nil && found, fmt.Sprint(err, err2))
	dr, err := cw.DeleteInsightRules(ctx, &cloudwatch.DeleteInsightRulesInput{RuleNames: []string{"go-rule-" + sfx, "missing-" + sfx}})
	chk("DeleteInsightRules reports the missing rule as a failure", err == nil && len(dr.Failures) == 1, fmt.Sprint(err))

	ps, err := cw.PutMetricStream(ctx, &cloudwatch.PutMetricStreamInput{Name: aws.String("go-stream-" + sfx), FirehoseArn: aws.String("arn:aws:firehose:us-east-1:123456789012:deliverystream/x"),
		RoleArn: aws.String("arn:aws:iam::123456789012:role/r"), OutputFormat: types.MetricStreamOutputFormatJson})
	chk("PutMetricStream returns the stream ARN", err == nil && strings.HasSuffix(aws.ToString(ps.Arn), ":metric-stream/go-stream-"+sfx), fmt.Sprint(err))
	_, err = cw.StopMetricStreams(ctx, &cloudwatch.StopMetricStreamsInput{Names: []string{"go-stream-" + sfx}})
	gs, err2 := cw.GetMetricStream(ctx, &cloudwatch.GetMetricStreamInput{Name: aws.String("go-stream-" + sfx)})
	chk("StopMetricStreams → GetMetricStream state stopped", err == nil && err2 == nil && aws.ToString(gs.State) == "stopped", fmt.Sprint(err, err2))
	_, err = cw.DeleteMetricStream(ctx, &cloudwatch.DeleteMetricStreamInput{Name: aws.String("go-stream-" + sfx)})
	_, err2 = cw.GetMetricStream(ctx, &cloudwatch.GetMetricStreamInput{Name: aws.String("go-stream-" + sfx)})
	chk("DeleteMetricStream then Get → ResourceNotFoundException", err == nil && code(err2) == "ResourceNotFoundException", code(err2))

	_, err = cw.DeleteAlarms(ctx, &cloudwatch.DeleteAlarmsInput{AlarmNames: []string{alarm}})
	chk("DeleteAlarms refuses an alarm a composite still references (ResourceConflict)", code(err) == "ResourceConflict", code(err))
	_, err = cw.DeleteAlarms(ctx, &cloudwatch.DeleteAlarmsInput{AlarmNames: []string{comp, alarm}})
	da, _ = cw.DescribeAlarms(ctx, &cloudwatch.DescribeAlarmsInput{AlarmNamePrefix: aws.String("go-")})
	left := 0
	if da != nil {
		for _, a := range da.MetricAlarms {
			if strings.HasSuffix(aws.ToString(a.AlarmName), sfx) {
				left++
			}
		}
	}
	chk("DeleteAlarms removes both", err == nil && left == 0, fmt.Sprint(err, left))

	fmt.Printf("\n%d passed, %d failed\n", pass, fail)
	if fail > 0 {
		os.Exit(1)
	}
}
