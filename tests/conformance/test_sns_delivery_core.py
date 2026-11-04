"""Amazon SNS offline delivery worker (core/sns_delivery.py) conformance — proves the
healthyRetryPolicy (sns.topic.delivery-policy) is a REAL retry/backoff/dead-letter engine
on the offline appliance substrate, not stored-only configuration: a flaky local HTTP
endpoint is really retried over the network the configured number of times before the
worker gives up and redrives the message to the subscription's dead-letter queue, and
changing the policy's numRetries changes the observed number of attempts.

This drives core/sns_delivery.Delivery._process directly (the real attempt/retry/backoff/
redrive logic, run against a real local HTTP server) rather than through its NATS
JetStream transport, since durability-over-restarts is infrastructure, not the retry
policy's own behaviour, and no NATS broker is available in this test environment.

Run:  PYTHONPATH=. python3 tests/conformance/test_sns_delivery_core.py
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from core.messaging_store import InMemoryMessagingStore
from core import sqs_core as sqs, sns_core as sns, sns_delivery

SQS = "AmazonSQS."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _v(xml, tag):
    import re
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    return m.group(1) if m else ""


class _FlakyHandler(BaseHTTPRequestHandler):
    fail_until = 0
    calls: list[str] = []

    def do_POST(self):
        type(self).calls.append(self.path)
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if len(type(self).calls) <= type(self).fail_until:
            self.send_response(500)
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):  # quiet
        pass


def _job(topic: dict, sub: dict, *, message: str, message_id: str) -> dict:
    """Same shape core.sns_core._enqueue_delivery hands the worker."""
    return {"id": message_id, "topic_arn": topic["topic_arn"], "subscription_arn": sub["subscription_arn"],
            "protocol": sub["protocol"], "endpoint": sub["endpoint"], "retry_policy": sns._retry_policy(topic, sub),
            "signature_version": "1", "redrive_arn": sns._redrive_target(sub), "enqueued": sns._now_iso(),
            "kind": "Notification", "subject": "", "message": message, "message_id": message_id,
            "raw": True, "envelope": {}, "group": "", "attributes": {}}


async def _drive(delivery: sns_delivery.Delivery, job: dict) -> None:
    """Runs the worker's real per-attempt logic to completion on an in-memory queue
    (no NATS message object, no durable transport) — same retry/backoff/redrive code
    core/sns_delivery.py's threaded worker runs against the appliance's JetStream."""
    q: asyncio.Queue = asyncio.Queue()
    current, attempt = job, 1
    while True:
        await delivery._process(current, attempt, None, q)
        if q.empty():
            return
        current, attempt = await q.get()


def run() -> int:
    server = HTTPServer(("127.0.0.1", 0), _FlakyHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _run_cases(port)
    finally:
        server.shutdown()
        thread.join(timeout=5)
    print("\nRESULT: PASS — SNS offline delivery worker conforms.")
    return 0


def _run_cases(port: int) -> None:
    st = InMemoryMessagingStore()
    call = lambda a, **p: sns.dispatch(st, dict(p, Action=a))

    arn = _v(call("CreateTopic", Name="pushes").body, "TopicArn")
    sqs.dispatch(st, SQS + "CreateQueue", {"QueueName": "dlq"})
    dlq_arn = st.get_queue("dlq")["queue_arn"]
    dlq_url = sqs.dispatch(st, SQS + "GetQueueUrl", {"QueueName": "dlq"}).body["QueueUrl"]
    call("Subscribe", TopicArn=arn, Protocol="http", Endpoint=f"http://127.0.0.1:{port}/hook")
    tok = next(d["token"] for d in st.sns["deliveries"]
               if d["kind"] == "SubscriptionConfirmation" and d["endpoint"] == f"http://127.0.0.1:{port}/hook")
    sub_arn = _v(call("ConfirmSubscription", TopicArn=arn, Token=tok).body, "SubscriptionArn")
    call("SetSubscriptionAttributes", SubscriptionArn=sub_arn, AttributeName="RedrivePolicy",
         AttributeValue=json.dumps({"deadLetterTargetArn": dlq_arn}))
    call("SetSubscriptionAttributes", SubscriptionArn=sub_arn, AttributeName="DeliveryPolicy",
         AttributeValue=json.dumps({"healthyRetryPolicy": {
             "numRetries": 3, "minDelayTarget": 0, "maxDelayTarget": 0, "numNoDelayRetries": 3}}))
    topic = st.get_topic(arn)
    subrec = topic["subscriptions"][sub_arn]

    def deliver_sqs(endpoint_arn, body, attrs, group, dedup):
        q = st.get_queue_by_arn(endpoint_arn)
        if q is None:
            return False
        sqs.enqueue(st, q, body, attrs, message_group_id=group, message_dedup_id=dedup)
        return True

    delivery = sns_delivery.Delivery(st, base_url=lambda: "http://127.0.0.1", invoke_lambda=lambda *a: None,
                                     deliver_sqs=deliver_sqs)

    # a flaky endpoint is really retried over the network until it succeeds
    _FlakyHandler.fail_until, _FlakyHandler.calls = 2, []
    asyncio.run(_drive(delivery, _job(topic, subrec, message="retried-until-success", message_id="m1")))
    _check("flaky http endpoint really POSTed to over the network, 2 failures + 1 success", _FlakyHandler.calls == ["/hook"] * 3)
    last = st.sns["deliveries"][-1]
    _check("success logged as a real delivered Notification", last["kind"] == "Notification" and last.get("status") == "delivered")

    # an endpoint that never recovers exhausts the configured retries, then redrives to the DLQ
    _FlakyHandler.fail_until, _FlakyHandler.calls = 999, []
    asyncio.run(_drive(delivery, _job(topic, subrec, message="exhausted", message_id="m2")))
    _check("exhausted retries == numRetries(3) + the initial attempt == 4 real POSTs", len(_FlakyHandler.calls) == 4)
    _check("gives up after exhausting the configured retries",
           any(d["kind"] == "DeliveryFailure" and "gave up after 4 attempts" in d.get("error", "") for d in st.sns["deliveries"]))
    dead = sqs.dispatch(st, SQS + "ReceiveMessage", {"QueueUrl": dlq_url}).body["Messages"]
    _check("exhausted http delivery really lands in the dead-letter queue", len(dead) == 1 and "exhausted" in dead[0]["Body"])

    # lowering numRetries changes the observed attempt count — the policy is enforced, not stored
    call("SetSubscriptionAttributes", SubscriptionArn=sub_arn, AttributeName="DeliveryPolicy",
         AttributeValue=json.dumps({"healthyRetryPolicy": {
             "numRetries": 1, "minDelayTarget": 0, "maxDelayTarget": 0, "numNoDelayRetries": 1}}))
    _FlakyHandler.fail_until, _FlakyHandler.calls = 999, []
    asyncio.run(_drive(delivery, _job(topic, subrec, message="fewer-retries", message_id="m3")))
    _check("numRetries=1 -> exactly 2 real POSTs before giving up", len(_FlakyHandler.calls) == 2)


if __name__ == "__main__":
    raise SystemExit(run())
