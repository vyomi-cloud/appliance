"""GCP eventing, offline appliance: HTTP-triggered Cloud Functions + Eventarc delivery.

* `/gcf/{project}/{location}/{function}[/rest]` is the function's HTTPS trigger URL: the handler
  receives a Flask-like request and its return value is the HTTP response (status/headers/body as
  returned). The management envelope ({executionId,status,result,logs}) stays on `...:call`.
* Eventarc triggers fire: an ASGI tap watches object uploads (storage finalized) and Pub/Sub
  publishes that the appliance serves, matches them against the trigger's eventFilters and delivers a
  CloudEvent to the destination (Cloud Function, or an HTTP endpoint) in a background thread.
User code runs through core.gcp_function_runtime (subprocess per call, timeout, temp dir) - not in-process.
"""
from __future__ import annotations

import base64
import fnmatch
import json
import re
import threading
import time
import urllib.request
import uuid

from fastapi import Request
from fastapi.responses import Response

from core.app_context import gcp_functions_state

STORAGE_FINALIZED = "google.cloud.storage.object.v1.finalized"
PUBSUB_PUBLISHED = "google.cloud.pubsub.topic.v1.messagePublished"


def _now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _find_function(name: str) -> dict | None:
    return (gcp_functions_state.get("functions") or {}).get(name)


def _fn_params(fn: dict) -> tuple:
    timeout = int((fn.get("serviceConfig") or {}).get("timeoutSeconds") or fn.get("timeout") or 60)
    env = fn.get("environmentVariables") or {}
    env = {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}
    return (str(fn.get("code") or ""), str(fn.get("entryPoint") or fn.get("handler") or "hello_http"),
            str(fn.get("runtime") or "python311"), min(max(timeout, 1), 120), env)


def _record(fn: dict, kind: str, req: dict, out: dict) -> None:
    fn.setdefault("invocations", []).append({
        "id": "inv-" + uuid.uuid4().hex[:12], "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "request": req, "response": out.get("body", b"")[:2000].decode("utf-8", "replace") if isinstance(out.get("body"), bytes) else None,
        "status": "SUCCESS" if out.get("ok") else "ERROR", "error": out.get("error", ""), "logs": out.get("logs", ""),
        "source": kind})
    fn["invocations"] = fn["invocations"][-200:]


def invoke_http(fn: dict, method: str, path: str, query: str, headers: dict, body: bytes, url: str = "") -> dict:
    from core import gcp_function_runtime as rt
    code, entry, runtime, timeout, env = _fn_params(fn)
    out = rt.execute_http(code, entry, runtime, {
        "method": method, "path": path or "/", "query": query or "", "headers": headers,
        "body_b64": base64.b64encode(body or b"").decode(), "url": url}, timeout=timeout, env=env)
    _record(fn, "http", {"method": method, "path": path, "query": query}, out)
    return out


def register(app) -> None:
    async def _gcf(project: str, location: str, function: str, request: Request, rest: str = ""):
        fn = _find_function(function)
        if not fn:
            return Response(content=json.dumps({"error": {"code": 404, "message": f"Function {function} not found", "status": "NOT_FOUND"}}),
                            status_code=404, media_type="application/json")
        body = await request.body()
        import asyncio
        out = await asyncio.get_running_loop().run_in_executor(None, lambda: invoke_http(
            fn, request.method, "/" + rest, request.url.query, {k: v for k, v in request.headers.items()}, body, str(request.url)))
        hdrs = {k: str(v) for k, v in (out.get("headers") or {}).items() if k.lower() not in ("content-length", "transfer-encoding")}
        ct = next((v for k, v in hdrs.items() if k.lower() == "content-type"), None)
        hdrs = {k: v for k, v in hdrs.items() if k.lower() != "content-type"}
        return Response(content=out.get("body", b""), status_code=int(out.get("status", 200)), headers=hdrs, media_type=ct)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
    app.add_api_route("/gcf/{project}/{location}/{function}", _gcf, methods=methods, include_in_schema=False)
    app.add_api_route("/gcf/{project}/{location}/{function}/{rest:path}", _gcf, methods=methods, include_in_schema=False)


# ── Eventarc ──────────────────────────────────────────────────────────────────────────────────
def _is_cloud_event_fn(fn: dict) -> bool:
    if fn.get("eventTrigger"):
        return True
    code = str(fn.get("code") or "")
    entry = str(fn.get("entryPoint") or "")
    return bool(re.search(r"functions_framework\.cloud_event\s*\ndef\s+" + re.escape(entry) + r"\b", code))


def _filters_match(trigger: dict, attrs: dict) -> bool:
    for f in trigger.get("eventFilters") or []:
        a, want, op = f.get("attribute"), str(f.get("value", "")), f.get("operator", "")
        have = attrs.get(a)
        if have is None:
            return False
        if op == "match-path-pattern":
            pat = re.escape(want).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
            if not re.fullmatch(pat, str(have)):
                return False
        elif str(have) != want:
            return False
    return True


def _deliver(trigger: dict, ce: dict) -> None:
    from core.app_context import REQUEST_PROVIDER
    REQUEST_PROVIDER.set("gcp")   # background thread: resolve functions in the GCP space, not the active AWS one
    dest = trigger.get("destination") or {}
    fn_ref = dest.get("cloudFunction") or dest.get("cloud_function") or ""
    http = (dest.get("httpEndpoint") or {}).get("uri") or ""
    ce_headers = {"ce-id": ce["id"], "ce-source": ce["source"], "ce-specversion": "1.0", "ce-type": ce["type"],
                  "ce-time": ce["time"], "content-type": "application/json"}
    if ce.get("subject"):
        ce_headers["ce-subject"] = ce["subject"]
    body = json.dumps(ce.get("data") or {}).encode()
    try:
        if fn_ref:
            fn = _find_function(fn_ref.rsplit("/", 1)[-1])
            if fn is None:
                return
            if _is_cloud_event_fn(fn):
                from core import gcp_function_runtime as rt
                code, entry, runtime, timeout, env = _fn_params(fn)
                out = rt.execute_cloud_event(code, entry, runtime, dict(ce), timeout=timeout, env=env)
                _record(fn, "eventarc", {"type": ce["type"], "subject": ce.get("subject")}, out)
            else:   # an HTTP function: Eventarc POSTs the event in binary content mode
                invoke_http(fn, "POST", "/", "", ce_headers, body)
        elif http:
            req = urllib.request.Request(http, data=body, method="POST", headers=ce_headers)
            urllib.request.urlopen(req, timeout=15).read()
    except Exception:
        pass   # a failed delivery never fails the upload / publish that produced the event
    trigger["lastDelivery"] = {"id": ce["id"], "type": ce["type"], "time": _now_rfc3339()}


def fire(project: str, event_type: str, source: str, subject: str, data: dict, attrs: dict, topic: str = "") -> int:
    """Match `attrs` against every Eventarc trigger of `project` and deliver (async). Returns #triggers matched."""
    from core import nats_routes as nr
    n = 0
    for (p, _loc, _name), trig in list(nr._eventarc_triggers.items()):
        if p != project:
            continue
        attrs2 = dict(attrs, type=event_type)
        tpic = ((trig.get("transport") or {}).get("pubsub") or {}).get("topic", "")
        if event_type == PUBSUB_PUBLISHED and tpic and tpic.rsplit("/", 1)[-1] != topic:
            continue
        if event_type == PUBSUB_PUBLISHED and not tpic and not any(f.get("attribute") == "topic" for f in trig.get("eventFilters") or []):
            continue   # a Pub/Sub trigger must name its topic
        if not _filters_match(trig, attrs2):
            continue
        ce = {"id": uuid.uuid4().hex, "source": source, "specversion": "1.0", "type": event_type,
              "subject": subject, "time": _now_rfc3339(), "datacontenttype": "application/json", "data": data}
        threading.Thread(target=_deliver, args=(trig, ce), daemon=True).start()
        n += 1
    return n


_GCS_PATHS = [re.compile(r"^/upload/storage/v1/b/([^/]+)/o/?$"), re.compile(r"^/storage/v1/b/([^/]+)/o/?$"),
              re.compile(r"^/api/gcp/storage/v1/b/([^/]+)/(?:o|upload)/?$")]
_PUBSUB_PATH = re.compile(r"^(?:/api/gcp/pubsub)?/v1/projects/([^/]+)/topics/([^/:]+):publish$")


def _project() -> str:
    try:
        from core.gcp_project import NANO_PROJECT  # noqa: F401
    except Exception:
        pass
    return "*"


class EventTap:
    """Pure-ASGI tap: lets the request through untouched, and AFTER a successful object upload / publish
    turns it into a CloudEvent for matching Eventarc triggers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT"):
            return await self.app(scope, receive, send)
        path = scope["path"]
        gcs = next((m for m in (p.match(path) for p in _GCS_PATHS) if m), None)
        ps = _PUBSUB_PATH.match(path)
        if not gcs and not ps:
            return await self.app(scope, receive, send)
        req_chunks, resp = [], {"status": 0, "body": []}

        async def _recv():
            msg = await receive()
            if msg["type"] == "http.request":
                req_chunks.append(msg.get("body", b""))
            return msg

        async def _send(msg):
            if msg["type"] == "http.response.start":
                resp["status"] = msg["status"]
            elif msg["type"] == "http.response.body":
                resp["body"].append(msg.get("body", b""))
            await send(msg)

        await self.app(scope, _recv, _send)
        try:
            if 200 <= resp["status"] < 300:
                query = scope.get("query_string", b"").decode()
                if gcs:
                    self._storage(gcs.group(1), query, b"".join(resp["body"]))
                else:
                    self._pubsub(ps.group(1), ps.group(2), b"".join(req_chunks), b"".join(resp["body"]))
        except Exception:
            pass

    @staticmethod
    def _storage(bucket: str, query: str, body: bytes) -> None:
        try:
            meta = json.loads(body.decode("utf-8")) if body[:1] == b"{" else {}
        except Exception:
            meta = {}
        from urllib.parse import parse_qs
        name = meta.get("name") or (parse_qs(query).get("name") or [""])[0]
        if not name or "uploadType=resumable" in query and not meta:
            return
        data = {"bucket": bucket, "name": name, "contentType": meta.get("contentType", ""), "size": str(meta.get("size", "")),
                "generation": str(meta.get("generation", "1")), "metageneration": str(meta.get("metageneration", "1")),
                "timeCreated": meta.get("timeCreated", _now_rfc3339()), "updated": meta.get("updated", _now_rfc3339())}
        from core import nats_routes as nr
        for project in {p for (p, _l, _n) in nr._eventarc_triggers}:
            fire(project, STORAGE_FINALIZED, f"//storage.googleapis.com/projects/_/buckets/{bucket}", f"objects/{name}",
                 data, {"bucket": bucket, "subject": f"objects/{name}"})

    @staticmethod
    def _pubsub(project: str, topic: str, req: bytes, resp: bytes) -> None:
        try:
            msgs = (json.loads(req.decode("utf-8")) or {}).get("messages") or []
            ids = (json.loads(resp.decode("utf-8")) or {}).get("messageIds") or []
        except Exception:
            return
        from core import nats_routes as nr
        for i, m in enumerate(msgs):
            data = {"message": {"data": m.get("data", ""), "attributes": m.get("attributes") or {},
                                "messageId": ids[i] if i < len(ids) else uuid.uuid4().hex, "publishTime": _now_rfc3339()},
                    "subscription": f"projects/{project}/subscriptions/eventarc-{topic}"}
            # triggers are keyed by project; the appliance's single project may differ from the URL's
            for p in {p for (p, _l, _n) in nr._eventarc_triggers} | {project}:
                fire(p, PUBSUB_PUBLISHED, f"//pubsub.googleapis.com/projects/{project}/topics/{topic}", "",
                     data, {}, topic=topic)
