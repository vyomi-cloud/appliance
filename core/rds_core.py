"""RDS core — substrate-independent, extracted from the appliance RDS handler
(server.py `_rds_*` / `api_rds_query`) so the SAME logic runs in Pro/Max
(FastAPI), Nano (Pyodide), and tests. NO fastapi / boto3 / socket / psycopg2 /
subprocess imports → loads under Pyodide. Persists + runs SQL through the SqlStore
seam (core/sql_store.py).

RDS speaks the AWS **Query protocol**: form-encoded POST with `Action=...&...` and
**XML** responses (not JSON/X-Amz-Target). The control plane returns an
`RdsResponse` (status, XML body, headers) in the native shapes
(<CreateDBInstanceResult><DBInstance>...</DBInstance></...>, <ErrorResponse>).

The DATA plane is special: AWS has no "run SQL" API — clients connect to the
endpoint over the Postgres/MySQL wire. In Nano that wire isn't reachable in-tab,
so `execute_sql()` exposes the instance's REAL SQL engine (sqlite3 via SqlStore)
to in-browser callers / the console query tool / the relay. The engine is real
(it actually parses + runs SQL); a PGlite/Postgres-wire engine swaps in behind
the seam for unmodified-psycopg2 conformance later.

Scope (v1 slice): CreateDBInstance, DescribeDBInstances, ModifyDBInstance,
DeleteDBInstance, StartDBInstance, StopDBInstance, RebootDBInstance,
CreateDBSnapshot, DescribeDBSnapshots + the execute_sql data-plane. Subnet/
parameter groups, read replicas, and Multi-AZ reuse the same helpers and slot in
next.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

from core.sql_store import SqlStore

RDS_NS = "http://rds.amazonaws.com/doc/2014-10-31/"
_ENGINE_PORT = {"postgres": 5432, "postgresql": 5432, "aurora-postgresql": 5432,
                "mysql": 3306, "mariadb": 3306, "aurora-mysql": 3306}


@dataclass
class RdsResponse:
    status: int = 200
    body: str = ""          # XML text
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class RdsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


# ── primitives ─────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _req_id() -> str:
    return str(uuid.uuid4())


def _instance_arn(store: SqlStore, db_id: str) -> str:
    return f"arn:aws:rds:us-east-1:{store.account_id}:db:{db_id}"


def _engine_port(engine: str) -> int:
    return _ENGINE_PORT.get(engine.lower(), 5432)


# ── response builders (native RDS Query-protocol XML) ──────────────────────
def _success(action: str, result_inner: str, status: int = 200) -> RdsResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<{action}Response xmlns="{RDS_NS}">'
           f'<{action}Result>{result_inner}</{action}Result>'
           f'<ResponseMetadata><RequestId>{_req_id()}</RequestId></ResponseMetadata>'
           f'</{action}Response>')
    return RdsResponse(status=status, body=xml)


def _error(code: str, message: str, status: int = 400) -> RdsResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<ErrorResponse xmlns="{RDS_NS}">'
           f'<Error><Type>Sender</Type><Code>{_xml_escape(code)}</Code>'
           f'<Message>{_xml_escape(message)}</Message></Error>'
           f'<RequestId>{_req_id()}</RequestId></ErrorResponse>')
    return RdsResponse(status=status, body=xml)


def _el(tag: str, value) -> str:
    return f"<{tag}>{_xml_escape(str(value))}</{tag}>"


def _db_instance_xml(db: dict) -> str:
    parts = [
        "<DBInstance>",
        _el("DBInstanceIdentifier", db["db_instance_identifier"]),
        _el("DBInstanceClass", db.get("db_instance_class", "db.t3.micro")),
        _el("Engine", db.get("engine", "postgres")),
        _el("EngineVersion", db.get("engine_version", "16.4")),
        _el("DBInstanceStatus", db.get("db_instance_status", "available")),
        _el("MasterUsername", db.get("master_username", "admin")),
        _el("AllocatedStorage", db.get("allocated_storage", 20)),
        _el("StorageType", db.get("storage_type", "gp3")),
        _el("AvailabilityZone", db.get("availability_zone", "us-east-1a")),
        _el("MultiAZ", str(db.get("multi_az", False)).lower()),
        _el("PubliclyAccessible", str(db.get("publicly_accessible", False)).lower()),
        _el("DBInstanceArn", db.get("db_instance_arn", "")),
        _el("InstanceCreateTime", db.get("created", "")),
        "<Endpoint>",
        _el("Address", db.get("endpoint_address", "")),
        _el("Port", db.get("endpoint_port", 5432)),
        _el("HostedZoneId", "Z1PVIF0B656C1W"),
        "</Endpoint>",
        "</DBInstance>",
    ]
    return "".join(parts)


def _db_snapshot_xml(snap: dict) -> str:
    return "".join([
        "<DBSnapshot>",
        _el("DBSnapshotIdentifier", snap["db_snapshot_identifier"]),
        _el("DBInstanceIdentifier", snap.get("db_instance_identifier", "")),
        _el("Status", snap.get("status", "available")),
        _el("Engine", snap.get("engine", "postgres")),
        _el("EngineVersion", snap.get("engine_version", "16.4")),
        _el("AllocatedStorage", snap.get("allocated_storage", 20)),
        _el("SnapshotCreateTime", snap.get("created", "")),
        _el("SnapshotType", snap.get("snapshot_type", "manual")),
        "</DBSnapshot>",
    ])


# ── helpers ────────────────────────────────────────────────────────────────
def _require_instance(store: SqlStore, db_id: str) -> dict:
    db = store.get_instance(db_id)
    if not db:
        raise RdsError("DBInstanceNotFound", f"DBInstance {db_id} not found.", 404)
    return db


def _int(params: dict, key: str, default: int) -> int:
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError):
        return default


# ── control-plane operations ────────────────────────────────────────────────
def _create_db_instance(store: SqlStore, params: dict) -> RdsResponse:
    db_id = str(params.get("DBInstanceIdentifier", "")).strip()
    if not db_id:
        raise RdsError("InvalidParameterValue", "DBInstanceIdentifier is required.", 400)
    if store.instance_exists(db_id):
        raise RdsError("DBInstanceAlreadyExists", f"DBInstance {db_id} already exists.", 400)
    engine = str(params.get("Engine", "postgres")).lower()
    record = {
        "db_instance_identifier": db_id,
        "db_instance_class": str(params.get("DBInstanceClass", "db.t3.micro")),
        "engine": engine,
        "engine_version": str(params.get("EngineVersion", "16.4")),
        "db_instance_status": "available",  # Nano: no provisioning lag, ready at once
        "master_username": str(params.get("MasterUsername", "admin")),
        "master_user_password": str(params.get("MasterUserPassword", "")),
        "allocated_storage": _int(params, "AllocatedStorage", 20),
        "storage_type": str(params.get("StorageType", "gp3")),
        "availability_zone": str(params.get("AvailabilityZone", "us-east-1a")),
        "multi_az": str(params.get("MultiAZ", "false")).lower() == "true",
        "publicly_accessible": str(params.get("PubliclyAccessible", "false")).lower() == "true",
        "backup_retention_period": _int(params, "BackupRetentionPeriod", 7),
        "endpoint_address": f"{db_id}.nano-rds.local",
        "endpoint_port": _int(params, "Port", _engine_port(engine)),
        "db_instance_arn": _instance_arn(store, db_id),
        "created": _now(),
        "updated": _now(),
        "runtime_backend": "sqlite",  # Nano data-plane engine
    }
    store.put_instance(db_id, record)
    # The SQL engine opens LAZILY on first execute_sql — so the control plane
    # needs no sqlite3 (a loadable Pyodide package), only the data plane does.
    store.mirror_create_instance(db_id, record)
    store.persist()
    return _success("CreateDBInstance", _db_instance_xml(record))


def _describe_db_instances(store: SqlStore, params: dict) -> RdsResponse:
    db_id = str(params.get("DBInstanceIdentifier", "")).strip()
    if db_id:
        ids = [db_id] if store.instance_exists(db_id) else []
        if not ids:
            raise RdsError("DBInstanceNotFound", f"DBInstance {db_id} not found.", 404)
    else:
        ids = store.instance_ids()
    inner = "<DBInstances>" + "".join(_db_instance_xml(store.get_instance(i)) for i in ids) + "</DBInstances>"
    return _success("DescribeDBInstances", inner)


def _modify_db_instance(store: SqlStore, params: dict) -> RdsResponse:
    db = _require_instance(store, str(params.get("DBInstanceIdentifier", "")).strip())
    for param, field_name, caster in (
        ("DBInstanceClass", "db_instance_class", str),
        ("AllocatedStorage", "allocated_storage", int),
        ("EngineVersion", "engine_version", str),
        ("BackupRetentionPeriod", "backup_retention_period", int),
        ("MasterUserPassword", "master_user_password", str),
    ):
        if params.get(param) is not None:
            try:
                db[field_name] = caster(params[param])
            except (TypeError, ValueError):
                pass
    db["updated"] = _now()
    store.persist()
    return _success("ModifyDBInstance", _db_instance_xml(db))


def _set_status(store: SqlStore, params: dict, action: str, status: str) -> RdsResponse:
    db = _require_instance(store, str(params.get("DBInstanceIdentifier", "")).strip())
    db["db_instance_status"] = status
    db["updated"] = _now()
    store.persist()
    return _success(action, _db_instance_xml(db))


def _delete_db_instance(store: SqlStore, params: dict) -> RdsResponse:
    db_id = str(params.get("DBInstanceIdentifier", "")).strip()
    db = _require_instance(store, db_id)
    if str(params.get("SkipFinalSnapshot", "true")).lower() != "true":
        snap_id = str(params.get("FinalDBSnapshotIdentifier", f"{db_id}-final"))
        _make_snapshot(store, db, snap_id, snapshot_type="automated")
    db = dict(db)
    db["db_instance_status"] = "deleting"
    store.drop_instance(db_id)
    store.mirror_delete_instance(db_id)
    store.persist()
    return _success("DeleteDBInstance", _db_instance_xml(db))


def _make_snapshot(store: SqlStore, db: dict, snap_id: str, snapshot_type: str = "manual") -> dict:
    snap = {
        "db_snapshot_identifier": snap_id,
        "db_instance_identifier": db["db_instance_identifier"],
        "status": "available",
        "engine": db.get("engine", "postgres"),
        "engine_version": db.get("engine_version", "16.4"),
        "allocated_storage": db.get("allocated_storage", 20),
        "snapshot_type": snapshot_type,
        "created": _now(),
    }
    store.put_snapshot(snap_id, snap)
    return snap


def _create_db_snapshot(store: SqlStore, params: dict) -> RdsResponse:
    db = _require_instance(store, str(params.get("DBInstanceIdentifier", "")).strip())
    snap_id = str(params.get("DBSnapshotIdentifier", "")).strip()
    if not snap_id:
        raise RdsError("InvalidParameterValue", "DBSnapshotIdentifier is required.", 400)
    snap = _make_snapshot(store, db, snap_id, snapshot_type="manual")
    store.persist()
    return _success("CreateDBSnapshot", _db_snapshot_xml(snap))


def _describe_db_snapshots(store: SqlStore, params: dict) -> RdsResponse:
    db_id = str(params.get("DBInstanceIdentifier", "")).strip()
    snaps = [store.get_snapshot(s) for s in store.snapshot_ids()]
    if db_id:
        snaps = [s for s in snaps if s.get("db_instance_identifier") == db_id]
    inner = "<DBSnapshots>" + "".join(_db_snapshot_xml(s) for s in snaps) + "</DBSnapshots>"
    return _success("DescribeDBSnapshots", inner)


# ── native-wire dispatcher (Query-protocol Action → operation) ─────────────
# The single routing point for the native AWS RDS Query protocol — what an
# unmodified aws-cli / boto3 RDS client speaks. `params` is the parsed
# form-encoded body ({"Action": "CreateDBInstance", "DBInstanceIdentifier": ...}).
def dispatch(store: SqlStore, params: dict | None = None) -> RdsResponse:
    params = params if isinstance(params, dict) else {}
    action = str(params.get("Action", "")).strip()
    if not action:
        return _error("MissingAction", "The request must include an Action.", 400)
    try:
        if action == "CreateDBInstance":
            return _create_db_instance(store, params)
        if action == "DescribeDBInstances":
            return _describe_db_instances(store, params)
        if action == "ModifyDBInstance":
            return _modify_db_instance(store, params)
        if action == "DeleteDBInstance":
            return _delete_db_instance(store, params)
        if action == "StartDBInstance":
            return _set_status(store, params, "StartDBInstance", "available")
        if action == "StopDBInstance":
            return _set_status(store, params, "StopDBInstance", "stopped")
        if action == "RebootDBInstance":
            return _set_status(store, params, "RebootDBInstance", "available")
        if action == "CreateDBSnapshot":
            return _create_db_snapshot(store, params)
        if action == "DescribeDBSnapshots":
            return _describe_db_snapshots(store, params)
        return _error("InvalidAction", f"The action {action} is not implemented.", 400)
    except RdsError as e:
        return _error(e.code, e.message, e.status)


# ── data plane (NOT a native RDS action — the in-tab SQL bridge) ───────────
def _dataplane_precheck(store: SqlStore, db_instance_identifier: str) -> dict | None:
    """Shared gate for the sync + async data-plane entries (no divergence)."""
    db = store.get_instance(db_instance_identifier)
    if not db:
        return {"ok": False, "code": "DBInstanceNotFound",
                "message": f"DBInstance {db_instance_identifier} not found."}
    if db.get("db_instance_status") != "available":
        return {"ok": False, "code": "InvalidDBInstanceState",
                "message": f"DBInstance is {db.get('db_instance_status')}."}
    return None


def execute_sql(store: SqlStore, db_instance_identifier: str, sql: str,
                params: list | None = None) -> dict:
    """Run real SQL against an instance's engine (sqlite3 in Nano). Used by the
    console query tool / in-browser apps / the relay — the analogue of connecting
    over the Postgres wire. Returns {ok, columns, rows, rowcount} or {ok:False}."""
    err = _dataplane_precheck(store, db_instance_identifier)
    if err:
        return err
    try:
        result = store.execute_sql(db_instance_identifier, sql, params)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "code": "SQLError", "message": str(e)}


async def aexecute_sql(store: SqlStore, db_instance_identifier: str, sql: str,
                       params: list | None = None) -> dict:
    """Async twin of execute_sql — SAME {ok, columns, rows, rowcount} contract, but
    awaits the engine so an ASYNC data-plane (PGlite over the real Postgres wire)
    can back RDS in the browser. Sync engines work unchanged (the base store's
    aexecute_sql delegates to execute_sql)."""
    err = _dataplane_precheck(store, db_instance_identifier)
    if err:
        return err
    try:
        result = await store.aexecute_sql(db_instance_identifier, sql, params)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "code": "SQLError", "message": str(e)}
