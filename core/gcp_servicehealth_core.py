"""GCP: Personalized Service Health (servicehealth v1) - a SIMULATED, Vyomi-owned service-health feed.

Substrate-independent (stdlib only; Pyodide-loadable). State on the Compute (VM) store `ext` dict, key "svchealth".

There is no real Google status source behind Vyomi, so nothing here reports on Google's infrastructure. The feed
describes the *simulated project*: per-service status for the services Vyomi simulates, an incident history that is
EMPTY by default, and a way to inject / resolve test incidents so applications can be built against the shape of
the real API. Every event carries `vyomiSimulated: true` and `vyomiSource: "Dev Simplified"`.

Wire (servicehealth.googleapis.com v1, project scope, location `global`):
  GET    /v1/projects/{p}/locations/global/events[?filter=state=ACTIVE|CLOSED&pageSize&pageToken]
  GET    /v1/projects/{p}/locations/global/events/{id}
  POST   /v1/projects/{p}/locations/global/events                (Vyomi extension: inject a test incident)
  POST   /v1/projects/{p}/locations/global/events/{id}:resolve   (Vyomi extension)
  POST   /v1/projects/{p}/locations/global/events/{id}:addUpdate (Vyomi extension)
  DELETE /v1/projects/{p}/locations/global/events/{id}           (Vyomi extension)
  GET    /v1/projects/{p}/locations/global/vyomiServiceStatus    (Vyomi extension: status per simulated service)
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone

_LOCK = threading.RLock()
SOURCE = "Dev Simplified"
PATH_RE = re.compile(r"^/v1/projects/[^/]+/locations/global/(events|vyomiServiceStatus)([/:?]|$)")

SERVICES = [
    "Compute Engine", "Cloud Storage", "Cloud SQL", "Cloud Run", "Cloud Functions", "Google Kubernetes Engine",
    "Pub/Sub", "Firestore", "Cloud KMS", "Secret Manager", "Cloud Logging", "Cloud Monitoring", "Artifact Registry",
    "Cloud Build", "Cloud DNS", "Virtual Private Cloud", "Identity and Access Management", "Vertex AI",
]
SEVERITIES = {"INFORMATION": 1, "DISRUPTION": 2, "OUTAGE": 3}
STATUS_OF = {0: "AVAILABLE", 1: "SERVICE_INFORMATION", 2: "SERVICE_DISRUPTION", 3: "SERVICE_OUTAGE"}
REGIONS = ["global", "us-central1", "us-east1", "us-east4", "us-west1", "europe-west1", "europe-west4",
           "asia-east1", "asia-southeast1", "asia-northeast1"]


class Resp:
    media_type = "application/json"

    def __init__(self, status, obj):
        self.status, self.headers = status, {}
        self.body = json.dumps(obj).encode()


class _E(Exception):
    def __init__(self, status, gstatus, msg):
        self.status, self.gstatus, self.message = status, gstatus, msg


def _err(e):
    return Resp(e.status, {"error": {"code": e.status, "message": e.message, "status": e.gstatus}})


def _bad(msg):
    return _E(400, "INVALID_ARGUMENT", msg)


def _iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _evs(store):
    if getattr(store, "ext", None) is None:
        store.ext = {}
    return store.ext.setdefault("svchealth", {})


def _body(body):
    if not body:
        return {}
    try:
        p = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)
    except Exception:
        raise _bad("Invalid JSON payload received.")
    return p if isinstance(p, dict) else {}


def _pub(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def _service_name(name):
    for s in SERVICES:
        if s.lower() == str(name).strip().lower():
            return s
    raise _bad("Unknown service %r. Simulated services: %s." % (name, ", ".join(SERVICES)))


def create_event(store, project, p):
    title = str(p.get("title") or "").strip()
    if not title:
        raise _bad("title is required.")
    sev = str(p.get("severity") or "DISRUPTION").upper()
    if sev not in SEVERITIES:
        raise _bad("severity must be one of %s." % ", ".join(SEVERITIES))
    products = p.get("products") or p.get("services") or []
    if isinstance(products, str):
        products = [products]
    if not products:
        raise _bad("products must name at least one simulated service.")
    products = [_service_name(x) for x in products]
    locs = p.get("locations") or ["global"]
    if isinstance(locs, str):
        locs = [locs]
    for l in locs:
        if l not in REGIONS:
            raise _bad("Unknown location %r." % l)
    eid = "vyomi-" + uuid.uuid4().hex[:12]
    now = _iso()
    ev = {
        "name": "projects/%s/locations/global/events/%s" % (project, eid),
        "title": title, "description": str(p.get("description") or ""),
        "category": "INCIDENT", "detailedCategory": "CONFIRMED_INCIDENT",
        "state": "ACTIVE", "detailedState": "CONFIRMED", "relevance": "RELATED",
        "eventImpacts": [{"product": {"productName": s, "id": s.lower().replace(" ", "-").replace("/", "-")},
                          "location": {"locationName": l}} for s in products for l in locs],
        "updates": [{"updateTime": now, "title": "Incident injected", "description": str(p.get("description") or title),
                     "symptom": str(p.get("symptom") or ""), "workaround": str(p.get("workaround") or "")}],
        "startTime": now, "updateTime": now,
        "vyomiSeverity": sev, "vyomiSimulated": True, "vyomiSource": SOURCE,
    }
    _evs(store)[eid] = ev
    return ev


def _get(store, project, eid):
    ev = _evs(store).get(eid)
    if not ev or ev["name"].split("/")[1] != project:
        raise _E(404, "NOT_FOUND", "Event projects/%s/locations/global/events/%s was not found." % (project, eid))
    return ev


def resolve_event(store, project, eid, p):
    ev = _get(store, project, eid)
    if ev["state"] == "CLOSED":
        raise _E(409, "FAILED_PRECONDITION", "Event is already resolved.")
    now = _iso()
    ev.update(state="CLOSED", detailedState="RESOLVED", endTime=now, updateTime=now)
    ev["updates"].append({"updateTime": now, "title": "Incident resolved",
                          "description": str(p.get("description") or "The incident has been resolved.")})
    return ev


def add_update(store, project, eid, p):
    ev = _get(store, project, eid)
    d = str(p.get("description") or "").strip()
    if not d:
        raise _bad("description is required.")
    now = _iso()
    ev["updates"].append({"updateTime": now, "title": str(p.get("title") or "Update"), "description": d})
    ev["updateTime"] = now
    return ev


def service_status(store, project):
    """Per simulated service: AVAILABLE unless an ACTIVE event impacts it (worst severity wins)."""
    worst, active = {s: 0 for s in SERVICES}, {s: [] for s in SERVICES}
    for eid, ev in _evs(store).items():
        if ev["name"].split("/")[1] != project or ev["state"] != "ACTIVE":
            continue
        for s in {i["product"]["productName"] for i in ev["eventImpacts"]}:
            worst[s] = max(worst[s], SEVERITIES[ev["vyomiSeverity"]])
            active[s].append(eid)
    return {"basis": "SIMULATED", "source": SOURCE,
            "services": [{"service": s, "status": STATUS_OF[worst[s]], "activeEvents": active[s]} for s in SERVICES]}


def _list(store, project, query):
    flt = str(query.get("filter") or "")
    m = re.search(r"state\s*=\s*\"?(ACTIVE|CLOSED)\"?", flt)
    if flt and not m:
        raise _bad("Unsupported filter. Supported: state=ACTIVE or state=CLOSED.")
    items = [e for e in _evs(store).values() if e["name"].split("/")[1] == project and (not m or e["state"] == m.group(1))]
    items.sort(key=lambda e: e["startTime"], reverse=True)
    try:
        size = int(query.get("pageSize") or 100)
        start = int(query.get("pageToken") or 0)
    except ValueError:
        raise _bad("pageSize/pageToken must be integers.")
    page = items[start:start + size]
    out = {"events": [_pub(e) for e in page], "unreachable": [], "vyomiSource": SOURCE}
    if start + size < len(items):
        out["nextPageToken"] = str(start + size)
    return out


def dispatch(store, method, path, query=None, headers=None, body=b""):
    query, method = query or {}, method.upper()
    try:
        p = path.split("?", 1)[0].strip("/")
        verb = ""
        if ":" in p.rsplit("/", 1)[-1]:
            p, verb = p.rsplit(":", 1)
        segs = p.split("/")          # v1 projects P locations global (events [id] | vyomiServiceStatus)
        project, coll, tail = segs[2], segs[5], segs[6:]
        with _LOCK:
            if coll == "vyomiServiceStatus":
                if method != "GET" or tail:
                    raise _E(405, "UNIMPLEMENTED", "Method %s not allowed." % method)
                return Resp(200, service_status(store, project))
            payload = _body(body) if method in ("POST", "PATCH") else {}
            if not tail:
                if method == "GET":
                    return Resp(200, _list(store, project, query))
                if method != "POST":
                    raise _E(405, "UNIMPLEMENTED", "Method %s not allowed." % method)
                out = _pub(create_event(store, project, payload))
            elif len(tail) == 1:
                eid = tail[0]
                if verb == "resolve" and method == "POST":
                    out = _pub(resolve_event(store, project, eid, payload))
                elif verb == "addUpdate" and method == "POST":
                    out = _pub(add_update(store, project, eid, payload))
                elif not verb and method == "GET":
                    return Resp(200, _pub(_get(store, project, eid)))
                elif not verb and method == "DELETE":
                    _get(store, project, eid)
                    del _evs(store)[eid]
                    out = {}
                else:
                    raise _E(404, "NOT_FOUND", "Unknown path or method: %s %s" % (method, path))
            else:
                raise _E(404, "NOT_FOUND", "Unknown path: %s" % path)
            if hasattr(store, "persist"):
                store.persist()
            return Resp(200, out)
    except _E as e:
        return _err(e)
