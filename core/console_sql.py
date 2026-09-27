"""console-next SQL facade (RDS) — relay-safe SQL over HTTP for the sql-console
widget (§13.4).

The spec calls for the RDS **Data API (ExecuteStatement)** as the connection path,
because it is the ONE relational surface that survives the HTTP relay (a bare
psycopg2/TCP socket can't). The appliance serves the RDS *control* plane over REST
(/api/rds/*) but has NO SQL-execution-over-REST endpoint, so this module adds one for
console-next — driving the SAME substrate-agnostic cores the Nano relay uses:

    core/rds_data_core.py  — translates the rest-json Data API wire onto …
    core/rds_core.aexecute_sql — the SqlStore data plane (real sqlite3 engine here;
                                 PGlite/real-Postgres swaps in behind the seam later)

So `ExecuteStatement` through this facade runs REAL SQL against a REAL engine, and an
external boto3 `rds-data` client hitting the Nano relay gets byte-identical behaviour.

Purely additive: it holds its own module-level InMemorySqlStore and never touches the
appliance RDS control-plane state or its routes. The target instance is auto-created
(status=available) on first use so the widget works without a separate CreateDBInstance
step — the demo db instance is `console-db` unless the caller names another.
"""

from __future__ import annotations

from typing import Any

from core import rds_core, rds_data_core
from core.sql_store import InMemorySqlStore

_STORE = InMemorySqlStore()
_DEFAULT_DB = "console-db"


def store() -> InMemorySqlStore:
    return _STORE


def _ensure_instance(db_id: str) -> None:
    if not _STORE.instance_exists(db_id):
        rds_core._create_db_instance(_STORE, {
            "DBInstanceIdentifier": db_id, "Engine": "postgres",
            "MasterUsername": "admin",
        })


def list_databases() -> dict:
    """List the console SQL instances (auto-provisions the default on first call)."""
    _ensure_instance(_DEFAULT_DB)
    out = []
    for db_id in _STORE.instance_ids():
        db = _STORE.get_instance(db_id) or {}
        out.append({
            "db_instance_identifier": db_id,
            "engine": db.get("engine", "postgres"),
            "engine_version": db.get("engine_version", ""),
            "status": db.get("db_instance_status", "available"),
            "endpoint": f"{db.get('endpoint_address', '')}:{db.get('endpoint_port', 5432)}",
        })
    return {"databases": out, "default": _DEFAULT_DB, "count": len(out)}


async def execute(db_id: str, sql: str, parameters: list | None = None) -> dict:
    """Run one SQL statement via the RDS Data API core (relay-safe path). Returns a
    grid-friendly {ok, columns, rows, rowcount, error?} shape for the widget."""
    db_id = (db_id or _DEFAULT_DB).strip() or _DEFAULT_DB
    _ensure_instance(db_id)
    body: dict[str, Any] = {"resourceArn": f"arn:aws:rds:us-east-1:{_STORE.account_id}:db:{db_id}",
                            "database": db_id, "sql": sql, "includeResultMetadata": True}
    if parameters:
        body["parameters"] = parameters
    resp = await rds_data_core.dispatch(_STORE, "/Execute", body)
    if resp.status >= 400:
        return {"ok": False, "error": resp.body.get("message", "SQL error"),
                "columns": [], "rows": [], "rowcount": 0}
    data = resp.body
    columns = [c.get("name") for c in data.get("columnMetadata", [])]
    # Data API returns typed field dicts; flatten to plain python for the grid.
    rows = [[rds_data_core._field_to_py(f) for f in rec] for rec in data.get("records", [])]
    return {"ok": True, "columns": columns, "rows": rows,
            "rowcount": data.get("numberOfRecordsUpdated", len(rows)),
            "is_select": bool(columns)}


async def schema(db_id: str) -> dict:
    """List tables + columns for the schema browser. sqlite3 engine → read
    sqlite_master + PRAGMA; keep it engine-tolerant (empty on non-sqlite for now)."""
    db_id = (db_id or _DEFAULT_DB).strip() or _DEFAULT_DB
    _ensure_instance(db_id)
    tables: list[dict] = []
    res = await execute(db_id,
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%' ORDER BY name")
    if res.get("ok"):
        for row in res.get("rows", []):
            tname = row[0]
            cols_res = await execute(db_id, f"PRAGMA table_info({tname})")
            cols = []
            if cols_res.get("ok"):
                # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
                idx = {c: i for i, c in enumerate(cols_res.get("columns", []))}
                for c in cols_res.get("rows", []):
                    cols.append({"name": c[idx.get("name", 1)],
                                 "type": c[idx.get("type", 2)],
                                 "pk": bool(c[idx.get("pk", 5)])})
            tables.append({"name": tname, "columns": cols})
    return {"db_instance_identifier": db_id, "tables": tables}
