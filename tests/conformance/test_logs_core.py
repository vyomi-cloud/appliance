"""CloudWatch Logs conformance — host + Pyodide.

Log groups/streams, PutLogEvents/GetLogEvents/FilterLogEvents, retention, tags,
metric + subscription filters, resource policies and Logs Insights queries,
against the native `Logs_20140328.*` JSON protocol with botocore error codes.
"""
import base64
import gzip
import json

try:
    from core import logs_core as lg
    from core import lambda_core as lam
    from core import kinesis_core as kin
except ImportError:  # pragma: no cover - Pyodide flat layout
    import logs_core as lg  # type: ignore
    import lambda_core as lam  # type: ignore
    import kinesis_core as kin  # type: ignore

T = "Logs_20140328."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or lg.LogsStore()

    def call(a, b=None):
        return lg.dispatch(s, T + a, b or {})

    def err(a, b, code):
        r = call(a, b)
        return r.status == 400 and r.body.get("__type") == code

    _check("create group", call("CreateLogGroup", {"logGroupName": "/app/web", "tags": {"env": "dev"}}).status == 200)
    _check("duplicate group", err("CreateLogGroup", {"logGroupName": "/app/web"}, "ResourceAlreadyExistsException"))
    _check("bad group name", err("CreateLogGroup", {"logGroupName": "bad name!"}, "InvalidParameterException"))
    g = call("DescribeLogGroups", {"logGroupNamePrefix": "/app"}).body["logGroups"]
    _check("describe groups", len(g) == 1 and g[0]["arn"].endswith("log-group:/app/web:*") and g[0]["storedBytes"] == 0)
    _check("retention", call("PutRetentionPolicy", {"logGroupName": "/app/web", "retentionInDays": 7}).status == 200
           and call("DescribeLogGroups", {}).body["logGroups"][0]["retentionInDays"] == 7)
    _check("bad retention", err("PutRetentionPolicy", {"logGroupName": "/app/web", "retentionInDays": 8}, "InvalidParameterException"))
    _check("delete retention", call("DeleteRetentionPolicy", {"logGroupName": "/app/web"}).status == 200
           and "retentionInDays" not in call("DescribeLogGroups", {}).body["logGroups"][0])

    _check("create stream", call("CreateLogStream", {"logGroupName": "/app/web", "logStreamName": "i-1"}).status == 200)
    _check("stream in missing group", err("CreateLogStream", {"logGroupName": "/nope", "logStreamName": "x"}, "ResourceNotFoundException"))
    now = s.now_ms()
    ev = [{"timestamp": now + i, "message": m} for i, m in enumerate(["GET /a 200", "GET /b 500 ERROR", "POST /c 200"])]
    r = call("PutLogEvents", {"logGroupName": "/app/web", "logStreamName": "i-1", "logEvents": ev})
    _check("put events", r.status == 200 and r.body["nextSequenceToken"])
    old = call("PutLogEvents", {"logGroupName": "/app/web", "logStreamName": "i-1",
                                "logEvents": [{"timestamp": now - 30 * 86400000, "message": "old"}]}).body
    _check("too-old event rejected", old["rejectedLogEventsInfo"]["tooOldLogEventEndIndex"] == 1)
    ge = call("GetLogEvents", {"logGroupName": "/app/web", "logStreamName": "i-1", "startFromHead": True}).body
    _check("get events in order", [e["message"] for e in ge["events"]] == [e["message"] for e in ev])
    pg = call("GetLogEvents", {"logGroupName": "/app/web", "logStreamName": "i-1", "startFromHead": True, "limit": 2}).body
    nx = call("GetLogEvents", {"logGroupName": "/app/web", "logStreamName": "i-1", "nextToken": pg["nextForwardToken"], "limit": 2}).body
    _check("forward paging", len(pg["events"]) == 2 and len(nx["events"]) == 1)
    st = call("DescribeLogStreams", {"logGroupName": "/app/web"}).body["logStreams"][0]
    _check("stream stats", st["storedBytes"] > 0 and st["lastEventTimestamp"] >= st["firstEventTimestamp"] > 0)
    fe = call("FilterLogEvents", {"logGroupName": "/app/web", "filterPattern": "ERROR"}).body["events"]
    _check("filter term", len(fe) == 1 and fe[0]["logStreamName"] == "i-1")
    _check("filter exclusion", len(call("FilterLogEvents", {"logGroupName": "/app/web", "filterPattern": "GET -ERROR"}).body["events"]) == 1)
    _check("filter any-of", len(call("FilterLogEvents", {"logGroupName": "/app/web", "filterPattern": "?POST ?ERROR"}).body["events"]) == 2)
    call("CreateLogStream", {"logGroupName": "/app/web", "logStreamName": "j"})
    call("PutLogEvents", {"logGroupName": "/app/web", "logStreamName": "j",
                          "logEvents": [{"timestamp": now, "message": json.dumps({"level": "error", "ms": 900})}]})
    _check("json filter", len(call("FilterLogEvents", {"logGroupName": "/app/web", "filterPattern": '{ $.level = "error" && $.ms > 500 }'}).body["events"]) == 1)

    _check("tag/list tags", call("TagLogGroup", {"logGroupName": "/app/web", "tags": {"team": "x"}}).status == 200
           and call("ListTagsLogGroup", {"logGroupName": "/app/web"}).body["tags"] == {"env": "dev", "team": "x"})
    arn = g[0]["logGroupArn"]
    call("UntagResource", {"resourceArn": arn, "tagKeys": ["env"]})
    _check("arn tags", call("ListTagsForResource", {"resourceArn": arn}).body["tags"] == {"team": "x"})

    mt = [{"metricName": "Errors", "metricNamespace": "App", "metricValue": "1"}]
    _check("metric filter", call("PutMetricFilter", {"logGroupName": "/app/web", "filterName": "errs", "filterPattern": "ERROR", "metricTransformations": mt}).status == 200
           and call("DescribeMetricFilters", {"logGroupName": "/app/web"}).body["metricFilters"][0]["filterName"] == "errs")
    _check("test metric filter", len(call("TestMetricFilter", {"filterPattern": "ERROR", "logEventMessages": ["a", "ERROR b"]}).body["matches"]) == 1)
    _check("delete metric filter", call("DeleteMetricFilter", {"logGroupName": "/app/web", "filterName": "errs"}).status == 200
           and err("DeleteMetricFilter", {"logGroupName": "/app/web", "filterName": "errs"}, "ResourceNotFoundException"))
    _check("subscription filter", call("PutSubscriptionFilter", {"logGroupName": "/app/web", "filterName": "sf", "filterPattern": "", "destinationArn": "arn:aws:lambda:us-east-1:123456789012:function:f"}).status == 200
           and len(call("DescribeSubscriptionFilters", {"logGroupName": "/app/web"}).body["subscriptionFilters"]) == 1)
    _check("delete subscription filter", call("DeleteSubscriptionFilter", {"logGroupName": "/app/web", "filterName": "sf"}).status == 200)

    pol = json.dumps({"Version": "2012-10-17", "Statement": []})
    _check("resource policy", call("PutResourcePolicy", {"policyName": "p", "policyDocument": pol}).status == 200
           and call("DescribeResourcePolicies", {}).body["resourcePolicies"][0]["policyName"] == "p"
           and call("DeleteResourcePolicy", {"policyName": "p"}).status == 200)

    qd = call("PutQueryDefinition", {"name": "errs", "queryString": "fields @message", "logGroupNames": ["/app/web"]}).body["queryDefinitionId"]
    _check("query definition", call("DescribeQueryDefinitions", {}).body["queryDefinitions"][0]["queryDefinitionId"] == qd
           and call("DeleteQueryDefinition", {"queryDefinitionId": qd}).body["success"])
    qid = call("StartQuery", {"logGroupName": "/app/web", "startTime": now // 1000 - 60, "endTime": now // 1000 + 60,
                              "queryString": "fields @message | filter @message like /ERROR/ | limit 5"}).body["queryId"]
    qr = call("GetQueryResults", {"queryId": qid}).body
    _check("insights query", qr["status"] == "Complete" and len(qr["results"]) == 1 and qr["results"][0][0]["field"] == "@message")
    qc = call("StartQuery", {"logGroupName": "/app/web", "startTime": now // 1000 - 60, "endTime": now // 1000 + 60, "queryString": "stats count(*) as n"}).body["queryId"]
    _check("insights stats", call("GetQueryResults", {"queryId": qc}).body["results"][0][0] == {"field": "n", "value": "4"})

    qp = call("StartQuery", {"logGroupName": "/app/web", "startTime": now // 1000 - 60, "endTime": now // 1000 + 60, "queryString": "pattern @message"}).body["queryId"]
    pr = [dict((c["field"], c["value"]) for c in row) for row in call("GetQueryResults", {"queryId": qp}).body["results"]]
    _check("pattern mining masks numbers into distinct templates", len(pr) == 4 and sum(int(r["@sampleCount"]) for r in pr) == 4
           and all("<*>" in r["@pattern"] for r in pr))
    _check("pattern severity flags error lines", {r["@severityLabel"] for r in pr if "ERROR" in r["@pattern"] or "error" in r["@pattern"]} == {"ERROR"})

    qb = call("StartQuery", {"logGroupName": "/app/web", "startTime": now // 1000 - 60, "endTime": now // 1000 + 60, "queryString": "stats count(*) by bin(60s)"}).body["queryId"]
    br = [dict((c["field"], c["value"]) for c in row) for row in call("GetQueryResults", {"queryId": qb}).body["results"]]
    _check("bin() buckets by time", len(br) == 1 and br[0]["count(*)"] == "4" and br[0]["bin(60s)"])

    _check("no data protection policy yet", err("GetDataProtectionPolicy", {"logGroupName": "/app/web"}, "ResourceNotFoundException"))
    identifiers = ["EmailAddress", "AwsAccessKey", "PhoneNumber-US", "IpAddress", "Url"]
    arns = [f"arn:aws:dataprotection::aws:data-identifier/{i}" for i in identifiers]
    policy = json.dumps({"Name": "p", "Version": "2021-06-01", "Statement": [
        {"Sid": "audit", "DataIdentifier": arns, "Operation": {"Audit": {"FindingsDestination": {}}}},
        {"Sid": "redact", "DataIdentifier": arns, "Operation": {"Deidentify": {"MaskConfig": {}}}},
    ]})
    _check("put data protection policy", call("PutDataProtectionPolicy", {"logGroupIdentifier": "/app/web", "policyDocument": policy}).status == 200
           and call("GetDataProtectionPolicy", {"logGroupName": "/app/web"}).body["policyDocument"] == policy)
    call("CreateLogStream", {"logGroupName": "/app/web", "logStreamName": "k"})
    call("PutLogEvents", {"logGroupName": "/app/web", "logStreamName": "k",
                          "logEvents": [{"timestamp": now, "message": "contact alice@example.com for access"}]})
    masked = call("GetLogEvents", {"logGroupName": "/app/web", "logStreamName": "k"}).body["events"][0]["message"]
    _check("email masked at ingestion", masked == "contact ***************** for access")
    call("PutLogEvents", {"logGroupName": "/app/web", "logStreamName": "k",
                          "logEvents": [{"timestamp": now, "message": "key AKIAABCDEFGHIJKLMNOP call 555-867-5309 from 10.0.0.1 see https://example.com/x"}]})
    masked2 = call("GetLogEvents", {"logGroupName": "/app/web", "logStreamName": "k"}).body["events"][1]["message"]
    _check("AWS access key masked", "AKIA" not in masked2 and "*" * 20 in masked2)
    _check("US phone number masked", "555-867-5309" not in masked2)
    _check("IP address masked", "10.0.0.1" not in masked2)
    _check("URL masked", "https://example.com/x" not in masked2)
    _check("findings counted on the log group", call("DescribeLogGroups", {"logGroupNamePrefix": "/app/web"}).body["logGroups"][0]["dataProtectionFindings"] == 5)
    _check("delete data protection policy", call("DeleteDataProtectionPolicy", {"logGroupName": "/app/web"}).status == 200
           and err("GetDataProtectionPolicy", {"logGroupName": "/app/web"}, "ResourceNotFoundException"))
    call("DeleteLogStream", {"logGroupName": "/app/web", "logStreamName": "k"})

    _check("no field index policy yet", err("GetIndexPolicy", {"logGroupName": "/app/web"}, "ResourceNotFoundException"))
    idx_doc = json.dumps({"fields": ["requestId", "statusCode"]})
    _check("put index policy", call("PutIndexPolicy", {"logGroupIdentifier": "/app/web", "policyDocument": idx_doc}).status == 200)
    _check("get index policy", call("GetIndexPolicy", {"logGroupName": "/app/web"}).body["indexPolicyDocument"]["policyDocument"] == idx_doc)
    _check("bad field name rejected", err("PutIndexPolicy", {"logGroupIdentifier": "/app/web", "policyDocument": json.dumps({"fields": ["bad field!"]})}, "InvalidParameterException"))
    _check("describe index policies", call("DescribeIndexPolicies", {"logGroupIdentifiers": ["/app/web", "/does/not/exist"]}).body["indexPolicies"][0]["policyDocument"] == idx_doc)
    _check("delete index policy", call("DeleteIndexPolicy", {"logGroupName": "/app/web"}).status == 200
           and err("GetIndexPolicy", {"logGroupName": "/app/web"}, "ResourceNotFoundException"))

    _check("no transformer yet", err("GetTransformer", {"logGroupName": "/app/web"}, "ResourceNotFoundException"))
    _check("bad processor rejected", err("PutTransformer", {"logGroupIdentifier": "/app/web", "transformerConfig": [{"grok": {}}]}, "InvalidParameterException"))
    tcfg = [{"parseJSON": {"source": "@message"}}, {"addKeys": {"entries": [{"key": "env", "value": "prod"}]}}, {"deleteKeys": {"withKeys": ["ms"]}}, {"renameKeys": {"entries": [{"key": "level", "renameTo": "severity"}]}}]
    _check("put transformer", call("PutTransformer", {"logGroupIdentifier": "/app/web", "transformerConfig": tcfg}).status == 200
           and call("GetTransformer", {"logGroupName": "/app/web"}).body["transformerConfig"] == tcfg)
    call("CreateLogStream", {"logGroupName": "/app/web", "logStreamName": "t"})
    call("PutLogEvents", {"logGroupName": "/app/web", "logStreamName": "t",
                          "logEvents": [{"timestamp": now, "message": json.dumps({"level": "error", "ms": 900})}]})
    transformed = json.loads(call("GetLogEvents", {"logGroupName": "/app/web", "logStreamName": "t"}).body["events"][0]["message"])
    _check("transformer parses, adds, deletes and renames keys", transformed == {"severity": "error", "env": "prod"})
    _check("delete transformer", call("DeleteTransformer", {"logGroupName": "/app/web"}).status == 200
           and err("GetTransformer", {"logGroupName": "/app/web"}, "ResourceNotFoundException"))
    call("DeleteLogStream", {"logGroupName": "/app/web", "logStreamName": "t"})

    _check("deletion protection create", call("CreateLogGroup", {"logGroupName": "/app/protected", "deletionProtectionEnabled": True}).status == 200
           and call("DescribeLogGroups", {"logGroupNamePrefix": "/app/protected"}).body["logGroups"][0]["deletionProtectionEnabled"] is True)
    _check("deletion protection blocks delete", err("DeleteLogGroup", {"logGroupName": "/app/protected"}, "OperationAbortedException"))
    _check("deletion protection can be turned off", call("UpdateLogGroupDeletionProtection", {"logGroupName": "/app/protected", "deletionProtectionEnabled": False}).status == 200
           and call("DeleteLogGroup", {"logGroupName": "/app/protected"}).status == 200)

    _check("delete stream", call("DeleteLogStream", {"logGroupName": "/app/web", "logStreamName": "j"}).status == 200)
    _check("delete group", call("DeleteLogGroup", {"logGroupName": "/app/web"}).status == 200
           and err("DeleteLogGroup", {"logGroupName": "/app/web"}, "ResourceNotFoundException"))
    _check("unknown op", call("Bogus").body["__type"] == "UnknownOperationException")
    return s


def test_logs_core():
    run()


def test_subscription_filter_really_delivers_to_lambda_and_kinesis():
    import types
    s = lg.LogsStore()
    s.lam_store = types.SimpleNamespace()
    s.kinesis_store = kin.KinesisStore()

    lam.dispatch(s.lam_store, "POST", "/2015-03-31/functions", {}, {}, json.dumps({
        "FunctionName": "sub-fn", "Code": {"Source": "def handler(event, context):\n    return event"},
    }).encode())
    fn_arn = "arn:aws:lambda:us-east-1:123456789012:function:sub-fn"
    kin.create_stream(s.kinesis_store, {"StreamName": "sub-stream", "ShardCount": 1})
    stream_arn = kin.describe_stream_summary(s.kinesis_store, {"StreamName": "sub-stream"})["StreamDescriptionSummary"]["StreamARN"]

    def call(a, b=None):
        return lg.dispatch(s, T + a, b or {})

    call("CreateLogGroup", {"logGroupName": "/sub"})
    call("CreateLogStream", {"logGroupName": "/sub", "logStreamName": "i-1"})
    call("PutSubscriptionFilter", {"logGroupName": "/sub", "filterName": "to-lambda", "filterPattern": "", "destinationArn": fn_arn})
    call("PutSubscriptionFilter", {"logGroupName": "/sub", "filterName": "to-kinesis", "filterPattern": "", "destinationArn": stream_arn})
    now = s.now_ms()
    call("PutLogEvents", {"logGroupName": "/sub", "logStreamName": "i-1", "logEvents": [{"timestamp": now, "message": "hello"}]})

    assert len(s.lam_store._lambda_functions["sub-fn"]["invocations"]) == 1
    fs = call("DescribeSubscriptionFilters", {"logGroupName": "/sub"}).body["subscriptionFilters"]
    assert all(f["filterName"] for f in fs)   # deliveredEvents is excluded from the wire shape, but delivery itself must have worked:

    shard_id = kin.list_shards(s.kinesis_store, {"StreamName": "sub-stream"})["Shards"][0]["ShardId"]
    it = kin.get_shard_iterator(s.kinesis_store, {"StreamName": "sub-stream", "ShardId": shard_id, "ShardIteratorType": "TRIM_HORIZON"})["ShardIterator"]
    recs = kin.get_records(s.kinesis_store, {"ShardIterator": it})["Records"]
    assert len(recs) == 1
    doc = json.loads(gzip.decompress(base64.b64decode(recs[0]["Data"])))
    assert doc["logEvents"][0]["message"] == "hello" and doc["logGroup"] == "/sub"


if __name__ == "__main__":
    run()
    test_subscription_filter_really_delivers_to_lambda_and_kinesis()
    print("  ok  subscription filter really delivers to lambda and kinesis")
