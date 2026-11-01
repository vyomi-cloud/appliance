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
config, dead-letter policy, retry policy, subscription filter), publish (base64
data + attributes + ordering key → messageIds, validated against an attached
AVRO/JSON schema), pull (ack-deadline-based redelivery with exponential retry
backoff, per-ordering-key in-order delivery, dead-letter forwarding past
maxDeliveryAttempts, retention pruning), acknowledge, seek (to a snapshot OR,
when the topic has message retention enabled, to a point in time), and
snapshot / schema create+get+list+delete. Also modifyAckDeadline (nack / lease extension),
modifyPushConfig, subscriptions:detach, topics/{t}/subscriptions + topics/{t}/snapshots,
snapshot patch, schemas:validate / :validateMessage and get/set/testIamPermissions on all
four resource kinds (v4 C0g — what the offline appliance's pre-v4 handlers or the native
clients also use). Any other path under the four collections is a google.rpc NOT_FOUND /
INVALID_ARGUMENT JSON error.

DEPTH pass (this module): topic message retention now actually retains a
replayable backlog (seek-by-time), AVRO/JSON schema messages are validated on
publish, a subscription's ordering key is enforced in delivery order, retry
policy backoff really delays redelivery, and a subset of the subscription
filter language is evaluated at fan-out. Push delivery is recorded but never
actually dispatched over the network (no outbound HTTP from the simulator);
BigQuery/Cloud Storage subscriptions, topic ingestion and message transforms
are not modeled at all — see core/capabilities/gcp/pubsub.json.
"""
from __future__ import annotations

import base64
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace

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


def _parse_rfc3339(ts: str) -> float:
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()


# ── subscription filter language (a documented subset of Pub/Sub's filter
# syntax: attribute equality/inequality, hasPrefix, has-attribute, NOT/AND/OR
# and parens — see core/capabilities/gcp/pubsub.json for what's NOT covered,
# e.g. the ':' substring operator) ──────────────────────────────────────────
class _FilterError(Exception):
    pass


_FILTER_TOKEN_RE = re.compile(r'\(|\)|,|!=|=|:|"(?:[^"\\]|\\.)*"|[A-Za-z_][A-Za-z0-9_.]*')


def _tokenize_filter(expr: str) -> list[str]:
    tokens: list[str] = []
    pos, n = 0, len(expr)
    while pos < n:
        if expr[pos].isspace():
            pos += 1
            continue
        m = _FILTER_TOKEN_RE.match(expr, pos)
        if not m:
            raise _FilterError(f"unexpected character {expr[pos]!r}")
        tokens.append(m.group(0))
        pos = m.end()
    return tokens


def _unquote(tok: str) -> str:
    if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
        return tok[1:-1].replace('\\"', '"')
    return tok


class _FilterParser:
    """Recursive-descent parser: OR < AND < NOT < atom."""

    def __init__(self, tokens: list[str]) -> None:
        self.toks = tokens
        self.i = 0

    def peek(self) -> str | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def advance(self) -> str:
        t = self.peek()
        if t is None:
            raise _FilterError("unexpected end of filter")
        self.i += 1
        return t

    def parse(self):
        node = self._or()
        if self.peek() is not None:
            raise _FilterError(f"unexpected trailing token {self.peek()!r}")
        return node

    def _or(self):
        left = self._and()
        while self.peek() == "OR":
            self.advance()
            left = ("OR", left, self._and())
        return left

    def _and(self):
        left = self._not()
        while self.peek() == "AND":
            self.advance()
            left = ("AND", left, self._not())
        return left

    def _not(self):
        if self.peek() == "NOT":
            self.advance()
            return ("NOT", self._not())
        return self._atom()

    def _atom(self):
        t = self.peek()
        if t == "(":
            self.advance()
            node = self._or()
            if self.advance() != ")":
                raise _FilterError("expected ')'")
            return node
        if t == "hasPrefix":
            self.advance()
            if self.advance() != "(":
                raise _FilterError("expected '(' after hasPrefix")
            ref = self.advance()
            if self.advance() != ",":
                raise _FilterError("expected ',' in hasPrefix(...)")
            val = _unquote(self.advance())
            if self.advance() != ")":
                raise _FilterError("expected ')' in hasPrefix(...)")
            return ("HASPREFIX", _ref_key(ref), val)
        ref = self.advance()
        nxt = self.peek()
        if nxt == ":":
            self.advance()
            return ("HAS", _unquote(self.advance()))
        if nxt == "=":
            self.advance()
            return ("EQ", _ref_key(ref), _unquote(self.advance()))
        if nxt == "!=":
            self.advance()
            return ("NEQ", _ref_key(ref), _unquote(self.advance()))
        raise _FilterError(f"unsupported expression near {ref!r}")


def _ref_key(ref: str) -> str:
    prefix = "attributes."
    if not ref.startswith(prefix) or len(ref) <= len(prefix):
        raise _FilterError(f"unsupported attribute reference {ref!r} (expected attributes.<key>)")
    return ref[len(prefix):]


def _compile_filter(expr: str):
    if not expr or not expr.strip():
        return None
    return _FilterParser(_tokenize_filter(expr)).parse()


def _eval_filter(node, attrs: dict) -> bool:
    op = node[0]
    if op == "AND":
        return _eval_filter(node[1], attrs) and _eval_filter(node[2], attrs)
    if op == "OR":
        return _eval_filter(node[1], attrs) or _eval_filter(node[2], attrs)
    if op == "NOT":
        return not _eval_filter(node[1], attrs)
    if op == "HAS":
        return node[1] in attrs
    if op == "HASPREFIX":
        val = attrs.get(node[1])
        return isinstance(val, str) and val.startswith(node[2])
    if op in ("EQ", "NEQ"):
        eq = attrs.get(node[1]) == node[2]
        return eq if op == "EQ" else not eq
    raise _FilterError(f"unknown filter op {op}")


def _message_matches(filter_expr: str | None, attrs: dict | None) -> bool:
    """A malformed filter (shouldn't happen — validated at create time) never
    silently drops traffic: it fails open, same as having no filter."""
    if not filter_expr:
        return True
    try:
        node = _compile_filter(filter_expr)
        return node is None or _eval_filter(node, attrs or {})
    except _FilterError:
        return True


# ── AVRO/JSON schema validation (a documented subset: scalars, unions,
# records/arrays/maps/enums by structural shape — not full Avro semantics) ──
_AVRO_SCALARS = {
    "null": type(None), "boolean": bool, "int": int, "long": int,
    "float": (int, float), "double": (int, float), "string": str, "bytes": str,
}


def _avro_matches(schema_type, value) -> bool:
    if isinstance(schema_type, list):              # union, e.g. ["null", "string"]
        return any(_avro_matches(t, value) for t in schema_type)
    if isinstance(schema_type, str):
        if schema_type == "record":
            return isinstance(value, dict)          # named-type reference Vyomi doesn't resolve
        py = _AVRO_SCALARS.get(schema_type)
        if py is None:
            return True
        if py is bool:
            return isinstance(value, bool)
        if py is int:
            return isinstance(value, int) and not isinstance(value, bool)
        return isinstance(value, py)
    if not isinstance(schema_type, dict):
        return True
    kind = schema_type.get("type")
    if kind == "record":
        if not isinstance(value, dict):
            return False
        for f in schema_type.get("fields", []):
            fname = f.get("name")
            if fname not in value:
                ftype = f.get("type")
                if "default" in f or (isinstance(ftype, list) and "null" in ftype):
                    continue
                return False
            if not _avro_matches(f.get("type"), value[fname]):
                return False
        return True
    if kind == "array":
        return isinstance(value, list) and all(_avro_matches(schema_type.get("items"), v) for v in value)
    if kind == "map":
        return isinstance(value, dict)
    if kind == "enum":
        return value in schema_type.get("symbols", [value])
    return _avro_matches(kind, value)


def _validate_schema_message(store, topic: dict, record: dict) -> None:
    settings = topic.get("schemaSettings")
    if not settings or not settings.get("schema"):
        return
    schema = _schema_store(store).get(settings["schema"])
    if not schema:
        return
    encoding = str(settings.get("encoding") or "JSON").upper()
    if schema.get("type") != "AVRO" or encoding != "JSON":
        return  # BINARY-encoded Avro and PROTOCOL_BUFFER payloads aren't decoded in Vyomi
    try:
        parsed = json.loads(base64.b64decode(record["data"] or "").decode("utf-8"))
    except Exception:
        raise PubsubError(400, "INVALID_ARGUMENT", "Message data is not valid JSON for the topic's AVRO/JSON schema.")
    try:
        avro_schema = json.loads(schema.get("definition") or "null")
    except Exception:
        avro_schema = None
    if avro_schema is not None and not _avro_matches(avro_schema, parsed):
        raise PubsubError(400, "INVALID_ARGUMENT", "Message does not match the topic's schema.")


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
    if sub.get("filter"):
        v["filter"] = sub["filter"]
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
    """Deliver a prepared message record into every subscription attached to `topic`
    whose filter (if any) matches the message's attributes."""
    for sub_name in topic.get("subscriptions", []):
        sub = store.get_queue(sub_name)
        if sub is None or not _message_matches(sub.get("filter"), record.get("attributes")):
            continue
        sub.setdefault("messages", []).append({"_id": uuid.uuid4().hex, "_publish_at": store.now(), **record})


def _prune_topic_retention(store, topic: dict) -> None:
    """Topic-level message retention: an independent, replayable backlog used by
    seek-by-time (unlike subscription retention, this exists even for subscriptions
    created after the message was published)."""
    try:
        retention = int(str(topic.get("messageRetentionDuration", "0s")).rstrip("s"))
    except ValueError:
        retention = 0
    if not retention:
        topic.pop("_retained", None)
        return
    now = store.now()
    topic["_retained"] = [m for m in topic.get("_retained", []) if now - m.get("_publish_at", now) <= retention]


def _publish(store, name: str, body: dict, on_publish=None) -> PubsubResponse:
    topic = _require_topic(store, name)
    messages = body.get("messages") or []
    if not messages:
        raise PubsubError(400, "INVALID_ARGUMENT", "The value for message_count is too small. You passed 0")
    # Validate every message against the topic's schema (if any) BEFORE fanning any of
    # them out: a schema violation anywhere in the batch fails the whole publish call,
    # same as the real API — never a partial delivery.
    prepared: list[dict] = []
    for m in messages:
        record = {
            "data": m.get("data", ""),            # already base64 on the wire
            "attributes": dict(m.get("attributes") or {}),
            "messageId": _next_message_id(store),
            "publishTime": _now_rfc3339(),
        }
        if m.get("orderingKey"):
            record["orderingKey"] = m["orderingKey"]
        _validate_schema_message(store, topic, record)
        prepared.append(record)
    retain = bool(topic.get("messageRetentionDuration"))
    for record in prepared:
        _fanout(store, topic, record)
        if retain:
            topic.setdefault("_retained", []).append({**record, "_publish_at": store.now()})
    if retain:
        _prune_topic_retention(store, topic)
    store.persist()
    if on_publish:
        on_publish(name, prepared)
    return _json(200, {"messageIds": [r["messageId"] for r in prepared]})


# ── subscription operations ───────────────────────────────────────────────
def _create_subscription(store, name: str, body: dict) -> PubsubResponse:
    if store.get_queue(name):
        raise PubsubError(409, "ALREADY_EXISTS", f"Subscription already exists: {name}")
    topic_name = str(body.get("topic", "")).strip()
    if not topic_name:
        raise PubsubError(400, "INVALID_ARGUMENT", "Subscription must specify a topic.")
    topic = _require_topic(store, topic_name)
    filter_expr = str(body.get("filter", "") or "").strip()
    if filter_expr:
        try:
            _compile_filter(filter_expr)
        except _FilterError as e:
            raise PubsubError(400, "INVALID_ARGUMENT", f"Invalid filter: {e}")
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
    if filter_expr:
        # Immutable after creation, matching the real API: filter is never in
        # _SUB_PATCHABLE below.
        sub["filter"] = filter_expr
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


def _backoff_seconds(retry_policy: dict, attempts: int) -> float:
    def _secs(v, default):
        try:
            return float(str(v).rstrip("s"))
        except (TypeError, ValueError):
            return default
    minimum = _secs(retry_policy.get("minimumBackoff"), 10.0)
    maximum = _secs(retry_policy.get("maximumBackoff"), 600.0)
    return min(minimum * (2 ** max(0, attempts - 1)), maximum)


def _pull(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    _prune_retention(store, sub)
    max_messages = int(body.get("maxMessages", 1) or 1)
    deadline = int(sub.get("ackDeadlineSeconds", 10) or 10)
    dlp = sub.get("deadLetterPolicy")
    retry_policy = sub.get("retryPolicy")
    ordered = bool(sub.get("enableMessageOrdering"))
    now = store.now()
    kept: list[dict] = []
    received: list[dict] = []
    blocked_keys: set[str] = set()
    for msg in sub.get("messages", []):
        if msg.get("_acked"):
            kept.append(msg)
            continue
        key = msg.get("orderingKey") if ordered else None
        if key:
            if key in blocked_keys:
                kept.append(msg)   # an earlier unacked message with this ordering key exists
                continue
            blocked_keys.add(key)  # this is the head for the key: block any later one until it's acked
        if msg.get("_pending") and now < msg.get("_pending_until", 0):
            kept.append(msg)   # still out for delivery, within its ack deadline
            continue
        attempts_so_far = msg.get("_attempts", 0)
        if attempts_so_far and retry_policy and now < msg.get("_pending_until", 0) + _backoff_seconds(retry_policy, attempts_so_far):
            kept.append(msg)   # ack deadline expired, but still inside the retry policy's backoff window
            continue
        if len(received) >= max_messages:
            kept.append(msg)   # eligible, but this pull's quota is already full
            continue
        attempts = attempts_so_far + 1
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


_SEEK_COPY_DROP = ("_pending", "_pending_until", "_acked", "_attempts", "_id")


def _seek(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    snap_name = body.get("snapshot")
    time_val = body.get("time")
    if snap_name:
        snap = _snap_store(store).get(snap_name)
        if not snap:
            raise PubsubError(404, "NOT_FOUND", f"Snapshot not found: {snap_name}")
        sub["messages"] = [{**{k: v for k, v in m.items() if k not in _SEEK_COPY_DROP}, "_id": uuid.uuid4().hex}
                           for m in snap.get("_messages", [])]
        sub["ackids"] = {}
    elif time_val:
        # Seek to a point in time: only possible when the topic has message retention
        # enabled, since that's the only backlog Vyomi keeps independent of any one
        # subscription's own (shorter-lived) message list.
        topic = store.get_topic(sub.get("topic", ""))
        if not topic or not topic.get("messageRetentionDuration"):
            raise PubsubError(400, "FAILED_PRECONDITION",
                               "Seeking to a timestamp requires the topic to have message retention enabled.")
        try:
            ts = _parse_rfc3339(time_val) if isinstance(time_val, str) else float(time_val)
        except (ValueError, TypeError):
            raise PubsubError(400, "INVALID_ARGUMENT", f"Invalid seek time: {time_val!r}")
        _prune_topic_retention(store, topic)
        sub["messages"] = [{**{k: v for k, v in m.items() if k not in _SEEK_COPY_DROP}, "_id": uuid.uuid4().hex}
                           for m in topic.get("_retained", []) if m.get("_publish_at", 0) >= ts]
        sub["ackids"] = {}
    else:
        raise PubsubError(400, "INVALID_ARGUMENT", "Seek requires either a snapshot or a time.")
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



# ── subscription verbs the high-level clients use (modifyAckDeadline is how
# google-cloud-pubsub's streaming / flow-controlled subscribers extend or nack a
# lease; modifyPushConfig flips a subscription between push and pull; detach cuts a
# subscription from its topic) ─────────────────────────────────────────────────────
def _modify_ack_deadline(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    try:
        deadline = int(body.get("ackDeadlineSeconds", 0) or 0)
    except (TypeError, ValueError):
        raise PubsubError(400, "INVALID_ARGUMENT", "ackDeadlineSeconds must be an integer.")
    if deadline < 0 or deadline > 600:
        raise PubsubError(400, "INVALID_ARGUMENT",
                          f"Invalid ack deadline: {deadline}. It must be between 0 and 600 seconds.")
    ackids = sub.setdefault("ackids", {})
    targets = {ackids[a] for a in (body.get("ackIds") or []) if a in ackids}
    if targets:
        now = store.now()
        for m in sub.get("messages", []):
            if m.get("_id") in targets and not m.get("_acked"):
                if deadline == 0:            # a nack: redeliverable on the very next pull
                    m["_pending"] = False
                    m["_pending_until"] = now
                else:                        # extend (or shorten) the lease from now
                    m["_pending"] = True
                    m["_pending_until"] = now + deadline
        store.persist()
    return _json(200, {})


def _modify_push_config(store, name: str, body: dict) -> PubsubResponse:
    sub = _require_subscription(store, name)
    sub["pushConfig"] = dict(body.get("pushConfig") or {})
    store.persist()
    return _json(200, {})


def _detach_subscription(store, name: str) -> PubsubResponse:
    sub = _require_subscription(store, name)
    topic = store.get_topic(sub.get("topic", ""))
    if topic and name in topic.get("subscriptions", []):
        topic["subscriptions"].remove(name)
    sub["topic"] = "_deleted-topic_"
    sub["detached"] = True
    sub["messages"] = []
    sub["ackids"] = {}
    store.persist()
    return _json(200, {})


def _list_topic_subscriptions(store, topic_name: str) -> PubsubResponse:
    topic = _require_topic(store, topic_name)
    subs = [n for n in topic.get("subscriptions", []) if store.get_queue(n)]
    out: dict = {}
    if subs:
        out["subscriptions"] = subs
    return _json(200, out)


def _list_topic_snapshots(store, topic_name: str) -> PubsubResponse:
    _require_topic(store, topic_name)
    snaps = sorted(n for n, s in _snap_store(store).items() if s.get("topic") == topic_name)
    out: dict = {}
    if snaps:
        out["snapshots"] = snaps
    return _json(200, out)


def _patch_snapshot(store, name: str, body: dict) -> PubsubResponse:
    snap = _snap_store(store).get(name)
    if not snap:
        raise PubsubError(404, "NOT_FOUND", f"Snapshot not found: {name}")
    fields = body.get("snapshot") or body
    mask = [f.strip() for f in str(body.get("updateMask", "")).split(",") if f.strip()]
    for k in (mask or [k for k in fields if k in ("labels", "expireTime")]):
        if k in ("labels", "expireTime"):
            if k in fields:
                snap[k] = fields[k]
            elif k == "labels":
                snap.pop(k, None)
    store.persist()
    return _json(200, _snapshot_view(snap))


# ── schema validation (schemas:validate / schemas:validateMessage) ─────────────
_SCHEMA_TYPES = ("AVRO", "PROTOCOL_BUFFER")


def _check_schema_definition(schema: dict) -> None:
    stype = str(schema.get("type") or "")
    if stype not in _SCHEMA_TYPES:
        raise PubsubError(400, "INVALID_ARGUMENT", f"Invalid schema type: {stype or 'TYPE_UNSPECIFIED'}.")
    definition = str(schema.get("definition") or "")
    if not definition.strip():
        raise PubsubError(400, "INVALID_ARGUMENT", "Schema definition is empty.")
    if stype == "AVRO":
        try:
            json.loads(definition)
        except Exception:
            raise PubsubError(400, "INVALID_ARGUMENT", "Invalid AVRO schema definition: not valid JSON.")


def _validate_schema(store, project: str, body: dict) -> PubsubResponse:
    _check_schema_definition(body.get("schema") or {})
    return _json(200, {})


def _validate_message(store, project: str, body: dict) -> PubsubResponse:
    if body.get("name"):
        name = str(body["name"])
        if "/" not in name:
            name = f"projects/{project}/schemas/{name}"
        schema = _schema_store(store).get(name)
        if not schema:
            raise PubsubError(404, "NOT_FOUND", f"Schema not found: {name}")
    elif body.get("schema"):
        schema = body["schema"]
        _check_schema_definition(schema)
    else:
        raise PubsubError(400, "INVALID_ARGUMENT", "Either name or schema must be set.")
    encoding = str(body.get("encoding") or "JSON").upper()
    record = {"data": body.get("message", "")}
    one = SimpleNamespace(pubsub={"schemas": {"_v": schema}})   # reuse the publish-time validator verbatim
    _validate_schema_message(one, {"schemaSettings": {"schema": "_v", "encoding": encoding}}, record)
    return _json(200, {})


# ── IAM on Pub/Sub resources (topics / subscriptions / snapshots / schemas) ────
def _resource_for_iam(store, collection: str, name: str) -> dict:
    if collection == "topics":
        return _require_topic(store, name)
    if collection == "subscriptions":
        return _require_subscription(store, name)
    holder = _snap_store(store) if collection == "snapshots" else _schema_store(store)
    rec = holder.get(name)
    if not rec:
        raise PubsubError(404, "NOT_FOUND", f"Resource not found: {name}")
    return rec


def _iam(store, collection: str, name: str, verb: str, body: dict) -> PubsubResponse:
    rec = _resource_for_iam(store, collection, name)
    if verb == "getIamPolicy":
        return _json(200, rec.get("_iamPolicy") or {"etag": "ACAB"})
    if verb == "setIamPolicy":
        policy = dict(body.get("policy") or {})
        policy["etag"] = uuid.uuid4().hex[:8]
        rec["_iamPolicy"] = policy
        store.persist()
        return _json(200, policy)
    # testIamPermissions: the simulator's caller holds every permission it asks about
    perms = [p for p in (body.get("permissions") or []) if isinstance(p, str)]
    return _json(200, {"permissions": perms} if perms else {})


_IAM_VERBS = ("getIamPolicy", "setIamPolicy", "testIamPermissions")


# ── dispatch ──────────────────────────────────────────────────────────────
def dispatch(store: MessagingStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", on_publish=None) -> PubsubResponse:
    """Native GCP Pub/Sub REST v1 router. Resource names are `projects/{p}/...`;
    verbs (`:publish`, `:pull`, `:acknowledge`, `:seek`) are `:`-suffixed on the path.

    *on_publish(topic_full_name, prepared_messages)*, when given, is called after a
    successful publish — Cloud Run's Eventarc-style triggers hook in here (see
    core/aws_wire_router.py / routes/gcp_pubsub_unified.py)."""
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
            if len(segs) == 5 and segs[4] in ("subscriptions", "snapshots") and not verb:
                topic_name = "/".join(segs[:4])
                if method != "GET":
                    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on topic {segs[4]}")
                if segs[4] == "subscriptions":
                    return _list_topic_subscriptions(store, topic_name)
                return _list_topic_snapshots(store, topic_name)
            if len(segs) != 4:
                return _err(404, "NOT_FOUND", f"Unknown path: {path}")
            if verb in _IAM_VERBS:
                return _iam(store, collection, resource, verb, payload)
            # specific topic
            if verb == "publish" and method == "POST":
                return _publish(store, resource, payload, on_publish=on_publish)
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
            if len(segs) != 4:
                return _err(404, "NOT_FOUND", f"Unknown path: {path}")
            if verb in _IAM_VERBS:
                return _iam(store, collection, resource, verb, payload)
            if verb == "modifyAckDeadline" and method == "POST":
                return _modify_ack_deadline(store, resource, payload)
            if verb == "modifyPushConfig" and method == "POST":
                return _modify_push_config(store, resource, payload)
            if verb == "detach" and method == "POST":
                return _detach_subscription(store, resource)
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
            if len(segs) != 4:
                return _err(404, "NOT_FOUND", f"Unknown path: {path}")
            if verb in _IAM_VERBS:
                return _iam(store, collection, resource, verb, payload)
            # specific snapshot
            if method == "PUT":
                return _create_snapshot(store, resource, payload)
            if method == "PATCH":
                return _patch_snapshot(store, resource, payload)
            if method == "GET":
                return _get_snapshot(store, resource)
            if method == "DELETE":
                return _delete_snapshot(store, resource)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on snapshot")

        if collection == "schemas":
            if len(segs) == 3:                       # collection
                if method == "GET":
                    return _list_schemas(store, project, query)
                if method == "POST" and verb == "validate":
                    return _validate_schema(store, project, payload)
                if method == "POST" and verb == "validateMessage":
                    return _validate_message(store, project, payload)
                if method == "POST" and not verb:
                    return _create_schema(store, project, query, payload)
                return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on schemas")
            if len(segs) != 4:
                return _err(404, "NOT_FOUND", f"Unknown path: {path}")
            if verb in _IAM_VERBS:
                return _iam(store, collection, resource, verb, payload)
            # specific schema
            if method == "GET":
                return _get_schema(store, resource, query)
            if method == "DELETE":
                return _delete_schema(store, resource)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on schema")

        return _err(404, "NOT_FOUND", f"Unknown collection: {collection}")
    except PubsubError as e:
        return _err(e.code, e.status, e.message)
