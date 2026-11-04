"""App Hub (apphub.googleapis.com v1) — applications, registered services and workloads, discovered resources.

Substrate-independent (stdlib only). State: store.ext["apphub_apps"|"apphub_services"|"apphub_workloads"] on the Monitoring store
(public dict attrs persist). Discovery is real: discoveredServices come from the project's Cloud Run services, discoveredWorkloads
from its Compute managed instance groups, found through the sibling stores the router attaches (store.run_store / store.vm_store).

  /v1/projects/{p}/locations/{l}/applications[/{a}]                 (LRO create/patch/delete, done)
  /v1/projects/{p}/locations/{l}/applications/{a}/services|workloads[/{id}]
  /v1/projects/{p}/locations/{l}/discoveredServices|discoveredWorkloads[/{id}]
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

ID_RE = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")
CRIT = ("MISSION_CRITICAL", "HIGH", "MEDIUM", "LOW")
ENV = ("PRODUCTION", "STAGING", "TEST", "DEVELOPMENT")
SCOPES = ("REGIONAL", "GLOBAL")


class Resp:
    media_type = "application/json"

    def __init__(self, status, obj):
        self.status, self.headers = status, {}
        self.body = json.dumps(obj).encode()


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _bad(m):
    return _E(400, "INVALID_ARGUMENT", m)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _x(store, coll):
    if getattr(store, "ext", None) is None:
        store.ext = {}
    return store.ext.setdefault(coll, {})


def _lro(project, loc, resource, verb="create"):
    return {"name": "projects/%s/locations/%s/operations/operation-%s" % (project, loc, uuid.uuid4().hex[:16]), "done": True,
            "metadata": {"@type": "type.googleapis.com/google.cloud.apphub.v1.OperationMetadata", "verb": verb, "createTime": _now(), "endTime": _now()},
            "response": resource}


def _validate_attrs(a):
    if a is None:
        return {}
    if not isinstance(a, dict):
        raise _bad("attributes must be an object.")
    for k in a:
        if k not in ("criticality", "environment", "developerOwners", "operatorOwners", "businessOwners"):
            raise _bad("Unknown field attributes.%s." % k)
    if a.get("criticality") and a["criticality"].get("type") not in CRIT:
        raise _bad("attributes.criticality.type must be one of %s." % ", ".join(CRIT))
    if a.get("environment") and a["environment"].get("type") not in ENV:
        raise _bad("attributes.environment.type must be one of %s." % ", ".join(ENV))
    for k in ("developerOwners", "operatorOwners", "businessOwners"):
        for o in a.get(k) or []:
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str((o or {}).get("email", ""))):
                raise _bad("attributes.%s[].email must be a valid email address." % k)
    return a


# ── discovery over the real sibling stores ────────────────────────────────────
def discovered_services(store, project, loc):
    rs = getattr(store, "run_store", None)
    out = []
    for full, svc in sorted(((rs.services if rs is not None else {}) or {}).items()):
        if not full.startswith("projects/%s/locations/%s/services/" % (project, loc)):
            continue
        sid = full.rsplit("/", 1)[-1]
        out.append({"name": "projects/%s/locations/%s/discoveredServices/run-%s" % (project, loc, sid),
                    "serviceReference": {"uri": "//run.googleapis.com/%s" % full, "sourceProject": "projects/%s" % project},
                    "serviceProperties": {"gcpProject": "projects/%s" % project, "location": loc, "zone": ""}})
    return out


def discovered_workloads(store, project, loc):
    vm = getattr(store, "vm_store", None)
    out = []
    for full, m in sorted(((vm.instance_group_managers if vm is not None else {}) or {}).items()):
        if not full.startswith("projects/%s/zones/" % project):
            continue
        zone, name = full.split("/")[3], full.rsplit("/", 1)[-1]
        if zone.rsplit("-", 1)[0] != loc:
            continue
        out.append({"name": "projects/%s/locations/%s/discoveredWorkloads/mig-%s" % (project, loc, name),
                    "workloadReference": {"uri": "//compute.googleapis.com/%s" % full},
                    "workloadProperties": {"gcpProject": "projects/%s" % project, "location": loc, "zone": zone}})
    return out


# ── applications ──────────────────────────────────────────────────────────────
def _app_view(store, rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def _page(items, query, key):
    try:
        size = min(int(query.get("pageSize") or 100), 1000)
        start = int(query.get("pageToken") or 0)
    except Exception:
        raise _bad("Invalid pageSize/pageToken.")
    out = {key: items[start:start + size]}
    if start + size < len(items):
        out["nextPageToken"] = str(start + size)
    return out


def _applications(store, method, project, loc, rest, verb, payload, query):
    apps = _x(store, "apphub_apps")
    pre = "projects/%s/locations/%s/applications/" % (project, loc)
    if not rest:
        if method == "GET" and loc == "-":      # locations/- lists across every location, like the real API
            return _page([_app_view(store, v) for k, v in sorted(apps.items()) if k.startswith("projects/%s/locations/" % project)], query, "applications")
        if method == "GET":
            return _page([_app_view(store, v) for k, v in sorted(apps.items()) if k.startswith(pre)], query, "applications")
        if method == "POST":
            aid = query.get("applicationId") or ""
            if not ID_RE.match(aid):
                raise _bad("applicationId must match [a-z]([-a-z0-9]*[a-z0-9])? and be at most 63 characters.")
            if pre + aid in apps:
                raise _E(409, "ALREADY_EXISTS", "Application %s already exists." % aid)
            scope = (payload.get("scope") or {}).get("type")
            if scope not in SCOPES:
                raise _bad("scope.type is required (REGIONAL or GLOBAL).")
            if scope == "GLOBAL" and loc != "global":
                raise _bad("A GLOBAL application must be created in location 'global'.")
            if scope == "REGIONAL" and loc == "global":
                raise _bad("A REGIONAL application cannot be created in location 'global'.")
            if len(str(payload.get("displayName", ""))) > 63 or len(str(payload.get("description", ""))) > 2048:
                raise _bad("displayName must be at most 63 and description at most 2048 characters.")
            now = _now()
            rec = {"name": pre + aid, "displayName": payload.get("displayName", ""), "description": payload.get("description", ""),
                   "attributes": _validate_attrs(payload.get("attributes")), "createTime": now, "updateTime": now,
                   "scope": {"type": scope}, "uid": str(uuid.uuid4()), "state": "ACTIVE"}
            apps[pre + aid] = rec
            return _lro(project, loc, _app_view(store, rec))
        raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)
    full = pre + rest[0]
    rec = apps.get(full)
    if rec is None:
        raise _E(404, "NOT_FOUND", "Application %s not found." % rest[0])
    if len(rest) >= 2 and rest[1] in ("services", "workloads"):
        return _children(store, method, project, loc, rec, rest[1], rest[2:], payload, query)
    if method == "GET":
        return _app_view(store, rec)
    if method == "DELETE":
        if any(c["name"].startswith(full + "/") for coll in ("apphub_services", "apphub_workloads") for c in _x(store, coll).values()):
            raise _E(400, "FAILED_PRECONDITION", "Application %s still has registered services or workloads; delete them first." % rest[0])
        del apps[full]
        return _lro(project, loc, {}, "delete")
    if method == "PATCH":
        mask = [m for m in (query.get("updateMask") or "").split(",") if m] or [k for k in payload if k in ("displayName", "description", "attributes")]
        for m in mask:
            if m not in ("displayName", "description", "attributes"):
                raise _bad("Unsupported update_mask path %r (scope is immutable)." % m)
        if "attributes" in mask:
            rec["attributes"] = _validate_attrs(payload.get("attributes"))
        for m in ("displayName", "description"):
            if m in mask:
                rec[m] = payload.get(m, "")
        rec["updateTime"] = _now()
        return _lro(project, loc, _app_view(store, rec), "update")
    raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)


def _children(store, method, project, loc, app, kind, rest, payload, query):
    coll = "apphub_services" if kind == "services" else "apphub_workloads"
    items = _x(store, coll)
    pre = app["name"] + "/" + kind + "/"
    disc_key, ref_key, prop_key = (("discoveredService", "serviceReference", "serviceProperties") if kind == "services"
                                   else ("discoveredWorkload", "workloadReference", "workloadProperties"))
    if not rest:
        if method == "GET":
            return _page([v for k, v in sorted(items.items()) if k.startswith(pre)], query, kind)
        if method == "POST":
            cid = query.get("serviceId" if kind == "services" else "workloadId") or ""
            if not ID_RE.match(cid):
                raise _bad("%sId must match [a-z]([-a-z0-9]*[a-z0-9])? and be at most 63 characters." % kind[:-1])
            if pre + cid in items:
                raise _E(409, "ALREADY_EXISTS", "%s %s already exists." % (kind[:-1].capitalize(), cid))
            dn = payload.get(disc_key)
            if not dn:
                raise _bad("%s is required." % disc_key)
            pool = discovered_services(store, project, loc) if kind == "services" else discovered_workloads(store, project, loc)
            found = next((d for d in pool if d["name"] == dn), None)
            if found is None:
                raise _E(404, "NOT_FOUND", "The %s '%s' was not found in location %s." % (disc_key, dn, loc))
            for other in items.values():
                if other[disc_key] == dn:
                    raise _E(409, "ALREADY_EXISTS", "%s is already registered in application %s." % (dn, other["name"].split("/")[5]))
            now = _now()
            rec = {"name": pre + cid, "displayName": payload.get("displayName", ""), "description": payload.get("description", ""),
                   "attributes": _validate_attrs(payload.get("attributes")), disc_key: dn, ref_key: found[ref_key], prop_key: found[prop_key],
                   "createTime": now, "updateTime": now, "uid": str(uuid.uuid4()), "state": "ACTIVE"}
            items[pre + cid] = rec
            return _lro(project, loc, rec)
        raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)
    full = pre + rest[0]
    rec = items.get(full)
    if rec is None:
        raise _E(404, "NOT_FOUND", "%s %s not found." % (kind[:-1].capitalize(), rest[0]))
    if method == "GET":
        return rec
    if method == "DELETE":
        del items[full]
        return _lro(project, loc, {}, "delete")
    if method == "PATCH":
        for m in ("displayName", "description"):
            if m in payload:
                rec[m] = payload[m]
        if "attributes" in payload:
            rec["attributes"] = _validate_attrs(payload["attributes"])
        rec["updateTime"] = _now()
        return _lro(project, loc, rec, "update")
    raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)


def dispatch(store, method, path, query=None, headers=None, body=b""):
    query, method = query or {}, method.upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        return Resp(400, {"error": {"code": 400, "message": "Invalid JSON payload received.", "status": "INVALID_ARGUMENT"}})
    p = path.split("?", 1)[0].strip("/")
    segs = p.split("/")
    try:
        project, loc, rest = segs[2], segs[4], segs[5:]
        if rest[:1] == ["applications"]:
            out = _applications(store, method, project, loc, rest[1:], "", payload, query)
        elif rest[:1] in (["discoveredServices"], ["discoveredWorkloads"]) and method == "GET":
            pool = discovered_services(store, project, loc) if rest[0] == "discoveredServices" else discovered_workloads(store, project, loc)
            if len(rest) == 1:
                out = _page(pool, query, rest[0])
            else:
                full = "projects/%s/locations/%s/%s/%s" % (project, loc, rest[0], rest[1])
                out = next((d for d in pool if d["name"] == full), None)
                if out is None:
                    raise _E(404, "NOT_FOUND", "%s not found." % full)
        else:
            raise _E(404, "NOT_FOUND", "Unknown path: %s" % path)
        if method != "GET" and hasattr(store, "persist"):
            store.persist()
        return Resp(200, out)
    except _E as e:
        return Resp(e.status, {"error": {"code": e.status, "message": e.message, "status": e.gcp_status}})
    except (IndexError, ValueError):
        return Resp(404, {"error": {"code": 404, "message": "Unknown path: %s" % path, "status": "NOT_FOUND"}})
