"""CloudWatch Logs conformance — host + Pyodide.

Log groups/streams, PutLogEvents/GetLogEvents/FilterLogEvents, retention, tags,
metric + subscription filters, resource policies and Logs Insights queries,
against the native `Logs_20140328.*` JSON protocol with botocore error codes.
"""
import json

try:
    from core import logs_core as lg
except ImportError:  # pragma: no cover - Pyodide flat layout
    import logs_core as lg  # type: ignore

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

    _check("delete stream", call("DeleteLogStream", {"logGroupName": "/app/web", "logStreamName": "j"}).status == 200)
    _check("delete group", call("DeleteLogGroup", {"logGroupName": "/app/web"}).status == 200
           and err("DeleteLogGroup", {"logGroupName": "/app/web"}, "ResourceNotFoundException"))
    _check("unknown op", call("Bogus").body["__type"] == "UnknownOperationException")
    return s


def test_logs_core():
    run()


if __name__ == "__main__":
    run()
