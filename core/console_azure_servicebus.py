"""console-next messaging facade (Azure Service Bus) — the Azure lens's
queue-topic-viewer data plane.

The SAME queue-topic-viewer widget renders under lens=azure; the ONLY difference is
the manifest `api` block pointing at /api/console/azure-servicebus/* instead of
/api/console/messaging/* (§15.2 — no if(cloud) branching in the widget). This module
is the Service Bus sibling of the GCP Pub/Sub console facade
(core/console_gcp_pubsub.py) and the AWS SQS+SNS facade (core/console_messaging.py):
it returns the SAME JSON response shapes the widget consumes (list queues/topics,
send, peek/receive, subscriptions, subscribe, publish), so the widget stays
cloud-agnostic.

Service Bus mapping onto the queue-topic-viewer's two-column model:
    queue column  ->  Service Bus QUEUES (a queue has its own message backlog you
                      receive from — the analogue of an SQS queue / Pub/Sub sub)
    topic column  ->  Service Bus TOPICS (publish → fans out to every SUBSCRIPTION)
A "topic" fans a message out to every attached subscription's backlog; you receive
from a subscription just like from a queue. So the flagship fan-out (publish → lands
in every subscribed backlog) is REAL here too, with NO widget changes.

A Service Bus queue and a topic subscription are BOTH pull-targets with a backlog;
this facade models them uniformly (a subscription is a backlog registered under the
queue space so receive/peek work identically). The widget's "subscribe" step attaches
an existing queue as a topic subscription (protocol is always the Service Bus pull
model). "Send message to a queue" injects straight into that queue's backlog (the
canonical topic path is publish → fan-out).

Purely additive + substrate-free (no fastapi / azure-sdk / socket imports): it holds
its OWN module-level in-memory store so the Azure lens's messaging state is
independent of the AWS/GCP lenses', exactly like core/console_gcp_pubsub mirrors the
AWS messaging facade. It never touches the appliance's native messaging handling or
the shared MessagingStore the AWS messaging facade uses.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

NAMESPACE = "vyomi-sb"

# In-memory store, independent from the AWS/GCP messaging facades:
#   queues: { queue_name: { "topic": topic_name|None, "created": iso,
#             "messages": [ { message_id, body, published_at, visible_at,
#                             receive_count, deleted, is_notification } ] } }
#             (a plain queue has topic=None; a topic subscription has topic set)
#   topics: { topic_name: { "created": iso, "subscriptions": set[str] } }
_QUEUES: dict[str, dict[str, Any]] = {}
_TOPICS: dict[str, dict[str, Any]] = {}

# Controllable clock so receive/visibility is deterministic in tests (mirrors the
# MessagingStore clock contract). None -> real wall clock.
_CLOCK: float | None = None


def _now_ts() -> float:
    return _CLOCK if _CLOCK is not None else time.time()


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(_now_ts(), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def set_time(t: float) -> None:  # test hook
    global _CLOCK
    _CLOCK = t


def advance(seconds: float) -> None:  # test hook
    global _CLOCK
    _CLOCK = _now_ts() + seconds


def reset() -> None:  # test hook
    _QUEUES.clear()
    _TOPICS.clear()
    global _CLOCK
    _CLOCK = None


class ServiceBusError(Exception):
    """Facade error carrying an HTTP status + message (mapped to HTTPException)."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _queue_path(name: str) -> str:
    return f"sb://{NAMESPACE}.servicebus.windows.net/{name}"


def _topic_path(name: str) -> str:
    return f"sb://{NAMESPACE}.servicebus.windows.net/{name}"


def _msg_id(body: str) -> str:
    seed = f"{body}|{_now_ts()}|{len(_QUEUES)}".encode("utf-8")
    return hashlib.sha1(seed).hexdigest()[:24]


def _looks_like_fanout(body: str) -> bool:
    """A message delivered by a topic publish carries a fan-out envelope marker so
    the widget can flag it (mirrors the SNS-notification / Pub/Sub-delivery flag)."""
    try:
        d = json.loads(body)
        return isinstance(d, dict) and d.get("_sb_delivery") == "topic"
    except Exception:
        return False


# ── queues (the widget's "queue" column) ────────────────────────────────────
def list_queues() -> dict:
    """List queues with an approximate depth (visible message count) — the SAME JSON
    shape console_messaging.list_queues returns."""
    now = _now_ts()
    out = []
    for name in sorted(_QUEUES):
        s = _QUEUES[name]
        msgs = s.get("messages", [])
        visible = sum(
            1 for m in msgs if not m.get("deleted") and m.get("visible_at", 0) <= now
        )
        out.append(
            {
                "queue_name": name,
                "queue_url": _queue_path(name),
                "queue_arn": _queue_path(name),
                "approximate_messages": visible,
                "total_messages": sum(1 for m in msgs if not m.get("deleted")),
                "fifo": False,
                "topic": s.get("topic"),
            }
        )
    return {"queues": out, "count": len(out)}


def create_queue(name: str) -> dict:
    """Create a (detached) queue. It becomes a topic subscription via subscribe()."""
    name = (name or "").strip()
    if not name:
        raise ServiceBusError("ValidationError: queue name is required.", 400)
    if name in _QUEUES:
        raise ServiceBusError("Conflict: queue already exists.", 409)
    _QUEUES[name] = {"topic": None, "created": _now_iso(), "messages": []}
    return {"queue_name": name, "queue_url": _queue_path(name)}


def delete_queue(name: str) -> dict:
    q = _QUEUES.pop(name, None)
    if q is None:
        raise ServiceBusError("The specified queue does not exist.", 404)
    topic = q.get("topic")
    if topic and topic in _TOPICS:
        _TOPICS[topic]["subscriptions"].discard(name)
    return {"deleted": True, "queue_name": name}


def _queue(name: str) -> dict:
    s = _QUEUES.get(name)
    if s is None:
        raise ServiceBusError("The specified queue does not exist.", 404)
    return s


def send_message(name: str, body: str, attributes: dict | None = None) -> dict:
    """Inject a message straight into a queue's backlog (the canonical topic path is
    publish → fan-out)."""
    s = _queue(name)
    mid = _msg_id(body)
    s["messages"].append(
        {
            "message_id": mid,
            "body": body,
            "published_at": _now_iso(),
            "visible_at": 0,
            "receive_count": 0,
            "deleted": False,
            "is_notification": _looks_like_fanout(body),
        }
    )
    return {"queue_name": name, "message_id": mid, "md5_of_body": ""}


def receive_messages(name: str, max_n: int = 10, visibility: int = 0) -> dict:
    """Receive (lock) up to max_n visible messages — MUTATES visibility like Service
    Bus peek-lock (mirrors console_messaging.receive_messages)."""
    s = _queue(name)
    now = _now_ts()
    leased = []
    for m in s.get("messages", []):
        if len(leased) >= max_n:
            break
        if m.get("deleted") or m.get("visible_at", 0) > now:
            continue
        m["receive_count"] = m.get("receive_count", 0) + 1
        if visibility:
            m["visible_at"] = now + visibility
        leased.append(
            {
                "MessageId": m["message_id"],
                "Body": m["body"],
                "ReceiptHandle": m["message_id"],
                "receive_count": m["receive_count"],
            }
        )
    return {"queue_name": name, "messages": leased, "count": len(leased)}


def peek_messages(name: str) -> dict:
    """Non-mutating peek — SAME shape console_messaging.peek_messages returns."""
    s = _queue(name)
    now = _now_ts()
    out = []
    for m in s.get("messages", []):
        if m.get("deleted"):
            continue
        out.append(
            {
                "MessageId": m.get("message_id", ""),
                "Body": m.get("body", ""),
                "receive_count": m.get("receive_count", 0),
                "visible": m.get("visible_at", 0) <= now,
                "sent_at": m.get("published_at", ""),
                "is_notification": m.get("is_notification", False),
            }
        )
    return {"queue_name": name, "messages": out, "count": len(out)}


def purge_queue(name: str) -> dict:
    s = _queue(name)
    s["messages"] = []
    return {"purged": True, "queue_name": name}


# ── topics (the widget's "topic" column) ────────────────────────────────────
def list_topics() -> dict:
    out = []
    for name in sorted(_TOPICS):
        t = _TOPICS[name]
        out.append(
            {
                "topic_arn": _topic_path(name),
                "name": name,
                "subscription_count": len(t.get("subscriptions", set())),
            }
        )
    return {"topics": out, "count": len(out)}


def create_topic(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ServiceBusError("ValidationError: topic name is required.", 400)
    if name not in _TOPICS:
        _TOPICS[name] = {"created": _now_iso(), "subscriptions": set()}
    return {"topic_arn": _topic_path(name), "name": name}


def _topic_name_from_ref(topic_ref: str) -> str:
    """Accept either a bare topic name or a full sb://.../<name> path."""
    ref = (topic_ref or "").strip()
    return ref.rsplit("/", 1)[-1] if "/" in ref else ref


def _topic(topic_ref: str) -> tuple[str, dict]:
    name = _topic_name_from_ref(topic_ref)
    t = _TOPICS.get(name)
    if t is None:
        raise ServiceBusError("Topic does not exist.", 404)
    return name, t


def delete_topic(topic_ref: str) -> dict:
    name, t = _topic(topic_ref)
    for sub_name in list(t.get("subscriptions", set())):
        q = _QUEUES.get(sub_name)
        if q and q.get("topic") == name:
            q["topic"] = None
    _TOPICS.pop(name, None)
    return {"deleted": True, "topic_arn": _topic_path(name)}


def subscribe_queue(topic_ref: str, queue_name: str) -> dict:
    """Attach an existing queue as a topic subscription — the fan-out wiring the
    widget does with one click (analogue of SNS Subscribe protocol=sqs)."""
    name, t = _topic(topic_ref)
    q = _QUEUES.get(queue_name)
    if q is None:
        raise ServiceBusError("The specified queue does not exist.", 404)
    # A Service Bus subscription binds to exactly one topic; rebinding detaches the old.
    old = q.get("topic")
    if old and old in _TOPICS and old != name:
        _TOPICS[old]["subscriptions"].discard(queue_name)
    q["topic"] = name
    t["subscriptions"].add(queue_name)
    return {
        "subscribed": True,
        "topic_arn": _topic_path(name),
        "queue": queue_name,
        "endpoint": _queue_path(queue_name),
    }


def list_subscriptions(topic_ref: str) -> dict:
    """List the subscriptions attached to a topic — SAME shape console_messaging
    returns (protocol is the Service Bus pull model)."""
    name, t = _topic(topic_ref)
    out = []
    for sub_name in sorted(t.get("subscriptions", set())):
        out.append(
            {
                "subscription_arn": _queue_path(sub_name),
                "protocol": "pull",
                "endpoint": _queue_path(sub_name),
                "queue": sub_name,
            }
        )
    return {"topic_arn": _topic_path(name), "subscriptions": out, "count": len(out)}


def publish(topic_ref: str, message: str, subject: str | None = None) -> dict:
    """Publish to a topic — fans out to every attached subscription's backlog (REAL
    delivery). SAME response shape console_messaging.publish returns."""
    name, t = _topic(topic_ref)
    envelope = json.dumps(
        {
            "_sb_delivery": "topic",
            "topic": name,
            "subject": subject or "",
            "message": message,
        }
    )
    delivered = 0
    for sub_name in list(t.get("subscriptions", set())):
        q = _QUEUES.get(sub_name)
        if not q:
            continue
        q["messages"].append(
            {
                "message_id": _msg_id(envelope),
                "body": envelope,
                "published_at": _now_iso(),
                "visible_at": 0,
                "receive_count": 0,
                "deleted": False,
                "is_notification": True,
            }
        )
        delivered += 1
    return {"published": True, "topic_arn": _topic_path(name), "fanned_out_to": delivered}
