# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""SqlStore — the data-plane seam for RDS (relational databases) (ADR-001).

The RDS control-plane logic (instance lifecycle, snapshots, native wire shapes)
is substrate-independent and lives in core/rds_core.py. THIS is the seam it
persists through — and, unlike the other backends, it also carries a REAL SQL
engine so created instances actually run SQL:

    Pro/Max : a real Postgres/MySQL (psycopg2/pymysql to a shared engine/container)
    Nano    : InMemorySqlStore — stdlib sqlite3 (a real SQL engine that runs in
              Pyodide); a PGlite/Postgres-wire engine can swap in for unmodified
              psycopg2 conformance via the relay/bridge later
    tests   : InMemorySqlStore

`sqlite3` is imported LAZILY (inside the engine) because in Pyodide it is a
loadable package (`pyodide.loadPackage("sqlite3")`), not part of the default
runtime — so importing this module never fails, and the engine only needs sqlite3
when SQL actually runs. Nothing here imports fastapi / boto3 / socket / psycopg2,
so it loads under Pyodide.

State shapes:
    db_instances : { id -> instance metadata }   (record shape owned by rds_core)
    snapshots    : { id -> snapshot metadata }
    (live SQL connections are held off-state in _conns, keyed by instance id)
"""
from __future__ import annotations

from typing import Any

DEFAULT_ACCOUNT_ID = "123456789012"  # matches core.app_context.AWS_ACCOUNT_ID


class SqlStore:
    """Base seam. In-memory + sqlite3 by default; subclass to point the data
    plane at a real Postgres/MySQL (Pro/Max) or PGlite (browser)."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID) -> None:
        self.db_instances: dict[str, dict[str, Any]] = {}
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.account_id = account_id
        self._conns: dict[str, Any] = {}  # instance_id -> live DB connection

    # ── instance metadata accessors ───────────────────────────────────
    def instance_exists(self, db_id: str) -> bool:
        return db_id in self.db_instances

    def get_instance(self, db_id: str) -> dict | None:
        v = self.db_instances.get(db_id)
        return v if isinstance(v, dict) else None

    def put_instance(self, db_id: str, record: dict) -> None:
        self.db_instances[db_id] = record

    def drop_instance(self, db_id: str) -> None:
        self.db_instances.pop(db_id, None)
        self.close_engine(db_id)

    def instance_ids(self) -> list[str]:
        return sorted(self.db_instances)

    # ── snapshot accessors ────────────────────────────────────────────
    def put_snapshot(self, snap_id: str, record: dict) -> None:
        self.snapshots[snap_id] = record

    def get_snapshot(self, snap_id: str) -> dict | None:
        v = self.snapshots.get(snap_id)
        return v if isinstance(v, dict) else None

    def snapshot_ids(self) -> list[str]:
        return sorted(self.snapshots)

    # ── dialect: bind-parameter placeholder style ─────────────────────
    def param_placeholder(self, index: int) -> str:
        """The bind placeholder for the (1-based) i-th parameter in THIS engine's
        dialect. sqlite3 uses positional '?'; Postgres/PGlite uses '$1', '$2', …
        The RDS Data API core uses this to rewrite its named `:name` params to the
        engine's native style — so the dialect lives with the engine, not callers."""
        return "?"

    # ── the SQL engine (data plane) ───────────────────────────────────
    def _connect(self):
        """Open a fresh DB connection. Override to back the engine with a real
        Postgres/MySQL or PGlite. Default: an in-memory sqlite3 database."""
        import sqlite3  # lazy: a loadable package under Pyodide, stdlib on host
        return sqlite3.connect(":memory:")

    def open_engine(self, db_id: str):
        if db_id not in self._conns:
            self._conns[db_id] = self._connect()
        return self._conns[db_id]

    def close_engine(self, db_id: str) -> None:
        conn = self._conns.pop(db_id, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def execute_sql(self, db_id: str, sql: str, params: list | None = None) -> dict:
        """Run ONE SQL statement against the instance's real engine. Returns
        {columns, rows, rowcount} — rows for a SELECT, rowcount for DML."""
        conn = self.open_engine(db_id)
        cur = conn.cursor()
        try:
            cur.execute(sql, list(params or []))
            if cur.description:
                columns = [d[0] for d in cur.description]
                rows = [list(r) for r in cur.fetchall()]
                result = {"columns": columns, "rows": rows, "rowcount": len(rows)}
            else:
                result = {"columns": [], "rows": [], "rowcount": cur.rowcount}
            conn.commit()
            return result
        finally:
            cur.close()

    async def aexecute_sql(self, db_id: str, sql: str, params: list | None = None) -> dict:
        """Async data-plane entry (same {columns, rows, rowcount} contract). The
        base delegates to the sync engine, so existing stores (sqlite3 in Nano, a
        real Postgres/MySQL in Pro/Max) work unchanged through the async path. An
        ASYNC engine — PGlite over the real Postgres wire — overrides ONLY this."""
        return self.execute_sql(db_id, sql, params)

    # ── optional hooks (no-ops in the base) ───────────────────────────
    def persist(self) -> None:
        """Flush instance/snapshot metadata to durable storage."""

    def mirror_create_instance(self, db_id: str, record: dict) -> None:
        """Best-effort provision in an external backend (real Postgres/MySQL)."""

    def mirror_delete_instance(self, db_id: str) -> None:
        """Best-effort deprovision in the external mirror."""


class InMemorySqlStore(SqlStore):
    """The Nano / test substrate: in-memory metadata + stdlib-sqlite3 SQL engine."""


class PGliteSqlStore(SqlStore):
    """Browser data-plane: REAL Postgres via PGlite (Postgres compiled to WASM),
    behind the SAME SqlStore seam. This is the fidelity upgrade the sqlite3 default
    can't give — RDS-Postgres apps get genuine Postgres dialect + wire semantics
    (`$1` placeholders, SERIAL, RETURNING, ILIKE, casts, real types), so an
    unmodified psycopg2/SQL app validates against the in-browser sim faithfully.

    PGlite is ASYNC, so this overrides ONLY the async data-plane entry
    (`aexecute_sql`); the control plane and metadata accessors are unchanged. One
    PGlite database is opened per RDS instance id.

    Substrate boundary: the `js` / `pyodide.ffi` imports are LAZY (method-local) so
    this module still imports cleanly on host CPython; the JS side must expose
    `globalThis.__nano_pglite_new` — an `async () -> PGlite` factory (the bundle
    wires this from the PGlite ESM module; the Node validator shims it the same way).
    """

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID) -> None:
        super().__init__(account_id)
        self._aconns: dict[str, Any] = {}  # instance_id -> live PGlite database

    def param_placeholder(self, index: int) -> str:
        return f"${index}"  # Postgres numbered placeholders

    async def _aopen(self, db_id: str):
        if db_id not in self._aconns:
            from js import globalThis  # lazy: Pyodide-only
            # getattr avoids Python name-mangling of the dunder attribute name.
            factory = getattr(globalThis, "__nano_pglite_new")
            self._aconns[db_id] = await factory()
        return self._aconns[db_id]

    async def aexecute_sql(self, db_id: str, sql: str, params: list | None = None) -> dict:
        from pyodide.ffi import to_js  # lazy: Pyodide-only
        from js import Object
        db = await self._aopen(db_id)
        opts = to_js({"rowMode": "array"}, dict_converter=Object.fromEntries)
        res = await db.query(sql, to_js(list(params or [])), opts)
        columns = [f.name for f in res.fields]
        rows = [list(r) for r in res.rows.to_py()]
        affected = getattr(res, "affectedRows", None)
        rowcount = int(affected) if affected is not None else len(rows)
        return {"columns": columns, "rows": rows, "rowcount": rowcount}

    def close_engine(self, db_id: str) -> None:
        super().close_engine(db_id)
        self._aconns.pop(db_id, None)
