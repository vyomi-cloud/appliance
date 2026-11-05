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

    _NS: dict = {}   # namespace -> store: several PGlite-backed services (rds, gcp_sql, ...) share one JS bridge

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID, ns: str = "rds") -> None:
        super().__init__(account_id)
        self._aconns: dict[str, Any] = {}  # instance_id -> live PGlite database
        self._ns = ns
        PGliteSqlStore._NS[ns] = self
        # The tunnel bridge (JS side) reports the host port once `vyomi-tunnel` is reachable, so host apps
        # (psql, app drivers) can connect to the in-browser database. Best-effort; absent off-Pyodide.
        try:
            from js import globalThis
            from pyodide.ffi import create_proxy
            if not getattr(PGliteSqlStore, "_proxy", None):
                PGliteSqlStore._proxy = create_proxy(PGliteSqlStore._dispatch_port)
            globalThis.__nano_pg_on_port = PGliteSqlStore._proxy
        except Exception:
            pass

    @staticmethod
    def _dispatch_port(key, port) -> None:
        ns, _, db_id = str(key).partition("/")
        st = PGliteSqlStore._NS.get(ns)
        if st is not None:
            st._on_bridge_port(db_id, port)

    def _key(self, db_id: str) -> str:
        return f"{self._ns}/{db_id}"

    @staticmethod
    def _is_pg(rec: dict | None) -> bool:
        e = str((rec or {}).get("engine") or (rec or {}).get("databaseVersion") or "postgres").lower()
        return not ("mysql" in e or "maria" in e)

    def _on_bridge_port(self, db_id, port) -> None:
        # Kept in a side map and overlaid in get_instance(): a registry snapshot/restore (console<->worker sync)
        # replaces the instance dicts, which would silently drop an endpoint written onto the record itself.
        port = int(port or 0)
        if port:
            self.__dict__.setdefault("_bridge_ports", {})[str(db_id)] = port
            # Also write it onto the record so the registry snapshot carries it to the console's context.
            rec = SqlStore.get_instance(self, str(db_id))
            if rec is not None and self._is_pg(rec):
                rec["endpoint_address"] = "127.0.0.1"; rec["endpoint_port"] = port; rec["runtime_backend"] = "pglite"
                self.persist()

    def get_instance(self, db_id: str) -> dict | None:
        rec = super().get_instance(db_id)
        port = self.__dict__.get("_bridge_ports", {}).get(db_id)
        if rec is not None and port and self._is_pg(rec):
            rec["endpoint_address"] = "127.0.0.1"
            rec["endpoint_port"] = port
            rec["runtime_backend"] = "pglite"
        return rec

    async def _abridge(self, db_id: str) -> None:
        """Open the instance's PGlite database now and publish it on a tunnel host port."""
        try:
            await self._aopen(db_id)
            from js import globalThis
            fn = getattr(globalThis, "__nano_pg_endpoint", None)
            if fn is not None:
                self._on_bridge_port(db_id, await fn(self._key(db_id)))
        except Exception:
            pass

    def ensure_bridges(self) -> None:
        """After a registry restore (the console created/removed databases in another context): publish every
        Postgres instance that has no live PGlite yet, and drop bridges for instances that are gone."""
        try:
            import asyncio
            from js import globalThis
            live = set(self.instance_ids())
            sync = getattr(globalThis, "__nano_pg_sync", None)
            if sync is not None:   # the JS side owns the bridges: drop any whose instance no longer exists
                from pyodide.ffi import to_js
                sync(self._ns, to_js([self._key(i) for i in live]))
            for db_id in list(self._aconns):
                if db_id not in live:
                    self.close_engine(db_id)
                    fn = getattr(globalThis, "__nano_pg_close", None)
                    if fn is not None:
                        fn(self._key(db_id))
                    self.__dict__.setdefault("_bridge_ports", {}).pop(db_id, None)
            for db_id in live:
                rec = SqlStore.get_instance(self, db_id)
                if rec is not None and self._is_pg(rec) and not rec.get("masterInstanceName") and db_id not in self._aconns:
                    asyncio.ensure_future(self._abridge(db_id))
        except Exception:
            pass

    def mirror_create_instance(self, db_id: str, record: dict) -> None:
        if not self._is_pg(record):
            return
        try:
            import asyncio
            asyncio.ensure_future(self._abridge(db_id))
        except Exception:
            pass

    def mirror_delete_instance(self, db_id: str) -> None:
        self.__dict__.setdefault("_bridge_ports", {}).pop(db_id, None)
        try:
            from js import globalThis
            fn = getattr(globalThis, "__nano_pg_close", None)
            if fn is not None:
                fn(self._key(db_id))
        except Exception:
            pass

    def param_placeholder(self, index: int) -> str:
        return f"${index}"  # Postgres numbered placeholders

    async def _aopen(self, db_id: str):
        if db_id not in self._aconns:
            from js import globalThis  # lazy: Pyodide-only
            # getattr avoids Python name-mangling of the dunder attribute name.
            factory = getattr(globalThis, "__nano_pglite_new")
            self._aconns[db_id] = await factory(self._key(db_id))
        return self._aconns[db_id]

    async def aexecute_sql(self, db_id: str, sql: str, params: list | None = None) -> dict:
        if self._ns != "rds" and not self._is_pg(self.get_instance(db_id)):
            return self.execute_sql(db_id, sql, params)   # a MySQL instance keeps the sqlite fallback (no browser MySQL engine)
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
