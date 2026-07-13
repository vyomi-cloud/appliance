"""SQS FIFO + DLQ conformance (v2.6.0 operation depth) — runs on host + Pyodide.

Asserts the native SQS JSON-wire semantics for:
  - FIFO queues (.fifo): MessageGroupId required, content-based dedup, and
    per-group ordering (a group with an in-flight message is locked).
  - Dead-letter redrive: after maxReceiveCount receives without a delete, a
    message is moved to the RedrivePolicy target queue.
"""
import json

try:
    from core.messaging_store import InMemoryMessagingStore
    from core import sqs_core as sqs
except ImportError:  # pragma: no cover - Pyodide flat layout
    from messaging_store import InMemoryMessagingStore  # type: ignore
    import sqs_core as sqs  # type: ignore

T = "AmazonSQS."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or InMemoryMessagingStore()
    s.set_time(1000.0)

    def call(a, b):
        r = sqs.dispatch(s, T + a, b)
        if r.status != 200:
            raise AssertionError((a, r.body))
        return r.body

    # ── FIFO ──────────────────────────────────────────────────────────────
    url = call("CreateQueue", {"QueueName": "orders.fifo",
                               "Attributes": {"ContentBasedDeduplication": "true"}})["QueueUrl"]
    call("SendMessage", {"QueueUrl": url, "MessageBody": "A1", "MessageGroupId": "g1"})
    call("SendMessage", {"QueueUrl": url, "MessageBody": "A2", "MessageGroupId": "g1"})
    call("SendMessage", {"QueueUrl": url, "MessageBody": "B1", "MessageGroupId": "g2"})
    call("SendMessage", {"QueueUrl": url, "MessageBody": "A1", "MessageGroupId": "g1"})  # dup

    r = call("ReceiveMessage", {"QueueUrl": url, "MaxNumberOfMessages": 10})
    bodies = sorted(m["Body"] for m in r["Messages"])
    _check("FIFO group-exclusivity + content dedup (A1,B1; not A2)", bodies == ["A1", "B1"])

    miss = sqs.dispatch(s, T + "SendMessage", {"QueueUrl": url, "MessageBody": "x"})
    _check("FIFO requires MessageGroupId", miss.status == 400 and "MessageGroupId" in miss.body["message"])

    # ── DLQ redrive ───────────────────────────────────────────────────────
    s2 = InMemoryMessagingStore()
    s2.set_time(0.0)

    def call2(a, b):
        r = sqs.dispatch(s2, T + a, b)
        if r.status != 200:
            raise AssertionError((a, r.body))
        return r.body

    dlq = call2("CreateQueue", {"QueueName": "dead"})["QueueUrl"]
    dlq_arn = call2("GetQueueAttributes", {"QueueUrl": dlq})["Attributes"]["QueueArn"]
    main = call2("CreateQueue", {"QueueName": "main", "Attributes": {
        "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": 2})}})["QueueUrl"]
    call2("SendMessage", {"QueueUrl": main, "MessageBody": "poison"})
    for _ in range(3):
        call2("ReceiveMessage", {"QueueUrl": main})
        s2.advance(60)   # lease lapses → available again
    _check("main empty after redrive",
           call2("GetQueueAttributes", {"QueueUrl": main})["Attributes"]["ApproximateNumberOfMessages"] == "0")
    got = call2("ReceiveMessage", {"QueueUrl": dlq})
    _check("poison message moved to DLQ", got.get("Messages") and got["Messages"][0]["Body"] == "poison")

    print("\nSQS FIFO + DLQ conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
