# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Database endpoints for the Nano host bridge (wasm/db-bridge.js): which in-browser database instances exist, and a SQL entry point.

The browser cannot listen on a TCP port, so `vyomi-tunnel` opens a host port per database and bridges the bytes to the tab, where
wasm/db-wire-pg.js (Postgres wire -> PGlite) and wasm/db-wire-mysql.js (MySQL wire -> the translator in core/mysql_dialect) speak the
database protocol. This module is the Python half: enumerate instances (RDS + Cloud SQL), and run SQL (MySQL-family instances go through
the dialect translator onto their sqlite store; everything else straight to the engine).

State is read from the live SqlStores (core/nano_registry); nothing is stored here.
"""
from __future__ import annotations

import json

try:
    from core import mysql_dialect as _md
    from core import nano_registry as _reg
    from core import sql_store as _sq
except ImportError:  # pragma: no cover - Pyodide flat layout
    import mysql_dialect as _md  # type: ignore
    import nano_registry as _reg  # type: ignore
    import sql_store as _sq  # type: ignore

_STORE_KEYS = ("rds", "gcp_sql")


def _family(engine) -> str:
    e = str(engine or "").lower()
    if _md.is_mysql_engine(e):
        return "mysql"
    if e.startswith("postgres") or "postgres" in e or e == "aurora-postgresql":
        return "postgres"
    return ""


def list_endpoints(stores: dict | None = None) -> list[dict]:
    stores = stores if stores is not None else _reg.get()
    out = []
    for key in _STORE_KEYS:
        st = stores.get(key)
        if st is None:
            continue
        for db_id in st.instance_ids():
            rec = st.get_instance(db_id) or {}
            if key == "rds":
                if rec.get("db_instance_status", "available") != "available":
                    continue
                fam = _family(rec.get("engine"))
                user, name, label = rec.get("master_username", "admin"), rec.get("db_name") or "", db_id
            else:  # Cloud SQL: cloudsql:<project>/<instance>
                if str(rec.get("state", "RUNNABLE")).upper() not in ("RUNNABLE", "AVAILABLE"):
                    continue
                fam = _family(rec.get("databaseVersion"))
                user, name, label = "postgres" if fam == "postgres" else "root", "", db_id.split(":", 1)[-1]
            if not fam:
                continue
            if fam == "postgres" and not hasattr(st, "_aopen"):
                continue    # the Postgres wire needs a real Postgres engine (PGlite); a sqlite-backed store has nothing to serve
            out.append({"key": f"{key}:{db_id}", "label": label, "engine": fam, "user": user, "database": name,
                        "version": str(rec.get("engine_version") or rec.get("databaseVersion") or "")})
    return out


def list_json() -> str:
    return json.dumps(list_endpoints())


def _resolve(key: str, stores: dict | None = None):
    stores = stores if stores is not None else _reg.get()
    sk, _, db_id = str(key).partition(":")
    st = stores.get(sk)
    if st is None or not st.get_instance(db_id):
        raise LookupError(f"no such database {key}")
    return st, db_id


def _jsonable(v):
    if isinstance(v, (bytes, bytearray)):
        try:
            return bytes(v).decode("utf-8")
        except UnicodeDecodeError:
            return bytes(v).hex()
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    return str(v)


async def exec_json(key: str, sql: str) -> str:
    """Run one SQL string; -> JSON {ok, columns, rows, rowcount, lastInsertId} or {ok:false, message}."""
    try:
        st, db_id = _resolve(key)
        rec = st.get_instance(db_id) or {}
        fam = _family(rec.get("engine") or rec.get("databaseVersion"))
        if fam == "mysql":
            es = _sq.engine_store_for(st, db_id)
            dbname = str(rec.get("db_name") or "db")
            res = await _md.arun(sql, None, lambda q, p: es.aexecute_sql(db_id, q, p), dbname)
            last = 0
            if sql.lstrip()[:7].upper() in ("INSERT ", "REPLACE"):
                try:
                    last = (await es.aexecute_sql(db_id, "SELECT last_insert_rowid()", None))["rows"][0][0] or 0
                except Exception:
                    last = 0
        else:
            res = await st.aexecute_sql(db_id, sql, None)
            last = 0
        return json.dumps({"ok": True, "columns": list(res.get("columns", [])),
                           "rows": [[_jsonable(c) for c in r] for r in res.get("rows", [])],
                           "rowcount": res.get("rowcount", 0), "lastInsertId": last})
    except Exception as e:  # noqa: BLE001 — the wire front end turns this into the protocol's own error packet
        return json.dumps({"ok": False, "message": str(e)})


async def pg_handle(key: str):
    """The live PGlite database object for a Postgres instance (JS side calls execProtocolRaw on it); None when the engine is not PGlite."""
    st, db_id = _resolve(key)
    if hasattr(st, "_aopen"):
        return await st._aopen(db_id)
    return None
