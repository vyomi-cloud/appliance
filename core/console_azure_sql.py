"""console-next SQL facade (Azure SQL Database) — the Azure lens's sql-console data
plane.

Azure SQL Database reuses the SAME relay-safe SQL engine the RDS Data API facade
(core/console_sql.py) and the Cloud SQL facade (core/console_cloudsql.py) drive:

    core/rds_data_core.py       — translates the rest-json Data API wire onto …
    core/rds_core.aexecute_sql  — the SqlStore data plane (real sqlite3 engine here)

The SAME sql-console widget renders under lens=azure; the ONLY difference is the
manifest `api` block pointing at /api/console/azure-sql/* instead of
/api/console/rds/* or /api/console/cloudsql/* (§15.2 — no if(cloud) branching in the
widget). This module is a thin sibling of console_cloudsql with its OWN
module-level store + default db so the Azure lens's SQL state is independent of the
AWS/GCP lenses'; the response shapes are byte-identical.

Purely additive: it holds its own InMemorySqlStore and never touches any native
Azure SQL control-plane state or its routes. The target database is auto-created
(status=available) on first use so the widget works without a separate create step —
the demo database is `azuresql-demo` unless the caller names another.
"""

from __future__ import annotations

from typing import Any

from core import rds_core, rds_data_core
from core.sql_store import InMemorySqlStore

_STORE = InMemorySqlStore()
_DEFAULT_DB = "azuresql-demo"


def store() -> InMemorySqlStore:
    return _STORE


def _ensure_instance(db_id: str) -> None:
    if not _STORE.instance_exists(db_id):
        rds_core._create_db_instance(_STORE, {
            "DBInstanceIdentifier": db_id, "Engine": "postgres",
            "MasterUsername": "sqladmin",
        })


def list_databases() -> dict:
    """List the Azure SQL databases (auto-provisions the default on first call)."""
    _ensure_instance(_DEFAULT_DB)
    out = []
    for db_id in _STORE.instance_ids():
        db = _STORE.get_instance(db_id) or {}
        out.append({
            "db_instance_identifier": db_id,
            "engine": db.get("engine", "postgres"),
            "engine_version": db.get("engine_version", ""),
            "status": db.get("db_instance_status", "available"),
            "endpoint": f"{db.get('endpoint_address', '')}:{db.get('endpoint_port', 1433)}",
        })
    return {"databases": out, "default": _DEFAULT_DB, "count": len(out)}


async def execute(db_id: str, sql: str, parameters: list | None = None) -> dict:
    """Run one SQL statement via the SAME relay-safe SQL engine console_sql uses.
    Returns the grid-friendly {ok, columns, rows, rowcount, error?} shape the
    sql-console widget consumes — identical to the RDS / Cloud SQL facades."""
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
    rows = [[rds_data_core._field_to_py(f) for f in rec] for rec in data.get("records", [])]
    return {"ok": True, "columns": columns, "rows": rows,
            "rowcount": data.get("numberOfRecordsUpdated", len(rows)),
            "is_select": bool(columns)}


async def schema(db_id: str) -> dict:
    """List tables + columns for the schema browser (sqlite_master + PRAGMA)."""
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
                idx = {c: i for i, c in enumerate(cols_res.get("columns", []))}
                for c in cols_res.get("rows", []):
                    cols.append({"name": c[idx.get("name", 1)],
                                 "type": c[idx.get("type", 2)],
                                 "pk": bool(c[idx.get("pk", 5)])})
            tables.append({"name": tname, "columns": cols})
    return {"db_instance_identifier": db_id, "tables": tables}
