"""CloudWatch core — CBOR / JSON / Query wire on the shared router, alarms, metric math, persistence."""
import json
import math
import re
import time

from core import cloudwatch_core as cw
from core import lambda_core as lam
from core import sns_core as sns
from core import sqs_core as sqs
from core.aws_wire_router import AwsWireRouter
from core.persistent_store import PersistentCloudWatchStore, SqliteStateBackend

PREFIX = "/service/GraniteServiceVersion20100801/operation/"
CBOR_H = {"smithy-protocol": "rpc-v2-cbor", "content-type": "application/cbor"}


def cbor(router, op, **args):
    out = router.handle("POST", PREFIX + op, {}, CBOR_H, cw.cbor_encode(args))
    return out["status"], cw.cbor_decode(out["body"]), out["headers"]


def now():
    return time.time()


def test_cbor_codec_roundtrip():
    v = {"a": [1, -5, 2.5, "x", True, None], "n": {"k": 70000, "big": 2 ** 40}, "t": cw.Ts(1700000000.5)}
    got = cw.cbor_decode(cw.cbor_encode(v))
    assert got["a"] == [1, -5, 2.5, "x", True, None] and got["n"] == {"k": 70000, "big": 2 ** 40} and got["t"] == 1700000000.5


def test_router_detects_cloudwatch_on_all_three_protocols():
    r = AwsWireRouter()
    assert r.service_of("POST", PREFIX + "ListMetrics", {"smithy-protocol": "rpc-v2-cbor"}, b"") == "cloudwatch"
    assert r.service_of("POST", "/", {"x-amz-target": "GraniteServiceVersion20100801.ListMetrics"}, b"{}") == "cloudwatch"
    scope = {"authorization": "AWS4-HMAC-SHA256 Credential=AK/20260101/us-east-1/monitoring/aws4_request"}
    assert r.service_of("POST", "/", scope, b"Action=ListMetrics") == "cloudwatch"
    assert r.service_of("POST", "/", {"content-type": "application/x-www-form-urlencoded"}, b"Action=PutMetricAlarm") == "cloudwatch"


def test_metrics_alarm_lifecycle_over_cbor():
    r = AwsWireRouter()
    t = now()
    s, _, _ = cbor(r, "PutMetricData", Namespace="App", MetricData=[
        {"MetricName": "Lat", "Dimensions": [{"Name": "S", "Value": "a"}], "Value": 5.0, "Timestamp": cw.Ts(t)},
        {"MetricName": "Lat", "Dimensions": [{"Name": "S", "Value": "a"}], "Values": [1.0, 3.0], "Counts": [2.0, 1.0], "Timestamp": cw.Ts(t)}])
    assert s == 200
    s, b, h = cbor(r, "GetMetricStatistics", Namespace="App", MetricName="Lat", Dimensions=[{"Name": "S", "Value": "a"}],
                   StartTime=cw.Ts(t - 600), EndTime=cw.Ts(t + 60), Period=3600, Statistics=["Sum", "SampleCount", "Minimum", "Maximum", "Average"])
    d = b["Datapoints"][0]
    assert s == 200 and h["smithy-protocol"] == "rpc-v2-cbor"
    assert (d["Sum"], d["SampleCount"], d["Minimum"], d["Maximum"]) == (10.0, 4.0, 1.0, 5.0) and d["Average"] == 2.5
    cbor(r, "PutMetricAlarm", AlarmName="hi", Namespace="App", MetricName="Lat", Dimensions=[{"Name": "S", "Value": "a"}],
         Statistic="Maximum", Period=60, EvaluationPeriods=1, Threshold=50.0, ComparisonOperator="GreaterThanThreshold")
    assert cbor(r, "DescribeAlarms", AlarmNames=["hi"])[1]["MetricAlarms"][0]["StateValue"] == "OK"
    cbor(r, "PutMetricData", Namespace="App", MetricData=[{"MetricName": "Lat", "Dimensions": [{"Name": "S", "Value": "a"}], "Value": 99.0}])
    a = cbor(r, "DescribeAlarms", AlarmNames=["hi"])[1]["MetricAlarms"][0]
    assert a["StateValue"] == "ALARM" and "greater than the threshold" in a["StateReason"]
    hist = cbor(r, "DescribeAlarmHistory", AlarmName="hi")[1]["AlarmHistoryItems"]
    assert {h["HistoryItemType"] for h in hist} == {"ConfigurationUpdate", "StateUpdate"}


def test_errors_carry_wire_codes_on_each_protocol():
    r = AwsWireRouter()
    s, b, h = cbor(r, "GetDashboard", DashboardName="nope")
    assert s == 404 and b["__type"] == "com.amazonaws.cloudwatch#DashboardNotFoundError" and h["x-amzn-query-error"].startswith("ResourceNotFound;")
    out = r.handle("POST", "/", {}, {"x-amz-target": "GraniteServiceVersion20100801.SetAlarmState", "content-type": "application/x-amz-json-1.0"},
                   json.dumps({"AlarmName": "x", "StateValue": "OK", "StateReason": "r"}).encode())
    assert out["status"] == 404 and json.loads(out["body"])["__type"] == "ResourceNotFound"
    out = r.handle("POST", "/", {}, {"content-type": "application/x-www-form-urlencoded"}, b"Action=GetMetricStatistics&Namespace=A&MetricName=M")
    assert out["status"] == 400 and b"<Code>MissingParameter</Code>" in out["body"]


def test_query_protocol_unflattens_and_renders_xml():
    r = AwsWireRouter()
    body = ("Action=PutMetricData&Version=2010-08-01&Namespace=Q&MetricData.member.1.MetricName=M&MetricData.member.1.Value=7"
            "&MetricData.member.1.Dimensions.member.1.Name=D&MetricData.member.1.Dimensions.member.1.Value=v").encode()
    assert r.handle("POST", "/", {}, {"content-type": "application/x-www-form-urlencoded"}, body)["status"] == 200
    out = r.handle("POST", "/", {}, {"content-type": "application/x-www-form-urlencoded"}, b"Action=ListMetrics&Namespace=Q")
    assert b"<MetricName>M</MetricName>" in out["body"] and b"<Dimensions><member><Name>D</Name>" in out["body"]


def test_metric_math_composite_and_validation():
    st = cw.CloudWatchStore()
    t = now()
    cw.op_put_metric_data(st, {"Namespace": "N", "MetricData": [{"MetricName": "a", "Value": 6.0}, {"MetricName": "b", "Value": 3.0}]})
    q = [{"Id": "a1", "MetricStat": {"Metric": {"Namespace": "N", "MetricName": "a"}, "Period": 3600, "Stat": "Sum"}, "ReturnData": False},
         {"Id": "b1", "MetricStat": {"Metric": {"Namespace": "N", "MetricName": "b"}, "Period": 3600, "Stat": "Sum"}, "ReturnData": False},
         {"Id": "r", "Expression": "a1 / b1 * 100"}]
    res = cw.op_get_metric_data(st, {"MetricDataQueries": q, "StartTime": t - 600, "EndTime": t + 60})["MetricDataResults"]
    assert [x["Id"] for x in res] == ["r"] and res[0]["Values"] == [200.0]
    for bad in ({"Namespace": "AWS/EC2", "MetricData": [{"MetricName": "x", "Value": 1}]},
                {"Namespace": "N", "MetricData": [{"MetricName": "x", "Value": 1, "Timestamp": t - 30 * 86400}]},
                {"Namespace": "N", "MetricData": [{"MetricName": "x"}]}):
        try:
            cw.op_put_metric_data(st, bad)
            raise AssertionError("expected an error")
        except cw.CwError as e:
            assert e.status == 400
    cw.op_put_metric_alarm(st, {"AlarmName": "c1", "Namespace": "N", "MetricName": "a", "Statistic": "Sum", "Period": 60, "EvaluationPeriods": 1,
                                "Threshold": 1, "ComparisonOperator": "GreaterThanThreshold"})
    assert st.alarms["c1"]["StateValue"] == "ALARM"      # existing data (6 > 1) breaches on creation
    cw.op_put_composite_alarm(st, {"AlarmName": "comp", "AlarmRule": 'ALARM("c1") AND NOT OK("c1")'})
    assert st.composites["comp"]["StateValue"] == "ALARM"
    cw.op_set_alarm_state(st, {"AlarmName": "c1", "StateValue": "OK", "StateReason": "x"})
    assert st.composites["comp"]["StateValue"] == "OK"
    try:
        cw.op_delete_alarms(st, {"AlarmNames": ["c1"]})
        raise AssertionError("expected ResourceConflict")
    except cw.CwError as e:
        assert e.code == "ResourceConflict"


def test_state_survives_a_fresh_instance():
    backend = SqliteStateBackend(":memory:")
    a = PersistentCloudWatchStore(backend)
    cw.op_put_metric_data(a, {"Namespace": "P", "MetricData": [{"MetricName": "m", "Value": 1.0}]})
    cw.op_put_dashboard(a, {"DashboardName": "d", "DashboardBody": "{}"})
    b = PersistentCloudWatchStore(backend)
    assert len(b.metrics) == 1 and "d" in b.dashboards


def test_console_helpers_fill_every_column():
    st = cw.CloudWatchStore()
    r = cw.console_create(st, {})
    assert r["ok"] and r["state"] == "INSUFFICIENT_DATA" and r["details"] and r["history"] and r["action_list"]
    row = cw.console_list(st)["items"][0]
    assert all(str(row[k]).strip() not in ("", "-") for k in ("name", "state", "metric", "condition", "period", "actions", "updated"))
    assert cw.console_delete(st, "my-alarm")["ok"] and not cw.console_list(st)["items"]


def test_alarm_actions_really_deliver_to_sns_and_lambda():
    r = AwsWireRouter()
    # An SNS topic subscribed by an SQS queue, so delivery is externally observable.
    topic_xml = sns.dispatch(r.msg, {"Action": "CreateTopic", "Name": "cw-topic"}).body
    topic_arn = re.search(r"<TopicArn>([^<]+)</TopicArn>", topic_xml).group(1)
    qurl = sqs.dispatch(r.msg, "AmazonSQS.CreateQueue", {"QueueName": "cw-q"}).body["QueueUrl"]
    qarn = sqs.dispatch(r.msg, "AmazonSQS.GetQueueAttributes", {"QueueUrl": qurl}).body["Attributes"]["QueueArn"]
    sns.dispatch(r.msg, {"Action": "Subscribe", "TopicArn": topic_arn, "Protocol": "sqs", "Endpoint": qarn})
    # A real Lambda function.
    lam.dispatch(r.lam, "POST", "/2015-03-31/functions", {}, {}, json.dumps({
        "FunctionName": "cw-fn", "Code": {"Source": "def handler(event, context):\n    return event"},
    }).encode())
    fn_arn = "arn:aws:lambda:us-east-1:123456789012:function:cw-fn"

    cbor(r, "PutMetricAlarm", AlarmName="act1", Namespace="App", MetricName="Err", Statistic="Sum", Period=60,
         EvaluationPeriods=1, Threshold=1.0, ComparisonOperator="GreaterThanThreshold",
         AlarmActions=[topic_arn, fn_arn])
    cbor(r, "PutMetricData", Namespace="App", MetricData=[{"MetricName": "Err", "Value": 5.0}])

    hist = cbor(r, "DescribeAlarmHistory", AlarmName="act1")[1]["AlarmHistoryItems"]
    actions = [h for h in hist if h["HistoryItemType"] == "Action"]
    assert len(actions) == 2 and all("Successfully executed" in h["HistorySummary"] for h in actions)
    recv = sqs.dispatch(r.msg, "AmazonSQS.ReceiveMessage", {"QueueUrl": qurl, "MaxNumberOfMessages": 10}).body.get("Messages", [])
    assert len(recv) == 1 and "act1" in recv[0]["Body"]
    assert len(r.lam._lambda_functions["cw-fn"]["invocations"]) == 1

    # An EC2 action ARN whose alarm has no InstanceId dimension to act on (and an Auto
    # Scaling ARN, which has no backing core at all) are both honestly recorded as failed.
    cbor(r, "PutMetricAlarm", AlarmName="act2", Namespace="App", MetricName="Err", Statistic="Sum", Period=60,
         EvaluationPeriods=1, Threshold=1.0, ComparisonOperator="GreaterThanThreshold",
         AlarmActions=["arn:aws:automate:us-east-1:ec2:stop"])
    cbor(r, "PutMetricData", Namespace="App", MetricData=[{"MetricName": "Err", "Value": 5.0}])
    hist2 = [h for h in cbor(r, "DescribeAlarmHistory", AlarmName="act2")[1]["AlarmHistoryItems"] if h["HistoryItemType"] == "Action"]
    assert hist2 and "Failed to execute action" in hist2[0]["HistorySummary"]


def test_alarm_ec2_action_really_changes_instance_state():
    from core import vpc_core as vpc

    r = AwsWireRouter()
    run_body = vpc.dispatch(r.vpc, {"Action": "RunInstances", "InstanceType": "t3.micro", "MaxCount": "1"}).body
    iid = re.search(r"<instanceId>([^<]+)</instanceId>", run_body).group(1)

    cbor(r, "PutMetricAlarm", AlarmName="ec2act", Namespace="App", MetricName="Err",
         Dimensions=[{"Name": "InstanceId", "Value": iid}], Statistic="Sum", Period=60,
         EvaluationPeriods=1, Threshold=1.0, ComparisonOperator="GreaterThanThreshold",
         AlarmActions=[f"arn:aws:automate:{r.cw.region}:ec2:stop"])
    cbor(r, "PutMetricData", Namespace="App", MetricData=[{"MetricName": "Err", "Dimensions": [{"Name": "InstanceId", "Value": iid}], "Value": 5.0}])

    hist = [h for h in cbor(r, "DescribeAlarmHistory", AlarmName="ec2act")[1]["AlarmHistoryItems"] if h["HistoryItemType"] == "Action"]
    assert hist and "Successfully executed" in hist[0]["HistorySummary"]
    desc = vpc.dispatch(r.vpc, {"Action": "DescribeInstances", "InstanceId.1": iid}).body
    assert "<name>stopped</name>" in desc

    # Termination protection is honoured the same way a direct TerminateInstances call is.
    vpc.dispatch(r.vpc, {"Action": "StartInstances", "InstanceId.1": iid})
    vpc.dispatch(r.vpc, {"Action": "ModifyInstanceAttribute", "InstanceId": iid, "DisableApiTermination.Value": "true"})
    cbor(r, "PutMetricAlarm", AlarmName="ec2act2", Namespace="App", MetricName="Err",
         Dimensions=[{"Name": "InstanceId", "Value": iid}], Statistic="Sum", Period=60,
         EvaluationPeriods=1, Threshold=1.0, ComparisonOperator="GreaterThanThreshold",
         AlarmActions=[f"arn:aws:automate:{r.cw.region}:ec2:terminate"])
    cbor(r, "PutMetricData", Namespace="App", MetricData=[{"MetricName": "Err", "Dimensions": [{"Name": "InstanceId", "Value": iid}], "Value": 5.0}])
    hist2 = [h for h in cbor(r, "DescribeAlarmHistory", AlarmName="ec2act2")[1]["AlarmHistoryItems"] if h["HistoryItemType"] == "Action"]
    assert hist2 and "Failed to execute action" in hist2[0]["HistorySummary"]
    assert "<name>running</name>" in vpc.dispatch(r.vpc, {"Action": "DescribeInstances", "InstanceId.1": iid}).body


def _band_alarm(name, metric):
    return {
        "AlarmName": name, "ComparisonOperator": "LessThanLowerOrGreaterThanUpperThreshold",
        "EvaluationPeriods": 1, "ThresholdMetricId": "ad1",
        "Metrics": [
            {"Id": "m1", "MetricStat": {"Metric": {"Namespace": "App", "MetricName": metric}, "Period": 60, "Stat": "Average"}, "ReturnData": False},
            {"Id": "ad1", "Expression": "ANOMALY_DETECTION_BAND(m1, 2)", "ReturnData": True},
        ],
    }


def test_anomaly_detector_trains_and_band_alarm_evaluates():
    st = cw.CloudWatchStore()
    end0 = math.ceil((now() + 1e-3) / 60) * 60   # the 60s bucket boundary _evaluate_alarm will compute "now" as

    cw.op_put_anomaly_detector(st, {"Namespace": "App", "MetricName": "Lat", "Stat": "Average"})
    assert cw.op_describe_anomaly_detectors(st, {"Namespace": "App", "MetricName": "Lat"})["AnomalyDetectors"][0]["StateValue"] == "PENDING_TRAINING"

    cw.op_put_metric_alarm(st, _band_alarm("band_ok", "Lat"))
    assert st.alarms["band_ok"]["StateValue"] == "INSUFFICIENT_DATA"   # not enough history to train yet

    for k in range(2, 13):   # 11 steady historical datapoints, well before the current bucket
        cw.op_put_metric_data(st, {"Namespace": "App", "MetricData": [{"MetricName": "Lat", "Value": 10.0, "Timestamp": cw.Ts(end0 - 60 * k)}]})
    # The current-bucket datapoint is also steady, so it should land inside its own trained band.
    cw.op_put_metric_data(st, {"Namespace": "App", "MetricData": [{"MetricName": "Lat", "Value": 10.0, "Timestamp": cw.Ts(end0 - 30)}]})
    assert cw.op_describe_anomaly_detectors(st, {"Namespace": "App", "MetricName": "Lat"})["AnomalyDetectors"][0]["StateValue"] == "TRAINED"
    assert st.alarms["band_ok"]["StateValue"] == "OK"

    # A second, independently-trained metric whose only current-bucket point is a huge spike.
    cw.op_put_metric_alarm(st, _band_alarm("band_alarm", "LatSpike"))
    for k in range(2, 13):
        cw.op_put_metric_data(st, {"Namespace": "App", "MetricData": [{"MetricName": "LatSpike", "Value": 10.0, "Timestamp": cw.Ts(end0 - 60 * k)}]})
    cw.op_put_metric_data(st, {"Namespace": "App", "MetricData": [{"MetricName": "LatSpike", "Value": 10000.0, "Timestamp": cw.Ts(end0 - 30)}]})
    assert st.alarms["band_alarm"]["StateValue"] == "ALARM"
    assert "outside the expected band" in st.alarms["band_alarm"]["StateReason"]
