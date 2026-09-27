"""console-next messaging facade (SQS + SNS) — one shared MessagingStore so the
queue/topic-viewer widget can demonstrate REAL SNS→SQS fan-out (§13 queue/topic).

Why a console-scoped facade instead of the existing /api/sqs/* routes: the appliance
already has an SQS console REST facade, but it is backed by `ctx.sqs_state`, and SNS
has NO console REST facade at all — only the native SigV4 wire. To show the flagship
SNS→SQS fan-out honestly, SQS and SNS must share ONE store. So this module drives the
substrate-agnostic cores (core/sqs_core.py + core/sns_core.py) over a single
InMemoryMessagingStore — exactly the cores + shared store the Nano relay uses, so the
behaviour is byte-identical across substrates (§15). Purely additive: it does not
touch the existing /api/sqs/* routes or ctx state.

It exposes small JSON-shaped functions the console_next route layer maps to
/api/console/messaging/*. Mutating ops go through the cores' dispatch (real logic +
fan-out); list/peek ops read the store directly for clean JSON (no XML round-trip).
"""

from __future__ import annotations

import json
from typing import Any

from core import sqs_core, sns_core
from core.messaging_store import REGION, InMemoryMessagingStore

# ── one shared store for the console messaging vertical (module singleton) ──
_STORE = InMemoryMessagingStore()


def store() -> InMemoryMessagingStore:
    return _STORE


class MessagingError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _sqs(action: str, payload: dict) -> dict:
    resp = sqs_core.dispatch(_STORE, f"AmazonSQS.{action}", payload)
    body = resp.body if isinstance(resp.body, dict) else {}
    if resp.status >= 400:
        raise MessagingError(str(body.get("message") or body.get("Message") or action + " failed"),
                             resp.status)
    return body


def _sns(action: str, payload: dict) -> None:
    payload = dict(payload)
    payload["Action"] = action
    resp = sns_core.dispatch(_STORE, payload)
    if resp.status >= 400:
        # SNS core returns an XML error body; surface a plain message.
        raise MessagingError(f"{action} failed (HTTP {resp.status})", resp.status)


# ── queues (SQS) ────────────────────────────────────────────────────────────
def list_queues() -> dict:
    """List queues with an approximate depth (visible message count)."""
    now = _STORE.now()
    out = []
    for name in _STORE.queue_names():
        q = _STORE.get_queue(name) or {}
        msgs = q.get("messages", [])
        visible = sum(1 for m in msgs
                      if not m.get("deleted") and m.get("visible_at", 0) <= now)
        out.append({
            "queue_name": name,
            "queue_url": q.get("queue_url", ""),
            "queue_arn": q.get("queue_arn", ""),
            "approximate_messages": visible,
            "total_messages": sum(1 for m in msgs if not m.get("deleted")),
            "fifo": bool(q.get("fifo")),
        })
    return {"queues": out, "count": len(out)}


def create_queue(name: str) -> dict:
    body = _sqs("CreateQueue", {"QueueName": name})
    return {"queue_name": name, "queue_url": body.get("QueueUrl", "")}


def delete_queue(name: str) -> dict:
    q = _STORE.get_queue(name)
    _sqs("DeleteQueue", {"QueueUrl": q.get("queue_url") if q else name})
    return {"deleted": True, "queue_name": name}


def send_message(name: str, body: str, attributes: dict | None = None) -> dict:
    q = _STORE.get_queue(name)
    if not q:
        raise MessagingError("The specified queue does not exist.", 404)
    resp = _sqs("SendMessage", {"QueueUrl": q["queue_url"], "MessageBody": body})
    return {"queue_name": name, "message_id": resp.get("MessageId", ""),
            "md5_of_body": resp.get("MD5OfMessageBody", "")}


def receive_messages(name: str, max_n: int = 10, visibility: int = 0) -> dict:
    """Receive (lease) up to max_n messages — this MUTATES visibility like real SQS."""
    q = _STORE.get_queue(name)
    if not q:
        raise MessagingError("The specified queue does not exist.", 404)
    payload = {"QueueUrl": q["queue_url"], "MaxNumberOfMessages": max_n}
    if visibility:
        payload["VisibilityTimeout"] = visibility
    resp = _sqs("ReceiveMessage", payload)
    msgs = [_shape_msg(m) for m in resp.get("Messages", [])]
    return {"queue_name": name, "messages": msgs, "count": len(msgs)}


def peek_messages(name: str) -> dict:
    """Non-mutating peek: show all not-deleted messages + their visibility state,
    WITHOUT leasing them (so the browser view doesn't hide messages on refresh)."""
    q = _STORE.get_queue(name)
    if not q:
        raise MessagingError("The specified queue does not exist.", 404)
    now = _STORE.now()
    out = []
    for m in q.get("messages", []):
        if m.get("deleted"):
            continue
        out.append({
            "MessageId": m.get("message_id", ""),
            "Body": m.get("body", ""),
            "receive_count": m.get("receive_count", 0),
            "visible": m.get("visible_at", 0) <= now,
            "sent_at": m.get("sent_at", ""),
            "is_notification": _looks_like_sns(m.get("body", "")),
        })
    return {"queue_name": name, "messages": out, "count": len(out)}


def purge_queue(name: str) -> dict:
    q = _STORE.get_queue(name)
    _sqs("PurgeQueue", {"QueueUrl": q.get("queue_url") if q else name})
    return {"purged": True, "queue_name": name}


def _shape_msg(m: dict) -> dict:
    return {"MessageId": m.get("MessageId", ""), "Body": m.get("Body", ""),
            "ReceiptHandle": m.get("ReceiptHandle", ""),
            "receive_count": (m.get("Attributes", {}) or {}).get("ApproximateReceiveCount", "1")}


def _looks_like_sns(body: str) -> bool:
    try:
        d = json.loads(body)
        return isinstance(d, dict) and d.get("Type") == "Notification"
    except Exception:
        return False


# ── topics (SNS) ──────────────────────────────────────────────────────────
def list_topics() -> dict:
    out = []
    for arn in _STORE.topic_arns():
        t = _STORE.get_topic(arn) or {}
        subs = t.get("subscriptions", {})
        out.append({
            "topic_arn": arn,
            "name": t.get("name", arn.rsplit(":", 1)[-1]),
            "subscription_count": len(subs),
        })
    return {"topics": out, "count": len(out)}


def create_topic(name: str) -> dict:
    _sns("CreateTopic", {"Name": name})
    arn = f"arn:aws:sns:{REGION}:{_STORE.account_id}:{name}"
    return {"topic_arn": arn, "name": name}


def delete_topic(arn: str) -> dict:
    _sns("DeleteTopic", {"TopicArn": arn})
    return {"deleted": True, "topic_arn": arn}


def subscribe_queue(topic_arn: str, queue_name: str) -> dict:
    """Subscribe an SQS queue to an SNS topic (protocol=sqs) — the canonical
    fan-out subscription the widget wires with one click."""
    q = _STORE.get_queue(queue_name)
    if not q:
        raise MessagingError("The specified queue does not exist.", 404)
    _sns("Subscribe", {"TopicArn": topic_arn, "Protocol": "sqs",
                       "Endpoint": q["queue_arn"]})
    return {"subscribed": True, "topic_arn": topic_arn, "queue": queue_name,
            "endpoint": q["queue_arn"]}


def list_subscriptions(topic_arn: str) -> dict:
    t = _STORE.get_topic(topic_arn)
    if not t:
        raise MessagingError("Topic does not exist.", 404)
    out = []
    for sub in t.get("subscriptions", {}).values():
        endpoint = sub.get("endpoint", "")
        out.append({
            "subscription_arn": sub.get("subscription_arn", ""),
            "protocol": sub.get("protocol", ""),
            "endpoint": endpoint,
            "queue": endpoint.rsplit(":", 1)[-1] if sub.get("protocol") == "sqs" else "",
        })
    return {"topic_arn": topic_arn, "subscriptions": out, "count": len(out)}


def publish(topic_arn: str, message: str, subject: str | None = None) -> dict:
    """Publish to a topic — fans out to every subscribed SQS queue (real delivery)."""
    payload: dict[str, Any] = {"TopicArn": topic_arn, "Message": message}
    if subject:
        payload["Subject"] = subject
    _sns("Publish", payload)
    subs = _STORE.get_topic(topic_arn)
    delivered = 0
    if subs:
        delivered = sum(1 for s in subs.get("subscriptions", {}).values()
                        if s.get("protocol") == "sqs")
    return {"published": True, "topic_arn": topic_arn, "fanned_out_to": delivered}
