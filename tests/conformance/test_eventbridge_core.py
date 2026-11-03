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

    # Retry + DLQ: a failing target is retried (RetryPolicy), then the event lands in its DLQ.
    dq = sqs.dispatch(s, "AmazonSQS.CreateQueue", {"QueueName": "eb-dlq"}).body["QueueUrl"]
    dqarn = sqs.dispatch(s, "AmazonSQS.GetQueueAttributes", {"QueueUrl": dq}).body["Attributes"]["QueueArn"]
    attempts = []
    eb.set_lambda_invoker(lambda n, b: attempts.append(n) or (_ for _ in ()).throw(RuntimeError("boom")))
    call2("PutRule", {"Name": "rd", "EventPattern": json.dumps({"source": ["dlq.app"]})})
    call2("PutTargets", {"Rule": "rd", "Targets": [{
        "Id": "td", "Arn": "arn:aws:lambda:us-east-1:123456789012:function:bad",
        "RetryPolicy": {"MaximumRetryAttempts": 2}, "DeadLetterConfig": {"Arn": dqarn}}]})
    r = call2("PutEvents", {"Entries": [{"Source": "dlq.app", "DetailType": "x", "Detail": json.dumps({"k": 1})}]}).body
    eb.set_lambda_invoker(None)
    _check("failing target does not fail PutEvents", r["FailedEntryCount"] == 0)
    _check("failing target retried MaximumRetryAttempts times (1+2)", len(attempts) == 3)
    m = sqs.dispatch(s, "AmazonSQS.ReceiveMessage", {"QueueUrl": dq, "MaxNumberOfMessages": 10}).body.get("Messages", [])
    _check("exhausted event dead-lettered to DeadLetterConfig queue",
           len(m) == 1 and json.loads(m[0]["Body"])["detail"] == {"k": 1})

    # Event-bus target: a rule on `default` forwards the event to another bus whose rule delivers it.
    call("PutRule", {"Name": "fwd", "EventPattern": json.dumps({"source": ["bus.app"]})})
    call("PutTargets", {"Rule": "fwd", "Targets": [{"Id": "tb", "Arn": "arn:aws:events:us-east-1:123456789012:event-bus/other"}]})
    call("PutRule", {"Name": "onother", "EventBusName": "other", "EventPattern": json.dumps({"source": ["bus.app"]})})
    call("PutTargets", {"Rule": "onother", "EventBusName": "other", "Targets": [{"Id": "tq", "Arn": qarn}]})
    drain()
    call("PutEvents", {"Entries": [{"Source": "bus.app", "DetailType": "x", "Detail": json.dumps({"k": 3})}]})
    _check("event-bus target forwards to the other bus's rule → SQS", drain() == 1)

    # Step Functions target: StartExecution with the event as input.
    try:
        from core import stepfunctions_core as sfn
    except ImportError:  # pragma: no cover
        import stepfunctions_core as sfn  # type: ignore
    ss = sfn.shared_store()
    sm = sfn.dispatch(ss, "AWSStepFunctions.CreateStateMachine", {
        "name": "eb-sm", "roleArn": "arn:aws:iam::123456789012:role/r",
        "definition": json.dumps({"StartAt": "P", "States": {"P": {"Type": "Pass", "End": True}}})}).body
    call("PutRule", {"Name": "rsf", "EventPattern": json.dumps({"source": ["sfn.app"]})})
    call("PutTargets", {"Rule": "rsf", "Targets": [{"Id": "ts", "Arn": sm["stateMachineArn"]}]})
    call("PutEvents", {"Entries": [{"Source": "sfn.app", "DetailType": "x", "Detail": json.dumps({"k": 9})}]})
    ex = sfn.dispatch(ss, "AWSStepFunctions.ListExecutions", {"stateMachineArn": sm["stateMachineArn"]}).body["executions"]
    _check("Step Functions target starts an execution", len(ex) == 1)
    d = sfn.dispatch(ss, "AWSStepFunctions.DescribeExecution", {"executionArn": ex[0]["executionArn"]}).body
    _check("execution input is the event", json.loads(d["input"])["detail"] == {"k": 9})

    _check("ListRules",call("ListRules", {}).body["Rules"][0]["Name"] == "r1")
    _check("ListTargetsByRule", call("ListTargetsByRule", {"Rule": "r1"}).body["Targets"][0]["Id"] == "t1")

    print("\nEventBridge event-bus conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
