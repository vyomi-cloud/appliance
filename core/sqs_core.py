"""SQS core — substrate-independent, faithfully extracted from the appliance SQS
handler (providers/aws_services.py `_sqs_*` + server.py dispatch) so the SAME
logic runs in Pro/Max (FastAPI), Nano (Pyodide), and tests. NO fastapi / boto3 /
socket / broker imports → loads under Pyodide. Persists through the MessagingStore
seam (core/messaging_store.py).

Wire: modern SQS speaks the **JSON protocol** (X-Amz-Target `AmazonSQS.<Op>`,
JSON body, `__type` errors) — what current boto3/aws-cli use — so the core
dispatches on the target and returns a `SqsResponse` (status, body-dict, headers).

Message semantics (the heart of SQS) are timestamp-based and faithful: a message
is available when `visible_at <= now` and not deleted; ReceiveMessage leases it
(new ReceiptHandle, `visible_at = now + VisibilityTimeout`, receive_count++);
DeleteMessage removes it by the CURRENT ReceiptHandle; when a lease expires the
message redelivers automatically. The store's controllable clock makes this
deterministic.

Scope: CreateQueue, GetQueueUrl, ListQueues, DeleteQueue, GetQueueAttributes,
SetQueueAttributes, SendMessage(+Batch), ReceiveMessage, DeleteMessage(+Batch),
ChangeMessageVisibility(+Batch), PurgeQueue, tags, FIFO ordering/dedup (5-minute
window), DLQ redrive (maxReceiveCount) and redrive back out of a DLQ
(Start/List/CancelMessageMoveTask, ListDeadLetterSourceQueues), message retention,
MaximumMessageSize, MD5OfMessageAttributes.

The legacy **Query protocol** (form-encoded `Action=…`, XML responses — older SDKs,
the Java v1 SDK, `curl`) is served by `dispatch_query`, which maps the flattened
params onto the same JSON operations and renders the native XML, so both protocols
share one engine and one state.

Queue URLs: `store.queue_url_for(name)` (optional hook) lets a substrate hand out
URLs an SDK can POST back to (the offline appliance returns `<endpoint>/<account>/<queue>`);
without it the URL is the AWS-shaped `https://sqs.<region>.amazonaws.com/<account>/<queue>`.
Any URL whose last segment is the queue name is accepted on input.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
import uuid
from xml.sax.saxutils import escape as _xml_escape
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.messaging_store import MessagingStore, REGION

_DEFAULT_VISIBILITY = 30
_DEFAULT_RETENTION = 345600          # 4 days
_DEFAULT_MAX_SIZE = 262144           # 256 KiB
DEDUP_WINDOW_SECONDS = 300           # FIFO deduplication interval
_QUEUE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


@dataclass
class SqsResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class SqsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _req_id() -> str:
    return str(uuid.uuid4())


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _queue_arn(store, name: str) -> str:
    return f"arn:aws:sqs:{REGION}:{store.account_id}:{name}"


def _queue_url(store, name: str) -> str:
    hook = getattr(store, "queue_url_for", None)
    if callable(hook):
        try:
            url = hook(name)
            if url:
                return str(url)
        except Exception:
            pass
    return f"https://sqs.{REGION}.amazonaws.com/{store.account_id}/{name}"


def _attr_int(attrs: dict, key: str, default: int) -> int:
    try:
        return int(attrs.get(key, default))
    except (TypeError, ValueError):
        return default


# ── MD5 of message attributes (the digest every AWS SDK verifies) ──────────
def md5_of_message_attributes(attrs: dict | None) -> str | None:
    """The SQS MD5OfMessageAttributes algorithm: for each attribute in name order,
    length-prefixed (4-byte big-endian) name, data type, a transport byte (1 = string,
    2 = binary) and the length-prefixed value."""
    if not attrs:
        return None
    buf = bytearray()

    def _lp(b: bytes) -> None:
        buf.extend(struct.pack(">I", len(b)))
        buf.extend(b)

    for name in sorted(attrs):
        a = attrs[name] or {}
        dtype = str(a.get("DataType") or "String")
        _lp(name.encode("utf-8"))
        _lp(dtype.encode("utf-8"))
        if a.get("BinaryValue") is not None and not dtype.startswith(("String", "Number")):
            raw = a["BinaryValue"]
            if isinstance(raw, str):
                try:
                    raw = base64.b64decode(raw)
                except Exception:
                    raw = raw.encode("utf-8")
            buf.append(2)
            _lp(bytes(raw))
        else:
            buf.append(1)
            _lp(str(a.get("StringValue") if a.get("StringValue") is not None else "").encode("utf-8"))
    return hashlib.md5(bytes(buf)).hexdigest()


def _name_from_url(url: str) -> str:
    return (url or "").rstrip("/").split("/")[-1]


# ── shared enqueue primitive (used by SendMessage AND SNS fan-out) ─────────
def _sqs_event_record(q: dict, msg: dict) -> dict:
    """The record shape a real Lambda SQS event source mapping hands the function —
    used both for a Lambda trigger invocation and (pass-through) for an EventBridge
    Pipe delivery."""
    sent_ms = str(int(float(msg.get("sent_epoch") or 0) * 1000))
    attrs = {"ApproximateReceiveCount": "1", "SentTimestamp": sent_ms,
             "SenderId": "AIDACKCEVSQ6C2EXAMPLE", "ApproximateFirstReceiveTimestamp": sent_ms}
    if msg.get("message_group_id"):
        attrs["MessageGroupId"] = msg["message_group_id"]
    if msg.get("message_dedup_id"):
        attrs["MessageDeduplicationId"] = msg["message_dedup_id"]
    msg_attrs = {name: {"stringValue": a.get("StringValue"), "binaryValue": a.get("BinaryValue"),
                        "dataType": a.get("DataType", "String")}
                 for name, a in (msg.get("message_attributes") or {}).items()}
    return {"messageId": msg["message_id"], "receiptHandle": "trigger-" + uuid.uuid4().hex,
            "body": msg["body"], "attributes": attrs, "messageAttributes": msg_attrs,
            "md5OfBody": msg["md5_of_body"], "eventSource": "aws:sqs",
            "eventSourceARN": q.get("queue_arn", ""), "awsRegion": REGION}


def _fire_triggers(store, lam_store, q: dict, msg: dict) -> None:
    """A message landing in the queue is handed, right away, to every ENABLED Lambda
    event source mapping and RUNNING EventBridge Pipe that names this queue as its
    source — the same two console features ("Lambda triggers" / "EventBridge Pipes")
    a real background poller would deliver to; Vyomi has none, so this fires
    synchronously at send time instead of on a batching/polling schedule (see
    sqs.lambda-triggers / sqs.eventbridge-pipes limitations). A delayed message
    (DelaySeconds) isn't fired until it is actually visible."""
    arn = q.get("queue_arn", "")
    if not arn or msg.get("visible_at", 0) > store.now():
        return
    consumed = False
    if lam_store is not None:
        from core import lambda_core as _lam
        for mapping in _lam.active_mappings_for_source(lam_store, arn):
            event = {"Records": [_sqs_event_record(q, msg)]}
            if _lam.invoke_trigger_mapping(lam_store, mapping, event):
                consumed = True
    from core import eventbridge_core as _eb
    for pipe in _eb.active_pipes_for_source(store, arn):
        record = _sqs_event_record(q, msg)
        if _eb.deliver(store, lam_store, pipe["Target"], msg["body"], record):
            consumed = True
    if consumed:
        msg["deleted"] = True


def enqueue(store: MessagingStore, queue: dict, body: str,
            message_attributes: dict | None = None, delay_seconds: int = 0,
            message_group_id: str | None = None,
            message_dedup_id: str | None = None) -> dict:
    now = store.now()
    msg = {
        "message_id": "msg-" + uuid.uuid4().hex,
        "body": body,
        "md5_of_body": _md5(body),
        "message_attributes": message_attributes or {},
        "sent_at": _now_iso(),
        "sent_epoch": now,
        "visible_at": now + max(0, delay_seconds),
        "receive_count": 0,
        "receipt_handle": "",
        "in_flight": False,
        "deleted": False,
        "message_group_id": message_group_id,
        "message_dedup_id": message_dedup_id,
    }
    queue.setdefault("messages", []).append(msg)
    return msg


# ── queue lifecycle ──────────────────────────────────────────────────────
def _require_queue(store, url_or_name: str) -> dict:
    name = _name_from_url(url_or_name) if "/" in (url_or_name or "") else url_or_name
    q = store.get_queue(name)
    if not q:
        raise SqsError("com.amazonaws.sqs#QueueDoesNotExist",
                       "The specified queue does not exist.", 400)
    return q


def _create_queue(store, body):
    name = str(body.get("QueueName", "")).strip()
    if not name:
        raise SqsError("com.amazonaws.sqs#MissingParameter", "QueueName is required.", 400)
    if name.endswith(".fifo") is False and str(body.get("Attributes", {}).get("FifoQueue", "")).lower() == "true":
        raise SqsError("com.amazonaws.sqs#InvalidParameterValue",
                       "The name of a FIFO queue can only include alphanumeric characters, "
                       "hyphens, or underscores, must end with .fifo suffix.", 400)
    if not _QUEUE_NAME_RE.match(name[:-5] if name.endswith(".fifo") else name) or len(name) > 80:
        raise SqsError("com.amazonaws.sqs#InvalidParameterValue",
                       "Can only include alphanumeric characters, hyphens, or underscores. "
                       "1 to 80 in length", 400)
    existing = store.get_queue(name)
    if existing is not None:
        # Real SQS: CreateQueue is idempotent, but not with different attribute values.
        incoming = {k: str(v) for k, v in dict(body.get("Attributes") or {}).items()}
        current = {k: str(v) for k, v in dict(existing.get("attributes") or {}).items()}
        if any(k in current and current[k] != v for k, v in incoming.items()):
            raise SqsError("com.amazonaws.sqs#QueueAlreadyExists",
                           "A queue already exists with the same name and a different value for attribute(s) "
                           + ", ".join(sorted(k for k, v in incoming.items() if k in current and current[k] != v)), 400)
    if not store.queue_exists(name):
        attrs = dict(body.get("Attributes") or {})
        is_fifo = name.endswith(".fifo") or str(attrs.get("FifoQueue", "")).lower() == "true"
        if attrs.get("RedrivePolicy"):
            _check_redrive_allowed(store, _queue_arn(store, name), attrs["RedrivePolicy"])
        store.put_queue(name, {
            "queue_name": name,
            "queue_url": _queue_url(store, name),
            "queue_arn": _queue_arn(store, name),
            "attributes": attrs,
            "visibility_timeout": int(attrs.get("VisibilityTimeout", _DEFAULT_VISIBILITY)),
            "delay_seconds": int(attrs.get("DelaySeconds", 0)),
            "tags": dict(body.get("tags") or {}),
            "messages": [],
            "created": _now_iso(),
            "created_epoch": store.now(),
            "last_modified_epoch": store.now(),
            "fifo": is_fifo,
            "content_based_dedup": str(attrs.get("ContentBasedDeduplication", "")).lower() == "true",
            "dedup_seen": {},   # dedup_id -> message_id (5-min window, simplified to lifetime)
        })
        store.persist()
    return SqsResponse(body={"QueueUrl": _queue_url(store, name)})


def _redrive_policy(q: dict) -> dict | None:
    raw = q.get("attributes", {}).get("RedrivePolicy")
    if not raw:
        return None
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None


def _redrive_allow_policy(q: dict) -> dict | None:
    raw = q.get("attributes", {}).get("RedriveAllowPolicy")
    if not raw:
        return None
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return None


def _check_redrive_allowed(store, source_arn: str, redrive_policy_json) -> None:
    """A queue may only name another queue as its dead-letter target if that target's
    RedriveAllowPolicy permits it (allowAll/unset = anyone, byQueue = listed ARNs only,
    denyAll = no one) — enforced at the same point real SQS enforces it: when the SOURCE
    queue's RedrivePolicy is set."""
    try:
        pol = json.loads(redrive_policy_json) if isinstance(redrive_policy_json, str) else redrive_policy_json
    except Exception:
        return
    if not pol:
        return
    dlq = store.get_queue_by_arn(str(pol.get("deadLetterTargetArn", "")))
    if dlq is None:
        return
    allow = _redrive_allow_policy(dlq)
    if not allow:
        return
    perm = str(allow.get("redrivePermission", "allowAll"))
    if perm == "denyAll":
        raise SqsError("com.amazonaws.sqs#InvalidParameterValue",
                       "Value for parameter RedrivePolicy is invalid. Reason: the dead-letter "
                       "queue's redrive allow policy denies all source queues.", 400)
    if perm == "byQueue":
        allowed = {str(a) for a in (allow.get("sourceQueueArns") or [])}
        if source_arn not in allowed:
            raise SqsError("com.amazonaws.sqs#InvalidParameterValue",
                           "Value for parameter RedrivePolicy is invalid. Reason: the dead-letter "
                           "queue's redrive allow policy does not list this queue as an allowed source.", 400)


def _get_queue_url(store, body):
    name = str(body.get("QueueName", "")).strip()
    if not store.queue_exists(name):
        raise SqsError("com.amazonaws.sqs#QueueDoesNotExist", "The specified queue does not exist.", 400)
    return SqsResponse(body={"QueueUrl": _queue_url(store, name)})


def _list_queues(store, body):
    prefix = str(body.get("QueueNamePrefix", "") or "")
    urls = [_queue_url(store, n) for n in store.queue_names() if n.startswith(prefix)]
    return SqsResponse(body={"QueueUrls": urls})


def _delete_queue(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    store.drop_queue(q["queue_name"])
    store.persist()
    return SqsResponse(body={})


def _get_queue_attributes(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    visible = sum(1 for m in q["messages"] if _available(m, store.now()))
    not_visible = sum(1 for m in q["messages"] if not m["deleted"] and not _available(m, store.now()))
    attrs = {"DelaySeconds": "0", "MaximumMessageSize": str(_DEFAULT_MAX_SIZE),
             "MessageRetentionPeriod": str(_DEFAULT_RETENTION), "ReceiveMessageWaitTimeSeconds": "0",
             "ApproximateNumberOfMessagesDelayed": "0"}
    attrs.update({k: str(v) for k, v in dict(q.get("attributes", {})).items()})
    delayed = sum(1 for m in q["messages"] if not m.get("deleted") and not m.get("receive_count")
                  and not _available(m, store.now()))
    attrs.update({
        "QueueArn": q["queue_arn"],
        "ApproximateNumberOfMessages": str(visible),
        "ApproximateNumberOfMessagesNotVisible": str(max(0, not_visible - delayed)),
        "ApproximateNumberOfMessagesDelayed": str(delayed),
        "VisibilityTimeout": str(q.get("visibility_timeout", _DEFAULT_VISIBILITY)),
        "DelaySeconds": str(q.get("delay_seconds", attrs.get("DelaySeconds", 0))),
        "CreatedTimestamp": str(int(q.get("created_epoch", 0))),
        "LastModifiedTimestamp": str(int(q.get("last_modified_epoch", q.get("created_epoch", 0)))),
    })
    if q.get("fifo"):
        attrs["FifoQueue"] = "true"
        attrs["ContentBasedDeduplication"] = "true" if q.get("content_based_dedup") else "false"
    names = [str(n) for n in (body.get("AttributeNames") or [])]
    if names and "All" not in names:
        attrs = {k: v for k, v in attrs.items() if k in names}
    return SqsResponse(body={"Attributes": attrs})


def _set_queue_attributes(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    incoming = dict(body.get("Attributes") or {})
    if incoming.get("RedrivePolicy"):
        _check_redrive_allowed(store, q["queue_arn"], incoming["RedrivePolicy"])
    q.setdefault("attributes", {}).update(incoming)
    if "VisibilityTimeout" in incoming:
        q["visibility_timeout"] = int(incoming["VisibilityTimeout"])
    if "DelaySeconds" in incoming:
        q["delay_seconds"] = int(incoming["DelaySeconds"])
    if "ContentBasedDeduplication" in incoming:
        q["content_based_dedup"] = str(incoming["ContentBasedDeduplication"]).lower() == "true"
    q["last_modified_epoch"] = store.now()
    store.persist()
    return SqsResponse(body={})


# ── messages ─────────────────────────────────────────────────────────────
def _available(msg: dict, now: float) -> bool:
    return not msg.get("deleted") and msg.get("visible_at", 0) <= now


def _send_message(store, body, lam_store=None):
    q = _require_queue(store, body.get("QueueUrl", ""))
    payload = body.get("MessageBody")
    if payload is None:
        raise SqsError("com.amazonaws.sqs#MissingParameter", "MessageBody is required.", 400)
    payload = str(payload)
    max_size = _attr_int(q.get("attributes") or {}, "MaximumMessageSize", _DEFAULT_MAX_SIZE)
    if len(payload.encode("utf-8")) > max_size:
        raise SqsError("com.amazonaws.sqs#InvalidParameterValue",
                       f"One or more parameters are invalid. Reason: Message must be shorter than {max_size} bytes.", 400)
    _expire_retention(store, q)
    delay = int(body.get("DelaySeconds", q.get("delay_seconds", 0)) or 0)
    group_id = body.get("MessageGroupId")
    dedup_id = body.get("MessageDeduplicationId")
    if q.get("fifo"):
        if not group_id:
            raise SqsError("com.amazonaws.sqs#MissingParameter",
                           "The request must contain the parameter MessageGroupId.", 400)
        if not dedup_id:
            if q.get("content_based_dedup"):
                dedup_id = _md5(payload)
            else:
                raise SqsError("com.amazonaws.sqs#InvalidParameterValue",
                               "The queue should either have ContentBasedDeduplication enabled "
                               "or MessageDeduplicationId provided explicitly.", 400)
        seen = q.setdefault("dedup_seen", {})
        now = store.now()
        for k in [k for k, v in seen.items() if isinstance(v, dict) and now - v.get("ts", 0) > DEDUP_WINDOW_SECONDS]:
            del seen[k]
        if dedup_id in seen:
            # Duplicate within the 5-minute dedup interval — accept but do not enqueue again.
            prior = seen[dedup_id]
            prior_id = prior.get("id") if isinstance(prior, dict) else prior
            return SqsResponse(body={"MessageId": prior_id, "MD5OfMessageBody": _md5(payload),
                                     "SequenceNumber": str(prior.get("seq", "0")) if isinstance(prior, dict) else "0"})
        # FIFO ignores per-message delay.
        delay = 0
    msg = enqueue(store, q, payload, body.get("MessageAttributes"), delay,
                  message_group_id=group_id, message_dedup_id=dedup_id)
    out = {"MessageId": msg["message_id"], "MD5OfMessageBody": msg["md5_of_body"]}
    md5a = md5_of_message_attributes(msg.get("message_attributes"))
    if md5a:
        out["MD5OfMessageAttributes"] = md5a
    if q.get("fifo"):
        q["sequence"] = int(q.get("sequence", 0) or 0) + 1
        msg["sequence_number"] = str(q["sequence"]).zfill(20)
        out["SequenceNumber"] = msg["sequence_number"]
        if dedup_id:
            q["dedup_seen"][dedup_id] = {"id": msg["message_id"], "ts": store.now(), "seq": msg["sequence_number"]}
    _fire_triggers(store, lam_store, q, msg)
    store.persist()
    return SqsResponse(body=out)


def _expire_retention(store, q) -> None:
    """Messages older than MessageRetentionPeriod are deleted (as SQS does)."""
    keep = _attr_int(q.get("attributes") or {}, "MessageRetentionPeriod", _DEFAULT_RETENTION)
    now = store.now()
    msgs = q.get("messages") or []
    live = [m for m in msgs if not m.get("deleted")
            and not (m.get("sent_epoch") is not None and now - float(m["sent_epoch"]) > keep)]
    if len(live) != len(msgs):
        q["messages"] = live


def _redrive_expired(store, q, now):
    """Move messages that have been received > maxReceiveCount times to the DLQ
    (the canonical SQS redrive). Runs at receive time, before leasing."""
    policy = _redrive_policy(q)
    if not policy:
        return
    try:
        max_recv = int(policy.get("maxReceiveCount", 0) or 0)
    except (TypeError, ValueError):
        return
    if max_recv <= 0:
        return
    dlq = store.get_queue_by_arn(str(policy.get("deadLetterTargetArn", "")))
    if dlq is None:
        return
    survivors = []
    moved = False
    for msg in q["messages"]:
        if msg.get("deleted"):
            continue
        # A message that has already been received max_recv times and is available
        # again (its lease lapsed without a delete) is dead-lettered.
        if _available(msg, now) and msg.get("receive_count", 0) >= max_recv:
            dead = dict(msg)
            dead.update({"receive_count": 0, "receipt_handle": "", "in_flight": False,
                         "visible_at": now, "dead_letter_source_arn": q.get("queue_arn", "")})
            dlq.setdefault("messages", []).append(dead)
            moved = True
            continue
        survivors.append(msg)
    if moved:
        q["messages"] = survivors


def _receive_message(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    now = store.now()
    max_n = int(body.get("MaxNumberOfMessages", 1) or 1)
    if max_n < 1 or max_n > 10:
        raise SqsError("com.amazonaws.sqs#InvalidParameterValue",
                       f"Value {max_n} for parameter MaxNumberOfMessages is invalid. "
                       "Reason: Must be between 1 and 10, if provided.", 400)
    vis = int(body.get("VisibilityTimeout", q.get("visibility_timeout", _DEFAULT_VISIBILITY)))
    sys_names = set(str(n) for n in (body.get("AttributeNames") or []))
    sys_names |= set(str(n) for n in (body.get("MessageSystemAttributeNames") or []))
    want_attrs = body.get("MessageAttributeNames")
    _expire_retention(store, q)
    _redrive_expired(store, q, now)
    # FIFO: a group with an in-flight (leased, not-yet-deleted) message is locked —
    # no other message from that group is delivered until the in-flight one is deleted.
    locked_groups = set()
    if q.get("fifo"):
        for m in q["messages"]:
            if not m.get("deleted") and not _available(m, now) and m.get("message_group_id"):
                locked_groups.add(m["message_group_id"])
    out = []
    for msg in q["messages"]:
        if len(out) >= max_n:
            break
        if not _available(msg, now):
            continue
        grp = msg.get("message_group_id")
        if q.get("fifo") and grp in locked_groups:
            continue   # preserve per-group ordering
        msg["in_flight"] = True
        msg["receipt_handle"] = "rhdl-" + uuid.uuid4().hex
        msg["visible_at"] = now + vis
        msg["receive_count"] += 1
        msg.setdefault("first_receive_epoch", now)
        if q.get("fifo") and grp:
            locked_groups.add(grp)   # lock the group for the rest of this batch
        attrs = {"ApproximateReceiveCount": str(msg["receive_count"])}
        if grp:
            attrs["MessageGroupId"] = grp
        extra = {"SentTimestamp": str(int(float(msg.get("sent_epoch") or now) * 1000)),
                 "ApproximateFirstReceiveTimestamp": str(int(float(msg["first_receive_epoch"]) * 1000)),
                 "SenderId": str(store.account_id)}
        if msg.get("message_dedup_id"):
            extra["MessageDeduplicationId"] = msg["message_dedup_id"]
        if msg.get("sequence_number"):
            extra["SequenceNumber"] = msg["sequence_number"]
        if msg.get("dead_letter_source_arn"):
            extra["DeadLetterQueueSourceArn"] = msg["dead_letter_source_arn"]
        for k, v in extra.items():
            if "All" in sys_names or k in sys_names:
                attrs[k] = v
        mattrs = _select_message_attributes(msg.get("message_attributes") or {}, want_attrs)
        item = {
            "MessageId": msg["message_id"],
            "ReceiptHandle": msg["receipt_handle"],
            "MD5OfBody": msg["md5_of_body"],
            "Body": msg["body"],
            "Attributes": attrs,
            "MessageAttributes": mattrs,
        }
        md5a = md5_of_message_attributes(mattrs)
        if md5a:
            item["MD5OfMessageAttributes"] = md5a
        out.append(item)
    if out or _redrive_policy(q):
        store.persist()
    return SqsResponse(body={"Messages": out} if out else {})


def _select_message_attributes(attrs: dict, names) -> dict:
    """MessageAttributeNames: "All" / ".*" / "prefix.*" / exact names. Omitted → every
    attribute (Vyomi keeps returning them so pre-existing clients that never asked
    still see them)."""
    if names is None:
        return dict(attrs)
    names = [str(n) for n in names]
    out = {}
    for k, v in attrs.items():
        for n in names:
            if n in ("All", ".*") or k == n or (n.endswith(".*") and k.startswith(n[:-2])):
                out[k] = v
                break
    return out


def _delete_message(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    handle = str(body.get("ReceiptHandle", ""))
    for msg in q["messages"]:
        if msg.get("receipt_handle") == handle and not msg["deleted"]:
            msg["deleted"] = True
            q["messages"] = [m for m in q["messages"] if not m["deleted"]]
            store.persist()
            return SqsResponse(body={})
    raise SqsError("com.amazonaws.sqs#ReceiptHandleIsInvalid",
                   "The receipt handle is not valid.", 400)


def _change_message_visibility(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    handle = str(body.get("ReceiptHandle", ""))
    vis = int(body.get("VisibilityTimeout", 0))
    for msg in q["messages"]:
        if msg.get("receipt_handle") == handle and not msg["deleted"]:
            msg["visible_at"] = store.now() + max(0, vis)
            store.persist()
            return SqsResponse(body={})
    raise SqsError("com.amazonaws.sqs#ReceiptHandleIsInvalid",
                   "The receipt handle is not valid.", 400)


def _purge_queue(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    q["messages"] = []
    store.persist()
    return SqsResponse(body={})


# ── tags ─────────────────────────────────────────────────────────────────
def _tag_queue(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    q.setdefault("tags", {}).update(dict(body.get("Tags") or {}))
    store.persist()
    return SqsResponse(body={})


def _untag_queue(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    tags = q.setdefault("tags", {})
    for k in body.get("TagKeys") or []:
        tags.pop(k, None)
    store.persist()
    return SqsResponse(body={})


def _list_queue_tags(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    return SqsResponse(body={"Tags": q.get("tags", {})})


# ── batch operations ─────────────────────────────────────────────────────
def _batch(entries, fn, ok_key):
    if not entries:
        raise SqsError("com.amazonaws.sqs#EmptyBatchRequest",
                       "There should be at least one SendMessageBatchRequestEntry in the request.", 400)
    if len(entries) > 10:
        raise SqsError("com.amazonaws.sqs#TooManyEntriesInBatchRequest",
                       f"Maximum number of entries per request are 10. You have sent {len(entries)}.", 400)
    ids = [str(e.get("Id", "")) for e in entries]
    if len(set(ids)) != len(ids):
        raise SqsError("com.amazonaws.sqs#BatchEntryIdsNotDistinct",
                       "Two or more batch entries in the request have the same Id.", 400)
    ok, failed = [], []
    for e in entries:
        try:
            res = fn(e)
            ok.append(dict({"Id": str(e.get("Id", ""))}, **(res or {})))
        except SqsError as err:
            failed.append({"Id": str(e.get("Id", "")), "SenderFault": True,
                           "Code": err.code.split("#")[-1], "Message": err.message})
    return SqsResponse(body={ok_key: ok, "Failed": failed})


def _send_message_batch(store, body, lam_store=None):
    url = body.get("QueueUrl", "")
    _require_queue(store, url)

    def one(e):
        req = {k: v for k, v in e.items() if k != "Id"}
        req["QueueUrl"] = url
        r = _send_message(store, req, lam_store)
        return r.body
    return _batch(body.get("Entries") or [], one, "Successful")


def _delete_message_batch(store, body):
    url = body.get("QueueUrl", "")
    _require_queue(store, url)

    def one(e):
        _delete_message(store, {"QueueUrl": url, "ReceiptHandle": e.get("ReceiptHandle", "")})
        return {}
    return _batch(body.get("Entries") or [], one, "Successful")


def _change_message_visibility_batch(store, body):
    url = body.get("QueueUrl", "")
    _require_queue(store, url)

    def one(e):
        _change_message_visibility(store, {"QueueUrl": url, "ReceiptHandle": e.get("ReceiptHandle", ""),
                                           "VisibilityTimeout": e.get("VisibilityTimeout", 0)})
        return {}
    return _batch(body.get("Entries") or [], one, "Successful")


# ── dead-letter queues: sources + redrive back out (message move tasks) ───
def _list_dead_letter_source_queues(store, body):
    dlq = _require_queue(store, body.get("QueueUrl", ""))
    urls = []
    for name in store.queue_names():
        pol = _redrive_policy(store.get_queue(name) or {})
        if pol and str(pol.get("deadLetterTargetArn", "")) == dlq.get("queue_arn"):
            urls.append(_queue_url(store, name))
    return SqsResponse(body={"queueUrls": urls})


def _move_tasks(store) -> dict:
    m = getattr(store, "sqs_move_tasks", None)
    if not isinstance(m, dict):
        try:
            store.sqs_move_tasks = m = {}
        except Exception:
            m = {}
    return m


def _start_message_move_task(store, body):
    src_arn = str(body.get("SourceArn", ""))
    src = store.get_queue_by_arn(src_arn)
    if src is None:
        raise SqsError("com.amazonaws.sqs#ResourceNotFoundException", "The resource that you specified for the SourceArn parameter doesn't exist.", 400)
    is_dlq = any((_redrive_policy(store.get_queue(n) or {}) or {}).get("deadLetterTargetArn") == src_arn
                 for n in store.queue_names())
    if not is_dlq:
        raise SqsError("com.amazonaws.sqs#InvalidParameterValue",
                       "Source queue must be configured as a Dead Letter Queue.", 400)
    dest_arn = str(body.get("DestinationArn", "") or "")
    if dest_arn and store.get_queue_by_arn(dest_arn) is None:
        raise SqsError("com.amazonaws.sqs#ResourceNotFoundException", "The resource that you specified for the DestinationArn parameter doesn't exist.", 400)
    now = store.now()
    moved, failed, keep = 0, 0, []
    for msg in src.get("messages") or []:
        if not _available(msg, now):
            keep.append(msg)
            continue
        target = store.get_queue_by_arn(dest_arn or str(msg.get("dead_letter_source_arn", "")))
        if target is None:
            failed += 1
            keep.append(msg)
            continue
        enqueue(store, target, msg["body"], msg.get("message_attributes") or None,
                message_group_id=msg.get("message_group_id"), message_dedup_id=msg.get("message_dedup_id"))
        moved += 1
    src["messages"] = keep
    handle = base64.b64encode(json.dumps({"taskId": uuid.uuid4().hex, "sourceArn": src_arn}).encode()).decode()
    _move_tasks(store)[handle] = {
        "TaskHandle": handle, "Status": "COMPLETED", "SourceArn": src_arn,
        **({"DestinationArn": dest_arn} if dest_arn else {}),
        "ApproximateNumberOfMessagesMoved": moved, "ApproximateNumberOfMessagesToMove": moved,
        "StartedTimestamp": int(now * 1000)}
    if failed:
        _move_tasks(store)[handle]["FailureReason"] = f"{failed} message(s) had no destination queue"
    store.persist()
    return SqsResponse(body={"TaskHandle": handle})


def _list_message_move_tasks(store, body):
    src_arn = str(body.get("SourceArn", ""))
    if store.get_queue_by_arn(src_arn) is None:
        raise SqsError("com.amazonaws.sqs#ResourceNotFoundException", "The resource that you specified for the SourceArn parameter doesn't exist.", 400)
    rows = sorted((t for t in _move_tasks(store).values() if t.get("SourceArn") == src_arn),
                  key=lambda t: t.get("StartedTimestamp", 0), reverse=True)
    n = int(body.get("MaxResults", 1) or 1)
    return SqsResponse(body={"Results": [{k: v for k, v in t.items() if k != "TaskHandle" or t["Status"] == "RUNNING"}
                                         for t in rows[:max(1, min(n, 10))]]})


def _cancel_message_move_task(store, body):
    t = _move_tasks(store).get(str(body.get("TaskHandle", "")))
    if t is None:
        raise SqsError("com.amazonaws.sqs#ResourceNotFoundException", "The specified task handle doesn't exist.", 400)
    if t.get("Status") != "RUNNING":
        raise SqsError("com.amazonaws.sqs#UnsupportedOperation", "Only RUNNING tasks can be cancelled.", 400)
    t["Status"] = "CANCELLED"
    store.persist()
    return SqsResponse(body={"ApproximateNumberOfMessagesMoved": t.get("ApproximateNumberOfMessagesMoved", 0)})


_OPS = {
    "SendMessageBatch": _send_message_batch, "DeleteMessageBatch": _delete_message_batch,
    "ChangeMessageVisibilityBatch": _change_message_visibility_batch,
    "ListDeadLetterSourceQueues": _list_dead_letter_source_queues,
    "StartMessageMoveTask": _start_message_move_task, "ListMessageMoveTasks": _list_message_move_tasks,
    "CancelMessageMoveTask": _cancel_message_move_task,
    "CreateQueue": _create_queue, "GetQueueUrl": _get_queue_url, "ListQueues": _list_queues,
    "DeleteQueue": _delete_queue, "GetQueueAttributes": _get_queue_attributes,
    "SetQueueAttributes": _set_queue_attributes, "SendMessage": _send_message,
    "ReceiveMessage": _receive_message, "DeleteMessage": _delete_message,
    "ChangeMessageVisibility": _change_message_visibility, "PurgeQueue": _purge_queue,
    "TagQueue": _tag_queue, "UntagQueue": _untag_queue, "ListQueueTags": _list_queue_tags,
}


_NEEDS_LAMBDA = {"SendMessage", "SendMessageBatch"}


def dispatch(store: MessagingStore, target: str, payload: dict | None = None, lam_store=None) -> SqsResponse:
    """Native AWS SQS JSON protocol router. `target` is the X-Amz-Target header,
    e.g. "AmazonSQS.SendMessage". `lam_store` (optional) is the Lambda function/trigger
    registry, needed only so SendMessage(Batch) can fire an active Lambda trigger or
    EventBridge Pipe targeting a Lambda function (see `_fire_triggers`)."""
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    if not action:
        return _error("com.amazonaws.sqs#MissingAction", "Missing X-Amz-Target.", 400)
    op = _OPS.get(action)
    if op is None:
        return _error("com.amazonaws.sqs#UnknownOperation", f"Unknown operation {action}.", 400)
    try:
        if action in _NEEDS_LAMBDA:
            return op(store, body, lam_store)
        return op(store, body)
    except SqsError as e:
        return _error(e.code, e.message, e.status)


def _error(code: str, message: str, status: int = 400) -> SqsResponse:
    return SqsResponse(status=status, body={"__type": code, "message": message},
                       headers={"x-amzn-requestid": _req_id()})


# ── legacy Query protocol (form-encoded Action=…, XML responses) ────────────
SQS_XML_NS = "http://queue.amazonaws.com/doc/2012-11-05/"

# JSON-protocol error code → the Query-protocol code the SDKs map to the same exception.
_QUERY_ERROR_CODE = {
    "QueueDoesNotExist": "AWS.SimpleQueueService.NonExistentQueue",
    "QueueAlreadyExists": "QueueAlreadyExists",
    "PurgeQueueInProgress": "AWS.SimpleQueueService.PurgeQueueInProgress",
    "EmptyBatchRequest": "AWS.SimpleQueueService.EmptyBatchRequest",
    "TooManyEntriesInBatchRequest": "AWS.SimpleQueueService.TooManyEntriesInBatchRequest",
    "BatchEntryIdsNotDistinct": "AWS.SimpleQueueService.BatchEntryIdsNotDistinct",
    "UnsupportedOperation": "AWS.SimpleQueueService.UnsupportedOperation",
}

_SCALARS = ("QueueName", "QueueUrl", "MessageBody", "DelaySeconds", "MaxNumberOfMessages",
            "VisibilityTimeout", "WaitTimeSeconds", "ReceiptHandle", "MessageGroupId",
            "MessageDeduplicationId", "QueueNamePrefix", "MaxResults", "NextToken",
            "QueueOwnerAWSAccountId", "SourceArn", "DestinationArn", "TaskHandle",
            "MaxNumberOfMessagesPerSecond", "ReceiveRequestAttemptId")


def _indexed(params: dict, prefix: str) -> list[tuple[int, str, str]]:
    """`Prefix.N.Rest=v` → [(N, Rest, v)] (Rest may be "" for `Prefix.N=v`)."""
    out = []
    plen = len(prefix) + 1
    for k, v in params.items():
        if not k.startswith(prefix + "."):
            continue
        num, _, rest = k[plen:].partition(".")
        if num.isdigit():
            out.append((int(num), rest, v))
    return sorted(out)


def _group(params: dict, prefix: str) -> list[dict]:
    rows: dict[int, dict] = {}
    for n, rest, v in _indexed(params, prefix):
        rows.setdefault(n, {})[rest] = v
    return [rows[n] for n in sorted(rows)]


def _msg_attrs(flat: dict, prefix: str = "MessageAttribute") -> dict:
    out = {}
    for row in _group(flat, prefix):
        name = row.get("Name")
        if not name:
            continue
        a = {"DataType": row.get("Value.DataType", "String")}
        if "Value.StringValue" in row:
            a["StringValue"] = row["Value.StringValue"]
        if "Value.BinaryValue" in row:
            a["BinaryValue"] = row["Value.BinaryValue"]
        out[name] = a
    return out


def query_to_json(params: dict) -> tuple[str, dict]:
    """Flattened Query params → (action, JSON-protocol body)."""
    action = str(params.get("Action", "")).strip()
    body: dict = {k: params[k] for k in _SCALARS if k in params}
    for k in ("DelaySeconds", "MaxNumberOfMessages", "VisibilityTimeout", "WaitTimeSeconds",
              "MaxResults", "MaxNumberOfMessagesPerSecond"):
        if k in body:
            try:
                body[k] = int(body[k])
            except (TypeError, ValueError):
                pass
    attrs = {r["Name"]: r.get("Value", "") for r in _group(params, "Attribute") if r.get("Name")}
    if attrs:
        body["Attributes"] = attrs
    names = [v for _, rest, v in _indexed(params, "AttributeName") if not rest]
    if names:
        body["AttributeNames"] = names
    sys_names = [v for _, rest, v in _indexed(params, "MessageSystemAttributeName") if not rest]
    if sys_names:
        body["MessageSystemAttributeNames"] = sys_names
    man = [v for _, rest, v in _indexed(params, "MessageAttributeName") if not rest]
    if man:
        body["MessageAttributeNames"] = man
    mattrs = _msg_attrs(params)
    if mattrs:
        body["MessageAttributes"] = mattrs
    tags = {r["Key"]: r.get("Value", "") for r in _group(params, "Tag") if r.get("Key")}
    if tags:
        body["Tags" if action == "TagQueue" else "tags"] = tags
    keys = [v for _, rest, v in _indexed(params, "TagKey") if not rest]
    if keys:
        body["TagKeys"] = keys
    for prefix in ("SendMessageBatchRequestEntry", "DeleteMessageBatchRequestEntry",
                   "ChangeMessageVisibilityBatchRequestEntry"):
        rows = _group(params, prefix)
        if rows:
            entries = []
            for r in rows:
                e = {k: v for k, v in r.items() if "." not in k}
                for k in ("DelaySeconds", "VisibilityTimeout"):
                    if k in e:
                        try:
                            e[k] = int(e[k])
                        except (TypeError, ValueError):
                            pass
                ma = _msg_attrs(_sub_flat(r))
                if ma:
                    e["MessageAttributes"] = ma
                entries.append(e)
            body["Entries"] = entries
    return action, body


def _sub_flat(row: dict) -> dict:
    return {k: v for k, v in row.items() if k.startswith("MessageAttribute.")}


def _x(tag: str, val) -> str:
    return f"<{tag}>{_xml_escape(str(val))}</{tag}>"


def _xml_result(action: str, body: dict) -> str:
    b = body or {}
    if action in ("CreateQueue", "GetQueueUrl"):
        inner = _x("QueueUrl", b.get("QueueUrl", ""))
    elif action == "ListQueues":
        inner = "".join(_x("QueueUrl", u) for u in b.get("QueueUrls") or [])
    elif action == "ListDeadLetterSourceQueues":
        inner = "".join(_x("QueueUrl", u) for u in b.get("queueUrls") or [])
    elif action == "GetQueueAttributes":
        inner = "".join(f"<Attribute>{_x('Name', k)}{_x('Value', v)}</Attribute>"
                        for k, v in (b.get("Attributes") or {}).items())
    elif action == "SendMessage":
        inner = "".join(_x(k, b[k]) for k in ("MD5OfMessageBody", "MD5OfMessageAttributes",
                                              "MessageId", "SequenceNumber") if k in b)
    elif action == "ReceiveMessage":
        parts = []
        for m in b.get("Messages") or []:
            x = "".join(_x(k, m[k]) for k in ("MessageId", "ReceiptHandle", "MD5OfBody", "Body") if k in m)
            if m.get("MD5OfMessageAttributes"):
                x += _x("MD5OfMessageAttributes", m["MD5OfMessageAttributes"])
            x += "".join(f"<Attribute>{_x('Name', k)}{_x('Value', v)}</Attribute>"
                         for k, v in (m.get("Attributes") or {}).items())
            for k, a in (m.get("MessageAttributes") or {}).items():
                val = "".join(_x(f, a[f]) for f in ("StringValue", "BinaryValue") if a.get(f) is not None)
                x += f"<MessageAttribute>{_x('Name', k)}<Value>{val}{_x('DataType', a.get('DataType', 'String'))}</Value></MessageAttribute>"
            parts.append(f"<Message>{x}</Message>")
        inner = "".join(parts)
    elif action == "ListQueueTags":
        inner = "".join(f"<Tag>{_x('Key', k)}{_x('Value', v)}</Tag>" for k, v in (b.get("Tags") or {}).items())
    elif action in ("SendMessageBatch", "DeleteMessageBatch", "ChangeMessageVisibilityBatch"):
        ok_tag = action + "ResultEntry"
        inner = "".join(f"<{ok_tag}>" + "".join(_x(k, v) for k, v in e.items()) + f"</{ok_tag}>"
                        for e in b.get("Successful") or [])
        inner += "".join("<BatchResultErrorEntry>" + "".join(
            _x(k, str(v).lower() if isinstance(v, bool) else v) for k, v in e.items()) + "</BatchResultErrorEntry>"
            for e in b.get("Failed") or [])
    elif action == "StartMessageMoveTask":
        inner = _x("TaskHandle", b.get("TaskHandle", ""))
    elif action == "CancelMessageMoveTask":
        inner = _x("ApproximateNumberOfMessagesMoved", b.get("ApproximateNumberOfMessagesMoved", 0))
    elif action == "ListMessageMoveTasks":
        inner = "".join("<ListMessageMoveTasksResultEntry>" + "".join(_x(k, v) for k, v in t.items())
                        + "</ListMessageMoveTasksResultEntry>" for t in b.get("Results") or [])
    else:
        inner = ""
    result = f"<{action}Result>{inner}</{action}Result>" if inner or action in (
        "ListQueues", "ReceiveMessage", "ListQueueTags", "GetQueueAttributes", "ListDeadLetterSourceQueues",
        "SendMessageBatch", "DeleteMessageBatch", "ChangeMessageVisibilityBatch", "ListMessageMoveTasks") else ""
    return (f'<?xml version="1.0"?><{action}Response xmlns="{SQS_XML_NS}">{result}'
            f"<ResponseMetadata><RequestId>{_req_id()}</RequestId></ResponseMetadata></{action}Response>")


def dispatch_query(store: MessagingStore, params: dict | None = None, lam_store=None) -> tuple[int, str]:
    """Legacy Query-protocol router → (status, XML). Same operations, same state as
    `dispatch`; errors come back as the native `<ErrorResponse>`."""
    params = dict(params or {})
    action, body = query_to_json(params)
    if not action:
        return _query_error("MissingAction", "The request must contain the parameter Action.", 400)
    r = dispatch(store, "AmazonSQS." + action, body, lam_store=lam_store)
    if r.status >= 400:
        code = str(r.body.get("__type", "InternalError")).split("#")[-1]
        return _query_error(_QUERY_ERROR_CODE.get(code, code), str(r.body.get("message", "")), r.status)
    return 200, _xml_result(action, r.body)


def _query_error(code: str, message: str, status: int) -> tuple[int, str]:
    return status, (f'<?xml version="1.0"?><ErrorResponse xmlns="{SQS_XML_NS}"><Error><Type>Sender</Type>'
                    f"{_x('Code', code)}{_x('Message', message)}<Detail/></Error>"
                    f"<RequestId>{_req_id()}</RequestId></ErrorResponse>")
