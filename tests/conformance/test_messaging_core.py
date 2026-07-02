"""Messaging (SQS + SNS) core conformance — the acceptance gate for the WASM
extraction.

This SAME test runs on two substrates and must be green on both:
  - host CPython (proxy for the Pro/Max appliance handler)
  - Pyodide / WASM (the Nano substrate)

It asserts the NATIVE wire semantics for both eventing services:
  - SQS (JSON protocol, AmazonSQS.*): send/receive round-trip with MD5,
    visibility-timeout hiding + automatic redelivery (deterministic via the
    store clock), delete-by-ReceiptHandle, ChangeMessageVisibility, purge.
  - SNS (Query protocol, XML): topics + subscriptions + real **fan-out** —
    Publish delivers the SNS envelope into the subscribed SQS queue, where it's
    a real, receivable message.

This is in-memory pub/sub (the NATS analogue). No network, no fastapi/boto3/broker.

Run on host:    python3 tests/conformance/test_messaging_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""
import hashlib
import json

# Allow running both as a repo script (host) and from a flat FS (Pyodide).
try:
    from core.messaging_store import InMemoryMessagingStore
    from core import sqs_core as sqs
    from core import sns_core as sns
except ImportError:  # pragma: no cover - Pyodide flat layout
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import sqs_core as sqs  # type: ignore
    import sns_core as sns  # type: ignore

SQS = "AmazonSQS."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run() -> int:
    st = InMemoryMessagingStore()
    st.set_time(1_000_000.0)  # deterministic clock for visibility timeouts

    # 1. CreateQueue -> QueueUrl; GetQueueUrl + ListQueues agree
    cq = sqs.dispatch(st, SQS + "CreateQueue", {"QueueName": "jobs",
                      "Attributes": {"VisibilityTimeout": "30"}})
    _check("create queue 200", cq.status == 200)
    url = cq.body["QueueUrl"]
    _check("create queue url", url.endswith("/jobs"))
    _check("get queue url matches", sqs.dispatch(st, SQS + "GetQueueUrl", {"QueueName": "jobs"}).body["QueueUrl"] == url)
    _check("list queues has jobs", url in sqs.dispatch(st, SQS + "ListQueues", {}).body["QueueUrls"])

    # 2. SendMessage -> MessageId + correct MD5
    payload = '{"task":"resize","id":42}'
    sm = sqs.dispatch(st, SQS + "SendMessage", {"QueueUrl": url, "MessageBody": payload})
    _check("send 200", sm.status == 200)
    _check("send MD5 correct", sm.body["MD5OfMessageBody"] == hashlib.md5(payload.encode()).hexdigest())

    # 3. ReceiveMessage -> body + ReceiptHandle
    rc = sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": url})
    msgs = rc.body["Messages"]
    _check("receive returns 1", len(msgs) == 1)
    _check("receive body round-trips", msgs[0]["Body"] == payload)
    handle = msgs[0]["ReceiptHandle"]
    _check("receive has ReceiptHandle", handle.startswith("rhdl-"))

    # 4. Re-receive immediately -> hidden (in visibility window)
    rc2 = sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": url})
    _check("message hidden during visibility window", "Messages" not in rc2.body)

    # 5. Advance past visibility -> redelivered, receive_count increments
    st.advance(31)
    rc3 = sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": url})
    _check("message redelivered after visibility expiry", len(rc3.body["Messages"]) == 1)
    _check("receive count incremented", rc3.body["Messages"][0]["Attributes"]["ApproximateReceiveCount"] == "2")
    new_handle = rc3.body["Messages"][0]["ReceiptHandle"]

    # 6. DeleteMessage with the STALE handle fails; with the current handle succeeds
    stale = sqs.dispatch(st, SQS + "DeleteMessage", {"QueueUrl": url, "ReceiptHandle": handle})
    _check("delete with stale handle rejected", stale.status == 400 and "ReceiptHandleIsInvalid" in stale.body["__type"])
    ok = sqs.dispatch(st, SQS + "DeleteMessage", {"QueueUrl": url, "ReceiptHandle": new_handle})
    _check("delete with current handle 200", ok.status == 200)
    st.advance(31)
    _check("deleted message gone", "Messages" not in sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": url}).body)

    # 7. ChangeMessageVisibility(0) makes an in-flight message immediately visible
    sqs.dispatch(st, SQS + "SendMessage", {"QueueUrl": url, "MessageBody": "retry-me"})
    h = sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": url}).body["Messages"][0]["ReceiptHandle"]
    _check("hidden right after receive", "Messages" not in sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": url}).body)
    sqs.dispatch(st, SQS + "ChangeMessageVisibility", {"QueueUrl": url, "ReceiptHandle": h, "VisibilityTimeout": 0})
    _check("change-visibility 0 makes it visible again", len(sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": url}).body["Messages"]) == 1)

    # 8. PurgeQueue empties it
    sqs.dispatch(st, SQS + "PurgeQueue", {"QueueUrl": url})
    st.advance(31)
    _check("purge empties the queue", "Messages" not in sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": url}).body)

    # 9. Non-existent queue -> native __type error
    nf = sqs.dispatch(st, SQS + "SendMessage", {"QueueUrl": "https://sqs.us-east-1.amazonaws.com/123456789012/ghost", "MessageBody": "x"})
    _check("missing queue QueueDoesNotExist", nf.status == 400 and "QueueDoesNotExist" in nf.body["__type"])

    # ── SNS pub/sub with real fan-out to SQS ──────────────────────────────
    # 10. CreateTopic + Subscribe an SQS queue
    sqs.dispatch(st, SQS + "CreateQueue", {"QueueName": "events"})
    events_q = sqs.dispatch(st, SQS + "GetQueueUrl", {"QueueName": "events"}).body["QueueUrl"]
    events_arn = st.get_queue("events")["queue_arn"]
    ct = sns.dispatch(st, {"Action": "CreateTopic", "Name": "orders"})
    _check("create topic 200", ct.status == 200)
    topic_arn = _xml_value(ct.body, "TopicArn")
    _check("topic arn", topic_arn.endswith(":orders"))
    sub = sns.dispatch(st, {"Action": "Subscribe", "TopicArn": topic_arn, "Protocol": "sqs", "Endpoint": events_arn})
    sub_arn = _xml_value(sub.body, "SubscriptionArn")
    _check("subscribe returns SubscriptionArn", bool(sub_arn))
    lst = sns.dispatch(st, {"Action": "ListSubscriptionsByTopic", "TopicArn": topic_arn})
    _check("subscription listed", events_arn in lst.body)

    # 11. Publish fans out -> the message lands in the subscribed SQS queue
    pub = sns.dispatch(st, {"Action": "Publish", "TopicArn": topic_arn, "Message": "order-placed:99", "Subject": "neworder"})
    _check("publish 200 + MessageId", pub.status == 200 and bool(_xml_value(pub.body, "MessageId")))
    got = sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": events_q}).body["Messages"]
    _check("fan-out delivered to the queue", len(got) == 1)
    envelope = json.loads(got[0]["Body"])
    _check("delivered SNS envelope type", envelope["Type"] == "Notification")
    _check("delivered message payload", envelope["Message"] == "order-placed:99")
    _check("delivered envelope topic", envelope["TopicArn"] == topic_arn)
    # delete it so it can't redeliver and confound the post-unsubscribe check
    sqs.dispatch(st, SQS + "DeleteMessage", {"QueueUrl": events_q, "ReceiptHandle": got[0]["ReceiptHandle"]})

    # 12. Unsubscribe stops delivery
    sns.dispatch(st, {"Action": "Unsubscribe", "SubscriptionArn": sub_arn})
    sns.dispatch(st, {"Action": "Publish", "TopicArn": topic_arn, "Message": "should-not-arrive"})
    st.advance(31)
    after = sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": events_q}).body
    _check("no delivery after unsubscribe", "Messages" not in after)

    # 13. SNS errors: publish to a missing topic; unknown action
    miss = sns.dispatch(st, {"Action": "Publish", "TopicArn": "arn:aws:sns:us-east-1:123456789012:ghost", "Message": "x"})
    _check("publish missing topic NotFound", "<Code>NotFound</Code>" in miss.body and miss.status == 404)
    _check("sns unknown action", "<Code>InvalidAction</Code>" in sns.dispatch(st, {"Action": "Nope"}).body)

    print("\nRESULT: PASS — Messaging core conforms (SQS JSON wire + SNS pub/sub fan-out) on this substrate.")
    return 0


def _xml_value(xml: str, tag: str) -> str:
    import re
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    return m.group(1) if m else ""


if __name__ == "__main__":
    raise SystemExit(run())
