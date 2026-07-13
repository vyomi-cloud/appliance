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
"""
from __future__ import annotations

import json
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


def _query(store: SqlStore, server: str, database: str, body: bytes) -> AzureSqlResponse:
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    sql = str(payload.get("sql") or payload.get("query") or "")
    if not sql:
        return _err(400, "BadRequest", "A 'sql' statement is required.")
    result = execute_sql(store, server, database, sql, payload.get("params"))
    if not result.get("ok"):
        return _err(400, result.get("code", "SQLError"), result.get("message", ""))
    return _json(200, {"columns": result["columns"], "rows": result["rows"],
                       "rowCount": result["rowCount"]})


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: SqlStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> AzureSqlResponse:
    """Native-ish Azure SQL REST wire:
        PUT    /servers/{server}                             create server
        PUT    /servers/{server}/databases/{db}             create database
        GET    /servers/{server}/databases                  list databases
        DELETE /servers/{server}/databases/{db}             delete database
        POST   /servers/{server}/databases/{db}/query       execute SQL
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
            return _query(store, server, database, body)

    return _err(404, "NotFound", f"Unknown path: {path}")
