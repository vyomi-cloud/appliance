"""Nano (in-browser) trigger delivery + function data planes - the Pyodide twin of the offline appliance's
core/gcp_eventing.py, core/azure_eventgrid_delivery.py and Azure function-app data plane.

Everything runs in-process and synchronously (no threads, no Docker, no outbound network):
  * GCP Eventarc: an object upload (storage finalized) or a Pub/Sub publish that the wire router just served is
    matched against the console's Eventarc trigger records and delivered to the destination Cloud Function,
    executed in the restricted Pyodide sandbox (CloudEvent or HTTP style).
  * Cloud Functions HTTP trigger `/gcf/{project}/{location}/{function}`: Flask-like request, the return value is the response.
  * Azure Event Grid publish `/azure-data/eventgrid/{topic}/(api/)events`: delivered to StorageQueue (the in-browser
    queue) and AzureFunction destinations. WebHook destinations cannot be called from a browser sandbox: they are
    recorded on the subscription as `Unsupported` (visible, never silently dropped) and counted in the response.
  * Azure function apps: `/azure-data/functions/{app}/(api/)<fn>` and Kudu-style `.../api/zipdeploy`.
"""
from __future__ import annotations

import base64
import io
import json
import re
import time
import uuid

from core import gcp_console_tabs as T

STORAGE_FINALIZED = "google.cloud.storage.object.v1.finalized"
PUBSUB_PUBLISHED = "google.cloud.pubsub.topic.v1.messagePublished"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _resp(status, body=b"", ctype="application/json", headers=None):
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    h = dict(headers or {})
    h.setdefault("content-type", ctype)
    return {"status": status, "headers": h, "body": body}


# ── GCP ────────────────────────────────────────────────────────────────────────────────────
def _gcp_collection(resources, service):
    out = {}
    for ns, coll in (getattr(resources, "collections", None) or {}).items():
        if ns.startswith("gcp/") and ns.endswith("/" + service):
            out.update(coll)
    return out


def _fn_env(rec):
    env = rec.get("environmentVariables") or {}
    return {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}


def _record(rec, kind, req, out):
    inv = rec.setdefault("invocations", [])
    body = out.get("body")
    inv.append({"id": "inv-" + uuid.uuid4().hex[:12], "timestamp": _now(), "request": req, "source": kind,
                "response": (body.decode("utf-8", "replace")[:2000] if isinstance(body, bytes) else json.dumps(out.get("result"), default=str)[:2000]),
                "status": "SUCCESS" if (out.get("ok") or out.get("status") == "SUCCESS") else "ERROR",
                "error": out.get("error", ""), "logs": out.get("logs", "")})
    del inv[:-200]


def _is_cloud_event_fn(rec):
    code, entry = str(rec.get("code") or ""), str(rec.get("entryPoint") or "")
    return bool(rec.get("eventTrigger")) or bool(re.search(r"functions_framework\.cloud_event\s*\ndef\s+" + re.escape(entry) + r"\b", code))


def _match(trigger, attrs):
    filters = trigger.get("eventFilters")
    if not filters:
        filters = [{"attribute": "type", "value": trigger.get("eventType") or PUBSUB_PUBLISHED}]
    for f in filters:
        have = attrs.get(f.get("attribute"))
        if have is None:
            return False
        want = str(f.get("value", ""))
        if f.get("operator") == "match-path-pattern":
            pat = re.escape(want).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
            if not re.fullmatch(pat, str(have)):
                return False
        elif str(have) != want:
            return False
    return True


def _fire(resources, event_type, source, subject, data, attrs, topic=""):
    fns = _gcp_collection(resources, "functions")
    n = 0
    for trig in _gcp_collection(resources, "eventarc").values():
        if not _match(trig, dict(attrs, type=event_type)):
            continue
        if event_type == PUBSUB_PUBLISHED:
            tp = ((trig.get("transport") or {}).get("pubsub") or {}).get("topic", "")
            if tp.rsplit("/", 1)[-1] != topic:
                continue
        spec = trig.get("destinationSpec") or {}
        target = str(spec.get("service") or trig.get("destination") or "").rsplit("/", 1)[-1]
        fn = fns.get(target)
        if not fn:
            continue
        ce = {"id": uuid.uuid4().hex, "source": source, "specversion": "1.0", "type": event_type, "subject": subject,
              "time": _now(), "datacontenttype": "application/json", "data": data}
        entry = str(fn.get("entryPoint") or "handler")
        code = str(fn.get("code") or "")
        if _is_cloud_event_fn(fn):
            out = T.run_cloud_event_function(code, entry, ce, _fn_env(fn))
            _record(fn, "eventarc", {"type": event_type, "subject": subject}, out)
        else:   # HTTP function: Eventarc POSTs the event in binary content mode
            hdrs = {"ce-id": ce["id"], "ce-source": source, "ce-specversion": "1.0", "ce-type": event_type, "ce-subject": subject,
                    "content-type": "application/json"}
            out = T.run_http_function(code, entry, {"method": "POST", "path": "/", "query": "", "headers": hdrs,
                                                    "body": json.dumps(data).encode()}, "gcp", _fn_env(fn))
            _record(fn, "eventarc", {"type": event_type, "subject": subject}, out)
        n += 1
    return n


def after_gcp(router, svc, method, path, query, body, r):
    """Called by the wire router after it served a GCS / Pub/Sub request: turn uploads and publishes into events."""
    try:
        if r.status >= 300 or method not in ("POST", "PUT"):
            return
        res = router._stores.get("resources") if hasattr(router, "_stores") else None
        if res is None:
            return
        base = path.split("?", 1)[0]
        if svc == "gcp-gcs":
            m = re.match(r"^/(?:upload/)?storage/v1/b/([^/]+)/o/?$", base)
            if not m:
                return
            try:
                meta = json.loads((r.body or b"").decode("utf-8")) if (r.body or b"")[:1] == b"{" else {}
            except Exception:
                meta = {}
            name = meta.get("name") or (query or {}).get("name") or ""
            if isinstance(name, list):
                name = name[0]
            if not name:
                return
            _fire(res, STORAGE_FINALIZED, "//storage.googleapis.com/projects/_/buckets/" + m.group(1), "objects/" + name,
                  {"bucket": m.group(1), "name": name, "contentType": meta.get("contentType", ""), "size": str(meta.get("size", "")),
                   "generation": str(meta.get("generation", "1")), "timeCreated": meta.get("timeCreated", _now())},
                  {"bucket": m.group(1), "subject": "objects/" + name})
        elif svc == "gcp-pubsub":
            m = re.match(r"^/v1/projects/([^/]+)/topics/([^/:]+):publish$", base)
            if not m:
                return
            msgs = (json.loads(body.decode("utf-8")) or {}).get("messages") or []
            ids = (json.loads((r.body or b"{}").decode("utf-8")) or {}).get("messageIds") or []
            for i, mm in enumerate(msgs):
                _fire(res, PUBSUB_PUBLISHED, "//pubsub.googleapis.com/projects/%s/topics/%s" % (m.group(1), m.group(2)), "",
                      {"message": {"data": mm.get("data", ""), "attributes": mm.get("attributes") or {},
                                   "messageId": ids[i] if i < len(ids) else uuid.uuid4().hex, "publishTime": _now()},
                       "subscription": "projects/%s/subscriptions/eventarc-%s" % (m.group(1), m.group(2))}, {}, topic=m.group(2))
    except Exception:
        pass   # an event hook never fails the upload / publish that produced it


# ── Azure ──────────────────────────────────────────────────────────────────────────────────
def _arm_records(router):
    st = getattr(getattr(router, "az_arm", None), "state", None) or {}
    return [r for r in st.values() if isinstance(r, dict)]


def _rtype(rec):
    return str(rec.get("type") or rec.get("_type") or "").lower()


def _function_app(router, name):
    for r in _arm_records(router):
        if _rtype(r) == "microsoft.web/sites" and str(r.get("name", "")).lower() == name.lower():
            return r
    return None


def _eventgrid_publish(router, topic, body, ctype):
    items = body if isinstance(body, list) else [body]
    events = []
    for ev in items:
        if not isinstance(ev, dict):
            continue
        if "specversion" in ev:
            events.append({"id": ev.get("id") or uuid.uuid4().hex, "topic": topic, "subject": ev.get("subject", ""),
                           "eventType": ev.get("type", ""), "eventTime": ev.get("time") or _now(), "data": ev.get("data", {}),
                           "dataVersion": "1.0", "metadataVersion": "1"})
        else:
            events.append({"id": ev.get("id") or uuid.uuid4().hex, "topic": ev.get("topic", topic), "subject": ev.get("subject", ""),
                           "eventType": ev.get("eventType", "Default"), "eventTime": ev.get("eventTime") or _now(),
                           "data": ev.get("data", {}), "dataVersion": ev.get("dataVersion", "1.0"), "metadataVersion": "1"})
    delivered = skipped = 0
    for sub in _arm_records(router):
        rid = str(sub.get("id", "")).lower()
        if "/eventsubscriptions/" not in rid or "/topics/%s/" % topic.lower() not in rid:
            continue
        props = sub.get("properties") or {}
        f = props.get("filter") or {}
        evs = [e for e in events
               if (not f.get("includedEventTypes") or e["eventType"] in f["includedEventTypes"])
               and (not f.get("subjectBeginsWith") or e["subject"].startswith(f["subjectBeginsWith"]))
               and (not f.get("subjectEndsWith") or e["subject"].endswith(f["subjectEndsWith"]))]
        if not evs:
            continue
        dest = props.get("destination") or {}
        dp = dest.get("properties") or {}
        et = str(dest.get("endpointType") or "").lower()
        cloud = str(props.get("eventDeliverySchema") or "").lower().startswith("cloudevent")
        topic_id = str(sub.get("id", "")).split("/providers/Microsoft.EventGrid/eventSubscriptions")[0]
        payload = [{"specversion": "1.0", "id": e["id"], "source": topic_id, "type": e["eventType"], "subject": e["subject"],
                    "time": e["eventTime"], "datacontenttype": "application/json", "data": e["data"]} for e in evs] if cloud \
            else [dict(e, topic=e.get("topic") or topic_id) for e in evs]
        log = sub.setdefault("_deliveries", [])
        if et == "storagequeue" and dp.get("queueName"):
            from core import azure_queue_core as aq
            store = router.az_queue
            if not store.queue_exists(dp["queueName"]):
                aq.dispatch(store, "PUT", "/" + dp["queueName"], {}, {}, b"")
            for item in payload:
                aq.dispatch(store, "POST", "/%s/messages" % dp["queueName"], {}, {},
                            ("<QueueMessage><MessageText>%s</MessageText></QueueMessage>" % json.dumps(item).replace("&", "&amp;").replace("<", "&lt;")).encode())
            delivered += 1
            log.append({"time": _now(), "status": "Delivered", "destination": "StorageQueue/" + dp["queueName"]})
        elif et == "azurefunction":
            rid_dest = str(dp.get("resourceId", ""))
            app = rid_dest.split("/functions/")[0].rsplit("/", 1)[-1]
            fn = rid_dest.rsplit("/", 1)[-1]
            rec = _function_app(router, app)
            code = ((rec or {}).get("properties") or {}).get("code") or ""
            if code.strip():
                out = T.run_http_function(code, fn, {"method": "POST", "path": "/" + fn, "query": "",
                                                     "headers": {"content-type": "application/json"},
                                                     "body": json.dumps(payload).encode(), "url": ""}, "azure")
                delivered += 1
                log.append({"time": _now(), "status": "Delivered" if out.get("ok") else "Failed", "destination": "AzureFunction/" + app})
            else:
                log.append({"time": _now(), "status": "Failed", "destination": "AzureFunction/" + app, "reason": "no code deployed"})
        else:
            skipped += 1
            log.append({"time": _now(), "status": "Unsupported", "destination": dest.get("endpointType") or "?",
                        "reason": "WebHook/Event Hub/Service Bus destinations need outbound network; this in-browser build can only "
                                  "deliver to Storage Queue and Azure Function destinations. Run the offline appliance for webhooks."})
        del log[:-50]
    return _resp(200, {"published": len(events), "count": len(events), "delivered": delivered, "skippedUnsupported": skipped})


def _function_app_invoke(router, app, fn, method, query, headers, body):
    rec = _function_app(router, app)
    if not rec:
        return _resp(404, {"error": "Function App '%s' not found" % app})
    props = rec.get("properties") or {}
    code = props.get("code") or ""
    if not code.strip():
        return _resp(404, {"error": {"code": "FunctionNotFound", "message":
                                     "Function '%s' does not exist on app '%s': no code is deployed. Deploy a zip with POST "
                                     "/azure-data/functions/%s/api/zipdeploy." % (fn, app, app)}})
    out = T.run_http_function(code, fn, {"method": method, "path": "/" + fn, "query": query, "headers": headers, "body": body, "url": ""}, "azure")
    ct = next((v for k, v in (out.get("headers") or {}).items() if k.lower() == "content-type"), "text/plain")
    return _resp(out.get("status", 500), out.get("body", b""), ct,
                 {k: str(v) for k, v in (out.get("headers") or {}).items() if k.lower() not in ("content-type", "content-length")})


def _zipdeploy(router, app, body):
    import zipfile
    rec = _function_app(router, app)
    if not rec:
        return _resp(404, {"error": "Function App '%s' not found" % app})
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
    except Exception:
        return _resp(400, {"error": "Body is not a zip archive"})
    names = z.namelist()
    pick = next((n for n in ("function_app.py", "main.py", "__init__.py") if n in names), None) \
        or next((n for n in names if n.endswith("/__init__.py") and n.count("/") == 1), None) \
        or next((n for n in names if n.endswith(".py") and "/" not in n), None)
    if not pick:
        return _resp(400, {"error": "No python entry module found (function_app.py, main.py or <fn>/__init__.py)"})
    props = rec.setdefault("properties", {})
    props["code"] = z.read(pick).decode("utf-8")
    props["entryPoint"] = "main"
    props["runtime"] = "python"
    return _resp(200, b"Deployment successful.", "text/plain")


def route(router, method, path, query, lheaders, body):
    """Wire-router front hook. Returns a response dict for the paths this module owns, else None."""
    p = path.split("?", 1)[0]
    qs = "&".join("%s=%s" % (k, v if not isinstance(v, list) else v[0]) for k, v in (query or {}).items())
    try:
        if p.startswith("/gcf/"):
            parts = p.split("/")[2:]
            if len(parts) < 3:
                return None
            res = router._stores.get("resources")
            fn = _gcp_collection(res, "functions").get(parts[2])
            if not fn:
                return _resp(404, {"error": {"code": 404, "message": "Function %s not found" % parts[2], "status": "NOT_FOUND"}})
            out = T.run_http_function(str(fn.get("code") or ""), str(fn.get("entryPoint") or "hello_http"),
                                      {"method": method, "path": "/" + "/".join(parts[3:]), "query": qs, "headers": lheaders, "body": bytes(body)},
                                      "gcp", _fn_env(fn))
            _record(fn, "http", {"method": method}, out)
            ct = next((v for k, v in (out.get("headers") or {}).items() if k.lower() == "content-type"), "text/plain")
            return _resp(out["status"], out["body"], ct, {k: str(v) for k, v in (out.get("headers") or {}).items()
                                                          if k.lower() not in ("content-type", "content-length")})
        m = re.match(r"^/azure-data/eventgrid/([^/]+)/(?:api/)?events$", p)
        if m and method == "POST":
            try:
                doc = json.loads(bytes(body).decode("utf-8") or "[]")
            except Exception:
                return _resp(400, {"error": {"code": "InvalidRequest", "message": "Body is not valid JSON"}})
            return _eventgrid_publish(router, m.group(1), doc, lheaders.get("content-type", ""))
        m = re.match(r"^/azure-data/functions/([^/]+)/api/zipdeploy$", p)
        if m and method in ("POST", "PUT"):
            return _zipdeploy(router, m.group(1), bytes(body))
        m = re.match(r"^/azure-data/functions/([^/]+)/(?:api/)?([^/]+)$", p)
        if m:
            return _function_app_invoke(router, m.group(1), m.group(2), method, qs, lheaders, bytes(body))
    except Exception as e:   # pragma: no cover
        return _resp(500, {"error": "%s: %s" % (type(e).__name__, e)})
    return None
