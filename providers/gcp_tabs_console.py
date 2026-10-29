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
# Cloud SQL — databases, users, backups, replicas, connectivity, flags, …
# ---------------------------------------------------------------------------
def _sql_err(e):
    return T.TabError(e.status, e.code, e.message)


def _cloudsql(op: str, name: str, body: dict):
    from core import gcp_cloudsql_core as sqlc
    s = _server()
    insts = s.gcp_sql_state.setdefault("instances", {})
    rec = insts.get(name)
    if not isinstance(rec, dict):
        raise T.TabError(404, "NOT_FOUND", "The Cloud SQL instance does not exist. Instance: %s" % name)
    project = str(rec.get("project") or "cloudlearn")
    version = str(rec.get("databaseVersion") or "POSTGRES_15")
    full = lambda: s._gcp_sql_instance_view(project, rec)

    def op_rec(kind, target=None):
        s._gcp_sql_make_operation(project, target or name, kind)
        _usage("sql", op, name, {"instance": name, "operationType": kind})

    v = T.view_op("cloudsql", op)
    if v:
        return {"ok": True, "item": T.view("cloudsql", v, full())}
    patch = T.sql_settings_patch(op, body, rec.get("settings") or {})
    if patch is not None:
        try:
            rec["settings"] = sqlc.patch_settings(version, rec.get("settings") or {}, patch)
        except sqlc.SqlSettingsError as e:
            raise _sql_err(e)
        rec["updateTime"] = s._now()
        op_rec("UPDATE")
        return {"ok": True, "item": full()}
    # databases
    dbs = rec.setdefault("databases", [])
    if op == "listDatabases":
        return {"ok": True, "items": [{"name": d.get("name"), "charset": d.get("charset") or "UTF8",
                                       "collation": d.get("collation") or "en_US.UTF8"} for d in dbs]}
    if op == "createDatabase":
        dn = str(body.get("name") or "").strip()
        if not dn:
            raise T.TabError(400, "INVALID_ARGUMENT", "Database name is required.")
        if any(d.get("name") == dn for d in dbs):
            raise T.TabError(409, "ALREADY_EXISTS", "The database already exists. Database: %s" % dn)
        dbs.append({"name": dn, "charset": str(body.get("charset") or "UTF8"), "collation": str(body.get("collation") or "en_US.UTF8")})
        op_rec("CREATE_DATABASE")
        return {"ok": True, "name": dn}
    if op == "deleteDatabase":
        dn = str(body.get("name") or "")
        if not any(d.get("name") == dn for d in dbs):
            raise T.TabError(404, "NOT_FOUND", "The database does not exist. Database: %s" % dn)
        rec["databases"] = [d for d in dbs if d.get("name") != dn]
        op_rec("DELETE_DATABASE")
        return {"ok": True, "name": dn}
    # users (the instance's master user is a real login on the backing engine)
    users = rec.setdefault("users", [])
    master_user = str(rec.get("masterUsername") or "")
    if master_user and not any(u.get("name") == master_user for u in users):
        users.insert(0, {"name": master_user, "host": "%" if sqlc.engine_of(version) == "MYSQL" else "", "type": "BUILT_IN"})
    if op == "listUsers":
        return {"ok": True, "items": [{"name": u.get("name"), "host": u.get("host") or "", "type": u.get("type") or "BUILT_IN"} for u in users]}
    if op == "createUser":
        try:
            u = sqlc.validate_user(version, body, users)
        except sqlc.SqlSettingsError as e:
            raise _sql_err(e)
        users.append({"name": u["name"], "host": u["host"], "type": u["type"]})
        op_rec("CREATE_USER")
        return {"ok": True, "name": u["name"]}
    if op in ("deleteUser", "setUserPassword"):
        un, host = str(body.get("name") or ""), str(body.get("host") or "")
        if not any(u.get("name") == un and (u.get("host") or "") == host for u in users):
            raise T.TabError(404, "NOT_FOUND", "The user does not exist. User: %s" % un)
        if op == "deleteUser":
            rec["users"] = [u for u in users if not (u.get("name") == un and (u.get("host") or "") == host)]
            op_rec("DELETE_USER")
        else:
            if not str(body.get("password") or ""):
                raise T.TabError(400, "INVALID_ARGUMENT", "Invalid request: a password is required.")
            op_rec("UPDATE_USER")
        return {"ok": True, "name": un}
    # backups (backupRuns)
    backups = s.gcp_sql_state.setdefault("backups", {})
    if op == "listBackups":
        mine = [b for b in backups.values() if isinstance(b, dict) and b.get("instance") == name]
        mine.sort(key=lambda b: b.get("createTime", ""), reverse=True)
        return {"ok": True, "items": [{"id": b.get("name"), "type": b.get("backupType") or "ON_DEMAND",
                                       "status": b.get("status") or "SUCCESSFUL", "description": b.get("description") or "",
                                       "windowStartTime": b.get("createTime", ""), "location": "us"} for b in mine]}
    if op == "createBackup":
        b = s._gcp_sql_backup_record(project, name, {"backupType": "ON_DEMAND", "description": body.get("description") or ""})
        backups[b["name"]] = b
        op_rec("BACKUP_VOLUME")
        return {"ok": True, "id": b["name"]}
    if op == "deleteBackup":
        bid = str(body.get("id") or "")
        b = backups.get(bid)
        if not isinstance(b, dict) or b.get("instance") != name:
            raise T.TabError(404, "NOT_FOUND", "The backup run does not exist. Backup run: %s" % bid)
        del backups[bid]
        op_rec("DELETE_BACKUP")
        return {"ok": True, "id": bid}
    # read replicas: instances whose masterInstanceName is this one
    if op == "listReplicas":
        reps = [r for r in insts.values() if isinstance(r, dict) and r.get("masterInstanceName") == name]
        return {"ok": True, "items": [{"name": r.get("name"), "state": r.get("state") or "RUNNABLE", "region": r.get("region"),
                                       "databaseVersion": r.get("databaseVersion"), "tier": (r.get("settings") or {}).get("tier", ""),
                                       "instanceType": "READ_REPLICA_INSTANCE"} for r in reps]}
    if op == "createReplica":
        if rec.get("masterInstanceName"):
            raise T.TabError(400, "INVALID_ARGUMENT", "Invalid request: cannot create a replica of a read replica.")
        rn = T.validate_name(body.get("name"), "name")
        if rn in insts:
            raise T.TabError(409, "ALREADY_EXISTS", "The Cloud SQL instance already exists. Instance: %s" % rn)
        rep = s._gcp_sql_instance_record(project, {"name": rn, "databaseVersion": version, "region": rec.get("region"),
                                                   "settings": dict(rec.get("settings") or {}),
                                                   "instanceType": "READ_REPLICA_INSTANCE"})
        rep["masterInstanceName"] = name
        rep["_backend"] = rec.get("_backend")          # a replica serves reads from the primary's data
        rep["ipAddresses"] = rec.get("ipAddresses") or rep["ipAddresses"]
        insts[rn] = rep
        rec.setdefault("replicaNames", []).append(rn)
        op_rec("CREATE_REPLICA", rn)
        return {"ok": True, "name": rn}
    if op in ("promoteReplica", "deleteReplica"):
        rn = str(body.get("name") or "")
        rep = insts.get(rn)
        if not isinstance(rep, dict) or rep.get("masterInstanceName") != name:
            raise T.TabError(404, "NOT_FOUND", "%s is not a read replica of %s." % (rn, name))
        rec["replicaNames"] = [x for x in rec.get("replicaNames") or [] if x != rn]
        if op == "promoteReplica":
            rep.pop("masterInstanceName", None)
            rep["instanceType"] = "CLOUD_SQL_INSTANCE"
            op_rec("PROMOTE_REPLICA", rn)
        else:
            del insts[rn]
            op_rec("DELETE", rn)
        return {"ok": True, "name": rn}
    if op == "listOperations":
        ops = [o for o in (s.gcp_sql_state.get("operation_records") or {}).values() if o.get("targetId") == name]
        ops.sort(key=lambda o: o.get("insertTime", ""), reverse=True)
        return {"ok": True, "items": [{"operationType": o.get("operationType"), "status": o.get("status"),
                                       "insertTime": o.get("insertTime"), "endTime": o.get("endTime") or "",
                                       "user": o.get("user"), "name": o.get("name")} for o in ops[:100]]}
    if op == "listQueryInsights":
        out = [s._gcp_sql_query_insight_view(q) for q in (s.gcp_sql_state.get("query_insights") or {}).values()
               if isinstance(q, dict) and q.get("instance") == name]
        return {"ok": True, "items": out}
    return None


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
    "cloudsql": _cloudsql,
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
