"""GCP console resource-detail tabs on the offline appliance.

`/api/gcp/sub/{service}/{op}/{name}` (GET reads, POST writes) for the tabs of the GCP
console's resource-detail pages — the same URL family the Nano service worker maps onto
`_resource` ops (wasm/providers/gcp_core_adapter.py). Each op reads or writes the SAME
state the service's own REST/SDK API uses (server.py's gcp_*_state, the GCP IAM policy,
the cores), so what a tab shows is the resource's real data and a tab edit is visible to
the API, the CLI and the SDKs. Validation and the records no backend models on its own
(snapshots-of-an-instance filtering, Cloud SQL users/flags, …) come from the shared engine
core/gcp_console_tabs.py — the one Nano runs too.

Responses: reads → {"ok": true, "items": [...]} or {"ok": true, "item": {...}}; writes →
{"ok": true, ...}; errors → {"ok": false, "code", "message"} with the HTTP status the real
API uses.
"""
from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import JSONResponse

from core import gcp_console_tabs as T
from core.app_context import _SpaceScopedDictProxy

# Child records / settings no service backend holds itself (space-scoped, persisted with
# the space like every other gcp_* service state).
tab_state = _SpaceScopedDictProxy("gcp_console_tabs", lambda: {"children": {}}, "children")


def _server():
    import server as server_module
    return server_module


def _ctx():
    from core import app_context
    return app_context


def _usage(service: str, op: str, name: str, extra: dict | None = None) -> None:
    """A tab write is an event on the resource (its Activity tab + the space's log)."""
    try:
        event = "gcp.%s.%s" % (service, re.sub(r"(?<!^)(?=[A-Z])", "_", op).lower())
        _ctx().record_usage(event, {"name": name, **(extra or {})})
        _ctx().persist_state()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Compute Engine
# ---------------------------------------------------------------------------
def _instance(name: str) -> dict:
    s = _server()
    try:
        s._gcp_compute_sync_runtime_instances()
    except Exception:
        pass
    for cand in list(s._gcp_compute_instance_bucket().values()) + list(s.gcp_compute_state.get("instances", {}).values()):
        if isinstance(cand, dict) and name in (str(cand.get("name") or ""), str(cand.get("instance_id") or ""),
                                               str(cand.get("gcp_resource_id") or "")):
            return cand
    raise T.TabError(404, "NOT_FOUND", "The resource 'instances/%s' was not found" % name)


def _instance_view(inst: dict) -> dict:
    return _server()._gcp_compute_instance_json(inst)


def _known_machine_types() -> list:
    try:
        from core.instance_catalog import GCP
        return list(GCP.keys())
    except Exception:
        return []


def _compute(op: str, name: str, body: dict):
    s = _server()
    inst = _instance(name)
    iname = str(inst.get("name") or name)
    v = T.view_op("compute", op)
    if v:
        return {"ok": True, "item": T.view("compute", v, _instance_view(inst))}
    if op == "setMetadata":
        items = T.validate_metadata(body.get("items", []))
        inst["metadata_items"] = {i["key"]: i["value"] for i in items}
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), "keys": [i["key"] for i in items]})
        return {"ok": True, "item": _instance_view(inst)}
    if op == "setMachineType":
        T.check_stopped(_instance_view(inst).get("status"), "changing its machine type")
        mt = T.validate_machine_type(body.get("machineType"), _known_machine_types())
        inst["machine_type"] = mt
        inst["instance_type"] = mt
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), "machineType": mt})
        return {"ok": True, "item": _instance_view(inst)}
    if op == "setScheduling":
        sched = T.validate_scheduling(body, _instance_view(inst).get("scheduling"))
        inst["scheduling"] = sched
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), **sched})
        return {"ok": True, "item": _instance_view(inst)}
    if op == "setLabels":
        inst["labels"] = T.validate_labels(body.get("labels", {}))
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", "")})
        return {"ok": True, "item": _instance_view(inst)}
    disks = s.gcp_compute_state.setdefault("disks", {})
    attached = [str(d) for d in (inst.get("attached_disk_names") or [])]
    if op == "listDisks":
        out = []
        for dn in attached:
            d = disks.get(dn)
            if isinstance(d, dict):
                v = s._gcp_compute_disk_view(d)
                out.append({"name": v.get("name"), "boot": bool(d.get("boot")), "sizeGb": str(d.get("sizeGb") or ""),
                            "type": T.short(d.get("type") or "pd-balanced"), "status": v.get("status") or "READY",
                            "autoDelete": bool(d.get("autoDelete")), "mode": "READ_WRITE",
                            "sourceImage": T.short(d.get("sourceImage") or "") or "None",
                            "deviceName": d.get("deviceName") or dn})
        return {"ok": True, "items": out}
    if op == "attachDisk":
        spec = T.disk_spec(body, iname, list(disks.keys()))
        project = str(inst.get("project") or "cloudlearn")
        zone = str(inst.get("zone") or inst.get("az") or "us-central1-a")
        rec = s._gcp_compute_disk_record(project, zone, {**spec, "instance": iname,
                                                          "instance_id": inst.get("instance_id", ""), "deviceName": spec["name"]})
        rec["status"] = "READY"
        disks[rec["name"]] = rec
        inst.setdefault("attached_disk_names", []).append(rec["name"])
        s._gcp_compute_sync_resource_links()
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), "disk": rec["name"]})
        return {"ok": True, "name": rec["name"]}
    if op == "detachDisk":
        dn = str(body.get("name") or "")
        d = disks.get(dn)
        if dn not in attached or not isinstance(d, dict):
            raise T.TabError(404, "NOT_FOUND", "Disk '%s' is not attached to this instance." % dn)
        if d.get("boot"):
            raise T.TabError(400, "INVALID_ARGUMENT", "The boot disk cannot be detached from a VM instance.")
        inst["attached_disk_names"] = [x for x in attached if x != dn]
        d["instance"] = ""
        d["instance_id"] = ""
        d["status"] = "READY"
        s._gcp_compute_sync_resource_links()
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), "disk": dn})
        return {"ok": True, "name": dn}
    snaps = s.gcp_compute_state.setdefault("snapshots", {})
    if op == "listSnapshots":
        mine = [x for x in snaps.values() if isinstance(x, dict) and T.short(x.get("sourceDisk")) in attached]
        return {"ok": True, "items": [{"name": x.get("name"), "sourceDisk": T.short(x.get("sourceDisk")),
                                       "status": x.get("status", "READY"), "sizeGb": str(x.get("sizeGb") or ""),
                                       "storageLocations": ", ".join(x.get("storageLocations") or []),
                                       "created": x.get("created", "")} for x in mine]}
    if op == "createSnapshot":
        spec = T.snapshot_spec(body, attached, list(snaps.keys()))
        d = disks.get(spec["sourceDisk"]) or {}
        rec = s._gcp_compute_snapshot_record(str(inst.get("project") or "cloudlearn"),
                                             {**spec, "sizeGb": d.get("sizeGb") or 10})
        snaps[rec["name"]] = rec
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), "snapshot": rec["name"]})
        return {"ok": True, "name": rec["name"]}
    if op == "deleteSnapshot":
        sn = str(body.get("name") or "")
        x = snaps.get(sn)
        if not isinstance(x, dict) or T.short(x.get("sourceDisk")) not in attached:
            raise T.TabError(404, "NOT_FOUND", "The resource 'snapshots/%s' was not found" % sn)
        del snaps[sn]
        _usage("compute", op, iname, {"instance_id": inst.get("instance_id", ""), "snapshot": sn})
        return {"ok": True, "name": sn}
    return None


# ---------------------------------------------------------------------------
# Cloud Storage — bucket settings (lifecycle, encryption, retention, …)
# ---------------------------------------------------------------------------
def _storage(op: str, name: str, body: dict):
    from core import gcp_storage_core as gcs
    s = _server()
    rec = s.gcp_storage_state.get("buckets", {}).get(name)
    if not isinstance(rec, dict):
        raise T.TabError(404, "NOT_FOUND", "The specified bucket does not exist.")
    project = str(rec.get("project") or "cloudlearn")
    v = T.view_op("storage", op)
    if v:
        return {"ok": True, "item": T.view("storage", v, s._gcp_storage_bucket_view(project, rec))}
    if op == "lockRetention":
        try:
            gcs.lock_retention(rec)
        except gcs.BucketPatchError as e:
            raise T.TabError(e.status, e.reason.upper(), e.message)
        _usage("storage", op, name)
        return {"ok": True, "item": s._gcp_storage_bucket_view(project, rec)}
    patch = T.storage_patch(op, body)
    if patch is None:
        return None
    try:
        gcs.apply_bucket_patch(rec, gcs.validate_bucket_patch(rec, patch))
    except gcs.BucketPatchError as e:
        raise T.TabError(e.status, "INVALID_ARGUMENT" if e.status == 400 else "FAILED_PRECONDITION", e.message)
    _usage("storage", op, name, {"bucket": name, "fields": ",".join(patch)})
    return {"ok": True, "item": s._gcp_storage_bucket_view(project, rec)}


# ---------------------------------------------------------------------------
# Project IAM policy (every resource's Permissions tab)
# ---------------------------------------------------------------------------
def _iam_project(op: str, project: str, body: dict):
    s = _server()
    proj = s._gcp_project_name(project)
    if op == "getProjectPolicy":
        pol = s._gcp_iam_policy_view(proj)
        return {"ok": True, "project": proj, "bindings": pol.get("bindings", []), "etag": pol.get("etag", "")}
    if op in ("grantAccess", "revokeAccess"):
        cur = s._gcp_iam_policy_view(proj)
        fn = T.policy_grant if op == "grantAccess" else T.policy_revoke
        pol = fn(cur, body.get("role"), body.get("member"))
        out = s._gcp_iam_set_policy(proj, pol)
        _usage("iam", op, proj, {"role": body.get("role"), "member": body.get("member")})
        return {"ok": True, "project": proj, "bindings": (out or pol).get("bindings", [])}
    return None


_HANDLERS = {
    "compute": _compute,
    "storage": _storage,
}


async def _dispatch(service: str, op: str, name: str, request: Request):
    body = {}
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
    # /api/gcp/sub isn't a native GCP path, so the provider-alias middleware leaves the request
    # bound to the AWS space; the gcp_* state proxies must resolve the active GCP space.
    from core.app_context import REQUEST_PROVIDER
    token = REQUEST_PROVIDER.set("gcp")
    try:
        out = None
        if service == "iam" and op in ("getProjectPolicy", "grantAccess", "revokeAccess"):
            out = _iam_project(op, name, body)
        elif service in _HANDLERS:
            out = _HANDLERS[service](op, name, body)
        if out is None:
            return JSONResponse({"ok": False, "code": "UNIMPLEMENTED",
                                 "message": "Operation '%s' is not supported for %s." % (op, service)}, status_code=404)
        return JSONResponse(out)
    except T.TabError as e:
        return JSONResponse({"ok": False, "code": e.code, "message": e.message}, status_code=e.status)
    finally:
        REQUEST_PROVIDER.reset(token)


SERVICES = ("compute", "storage", "cloudsql", "pubsub", "firestore", "functions", "apigateway", "vpc",
            "iam", "eventarc", "secretmanager", "kms")


def register(app) -> None:
    for svc in SERVICES:
        async def endpoint(op: str, name: str, request: Request, _svc=svc):
            return await _dispatch(_svc, op, name, request)
        endpoint.__name__ = "gcp_tabs_%s" % svc
        # /api/gcp/sub/... reaches the router as /api/sub/... (provider-alias rewrite); keep both.
        for prefix in ("/api/gcp/sub/", "/api/sub/"):
            app.add_api_route(prefix + svc + "/{op}/{name:path}", endpoint, methods=["GET", "POST"],
                              include_in_schema=False)
