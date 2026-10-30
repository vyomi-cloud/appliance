# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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
message out to every subscription attached to that topic. Snapshots and schemas
(resources the SNS/SQS seam has no shape for) live in `store.pubsub`.

Scope: create/get/list/delete/patch topic (labels, CMEK, message retention,
schema settings), create/get/list/delete/patch subscription (labels, retention
+ retain-acked, expiration policy, message ordering + exactly-once flags, push
config, dead-letter policy, retry policy), publish (base64 data + attributes +
ordering key → messageIds), pull (ack-deadline-based redelivery, dead-letter
forwarding past maxDeliveryAttempts, retention pruning), acknowledge, seek (to a
snapshot), and snapshot / schema create+get+list+delete. Push delivery is
recorded but never actually dispatched over the network (see capability
registry); BigQuery/Cloud Storage subscriptions and the CEL filter language are
not modeled at all.
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


def _expires_rfc3339(seconds_from_now: float) -> str:
    return datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + seconds_from_now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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


def _snap_store(store) -> dict:
    return store.pubsub.setdefault("snapshots", {})


def _schema_store(store) -> dict:
    return store.pubsub.setdefault("schemas", {})


# ── resource views ────────────────────────────────────────────────────────
def _topic_view(topic: dict) -> dict:
    v: dict = {"name": topic["name"]}
    if topic.get("labels"):
        v["labels"] = topic["labels"]
    if topic.get("kmsKeyName"):
        v["kmsKeyName"] = topic["kmsKeyName"]
    if topic.get("messageRetentionDuration"):
        v["messageRetentionDuration"] = topic["messageRetentionDuration"]
    if topic.get("schemaSettings"):
        v["schemaSettings"] = topic["schemaSettings"]
    return v


def _subscription_view(sub: dict) -> dict:
    v = {
        "name": sub["name"],
        "topic": sub["topic"],
        "pushConfig": sub.get("pushConfig") or {},
        "ackDeadlineSeconds": sub.get("ackDeadlineSeconds", 10),
        "messageRetentionDuration": sub.get("messageRetentionDuration", "604800s"),
        "expirationPolicy": sub.get("expirationPolicy", {"ttl": "2678400s"}),
    }
    if sub.get("labels"):
        v["labels"] = sub["labels"]
    if sub.get("retainAckedMessages"):
        v["retainAckedMessages"] = True
    if sub.get("enableMessageOrdering"):
        v["enableMessageOrdering"] = True
    if sub.get("enableExactlyOnceDelivery"):
        v["enableExactlyOnceDelivery"] = True
    if sub.get("deadLetterPolicy"):
        v["deadLetterPolicy"] = sub["deadLetterPolicy"]
    if sub.get("retryPolicy"):
        v["retryPolicy"] = sub["retryPolicy"]
    return v


def _snapshot_view(snap: dict) -> dict:
    v = {"name": snap["name"], "topic": snap["topic"], "expireTime": snap["expireTime"],
         # `subscription` is beyond the real Snapshot resource shape (kept for the console's
         # "Subscription" column); real SDKs ignore unknown JSON fields.
         "subscription": snap.get("subscription", "")}
    if snap.get("labels"):
        v["labels"] = snap["labels"]
    return v


def _schema_view(schema: dict, full: bool = False) -> dict:
    v = {"name": schema["name"], "type": schema.get("type", "TYPE_UNSPECIFIED"),
         "revisionId": schema.get("revisionId", ""), "revisionCreateTime": schema.get("revisionCreateTime", "")}
    if full:
        v["definition"] = schema.get("definition", "")
    return v


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
    topic = {"name": name, "subscriptions": [], "created": _now_rfc3339(), "labels": dict(body.get("labels") or {})}
    if body.get("kmsKeyName"):
        topic["kmsKeyName"] = body["kmsKeyName"]
    if body.get("messageRetentionDuration"):
        topic["messageRetentionDuration"] = body["messageRetentionDuration"]
    if body.get("schemaSettings"):
        topic["schemaSettings"] = body["schemaSettings"]
    store.put_topic(name, topic)
    store.persist()
    return _json(200, _topic_view(store.get_topic(name)))


def _get_topic(store, name: str) -> PubsubResponse:
    return _json(200, _topic_view(_require_topic(store, name)))


_TOPIC_PATCHABLE = {"labels", "kmsKeyName", "messageRetentionDuration", "schemaSettings"}


def _patch_topic(store, name: str, body: dict) -> PubsubResponse:
    topic = _require_topic(store, name)
    fields = body.get("topic") or body
    mask = [f.strip() for f in str(body.get("updateMask", "")).split(",") if f.strip()]
    keys = mask if mask else [k for k in fields if k in _TOPIC_PATCHABLE]
    for k in keys:
        if k not in _TOPIC_PATCHABLE:
            continue
        if k in fields:
            topic[k] = fields[k]
        else:
            topic.pop(k, None)
    store.persist()
    return _json(200, _topic_view(topic))


def _list_topics(store, project: str) -> PubsubResponse:
    prefix = f"projects/{project}/topics/"
    items = [_topic_view(store.get_topic(n)) for n in store.topic_arns() if n.startswith(prefix)]
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


def _fanout(store, topic: dict, record: dict) -> None:
    """Deliver a prepared message record into every subscription attached to `topic`."""
    for sub_name in topic.get("subscriptions", []):
        sub = store.get_queue(sub_name)
        if sub is None:
            continue
        sub.setdefault("messages", []).append({"_id": uuid.uuid4().hex, "_publish_at": store.now(), **record})


def _publish(store, name: str, body: dict) -> PubsubResponse:
    topic = _require_topic(store, name)
    messages = body.get("messages") or []
    if not messages:
        raise PubsubError(400, "INVALID_ARGUMENT", "The value for message_count is too small. You passed 0")
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
        if m.get("orderingKey"):
            record["orderingKey"] = m["orderingKey"]
        _fanout(store, topic, record)
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
        "labels": dict(body.get("labels") or {}),
        "messageRetentionDuration": body.get("messageRetentionDuration", "604800s"),
        "retainAckedMessages": bool(body.get("retainAckedMessages", False)),
        "expirationPolicy": body.get("expirationPolicy", {"ttl": "2678400s"}),
        "enableMessageOrdering": bool(body.get("enableMessageOrdering", False)),
        "enableExactlyOnceDelivery": bool(body.get("enableExactlyOnceDelivery", False)),
        "pushConfig": body.get("pushConfig") or {},
    }
    if body.get("deadLetterPolicy"):
        sub["deadLetterPolicy"] = body["deadLetterPolicy"]
    if body.get("retryPolicy"):
        sub["retryPolicy"] = body["retryPolicy"]
    store.put_queue(name, sub)
    if name not in topic["subscriptions"]:
        topic["subscriptions"].append(name)
    store.persist()
    return _json(200, _subscription_view(sub))


def _get_subscription(store, name: str) -> PubsubResponse:
    return _json(200, _subscription_view(_require_subscription(store, name)))


_SUB_PATCHABLE = {
    "labels", "ackDeadlineSeconds", "messageRetentionDuration", "retainAckedMessages",
    "expirationPolicy", "enableMessageOrdering", "pushConfig", "deadLetterPolicy", "retryPolicy",
}


def _patch_subscription(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    fields = body.get("subscription") or body
    mask = [f.strip() for f in str(body.get("updateMask", "")).split(",") if f.strip()]
    keys = mask if mask else [k for k in fields if k in _SUB_PATCHABLE]
    for k in keys:
        if k not in _SUB_PATCHABLE:
            continue
        if k in fields:
            sub[k] = fields[k]
        else:
            sub.pop(k, None)
    store.persist()
    return _json(200, _subscription_view(sub))


def _list_subscriptions(store, project: str) -> PubsubResponse:
    prefix = f"projects/{project}/subscriptions/"
    items = [_subscription_view(store.get_queue(n)) for n in store.queue_names() if n.startswith(prefix)]
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


def _prune_retention(store, sub: dict) -> None:
    try:
        retention = int(str(sub.get("messageRetentionDuration", "604800s")).rstrip("s"))
    except ValueError:
        retention = 604800
    now = store.now()
    sub["messages"] = [m for m in sub.get("messages", []) if now - m.get("_publish_at", now) <= retention]


def _pull(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    _prune_retention(store, sub)
    max_messages = int(body.get("maxMessages", 1) or 1)
    deadline = int(sub.get("ackDeadlineSeconds", 10) or 10)
    dlp = sub.get("deadLetterPolicy")
    now = store.now()
    kept: list[dict] = []
    received: list[dict] = []
    for msg in sub.get("messages", []):
        if msg.get("_acked"):
            kept.append(msg)
            continue
        if msg.get("_pending") and now < msg.get("_pending_until", 0):
            kept.append(msg)   # still out for delivery, within its ack deadline
            continue
        if len(received) >= max_messages:
            kept.append(msg)   # eligible, but this pull's quota is already full
            continue
        attempts = msg.get("_attempts", 0) + 1
        if dlp and attempts > int(dlp.get("maxDeliveryAttempts", 5) or 5):
            dlq = store.get_topic(dlp.get("deadLetterTopic", ""))
            if dlq:
                fwd = {"data": msg["data"], "attributes": dict(msg.get("attributes") or {}),
                       "messageId": _next_message_id(store), "publishTime": _now_rfc3339()}
                _fanout(store, dlq, fwd)
            continue   # exceeded max delivery attempts: forwarded (or dropped), never kept
        msg["_attempts"] = attempts
        msg["_pending"] = True
        msg["_pending_until"] = now + deadline
        ack_id = "ackid-" + uuid.uuid4().hex
        sub.setdefault("ackids", {})[ack_id] = msg["_id"]
        out_msg = {"data": msg["data"], "attributes": msg["attributes"], "messageId": msg["messageId"], "publishTime": msg["publishTime"]}
        if msg.get("orderingKey"):
            out_msg["orderingKey"] = msg["orderingKey"]
        received.append({"ackId": ack_id, "message": out_msg, "deliveryAttempt": attempts})
        kept.append(msg)
    sub["messages"] = kept
    out: dict = {}
    if received:
        out["receivedMessages"] = received
        store.persist()
    return _json(200, out)


def _acknowledge(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    ack_ids = body.get("ackIds") or []
    ackids = sub.setdefault("ackids", {})
    remove_ids = {ackids.pop(a) for a in ack_ids if a in ackids}
    if remove_ids:
        if sub.get("retainAckedMessages"):
            for m in sub.get("messages", []):
                if m["_id"] in remove_ids:
                    m["_acked"] = True
                    m["_pending"] = False
        else:
            sub["messages"] = [m for m in sub.get("messages", []) if m["_id"] not in remove_ids]
        store.persist()
    return _json(200, {})


def _seek(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    snap_name = body.get("snapshot")
    if snap_name:
        snap = _snap_store(store).get(snap_name)
        if not snap:
            raise PubsubError(404, "NOT_FOUND", f"Snapshot not found: {snap_name}")
        sub["messages"] = [{k: v for k, v in m.items() if k not in ("_pending", "_pending_until", "_acked")}
                           for m in snap.get("_messages", [])]
        sub["ackids"] = {}
    # body.get("time") (seek to a timestamp) is accepted but not modeled beyond acceptance.
    store.persist()
    return _json(200, {})


# ── snapshot operations ───────────────────────────────────────────────────
def _create_snapshot(store, name: str, body: dict) -> PubsubResponse:
    snaps = _snap_store(store)
    if name in snaps:
        raise PubsubError(409, "ALREADY_EXISTS", f"Snapshot already exists: {name}")
    sub_name = str(body.get("subscription", "")).strip()
    if not sub_name:
        raise PubsubError(400, "INVALID_ARGUMENT", "Snapshot must specify a subscription.")
    sub = _require_subscription(store, sub_name)
    snap = {
        "name": name,
        "topic": sub.get("topic", ""),
        "subscription": sub_name,
        "labels": dict(body.get("labels") or {}),
        "expireTime": _expires_rfc3339(7 * 24 * 3600),
        "_messages": [dict(m) for m in sub.get("messages", [])],
    }
    snaps[name] = snap
    store.persist()
    return _json(200, _snapshot_view(snap))


def _get_snapshot(store, name: str) -> PubsubResponse:
    snap = _snap_store(store).get(name)
    if not snap:
        raise PubsubError(404, "NOT_FOUND", f"Snapshot not found: {name}")
    return _json(200, _snapshot_view(snap))


def _list_snapshots(store, project: str) -> PubsubResponse:
    prefix = f"projects/{project}/snapshots/"
    items = [_snapshot_view(s) for n, s in _snap_store(store).items() if n.startswith(prefix)]
    out: dict = {}
    if items:
        out["snapshots"] = items
    return _json(200, out)


def _delete_snapshot(store, name: str) -> PubsubResponse:
    snaps = _snap_store(store)
    if name not in snaps:
        raise PubsubError(404, "NOT_FOUND", f"Snapshot not found: {name}")
    del snaps[name]
    store.persist()
    return _json(200, {})


# ── schema operations ──────────────────────────────────────────────────────
def _create_schema(store, project: str, query: dict, body: dict) -> PubsubResponse:
    schema_id = (query or {}).get("schemaId")
    if isinstance(schema_id, list):
        schema_id = schema_id[0] if schema_id else None
    if not schema_id:
        raise PubsubError(400, "INVALID_ARGUMENT", "schemaId is required.")
    schemas = _schema_store(store)
    name = f"projects/{project}/schemas/{schema_id}"
    if name in schemas:
        raise PubsubError(409, "ALREADY_EXISTS", f"Schema already exists: {name}")
    schema = {
        "name": name,
        "type": body.get("type", "TYPE_UNSPECIFIED"),
        "definition": body.get("definition", ""),
        "revisionId": uuid.uuid4().hex[:8],
        "revisionCreateTime": _now_rfc3339(),
    }
    schemas[name] = schema
    store.persist()
    return _json(200, _schema_view(schema, full=True))


def _get_schema(store, name: str, query: dict) -> PubsubResponse:
    schema = _schema_store(store).get(name)
    if not schema:
        raise PubsubError(404, "NOT_FOUND", f"Schema not found: {name}")
    view = (query or {}).get("view", "BASIC")
    if isinstance(view, list):
        view = view[0] if view else "BASIC"
    return _json(200, _schema_view(schema, full=(view == "FULL")))


def _list_schemas(store, project: str, query: dict) -> PubsubResponse:
    prefix = f"projects/{project}/schemas/"
    view = (query or {}).get("view", "BASIC")
    if isinstance(view, list):
        view = view[0] if view else "BASIC"
    items = [_schema_view(s, full=(view == "FULL")) for n, s in _schema_store(store).items() if n.startswith(prefix)]
    out: dict = {}
    if items:
        out["schemas"] = items
    return _json(200, out)


def _delete_schema(store, name: str) -> PubsubResponse:
    schemas = _schema_store(store)
    if name not in schemas:
        raise PubsubError(404, "NOT_FOUND", f"Schema not found: {name}")
    del schemas[name]
    store.persist()
    return _json(200, {})


# ── dispatch ──────────────────────────────────────────────────────────────
def dispatch(store: MessagingStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> PubsubResponse:
    """Native GCP Pub/Sub REST v1 router. Resource names are `projects/{p}/...`;
    verbs (`:publish`, `:pull`, `:acknowledge`, `:seek`) are `:`-suffixed on the path."""
    method = (method or "GET").upper()
    query = query or {}

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
    # Expect: projects / {project} / (topics|subscriptions|snapshots|schemas) [ / {id...} ]
    if len(segs) < 3 or segs[0] != "projects":
        return _err(404, "NOT_FOUND", f"Unknown path: {path}")
    project = segs[1]
    collection = segs[2]
    resource = p  # full resource name for a specific topic/subscription/snapshot/schema

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
            if method == "PATCH":
                return _patch_topic(store, resource, payload)
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
            if verb == "seek" and method == "POST":
                return _seek(store, resource, payload)
            if method == "PUT":
                return _create_subscription(store, resource, payload)
            if method == "PATCH":
                return _patch_subscription(store, resource, payload)
            if method == "GET":
                return _get_subscription(store, resource)
            if method == "DELETE":
                return _delete_subscription(store, resource)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on subscription")

        if collection == "snapshots":
            if len(segs) == 3:                       # collection
                if method == "GET":
                    return _list_snapshots(store, project)
                return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on snapshots")
            # specific snapshot
            if method == "PUT":
                return _create_snapshot(store, resource, payload)
            if method == "GET":
                return _get_snapshot(store, resource)
            if method == "DELETE":
                return _delete_snapshot(store, resource)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on snapshot")

        if collection == "schemas":
            if len(segs) == 3:                       # collection
                if method == "GET":
                    return _list_schemas(store, project, query)
                if method == "POST":
                    return _create_schema(store, project, query, payload)
                return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on schemas")
            # specific schema
            if method == "GET":
                return _get_schema(store, resource, query)
            if method == "DELETE":
                return _delete_schema(store, resource)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on schema")

        return _err(404, "NOT_FOUND", f"Unknown collection: {collection}")
    except PubsubError as e:
        return _err(e.code, e.status, e.message)
