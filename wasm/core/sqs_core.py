# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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

Scope (v1 slice): CreateQueue, GetQueueUrl, ListQueues, DeleteQueue,
GetQueueAttributes, SetQueueAttributes, SendMessage, ReceiveMessage,
DeleteMessage, ChangeMessageVisibility, PurgeQueue. FIFO ordering/dedup, DLQ
redrive, and batch ops reuse the same helpers and slot in next.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.messaging_store import MessagingStore, REGION

_DEFAULT_VISIBILITY = 30


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
    return f"https://sqs.{REGION}.amazonaws.com/{store.account_id}/{name}"


def _name_from_url(url: str) -> str:
    return (url or "").rstrip("/").split("/")[-1]


# ── shared enqueue primitive (used by SendMessage AND SNS fan-out) ─────────
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
    if not store.queue_exists(name):
        attrs = dict(body.get("Attributes") or {})
        is_fifo = name.endswith(".fifo") or str(attrs.get("FifoQueue", "")).lower() == "true"
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
    attrs = dict(q.get("attributes", {}))
    attrs.update({
        "QueueArn": q["queue_arn"],
        "ApproximateNumberOfMessages": str(visible),
        "ApproximateNumberOfMessagesNotVisible": str(not_visible),
        "VisibilityTimeout": str(q.get("visibility_timeout", _DEFAULT_VISIBILITY)),
    })
    return SqsResponse(body={"Attributes": attrs})


def _set_queue_attributes(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    incoming = dict(body.get("Attributes") or {})
    q.setdefault("attributes", {}).update(incoming)
    if "VisibilityTimeout" in incoming:
        q["visibility_timeout"] = int(incoming["VisibilityTimeout"])
    store.persist()
    return SqsResponse(body={})


# ── messages ─────────────────────────────────────────────────────────────
def _available(msg: dict, now: float) -> bool:
    return not msg.get("deleted") and msg.get("visible_at", 0) <= now


def _send_message(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    payload = body.get("MessageBody")
    if payload is None:
        raise SqsError("com.amazonaws.sqs#MissingParameter", "MessageBody is required.", 400)
    payload = str(payload)
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
        if dedup_id in seen:
            # Duplicate within the dedup window — accept but do not enqueue again.
            return SqsResponse(body={"MessageId": seen[dedup_id], "MD5OfMessageBody": _md5(payload),
                                     "SequenceNumber": "0"})
        # FIFO ignores per-message delay.
        delay = 0
    msg = enqueue(store, q, payload, body.get("MessageAttributes"), delay,
                  message_group_id=group_id, message_dedup_id=dedup_id)
    if q.get("fifo") and dedup_id:
        q["dedup_seen"][dedup_id] = msg["message_id"]
    store.persist()
    out = {"MessageId": msg["message_id"], "MD5OfMessageBody": msg["md5_of_body"]}
    if q.get("fifo"):
        out["SequenceNumber"] = str(len(q["messages"]))
    return SqsResponse(body=out)


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
                         "visible_at": now})
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
    vis = int(body.get("VisibilityTimeout", q.get("visibility_timeout", _DEFAULT_VISIBILITY)))
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
        if q.get("fifo") and grp:
            locked_groups.add(grp)   # lock the group for the rest of this batch
        attrs = {"ApproximateReceiveCount": str(msg["receive_count"])}
        if grp:
            attrs["MessageGroupId"] = grp
        out.append({
            "MessageId": msg["message_id"],
            "ReceiptHandle": msg["receipt_handle"],
            "MD5OfBody": msg["md5_of_body"],
            "Body": msg["body"],
            "Attributes": attrs,
            "MessageAttributes": msg.get("message_attributes", {}),
        })
    if out or _redrive_policy(q):
        store.persist()
    return SqsResponse(body={"Messages": out} if out else {})


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


_OPS = {
    "CreateQueue": _create_queue, "GetQueueUrl": _get_queue_url, "ListQueues": _list_queues,
    "DeleteQueue": _delete_queue, "GetQueueAttributes": _get_queue_attributes,
    "SetQueueAttributes": _set_queue_attributes, "SendMessage": _send_message,
    "ReceiveMessage": _receive_message, "DeleteMessage": _delete_message,
    "ChangeMessageVisibility": _change_message_visibility, "PurgeQueue": _purge_queue,
}


def dispatch(store: MessagingStore, target: str, payload: dict | None = None) -> SqsResponse:
    """Native AWS SQS JSON protocol router. `target` is the X-Amz-Target header,
    e.g. "AmazonSQS.SendMessage"."""
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    if not action:
        return _error("com.amazonaws.sqs#MissingAction", "Missing X-Amz-Target.", 400)
    op = _OPS.get(action)
    if op is None:
        return _error("com.amazonaws.sqs#UnknownOperation", f"Unknown operation {action}.", 400)
    try:
        return op(store, body)
    except SqsError as e:
        return _error(e.code, e.message, e.status)


def _error(code: str, message: str, status: int = 400) -> SqsResponse:
    return SqsResponse(status=status, body={"__type": code, "message": message},
                       headers={"x-amzn-requestid": _req_id()})
