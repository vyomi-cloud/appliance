"""DynamoDB sweep A: maximum on-demand table throughput (OnDemandThroughput, enforced) and
WarmThroughput (stored + described, only ever raised).

Run: PYTHONPATH=. python3 tests/conformance/test_dynamodb_sweepa_core.py
"""
import json

try:
    from core.nosql_store import InMemoryNoSqlStore
    from core import dynamodb_core as d
except ImportError:  # pragma: no cover - Pyodide flat layout
    from nosql_store import InMemoryNoSqlStore  # type: ignore
    import dynamodb_core as d  # type: ignore

T = "DynamoDB_20120810."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _call(store, action, payload):
    r = d.dispatch(store, T + action, payload)
    body = r.body if isinstance(r.body, dict) else json.loads(r.body)
    return r.status, body


KEYS = {"KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}]}


def lambda_triggers():
    import types
    try:
        from core import lambda_core as lam
    except ImportError:  # pragma: no cover
        import lambda_core as lam  # type: ignore
    st = InMemoryNoSqlStore()
    st.lam_store = lam_store = types.SimpleNamespace()
    F, ESM = "/2015-03-31/functions", "/2015-03-31/event-source-mappings"

    def lc(method, path, body=None):
        return lam.dispatch(lam_store, method, path, {}, {}, json.dumps(body).encode() if body is not None else b"")

    _call(st, "CreateTable", {"TableName": "trg", "BillingMode": "PAY_PER_REQUEST",
                              "StreamSpecification": {"StreamEnabled": True, "StreamViewType": "NEW_AND_OLD_IMAGES"}, **KEYS})
    arn = _call(st, "DescribeTable", {"TableName": "trg"})[1]["Table"]["LatestStreamArn"]
    _check("function created", lc("POST", F, {"FunctionName": "trg-fn", "Runtime": "python3.12",
           "Code": {"Source": "def handler(event, context):\n    r = event['Records'][0]\n    return {'name': r['eventName'], 'src': r['eventSource']}\n"}}).status == 201)
    m = lc("POST", ESM, {"FunctionName": "trg-fn", "EventSourceArn": arn})
    _check("CreateEventSourceMapping on the stream ARN", m.status == 202 and json.loads(m.body)["EventSourceType"] == "DynamoDB")
    uid = json.loads(m.body)["UUID"]
    _call(st, "PutItem", {"TableName": "trg", "Item": {"id": {"S": "1"}}})
    inv = json.loads(lc("GET", f"{F}/trg-fn/invocations").body)["Invocations"]
    _check("PutItem invokes the function once", len(inv) == 1 and not inv[0]["Error"])
    _check("LastProcessingResult OK", json.loads(lc("GET", f"{ESM}/{uid}").body)["LastProcessingResult"] == "OK")
    _call(st, "DeleteItem", {"TableName": "trg", "Key": {"id": {"S": "1"}}})
    _check("DeleteItem invokes again (REMOVE)", len(json.loads(lc("GET", f"{F}/trg-fn/invocations").body)["Invocations"]) == 2)
    lc("PUT", f"{ESM}/{uid}", {"Enabled": False})
    _call(st, "PutItem", {"TableName": "trg", "Item": {"id": {"S": "2"}}})
    _check("disabled mapping does not invoke", len(json.loads(lc("GET", f"{F}/trg-fn/invocations").body)["Invocations"]) == 2)


def run() -> int:
    lambda_triggers()
    st = InMemoryNoSqlStore()
    s, b = _call(st, "CreateTable", {"TableName": "capped", "BillingMode": "PAY_PER_REQUEST",
                                     "OnDemandThroughput": {"MaxReadRequestUnits": 5, "MaxWriteRequestUnits": 1}, **KEYS})
    _check("CreateTable with OnDemandThroughput", s == 200)
    _, desc = _call(st, "DescribeTable", {"TableName": "capped"})
    _check("DescribeTable returns the OnDemandThroughput caps",
           desc["Table"]["OnDemandThroughput"] == {"MaxReadRequestUnits": 5, "MaxWriteRequestUnits": 1})
    _check("default WarmThroughput 12000/4000 ACTIVE",
           desc["Table"]["WarmThroughput"] == {"ReadUnitsPerSecond": 12000, "WriteUnitsPerSecond": 4000, "Status": "ACTIVE"})
    bucket = d._throughput_bucket(st, ("capped", None, "odw"), 1)
    bucket.tokens = 0.0
    s, b = _call(st, "PutItem", {"TableName": "capped", "Item": {"id": {"S": "x"}}})
    _check("write beyond the max table throughput is throttled", s == 400 and b.get("__type") == "ThrottlingException")
    rb = d._throughput_bucket(st, ("capped", None, "odr"), 5)
    rb.tokens = 0.0
    s, b = _call(st, "GetItem", {"TableName": "capped", "Key": {"id": {"S": "x"}}})
    _check("read beyond the max table throughput is throttled", s == 400 and b.get("__type") == "ThrottlingException")
    s, _ = _call(st, "UpdateTable", {"TableName": "capped", "OnDemandThroughput": {"MaxReadRequestUnits": -1, "MaxWriteRequestUnits": -1}})
    _check("UpdateTable removes the caps", s == 200)
    s, _ = _call(st, "PutItem", {"TableName": "capped", "Item": {"id": {"S": "x"}}})
    _check("uncapped table accepts the write again", s == 200)

    s, b = _call(st, "CreateTable", {"TableName": "prov", "BillingMode": "PROVISIONED",
                                     "ProvisionedThroughput": {"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
                                     "OnDemandThroughput": {"MaxReadRequestUnits": 5, "MaxWriteRequestUnits": 5}, **KEYS})
    _check("OnDemandThroughput on a PROVISIONED table is a ValidationException", s == 400 and b.get("__type") == "ValidationException")
    s, b = _call(st, "CreateTable", {"TableName": "badcap", "BillingMode": "PAY_PER_REQUEST",
                                     "OnDemandThroughput": {"MaxReadRequestUnits": -7}, **KEYS})
    _check("invalid cap rejected", s == 400)

    s, _ = _call(st, "CreateTable", {"TableName": "warm", "BillingMode": "PAY_PER_REQUEST",
                                     "WarmThroughput": {"ReadUnitsPerSecond": 20000, "WriteUnitsPerSecond": 100}, **KEYS})
    _, desc = _call(st, "DescribeTable", {"TableName": "warm"})
    _check("requested WarmThroughput raises the read level, never below the default write level",
           desc["Table"]["WarmThroughput"]["ReadUnitsPerSecond"] == 20000 and desc["Table"]["WarmThroughput"]["WriteUnitsPerSecond"] == 4000)
    _call(st, "UpdateTable", {"TableName": "warm", "WarmThroughput": {"WriteUnitsPerSecond": 9000}})
    _, desc = _call(st, "DescribeTable", {"TableName": "warm"})
    _check("UpdateTable raises WarmThroughput", desc["Table"]["WarmThroughput"]["WriteUnitsPerSecond"] == 9000)
    print("\nRESULT: PASS - DynamoDB sweep A")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
