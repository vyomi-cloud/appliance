# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure Storage Queue data-plane core — substrate-independent, the Azure
analogue of core/gcp_storage_core.py. Speaks the native **Azure Storage Queue
REST API** so the native `azure-storage-queue` SDK (QueueServiceClient /
QueueClient) works unchanged against it (point it at the endpoint via the
account URL, Azurite-style `http://host/devstoreaccount1`).

NO fastapi / azure / socket / subprocess imports → loads under Pyodide.
Self-contained in-memory `AzureQueueStore` lives in this module; nothing else
is required.

Wire is XML. Scope:
  - create queue          PUT  /{queue}                              -> 201
  - delete queue          DELETE /{queue}                            -> 204
  - list queues           GET  /?comp=list                           -> 200 XML
  - queue metadata        GET  /{queue}?comp=metadata                -> 200 (header count)
  - put message           POST /{queue}/messages  (<QueueMessage>)   -> 201 XML
  - get/dequeue messages  GET  /{queue}/messages?numofmessages=N     -> 200 XML (invisible)
  - peek messages         GET  /{queue}/messages?peekonly=true       -> 200 XML
  - delete message        DELETE /{queue}/messages/{id}?popreceipt=  -> 204

An OPTIONAL leading /{account} segment (e.g. /devstoreaccount1/) is tolerated.
Errors: HTTP status + `x-ms-error-code` header + <Error><Code>...</Code></Error>.
"""
from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class Response:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/xml"


# ── time helpers ──────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rfc1123(dt: datetime) -> str:
    # e.g. "Mon, 13 Jul 2026 12:34:56 GMT"
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")


# ── message model ─────────────────────────────────────────────────────────
@dataclass
class _Message:
    message_id: str
    text: str                       # raw MessageText as sent (usually base64)
    insertion_time: datetime
    expiration_time: datetime
    time_next_visible: datetime
    pop_receipt: str
    dequeue_count: int = 0


class AzureQueueStore:
    """In-memory queue account. `queues` maps queue-name -> dict with
    'metadata' and 'messages' (list of _Message, insertion order)."""

    def __init__(self) -> None:
        self.queues: dict[str, dict] = {}

    # queue ops -------------------------------------------------------------
    def queue_exists(self, name: str) -> bool:
        return name in self.queues

    def create_queue(self, name: str, metadata: dict | None = None) -> None:
        self.queues[name] = {"metadata": metadata or {}, "messages": []}

    def delete_queue(self, name: str) -> None:
        self.queues.pop(name, None)

    def messages(self, name: str) -> list:
        return self.queues[name]["messages"]

    def persist(self) -> None:
        """Write-through hook (no-op in-memory; a backed subclass overrides it)."""

    # approximate count = messages whose time_next_visible is in the past
    # (Azure counts every message not currently past expiration). We report
    # all live (non-expired) messages, matching x-ms-approximate-messages-count.
    def approximate_count(self, name: str) -> int:
        now = _now()
        return sum(1 for m in self.queues[name]["messages"] if m.expiration_time > now)


# ── XML helpers ───────────────────────────────────────────────────────────
def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _xml(body: str) -> bytes:
    return ('<?xml version="1.0" encoding="utf-8"?>' + body).encode("utf-8")


def _err(status: int, code: str, message: str) -> Response:
    body = _xml(f"<Error><Code>{_esc(code)}</Code>"
                f"<Message>{_esc(message)}</Message></Error>")
    return Response(status=status, headers={"x-ms-error-code": code}, body=body)


def _extract_message_text(body: bytes) -> str:
    """Pull MessageText out of <QueueMessage><MessageText>..</MessageText>."""
    if not body:
        return ""
    text = body.decode("utf-8", "replace")
    m = re.search(r"<MessageText>(.*?)</MessageText>", text, re.DOTALL)
    if not m:
        return ""
    raw = m.group(1)
    # unescape the few XML entities we escape on the way out
    return (raw.replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&"))


def _reap_expired(store: AzureQueueStore, name: str) -> None:
    now = _now()
    msgs = store.queues[name]["messages"]
    store.queues[name]["messages"] = [m for m in msgs if m.expiration_time > now]
    store.persist()


# ── dispatch ──────────────────────────────────────────────────────────────
def dispatch(store: AzureQueueStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> Response:
    query = query or {}
    headers = {(k or "").lower(): v for k, v in (headers or {}).items()}
    method = method.upper()

    p = path.split("?", 1)[0]
    segs = [s for s in p.split("/") if s != ""]

    # Optional leading /{account} (Azurite: /devstoreaccount1/...). Heuristic:
    # if the request targets the service root (comp=list) OR a queue, the first
    # segment may be an account. We treat a leading segment as an account when
    # there is more than one segment, or when it looks like a known dev account.
    # Concretely: strip a leading account when the *next* segment is 'messages',
    # is a comp target, or when comp=list is the service-root call.
    comp = query.get("comp")

    # service-root list: GET /?comp=list   OR  GET /{account}?comp=list
    if comp == "list" and method == "GET":
        # any single leading segment here is the account name → ignore it.
        return _list_queues(store, query)

    # Decide whether segs[0] is an account. If the path has 2+ segments and the
    # last is 'messages' or a message-id under messages, the first is account
    # only when there are 3+ segments (account/queue/messages). We disambiguate
    # by checking for the literal 'messages' segment.
    if "messages" in segs:
        mi = segs.index("messages")
        # queue is the segment immediately before 'messages'
        if mi >= 1:
            queue = segs[mi - 1]
            tail = segs[mi + 1:]        # optional message-id
            return _message_op(store, method, queue, tail, query, headers, body)
        return _err(400, "InvalidUri", "Malformed messages path.")

    # No 'messages' segment → queue-level op on /{queue} or /{account}/{queue}.
    if not segs:
        return _err(400, "InvalidUri", "No queue specified.")
    # If two segments and no comp on the account, treat first as account.
    queue = segs[-1]
    return _queue_op(store, method, queue, query, headers, body)


# ── queue-level ops ───────────────────────────────────────────────────────
def _list_queues(store: AzureQueueStore, query: dict) -> Response:
    prefix = query.get("prefix", "")
    rows = []
    for name in sorted(store.queues):
        if prefix and not name.startswith(prefix):
            continue
        rows.append(f"<Queue><Name>{_esc(name)}</Name></Queue>")
    body = _xml(
        '<EnumerationResults>'
        f'<Prefix>{_esc(prefix)}</Prefix>'
        '<Queues>' + "".join(rows) + '</Queues>'
        '<NextMarker />'
        '</EnumerationResults>'
    )
    return Response(status=200, body=body)


def _queue_op(store: AzureQueueStore, method: str, queue: str,
              query: dict, headers: dict, body: bytes) -> Response:
    comp = query.get("comp")

    if method == "PUT":                      # create queue
        if store.queue_exists(queue):
            # Azure returns 204 if identical metadata, 409 otherwise. We treat a
            # plain re-create as a conflict (QueueAlreadyExists).
            return _err(409, "QueueAlreadyExists",
                        "The specified queue already exists.")
        meta = {k[len("x-ms-meta-"):]: v for k, v in headers.items()
                if k.startswith("x-ms-meta-")}
        store.create_queue(queue, meta)
        return Response(status=201, body=b"", media_type=None)

    if method == "DELETE":                   # delete queue
        if not store.queue_exists(queue):
            return _err(404, "QueueNotFound", "The specified queue does not exist.")
        store.delete_queue(queue)
        return Response(status=204, body=b"", media_type=None)

    if method == "GET" or method == "HEAD":  # get metadata / properties
        if not store.queue_exists(queue):
            return _err(404, "QueueNotFound", "The specified queue does not exist.")
        _reap_expired(store, queue)
        count = store.approximate_count(queue)
        hdrs = {
            "x-ms-approximate-messages-count": str(count),
            "date": _rfc1123(_now()),
        }
        for k, v in store.queues[queue]["metadata"].items():
            hdrs[f"x-ms-meta-{k}"] = v
        return Response(status=200, headers=hdrs, body=b"", media_type=None)

    return _err(400, "UnsupportedHttpVerb", f"Unsupported method {method}.")


# ── message-level ops ─────────────────────────────────────────────────────
def _message_op(store: AzureQueueStore, method: str, queue: str, tail: list,
                query: dict, headers: dict, body: bytes) -> Response:
    if not store.queue_exists(queue):
        return _err(404, "QueueNotFound", "The specified queue does not exist.")
    _reap_expired(store, queue)

    # DELETE /{queue}/messages/{messageid}?popreceipt=...
    if method == "DELETE":
        if not tail:
            # clear-messages: DELETE /{queue}/messages
            store.queues[queue]["messages"] = []
            store.persist()
            return Response(status=204, body=b"", media_type=None)
        message_id = tail[0]
        pop_receipt = query.get("popreceipt", "")
        msgs = store.queues[queue]["messages"]
        target = next((m for m in msgs if m.message_id == message_id), None)
        if target is None:
            return _err(404, "MessageNotFound", "The specified message does not exist.")
        if pop_receipt and target.pop_receipt != pop_receipt:
            return _err(400, "PopReceiptMismatch",
                        "The specified pop receipt did not match the "
                        "pop receipt for a dequeued message.")
        msgs.remove(target)
        store.persist()
        return Response(status=204, body=b"", media_type=None)

    # POST /{queue}/messages  → put message
    if method == "POST":
        text = _extract_message_text(body)
        now = _now()
        try:
            ttl = int(query.get("messagettl", "604800"))   # 7 days default
        except ValueError:
            ttl = 604800
        try:
            vis = int(query.get("visibilitytimeout", "0"))
        except ValueError:
            vis = 0
        msg = _Message(
            message_id=str(uuid.uuid4()),
            text=text,
            insertion_time=now,
            expiration_time=now + timedelta(seconds=ttl),
            time_next_visible=now + timedelta(seconds=vis),
            pop_receipt=base64.b64encode(uuid.uuid4().bytes).decode(),
            dequeue_count=0,
        )
        store.queues[queue]["messages"].append(msg)
        store.persist()
        row = (
            "<QueueMessage>"
            f"<MessageId>{_esc(msg.message_id)}</MessageId>"
            f"<InsertionTime>{_rfc1123(msg.insertion_time)}</InsertionTime>"
            f"<ExpirationTime>{_rfc1123(msg.expiration_time)}</ExpirationTime>"
            f"<PopReceipt>{_esc(msg.pop_receipt)}</PopReceipt>"
            f"<TimeNextVisible>{_rfc1123(msg.time_next_visible)}</TimeNextVisible>"
            "</QueueMessage>"
        )
        body_xml = _xml(f"<QueueMessagesList>{row}</QueueMessagesList>")
        return Response(status=201, body=body_xml)

    # GET /{queue}/messages  → get (dequeue) or peek
    if method == "GET":
        try:
            num = int(query.get("numofmessages", "1"))
        except ValueError:
            num = 1
        num = max(1, min(num, 32))
        peek = str(query.get("peekonly", "")).lower() == "true"
        try:
            vis = int(query.get("visibilitytimeout", "30"))
        except ValueError:
            vis = 30
        now = _now()
        rows = []
        picked = 0
        for m in store.queues[queue]["messages"]:
            if picked >= num:
                break
            if m.time_next_visible > now:      # currently invisible
                continue
            if peek:
                rows.append(
                    "<QueueMessage>"
                    f"<MessageId>{_esc(m.message_id)}</MessageId>"
                    f"<InsertionTime>{_rfc1123(m.insertion_time)}</InsertionTime>"
                    f"<ExpirationTime>{_rfc1123(m.expiration_time)}</ExpirationTime>"
                    f"<DequeueCount>{m.dequeue_count}</DequeueCount>"
                    f"<MessageText>{_esc(m.text)}</MessageText>"
                    "</QueueMessage>"
                )
            else:
                # dequeue: bump count, refresh pop receipt, hide for `vis` secs
                m.dequeue_count += 1
                m.pop_receipt = base64.b64encode(uuid.uuid4().bytes).decode()
                m.time_next_visible = now + timedelta(seconds=vis)
                store.persist()
                rows.append(
                    "<QueueMessage>"
                    f"<MessageId>{_esc(m.message_id)}</MessageId>"
                    f"<InsertionTime>{_rfc1123(m.insertion_time)}</InsertionTime>"
                    f"<ExpirationTime>{_rfc1123(m.expiration_time)}</ExpirationTime>"
                    f"<PopReceipt>{_esc(m.pop_receipt)}</PopReceipt>"
                    f"<TimeNextVisible>{_rfc1123(m.time_next_visible)}</TimeNextVisible>"
                    f"<DequeueCount>{m.dequeue_count}</DequeueCount>"
                    f"<MessageText>{_esc(m.text)}</MessageText>"
                    "</QueueMessage>"
                )
            picked += 1
        body_xml = _xml(f"<QueueMessagesList>{''.join(rows)}</QueueMessagesList>")
        return Response(status=200, body=body_xml)

    return _err(400, "UnsupportedHttpVerb", f"Unsupported method {method}.")
