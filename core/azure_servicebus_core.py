"""Azure Service Bus (topics) core — the Azure peer of core/sns_core.py (AWS SNS)
and core/gcp_pubsub_core.py (GCP Pub/Sub). Closes the cross-cloud pub/sub-fan-out
symmetry gap: AWS + GCP had a topic→subscription fan-out service; Azure did not
(azure-storage-queue is a point-to-point queue, not pub/sub).

Speaks the native **Service Bus REST API** (`https://{ns}.servicebus.windows.net/`,
resource paths, HTTP verbs, `BrokerProperties` JSON header) and provides clean Python
entry points for the AMQP 1.0 listener (`core/servicebus_amqp/`).
NO fastapi / azure-sdk / socket imports → loads under Pyodide.
Persists through the SAME MessagingStore seam as SNS/SQS/Pub-Sub (core/messaging_store.py).
Message leasing, lock renewal, auto-dead-lettering, and settlement are backed by
the universal `core.lease` engine.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.messaging_store import MessagingStore
try:
    from core import lease
except ImportError:
    import lease  # type: ignore

MAX_MESSAGE_BYTES = 256 * 1024  # 256 KB Standard tier limit
DEFAULT_LOCK_DURATION = 60.0    # 60 seconds
DEFAULT_MAX_DELIVERY_COUNT = 10


@dataclass
class ServiceBusResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


class ServiceBusError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


def _now_iso(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts is not None else datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_seq(store: MessagingStore) -> int:
    seq = getattr(store, "_sb_seq", 0) + 1
    store._sb_seq = seq
    return seq


def _empty(status: int, headers: dict | None = None) -> ServiceBusResponse:
    return ServiceBusResponse(status=status, headers=headers or {}, media_type=None)


def _error(code: str, message: str, status: int = 400) -> ServiceBusResponse:
    body = json.dumps({"code": status, "detail": message}).encode()
    return ServiceBusResponse(status=status, body=body)


# ── topic / subscription accessors ───────────────────────────────────────────
def _require_topic(store: MessagingStore, name: str) -> dict[str, Any]:
    t = store.get_topic(name)
    if not t:
        raise ServiceBusError("MessagingEntityNotFound",
                              f"The messaging entity '{name}' could not be found.", 404)
    return t


def _require_subscription(topic: dict[str, Any], sub_name: str) -> dict[str, Any]:
    sub = topic.get("subscriptions", {}).get(sub_name)
    if not sub:
        raise ServiceBusError("MessagingEntityNotFound",
                              f"The subscription '{sub_name}' could not be found.", 404)
    return sub


def _redrive_subscription(sub: dict[str, Any], now: float) -> bool:
    """Move expired messages exceeding max_delivery_count to the dead_letter list."""
    max_d = int(sub.get("max_delivery_count", DEFAULT_MAX_DELIVERY_COUNT))
    messages = sub.setdefault("messages", [])
    dead = lease.take_dead(messages, now, max_d)
    if dead:
        dlq = sub.setdefault("dead_letter", [])
        for m in dead:
            m["DeadLetterReason"] = "MaxDeliveryCountExceeded"
            m["DeadLetterErrorDescription"] = "Message delivery count exceeded MaxDeliveryCount."
            m["lease_token"] = None
            m["visible_at"] = now
            dlq.append(m)
        return True
    return False


# ── topic operations ─────────────────────────────────────────────────────────
def _create_topic(store: MessagingStore, name: str) -> ServiceBusResponse:
    if not store.get_topic(name):
        store.put_topic(name, {"name": name, "subscriptions": {}, "created": _now_iso()})
        store.persist()
    return _empty(201)


def _get_topic(store: MessagingStore, name: str) -> ServiceBusResponse:
    _require_topic(store, name)
    return _empty(200)


def _delete_topic(store: MessagingStore, name: str) -> ServiceBusResponse:
    _require_topic(store, name)
    store.drop_topic(name)
    store.persist()
    return _empty(200)


def _create_subscription(store: MessagingStore, topic_name: str, sub_name: str,
                        lock_duration: float = DEFAULT_LOCK_DURATION,
                        max_delivery_count: int = DEFAULT_MAX_DELIVERY_COUNT) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    subs = topic.setdefault("subscriptions", {})
    if sub_name not in subs:
        subs[sub_name] = {
            "name": sub_name,
            "messages": [],
            "dead_letter": [],
            "lock_duration": float(lock_duration),
            "max_delivery_count": int(max_delivery_count),
            "created": _now_iso(),
        }
        store.persist()
    return _empty(201)


def _delete_subscription(store: MessagingStore, topic_name: str, sub_name: str) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    _require_subscription(topic, sub_name)
    topic["subscriptions"].pop(sub_name, None)
    store.persist()
    return _empty(200)


# ── message properties parser ────────────────────────────────────────────────
def _broker_props(headers: dict) -> dict:
    raw = headers.get("brokerproperties") or headers.get("BrokerProperties") or ""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


# ── send (fan-out) ───────────────────────────────────────────────────────────
def _send(store: MessagingStore, topic_name: str, body: bytes, headers: dict) -> ServiceBusResponse:
    if len(body) > MAX_MESSAGE_BYTES:
        raise ServiceBusError("PayloadTooLarge",
                              f"The size of the message ({len(body)} bytes) exceeds the maximum allowed size of 256 KB.", 413)

    topic = _require_topic(store, topic_name)
    props = _broker_props(headers)
    message_id = str(props.get("MessageId") or uuid.uuid4())
    content_type = headers.get("content-type", "application/octet-stream")
    correlation_id = props.get("CorrelationId")
    subject = props.get("Label") or props.get("Subject")
    reply_to = props.get("ReplyTo")

    # Application properties: any headers not in standard HTTP/Broker set
    app_props = {k: v for k, v in headers.items()
                 if k not in ("brokerproperties", "content-type", "authorization", "host", "user-agent", "accept")}

    # Fan out an independent copy into every subscription backlog
    for sub in topic.get("subscriptions", {}).values():
        seq = _next_seq(store)
        msg = {
            "_id": uuid.uuid4().hex,
            "SequenceNumber": seq,
            "MessageId": message_id,
            "body": body,
            "content_type": content_type,
            "correlation_id": correlation_id,
            "subject": subject,
            "reply_to": reply_to,
            "properties": {k: v for k, v in props.items() if k not in ("MessageId", "CorrelationId", "Label", "Subject", "ReplyTo")},
            "application_properties": dict(app_props),
            "EnqueuedTimeUtc": _now_iso(store.now()),
            "delivery_count": 0,
            "lease_token": None,
            "visible_at": 0.0,
            "deleted": False,
        }
        sub.setdefault("messages", []).append(msg)

    store.persist()
    return _empty(201)


# ── receive helpers ──────────────────────────────────────────────────────────
def _msg_response(msg: dict, lock_token: str | None = None, locked_until: str | None = None) -> ServiceBusResponse:
    bp = {
        "MessageId": msg["MessageId"],
        "SequenceNumber": msg["SequenceNumber"],
        "EnqueuedTimeUtc": msg["EnqueuedTimeUtc"],
        "DeliveryCount": msg.get("delivery_count", 1),
    }
    if lock_token:
        bp["LockToken"] = lock_token
    if locked_until:
        bp["LockedUntilUtc"] = locked_until
    if msg.get("correlation_id"):
        bp["CorrelationId"] = msg["correlation_id"]
    if msg.get("subject"):
        bp["Label"] = msg["subject"]
    if msg.get("reply_to"):
        bp["ReplyTo"] = msg["reply_to"]
    if msg.get("DeadLetterReason"):
        bp["DeadLetterReason"] = msg["DeadLetterReason"]
    if msg.get("DeadLetterErrorDescription"):
        bp["DeadLetterErrorDescription"] = msg["DeadLetterErrorDescription"]

    headers = {"BrokerProperties": json.dumps(bp)}
    for k, v in (msg.get("properties") or {}).items():
        headers[str(k)] = str(v)
    for k, v in (msg.get("application_properties") or {}).items():
        headers[str(k)] = str(v)

    return ServiceBusResponse(status=200, body=msg["body"], headers=headers,
                              media_type=msg.get("content_type", "application/octet-stream"))


def _get_target_backlog(sub: dict, is_dlq: bool) -> list[dict]:
    return sub.setdefault("dead_letter" if is_dlq else "messages", [])


def _receive_and_delete(store: MessagingStore, topic_name: str, sub_name: str, is_dlq: bool = False) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    if not is_dlq:
        _redrive_subscription(sub, now)

    backlog = _get_target_backlog(sub, is_dlq)
    for i, msg in enumerate(backlog):
        if lease.available(msg, now):
            lease.settle(msg, msg.get("lease_token"), now, strict=False)
            backlog.pop(i)
            store.persist()
            return _msg_response(msg)

    return _empty(204)  # No messages available


def _peek_lock(store: MessagingStore, topic_name: str, sub_name: str, is_dlq: bool = False) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    if not is_dlq:
        _redrive_subscription(sub, now)

    lock_duration = float(sub.get("lock_duration", DEFAULT_LOCK_DURATION))
    backlog = _get_target_backlog(sub, is_dlq)

    for msg in backlog:
        if lease.available(msg, now):
            token = lease.lease(msg, now, lock_duration)
            locked_until_iso = _now_iso(msg["visible_at"])
            store.persist()
            return _msg_response(msg, lock_token=token, locked_until=locked_until_iso)

    return _empty(204)


def _complete(store: MessagingStore, topic_name: str, sub_name: str, seq: str, lock: str, is_dlq: bool = False) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    backlog = _get_target_backlog(sub, is_dlq)

    for i, msg in enumerate(backlog):
        if str(msg["SequenceNumber"]) == str(seq) and (msg.get("lease_token") == lock or msg.get("_locked") == lock):
            try:
                lease.settle(msg, msg.get("lease_token") or lock, now, strict=True)
                backlog.pop(i)
                store.persist()
                return _empty(200)
            except lease.LeaseLost:
                raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)

    raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)


def _abandon(store: MessagingStore, topic_name: str, sub_name: str, seq: str, lock: str, is_dlq: bool = False) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    backlog = _get_target_backlog(sub, is_dlq)
    max_d = int(sub.get("max_delivery_count", DEFAULT_MAX_DELIVERY_COUNT))

    for i, msg in enumerate(backlog):
        if str(msg["SequenceNumber"]) == str(seq) and (msg.get("lease_token") == lock or msg.get("_locked") == lock):
            try:
                lease.release(msg, msg.get("lease_token") or lock, now, strict=True)
                # If release pushed delivery_count to max_delivery_count, move directly to DLQ
                if not is_dlq and int(msg.get("delivery_count", 0)) >= max_d:
                    dead = backlog.pop(i)
                    dead["DeadLetterReason"] = "MaxDeliveryCountExceeded"
                    dead["DeadLetterErrorDescription"] = "Message delivery count exceeded MaxDeliveryCount."
                    sub.setdefault("dead_letter", []).append(dead)
                store.persist()
                return _empty(200)
            except lease.LeaseLost:
                raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)

    raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)


def _renew_lock(store: MessagingStore, topic_name: str, sub_name: str, seq: str, lock: str, is_dlq: bool = False) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    lock_duration = float(sub.get("lock_duration", DEFAULT_LOCK_DURATION))
    backlog = _get_target_backlog(sub, is_dlq)

    for msg in backlog:
        if str(msg["SequenceNumber"]) == str(seq) and (msg.get("lease_token") == lock or msg.get("_locked") == lock):
            try:
                new_vis = lease.extend(msg, msg.get("lease_token") or lock, now, lock_duration, strict=True)
                store.persist()
                headers = {"BrokerProperties": json.dumps({"LockedUntilUtc": _now_iso(new_vis)})}
                return ServiceBusResponse(status=200, headers=headers)
            except lease.LeaseLost:
                raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)

    raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)


# ── direct Python entry points for AMQP and other callers ────────────────────
def sb_send(store: MessagingStore, topic_name: str, body: bytes,
            headers: dict | None = None, properties: dict | None = None,
            application_properties: dict | None = None,
            message_id: str | None = None, content_type: str | None = None,
            correlation_id: str | None = None, subject: str | None = None,
            reply_to: str | None = None) -> str:
    """Send message to a topic (fan-out into all subscriptions). Returns message_id."""
    if len(body) > MAX_MESSAGE_BYTES:
        raise ServiceBusError("PayloadTooLarge",
                              f"The size of the message ({len(body)} bytes) exceeds the maximum allowed size of 256 KB.", 413)

    topic = _require_topic(store, topic_name)
    mid = message_id or str(uuid.uuid4())
    ct = content_type or "application/octet-stream"

    for sub in topic.get("subscriptions", {}).values():
        seq = _next_seq(store)
        msg = {
            "_id": uuid.uuid4().hex,
            "SequenceNumber": seq,
            "MessageId": mid,
            "body": body,
            "content_type": ct,
            "correlation_id": correlation_id,
            "subject": subject,
            "reply_to": reply_to,
            "properties": dict(properties or {}),
            "application_properties": dict(application_properties or {}),
            "EnqueuedTimeUtc": _now_iso(store.now()),
            "delivery_count": 0,
            "lease_token": None,
            "visible_at": 0.0,
            "deleted": False,
        }
        sub.setdefault("messages", []).append(msg)

    store.persist()
    return mid


def sb_peek_lock(store: MessagingStore, topic_name: str, sub_name: str, is_dlq: bool = False) -> tuple[dict | None, str | None]:
    """Lease a message. Returns (msg, lock_token) or (None, None)."""
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    if not is_dlq:
        _redrive_subscription(sub, now)

    lock_duration = float(sub.get("lock_duration", DEFAULT_LOCK_DURATION))
    backlog = _get_target_backlog(sub, is_dlq)

    for msg in backlog:
        if lease.available(msg, now):
            token = lease.lease(msg, now, lock_duration)
            store.persist()
            return msg, token

    return None, None


def sb_complete(store: MessagingStore, topic_name: str, sub_name: str, seq: str | int, lock: str, is_dlq: bool = False) -> None:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    backlog = _get_target_backlog(sub, is_dlq)

    for i, msg in enumerate(backlog):
        if str(msg["SequenceNumber"]) == str(seq) and (msg.get("lease_token") == lock or msg.get("_locked") == lock):
            try:
                lease.settle(msg, msg.get("lease_token") or lock, now, strict=True)
                backlog.pop(i)
                store.persist()
                return
            except lease.LeaseLost:
                raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)

    raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)


def sb_abandon(store: MessagingStore, topic_name: str, sub_name: str, seq: str | int, lock: str, is_dlq: bool = False) -> None:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    backlog = _get_target_backlog(sub, is_dlq)
    max_d = int(sub.get("max_delivery_count", DEFAULT_MAX_DELIVERY_COUNT))

    for i, msg in enumerate(backlog):
        if str(msg["SequenceNumber"]) == str(seq) and (msg.get("lease_token") == lock or msg.get("_locked") == lock):
            try:
                lease.release(msg, msg.get("lease_token") or lock, now, strict=True)
                if not is_dlq and int(msg.get("delivery_count", 0)) >= max_d:
                    dead = backlog.pop(i)
                    dead["DeadLetterReason"] = "MaxDeliveryCountExceeded"
                    dead["DeadLetterErrorDescription"] = "Message delivery count exceeded MaxDeliveryCount."
                    sub.setdefault("dead_letter", []).append(dead)
                store.persist()
                return
            except lease.LeaseLost:
                raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)

    raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)


def sb_renew_lock(store: MessagingStore, topic_name: str, sub_name: str, seq: str | int, lock: str, is_dlq: bool = False) -> float:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    lock_duration = float(sub.get("lock_duration", DEFAULT_LOCK_DURATION))
    backlog = _get_target_backlog(sub, is_dlq)

    for msg in backlog:
        if str(msg["SequenceNumber"]) == str(seq) and (msg.get("lease_token") == lock or msg.get("_locked") == lock):
            try:
                new_vis = lease.extend(msg, msg.get("lease_token") or lock, now, lock_duration, strict=True)
                store.persist()
                return new_vis
            except lease.LeaseLost:
                raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)

    raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)


def sb_dead_letter(store: MessagingStore, topic_name: str, sub_name: str, seq: str | int, lock: str,
                   reason: str | None = None, description: str | None = None) -> None:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    messages = sub.setdefault("messages", [])

    for i, msg in enumerate(messages):
        if str(msg["SequenceNumber"]) == str(seq) and (msg.get("lease_token") == lock or msg.get("_locked") == lock):
            try:
                lease.dead_letter(msg, msg.get("lease_token") or lock, now, strict=True, reason=reason, description=description)
                dead = messages.pop(i)
                dead["deleted"] = False
                dead["lease_token"] = None
                dead["visible_at"] = now
                dead["DeadLetterReason"] = reason or "ExplicitDeadLetter"
                dead["DeadLetterErrorDescription"] = description or ""
                sub.setdefault("dead_letter", []).append(dead)
                store.persist()
                return
            except lease.LeaseLost:
                raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)

    raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)


# ── REST dispatch router ────────────────────────────────────────────────────
def dispatch(store: MessagingStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> ServiceBusResponse:
    method = (method or "GET").upper()
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    p = path.split("?", 1)[0].strip("/")
    segs = [s for s in p.split("/") if s != ""]
    if not segs:
        return _error("BadRequest", "Missing entity path.", 400)

    topic = segs[0]
    try:
        # topic-level: /{topic}
        if len(segs) == 1:
            if method == "PUT":
                return _create_topic(store, topic)
            if method == "GET":
                return _get_topic(store, topic)
            if method == "DELETE":
                return _delete_topic(store, topic)
            return _error("BadRequest", f"Unsupported method {method} on topic.", 400)

        # send: /{topic}/messages
        if len(segs) == 2 and segs[1] == "messages":
            if method == "POST":
                return _send(store, topic, body, headers)
            return _error("BadRequest", f"Unsupported method {method} on messages.", 400)

        # subscription-scoped: /{topic}/subscriptions/{sub}[...]
        if len(segs) >= 3 and segs[1].lower() == "subscriptions":
            sub = segs[2]

            # /{topic}/subscriptions/{sub}
            if len(segs) == 3:
                if method == "PUT":
                    return _create_subscription(store, topic, sub)
                if method == "DELETE":
                    return _delete_subscription(store, topic, sub)
                if method == "GET":
                    _require_subscription(_require_topic(store, topic), sub)
                    return _empty(200)
                return _error("BadRequest", f"Unsupported method {method} on subscription.", 400)

            # Check if targeting $deadletterqueue: /{topic}/subscriptions/{sub}/$deadletterqueue/...
            is_dlq = False
            msg_idx = 3
            if segs[3].lower() in ("$deadletterqueue", "$deadletter"):
                is_dlq = True
                msg_idx = 4

            if len(segs) > msg_idx and segs[msg_idx] == "messages":
                # .../messages/head: receive-and-delete (DELETE) or peek-lock (POST)
                if len(segs) == msg_idx + 2 and segs[msg_idx + 1] == "head":
                    if method == "DELETE":
                        return _receive_and_delete(store, topic, sub, is_dlq=is_dlq)
                    if method == "POST":
                        return _peek_lock(store, topic, sub, is_dlq=is_dlq)

                # .../messages/{seq}/{lock}: complete (DELETE) / abandon (PUT) / renew-lock (POST)
                if len(segs) == msg_idx + 3:
                    seq, lock = segs[msg_idx + 1], segs[msg_idx + 2]
                    if method == "DELETE":
                        return _complete(store, topic, sub, seq, lock, is_dlq=is_dlq)
                    if method == "PUT":
                        return _abandon(store, topic, sub, seq, lock, is_dlq=is_dlq)
                    if method == "POST":
                        return _renew_lock(store, topic, sub, seq, lock, is_dlq=is_dlq)

                return _error("BadRequest", f"Unsupported message operation {method} {path}.", 400)

        return _error("BadRequest", f"Unknown Service Bus path: {path}", 404)
    except ServiceBusError as e:
        return _error(e.code, e.message, e.status)
