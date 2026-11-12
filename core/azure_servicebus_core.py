"""Azure Service Bus (topics) core — the Azure peer of core/sns_core.py (AWS SNS)
and core/gcp_pubsub_core.py (GCP Pub/Sub). Closes the cross-cloud pub/sub-fan-out
symmetry gap: AWS + GCP had a topic→subscription fan-out service; Azure did not
(azure-storage-queue is a point-to-point queue, not pub/sub).

Speaks the native **Service Bus REST API** (`https://{ns}.servicebus.windows.net/`,
resource paths, HTTP verbs, `BrokerProperties` JSON header) and provides clean Python
entry points for the AMQP 1.0 listener (`core/servicebus_amqp/`).
NO fastapi / azure-sdk / socket imports → loads under Pyodide.
Persists through the SAME MessagingStore seam as SNS/SQS/Pub-Sub (core/messaging_store.py):
topics live in `store.topics`, each with a nested `subscriptions` map whose entries hold an
independent message backlog.
Message leasing, lock renewal, auto-dead-lettering, and settlement are backed by
the universal `core.lease` engine (canonical fields: visible_at, delivery_count,
lease_token, deleted).

Model: a message SENT to a topic fans out an independent copy into every
subscription's backlog (the canonical topic model). A receiver pulls from a SPECIFIC
subscription — receive-and-delete (DELETE …/messages/head) pops the head; peek-lock
(POST …/messages/head) hands out the head under a lock token, DELETE …/messages/{seq}/{lock}
completes (removes) it, PUT unlocks (abandon), POST renews the lock.

Queues (the entity itself has no subscriptions): every entity ALSO keeps its own
direct backlog (`messages`), independent of any fan-out copies handed to
subscriptions — a real Service Bus queue has exactly one such backlog, so a plain
`PUT /{name}` + direct message ops models a queue; adding `subscriptions` on top of
the SAME entity is how a topic is modelled. Direct ops (no `/subscriptions/{sub}`
segment) are the Vyomi console's Service Bus Explorer surface — not strict Azure
wire shapes (that console UI isn't an SDK), so the batch peek/receive endpoints
return a plain JSON array rather than the single-message BrokerProperties shape the
SDK-facing subscription endpoints below return:
    GET    /{name}/messages                        batch peek (non-destructive)
    DELETE /{name}/messages?max=N                   batch receive-and-delete
    POST   /{name}/messages/{seq}/complete          remove a specific message
    POST   /{name}/messages/{seq}/defer             mark deferred (hidden from receive)
    POST   /{name}/messages/{seq}/deadletter        move to the $deadletterqueue sub-queue
    GET    /{name}/$deadletterqueue/messages        batch peek the dead-letter sub-queue
    POST   /{name}/$deadletterqueue/messages/{seq}/complete   remove a dead-lettered message

Scope (v1 slice): create/get/delete topic, create/get/delete subscription, send
(fan-out), receive-and-delete, peek-lock + complete/abandon, plus the queue direct-
backlog + dead-letter ops above. Sessions, SQL filter rules, and scheduled messages
reuse the same helpers and slot in next.
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


# ── topic operations ────────────────────────────────────────────────────────
# Optional JSON body on PUT /{entity} and PUT /{topic}/subscriptions/{sub}: entity options shared with the
# AMQP data plane (core/azure_servicebus_amqp.py). camelCase (as in the ARM properties) or snake_case.
_OPTION_KEYS = {"lockDuration": "lock_duration", "maxDeliveryCount": "max_delivery_count",
                "requiresSession": "requires_session", "requiresDuplicateDetection": "requires_duplicate_detection",
                "deadLetteringOnMessageExpiration": "dead_lettering_on_expiration", "defaultMessageTimeToLive": "default_ttl"}


def _entity_options(body: bytes) -> dict:
    if not body:
        return {}
    try:
        d = json.loads(body)
    except Exception:
        return {}
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        k2 = _OPTION_KEYS.get(k, k if k in _OPTION_KEYS.values() else None)
        if k2:
            out[k2] = v
    return out


def _create_topic(store: MessagingStore, name: str, body: bytes = b"") -> ServiceBusResponse:
    if not store.get_topic(name):
        t = {"name": name, "subscriptions": {}, "messages": [], "dead_letter": [], "created": _now_iso()}
        t.update(_entity_options(body))
        store.put_topic(name, t)
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


def _create_subscription(store: MessagingStore, topic_name: str, sub_name: str, body: bytes = b"",
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
        subs[sub_name].update(_entity_options(body))
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


def _make_message(message_id: str, body: bytes, content_type: str, props: dict, *, now: float | None = None,
                  correlation_id=None, subject=None, reply_to=None, app_props: dict | None = None) -> dict:
    """One message dict in the canonical `core.lease` schema (visible_at / delivery_count / lease_token / deleted)."""
    return {
        "_id": uuid.uuid4().hex,
        "SequenceNumber": None,   # assigned per-destination by the caller (_next_seq)
        "MessageId": message_id,
        "body": body,
        "content_type": content_type,
        "correlation_id": correlation_id,
        "subject": subject,
        "reply_to": reply_to,
        "properties": {k: v for k, v in props.items() if k not in ("MessageId", "CorrelationId", "Label", "Subject", "ReplyTo")},
        "application_properties": dict(app_props or {}),
        "EnqueuedTimeUtc": _now_iso(now),
        "delivery_count": 0,
        "lease_token": None,
        "visible_at": 0.0,
        "deleted": False,
        "_deferred": False,
    }


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
    now = store.now()
    # The entity's OWN backlog (a queue's single backlog, or a topic's "if anyone
    # peeks the topic directly" copy) ...
    own = _make_message(message_id, body, content_type, props, now=now, correlation_id=correlation_id,
                        subject=subject, reply_to=reply_to, app_props=app_props)
    own["SequenceNumber"] = _next_seq(store)
    topic.setdefault("messages", []).append(own)
    # ... AND an INDEPENDENT copy fanned out into every subscription backlog.
    try:
        from core import azure_servicebus_rules as _rules
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import azure_servicebus_rules as _rules  # type: ignore
    _view = {"sys": {"MessageId": message_id, "ContentType": content_type, "Label": subject,
                     "To": props.get("To"), "CorrelationId": correlation_id,
                     "SessionId": props.get("SessionId")},
             "user": {k: v for k, v in props.items() if k != "MessageId"}}
    for sub in topic.get("subscriptions", {}).values():
        if not _rules.subscription_matches(sub, _view):     # SQL / correlation rules (default: match all)
            continue
        copy = _make_message(message_id, body, content_type, props, now=now, correlation_id=correlation_id,
                             subject=subject, reply_to=reply_to, app_props=app_props)
        copy["SequenceNumber"] = _next_seq(store)
        sub.setdefault("messages", []).append(copy)
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


def _deliverable(m: dict, now: float) -> bool:
    """Available per the lease engine AND not deferred / not held by a legacy `_locked` token."""
    return lease.available(m, now) and not m.get("_deferred") and not m.get("_locked")


def _receive_and_delete(store: MessagingStore, topic_name: str, sub_name: str, is_dlq: bool = False) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    if not is_dlq:
        _redrive_subscription(sub, now)

    backlog = _get_target_backlog(sub, is_dlq)
    for i, msg in enumerate(backlog):
        if _deliverable(msg, now):
            msg["delivery_count"] = int(msg.get("delivery_count", 0)) + 1   # receive-and-delete counts as a delivery
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
        if _deliverable(msg, now):
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
            "ContentType": ct,
            "correlation_id": correlation_id,
            "CorrelationId": correlation_id,
            "subject": subject,
            "Subject": subject,
            "reply_to": reply_to,
            "ReplyTo": reply_to,
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
        if _deliverable(msg, now):
            token = lease.lease(msg, now, lock_duration)
            store.persist()
            return msg, token

    return None, None


def sb_complete(store: MessagingStore, topic_name: str, sub_name: str, seq: str | int | None = None, lock: str = "", is_dlq: bool = False) -> None:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    backlog = _get_target_backlog(sub, is_dlq)

    for i, msg in enumerate(backlog):
        if (seq is None or str(msg["SequenceNumber"]) == str(seq)) and (msg.get("lease_token") == lock or msg.get("_locked") == lock):
            try:
                lease.settle(msg, msg.get("lease_token") or lock, now, strict=True)
                backlog.pop(i)
                store.persist()
                return
            except lease.LeaseLost:
                raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)

    raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)


def sb_abandon(store: MessagingStore, topic_name: str, sub_name: str, seq: str | int | None = None, lock: str = "", is_dlq: bool = False) -> None:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    backlog = _get_target_backlog(sub, is_dlq)
    max_d = int(sub.get("max_delivery_count", DEFAULT_MAX_DELIVERY_COUNT))

    for i, msg in enumerate(backlog):
        if (seq is None or str(msg["SequenceNumber"]) == str(seq)) and (msg.get("lease_token") == lock or msg.get("_locked") == lock):
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


def sb_renew_lock(store: MessagingStore, topic_name: str, sub_name: str, seq: str | int | None = None, lock: str = "", is_dlq: bool = False) -> float:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    lock_duration = float(sub.get("lock_duration", DEFAULT_LOCK_DURATION))
    backlog = _get_target_backlog(sub, is_dlq)

    for msg in backlog:
        if (seq is None or str(msg["SequenceNumber"]) == str(seq)) and (msg.get("lease_token") == lock or msg.get("_locked") == lock):
            try:
                new_vis = lease.extend(msg, msg.get("lease_token") or lock, now, lock_duration, strict=True)
                store.persist()
                return new_vis
            except lease.LeaseLost:
                raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)

    raise ServiceBusError("MessageLockLost", "The lock supplied is invalid or has expired.", 410)


def sb_dead_letter(store: MessagingStore, topic_name: str, sub_name: str, seq: str | int | None = None, lock: str = "",
                   reason: str | None = None, description: str | None = None) -> None:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    now = store.now()
    messages = sub.setdefault("messages", [])

    for i, msg in enumerate(messages):
        if (seq is None or str(msg["SequenceNumber"]) == str(seq)) and (msg.get("lease_token") == lock or msg.get("_locked") == lock):
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


# ── direct queue backlog ops (the console's Service Bus Explorer; JSON-shaped,
#    not an SDK wire format — see the module docstring) ─────────────────────
def _message_view(m: dict, state: str) -> dict:
    body = m.get("body") or b""
    return {
        "SequenceNumber": m["SequenceNumber"],
        "MessageId": m["MessageId"],
        "EnqueuedTimeUtc": m["EnqueuedTimeUtc"],
        # lease schema (delivery_count) or the legacy AMQP broker's DeliveryCount: whichever stack delivered it
        "DeliveryCount": max(int(m.get("delivery_count") or 0), int(m.get("DeliveryCount") or 0)),
        "Label": m.get("subject") or (m.get("properties") or {}).get("Label"),
        "ContentType": m.get("content_type", "application/octet-stream"),
        "BodySize": len(body),
        "State": state,
        "Body": body.decode("utf-8", "replace"),
    }


def _entity_state(m: dict, now: float) -> str:
    if m.get("_deferred"):
        return "Deferred"
    if m.get("_locked") or not lease.available(m, now):
        return "Locked"
    return "Active"


def _json_list(messages: list) -> ServiceBusResponse:
    body = json.dumps({"messages": messages}).encode()
    return ServiceBusResponse(status=200, body=body, media_type="application/json")


def _peek_batch(store: MessagingStore, topic_name: str) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    now = store.now()
    msgs = [_message_view(m, _entity_state(m, now)) for m in topic.get("messages", []) if not m.get("deleted")]
    return _json_list(msgs)


def _receive_batch(store: MessagingStore, topic_name: str, max_n: int) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    now = store.now()
    taken, rest = [], []
    for m in topic.get("messages", []):
        if m.get("deleted"):
            continue
        if len(taken) < max_n and _deliverable(m, now):
            m["delivery_count"] = int(m.get("delivery_count", 0)) + 1
            taken.append(m)
        else:
            rest.append(m)
    topic["messages"] = rest
    store.persist()
    return _json_list([_message_view(m, "Active") for m in taken])


def _find_own_message(topic: dict, seq: str) -> dict:
    for m in topic.get("messages", []):
        if not m.get("deleted") and str(m["SequenceNumber"]) == str(seq):
            return m
    raise ServiceBusError("MessageNotFound", f"No message with sequence number '{seq}'.", 404)


def _complete_own(store: MessagingStore, topic_name: str, seq: str) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    _find_own_message(topic, seq)
    topic["messages"] = [m for m in topic["messages"] if str(m["SequenceNumber"]) != str(seq)]
    store.persist()
    return _empty(200)


def _defer_own(store: MessagingStore, topic_name: str, seq: str) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    m = _find_own_message(topic, seq)
    m["_deferred"] = True
    m["_locked"] = None
    m["lease_token"] = None
    store.persist()
    return _empty(200)


def _deadletter_own(store: MessagingStore, topic_name: str, seq: str, body: bytes) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    m = _find_own_message(topic, seq)
    try:
        reason = (json.loads(body) if body else {}).get("DeadLetterReason")
    except Exception:
        reason = None
    topic["messages"] = [x for x in topic["messages"] if x["_id"] != m["_id"]]
    m["_locked"] = None
    m["_deferred"] = False
    m["lease_token"] = None
    m["visible_at"] = store.now()
    m["DeadLetterReason"] = reason
    topic.setdefault("dead_letter", []).append(m)
    store.persist()
    return _empty(200)


def _peek_deadletter(store: MessagingStore, topic_name: str) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    msgs = [_message_view(m, "Dead-lettered") for m in topic.get("dead_letter", [])]
    return _json_list(msgs)


def _complete_deadletter(store: MessagingStore, topic_name: str, seq: str) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    dl = topic.get("dead_letter", [])
    if not any(str(m["SequenceNumber"]) == str(seq) for m in dl):
        raise ServiceBusError("MessageNotFound", f"No dead-lettered message with sequence number '{seq}'.", 404)
    topic["dead_letter"] = [m for m in dl if str(m["SequenceNumber"]) != str(seq)]
    store.persist()
    return _empty(200)


# ── REST dispatch router ────────────────────────────────────────────────────
def dispatch(store: MessagingStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", arm_state: dict | None = None) -> ServiceBusResponse:
    """Native Azure Service Bus REST router. With `arm_state` and an `x-vyomi-namespace` header the namespace's
    networkRuleSets/default (public access, IP rules, VNet rules + Microsoft.ServiceBus endpoint, trusted services,
    private endpoint) is ENFORCED against the declared caller (core/azure_netaccess.py). Paths:
        PUT    /{topic}                                        create topic
        GET    /{topic}                                        get topic
        DELETE /{topic}                                        delete topic
        PUT    /{topic}/subscriptions/{sub}                    create subscription
        DELETE /{topic}/subscriptions/{sub}                    delete subscription
        POST   /{topic}/messages                               send (fan-out + own backlog)
        GET    /{topic}/messages                               batch peek, own backlog (console)
        DELETE /{topic}/messages?max=N                         batch receive-and-delete (console)
        POST   /{topic}/messages/{seq}/complete                remove a message (console)
        POST   /{topic}/messages/{seq}/defer                   defer a message (console)
        POST   /{topic}/messages/{seq}/deadletter               move to $deadletterqueue (console)
        GET    /{topic}/$deadletterqueue/messages              batch peek dead-letter (console)
        POST   /{topic}/$deadletterqueue/messages/{seq}/complete  remove dead-lettered (console)
        DELETE /{topic}/subscriptions/{sub}/messages/head      receive-and-delete
        POST   /{topic}/subscriptions/{sub}/messages/head      peek-lock
        DELETE /{topic}/subscriptions/{sub}/messages/{seq}/{lock}  complete (lock)
        PUT    /{topic}/subscriptions/{sub}/messages/{seq}/{lock}  abandon (unlock)
    """
    method = (method or "GET").upper()
    query = query or {}
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    p = path.split("?", 1)[0].strip("/")
    segs = [s for s in p.split("/") if s != ""]
    if not segs:
        return _error("BadRequest", "Missing entity path.", 400)
    if arm_state and headers.get("x-vyomi-namespace"):
        try:
            from core import azure_netaccess as _na
        except ImportError:  # pragma: no cover - Pyodide flat layout
            import azure_netaccess as _na  # type: ignore
        _d = _na.servicebus_denied(arm_state, headers["x-vyomi-namespace"], headers, query)
        if _d:
            return _error("Forbidden", _d[2], 403)
        try:        # diagnostic settings (RuntimeAuditLogs) on the namespace: real delivery (core/azure_diag_pipeline.py)
            from core import azure_diag_pipeline as _dp
            _dp.emit_named(arm_state, "microsoft.servicebus/namespaces", f"namespaces/{headers['x-vyomi-namespace']}", "RuntimeAuditLogs",
                           f"{method} /{p}", 200)
        except Exception:
            pass

    topic = segs[0]
    try:
        # topic-level: /{topic}
        if len(segs) == 1:
            if method == "PUT":
                return _create_topic(store, topic, body)
            if method == "GET":
                return _get_topic(store, topic)
            if method == "DELETE":
                return _delete_topic(store, topic)
            return _error("BadRequest", f"Unsupported method {method} on topic.", 400)

        # dead-letter sub-queue (console): /{topic}/$deadletterqueue/messages[/{seq}/complete]
        if len(segs) >= 3 and segs[1] == "$deadletterqueue" and segs[2] == "messages":
            if len(segs) == 3 and method == "GET":
                return _peek_deadletter(store, topic)
            if len(segs) == 5 and segs[4] == "complete" and method == "POST":
                return _complete_deadletter(store, topic, segs[3])
            return _error("BadRequest", f"Unsupported dead-letter operation {method} {path}.", 400)

        # send / batch peek / batch receive: /{topic}/messages
        if len(segs) == 2 and segs[1] == "messages":
            if method == "POST":
                return _send(store, topic, body, headers)
            if method == "GET":
                return _peek_batch(store, topic)
            if method == "DELETE":
                return _receive_batch(store, topic, int(query.get("max") or 32))
            return _error("BadRequest", f"Unsupported method {method} on messages.", 400)

        # per-message action by sequence number (console): /{topic}/messages/{seq}/{action}
        if len(segs) == 4 and segs[1] == "messages" and segs[3] in ("complete", "defer", "deadletter") and method == "POST":
            action, seq = segs[3], segs[2]
            if action == "complete":
                return _complete_own(store, topic, seq)
            if action == "defer":
                return _defer_own(store, topic, seq)
            return _deadletter_own(store, topic, seq, body)

        # subscription-scoped: /{topic}/subscriptions/{sub}[...]
        if len(segs) >= 3 and segs[1].lower() == "subscriptions":
            sub = segs[2]

            # /{topic}/subscriptions/{sub}
            if len(segs) == 3:
                if method == "PUT":
                    return _create_subscription(store, topic, sub, body)
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


# ── customer-managed key: message bodies are ENVELOPE-ENCRYPTED at rest (core/azure_cmk_core.py) ─────────────
# A Premium namespace with encryption.keyVaultProperties[0] {keyVaultUri, keyName[, keyVersion]} has every message
# body (queue/topic backlogs, subscription copies, dead-letter) replaced by a placeholder between requests; the real
# bodies live only inside one CMK envelope (`store._sb_sealed`, DEK wrapped by the Key Vault key). A request opens the
# envelope (Key Vault unwrapKey), serves, and re-seals under the key's latest version. A disabled / deleted / expired key
# => 403 MessagingGatewayKeyInaccessible and the bodies stay unreadable. The simulator has ONE message store shared by
# all namespaces (the data wire carries no namespace), so the sealed unit is the whole store, driven by the namespace the
# request resolves to (x-vyomi-namespace header, `<ns>.servicebus.windows.net` host, or the only CMK namespace).
def cmk_namespace(arm_state, headers):
    nss = [r for r in (arm_state or {}).values()
           if str(r.get("_type") or r.get("type") or "").lower() == "microsoft.servicebus/namespaces"]
    hd = {(k or "").lower(): v for k, v in (headers or {}).items()}
    want = str(hd.get("x-vyomi-namespace") or "").lower()
    if not want:
        host = str(hd.get("host") or "").split(":")[0].lower()
        if host.endswith(".servicebus.windows.net"):
            want = host.split(".")[0]
    if want:
        nss = [r for r in nss if (r.get("name") or "").lower() == want]
    with_key = [r for r in nss if cmk_key_uri(r)]
    return with_key[0] if len(with_key) == 1 else None


def cmk_key_uri(ns_rec):
    kvp = (((ns_rec or {}).get("properties") or {}).get("encryption") or {}).get("keyVaultProperties") or []
    if not kvp or not kvp[0].get("keyName"):
        return None
    k = kvp[0]
    return f"{str(k.get('keyVaultUri') or '').rstrip('/')}/keys/{k['keyName']}" + (f"/{k['keyVersion']}" if k.get("keyVersion") else "")


def _all_messages(store):
    for t in getattr(store, "topics", {}).values():
        for m in t.get("messages", []):
            yield m
        for m in t.get("dead_letter", []):
            yield m
        for s in t.get("subscriptions", {}).values():
            for m in s.get("messages", []):
                yield m
            for m in s.get("dead_letter", []):
                yield m


class CmkScope:
    def __init__(self, store, ns_rec, kv_store=None):
        self.store, self.ns, self.kv = store, ns_rec, kv_store

    def __enter__(self):
        from core import azure_cmk_core as cmk
        self.cmk = cmk
        self.kv = cmk.keys(self.kv)
        self.uri = cmk_key_uri(self.ns) if self.ns else None
        self.active = self.kv is not None and (self.uri is not None or getattr(self.store, "_sb_sealed", None) is not None)
        if not self.active:
            return self
        cmk.LOCK.acquire()
        self.locked = True
        try:
            return self._enter(cmk)
        except BaseException:
            self.active = False
            self.locked = False
            cmk.LOCK.release()
            raise

    def _enter(self, cmk):
        if self.uri:
            ok, why = cmk.usable(self.kv, self.uri)
            if not ok:
                self.active = False
                raise ServiceBusError("MessagingGatewayKeyInaccessible",
                                      f"The namespace's customer-managed key cannot be used ({why}); message data is unreadable.", 403)
        env = getattr(self.store, "_sb_sealed", None)
        if env is not None:
            if not self.uri:        # request did not resolve to the CMK namespace: still re-seal under the envelope's key
                self.uri = "https://vault.vault.azure.net/keys/" + env["keyName"]
            try:
                bodies = json.loads(cmk.unseal(self.kv, env).decode())
            except cmk.CmkError as e:
                self.active = False
                raise ServiceBusError("MessagingGatewayKeyInaccessible", e.message, 403)
            import base64
            for m in _all_messages(self.store):
                if m.get("_sealed") and m["_id"] in bodies:
                    m["body"] = base64.b64decode(bodies[m["_id"]])
                    del m["_sealed"]
                    if ("w:" + m["_id"]) in bodies:        # the AMQP wire image of the message is sealed with the body
                        m["_wire"] = base64.b64decode(bodies["w:" + m["_id"]])
            self.store._sb_sealed = None
        return self

    def __exit__(self, *exc):
        try:
            return self._exit()
        finally:
            if getattr(self, "locked", False):
                self.locked = False
                self.cmk.LOCK.release()

    def _exit(self):
        if not self.active:
            return False
        import base64
        if not self.uri:
            return False
        bodies = {}
        for m in _all_messages(self.store):
            if isinstance(m.get("body"), (bytes, bytearray)):
                bodies[m["_id"]] = base64.b64encode(bytes(m["body"])).decode()
                if m.get("_wire"):
                    bodies["w:" + m["_id"]] = base64.b64encode(bytes(m["_wire"])).decode()
        try:
            env = self.cmk.seal(self.kv, self.uri, json.dumps(bodies).encode())
        except self.cmk.CmkError:
            return False
        for m in _all_messages(self.store):
            if m["_id"] in bodies:
                m["body"] = b""
                m["_sealed"] = True
                if "w:" + m["_id"] in bodies:
                    m["_wire"] = b""
        self.store._sb_sealed = env
        try:
            self.store.persist()          # persist AFTER sealing so a backed store never keeps the plaintext
        except Exception:
            pass
        return False


def rotate_cmk(store, ns_rec, kv_store=None):
    """Re-wrap the envelope's DEK under the namespace key's latest version (key rotation); bodies are not re-encrypted."""
    from core import azure_cmk_core as cmk
    kv = cmk.keys(kv_store)
    env = getattr(store, "_sb_sealed", None)
    if env is not None and kv is not None:
        store._sb_sealed = cmk.rewrap(kv, env, cmk_key_uri(ns_rec))
    return getattr(store, "_sb_sealed", None)
