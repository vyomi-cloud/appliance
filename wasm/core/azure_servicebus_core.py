# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure Service Bus (topics) core — the Azure peer of core/sns_core.py (AWS SNS)
and core/gcp_pubsub_core.py (GCP Pub/Sub). Closes the cross-cloud pub/sub-fan-out
symmetry gap: AWS + GCP had a topic→subscription fan-out service; Azure did not
(azure-storage-queue is a point-to-point queue, not pub/sub).

Speaks the native **Service Bus REST API** (`https://{ns}.servicebus.windows.net/`,
resource paths, HTTP verbs, `BrokerProperties` JSON header) — the protocol an HTTP
Service Bus client speaks, so it survives the relay (unlike the AMQP transport the
azure-servicebus Python SDK defaults to, which can't cross an HTTP boundary — that
path stays AMQP-only and is out of scope here). NO fastapi / azure-sdk / socket
imports → loads under Pyodide. Persists through the SAME MessagingStore seam as
SNS/SQS/Pub-Sub (core/messaging_store.py): topics live in `store.topics`, each with
a nested `subscriptions` map whose entries hold an independent message backlog.

Model: a message SENT to a topic fans out an independent copy into every
subscription's backlog (the canonical topic model). A receiver pulls from a SPECIFIC
subscription — receive-and-delete (DELETE …/messages/head) pops the head; peek-lock
(POST …/messages/head) hands out the head under a lock token, DELETE …/messages/{seq}/{lock}
completes (removes) it, PUT unlocks (abandon).

Scope (v1 slice): create/get/delete topic, create/get/delete subscription, send
(fan-out), receive-and-delete, peek-lock + complete/abandon. Sessions, dead-letter,
SQL filter rules, and scheduled messages reuse the same helpers and slot in next.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.messaging_store import MessagingStore


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_seq(store) -> int:
    seq = getattr(store, "_sb_seq", 0) + 1
    store._sb_seq = seq
    return seq


def _empty(status: int, headers: dict | None = None) -> ServiceBusResponse:
    return ServiceBusResponse(status=status, headers=headers or {}, media_type=None)


def _error(code: str, message: str, status: int = 400) -> ServiceBusResponse:
    # Service Bus REST errors are an Atom/XML-ish envelope; a JSON body with the
    # code/detail is sufficient for the conformance wire and human-readable.
    body = json.dumps({"code": status, "detail": message}).encode()
    return ServiceBusResponse(status=status, body=body)


# ── topic / subscription accessors (over the MessagingStore.topics seam) ─────
def _require_topic(store, name: str) -> dict:
    t = store.get_topic(name)
    if not t:
        raise ServiceBusError("MessagingEntityNotFound",
                              f"The messaging entity '{name}' could not be found.", 404)
    return t


def _require_subscription(topic: dict, sub_name: str) -> dict:
    sub = topic.get("subscriptions", {}).get(sub_name)
    if not sub:
        raise ServiceBusError("MessagingEntityNotFound",
                              f"The subscription '{sub_name}' could not be found.", 404)
    return sub


# ── topic operations ────────────────────────────────────────────────────────
def _create_topic(store, name: str) -> ServiceBusResponse:
    if not store.get_topic(name):
        store.put_topic(name, {"name": name, "subscriptions": {}, "created": _now_iso()})
        store.persist()
    return _empty(201)


def _get_topic(store, name: str) -> ServiceBusResponse:
    _require_topic(store, name)
    return _empty(200)


def _delete_topic(store, name: str) -> ServiceBusResponse:
    _require_topic(store, name)
    store.drop_topic(name)
    store.persist()
    return _empty(200)


def _create_subscription(store, topic_name: str, sub_name: str) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    subs = topic.setdefault("subscriptions", {})
    if sub_name not in subs:
        subs[sub_name] = {"name": sub_name, "messages": [], "created": _now_iso()}
        store.persist()
    return _empty(201)


def _delete_subscription(store, topic_name: str, sub_name: str) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    _require_subscription(topic, sub_name)
    topic["subscriptions"].pop(sub_name, None)
    store.persist()
    return _empty(200)


# ── send (fan-out) ──────────────────────────────────────────────────────────
def _broker_props(headers: dict) -> dict:
    raw = headers.get("brokerproperties") or headers.get("BrokerProperties") or ""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _send(store, topic_name: str, body: bytes, headers: dict) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    props = _broker_props(headers)
    message_id = str(props.get("MessageId") or uuid.uuid4())
    content_type = headers.get("content-type", "application/octet-stream")
    # Fan out an INDEPENDENT copy into every subscription backlog.
    for sub in topic.get("subscriptions", {}).values():
        seq = _next_seq(store)
        sub.setdefault("messages", []).append({
            "_id": uuid.uuid4().hex,
            "SequenceNumber": seq,
            "MessageId": message_id,
            "body": body,
            "content_type": content_type,
            "properties": {k: v for k, v in props.items() if k != "MessageId"},
            "EnqueuedTimeUtc": _now_iso(),
            "_locked": None,
        })
    store.persist()
    return _empty(201)


# ── receive ─────────────────────────────────────────────────────────────────
def _msg_response(msg: dict, lock_token: str | None = None) -> ServiceBusResponse:
    bp = {"MessageId": msg["MessageId"], "SequenceNumber": msg["SequenceNumber"],
          "EnqueuedTimeUtc": msg["EnqueuedTimeUtc"]}
    if lock_token:
        bp["LockToken"] = lock_token
    headers = {"BrokerProperties": json.dumps(bp)}
    for k, v in (msg.get("properties") or {}).items():
        headers[str(k)] = str(v)
    return ServiceBusResponse(status=200, body=msg["body"], headers=headers,
                              media_type=msg.get("content_type", "application/octet-stream"))


def _head_message(sub: dict):
    """The first message not currently locked, or None."""
    for m in sub.get("messages", []):
        if not m.get("_locked"):
            return m
    return None


def _receive_and_delete(store, topic_name: str, sub_name: str) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    msg = _head_message(sub)
    if msg is None:
        return _empty(204)   # empty subscription — no message available
    sub["messages"] = [m for m in sub["messages"] if m["_id"] != msg["_id"]]
    store.persist()
    return _msg_response(msg)


def _peek_lock(store, topic_name: str, sub_name: str) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    msg = _head_message(sub)
    if msg is None:
        return _empty(204)
    lock_token = str(uuid.uuid4())
    msg["_locked"] = lock_token
    store.persist()
    return _msg_response(msg, lock_token=lock_token)


def _complete(store, topic_name: str, sub_name: str, seq: str, lock: str) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    before = len(sub.get("messages", []))
    sub["messages"] = [m for m in sub.get("messages", [])
                       if not (str(m["SequenceNumber"]) == str(seq) and m.get("_locked") == lock)]
    if len(sub["messages"]) == before:
        raise ServiceBusError("MessageLockLost",
                              "The lock supplied is invalid or has expired.", 410)
    store.persist()
    return _empty(200)


def _abandon(store, topic_name: str, sub_name: str, seq: str, lock: str) -> ServiceBusResponse:
    topic = _require_topic(store, topic_name)
    sub = _require_subscription(topic, sub_name)
    for m in sub.get("messages", []):
        if str(m["SequenceNumber"]) == str(seq) and m.get("_locked") == lock:
            m["_locked"] = None
            store.persist()
            return _empty(200)
    raise ServiceBusError("MessageLockLost",
                          "The lock supplied is invalid or has expired.", 410)


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: MessagingStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> ServiceBusResponse:
    """Native Azure Service Bus REST router. Paths:
        PUT    /{topic}                                        create topic
        GET    /{topic}                                        get topic
        DELETE /{topic}                                        delete topic
        PUT    /{topic}/subscriptions/{sub}                    create subscription
        DELETE /{topic}/subscriptions/{sub}                    delete subscription
        POST   /{topic}/messages                               send (fan-out)
        DELETE /{topic}/subscriptions/{sub}/messages/head      receive-and-delete
        POST   /{topic}/subscriptions/{sub}/messages/head      peek-lock
        DELETE /{topic}/subscriptions/{sub}/messages/{seq}/{lock}  complete (lock)
        PUT    /{topic}/subscriptions/{sub}/messages/{seq}/{lock}  abandon (unlock)
    """
    method = (method or "GET").upper()
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    p = path.split("?", 1)[0].strip("/")
    segs = [s for s in p.split("/") if s != ""]
    if not segs:
        return _error("BadRequest", "Missing entity path.", 400)

    topic = segs[0]
    try:
        # topic-level
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
        if len(segs) >= 3 and segs[1] == "subscriptions":
            sub = segs[2]
            if len(segs) == 3:
                if method == "PUT":
                    return _create_subscription(store, topic, sub)
                if method == "DELETE":
                    return _delete_subscription(store, topic, sub)
                if method == "GET":
                    _require_subscription(_require_topic(store, topic), sub)
                    return _empty(200)
                return _error("BadRequest", f"Unsupported method {method} on subscription.", 400)

            # /{topic}/subscriptions/{sub}/messages/...
            if segs[3] == "messages":
                # head: receive-and-delete (DELETE) or peek-lock (POST)
                if len(segs) == 5 and segs[4] == "head":
                    if method == "DELETE":
                        return _receive_and_delete(store, topic, sub)
                    if method == "POST":
                        return _peek_lock(store, topic, sub)
                # /messages/{seq}/{lock}: complete (DELETE) / abandon (PUT)
                if len(segs) == 6:
                    seq, lock = segs[4], segs[5]
                    if method == "DELETE":
                        return _complete(store, topic, sub, seq, lock)
                    if method == "PUT":
                        return _abandon(store, topic, sub, seq, lock)
                return _error("BadRequest", f"Unsupported message operation {method} {path}.", 400)

        return _error("BadRequest", f"Unknown Service Bus path: {path}", 404)
    except ServiceBusError as e:
        return _error(e.code, e.message, e.status)
