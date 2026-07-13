# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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
    return {
        "kind": "sql#instance",
        "name": name,
        "project": project,
        "state": rec.get("state", "RUNNABLE"),
        "databaseVersion": rec.get("databaseVersion", "POSTGRES_15"),
        "backendType": "SECOND_GEN",
        "instanceType": "CLOUD_SQL_INSTANCE",
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
        },
        "ipAddresses": rec.get("ipAddresses", [
            {"type": "PRIMARY", "ipAddress": "10.0.0.2"}]),
        "createTime": rec.get("createTime", ""),
        "etag": rec.get("etag", ""),
        "selfLink": (f"https://sqladmin.googleapis.com/sql/v1beta4/projects/"
                     f"{project}/instances/{name}"),
    }


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


# ── control-plane operations: instances ────────────────────────────────────
def _insert_instance(store: SqlStore, project: str, body: dict) -> CloudSqlResponse:
    name = str(body.get("name", "")).strip()
    if not name:
        return _err(400, "INVALID_ARGUMENT", "Instance name is required.")
    if _get_instance(store, project, name):
        return _err(409, "ALREADY_EXISTS",
                    f"The Cloud SQL instance already exists. Instance: {name}")
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
    }
    store.put_instance(_key(project, name), rec)
    store.persist()
    return _json(200, _instance_view(rec))


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
    store.persist()
    return _json(200, {"kind": "sql#operation", "operationType": "DELETE_DATABASE",
                       "status": "DONE", "name": str(uuid.uuid4()),
                       "targetId": instance})


# ── native-wire dispatcher (REST path + method → operation) ────────────────
# Single routing point for the native Cloud SQL Admin REST API — what an
# unmodified google-cloud-sql-admin / gcloud sql client speaks.
def dispatch(store: SqlStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> CloudSqlResponse:
    method = method.upper()

    # Strip the API prefix; keep only the resource path.
    p = path.split("?", 1)[0]
    for pre in ("/sql/v1beta4", "/v1beta4", "/sql/v1", "/v1"):
        if p.startswith(pre):
            p = p[len(pre):]
            break
    segs = [s for s in p.strip("/").split("/") if s != ""]

    # Expected: projects/{project}/instances[/{instance}[/databases[/{db}]]]
    if len(segs) < 3 or segs[0] != "projects" or segs[2] != "instances":
        return _not_found(f"Unknown path: {path}")
    project = segs[1]

    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    # /projects/{p}/instances  → instances collection
    if len(segs) == 3:
        if method == "POST":
            return _insert_instance(store, project, payload)
        if method == "GET":
            return _list_instances_resp(store, project)
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on instances")

    instance = segs[3]

    # /projects/{p}/instances/{i}  → single instance
    if len(segs) == 4:
        if method == "GET":
            return _get_instance_resp(store, project, instance)
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

    return _not_found(f"Unknown path: {path}")
