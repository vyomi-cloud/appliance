"""Glass-box call capture — the flagship Inspector's data source.

Implements §12 of docs/CONSOLE-UX-REDESIGN.md for the console-next P0 vertical.

A single ASGI middleware taps every request/response, resolves service/action the
same way the router does (host + path + X-Amz-Target + Query Action), stamps
latency, redacts credentials at tap time (§12.7), and pushes an immutable event
(the §12.2 schema) onto an in-memory ring buffer (newest first, default 500).

An SSE endpoint streams new events to the Lit Inspector. Zero persistence by
default — it is the user's own sandbox.

This module is fully additive: it does NOT modify the existing `_record_usage`
seam or any handler. It observes at the ASGI boundary only.

The SAME event schema is intended to be emitted by the Nano SW/router interceptor
(§15.1 guarantee #5), so the Inspector UI is byte-for-byte identical across
substrates. Keep the schema here authoritative.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional
from urllib.parse import parse_qs

# ── Config ────────────────────────────────────────────────────────────────
_RING_MAX = int(os.environ.get("VYOMI_GLASSBOX_RING", "500") or "500")
_BODY_CAP = int(os.environ.get("VYOMI_GLASSBOX_BODY_CAP", "2048") or "2048")  # bytes summarised

# Paths we never capture: the glass-box's own plumbing, static assets, health.
_SKIP_PREFIXES = (
    "/api/console/calls",      # our own SSE + buffer endpoints (avoid feedback loop)
    "/assets/",
    "/console-next",           # the SPA shell + its vendored assets
    "/healthz",
    "/favicon.ico",
)

# Header names redacted at tap time — never stored (§12.7).
_REDACT_HEADERS = {
    "authorization",
    "x-amz-security-token",
    "x-amz-content-sha256",
    "cookie",
    "set-cookie",
    "x-vyomi-license",
    "x-cloudlearn-license",
    "proxy-authorization",
}


# ── ULID-ish monotonic id ───────────────────────────────────────────────────
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_id_lock = threading.Lock()
_last_ts = 0
_last_rand = 0


def _ulid() -> str:
    """A monotonic, sortable id (ULID-shaped). Good enough for ordering + deep-links."""
    global _last_ts, _last_rand
    with _id_lock:
        now_ms = int(time.time() * 1000)
        if now_ms <= _last_ts:
            _last_rand += 1
            now_ms = _last_ts
        else:
            _last_ts = now_ms
            _last_rand = int.from_bytes(os.urandom(5), "big")
        ts = now_ms
        rnd = _last_rand
    out = []
    t = ts
    for _ in range(10):
        out.append(_CROCKFORD[t & 31])
        t >>= 5
    r = rnd
    for _ in range(16):
        out.append(_CROCKFORD[r & 31])
        r >>= 5
    return "call_" + "".join(reversed(out))


# ── Ring buffer + subscribers ────────────────────────────────────────────────
class _Ring:
    """Thread-safe, fixed-size, newest-first ring buffer with async fan-out."""

    def __init__(self, maxlen: int):
        self._dq: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._subscribers: List[asyncio.Queue] = []
        self._sub_lock = threading.Lock()

    def push(self, event: Dict[str, Any]) -> None:
        with self._lock:
            self._dq.appendleft(event)
        # Fan out to any live SSE subscribers (non-blocking).
        with self._sub_lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def snapshot(self, limit: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._dq)
        if limit and limit > 0:
            return items[:limit]
        return items

    def clear(self) -> None:
        with self._lock:
            self._dq.clear()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._sub_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._sub_lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass


RING = _Ring(_RING_MAX)


# ── Service / action resolution (mirrors the router's dispatch) ──────────────
def _decode_headers(raw: List) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in raw or []:
        try:
            out[k.decode("latin-1").lower()] = v.decode("latin-1")
        except Exception:
            continue
    return out


def _redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    red: Dict[str, str] = {}
    for k, v in headers.items():
        if k in _REDACT_HEADERS:
            red[k] = "‹redacted›"
        else:
            red[k] = v
    return red


def _principal_from_auth(headers: Dict[str, str]) -> Optional[str]:
    """Extract ONLY the SigV4 access-key id — never the secret (§12.7)."""
    auth = headers.get("authorization", "")
    # AWS4-HMAC-SHA256 Credential=AKIA.../20260927/us-east-1/s3/aws4_request, ...
    if "Credential=" in auth:
        try:
            cred = auth.split("Credential=", 1)[1].split(",", 1)[0]
            return cred.split("/", 1)[0]
        except Exception:
            return None
    return None


def _resolve_service_action(method: str, path: str, headers: Dict[str, str],
                            query: Dict[str, List[str]]) -> tuple:
    """Best-effort resolution of (cloud, service, action) using the same signals
    the router uses: host + path + X-Amz-Target + Query Action.

    Deliberately conservative — returns ("aws"|"gcp"|"azure"|"vyomi", service, action).
    """
    xamz = headers.get("x-amz-target", "")
    xms = headers.get("x-ms-version", "")
    cloud = "aws"

    # X-Amz-Target => "Service_Version.Operation" (DynamoDB, KMS, Secrets, etc.)
    if xamz:
        svc_part, _, op = xamz.partition(".")
        svc = svc_part.split("_", 1)[0].lower()
        svc_map = {
            "dynamodb": "dynamodb", "trentservice": "kms",
            "secretsmanager": "secretsmanager", "amazonsqs": "sqs",
        }
        return (cloud, svc_map.get(svc, svc or "aws"), op or "")

    # Azure signature.
    if xms:
        cloud = "azure"

    # console-next / vyomi control-plane REST API.
    if path.startswith("/api/console/"):
        return ("vyomi", "console", path.rsplit("/", 1)[-1] or "console")

    # S3 console REST API: /api/s3/buckets[/{name}[/objects[/{key}]]]
    if path.startswith("/api/s3/"):
        seg = [p for p in path.split("/") if p]
        action = "S3"
        if "objects" in seg:
            if path.endswith("/download"):
                action = "GetObject"
            elif path.endswith("/meta"):
                action = "HeadObject"
            elif method == "POST":
                action = "PutObject"
            elif method == "DELETE":
                action = "DeleteObject"
            else:
                action = "ListObjects"
        elif "buckets" in seg:
            if method == "POST":
                action = "CreateBucket"
            elif method == "DELETE":
                action = "DeleteBucket"
            elif len(seg) >= 4:
                action = "HeadBucket"
            else:
                action = "ListBuckets"
        return ("aws", "s3", action)

    # Native S3 path-style: /{bucket}/{key} or /{bucket}
    if not path.startswith("/api/") and path != "/" and not path.startswith("/console"):
        q_action = (query.get("Action") or query.get("action") or [None])[0]
        if q_action:
            return (cloud, "s3", q_action)
        s3_action = {
            "GET": "ListObjects", "PUT": "PutObject",
            "HEAD": "HeadObject", "DELETE": "DeleteObject", "POST": "PostObject",
        }.get(method, method)
        return ("aws", "s3", s3_action)

    # AWS Query-protocol control plane (EC2/RDS/IAM/SNS): Action=... in the body/query.
    q_action = (query.get("Action") or [None])[0]
    if q_action:
        return (cloud, path.strip("/").split("/")[0] or "aws", q_action)

    return (cloud, "http", (path.strip("/").split("/")[0] or method))


# ── Explainer (deterministic, offline — §12.5, common cases) ─────────────────
_ERROR_EXPLAIN = {
    "NoSuchKey": ("that object key doesn't exist in the bucket yet",
                  "check the key spelling and that a PutObject wrote it to THIS bucket"),
    "NoSuchBucket": ("that bucket doesn't exist",
                     "create it first (CreateBucket) or check the bucket name"),
    "BucketAlreadyOwnedByYou": ("you already own a bucket with this name",
                                "reuse the existing bucket or pick another name"),
    "BucketNotEmpty": ("the bucket still has objects",
                       "empty the bucket (or pass force) before deleting it"),
    "AccessDenied": ("the request was denied by policy",
                     "check the IAM policy evaluated for this principal"),
    "InvalidBucketName": ("the bucket name is not a valid S3 name",
                          "use 3-63 lowercase chars, no underscores"),
}


def _explain(status: int, code: Optional[str], service: str, action: str) -> Dict[str, Any]:
    if status < 400:
        return {"level": "ok", "why": "", "hint": "", "related": []}
    level = "error" if status >= 500 else "warn"
    if code and code in _ERROR_EXPLAIN:
        why, hint = _ERROR_EXPLAIN[code]
        return {"level": level, "why": why, "hint": hint, "related": []}
    generic = {
        400: ("the request was malformed or failed validation", "check required fields and formats"),
        403: ("access denied", "check credentials and the evaluated policy"),
        404: ("the resource was not found", "create it first or check the identifier"),
        409: ("a conflict with existing state", "the resource may already exist or be in use"),
        429: ("throttled — too many requests", "back off and retry with jitter"),
    }
    if status in generic:
        why, hint = generic[status]
    elif status >= 500:
        why, hint = ("the backend errored serving this call", "inspect the response body; retry")
    else:
        why, hint = (f"HTTP {status}", "see the response body for details")
    return {"level": level, "why": why, "hint": hint, "related": []}


# ── backend.ref resolver (the call → real-backend deep-link seam, §12.4) ─────
def _json_field(body: bytes, *names) -> Optional[str]:
    """Pull a string field from a (capped) JSON body — used to recover the object key
    from the collection-POST upload, where the key lives in the body, not the URL."""
    if not body:
        return None
    try:
        data = json.loads(body[:_BODY_CAP].decode("utf-8", errors="replace") or "{}")
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    for n in names:
        v = data.get(n)
        if isinstance(v, str) and v:
            return v
    return None


def _backend_ref(service: str, action: str, method: str, path: str,
                 req_body: bytes = b"", resp_body: bytes = b"") -> Dict[str, Any]:
    """Produce {kind, served_by, ref} — the typed handle the Inspector turns into a
    one-click deep-link into the State tab / resource detail. P0 wires S3 fully."""
    if service == "s3":
        bucket = None
        key = None
        if path.startswith("/api/s3/buckets/"):
            rest = path[len("/api/s3/buckets/"):]
            parts = rest.split("/objects/", 1)
            bucket = parts[0].split("/", 1)[0] or None
            if len(parts) == 2:
                key = parts[1]
                for suffix in ("/download", "/meta", "/versions"):
                    if key.endswith(suffix):
                        key = key[: -len(suffix)]
                        break
            elif rest.rstrip("/").endswith("/objects") and method == "POST":
                # collection-POST upload — key is in the request body (SPA multipart
                # sets a filename; JSON path sets "key"/"name"). Recover it so the
                # PutObject 200 → click → real bytes deep-link works (§12.4).
                key = _json_field(req_body, "key", "name") or None
        elif not path.startswith("/api/"):
            seg = [p for p in path.split("/") if p]
            if seg:
                bucket = seg[0]
                if len(seg) > 1:
                    key = "/".join(seg[1:])
        ref: Dict[str, Any] = {"type": "s3.bucket" if not key else "s3.object"}
        if bucket:
            ref["bucket"] = bucket
        if key:
            ref["key"] = key
        return {"kind": "minio", "served_by": "s3_core", "ref": ref}

    served = {
        "dynamodb": ("dynamodb-local", "dynamodb_core"),
        "kms": ("vault", "kms_core"),
        "secretsmanager": ("vault", "secrets_core"),
        "sqs": ("nats", "sqs_core"),
        "rds": ("mysql/postgres", "rds_core"),
        "iam": ("in-proc", "iam_core"),
    }.get(service)
    if served:
        return {"kind": served[0], "served_by": served[1], "ref": {"type": service}}
    return {"kind": "vyomi", "served_by": "server.py", "ref": {"type": service}}


def _summarise_body(body: bytes, content_type: str) -> str:
    if not body:
        return ""
    capped = body[:_BODY_CAP]
    truncated = len(body) > _BODY_CAP
    ct = (content_type or "").lower()
    text_like = any(t in ct for t in ("json", "text", "xml", "urlencoded", "html")) or not ct
    if text_like:
        try:
            s = capped.decode("utf-8", errors="replace")
        except Exception:
            s = f"‹{len(body)} bytes {ct}›"
    else:
        s = f"‹binary {len(body)} bytes {ct or 'application/octet-stream'}›"
    if truncated:
        s += f" …(+{len(body) - _BODY_CAP}B)"
    return s


def _extract_error_code(status: int, resp_body: bytes, content_type: str) -> Optional[str]:
    if status < 400 or not resp_body:
        return None
    head = resp_body[:_BODY_CAP]
    ct = (content_type or "").lower()
    try:
        if "json" in ct:
            data = json.loads(head.decode("utf-8", errors="replace") or "{}")
            if isinstance(data, dict):
                det = data.get("detail")
                if isinstance(det, str):
                    return det.split(" ", 1)[0].strip() or None
                for k in ("code", "Code", "__type", "errorCode"):
                    if data.get(k):
                        return str(data[k]).split("#")[-1]
        else:
            txt = head.decode("utf-8", errors="replace")
            if "<Code>" in txt:
                return txt.split("<Code>", 1)[1].split("</Code>", 1)[0].strip() or None
    except Exception:
        return None
    return None


# ── ASGI capture middleware ──────────────────────────────────────────────────
class GlassBoxCaptureMiddleware:
    """Pure-ASGI middleware. Taps request line + headers + (capped) bodies and the
    response status/headers/body, builds a §12.2 event, redacts, and rings it.

    Registered as the OUTERMOST layer in server.py so it sees the final status.
    O(1) per call: bodies are summarised lazily and capped at _BODY_CAP bytes.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "") or ""
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await self.app(scope, receive, send)

        method = scope.get("method", "GET")
        req_headers = _decode_headers(scope.get("headers") or [])
        raw_qs = scope.get("query_string", b"") or b""
        try:
            query = parse_qs(raw_qs.decode("latin-1"))
        except Exception:
            query = {}

        # ── capture (capped) request body while re-delivering it downstream ──
        req_body_parts: List[bytes] = []
        req_body_len = 0

        async def _wrapped_receive():
            nonlocal req_body_len
            message = await receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"") or b""
                if req_body_len < _BODY_CAP:
                    req_body_parts.append(chunk[: _BODY_CAP - req_body_len])
                    req_body_len += len(chunk)
            return message

        # ── capture response status/headers/(capped) body ──
        resp_status = 0
        resp_headers: Dict[str, str] = {}
        resp_body_parts: List[bytes] = []
        resp_body_len = 0
        start = time.perf_counter()

        async def _wrapped_send(message):
            nonlocal resp_status, resp_headers, resp_body_len
            mt = message.get("type")
            if mt == "http.response.start":
                resp_status = message.get("status", 0)
                resp_headers = _decode_headers(message.get("headers") or [])
            elif mt == "http.response.body":
                chunk = message.get("body", b"") or b""
                if resp_body_len < _BODY_CAP:
                    resp_body_parts.append(chunk[: _BODY_CAP - resp_body_len])
                    resp_body_len += len(chunk)
            return await send(message)

        error: Optional[BaseException] = None
        try:
            await self.app(scope, _wrapped_receive, _wrapped_send)
        except BaseException as exc:  # noqa: BLE001 — record then re-raise
            error = exc
            if resp_status == 0:
                resp_status = 500
            raise
        finally:
            try:
                self._emit(method, path, req_headers, query,
                           b"".join(req_body_parts), resp_status, resp_headers,
                           b"".join(resp_body_parts),
                           (time.perf_counter() - start) * 1000.0, error)
            except Exception:
                pass  # never let capture break the request

    def _emit(self, method, path, req_headers, query, req_body, status,
              resp_headers, resp_body, ms, error):
        cloud, service, action = _resolve_service_action(method, path, req_headers, query)
        req_ct = req_headers.get("content-type", "")
        resp_ct = resp_headers.get("content-type", "")
        code = _extract_error_code(status, resp_body, resp_ct)
        backend = _backend_ref(service, action, method, path, req_body, resp_body)
        explain = _explain(status, code, service, action)
        if error is not None and status >= 500:
            explain = {"level": "error", "why": f"unhandled server error: {type(error).__name__}",
                       "hint": "check the server logs / traceback", "related": []}

        event = {
            "id": _ulid(),
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "cloud": cloud,
            "service": service,
            "action": action,
            "http": {
                "method": method,
                "path": path,
                "status": int(status or 0),
                "ms": round(ms, 1),
            },
            "principal": _principal_from_auth(req_headers) or "test",
            "request": {
                "headers": _redact_headers(req_headers),
                "query": {k: v for k, v in query.items() if k.lower() not in ("x-amz-signature", "signature")},
                "body_summary": _summarise_body(req_body, req_ct),
            },
            "response": {
                "code": code,
                "headers": _redact_headers(resp_headers),
                "body_summary": _summarise_body(resp_body, resp_ct),
            },
            "backend": backend,
            "explain": explain,
            "snapshot_id": None,   # populated once snapshot engine lands (P2)
        }
        RING.push(event)


# ── SSE stream generator ─────────────────────────────────────────────────────
async def sse_stream(replay: int = 50):
    """Async generator yielding SSE frames. Sends a backlog (newest-first, up to
    `replay`) then streams live events. Used by the /api/console/calls/stream route.
    """
    q = RING.subscribe()
    try:
        backlog = RING.snapshot(limit=replay)
        for ev in reversed(backlog):
            yield f"event: call\ndata: {json.dumps(ev)}\n\n"
        yield f"event: ready\ndata: {json.dumps({'buffered': len(backlog)})}\n\n"
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=15.0)
                yield f"event: call\ndata: {json.dumps(ev)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        RING.unsubscribe(q)
