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
            message_attributes: dict | None = None, delay_seconds: int = 0) -> dict:
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
    if not store.queue_exists(name):
        attrs = dict(body.get("Attributes") or {})
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
        })
        store.persist()
    return SqsResponse(body={"QueueUrl": _queue_url(store, name)})


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
    msg = enqueue(store, q, payload, body.get("MessageAttributes"), delay)
    store.persist()
    return SqsResponse(body={"MessageId": msg["message_id"], "MD5OfMessageBody": msg["md5_of_body"]})


def _receive_message(store, body):
    q = _require_queue(store, body.get("QueueUrl", ""))
    now = store.now()
    max_n = int(body.get("MaxNumberOfMessages", 1) or 1)
    vis = int(body.get("VisibilityTimeout", q.get("visibility_timeout", _DEFAULT_VISIBILITY)))
    out = []
    for msg in q["messages"]:
        if len(out) >= max_n:
            break
        if not _available(msg, now):
            continue
        msg["in_flight"] = True
        msg["receipt_handle"] = "rhdl-" + uuid.uuid4().hex
        msg["visible_at"] = now + vis
        msg["receive_count"] += 1
        out.append({
            "MessageId": msg["message_id"],
            "ReceiptHandle": msg["receipt_handle"],
            "MD5OfBody": msg["md5_of_body"],
            "Body": msg["body"],
            "Attributes": {"ApproximateReceiveCount": str(msg["receive_count"])},
            "MessageAttributes": msg.get("message_attributes", {}),
        })
    if out:
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
