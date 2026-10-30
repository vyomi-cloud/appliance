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
        "instanceType": rec.get("instanceType", "CLOUD_SQL_INSTANCE"),
        "connectionName": f"{project}:{region}:{name}",
        "region": region,
        "gceZone": rec.get("gceZone", f"{region}-a"),
        "serviceAccountEmailAddress": rec.get(
            "serviceAccountEmailAddress",
            f"{name}@{project}.iam.gserviceaccount.com"),
        **({"masterInstanceName": rec["masterInstanceName"]} if rec.get("masterInstanceName") else {}),
        **({"replicaNames": rec["replicaNames"]} if rec.get("replicaNames") else {}),
        "settings": {
            # flags / ipConfiguration / backupConfiguration / insightsConfig / userLabels (instances.patch)
            **{k: v for k, v in settings.items() if k not in ("dataDiskSizeGb", "settingsVersion")},
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
    master = None
    if body.get("masterInstanceName"):                    # read replica of an existing primary
        mname = str(body["masterInstanceName"]).split(":")[-1]
        master = _get_instance(store, project, mname)
        if not master:
            return _not_found(f"The Cloud SQL instance does not exist. Instance: {mname}")
        if master.get("masterInstanceName"):
            return _err(400, "INVALID_ARGUMENT", "Invalid request: cannot create a replica of a read replica.")
    version = str(body.get("databaseVersion") or (master or {}).get("databaseVersion") or "POSTGRES_15")
    region = str(body.get("region") or (master or {}).get("region") or _DEFAULT_REGION)
    eng = engine_of(version)
    rec = {
        "name": name,
        "project": project,
        "state": "RUNNABLE",  # Nano: no provisioning lag, ready at once
        "databaseVersion": version,
        "region": region,
        "gceZone": str(body.get("gceZone", f"{region}-a")),
        "settings": settings,
        "etag": _etag(),
        "databases": {},  # name -> database metadata (control-plane view)
        # the instance's default admin user (postgres / root / sqlserver), as Cloud SQL creates it
        "users": [{"kind": "sql#user", "name": {"MYSQL": "root", "SQLSERVER": "sqlserver"}.get(eng, "postgres"),
                   "host": "%" if eng == "MYSQL" else "", "type": "BUILT_IN"}],
    }
    if master is not None:
        rec["masterInstanceName"] = master["name"]
        rec["instanceType"] = "READ_REPLICA_INSTANCE"
        rec["users"] = list(master.get("users") or rec["users"])
        master.setdefault("replicaNames", []).append(name)
        store.put_instance(_key(project, master["name"]), master)
        _op(master, "CREATE_REPLICA", name)
    _op(rec, "CREATE")
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
    if rec.get("replicaNames"):
        return _err(400, "INVALID_ARGUMENT",
                    "Invalid request: the instance has read replicas (%s); delete them first." % ", ".join(rec["replicaNames"]))
    master = _get_instance(store, project, rec.get("masterInstanceName") or "") if rec.get("masterInstanceName") else None
    if master:
        master["replicaNames"] = [n for n in master.get("replicaNames") or [] if n != instance]
        _op(master, "DELETE_REPLICA", instance)
        store.put_instance(_key(project, master["name"]), master)
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
    _op(rec, "CREATE_DATABASE")
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
    _op(rec, "DELETE_DATABASE")
    store.persist()
    return _json(200, {"kind": "sql#operation", "operationType": "DELETE_DATABASE",
                       "status": "DONE", "name": str(uuid.uuid4()),
                       "targetId": instance})


# ── settings validation (instances.patch) — shared with the offline appliance ──
# Database flags, connectivity (ipConfiguration), automated backups and Query
# Insights are instance settings; one validator serves Nano's PATCH below and the
# offline appliance's (providers/gcp_services.py), so both reject the same input
# with the same Cloud SQL error.
class SqlSettingsError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


_ONOFF = ("on", "off")
# name -> (kind, allowed) ; kind: int (lo, hi) | enum (values) | float (lo, hi) | str
FLAGS = {
    "POSTGRES": {
        "max_connections": ("int", (14, 262143)), "log_min_duration_statement": ("int", (-1, 2147483647)),
        "log_connections": ("enum", _ONOFF), "log_disconnections": ("enum", _ONOFF),
        "log_statement": ("enum", ("none", "ddl", "mod", "all")), "log_lock_waits": ("enum", _ONOFF),
        "log_temp_files": ("int", (-1, 2147483647)), "work_mem": ("int", (64, 2147483647)),
        "maintenance_work_mem": ("int", (1024, 2147483647)), "autovacuum": ("enum", _ONOFF),
        "cloudsql.iam_authentication": ("enum", _ONOFF), "cloudsql.enable_pgaudit": ("enum", _ONOFF),
        "idle_in_transaction_session_timeout": ("int", (0, 2147483647)), "statement_timeout": ("int", (0, 2147483647)),
        "temp_file_limit": ("int", (-1, 2147483647)), "track_activity_query_size": ("int", (100, 1048576)),
        "pg_stat_statements.track": ("enum", ("none", "top", "all")), "timezone": ("str", None),
    },
    "MYSQL": {
        "max_connections": ("int", (1, 100000)), "slow_query_log": ("enum", _ONOFF),
        "long_query_time": ("float", (0, 30000000)), "general_log": ("enum", _ONOFF),
        "log_output": ("enum", ("TABLE", "FILE", "NONE")), "innodb_lock_wait_timeout": ("int", (1, 1073741824)),
        "wait_timeout": ("int", (1, 31536000)), "sql_mode": ("str", None),
        "character_set_server": ("enum", ("utf8", "utf8mb4", "latin1")), "cloudsql_iam_authentication": ("enum", _ONOFF),
        "log_bin_trust_function_creators": ("enum", _ONOFF), "max_allowed_packet": ("int", (16384, 1073741824)),
        "default_time_zone": ("str", None),
    },
    "SQLSERVER": {
        "cross db ownership chaining": ("enum", _ONOFF), "contained database authentication": ("enum", _ONOFF),
        "max server memory (mb)": ("int", (1000, 2147483647)), "user connections": ("int", (0, 32767)),
        "cost threshold for parallelism": ("int", (0, 32767)), "remote access": ("enum", _ONOFF),
    },
}


def engine_of(database_version: str) -> str:
    v = str(database_version or "POSTGRES").upper()
    return "MYSQL" if v.startswith("MYSQL") else "SQLSERVER" if v.startswith("SQLSERVER") else "POSTGRES"


def validate_flags(database_version: str, flags) -> list:
    eng = engine_of(database_version)
    known = FLAGS[eng]
    if not isinstance(flags, list):
        raise SqlSettingsError(400, "INVALID_ARGUMENT", "settings.databaseFlags must be a list of {name, value}.")
    bad = [str(f.get("name")) for f in flags if isinstance(f, dict) and f.get("name") not in known]
    if bad:
        raise SqlSettingsError(400, "INVALID_ARGUMENT",
                               "Invalid request: invalid flag name(s) for %s: %s." % (database_version, ", ".join(bad)))
    out, seen = [], set()
    for f in flags:
        if not isinstance(f, dict):
            continue
        n, v = f["name"], str(f.get("value", "")).strip()
        if n in seen:
            raise SqlSettingsError(400, "INVALID_ARGUMENT", "Invalid request: flag %s is set more than once." % n)
        seen.add(n)
        kind, allowed = known[n]
        ok = True
        if kind in ("int", "float"):
            try:
                num = int(v) if kind == "int" else float(v)
                ok = allowed[0] <= num <= allowed[1]
            except ValueError:
                ok = False
            hint = "%s..%s" % allowed
        elif kind == "enum":
            ok = v in allowed
            hint = "|".join(allowed)
        else:
            ok, hint = bool(v), "a non-empty value"
        if not ok:
            raise SqlSettingsError(400, "INVALID_ARGUMENT",
                                   "Invalid request: invalid value '%s' for flag %s (allowed: %s)." % (v, n, hint))
        out.append({"name": n, "value": v})
    return out


def _cidr(v: str) -> str:
    import ipaddress
    try:
        net = ipaddress.ip_network(str(v).strip(), strict=False)
    except ValueError:
        raise SqlSettingsError(400, "INVALID_ARGUMENT", "Invalid request: '%s' is not a valid CIDR range." % v)
    rfc1918 = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16")]
    if net.version == 4 and any(net.subnet_of(p) for p in rfc1918):
        raise SqlSettingsError(400, "INVALID_ARGUMENT", "Invalid request: Non-routable or private authorized network (%s)." % v)
    return str(net)


def validate_ip_config(cur: dict, patch: dict) -> dict:
    out = dict(cur or {})
    for k in ("ipv4Enabled", "requireSsl"):
        if k in patch:
            out[k] = bool(patch[k])
    if "sslMode" in patch:
        mode = str(patch["sslMode"] or "ALLOW_UNENCRYPTED_AND_ENCRYPTED")
        if mode not in ("ALLOW_UNENCRYPTED_AND_ENCRYPTED", "ENCRYPTED_ONLY", "TRUSTED_CLIENT_CERTIFICATE_REQUIRED"):
            raise SqlSettingsError(400, "INVALID_ARGUMENT", "Invalid request: unknown sslMode %s." % mode)
        out["sslMode"] = mode
        out["requireSsl"] = mode != "ALLOW_UNENCRYPTED_AND_ENCRYPTED"
    if "privateNetwork" in patch:
        out["privateNetwork"] = str(patch["privateNetwork"] or "")
    if "authorizedNetworks" in patch:
        nets, seen = [], set()
        for n in patch["authorizedNetworks"] or []:
            val = _cidr((n or {}).get("value", ""))
            if val in seen:
                raise SqlSettingsError(400, "INVALID_ARGUMENT", "Invalid request: duplicate authorized network %s." % val)
            seen.add(val)
            nets.append({"kind": "sql#aclEntry", "name": str((n or {}).get("name") or ""), "value": val})
        out["authorizedNetworks"] = nets
    if not out.get("ipv4Enabled") and not out.get("privateNetwork"):
        raise SqlSettingsError(400, "INVALID_ARGUMENT",
                               "Invalid request: At least one of Public IP or Private IP connectivity must be enabled.")
    return out


def validate_backup_config(cur: dict, patch: dict) -> dict:
    import re as _re
    out = dict(cur or {})
    for k in ("enabled", "pointInTimeRecoveryEnabled", "binaryLogEnabled"):
        if k in patch:
            out[k] = bool(patch[k])
    if "startTime" in patch:
        st = str(patch["startTime"] or "")
        if not _re.match(r"^([01]\d|2[0-3]):00$", st):
            raise SqlSettingsError(400, "INVALID_ARGUMENT", "Invalid request: backup start time must be on the hour, HH:00 (UTC).")
        out["startTime"] = st
    if "retainedBackups" in patch:
        n = int(patch["retainedBackups"])
        if not 1 <= n <= 365:
            raise SqlSettingsError(400, "INVALID_ARGUMENT", "Invalid request: retained backups must be between 1 and 365.")
        out["backupRetentionSettings"] = {"retentionUnit": "COUNT", "retainedBackups": n}
    if "transactionLogRetentionDays" in patch:
        n = int(patch["transactionLogRetentionDays"])
        if not 1 <= n <= 7:
            raise SqlSettingsError(400, "INVALID_ARGUMENT", "Invalid request: transaction log retention must be 1-7 days.")
        out["transactionLogRetentionDays"] = n
    if out.get("pointInTimeRecoveryEnabled") and not out.get("enabled"):
        raise SqlSettingsError(400, "INVALID_ARGUMENT",
                               "Invalid request: Point-in-time recovery requires automated backups to be enabled.")
    out.setdefault("kind", "sql#backupConfiguration")
    return out


def validate_insights(cur: dict, patch: dict) -> dict:
    out = dict(cur or {})
    for k in ("queryInsightsEnabled", "recordApplicationTags", "recordClientAddress"):
        if k in patch:
            out[k] = bool(patch[k])
    if "queryStringLength" in patch:
        n = int(patch["queryStringLength"])
        if not 256 <= n <= 4500:
            raise SqlSettingsError(400, "INVALID_ARGUMENT", "Invalid request: queryStringLength must be between 256 and 4500.")
        out["queryStringLength"] = n
    if "queryPlansPerMinute" in patch:
        n = int(patch["queryPlansPerMinute"])
        if not 0 <= n <= 20:
            raise SqlSettingsError(400, "INVALID_ARGUMENT", "Invalid request: queryPlansPerMinute must be between 0 and 20.")
        out["queryPlansPerMinute"] = n
    return out


def patch_settings(database_version: str, cur: dict, patch: dict) -> dict:
    """instances.patch on `settings`: validated merge (unknown keys pass through)."""
    out = dict(cur or {})
    for k, v in (patch or {}).items():
        if k == "databaseFlags":
            out[k] = validate_flags(database_version, v)
        elif k == "ipConfiguration":
            out[k] = validate_ip_config(out.get(k) or {"ipv4Enabled": True}, v or {})
        elif k == "backupConfiguration":
            out[k] = validate_backup_config(out.get(k) or {}, v or {})
        elif k == "insightsConfig":
            out[k] = validate_insights(out.get(k) or {}, v or {})
        elif k == "userLabels":
            out[k] = {str(a): str(b) for a, b in (v or {}).items()}
        else:
            out[k] = v
    out["settingsVersion"] = str(int(out.get("settingsVersion") or 1) + 1)
    return out


def validate_user(database_version: str, body: dict, existing: list) -> dict:
    eng = engine_of(database_version)
    name = str(body.get("name") or "").strip()
    utype = str(body.get("type") or "BUILT_IN")
    if utype not in ("BUILT_IN", "CLOUD_IAM_USER", "CLOUD_IAM_SERVICE_ACCOUNT", "CLOUD_IAM_GROUP"):
        raise SqlSettingsError(400, "INVALID_ARGUMENT", "Invalid request: unknown user type %s." % utype)
    limit = 32 if eng == "MYSQL" else 63 if eng == "POSTGRES" else 128
    if not name or (utype == "BUILT_IN" and len(name) > limit):
        raise SqlSettingsError(400, "INVALID_ARGUMENT",
                               "Invalid request: user name must be 1-%d characters for %s." % (limit, database_version))
    host = str(body.get("host") or ("%" if eng == "MYSQL" else "")) if eng == "MYSQL" else ""
    if any(u.get("name") == name and (u.get("host") or "") == host for u in existing):
        raise SqlSettingsError(409, "ALREADY_EXISTS", "Invalid request: user %s%s already exists." % (name, ("@" + host) if host else ""))
    if utype == "BUILT_IN" and not str(body.get("password") or ""):
        raise SqlSettingsError(400, "INVALID_ARGUMENT", "Invalid request: a password is required for a built-in user.")
    return {"kind": "sql#user", "name": name, "host": host, "type": utype}


# ── users / backup runs / operations (Nano's control-plane records) ─────────
def _op(rec: dict, op_type: str, target: str | None = None) -> dict:
    op = {"kind": "sql#operation", "name": str(uuid.uuid4()), "operationType": op_type, "status": "DONE",
          "targetId": target or rec["name"], "targetProject": rec["project"], "insertTime": _now_iso(),
          "startTime": _now_iso(), "endTime": _now_iso(), "user": "%s@%s.iam" % ("console", rec["project"])}
    rec.setdefault("operations", []).insert(0, op)
    del rec["operations"][200:]
    return op


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _patch_instance(store: SqlStore, project: str, instance: str, body: dict) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    try:
        if isinstance(body.get("settings"), dict):
            rec["settings"] = patch_settings(rec.get("databaseVersion", ""), rec.get("settings") or {}, body["settings"])
    except SqlSettingsError as e:
        return _err(e.status, e.code, e.message)
    rec["etag"] = _etag()
    store.put_instance(_key(project, instance), rec)
    store.persist()
    return _json(200, _op(rec, "UPDATE"))


def _promote_replica(store: SqlStore, project: str, instance: str) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    if not rec.get("masterInstanceName"):
        return _err(400, "INVALID_ARGUMENT", "Invalid request: the instance is not a read replica.")
    master = _get_instance(store, project, rec.pop("masterInstanceName"))
    if master:
        master["replicaNames"] = [n for n in master.get("replicaNames") or [] if n != instance]
        _op(master, "PROMOTE_REPLICA", instance)
        store.put_instance(_key(project, master["name"]), master)
    rec["instanceType"] = "CLOUD_SQL_INSTANCE"
    store.put_instance(_key(project, instance), rec)
    store.persist()
    return _json(200, _op(rec, "PROMOTE_REPLICA"))


def _users(store, project, instance, method, payload, query) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    users = rec.setdefault("users", [])
    if method == "GET":
        items = [dict(u, instance=instance, project=project) for u in users]
        return _json(200, {"kind": "sql#usersList", **({"items": items} if items else {})})
    if method == "POST":
        try:
            u = validate_user(rec.get("databaseVersion", ""), payload, users)
        except SqlSettingsError as e:
            return _err(e.status, e.code, e.message)
        users.append(u)
        store.persist()
        return _json(200, _op(rec, "CREATE_USER"))
    if method == "PUT":
        name, host = str(query.get("name") or payload.get("name") or ""), str(query.get("host") or payload.get("host") or "")
        if not any(u["name"] == name and (u.get("host") or "") == host for u in users):
            return _not_found(f"The user does not exist. User: {name}")
        store.persist()
        return _json(200, _op(rec, "UPDATE_USER"))
    if method == "DELETE":
        name, host = str(query.get("name") or ""), str(query.get("host") or "")
        keep = [u for u in users if not (u["name"] == name and (u.get("host") or "") == host)]
        if len(keep) == len(users):
            return _not_found(f"The user does not exist. User: {name}")
        rec["users"] = keep
        store.persist()
        return _json(200, _op(rec, "DELETE_USER"))
    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on users")


def _backup_runs(store, project, instance, method, payload, run_id) -> CloudSqlResponse:
    rec = _get_instance(store, project, instance)
    if not rec:
        return _not_found(f"The Cloud SQL instance does not exist. Instance: {instance}")
    runs = rec.setdefault("backupRuns", [])
    if run_id is None and method == "GET":
        return _json(200, {"kind": "sql#backupRunsList", **({"items": list(runs)} if runs else {})})
    if run_id is None and method == "POST":
        now = _now_iso()
        run = {"kind": "sql#backupRun", "id": str(int(uuid.uuid4().int % 10**13)), "instance": instance,
               "status": "SUCCESSFUL", "type": "ON_DEMAND", "description": str(payload.get("description") or ""),
               "enqueuedTime": now, "startTime": now, "endTime": now, "windowStartTime": now,
               "location": payload.get("location") or "us", "backupKind": "SNAPSHOT"}
        runs.insert(0, run)
        store.persist()
        return _json(200, _op(rec, "BACKUP_VOLUME"))
    if run_id is not None:
        run = next((r for r in runs if r["id"] == run_id), None)
        if run is None:
            return _not_found(f"The backup run does not exist. Backup run: {run_id}")
        if method == "GET":
            return _json(200, run)
        if method == "DELETE":
            runs.remove(run)
            store.persist()
            return _json(200, _op(rec, "DELETE_BACKUP"))
    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on backupRuns")


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

    query = query or {}
    # operations.list: /projects/{p}/operations?instance=I — the instance's operation log
    if len(segs) == 3 and segs[0] == "projects" and segs[2] == "operations" and method == "GET":
        rec = _get_instance(store, segs[1], str(query.get("instance") or ""))
        if not rec:
            return _not_found(f"The Cloud SQL instance does not exist. Instance: {query.get('instance')}")
        ops = list(rec.get("operations") or [])
        return _json(200, {"kind": "sql#operationsList", **({"items": ops} if ops else {})})

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

    # verbs on an instance: promoteReplica, users, backupRuns, PATCH
    if len(segs) == 4 and method in ("PATCH", "PUT"):
        return _patch_instance(store, project, segs[3], payload)
    if len(segs) == 5 and segs[4] == "promoteReplica" and method == "POST":
        return _promote_replica(store, project, segs[3])
    if len(segs) == 5 and segs[4] == "users":
        return _users(store, project, segs[3], method, payload, query)
    if len(segs) in (5, 6) and segs[4] == "backupRuns":
        return _backup_runs(store, project, segs[3], method, payload, segs[5] if len(segs) == 6 else None)

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
