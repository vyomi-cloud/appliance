"""DynamoDB CloudWatch metrics/alarms conformance (v4 wave 5b gap sweep) — host + Pyodide.

Vyomi has no background metrics pipeline, but every DynamoDB operation now
pushes a REAL AWS/DynamoDB datapoint (derived from the actual request, never
synthetic) into the shared CloudWatch core — the same engine core/vpc_core.py's
EC2 status-check metrics use (ingest_internal_metric). Proves: ConsumedRead/
WriteCapacityUnits move with real traffic (both the TableName-only series and
the TableName+Operation series), and a PutMetricAlarm set on that series fires
for real through CloudWatch's own alarm evaluator.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_dynamodb_monitor_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core.nosql_store import InMemoryNoSqlStore
    from core import dynamodb_core as d
    from core import cloudwatch_core as cw
except ImportError:  # pragma: no cover - Pyodide flat layout
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    import dynamodb_core as d  # type: ignore
    import cloudwatch_core as cw  # type: ignore

P = "DynamoDB_20120810."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None, cw_store=None):
    s = store or InMemoryNoSqlStore()
    cws = cw_store if cw_store is not None else cw.CloudWatchStore()
    s.cw_store = cws

    def call(a, p):
        r = d.dispatch(s, P + a, p)
        return r.status, (r.body if isinstance(r.body, dict) else json.loads(r.body))

    call("CreateTable", {"TableName": "monitored", "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                         "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
                         "BillingMode": "PAY_PER_REQUEST"})

    for i in range(3):
        call("PutItem", {"TableName": "monitored", "Item": {"id": {"S": str(i)}}})
    call("GetItem", {"TableName": "monitored", "Key": {"id": {"S": "0"}}})
    call("Scan", {"TableName": "monitored"})

    import time
    now = time.time()
    stats = cw.op_get_metric_statistics(cws, {
        "Namespace": "AWS/DynamoDB", "MetricName": "ConsumedWriteCapacityUnits",
        "Dimensions": [{"Name": "TableName", "Value": "monitored"}],
        "StartTime": now - 300, "EndTime": now + 1, "Period": 300, "Statistics": ["Sum"],
    })
    total_write = sum(dp["Sum"] or 0 for dp in stats["Datapoints"])
    _check("3 PutItem calls consumed 3 real write units", total_write == 3.0)

    read_stats = cw.op_get_metric_statistics(cws, {
        "Namespace": "AWS/DynamoDB", "MetricName": "ConsumedReadCapacityUnits",
        "Dimensions": [{"Name": "TableName", "Value": "monitored"}],
        "StartTime": now - 300, "EndTime": now + 1, "Period": 300, "Statistics": ["Sum"],
    })
    total_read = sum(dp["Sum"] or 0 for dp in read_stats["Datapoints"])
    _check("GetItem + Scan consumed real read units", total_read >= 2.0)

    op_stats = cw.op_get_metric_statistics(cws, {
        "Namespace": "AWS/DynamoDB", "MetricName": "ConsumedWriteCapacityUnits",
        "Dimensions": [{"Name": "TableName", "Value": "monitored"}, {"Name": "Operation", "Value": "PutItem"}],
        "StartTime": now - 300, "EndTime": now + 1, "Period": 300, "Statistics": ["Sum"],
    })
    _check("per-Operation dimension series also populated", sum(dp["Sum"] or 0 for dp in op_stats["Datapoints"]) == 3.0)

    metrics = cw.op_list_metrics(cws, {"Namespace": "AWS/DynamoDB"})
    _check("ListMetrics surfaces the table's metrics", any(
        m["MetricName"] == "ConsumedWriteCapacityUnits" and
        {dd["Name"]: dd["Value"] for dd in m["Dimensions"]}.get("TableName") == "monitored"
        for m in metrics["Metrics"]))

    # A real alarm set on this series fires for real traffic crossing the threshold.
    cw.op_put_metric_alarm(cws, {
        "AlarmName": "monitored-writes", "Namespace": "AWS/DynamoDB", "MetricName": "ConsumedWriteCapacityUnits",
        "Dimensions": [{"Name": "TableName", "Value": "monitored"}], "Statistic": "Sum", "Period": 60,
        "EvaluationPeriods": 1, "DatapointsToAlarm": 1, "Threshold": 1, "ComparisonOperator": "GreaterThanOrEqualToThreshold",
    })
    for i in range(3, 6):
        call("PutItem", {"TableName": "monitored", "Item": {"id": {"S": str(i)}}})
    rec = cws.alarms["monitored-writes"]
    _check("alarm transitions out of INSUFFICIENT_DATA on real traffic", rec["StateValue"] != "INSUFFICIENT_DATA")
    _check("alarm is actually in ALARM (3 more writes >= threshold 1)", rec["StateValue"] == "ALARM")

    print("\nDynamoDB CloudWatch metrics/alarms conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
