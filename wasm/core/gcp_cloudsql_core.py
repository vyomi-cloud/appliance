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

import hashlib
import json
import re
import time
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
def _ip_addresses(ip_config: dict) -> list[dict]:
    """Native Cloud SQL semantics, now ENFORCED: ipAddresses only carries an entry
    for each network path ipConfiguration actually turns on. Disabling ipv4Enabled
    means the instance has no public address at all — not a disabled one a client
    could still dial — and leaving privateNetwork unset means no private address
    either, matching real instances.get. authorizedNetworks (an allow-list of
    source IPs) stays unenforced: this simulator has no real client IP to filter
    against, same honest limit azure_sql_core.py takes for per-IP firewall rules.
    See gcp.sql.connections in core/capabilities/gcp/sql.json."""
    addrs = []
    if ip_config.get("ipv4Enabled", True):
        addrs.append({"type": "PRIMARY", "ipAddress": "34.148.0.2"})
    if ip_config.get("privateNetwork"):
        addrs.append({"type": "PRIVATE", "ipAddress": "10.0.0.2"})
    return addrs


# ── SSL/TLS (gcp.sql.connections-security): deterministic, realistic-shaped certs —
# same approach gcp_redis_core._ca_cert uses — rather than a real X.509/TLS stack
# (no cryptography/OpenSSL dependency, so this loads under Pyodide). The CA cert is
# generated once at instance creation; client certs are generated on sslCerts.insert
# and their private key is returned ONLY in that response, never stored or
# retrievable again — matching the real API. ──────────────────────────────────────
def _ca_cert(project: str, instance: str) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    return {"kind": "sql#sslCert", "certSerialNumber": "0",
            "cert": ("-----BEGIN CERTIFICATE-----\n"
                     + hashlib.sha256(f"ca-cert:{project}/{instance}".encode()).hexdigest()
                     + "\n-----END CERTIFICATE-----"),
            "commonName": f"C=US,O=Vyomi,CN=Vyomi Cloud SQL Server CA,dnQualifier={instance}",
            "sha1Fingerprint": hashlib.sha1(f"ca:{project}/{instance}".encode()).hexdigest(),
            "instance": instance, "createTime": now, "expirationTime": "2036-01-01T00:00:00.000Z"}


def _client_cert(project: str, instance: str, common_name: str) -> dict:
    serial = uuid.uuid4().hex[:16]
    fingerprint = hashlib.sha1(f"client:{project}/{instance}/{common_name}/{serial}".encode()).hexdigest()
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    return {"kind": "sql#sslCert", "certSerialNumber": serial,
            "cert": ("-----BEGIN CERTIFICATE-----\n"
                     + hashlib.sha256(f"client-cert:{serial}".encode()).hexdigest()
                     + "\n-----END CERTIFICATE-----"),
            "commonName": common_name, "sha1Fingerprint": fingerprint,
            "instance": instance, "createTime": now, "expirationTime": "2036-01-01T00:00:00.000Z",
            "_privateKey": ("-----BEGIN PRIVATE KEY-----\n"
                           + hashlib.sha256(f"client-key:{serial}".encode()).hexdigest()
                           + "\n-----END PRIVATE KEY-----")}


def _ssl_cert_view(project: str, instance: str, c: dict) -> dict:
    return {"kind": "sql#sslCert", "certSerialNumber": c["certSerialNumber"], "cert": c["cert"],
            "commonName": c["commonName"], "sha1Fingerprint": c["sha1Fingerprint"],
            "instance": instance, "project": project, "createTime": c["createTime"],
            "expirationTime": c["expirationTime"],
            "selfLink": (f"https://sqladmin.googleapis.com/sql/v1beta4/projects/{project}/instances/"
                         f"{instance}/sslCerts/{c['sha1Fingerprint']}")}


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
                "sslMode": ip_config.get("sslMode", "ALLOW_UNENCRYPTED_AND_ENCRYPTED"),
                "requireSsl": ip_config.get("sslMode", "ALLOW_UNENCRYPTED_AND_ENCRYPTED")
                != "ALLOW_UNENCRYPTED_AND_ENCRYPTED",
            },
            "backupConfiguration": {
                "kind": "sql#backupConfiguration",
                "enabled": backup_config.get("enabled", True),
                "pointInTimeRecoveryEnabled": backup_config.get("pointInTimeRecoveryEnabled", True),
                "startTime": backup_config.get("startTime", "03:00"),
            },
        },
        "ipAddresses": _ip_addresses(ip_config),
        "serverCaCert": rec.get("serverCaCert") or _ca_cert(project, name),
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
        "serverCaCert": _ca_cert(project, name),
        "sslCerts": {},     # sha1Fingerprint -> client cert metadata (no private key stored)
        "queryLog": [],     # most-recent-first real executed-query log (gcp.sql.insights)
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
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    b = {"id": backup_id, "project": project, "instance": instance, "type": "ON_DEMAND",
         "description": str(body.get("description", "")),
         "enqueuedTime": now, "startTime": now, "endTime": now, "windowStartTime": now,
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


# ── instances.export / instances.import — sqlFile / csvFile in the SIMULATOR's
# own Cloud Storage (gcs_store: the store the GCS console / gsutil / the
# google-cloud-storage SDK read). A gs:// URI is only parsed, never fetched from
# Google; a bucket that doesn't exist fails the operation. The rows are the
# instance's SQL engine behind the SqlStore seam (`rows_store` / `db_id`). ──────
def _gcs_put(gcs_store, bucket: str, obj: str, data: bytes, ctype: str) -> str:
    try:
        from core import gcp_storage_core as gcs
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import gcp_storage_core as gcs  # type: ignore
    r = gcs.dispatch(gcs_store, "POST", f"/upload/storage/v1/b/{bucket}/o",
                     {"uploadType": "media", "name": obj}, {"content-type": ctype}, data)
    if r.status != 200:
        return f"The bucket gs://{bucket} does not exist or the object could not be written."
    return ""


def _gcs_get(gcs_store, bucket: str, obj: str):
    try:
        from core import gcp_storage_core as gcs
    except ImportError:  # pragma: no cover
        import gcp_storage_core as gcs  # type: ignore
    from urllib.parse import quote
    r = gcs.dispatch(gcs_store, "GET", f"/storage/v1/b/{bucket}/o/{quote(obj, safe='')}",
                     {"alt": "media"}, {}, b"")
    return r.body if r.status == 200 else None


def run_export(rows_store: SqlStore, db_id: str, gcs_store, ctx: dict, label: str = "") -> str:
    """Write one exportContext's file. Returns "" or the operation error message."""
    from core import sql_store as sq
    file_type = str(ctx.get("fileType") or "SQL").upper()
    bucket, obj = sq.parse_gs_uri(ctx.get("uri"))
    if gcs_store is None:
        return "No Cloud Storage store is attached to this Cloud SQL engine."
    if not gcs_store.bucket_exists(bucket):
        return f"The bucket gs://{bucket} does not exist."
    if sq.is_async_engine(rows_store):
        return "This instance's SQL engine only answers asynchronously; export is unavailable here."
    dialect = sq.engine_dialect(rows_store)
    if file_type == "CSV":
        query = str((ctx.get("csvExportOptions") or {}).get("selectQuery") or "").strip()
        if not query:
            return "csvExportOptions.selectQuery is required for a CSV export."
        try:
            res = rows_store.execute_sql(db_id, query)
        except Exception as e:  # noqa: BLE001 — a bad query fails the operation
            return f"The select query failed: {e}"
        data = sq.to_csv([[sq.json_cell(v) for v in r] for r in res.get("rows", [])]).encode()
        return _gcs_put(gcs_store, bucket, obj, data, "text/csv")
    if file_type != "SQL":
        return f"Unsupported fileType {file_type!r} (SQL or CSV)."
    tables = sq.dump_tables(rows_store, db_id)
    wanted = [str(t) for t in ((ctx.get("sqlExportOptions") or {}).get("tables") or [])]
    if wanted:
        tables = [t for t in tables if t["name"] in wanted]
    header = (f"Cloud SQL export of {label or db_id}\nDatabases: "
              f"{', '.join(ctx.get('databases') or []) or '(all)'}\nTables: {len(tables)}")
    return _gcs_put(gcs_store, bucket, obj, sq.sql_dump(tables, dialect, header).encode(), "application/sql")


def run_import(rows_store: SqlStore, db_id: str, gcs_store, ctx: dict) -> str:
    """Load one importContext's file into the instance's engine. Returns "" or an error."""
    from core import sql_store as sq
    file_type = str(ctx.get("fileType") or "SQL").upper()
    bucket, obj = sq.parse_gs_uri(ctx.get("uri"))
    if gcs_store is None:
        return "No Cloud Storage store is attached to this Cloud SQL engine."
    if not gcs_store.bucket_exists(bucket):
        return f"The bucket gs://{bucket} does not exist."
    data = _gcs_get(gcs_store, bucket, obj)
    if data is None:
        return f"The object gs://{bucket}/{obj} does not exist."
    if sq.is_async_engine(rows_store):
        return "This instance's SQL engine only answers asynchronously; import is unavailable here."
    text = data.decode("utf-8", "replace")
    try:
        if file_type == "CSV":
            opts = ctx.get("csvImportOptions") or {}
            table = str(opts.get("table") or "").strip()
            if not table:
                return "csvImportOptions.table is required for a CSV import."
            cols = [str(c) for c in opts.get("columns") or []]
            for row in sq.parse_csv(text):
                names = cols or None
                ph = ", ".join(rows_store.param_placeholder(i + 1) for i in range(len(row)))
                col_sql = f" ({', '.join(sq.quote_ident(c) for c in names)})" if names else ""
                rows_store.execute_sql(db_id, f"INSERT INTO {sq.quote_ident(table)}{col_sql} VALUES ({ph})", row)
            return ""
        if file_type != "SQL":
            return f"Unsupported fileType {file_type!r} (SQL or CSV)."
        for stmt in sq.split_sql(text):
            rows_store.execute_sql(db_id, stmt)
    except Exception as e:  # noqa: BLE001 — the failing statement fails the operation
        return f"Import failed: {e}"
    return ""


def _op_error(op: dict, code: str, message: str) -> dict:
    op["error"] = {"kind": "sql#operationErrors",
                   "errors": [{"kind": "sql#operationError", "code": code, "message": message}]}
    return op


def _export_import(store: SqlStore, project: str, instance: str, body: dict, kind: str,
                   gcs_store=None) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    ctx_key = "exportContext" if kind == "EXPORT" else "importContext"
    ctx = body.get(ctx_key) or {}
    from core import sql_store as sq
    try:
        sq.parse_gs_uri(ctx.get("uri"))
    except ValueError as e:
        return _err(400, "INVALID_ARGUMENT", str(e))
    db_id = _key(project, instance)
    msg = (run_export(store, db_id, gcs_store, ctx, label=f"{project}:{instance}") if kind == "EXPORT"
           else run_import(store, db_id, gcs_store, ctx))
    op = _log_op(rec, kind)
    op[ctx_key] = {"kind": f"sql#{ctx_key}", **ctx}
    if msg:
        _op_error(op, "ERROR_RDBMS" if kind == "IMPORT" else "INTERNAL_ERROR", msg)
    store.persist()
    return _json(200, _operation_view(op, project, instance))


# ── sslCerts sub-resource (gcp.sql.connections-security: client/server certs) ──────
def _insert_ssl_cert(store: SqlStore, project: str, instance: str, body: dict) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    common_name = str(body.get("commonName", "")).strip()
    if not common_name:
        return _err(400, "INVALID_ARGUMENT", "commonName is required.")
    cert = _client_cert(project, instance, common_name)
    private_key = cert.pop("_privateKey")
    rec.setdefault("sslCerts", {})[cert["sha1Fingerprint"]] = cert
    op = _log_op(rec, "CREATE_SSL_CERT")
    store.persist()
    return _json(200, {"kind": "sql#sslCertsInsert", "operation": _operation_view(op, project, instance),
                       "serverCaCert": rec.get("serverCaCert") or _ca_cert(project, instance),
                       "clientCert": {"kind": "sql#sslCert",
                                      "certInfo": _ssl_cert_view(project, instance, cert),
                                      "certPrivateKey": private_key}})


def _list_ssl_certs(store: SqlStore, project: str, instance: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    certs = rec.get("sslCerts", {})
    items = [_ssl_cert_view(project, instance, certs[k]) for k in sorted(certs)]
    out: dict = {"kind": "sql#sslCertsList"}
    if items:
        out["items"] = items
    return _json(200, out)


def _get_ssl_cert(store: SqlStore, project: str, instance: str, fingerprint: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    c = rec.get("sslCerts", {}).get(fingerprint)
    if not c:
        return _not_found(f"The SSL cert does not exist. Fingerprint: {fingerprint}")
    return _json(200, _ssl_cert_view(project, instance, c))


def _delete_ssl_cert(store: SqlStore, project: str, instance: str, fingerprint: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    certs = rec.get("sslCerts", {})
    if fingerprint not in certs:
        return _not_found(f"The SSL cert does not exist. Fingerprint: {fingerprint}")
    certs.pop(fingerprint, None)
    op = _log_op(rec, "DELETE_SSL_CERT")
    store.persist()
    return _json(200, _operation_view(op, project, instance))


# ── data-plane query RPC (gcp.sql.insights: Cloud SQL Studio) — NOT a real Admin
# API method (Cloud SQL Studio isn't part of the public Admin REST surface either);
# added the same way core/azure_sql_core.py adds its own `/query` data-plane RPC
# next to the real ARM control plane. Runs against the SAME real engine
# (store.execute_sql, sqlite3 in Nano / a real Postgres or MySQL in Pro/Max) that
# instances.export/import already drive — never synthetic rows. ───────────────────
def _normalize_sql(sql: str) -> str:
    s = re.sub(r"'[^']*'", "?", sql.strip())
    s = re.sub(r"\b\d+\b", "?", s)
    return re.sub(r"\s+", " ", s)[:200]


def _ssl_enforcement_error(rec: dict, body: dict) -> str | None:
    """Cloud SQL Studio is the one client connection Vyomi fully brokers end to end, so
    it's where 'Require SSL/TLS' (sslMode) gets real teeth: ENCRYPTED_ONLY requires the
    caller to acknowledge an encrypted session; TRUSTED_CLIENT_CERTIFICATE_REQUIRED also
    requires a live client cert this instance issued (sslCerts.insert). A raw TCP client
    connecting directly to the shared engine container (gcp_sql_engine.py) is NOT in a
    path Vyomi intercepts, so this setting has no effect there — see
    core/capabilities/gcp/sql.json: gcp.sql.connections-security."""
    mode = rec.get("settings", {}).get("ipConfiguration", {}).get("sslMode", "ALLOW_UNENCRYPTED_AND_ENCRYPTED")
    if mode == "ALLOW_UNENCRYPTED_AND_ENCRYPTED":
        return None
    if not body.get("ssl"):
        return ("SSL connection is required. This instance requires an encrypted connection "
                "(Connections > Security > Require SSL/TLS).")
    if mode == "TRUSTED_CLIENT_CERTIFICATE_REQUIRED":
        fp = str(body.get("clientCertSha1Fingerprint") or "")
        if not fp or fp not in rec.get("sslCerts", {}):
            return ("This instance only accepts connections that present a trusted client "
                     "certificate. Create one under Connections > Security and reconnect.")
    return None


def _log_query(rec: dict, sql: str, duration_ms: float, row_count: int, ok: bool, error: str | None) -> None:
    log = rec.setdefault("queryLog", [])
    log.insert(0, {"sql": sql, "normalized": _normalize_sql(sql), "durationMs": round(duration_ms, 2),
                   "rowCount": row_count, "ok": ok, "error": error,
                   "ts": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "epoch": time.time()})
    del log[200:]


def _run_query(store: SqlStore, project: str, instance: str, body: dict) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    ssl_err = _ssl_enforcement_error(rec, body)
    if ssl_err:
        return _err(400, "FAILED_PRECONDITION", ssl_err)
    sql = str(body.get("sql") or "").strip()
    if not sql:
        return _err(400, "INVALID_ARGUMENT", "sql is required.")
    from core import sql_store as sq
    db_id = _key(project, instance)
    t0 = time.time()
    try:
        res = store.execute_sql(db_id, sql, body.get("params"))
        ok, error = True, None
    except Exception as e:  # noqa: BLE001 — a bad statement fails the query, not the RPC
        res, ok, error = {"columns": [], "rows": [], "rowcount": 0}, False, str(e)
    duration_ms = (time.time() - t0) * 1000
    _log_query(rec, sql, duration_ms, res.get("rowcount", 0), ok, error)
    store.persist()
    return _json(200, {"ok": ok, "columns": res.get("columns", []),
                       "rows": [[sq.json_cell(v) for v in r] for r in res.get("rows", [])],
                       "rowCount": res.get("rowcount", 0), "durationMs": round(duration_ms, 2),
                       "error": error})


def _list_queries(store: SqlStore, project: str, instance: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    return _json(200, {"items": list(rec.get("queryLog", []))})


def _list_tables(store: SqlStore, project: str, instance: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    from core import sql_store as sq
    db_id = _key(project, instance)
    names: list[str] = []
    try:
        if sq.engine_dialect(store) == "sqlite":
            res = store.execute_sql(db_id, "SELECT name FROM sqlite_master WHERE type='table' "
                                            "AND name NOT LIKE 'sqlite_%' ORDER BY name")
        else:
            res = store.execute_sql(db_id, "SELECT table_name FROM information_schema.tables "
                                            "WHERE table_schema = current_schema() ORDER BY table_name")
        names = [r[0] for r in res.get("rows", [])]
    except Exception:
        pass
    return _json(200, {"tables": names})


# ── gcp.sql.insights: System insights — real storage/connection/throughput series
# derived from actual activity (never synthetic). CPU/memory utilization is NOT
# surfaced: no virtualized compute resource backs a Vyomi instance, so there is no
# real OS process to sample — see core/capabilities/gcp/sql.json. ──────────────────
def _storage_bytes(store: SqlStore, db_id: str) -> int:
    from core import sql_store as sq
    try:
        if sq.engine_dialect(store) == "sqlite":
            res = store.execute_sql(db_id, "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
        else:
            res = store.execute_sql(db_id, "SELECT pg_database_size(current_database())")
        if res.get("rows"):
            return int(res["rows"][0][0] or 0)
    except Exception:
        pass
    return 0


def _get_metrics(store: SqlStore, project: str, instance: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    db_id = _key(project, instance)
    now = time.time()
    buckets = [0] * 12   # 12 x 5-minute buckets, oldest -> newest, covering the last hour
    errors = 0
    for entry in rec.get("queryLog", []):
        age = now - entry.get("epoch", now)
        if 0 <= age < 3600:
            buckets[11 - int(age // 300)] += 1
            if not entry.get("ok"):
                errors += 1
    return _json(200, {"storageBytes": _storage_bytes(store, db_id),
                       "activeConnections": store.open_transaction_count(db_id),
                       "queryCount1h": sum(buckets), "errorCount1h": errors,
                       "series": buckets})


# ── native-wire dispatcher (REST path + method → operation) ────────────────
# Single routing point for the native Cloud SQL Admin REST API — what an
# unmodified google-cloud-sql-admin / gcloud sql client speaks.
def dispatch(store: SqlStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", gcs_store=None) -> CloudSqlResponse:
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

    # Native Admin API RPCs are path segments: POST .../instances/{i}/restart|restoreBackup
    # (what gcloud / the client libraries send; the colon form is kept for older callers).
    if len(segs) == 5 and verb is None and method == "POST" and segs[4] in ("restart", "restoreBackup",
                                                                            "export", "import", "query"):
        verb = segs[4]
        segs = segs[:4]

    # /projects/{p}/instances/{i}  → single instance (+ colon RPCs)
    if len(segs) == 4:
        if verb == "restart" and method == "POST":
            return _restart_instance(store, project, instance)
        if verb == "restoreBackup" and method == "POST":
            return _restore_backup(store, project, instance, payload)
        if verb in ("export", "import") and method == "POST":
            return _export_import(store, project, instance, payload, verb.upper(), gcs_store=gcs_store)
        if verb == "query" and method == "POST":
            return _run_query(store, project, instance, payload)
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

    # /projects/{p}/instances/{i}/sslCerts[/{fingerprint}]
    if segs[4] == "sslCerts":
        if len(segs) == 5:
            if method == "POST":
                return _insert_ssl_cert(store, project, instance, payload)
            if method == "GET":
                return _list_ssl_certs(store, project, instance)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on sslCerts")
        if len(segs) == 6:
            fingerprint = segs[5]
            if method == "GET":
                return _get_ssl_cert(store, project, instance, fingerprint)
            if method == "DELETE":
                return _delete_ssl_cert(store, project, instance, fingerprint)
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on sslCert")

    # /projects/{p}/instances/{i}/queries — Cloud SQL Studio's real query log (gcp.sql.insights)
    if segs[4] == "queries" and len(segs) == 5 and method == "GET":
        return _list_queries(store, project, instance)

    # /projects/{p}/instances/{i}/tables — schema browser (gcp.sql.insights)
    if segs[4] == "tables" and len(segs) == 5 and method == "GET":
        return _list_tables(store, project, instance)

    # /projects/{p}/instances/{i}/metrics — System insights (gcp.sql.insights)
    if segs[4] == "metrics" and len(segs) == 5 and method == "GET":
        return _get_metrics(store, project, instance)

    return _not_found(f"Unknown path: {path}")
