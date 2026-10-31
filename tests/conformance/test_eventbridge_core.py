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

    _check("ListRules",call("ListRules", {}).body["Rules"][0]["Name"] == "r1")
    _check("ListTargetsByRule", call("ListTargetsByRule", {"Rule": "r1"}).body["Targets"][0]["Id"] == "t1")

    print("\nEventBridge event-bus conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
