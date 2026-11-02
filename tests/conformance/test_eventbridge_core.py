"""EventBridge event-bus conformance (v2.6.0, PARITY P4 #15) — host + Pyodide.

Rules with event patterns + SQS targets; PutEvents matches each event against every
rule and delivers matching events to the rule's target queues (EventBridge→SQS).
"""
import json

try:
    from core.messaging_store import InMemoryMessagingStore
    from core import sqs_core as sqs, eventbridge_core as eb
except ImportError:  # pragma: no cover - Pyodide flat layout
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import sqs_core as sqs  # type: ignore
    import eventbridge_core as eb  # type: ignore

E = "AWSEvents."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or InMemoryMessagingStore()

    from core import cloudwatch_core as cwc
    cws = cwc.CloudWatchStore(); s.cw_store = cws   # eventbridge.metrics runtime link

    def call(a, b):
        return eb.dispatch(s, E + a, b)

    qurl = sqs.dispatch(s, "AmazonSQS.CreateQueue", {"QueueName": "events-q"}).body["QueueUrl"]
    qarn = sqs.dispatch(s, "AmazonSQS.GetQueueAttributes", {"QueueUrl": qurl}).body["Attributes"]["QueueArn"]

    call("PutRule", {"Name": "r1", "EventPattern": json.dumps({"source": ["my.app"], "detail": {"state": ["running"]}})})
    call("PutTargets", {"Rule": "r1", "Targets": [{"Id": "t1", "Arn": qarn}]})

    def drain():
        r = sqs.dispatch(s, "AmazonSQS.ReceiveMessage", {"QueueUrl": qurl, "MaxNumberOfMessages": 10}).body
        for m in r.get("Messages", []):
            sqs.dispatch(s, "AmazonSQS.DeleteMessage", {"QueueUrl": qurl, "ReceiptHandle": m["ReceiptHandle"]})
        return len(r.get("Messages", []))

    call("PutEvents", {"Entries": [{"Source": "my.app", "DetailType": "x", "Detail": json.dumps({"state": "running"})}]})
    _check("matching event → delivered to SQS target", drain() == 1)
    call("PutEvents", {"Entries": [{"Source": "my.app", "DetailType": "x", "Detail": json.dumps({"state": "stopped"})}]})
    _check("detail mismatch → not delivered", drain() == 0)
    call("PutEvents", {"Entries": [{"Source": "other.app", "Detail": json.dumps({"state": "running"})}]})
    _check("source mismatch → not delivered", drain() == 0)

    _check("ListRules", call("ListRules", {}).body["Rules"][0]["Name"] == "r1")
    _check("ListTargetsByRule", call("ListTargetsByRule", {"Rule": "r1"}).body["Targets"][0]["Id"] == "t1")

    # eventbridge.metrics: AWS/Events datapoints derived from the real matching above
    def _sum(metric, dims):
        ser = cwc._series(cws, "AWS/Events", metric, dims)
        return sum(p[1] for p in ser["points"]) if ser else None
    rd = [{"Name": "RuleName", "Value": "r1"}]
    _check("TriggeredRules counts only matching events (1 match, 2 misses)", _sum("TriggeredRules", rd) == 1.0)
    _check("Invocations = deliveries attempted", _sum("Invocations", rd) == 1.0)
    _check("account-level Invocations (no dimensions)", _sum("Invocations", []) == 1.0)
    _check("no FailedInvocations for a good target", _sum("FailedInvocations", rd) is None)
    call("PutTargets", {"Rule": "r1", "Targets": [{"Id": "t2", "Arn": "arn:aws:lambda:us-east-1:123456789012:function:nope"}]})
    call("PutEvents", {"Entries": [{"Source": "my.app", "DetailType": "x", "Detail": json.dumps({"state": "running"})}]})
    _check("undeliverable target → FailedInvocations", _sum("FailedInvocations", rd) == 1.0)

    print("\nEventBridge event-bus conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
