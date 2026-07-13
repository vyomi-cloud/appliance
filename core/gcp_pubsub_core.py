"""GCP Pub/Sub core — substrate-independent in-memory eventing, the GCP analogue
of core/sns_core.py + core/sqs_core.py fused into one service. Speaks the native
**Pub/Sub REST API v1** (`https://pubsub.googleapis.com/v1/`, `projects/{p}/...`
resource names, JSON bodies, google.rpc-style errors) so the native
`google-cloud-pubsub` client (REST transport) works unchanged against it.

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide.
Persists through the SAME MessagingStore seam as SNS/SQS (core/messaging_store.py):
topics live in `store.topics`, subscriptions (each with its own message backlog)
live in `store.queues` — so Pub/Sub covers BOTH the SNS topic-fanout half and the
SQS-style pull-and-ack half in a single service. Publishing to a topic fans a
message out to every subscription attached to that topic.

Scope (v1 slice): create/get/list/delete topic, create/get/list/delete
subscription, publish (base64 data + attributes → messageIds), pull (returns
receivedMessages with ackIds), acknowledge (removes acked messages). Push
delivery, ack deadlines / modifyAckDeadline, seek, and ordering keys reuse the
same helpers and slot in next.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.messaging_store import MessagingStore


@dataclass
class PubsubResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


# ── primitives ────────────────────────────────────────────────────────────
def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _next_message_id(store) -> str:
    seq = getattr(store, "_pubsub_msg_seq", 0) + 1
    store._pubsub_msg_seq = seq
    return str(seq)


def _json(status: int, obj: dict) -> PubsubResponse:
    return PubsubResponse(status=status, body=json.dumps(obj).encode())


def _err(code: int, status: str, message: str) -> PubsubResponse:
    body = {"error": {"code": code, "message": message, "status": status}}
    return PubsubResponse(status=code, body=json.dumps(body).encode())


class PubsubError(Exception):
    def __init__(self, code: int, status: str, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.code = code
        self.status = status
        self.message = message


# ── resource views ────────────────────────────────────────────────────────
def _topic_view(topic: dict) -> dict:
    return {"name": topic["name"]}


def _subscription_view(sub: dict) -> dict:
    return {
        "name": sub["name"],
        "topic": sub["topic"],
        "pushConfig": {},
        "ackDeadlineSeconds": sub.get("ackDeadlineSeconds", 10),
        "messageRetentionDuration": "604800s",
    }


def _require_topic(store, name: str) -> dict:
    t = store.get_topic(name)
    if not t:
        raise PubsubError(404, "NOT_FOUND", f"Topic not found: {name}")
    return t


def _require_subscription(store, name: str) -> dict:
    s = store.get_queue(name)
    if not s:
        raise PubsubError(404, "NOT_FOUND", f"Subscription not found: {name}")
    return s


# ── topic operations ──────────────────────────────────────────────────────
def _create_topic(store, name: str, body: dict) -> PubsubResponse:
    if store.get_topic(name):
        raise PubsubError(409, "ALREADY_EXISTS", f"Topic already exists: {name}")
    store.put_topic(name, {"name": name, "subscriptions": [], "created": _now_rfc3339()})
    store.persist()
    return _json(200, _topic_view(store.get_topic(name)))


def _get_topic(store, name: str) -> PubsubResponse:
    return _json(200, _topic_view(_require_topic(store, name)))


def _list_topics(store, project: str) -> PubsubResponse:
    prefix = f"projects/{project}/topics/"
    items = [_topic_view(store.get_topic(n)) for n in store.topic_arns()
             if n.startswith(prefix)]
    out: dict = {}
    if items:
        out["topics"] = items
    return _json(200, out)


def _delete_topic(store, name: str) -> PubsubResponse:
    topic = _require_topic(store, name)
    # Detach subscriptions (Pub/Sub keeps them but marks topic _deleted-topic_).
    for sub_name in topic.get("subscriptions", []):
        sub = store.get_queue(sub_name)
        if sub:
            sub["topic"] = "_deleted-topic_"
    store.drop_topic(name)
    store.persist()
    return _json(200, {})


def _publish(store, name: str, body: dict) -> PubsubResponse:
    topic = _require_topic(store, name)
    messages = body.get("messages") or []
    if not messages:
        raise PubsubError(400, "INVALID_ARGUMENT",
                          "The value for message_count is too small. You passed 0")
    message_ids: list[str] = []
    for m in messages:
        mid = _next_message_id(store)
        message_ids.append(mid)
        record = {
            "data": m.get("data", ""),            # already base64 on the wire
            "attributes": dict(m.get("attributes") or {}),
            "messageId": mid,
            "publishTime": _now_rfc3339(),
        }
        # Fan out: an independent copy per subscription backlog.
        for sub_name in topic.get("subscriptions", []):
            sub = store.get_queue(sub_name)
            if sub is None:
                continue
            sub.setdefault("messages", []).append({"_id": uuid.uuid4().hex, **record})
    store.persist()
    return _json(200, {"messageIds": message_ids})


# ── subscription operations ───────────────────────────────────────────────
def _create_subscription(store, name: str, body: dict) -> PubsubResponse:
    if store.get_queue(name):
        raise PubsubError(409, "ALREADY_EXISTS", f"Subscription already exists: {name}")
    topic_name = str(body.get("topic", "")).strip()
    if not topic_name:
        raise PubsubError(400, "INVALID_ARGUMENT", "Subscription must specify a topic.")
    topic = _require_topic(store, topic_name)
    sub = {
        "name": name,
        "topic": topic_name,
        "ackDeadlineSeconds": int(body.get("ackDeadlineSeconds", 10) or 10),
        "messages": [],
        "ackids": {},
        "created": _now_rfc3339(),
    }
    store.put_queue(name, sub)
    if name not in topic["subscriptions"]:
        topic["subscriptions"].append(name)
    store.persist()
    return _json(200, _subscription_view(sub))


def _get_subscription(store, name: str) -> PubsubResponse:
    return _json(200, _subscription_view(_require_subscription(store, name)))


def _list_subscriptions(store, project: str) -> PubsubResponse:
    prefix = f"projects/{project}/subscriptions/"
    items = [_subscription_view(store.get_queue(n)) for n in store.queue_names()
             if n.startswith(prefix)]
    out: dict = {}
    if items:
        out["subscriptions"] = items
    return _json(200, out)


def _delete_subscription(store, name: str) -> PubsubResponse:
    sub = _require_subscription(store, name)
    topic = store.get_topic(sub.get("topic", ""))
    if topic and name in topic.get("subscriptions", []):
        topic["subscriptions"].remove(name)
    store.drop_queue(name)
    store.persist()
    return _json(200, {})


def _pull(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    max_messages = int(body.get("maxMessages", 1) or 1)
    received = []
    for msg in sub.get("messages", []):
        if len(received) >= max_messages:
            break
        if msg.get("_pending"):
            continue  # already handed out and awaiting ack this round
        ack_id = "ackid-" + uuid.uuid4().hex
        msg["_pending"] = True
        sub.setdefault("ackids", {})[ack_id] = msg["_id"]
        received.append({
            "ackId": ack_id,
            "message": {
                "data": msg["data"],
                "attributes": msg["attributes"],
                "messageId": msg["messageId"],
                "publishTime": msg["publishTime"],
            },
        })
    out: dict = {}
    if received:
        out["receivedMessages"] = received
        store.persist()
    return _json(200, out)


def _acknowledge(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    ack_ids = body.get("ackIds") or []
    ackids = sub.setdefault("ackids", {})
    remove = {ackids.pop(a) for a in ack_ids if a in ackids}
    if remove:
        sub["messages"] = [m for m in sub.get("messages", []) if m["_id"] not in remove]
        store.persist()
    return _json(200, {})


# ── dispatch ──────────────────────────────────────────────────────────────
def dispatch(store: MessagingStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> PubsubResponse:
    """Native GCP Pub/Sub REST v1 router. Resource names are `projects/{p}/...`;
    verbs (`:publish`, `:pull`, `:acknowledge`) are `:`-suffixed on the path."""
    method = (method or "GET").upper()

    # Strip a leading /v1 prefix and any query string.
    p = path.split("?", 1)[0]
    if p.startswith("/v1/"):
        p = p[len("/v1"):]
    elif p == "/v1":
        p = "/"
    p = p.strip("/")

    # Split a trailing `:verb` (e.g. projects/p/topics/t:publish) off the resource.
    verb = ""
    if ":" in p:
        p, _, verb = p.rpartition(":")

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}

    segs = [s for s in p.split("/") if s != ""]
    # Expect: projects / {project} / (topics|subscriptions) [ / {id...} ]
    if len(segs) < 3 or segs[0] != "projects":
        return _err(404, "NOT_FOUND", f"Unknown path: {path}")
    project = segs[1]
    collection = segs[2]
    resource = p  # full resource name for a specific topic/subscription

    try:
        if collection == "topics":
            if len(segs) == 3:                       # collection
                if method == "GET":
                    return _list_topics(store, project)
                return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on topics")
            # specific topic
            if verb == "publish" and method == "POST":
                return _publish(store, resource, payload)
            if method == "PUT":
                return _create_topic(store, resource, payload)
            if method == "GET":
                return _get_topic(store, resource)
            if method == "DELETE":
                return _delete_topic(store, resource)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on topic")

        if collection == "subscriptions":
            if len(segs) == 3:                       # collection
                if method == "GET":
                    return _list_subscriptions(store, project)
                return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on subscriptions")
            # specific subscription
            if verb == "pull" and method == "POST":
                return _pull(store, resource, payload)
            if verb == "acknowledge" and method == "POST":
                return _acknowledge(store, resource, payload)
            if method == "PUT":
                return _create_subscription(store, resource, payload)
            if method == "GET":
                return _get_subscription(store, resource)
            if method == "DELETE":
                return _delete_subscription(store, resource)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on subscription")

        return _err(404, "NOT_FOUND", f"Unknown collection: {collection}")
    except PubsubError as e:
        return _err(e.code, e.status, e.message)
