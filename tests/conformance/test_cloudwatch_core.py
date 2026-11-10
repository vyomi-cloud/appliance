"""CloudWatch core — CBOR / JSON / Query wire on the shared router, alarms, metric math, persistence."""
import json
import time

from core import cloudwatch_core as cw
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
