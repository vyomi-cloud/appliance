# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure SQL data-plane core — the Azure peer of AWS RDS + GCP Cloud SQL, closing
the cross-cloud relational-symmetry gap (PARITY P3 #13). Azure SQL had only an ARM
control-plane catalog and no data plane; this gives it a real one on the SAME
`SqlStore` seam the RDS/Cloud SQL cores use (stdlib sqlite3 in Nano; real Postgres
behind the seam in Pro/Max) — so `CREATE TABLE` / `INSERT` / `SELECT` actually run.

Azure SQL's native SDK speaks TDS (which can't traverse the HTTP relay), so this
core exposes the relational surface over a small REST/JSON wire — logical server +
database management and a `.../query` execute endpoint returning
`{columns, rows, rowCount}`. NO fastapi / pyodbc / socket imports → loads under
Pyodide. Databases live in the SqlStore keyed `azuresql:{server}/{database}`.

Scope (v1 slice): create/list/delete server + database, execute SQL (sync + async).
Elastic pools, geo-replication and the TDS wire slot in later.

DEPTH PASS (v2.7.0): the ARM control plane's `publicNetworkAccess` (server) and
`maxSizeBytes` (database) properties now actually constrain this data plane — the
same pattern `azure_blob_core.py` uses for CORS/lifecycle (`aws_wire_router.py`
passes the ARM core's `state` dict as `arm_state=`, read-only, never written back).
A real "Performance recommendations" engine also lives here: it watches the Query
editor's own statement log, detects WHERE-equality lookups that need a table scan
(via the SAME engine's `EXPLAIN QUERY PLAN`, not a guess) and proposes/creates
indexes — applied on request, or automatically when the database's
`automaticTuning.options.createIndex` is "On" (mirroring the real feature's name).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from core.sql_store import SqlStore


@dataclass
class AzureSqlResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


def _json(status: int, obj: dict) -> AzureSqlResponse:
    return AzureSqlResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, code: str, message: str) -> AzureSqlResponse:
    return AzureSqlResponse(status=status, body=json.dumps({"error": {"code": code, "message": message}}).encode())


def _servers(store: SqlStore) -> dict:
    m = getattr(store, "_azure_sql_servers", None)
    if m is None:
        m = {}
        store._azure_sql_servers = m
    return m


def _db_id(server: str, database: str) -> str:
    return f"azuresql:{server}/{database}"


# ── ARM config lookup (publicNetworkAccess / maxSizeBytes / automaticTuning) ───────────
# Same read-only-snapshot pattern as azure_blob_core._arm_properties: the ARM core's
# `state` dict is keyed by lower-cased resource id with a `_type` discriminator, so a
# type + id-suffix match finds the server/database record without needing the
# subscription/resource-group this data plane never learns.
def _arm_record(arm_state: dict | None, full_type: str, id_suffix: str) -> dict | None:
    if not arm_state:
        return None
    want_id = f"/{id_suffix}".lower()
    for rec in arm_state.values():
        if rec.get("_type", "").lower() == full_type and rec.get("id", "").lower().endswith(want_id):
            return rec
    return None


def _server_props(arm_state: dict | None, server: str) -> dict:
    rec = _arm_record(arm_state, "microsoft.sql/servers", f"servers/{server}")
    return (rec or {}).get("properties", {}) or {}


def _database_props(arm_state: dict | None, server: str, database: str) -> dict:
    rec = _arm_record(arm_state, "microsoft.sql/servers/databases", f"servers/{server}/databases/{database}")
    return (rec or {}).get("properties", {}) or {}


# ── control plane ───────────────────────────────────────────────────────────
def _create_server(store: SqlStore, server: str) -> AzureSqlResponse:
    _servers(store).setdefault(server, {"name": server, "databases": []})
    return _json(201, {"name": server, "type": "Microsoft.Sql/servers",
                       "properties": {"state": "Ready"}})


def _create_database(store: SqlStore, server: str, database: str) -> AzureSqlResponse:
    srv = _servers(store).setdefault(server, {"name": server, "databases": []})
    db_id = _db_id(server, database)
    if not store.instance_exists(db_id):
        store.put_instance(db_id, {
            "db_instance_identifier": db_id, "engine": "sqlserver",
            "db_instance_status": "available", "server": server, "database": database})
        if database not in srv["databases"]:
            srv["databases"].append(database)
    return _json(201, {"name": database, "type": "Microsoft.Sql/servers/databases",
                       "properties": {"status": "Online"}})


def _list_databases(store: SqlStore, server: str) -> AzureSqlResponse:
    srv = _servers(store).get(server)
    if srv is None:
        return _err(404, "ResourceNotFound", f"Server '{server}' was not found.")
    return _json(200, {"value": [{"name": d, "properties": {"status": "Online"}}
                                 for d in srv["databases"]]})


def _delete_database(store: SqlStore, server: str, database: str) -> AzureSqlResponse:
    db_id = _db_id(server, database)
    if not store.instance_exists(db_id):
        return _err(404, "ResourceNotFound", f"Database '{database}' was not found.")
    store.db_instances.pop(db_id, None)
    srv = _servers(store).get(server)
    if srv and database in srv["databases"]:
        srv["databases"].remove(database)
    return _json(200, {})


# ── data plane ──────────────────────────────────────────────────────────────
def execute_sql(store: SqlStore, server: str, database: str, sql: str,
                params: list | None = None) -> dict:
    """Run real SQL against the database's engine (sqlite3 in Nano; Postgres behind
    the seam in Pro/Max). Returns {ok, columns, rows, rowCount} or {ok: False}."""
    db_id = _db_id(server, database)
    if not store.instance_exists(db_id):
        return {"ok": False, "code": "DatabaseNotFound",
                "message": f"Database {server}/{database} not found."}
    try:
        result = store.execute_sql(db_id, sql, params)
        return {"ok": True, "columns": result.get("columns", []),
                "rows": result.get("rows", []), "rowCount": result.get("rowcount", 0)}
    except Exception as e:
        return {"ok": False, "code": "SQLError", "message": str(e)}


async def aexecute_sql(store: SqlStore, server: str, database: str, sql: str,
                       params: list | None = None) -> dict:
    """Async twin — awaits the engine so an async data-plane (PGlite/Postgres) can
    back Azure SQL in the browser; sync engines work unchanged."""
    db_id = _db_id(server, database)
    if not store.instance_exists(db_id):
        return {"ok": False, "code": "DatabaseNotFound",
                "message": f"Database {server}/{database} not found."}
    try:
        result = await store.aexecute_sql(db_id, sql, params)
        return {"ok": True, "columns": result.get("columns", []),
                "rows": result.get("rows", []), "rowCount": result.get("rowcount", 0)}
    except Exception as e:
        return {"ok": False, "code": "SQLError", "message": str(e)}


_WRITE_SQL_RE = re.compile(r"^\s*(insert|update|replace)\b", re.IGNORECASE)


def _db_size_bytes(store: SqlStore, db_id: str) -> int:
    """The database's current on-disk size, from the engine's OWN page accounting
    (sqlite `PRAGMA page_count` * `page_size`) — not an estimate."""
    try:
        pages = store.execute_sql(db_id, "PRAGMA page_count")["rows"][0][0]
        size = store.execute_sql(db_id, "PRAGMA page_size")["rows"][0][0]
        return int(pages) * int(size)
    except Exception:
        return 0


def _query(store: SqlStore, server: str, database: str, body: bytes,
          arm_state: dict | None = None) -> AzureSqlResponse:
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    sql = str(payload.get("sql") or payload.get("query") or "")
    if not sql:
        return _err(400, "BadRequest", "A 'sql' statement is required.")

    if _server_props(arm_state, server).get("publicNetworkAccess") == "Disabled":
        return _err(403, "PublicNetworkAccessDisabled",
                    f"Cannot connect to server '{server}.database.windows.net': "
                    "public network access is disabled.")

    db_id = _db_id(server, database)
    if _WRITE_SQL_RE.match(sql) and store.instance_exists(db_id):
        max_size = _database_props(arm_state, server, database).get("maxSizeBytes")
        if max_size and _db_size_bytes(store, db_id) >= int(max_size):
            return _err(400, "DatabaseSizeQuotaExceeded",
                        f"The database '{database}' has reached its configured maximum "
                        f"size of {int(max_size)} bytes (Error 40544). Partition or delete "
                        "data, drop indexes, or increase the maximum size.")

    result = execute_sql(store, server, database, sql, payload.get("params"))
    if not result.get("ok"):
        return _err(400, result.get("code", "SQLError"), result.get("message", ""))

    _log_select(store, db_id, sql)
    _auto_tune(store, arm_state, server, database)
    return _json(200, {"columns": result["columns"], "rows": result["rows"],
                       "rowCount": result["rowCount"]})


# ── Performance recommendations (CREATE_INDEX, real EXPLAIN-QUERY-PLAN driven) ─────────
# A rolling log of SELECTs the Query editor has actually run, kept on the store (same
# home as the server/database catalog) so recommendations survive across requests.
_EQ_WHERE_RE = re.compile(r"\bfrom\s+([A-Za-z_]\w*)\b.*?\bwhere\b.*?\b([A-Za-z_]\w*)\s*=",
                          re.IGNORECASE | re.DOTALL)


def _query_log(store: SqlStore, db_id: str) -> list:
    m = getattr(store, "_azure_sql_query_log", None)
    if m is None:
        m = {}
        store._azure_sql_query_log = m
    return m.setdefault(db_id, [])


def _applied_recs(store: SqlStore, db_id: str) -> set:
    m = getattr(store, "_azure_sql_applied_recs", None)
    if m is None:
        m = {}
        store._azure_sql_applied_recs = m
    return m.setdefault(db_id, set())


def _log_select(store: SqlStore, db_id: str, sql: str) -> None:
    if not sql.strip().lower().startswith("select"):
        return
    log = _query_log(store, db_id)
    log.append(sql)
    del log[:-200]   # cap the log — only recent activity drives a recommendation


def _needs_table_scan(store: SqlStore, db_id: str, table: str, column: str) -> bool:
    """Ask the engine's REAL query planner whether `WHERE {column} = ?` on {table}
    currently needs a full scan — the same signal Azure's Query Store/DTA use, just
    read straight off sqlite's EXPLAIN QUERY PLAN instead of reimplementing it."""
    try:
        plan = store.execute_sql(db_id, f"EXPLAIN QUERY PLAN SELECT * FROM {table} WHERE {column} = ?", [None])
    except Exception:
        return False
    for row in plan.get("rows", []):
        detail = str(row[-1] if row else "").upper()
        if detail.startswith("SCAN") and "USING INDEX" not in detail:
            return True
    return False


def _candidate_recommendations(store: SqlStore, db_id: str) -> list[dict]:
    counts: dict[tuple, int] = {}
    for sql in _query_log(store, db_id):
        m = _EQ_WHERE_RE.search(sql)
        if not m:
            continue
        key = (m.group(1), m.group(2))
        counts[key] = counts.get(key, 0) + 1
    applied = _applied_recs(store, db_id)
    recs = []
    for (table, column), count in counts.items():
        if count < 3:
            continue
        # "." not ":" — it survives encodeURIComponent() unescaped (the dev server/relay
        # never percent-decodes the path before splitting it on "/", so an escaped ":"
        # — %3A — would never match this plain id again).
        rec_id = f"{table}.{column}"
        if rec_id in applied or not _needs_table_scan(store, db_id, table, column):
            continue
        recs.append({"id": rec_id, "action": "CREATE_INDEX", "table": table, "column": column,
                     "script": f"CREATE INDEX ix_{table}_{column} ON {table}({column})",
                     "impactedQueries": count})
    recs.sort(key=lambda r: -r["impactedQueries"])
    return recs


def _apply_recommendation(store: SqlStore, db_id: str, rec_id: str) -> tuple[bool, str | None]:
    recs = {r["id"]: r for r in _candidate_recommendations(store, db_id)}
    rec = recs.get(rec_id)
    if rec is None:
        return False, "This recommendation no longer applies (it may already be indexed)."
    try:
        store.execute_sql(db_id, rec["script"])
    except Exception as e:
        return False, str(e)
    _applied_recs(store, db_id).add(rec_id)
    return True, None


def _auto_tune(store: SqlStore, arm_state: dict | None, server: str, database: str) -> None:
    """Automatic tuning > CREATE INDEX = On: apply every current candidate immediately,
    the same "automatic" promise the real feature makes. FORCE_LAST_GOOD_PLAN and
    DROP_INDEX stay config-only — no plan-regression detection or orphan-index pruning
    is modelled here."""
    opts = (_database_props(arm_state, server, database).get("automaticTuning") or {}).get("options") or {}
    if (opts.get("createIndex") or {}).get("desiredState") != "On":
        return
    db_id = _db_id(server, database)
    for rec in _candidate_recommendations(store, db_id):
        _apply_recommendation(store, db_id, rec["id"])


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: SqlStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", arm_state: dict | None = None) -> AzureSqlResponse:
    """Native-ish Azure SQL REST wire:
        PUT    /servers/{server}                                   create server
        PUT    /servers/{server}/databases/{db}                     create database
        GET    /servers/{server}/databases                          list databases
        DELETE /servers/{server}/databases/{db}                     delete database
        POST   /servers/{server}/databases/{db}/query               execute SQL
        GET    /servers/{server}/databases/{db}/recommendations     tuning recommendations
        POST   /servers/{server}/databases/{db}/recommendations/{id}/apply   apply one

    `arm_state` is the Azure ARM core's resource map (read-only snapshot, same
    contract as azure_blob_core's CORS/lifecycle lookup) — it is how publicNetworkAccess,
    maxSizeBytes and automaticTuning reach this data plane.
    """
    method = (method or "GET").upper()
    segs = [s for s in path.split("?", 1)[0].split("/") if s != ""]
    if len(segs) < 2 or segs[0] != "servers":
        return _err(404, "NotFound", f"Unknown path: {path}")
    server = segs[1]

    if len(segs) == 2:
        if method == "PUT":
            return _create_server(store, server)
        return _err(405, "MethodNotAllowed", f"Unsupported method {method} on server")

    if segs[2] == "databases":
        if len(segs) == 3:
            if method == "GET":
                return _list_databases(store, server)
            return _err(405, "MethodNotAllowed", f"Unsupported method {method} on databases")
        database = segs[3]
        if len(segs) == 4:
            if method == "PUT":
                return _create_database(store, server, database)
            if method == "DELETE":
                return _delete_database(store, server, database)
            return _err(405, "MethodNotAllowed", f"Unsupported method {method} on database")
        if len(segs) == 5 and segs[4] == "query" and method == "POST":
            return _query(store, server, database, body, arm_state)
        if len(segs) == 5 and segs[4] == "recommendations" and method == "GET":
            db_id = _db_id(server, database)
            if not store.instance_exists(db_id):
                return _err(404, "ResourceNotFound", f"Database '{database}' was not found.")
            return _json(200, {"value": _candidate_recommendations(store, db_id)})
        if len(segs) == 7 and segs[4] == "recommendations" and segs[6] == "apply" and method == "POST":
            db_id = _db_id(server, database)
            if not store.instance_exists(db_id):
                return _err(404, "ResourceNotFound", f"Database '{database}' was not found.")
            ok, message = _apply_recommendation(store, db_id, segs[5])
            if not ok:
                return _err(400, "RecommendationNotApplicable", message or "Could not apply recommendation.")
            return _json(200, {"applied": True})

    return _err(404, "NotFound", f"Unknown path: {path}")
