"""GCP Cloud SQL control-plane core — substrate-independent, the GCP analogue of
core/rds_core.py. Speaks the native **Cloud SQL Admin REST API v1** (v1beta4:
`/sql/v1beta4/projects/{project}/instances...`) so the native
`google-cloud-sql-admin` SDK / `gcloud sql` / raw REST work unchanged against it
(point the client's api_endpoint at this endpoint).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide.
Instance + database METADATA persists through the SAME SqlStore seam RDS uses
(core/sql_store.py); Cloud SQL instances are stored via put_instance/get_instance
and each instance record carries its databases map. This keeps one seam for the
whole relational control plane across clouds.

Scope (control plane only): instances.insert / .get / .list / .delete and
databases.insert / .list / .delete, returning Cloud-SQL-shaped JSON resources
(kind "sql#instance" / "sql#database"). The DATA plane (running SQL against an
instance) is deliberately OUT OF SCOPE here: in the browser it is the shared
SqlStore / PGlite engine (the same one rds_core.execute_sql drives), exposed
separately — this core only models the control plane, mirroring rds_core.

GCP errors use the Google JSON API shape `{"error":{"code","message","status"}}`
(status is the canonical enum, e.g. NOT_FOUND / ALREADY_EXISTS).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.sql_store import SqlStore

# Cloud SQL keys instances by name WITHIN a project; we namespace the SqlStore
# key by project so two projects can reuse an instance name.
_DEFAULT_REGION = "us-central1"
_DEFAULT_TIER = "db-custom-1-3840"


@dataclass
class CloudSqlResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


# ── primitives ─────────────────────────────────────────────────────────────
def _key(project: str, instance: str) -> str:
    return f"cloudsql:{project}/{instance}"


def _etag() -> str:
    return uuid.uuid4().hex[:16]


def _json(status: int, obj: dict) -> CloudSqlResponse:
    return CloudSqlResponse(status=status, body=json.dumps(obj).encode())


def _err(http_status: int, status: str, message: str) -> CloudSqlResponse:
    body = {"error": {"code": http_status, "message": message, "status": status,
                      "errors": [{"domain": "global", "reason": status.lower(),
                                  "message": message}]}}
    return CloudSqlResponse(status=http_status, body=json.dumps(body).encode())


def _not_found(message: str) -> CloudSqlResponse:
    return _err(404, "NOT_FOUND", message)


# ── resource views ─────────────────────────────────────────────────────────
def _instance_view(rec: dict) -> dict:
    project = rec["project"]
    name = rec["name"]
    region = rec.get("region", _DEFAULT_REGION)
    settings = rec.get("settings", {})
    ip_config = settings.get("ipConfiguration", {})
    backup_config = settings.get("backupConfiguration", {})
    view = {
        "kind": "sql#instance",
        "name": name,
        "project": project,
        "state": rec.get("state", "RUNNABLE"),
        "databaseVersion": rec.get("databaseVersion", "POSTGRES_15"),
        "backendType": "SECOND_GEN",
        "instanceType": rec.get("instanceType", "CLOUD_SQL_INSTANCE"),
        "connectionName": f"{project}:{region}:{name}",
        "region": region,
        "gceZone": rec.get("gceZone", f"{region}-a"),
        "serviceAccountEmailAddress": rec.get(
            "serviceAccountEmailAddress",
            f"{name}@{project}.iam.gserviceaccount.com"),
        "settings": {
            "kind": "sql#settings",
            "tier": settings.get("tier", _DEFAULT_TIER),
            "activationPolicy": settings.get("activationPolicy", "ALWAYS"),
            "dataDiskSizeGb": str(settings.get("dataDiskSizeGb", "10")),
            "dataDiskType": settings.get("dataDiskType", "PD_SSD"),
            "pricingPlan": settings.get("pricingPlan", "PER_USE"),
            "settingsVersion": str(settings.get("settingsVersion", "1")),
            "storageAutoResize": settings.get("storageAutoResize", True),
            "availabilityType": settings.get("availabilityType", "ZONAL"),
            "deletionProtectionEnabled": settings.get("deletionProtectionEnabled", False),
            "userLabels": settings.get("userLabels", {}),
            "databaseFlags": settings.get("databaseFlags", []),
            "ipConfiguration": {
                "ipv4Enabled": ip_config.get("ipv4Enabled", True),
                "privateNetwork": ip_config.get("privateNetwork"),
                "authorizedNetworks": ip_config.get("authorizedNetworks", []),
            },
            "backupConfiguration": {
                "kind": "sql#backupConfiguration",
                "enabled": backup_config.get("enabled", True),
                "pointInTimeRecoveryEnabled": backup_config.get("pointInTimeRecoveryEnabled", True),
                "startTime": backup_config.get("startTime", "03:00"),
            },
        },
        "ipAddresses": rec.get("ipAddresses", [
            {"type": "PRIMARY", "ipAddress": "10.0.0.2"}]),
        "createTime": rec.get("createTime", ""),
        "etag": rec.get("etag", ""),
        "selfLink": (f"https://sqladmin.googleapis.com/sql/v1beta4/projects/"
                     f"{project}/instances/{name}"),
    }
    if rec.get("masterInstanceName"):
        view["masterInstanceName"] = rec["masterInstanceName"]
    return view


def _database_view(project: str, instance: str, db: dict) -> dict:
    name = db["name"]
    return {
        "kind": "sql#database",
        "name": name,
        "project": project,
        "instance": instance,
        "charset": db.get("charset", "UTF8"),
        "collation": db.get("collation", "en_US.UTF8"),
        "etag": db.get("etag", _etag()),
        "selfLink": (f"https://sqladmin.googleapis.com/sql/v1beta4/projects/"
                     f"{project}/instances/{instance}/databases/{name}"),
    }


# ── store helpers (Cloud SQL metadata rides the shared SqlStore seam) ───────
def _get_instance(store: SqlStore, project: str, instance: str) -> dict | None:
    return store.get_instance(_key(project, instance))


def _list_instances(store: SqlStore, project: str) -> list[dict]:
    prefix = f"cloudsql:{project}/"
    recs = [store.get_instance(k) for k in store.instance_ids()
            if k.startswith(prefix)]
    return [r for r in recs if r]


def _backup_key(project: str, instance: str, backup_id: str) -> str:
    return f"cloudsql-backup:{project}/{instance}/{backup_id}"


def _replicas_of(store: SqlStore, project: str, master: str) -> list[dict]:
    return [r for r in _list_instances(store, project) if r.get("masterInstanceName") == master]


def _mirror_to_replicas(store: SqlStore, project: str, master: str) -> None:
    """Read replicas mirror the primary's control-plane metadata (databases, users) —
    the state this core manages — synchronously on every write, so a replica never
    lags behind on them (see gcp.sql.replicas in core/capabilities/gcp/sql.json)."""
    rec = _get_instance(store, project, master)
    if not rec:
        return
    dbs = {k: dict(v) for k, v in rec.get("databases", {}).items()}
    users = {k: dict(v) for k, v in rec.get("users", {}).items()}
    for rep in _replicas_of(store, project, master):
        rep["databases"] = {k: dict(v) for k, v in dbs.items()}
        rep["users"] = {k: dict(v) for k, v in users.items()}


def _operation(instance: str, op_type: str) -> dict:
    return {"kind": "sql#operation", "name": uuid.uuid4().hex, "operationType": op_type,
            "status": "DONE", "targetId": instance, "insertTime": "", "endTime": ""}


def _log_op(rec: dict, op_type: str) -> dict:
    op = _operation(rec["name"], op_type)
    rec.setdefault("operations", []).insert(0, op)
    return op


def _operation_view(op: dict, project: str, instance: str) -> dict:
    return {**op, "selfLink": (f"https://sqladmin.googleapis.com/sql/v1beta4/projects/"
                               f"{project}/operations/{op['name']}"),
            "targetLink": (f"https://sqladmin.googleapis.com/sql/v1beta4/projects/"
                           f"{project}/instances/{instance}")}


# ── control-plane operations: instances ────────────────────────────────────
def _insert_instance(store: SqlStore, project: str, body: dict) -> CloudSqlResponse:
    name = str(body.get("name", "")).strip()
    if not name:
        return _err(400, "INVALID_ARGUMENT", "Instance name is required.")
    if _get_instance(store, project, name):
        return _err(409, "ALREADY_EXISTS",
                    f"The Cloud SQL instance already exists. Instance: {name}")
    master = str(body.get("masterInstanceName", "") or "").strip()
    if master and not _get_instance(store, project, master):
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {master}")
    settings = body.get("settings") or {}
    if "tier" not in settings:
        settings["tier"] = _DEFAULT_TIER
    rec = {
        "name": name,
        "project": project,
        "state": "RUNNABLE",  # Nano: no provisioning lag, ready at once
        "databaseVersion": str(body.get("databaseVersion", "POSTGRES_15")),
        "region": str(body.get("region", _DEFAULT_REGION)),
        "gceZone": str(body.get("gceZone", f"{body.get('region', _DEFAULT_REGION)}-a")),
        "settings": settings,
        "etag": _etag(),
        "databases": {},  # name -> database metadata (control-plane view)
        "users": {},       # "name@host" -> user metadata
        "operations": [],  # most-recent-first
    }
    if master:
        rec["masterInstanceName"] = master
        rec["instanceType"] = "READ_REPLICA_INSTANCE"
    op = _log_op(rec, "CREATE_REPLICA" if master else "CREATE")
    store.put_instance(_key(project, name), rec)
    if master:
        _mirror_to_replicas(store, project, master)  # seed the new replica from the primary's current state
    store.persist()
    return _json(200, _operation_view(op, project, name))   # native instances.insert → Operation


def _DEEP_MERGE(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _DEEP_MERGE(dst[k], v)
        else:
            dst[k] = v
    return dst


def _patch_instance(store: SqlStore, project: str, instance: str, body: dict) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    settings = body.get("settings")
    if isinstance(settings, dict):
        _DEEP_MERGE(rec.setdefault("settings", {}), settings)
        policy = rec["settings"].get("activationPolicy")
        if policy == "NEVER":
            rec["state"] = "STOPPED"
        elif policy:
            rec["state"] = "RUNNABLE"
    rec["etag"] = _etag()
    op = _log_op(rec, "UPDATE")
    store.persist()
    return _json(200, _operation_view(op, project, instance))


def _restart_instance(store: SqlStore, project: str, instance: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    rec["state"] = "RUNNABLE"
    op = _log_op(rec, "RESTART")
    store.persist()
    return _json(200, _operation_view(op, project, instance))


def _list_operations(store: SqlStore, project: str, instance: str | None) -> CloudSqlResponse:
    if instance:
        rec = _get_instance(store, project, instance)
        if not rec:
            return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
        ops = rec.get("operations", [])
    else:
        ops = []
        for rec in _list_instances(store, project):
            ops.extend(rec.get("operations", []))
        ops.sort(key=lambda o: o.get("name", ""), reverse=True)
    items = [_operation_view(o, project, o["targetId"]) for o in ops]
    out: dict = {"kind": "sql#operationsList"}
    if items:
        out["items"] = items
    return _json(200, out)


def _get_instance_resp(store: SqlStore, project: str, instance: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    return _json(200, _instance_view(rec))


def _list_instances_resp(store: SqlStore, project: str) -> CloudSqlResponse:
    items = [_instance_view(r) for r in _list_instances(store, project)]
    out: dict = {"kind": "sql#instancesList"}
    if items:
        out["items"] = items
    return _json(200, out)


def _delete_instance(store: SqlStore, project: str, instance: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    if _replicas_of(store, project, instance):
        return _err(400, "FAILED_PRECONDITION",
                    f"The instance cannot be deleted because it has read replicas. Instance: {instance}")
    for bid in _list_backup_ids(store, project, instance):
        store.snapshots.pop(_backup_key(project, instance, bid), None)
    store.drop_instance(_key(project, instance))
    store.persist()
    return _json(200, {"kind": "sql#operation", "operationType": "DELETE",
                       "status": "DONE", "name": str(uuid.uuid4()),
                       "targetId": instance})


# ── control-plane operations: databases ────────────────────────────────────
def _insert_database(store: SqlStore, project: str, instance: str,
                     body: dict) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    name = str(body.get("name", "")).strip()
    if not name:
        return _err(400, "INVALID_ARGUMENT", "Database name is required.")
    dbs = rec.setdefault("databases", {})
    if name in dbs:
        return _err(409, "ALREADY_EXISTS",
                    f"The database already exists. Database: {name}")
    dbs[name] = {
        "name": name,
        "charset": str(body.get("charset", "UTF8")),
        "collation": str(body.get("collation", "en_US.UTF8")),
        "etag": _etag(),
    }
    _mirror_to_replicas(store, project, instance)
    store.persist()
    return _json(200, _database_view(project, instance, dbs[name]))


def _list_databases(store: SqlStore, project: str, instance: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    dbs = rec.get("databases", {})
    items = [_database_view(project, instance, dbs[n]) for n in sorted(dbs)]
    out: dict = {"kind": "sql#databasesList"}
    if items:
        out["items"] = items
    return _json(200, out)


def _delete_database(store: SqlStore, project: str, instance: str,
                     database: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    dbs = rec.get("databases", {})
    if database not in dbs:
        return _not_found(f"The database does not exist. Database: {database}")
    dbs.pop(database, None)
    _mirror_to_replicas(store, project, instance)
    store.persist()
    return _json(200, {"kind": "sql#operation", "operationType": "DELETE_DATABASE",
                       "status": "DONE", "name": str(uuid.uuid4()),
                       "targetId": instance})


# ── control-plane operations: users ─────────────────────────────────────────
def _user_key(name: str, host: str) -> str:
    return f"{name}@{host or '%'}"


def _user_view(project: str, instance: str, u: dict) -> dict:
    return {"kind": "sql#user", "name": u["name"], "host": u.get("host", "%"),
            "project": project, "instance": instance,
            "type": u.get("type", "BUILT_IN"), "etag": u.get("etag", _etag())}


def _insert_user(store: SqlStore, project: str, instance: str, body: dict) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    name = str(body.get("name", "")).strip()
    if not name:
        return _err(400, "INVALID_ARGUMENT", "User name is required.")
    host = str(body.get("host", "%") or "%")
    users = rec.setdefault("users", {})
    key = _user_key(name, host)
    if key in users:
        return _err(409, "ALREADY_EXISTS", f"The user already exists. User: {name}")
    users[key] = {"name": name, "host": host, "type": body.get("type", "BUILT_IN"),
                 "password": body.get("password", ""), "etag": _etag()}
    _log_op(rec, "CREATE_USER")
    _mirror_to_replicas(store, project, instance)
    store.persist()
    return _json(200, _user_view(project, instance, users[key]))


def _list_users(store: SqlStore, project: str, instance: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    users = rec.get("users", {})
    items = [_user_view(project, instance, users[k]) for k in sorted(users)]
    out: dict = {"kind": "sql#usersList"}
    if items:
        out["items"] = items
    return _json(200, out)


def _update_user(store: SqlStore, project: str, instance: str, name: str,
                 host: str, body: dict) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    users = rec.get("users", {})
    key = _user_key(name, host)
    if key not in users:
        return _not_found(f"The user does not exist. User: {name}")
    if "password" in body:
        users[key]["password"] = body["password"]
    users[key]["etag"] = _etag()
    _log_op(rec, "UPDATE_USER")
    _mirror_to_replicas(store, project, instance)
    store.persist()
    return _json(200, {"kind": "sql#operation", "operationType": "UPDATE_USER",
                       "status": "DONE", "name": str(uuid.uuid4()), "targetId": instance})


def _delete_user(store: SqlStore, project: str, instance: str, name: str, host: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    users = rec.get("users", {})
    key = _user_key(name, host)
    if key not in users:
        return _not_found(f"The user does not exist. User: {name}")
    users.pop(key, None)
    _log_op(rec, "DELETE_USER")
    _mirror_to_replicas(store, project, instance)
    store.persist()
    return _json(200, {"kind": "sql#operation", "operationType": "DELETE_USER",
                       "status": "DONE", "name": str(uuid.uuid4()), "targetId": instance})


# ── control-plane operations: backup runs ───────────────────────────────────
def _list_backup_ids(store: SqlStore, project: str, instance: str) -> list[str]:
    prefix = _backup_key(project, instance, "")
    return [k[len(prefix):] for k in store.snapshot_ids() if k.startswith(prefix)]


def _backup_view(b: dict) -> dict:
    return {"kind": "sql#backupRun", "id": b["id"], "project": b["project"], "instance": b["instance"],
            "status": "SUCCESSFUL", "type": b.get("type", "ON_DEMAND"), "description": b.get("description", ""),
            "enqueuedTime": b.get("enqueuedTime", ""), "startTime": b.get("startTime", ""),
            "endTime": b.get("endTime", ""), "location": b.get("location", "us"),
            "windowStartTime": b.get("windowStartTime", ""),
            "selfLink": (f"https://sqladmin.googleapis.com/sql/v1beta4/projects/"
                         f"{b['project']}/instances/{b['instance']}/backupRuns/{b['id']}")}


def _insert_backup(store: SqlStore, project: str, instance: str, body: dict) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    backup_id = str(uuid.uuid4().int % 10_000_000_000)
    b = {"id": backup_id, "project": project, "instance": instance, "type": "ON_DEMAND",
         "description": str(body.get("description", "")),
         # Point-in-time snapshot of the control-plane metadata this core manages, restored
         # by instances.restoreBackup. Row-level SQL data lives in the separate SQL data
         # plane (see module docstring) and isn't captured here.
         "snapshot": {"databases": {k: dict(v) for k, v in rec.get("databases", {}).items()},
                      "users": {k: dict(v) for k, v in rec.get("users", {}).items()}}}
    store.put_snapshot(_backup_key(project, instance, backup_id), b)
    _log_op(rec, "BACKUP_VOLUME")
    store.persist()
    return _json(200, _backup_view(b))


def _list_backups(store: SqlStore, project: str, instance: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    items = [_backup_view(store.get_snapshot(_backup_key(project, instance, bid)))
             for bid in sorted(_list_backup_ids(store, project, instance), reverse=True)]
    out: dict = {"kind": "sql#backupRunsList"}
    if items:
        out["items"] = items
    return _json(200, out)


def _get_backup(store: SqlStore, project: str, instance: str, backup_id: str) -> CloudSqlResponse:
    b = store.get_snapshot(_backup_key(project, instance, backup_id))
    if not b:
        return _not_found(f"The backupRun does not exist. BackupRun: {backup_id}")
    return _json(200, _backup_view(b))


def _delete_backup(store: SqlStore, project: str, instance: str, backup_id: str) -> CloudSqlResponse:
    key = _backup_key(project, instance, backup_id)
    if not store.get_snapshot(key):
        return _not_found(f"The backupRun does not exist. BackupRun: {backup_id}")
    store.snapshots.pop(key, None)
    rec = _get_instance(store, project, instance)
    if rec:
        _log_op(rec, "DELETE_BACKUP")
    store.persist()
    return _json(200, {"kind": "sql#operation", "operationType": "DELETE_BACKUP",
                       "status": "DONE", "name": str(uuid.uuid4()), "targetId": instance})


def _restore_backup(store: SqlStore, project: str, instance: str, body: dict) -> CloudSqlResponse:
    """instances.restoreBackup — replaces the target instance's databases/users with the
    backupRun's snapshot (native restoreBackupContext.backupRunId[/instanceId])."""
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    ctx = body.get("restoreBackupContext") or {}
    backup_id = str(ctx.get("backupRunId", "")).strip()
    source_instance = str(ctx.get("instanceId", "") or instance).strip()
    b = store.get_snapshot(_backup_key(project, source_instance, backup_id))
    if not b:
        return _not_found(f"The backupRun does not exist. BackupRun: {backup_id}")
    snap = b.get("snapshot") or {}
    rec["databases"] = {k: dict(v) for k, v in snap.get("databases", {}).items()}
    rec["users"] = {k: dict(v) for k, v in snap.get("users", {}).items()}
    rec["etag"] = _etag()
    op = _log_op(rec, "RESTORE_VOLUME")
    _mirror_to_replicas(store, project, instance)
    store.persist()
    return _json(200, _operation_view(op, project, instance))


# ── native-wire dispatcher (REST path + method → operation) ────────────────
# Single routing point for the native Cloud SQL Admin REST API — what an
# unmodified google-cloud-sql-admin / gcloud sql client speaks.
def dispatch(store: SqlStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> CloudSqlResponse:
    method = method.upper()

    # Strip the API prefix; keep only the resource path.
    raw_path = path.split("?", 1)[0]
    p = raw_path
    for pre in ("/sql/v1beta4", "/v1beta4", "/sql/v1", "/v1"):
        if p.startswith(pre):
            p = p[len(pre):]
            break
    segs = [s for s in p.strip("/").split("/") if s != ""]
    query = query or {}

    if len(segs) < 2 or segs[0] != "projects":
        return _not_found(f"Unknown path: {path}")
    project = segs[1]

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    # /projects/{p}/operations[/{name}]  → project-wide operations log
    if len(segs) >= 3 and segs[2] == "operations":
        if method != "GET":
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on operations")
        if len(segs) == 3:
            return _list_operations(store, project, query.get("instance"))
        op_name = segs[3]
        for rec in _list_instances(store, project):
            for op in rec.get("operations", []):
                if op["name"] == op_name:
                    return _json(200, _operation_view(op, project, rec["name"]))
        return _not_found(f"The operation does not exist. Operation: {op_name}")

    if len(segs) < 3 or segs[2] != "instances":
        return _not_found(f"Unknown path: {path}")

    # /projects/{p}/instances  → instances collection
    if len(segs) == 3:
        if method == "POST":
            return _insert_instance(store, project, payload)
        if method == "GET":
            return _list_instances_resp(store, project)
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on instances")

    # Colon-suffixed RPCs (instances.restart) arrive as "{instance}:restart" in one segment.
    instance_seg = segs[3]
    instance, verb = (instance_seg.split(":", 1) + [None])[:2] if ":" in instance_seg else (instance_seg, None)

    # /projects/{p}/instances/{i}  → single instance (+ colon RPCs)
    if len(segs) == 4:
        if verb == "restart" and method == "POST":
            return _restart_instance(store, project, instance)
        if verb == "restoreBackup" and method == "POST":
            return _restore_backup(store, project, instance, payload)
        if method == "GET":
            return _get_instance_resp(store, project, instance)
        if method == "PATCH":
            return _patch_instance(store, project, instance, payload)
        if method == "DELETE":
            return _delete_instance(store, project, instance)
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on instance")

    # /projects/{p}/instances/{i}/databases[...]
    if segs[4] == "databases":
        # collection
        if len(segs) == 5:
            if method == "POST":
                return _insert_database(store, project, instance, payload)
            if method == "GET":
                return _list_databases(store, project, instance)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on databases")
        # single database
        if len(segs) == 6:
            database = segs[5]
            if method == "DELETE":
                return _delete_database(store, project, instance, database)
            if method == "GET":
                rec = _get_instance(store, project, instance)
                dbs = (rec or {}).get("databases", {})
                if not rec or database not in dbs:
                    return _not_found(f"The database does not exist. Database: {database}")
                return _json(200, _database_view(project, instance, dbs[database]))
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on database")

    # /projects/{p}/instances/{i}/users  (name + host are query params, not path segments)
    if segs[4] == "users" and len(segs) == 5:
        if method == "POST":
            return _insert_user(store, project, instance, payload)
        if method == "GET":
            return _list_users(store, project, instance)
        if method == "PUT":
            return _update_user(store, project, instance, query.get("name", ""), query.get("host", "%"), payload)
        if method == "DELETE":
            return _delete_user(store, project, instance, query.get("name", ""), query.get("host", "%"))
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on users")

    # /projects/{p}/instances/{i}/backupRuns[/{id}]
    if segs[4] == "backupRuns":
        if len(segs) == 5:
            if method == "POST":
                return _insert_backup(store, project, instance, payload)
            if method == "GET":
                return _list_backups(store, project, instance)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on backupRuns")
        if len(segs) == 6:
            backup_id = segs[5]
            if method == "GET":
                return _get_backup(store, project, instance, backup_id)
            if method == "DELETE":
                return _delete_backup(store, project, instance, backup_id)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on backupRun")

    return _not_found(f"Unknown path: {path}")
