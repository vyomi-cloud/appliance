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

    # SNS target: event published to the topic fans out to an SQS subscription.
    try:
        from core import sns_core as sns
    except ImportError:  # pragma: no cover
        import sns_core as sns  # type: ignore
    qurl2 = sqs.dispatch(s, "AmazonSQS.CreateQueue", {"QueueName": "sns-sub-q"}).body["QueueUrl"]
    qarn2 = sqs.dispatch(s, "AmazonSQS.GetQueueAttributes", {"QueueUrl": qurl2}).body["Attributes"]["QueueArn"]
    sns.dispatch(s, {"Action": "CreateTopic", "Name": "ev-topic"})
    tarn = sns._topic_arn(s, "ev-topic")
    sns.dispatch(s, {"Action": "Subscribe", "TopicArn": tarn, "Protocol": "sqs", "Endpoint": qarn2})
    call("PutRule", {"Name": "r2", "EventPattern": json.dumps({"source": ["sns.app"]})})
    call("PutTargets", {"Rule": "r2", "Targets": [{"Id": "t2", "Arn": tarn}]})
    call("PutEvents", {"Entries": [{"Source": "sns.app", "DetailType": "x", "Detail": "{}"}]})
    got = sqs.dispatch(s, "AmazonSQS.ReceiveMessage", {"QueueUrl": qurl2, "MaxNumberOfMessages": 10}).body
    _check("matching event → delivered to SNS target → SQS subscriber", len(got.get("Messages", [])) == 1)

    # Target input shaping: InputTransformer, InputPath, constant Input.
    def recv():
        m = sqs.dispatch(s, "AmazonSQS.ReceiveMessage", {"QueueUrl": qurl, "MaxNumberOfMessages": 10}).body["Messages"]
        for x in m:
            sqs.dispatch(s, "AmazonSQS.DeleteMessage", {"QueueUrl": qurl, "ReceiptHandle": x["ReceiptHandle"]})
        return json.loads(m[0]["Body"])

    call("PutRule", {"Name": "r3", "EventPattern": json.dumps({"source": ["shape.app"]})})
    call("PutTargets", {"Rule": "r3", "Targets": [
        {"Id": "tt", "Arn": qarn, "InputTransformer": {
            "InputPathsMap": {"st": "$.detail.state", "src": "$.source"},
            "InputTemplate": '{"s":"<st>","from":"<src>"}'}}]})
    _check("PutTargets keeps InputTransformer",
           "InputTransformer" in call("ListTargetsByRule", {"Rule": "r3"}).body["Targets"][0])
    call("PutEvents", {"Entries": [{"Source": "shape.app", "DetailType": "x", "Detail": json.dumps({"state": "up"})}]})
    _check("InputTransformer applied", recv() == {"s": "up", "from": "shape.app"})
    call("PutTargets", {"Rule": "r3", "Targets": [{"Id": "tt", "Arn": qarn, "InputPath": "$.detail"}]})
    call("PutEvents", {"Entries": [{"Source": "shape.app", "DetailType": "x", "Detail": json.dumps({"state": "up"})}]})
    _check("InputPath applied", recv() == {"state": "up"})
    call("PutTargets", {"Rule": "r3", "Targets": [{"Id": "tt", "Arn": qarn, "Input": '{"fixed":1}'}]})
    call("PutEvents", {"Entries": [{"Source": "shape.app", "DetailType": "x", "Detail": "{}"}]})
    _check("constant Input applied", recv() == {"fixed": 1})

    # Pattern language: numeric, anything-but, prefix, suffix, exists, array value, $or.
    P = eb._match_pattern
    ev = {"source": "a.b", "detail": {"price": 12, "tags": ["x", "y"], "name": "order-17"}}
    _check("numeric range", P({"detail": {"price": [{"numeric": [">", 10, "<=", 12]}]}}, ev)
           and not P({"detail": {"price": [{"numeric": ["<", 10]}]}}, ev))
    _check("anything-but / prefix / suffix",
           P({"source": [{"anything-but": ["z"]}]}, ev) and not P({"source": [{"anything-but": "a.b"}]}, ev)
           and P({"detail": {"name": [{"prefix": "order-"}]}}, ev) and P({"detail": {"name": [{"suffix": "17"}]}}, ev))
    _check("exists true/false", P({"detail": {"name": [{"exists": True}]}}, ev)
           and P({"detail": {"nope": [{"exists": False}]}}, ev) and not P({"detail": {"nope": [{"exists": True}]}}, ev))
    _check("array event value matches any element + $or",
           P({"detail": {"tags": ["y"]}}, ev) and P({"$or": [{"source": ["q"]}, {"source": ["a.b"]}]}, ev))

    # Lambda target: matching event INVOKES the function with the event as payload.
    try:
        from core import lambda_core as lam
    except ImportError:  # pragma: no cover
        import lambda_core as lam  # type: ignore
    import types
    ls = types.SimpleNamespace()
    got = []
    lam.dispatch(ls, "POST", "/2015-03-31/functions", {}, {}, json.dumps({
        "FunctionName": "sink", "Handler": "index.handler",
        "Code": {"Source": "def handler(e, c):\n    return {'seen': e['detail']['k']}"}}).encode())
    # prove delivery through the store the function records its run on
    call2 = lambda a, b: eb.dispatch(s, E + a, b, lambda_store=ls)
    call2("PutRule", {"Name": "rl", "EventPattern": json.dumps({"source": ["lam.app"]})})
    call2("PutTargets", {"Rule": "rl", "Targets": [{"Id": "tl", "Arn": "arn:aws:lambda:us-east-1:123456789012:function:sink"}]})
    eb.set_lambda_invoker(lambda n, b: got.append((n, json.loads(b))))
    call2("PutEvents", {"Entries": [{"Source": "lam.app", "DetailType": "x", "Detail": json.dumps({"k": 7})}]})
    eb.set_lambda_invoker(None)
    _check("Lambda target invoked with the event (offline invoker hook)",
           got and got[0][0] == "sink" and got[0][1]["detail"] == {"k": 7})
    real = []
    orig = lam.dispatch
    lam.dispatch = lambda st, m, p, q, h, b=b"": real.append((p, json.loads(b))) or orig(st, m, p, q, h, b)
    try:
        call2("PutEvents", {"Entries": [{"Source": "lam.app", "DetailType": "x", "Detail": json.dumps({"k": 8})}]})
    finally:
        lam.dispatch = orig
    _check("Lambda target invoked through lambda_core store (Nano path)",
           real and real[0][0].endswith("/functions/sink/invocations") and real[0][1]["detail"] == {"k": 8})

    # Event-bus target: default-bus rule forwards to bus "audit"; its rule delivers to SQS.
    qurl3 = sqs.dispatch(s, "AmazonSQS.CreateQueue", {"QueueName": "audit-q"}).body["QueueUrl"]
    qarn3 = sqs.dispatch(s, "AmazonSQS.GetQueueAttributes", {"QueueUrl": qurl3}).body["Attributes"]["QueueArn"]
    call("PutRule", {"Name": "fwd", "EventPattern": json.dumps({"source": ["fwd.app"]})})
    call("PutTargets", {"Rule": "fwd", "Targets": [{"Id": "b1", "Arn": f"arn:aws:events:us-east-1:{s.account_id}:event-bus/audit"}]})
    call("PutRule", {"Name": "audit-r", "EventBusName": "audit", "EventPattern": json.dumps({"source": ["fwd.app"]})})
    call("PutTargets", {"Rule": "audit-r", "Targets": [{"Id": "q", "Arn": qarn3}]})
    call("PutEvents", {"Entries": [{"Source": "fwd.app", "DetailType": "x", "Detail": "{}"}]})
    got = sqs.dispatch(s, "AmazonSQS.ReceiveMessage", {"QueueUrl": qurl3, "MaxNumberOfMessages": 10}).body.get("Messages", [])
    _check("event-bus target forwards to the destination bus's rules", len(got) == 1)

    _check("ListRules",call("ListRules", {}).body["Rules"][0]["Name"] == "r1")
    _check("ListTargetsByRule", call("ListTargetsByRule", {"Rule": "r1"}).body["Targets"][0]["Id"] == "t1")

    print("\nEventBridge event-bus conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
