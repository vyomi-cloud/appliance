# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Eventarc API v1 (eventarc.googleapis.com) — substrate-independent, stdlib only.

`projects/{p}/locations/{l}/triggers|providers|operations` with real behaviour:

  * providers + event types catalog (Cloud Storage, Pub/Sub, Cloud Audit Logs, Firestore)
  * trigger validation per event type (required eventFilters, bucket / topic / document-pattern checks),
    destination checks (the Cloud Run service or job must exist in the same region), LRO responses
  * REAL delivery from real sources, one CloudEvent per matching trigger:
      - Cloud Storage object finalize/delete   (fired by the GCS core's on_object_event)
      - Pub/Sub messagePublished               (fired by the Pub/Sub core's publish hook)
      - Cloud Audit Logs written               (fired for every Admin Activity audit entry, core/gcp_audit_core.py)
      - Firestore document created/updated/deleted/written (fired by FirestoreStore writes, with old/new values)
  * destinations: Cloud Run service (invoked with the CloudEvent) and — Vyomi extension — Cloud Run job
    (`destination.cloudRunJob` starts an execution; real Eventarc reaches jobs through Workflows, which
    Vyomi does not simulate), delivery history per trigger (`/triggers/{t}/deliveries`).

State lives in `store.ext["eventarc"]` of the monitoring store (persisted with it).
"""
from __future__ import annotations

import fnmatch
import json
import re
import uuid
from datetime import datetime, timezone

try:
    from core import gcp_run_core as run
    from core.gcp_firestore_core import FirestoreResponse
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gcp_run_core as run  # type: ignore
    from gcp_firestore_core import FirestoreResponse  # type: ignore

EVENT_TYPES = {
    "google.cloud.storage.object.v1.finalized": ("storage.googleapis.com", ["bucket"]),
    "google.cloud.storage.object.v1.deleted": ("storage.googleapis.com", ["bucket"]),
    "google.cloud.storage.object.v1.archived": ("storage.googleapis.com", ["bucket"]),
    "google.cloud.storage.object.v1.metadataUpdated": ("storage.googleapis.com", ["bucket"]),
    "google.cloud.pubsub.topic.v1.messagePublished": ("pubsub.googleapis.com", []),
    "google.cloud.audit.log.v1.written": ("cloudaudit.googleapis.com", ["serviceName", "methodName"]),
    "google.cloud.firestore.document.v1.created": ("firestore.googleapis.com", ["database"]),
    "google.cloud.firestore.document.v1.updated": ("firestore.googleapis.com", ["database"]),
    "google.cloud.firestore.document.v1.deleted": ("firestore.googleapis.com", ["database"]),
    "google.cloud.firestore.document.v1.written": ("firestore.googleapis.com", ["database"]),
}
PROVIDERS = [
    ("cloudaudit.googleapis.com", "Cloud Audit Logs"), ("firestore.googleapis.com", "Firestore"),
    ("pubsub.googleapis.com", "Cloud Pub/Sub"), ("storage.googleapis.com", "Cloud Storage"),
]
_ID = re.compile(r"^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$")
_SA = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam\.gserviceaccount\.com$|^\d+-compute@developer\.gserviceaccount\.com$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status: int, gs: str, msg: str) -> FirestoreResponse:
    return FirestoreResponse(status, {"content-type": "application/json"},
                             json.dumps({"error": {"code": status, "message": msg, "status": gs}}).encode())


def _json(o) -> FirestoreResponse:
    return FirestoreResponse(200, {"content-type": "application/json"}, json.dumps(o).encode())


class _E(Exception):
    def __init__(self, status, gs, msg):
        self.r = _err(status, gs, msg)


def _coll(store, name: str) -> dict:
    if getattr(store, "ext", None) is None:
        store.ext = {}
    return store.ext.setdefault("eventarc_" + name, {})


def _view(t: dict) -> dict:
    return {k: v for k, v in t.items() if not k.startswith("_")}


def _lro(project, location, response=None, verb="create"):
    oid = "operation-" + uuid.uuid4().hex[:16]
    op = {"name": f"projects/{project}/locations/{location}/operations/{oid}",
          "metadata": {"@type": "type.googleapis.com/google.cloud.eventarc.v1.OperationMetadata", "createTime": _now(), "endTime": _now(),
                       "target": (response or {}).get("name", ""), "verb": verb, "apiVersion": "v1"},
          "done": True}
    if response is not None:
        op["response"] = {"@type": "type.googleapis.com/google.cloud.eventarc.v1.Trigger", **response}
    return op


# ── CRUD ───────────────────────────────────────────────────────────────────
def _validate(store, run_store, project, location, tid, payload, pubsub_store, gcs_store) -> dict:
    filters = payload.get("eventFilters") or []
    if not isinstance(filters, list) or not filters:
        raise _E(400, "INVALID_ARGUMENT", "eventFilters must include at least the 'type' attribute.")
    fmap = {f.get("attribute"): f for f in filters if isinstance(f, dict)}
    etype = (fmap.get("type") or {}).get("value")
    if etype not in EVENT_TYPES:
        raise _E(400, "INVALID_ARGUMENT", "Invalid or unsupported event type %r. Supported: %s." % (etype, ", ".join(sorted(EVENT_TYPES))))
    for req in EVENT_TYPES[etype][1]:
        if req not in fmap:
            raise _E(400, "INVALID_ARGUMENT", "The event type %s requires an eventFilters entry with attribute %r." % (etype, req))
    for f in filters:
        if f.get("operator") not in (None, "", "match-path-pattern"):
            raise _E(400, "INVALID_ARGUMENT", "Unsupported eventFilters operator %r." % f["operator"])
    if etype.startswith("google.cloud.storage"):
        b = fmap["bucket"]["value"]
        if gcs_store is not None and not gcs_store.bucket_exists(b):
            raise _E(400, "INVALID_ARGUMENT", "Cloud Storage bucket '%s' does not exist." % b)
    sa = payload.get("serviceAccount")
    if sa and not _SA.match(sa):
        raise _E(400, "INVALID_ARGUMENT", "serviceAccount must be a service account email, got %r." % sa)
    dest = payload.get("destination") or {}
    kinds = [k for k in ("cloudRun", "cloudRunJob", "workflow", "cloudFunction", "gke") if k in dest]
    if len(kinds) != 1:
        raise _E(400, "INVALID_ARGUMENT", "destination must name exactly one of cloudRun, cloudRunJob (Vyomi), workflow, cloudFunction, gke.")
    k = kinds[0]
    if k in ("workflow", "gke"):
        raise _E(400, "FAILED_PRECONDITION", "Destination %s is not simulated by Vyomi (no Workflows / GKE delivery backend); use cloudRun or cloudRunJob." % k)
    if k == "cloudFunction":
        raise _E(400, "FAILED_PRECONDITION", "Cloud Functions 1st-gen destinations are not simulated; deploy the function as a Cloud Run service.")
    target = dest[k]
    region = target.get("region") or location
    if region != location:
        raise _E(400, "INVALID_ARGUMENT", "The destination must be in the same region as the trigger (%s)." % location)
    name = target.get("service") if k == "cloudRun" else target.get("job")
    if not name:
        raise _E(400, "INVALID_ARGUMENT", "destination.%s.%s is required." % (k, "service" if k == "cloudRun" else "job"))
    try:
        (run._get_service if k == "cloudRun" else run._get_job)(run_store, project, location, name)
    except run._E as e:
        raise _E(400, "FAILED_PRECONDITION", "Destination Cloud Run %s '%s' does not exist in %s." % ("service" if k == "cloudRun" else "job", name, location))
    transport = payload.get("transport") or {}
    topic = ((transport.get("pubsub") or {}).get("topic")) or ""
    if etype.endswith("messagePublished") and not topic:
        topic = "projects/%s/topics/eventarc-%s-%s" % (project, location, tid)
        if pubsub_store is not None:       # real Eventarc creates a topic for you
            from core import gcp_pubsub_core as ps
            ps.dispatch(pubsub_store, "PUT", "/v1/" + topic, {}, {}, b"{}")
    elif topic and pubsub_store is not None and pubsub_store.get_topic(topic) is None:
        raise _E(400, "INVALID_ARGUMENT", "Pub/Sub topic '%s' does not exist." % topic)
    return {"etype": etype, "filters": filters, "topic": topic, "dest_kind": k, "dest_name": name}


def _create(store, run_store, project, location, query, payload, **kw):
    tid = str(query.get("triggerId") or "").strip()
    if not _ID.match(tid):
        raise _E(400, "INVALID_ARGUMENT", "triggerId must be 1-63 chars of lowercase letters, digits and hyphens (starting with a letter).")
    trg = _coll(store, "triggers")
    full = f"projects/{project}/locations/{location}/triggers/{tid}"
    if full in trg:
        raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % full)
    v = _validate(store, run_store, project, location, tid, payload, kw.get("pubsub_store"), kw.get("gcs_store"))
    now = _now()
    t = {"name": full, "uid": str(uuid.uuid4()), "createTime": now, "updateTime": now,
         "eventFilters": v["filters"], "destination": payload["destination"],
         "serviceAccount": payload.get("serviceAccount") or "%s-compute@developer.gserviceaccount.com" % (abs(hash(project)) % 10**11),
         "transport": {"pubsub": {"topic": v["topic"]}} if v["topic"] else {},
         "labels": payload.get("labels") or {}, "eventDataContentType": payload.get("eventDataContentType") or "application/json",
         "etag": uuid.uuid4().hex[:16], "conditions": {"Ready": {"code": "OK", "message": ""}},
         "_event_type": v["etype"], "_deliveries": [], "_delivered": 0, "_failed": 0}
    trg[full] = t
    return _lro(project, location, _view(t))


def _match_filters(t: dict, attrs: dict) -> bool:
    for f in t["eventFilters"]:
        a, val = f.get("attribute"), f.get("value")
        if a == "type":
            continue
        got = attrs.get(a)
        if got is None:
            return False
        if f.get("operator") == "match-path-pattern":
            pat = "^" + re.sub(r"\{[^/}]+=\*\*\}", ".+", re.sub(r"\{[^/}]+\}", "[^/]+", re.escape(val).replace(r"\{", "{").replace(r"\}", "}"))) + "$"
            if not re.match(pat, got):
                return False
        elif str(got) != str(val):
            return False
    return True


# ── delivery ───────────────────────────────────────────────────────────────
def deliver(store, run_store, event_type: str, attrs: dict, ce: dict, log_fn=None, topic=None) -> int:
    """Fire every trigger matching (event_type, attrs) with CloudEvent `ce`. Never raises. -> number delivered."""
    n = 0
    for full, t in list(_coll(store, "triggers").items()):
        if t.get("_event_type") != event_type or not _match_filters(t, attrs):
            continue
        if topic is not None and ((t.get("transport") or {}).get("pubsub") or {}).get("topic") != topic:
            continue
        parts = full.split("/")
        project, location = parts[1], parts[3]
        dest = t["destination"]
        err, status = "", "DELIVERED"
        try:
            if "cloudRun" in dest:
                out = run.invoke_service(run_store, project, location, dest["cloudRun"]["service"], ce, internal=True)
                if out["status"] >= 500:
                    err = str(out["body"].get("error", "")) if isinstance(out["body"], dict) else "delivery failed"
            else:
                run.run_job(run_store, project, location, dest["cloudRunJob"]["job"],
                            {"overrides": {"containerOverrides": [{"env": [{"name": "CLOUD_EVENT", "value": json.dumps(ce)[:4000]}]}]}})
        except Exception as e:   # noqa: BLE001
            err = getattr(e, "message", str(e))
        if err:
            status = "FAILED"
            t["_failed"] += 1
        else:
            t["_delivered"] += 1
            n += 1
        t["_deliveries"] = ([{"time": _now(), "eventId": ce.get("id"), "type": ce.get("type"), "status": status, "error": err,
                              "destination": dest.get("cloudRun", dest.get("cloudRunJob"))}] + t["_deliveries"])[:50]
        if log_fn:
            kind = "service" if "cloudRun" in dest else "job"
            rid = dest["cloudRun"]["service"] if kind == "service" else dest["cloudRunJob"]["job"]
            log_fn(kind, project, location, rid, "Eventarc trigger %s %s %s" % (parts[-1], "failed: " + err if err else "delivered", ce.get("type")),
                   "ERROR" if err else "INFO")
    return n


def _ce(etype, source, subject, data):
    return {"specversion": "1.0", "type": etype, "id": uuid.uuid4().hex[:16], "source": source, "subject": subject, "time": _now(),
            "datacontenttype": "application/json", "data": data}


def on_storage_event(store, run_store, bucket, name, event, obj, log_fn=None):
    etype = "google.cloud.storage.object.v1.%s" % event
    return deliver(store, run_store, etype, {"bucket": bucket}, _ce(etype, "//storage.googleapis.com/projects/_/buckets/%s" % bucket, "objects/%s" % name, obj), log_fn)


def on_pubsub_publish(store, run_store, topic_full, messages, log_fn=None):
    etype = "google.cloud.pubsub.topic.v1.messagePublished"
    n = 0
    for m in messages or []:
        ce = _ce(etype, "//pubsub.googleapis.com/%s" % topic_full, "",
                 {"message": {"data": m.get("data", ""), "attributes": m.get("attributes") or {}, "messageId": m.get("messageId", "")},
                  "subscription": "eventarc"})
        n += deliver(store, run_store, etype, {}, ce, log_fn, topic=topic_full)
    return n


def on_audit_entry(store, run_store, entry: dict, log_fn=None):
    p = entry.get("protoPayload") or {}
    if not p.get("serviceName"):
        return 0
    etype = "google.cloud.audit.log.v1.written"
    attrs = {"serviceName": p["serviceName"], "methodName": p.get("methodName", ""), "resourceName": p.get("resourceName", "")}
    ce = _ce(etype, "//cloudaudit.googleapis.com/%s" % entry["logName"].split("/logs/")[0] + "/logs/activity",
             "%s/%s" % (p["serviceName"], p.get("resourceName", "")), entry)
    return deliver(store, run_store, etype, attrs, ce, log_fn)


def _fs_values(entry):
    if entry is None:
        return None
    return {"name": "", "fields": entry.get("fields", {}), "createTime": entry.get("createTime"), "updateTime": entry.get("updateTime")}


def on_firestore_write(store, run_store, project, db, rel, old, new, log_fn=None):
    kind = "created" if old is None and new is not None else "deleted" if new is None else "updated"
    base = "projects/%s/databases/%s/documents/%s" % (project, db, rel)
    n = 0
    for etype in ("google.cloud.firestore.document.v1." + kind, "google.cloud.firestore.document.v1.written"):
        ov, nv = _fs_values(old), _fs_values(new)
        for v in (ov, nv):
            if v:
                v["name"] = base
        ce = _ce(etype, "//firestore.googleapis.com/projects/%s/databases/%s" % (project, db), "documents/%s" % rel,
                 {"oldValue": ov or {}, "value": nv or {}, **({"updateMask": {"fieldPaths": sorted(set((old or {}).get("fields", {})) ^ set((new or {}).get("fields", {})))}} if old and new else {})})
        n += deliver(store, run_store, etype, {"database": db, "document": rel, "namespace": "(default)"}, ce, log_fn)
    return n


# ── dispatch ───────────────────────────────────────────────────────────────
def is_eventarc_path(path: str) -> bool:
    return bool(re.match(r"^/v1/projects/[^/]+/locations/[^/]+/(triggers|providers)([/?:]|$)", path.split("?", 1)[0]))


def dispatch(store, method: str, path: str, query=None, headers=None, body: bytes = b"", run_store=None, pubsub_store=None,
             gcs_store=None, log_fn=None) -> FirestoreResponse:
    query = query or {}
    method = method.upper()
    m = re.match(r"^/v1/projects/([^/]+)/locations/([^/]+)/(\w+)(?:/([^/:]+))?(?:/(\w+))?$", path.split("?", 1)[0])
    if not m:
        return _err(404, "NOT_FOUND", "Unknown path: " + path)
    project, location, coll, rid, sub = m.groups()
    try:
        data = json.loads(body.decode() or "{}") if body else {}
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Request body is not valid JSON.")
    try:
        if coll == "providers":
            if rid is None:
                return _json({"providers": [{"name": f"projects/{project}/locations/{location}/providers/{p}", "displayName": d} for p, d in PROVIDERS]})
            prov = next((p for p in PROVIDERS if p[0] == rid), None)
            if not prov:
                return _err(404, "NOT_FOUND", f"Provider {rid} not found.")
            return _json({"name": f"projects/{project}/locations/{location}/providers/{rid}", "displayName": prov[1],
                          "eventTypes": [{"type": t, "description": t.rsplit(".", 1)[-1], "filteringAttributes": [{"attribute": a, "required": True} for a in req]}
                                         for t, (svc, req) in EVENT_TYPES.items() if svc == rid]})
        if coll == "operations":
            return _json({"name": f"projects/{project}/locations/{location}/operations/{rid}", "done": True})
        if coll != "triggers":
            return _err(404, "NOT_FOUND", "Unknown collection " + coll)
        trg = _coll(store, "triggers")
        prefix = f"projects/{project}/locations/{location}/triggers/"
        if rid is None:
            if method == "POST":
                return _json(_create(store, run_store, project, location, query, data, pubsub_store=pubsub_store, gcs_store=gcs_store))
            if method == "GET":
                items = sorted((_view(t) for n, t in trg.items() if n.startswith(prefix)), key=lambda t: t["createTime"])
                if location == "-":
                    pass
                return _json({"triggers": items})
        else:
            full = prefix + rid
            t = trg.get(full)
            if t is None:
                return _err(404, "NOT_FOUND", f"Resource '{full}' was not found.")
            if sub == "deliveries" and method == "GET":
                return _json({"deliveries": t["_deliveries"], "delivered": t["_delivered"], "failed": t["_failed"]})
            if method == "GET":
                return _json(_view(t))
            if method == "PATCH":
                mask = [x for x in str(query.get("updateMask") or "").split(",") if x]
                for f in (mask or [k for k in ("labels", "serviceAccount", "destination", "eventFilters") if k in data]):
                    if f in ("labels", "serviceAccount"):
                        t[f] = data.get(f, t.get(f))
                    elif f in ("destination", "eventFilters"):
                        merged = {"eventFilters": t["eventFilters"], "destination": t["destination"], "serviceAccount": t["serviceAccount"], "transport": t.get("transport")}
                        merged[f] = data[f]
                        _validate(store, run_store, project, location, rid, merged, pubsub_store, gcs_store)
                        t[f] = data[f]
                        if f == "eventFilters":
                            t["_event_type"] = next(x["value"] for x in data[f] if x.get("attribute") == "type")
                    else:
                        return _err(400, "INVALID_ARGUMENT", f"Unsupported updateMask path {f}.")
                t["updateTime"], t["etag"] = _now(), uuid.uuid4().hex[:16]
                return _json(_lro(project, location, _view(t), "update"))
            if method == "DELETE":
                trg.pop(full)
                return _json(_lro(project, location, _view(t), "delete"))
    except _E as e:
        return e.r
    return _err(400, "INVALID_ARGUMENT", f"Unsupported request {method} {path}")
