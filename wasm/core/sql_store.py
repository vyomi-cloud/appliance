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

import threading
import time
import uuid
from typing import Any

LOG_LINES_KEPT = 500  # per-instance ring buffer cap (rds.logs honest error log)

DEFAULT_ACCOUNT_ID = "123456789012"  # matches core.app_context.AWS_ACCOUNT_ID


class TransactionError(Exception):
    """An RDS Data API transaction op (Begin/Execute/Commit/Rollback) referenced
    an id that isn't open."""


class TransactionLimitError(TransactionError):
    """BeginTransaction would exceed the instance's max_connections."""


class SqlStore:
    """Base seam. In-memory + sqlite3 by default; subclass to point the data
    plane at a real Postgres/MySQL (Pro/Max) or PGlite (browser)."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID) -> None:
        self.db_instances: dict[str, dict[str, Any]] = {}
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.subnet_groups: dict[str, dict[str, Any]] = {}
        self.parameter_groups: dict[str, dict[str, Any]] = {}
        self.proxies: dict[str, dict[str, Any]] = {}
        self.option_groups: dict[str, dict[str, Any]] = {}
        self.event_subscriptions: dict[str, dict[str, Any]] = {}
        self.reserved_instances: dict[str, dict[str, Any]] = {}
        self.export_tasks: dict[str, dict[str, Any]] = {}
        self.integrations: dict[str, dict[str, Any]] = {}
        self.custom_engine_versions: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []       # append-only event log (DescribeEvents)
        self.tags: dict[str, dict[str, str]] = {}     # resource ARN -> {key: value}
        self.account_id = account_id
        self._conns: dict[str, Any] = {}  # instance_id -> live DB connection
        self._lock = threading.RLock()    # serializes sqlite3 access across request threads
        self._tx_ns = uuid.uuid4().hex    # disambiguates shared-cache sqlite URIs between store instances
        self._tx_conns: dict[str, Any] = {}   # transaction_id -> its own held-open connection
        self._tx_db: dict[str, str] = {}      # transaction_id -> instance id
        self._tx_count: dict[str, int] = {}   # instance id -> count of open explicit transactions
        self._log_lines: dict[str, list[tuple[float, str]]] = {}   # instance id -> [(ts, line), ...]

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

    def drop_snapshot(self, snap_id: str) -> None:
        self.snapshots.pop(snap_id, None)

    def snapshot_ids(self) -> list[str]:
        return sorted(self.snapshots)

    # ── DB subnet group accessors ──────────────────────────────────────
    def put_subnet_group(self, name: str, record: dict) -> None:
        self.subnet_groups[name] = record

    def get_subnet_group(self, name: str) -> dict | None:
        v = self.subnet_groups.get(name)
        return v if isinstance(v, dict) else None

    def drop_subnet_group(self, name: str) -> None:
        self.subnet_groups.pop(name, None)

    def subnet_group_names(self) -> list[str]:
        return sorted(self.subnet_groups)

    # ── DB parameter group accessors ───────────────────────────────────
    def put_parameter_group(self, name: str, record: dict) -> None:
        self.parameter_groups[name] = record

    def get_parameter_group(self, name: str) -> dict | None:
        v = self.parameter_groups.get(name)
        return v if isinstance(v, dict) else None

    def drop_parameter_group(self, name: str) -> None:
        self.parameter_groups.pop(name, None)

    def parameter_group_names(self) -> list[str]:
        return sorted(self.parameter_groups)

    # ── DB proxy accessors ──────────────────────────────────────────────
    def put_proxy(self, name: str, record: dict) -> None:
        self.proxies[name] = record

    def get_proxy(self, name: str) -> dict | None:
        v = self.proxies.get(name)
        return v if isinstance(v, dict) else None

    def drop_proxy(self, name: str) -> None:
        self.proxies.pop(name, None)

    def proxy_names(self) -> list[str]:
        return sorted(self.proxies)

    # ── option group accessors ──────────────────────────────────────────
    def put_option_group(self, name: str, record: dict) -> None:
        self.option_groups[name] = record

    def get_option_group(self, name: str) -> dict | None:
        v = self.option_groups.get(name)
        return v if isinstance(v, dict) else None

    def drop_option_group(self, name: str) -> None:
        self.option_groups.pop(name, None)

    def option_group_names(self) -> list[str]:
        return sorted(self.option_groups)

    # ── reserved DB instance accessors ──────────────────────────────────
    def put_reserved_instance(self, reservation_id: str, record: dict) -> None:
        self.reserved_instances[reservation_id] = record

    def get_reserved_instance(self, reservation_id: str) -> dict | None:
        v = self.reserved_instances.get(reservation_id)
        return v if isinstance(v, dict) else None

    def reserved_instance_ids(self) -> list[str]:
        return sorted(self.reserved_instances)

    # ── export task accessors ───────────────────────────────────────────
    def put_export_task(self, task_id: str, record: dict) -> None:
        self.export_tasks[task_id] = record

    def get_export_task(self, task_id: str) -> dict | None:
        v = self.export_tasks.get(task_id)
        return v if isinstance(v, dict) else None

    def drop_export_task(self, task_id: str) -> None:
        self.export_tasks.pop(task_id, None)

    def export_task_ids(self) -> list[str]:
        return sorted(self.export_tasks)

    # ── zero-ETL integration accessors ──────────────────────────────────
    def put_integration(self, name: str, record: dict) -> None:
        self.integrations[name] = record

    def get_integration(self, name: str) -> dict | None:
        v = self.integrations.get(name)
        return v if isinstance(v, dict) else None

    def drop_integration(self, name: str) -> None:
        self.integrations.pop(name, None)

    def integration_names(self) -> list[str]:
        return sorted(self.integrations)

    # ── custom DB engine version accessors ──────────────────────────────
    def put_custom_engine_version(self, cev_id: str, record: dict) -> None:
        self.custom_engine_versions[cev_id] = record

    def get_custom_engine_version(self, cev_id: str) -> dict | None:
        v = self.custom_engine_versions.get(cev_id)
        return v if isinstance(v, dict) else None

    def drop_custom_engine_version(self, cev_id: str) -> None:
        self.custom_engine_versions.pop(cev_id, None)

    def custom_engine_version_ids(self) -> list[str]:
        return sorted(self.custom_engine_versions)

    # ── event subscription accessors ─────────────────────────────────────
    def put_event_subscription(self, name: str, record: dict) -> None:
        self.event_subscriptions[name] = record

    def get_event_subscription(self, name: str) -> dict | None:
        v = self.event_subscriptions.get(name)
        return v if isinstance(v, dict) else None

    def drop_event_subscription(self, name: str) -> None:
        self.event_subscriptions.pop(name, None)

    def event_subscription_names(self) -> list[str]:
        return sorted(self.event_subscriptions)

    # ── event log (DescribeEvents) ───────────────────────────────────────
    def add_event(self, record: dict) -> None:
        self.events.append(record)

    def list_events(self) -> list[dict]:
        return list(self.events)

    # ── tags (by resource ARN) ───────────────────────────────────────────
    def get_tags(self, arn: str) -> dict[str, str]:
        return dict(self.tags.get(arn) or {})

    def set_tags(self, arn: str, tags: dict[str, str]) -> None:
        self.tags[arn] = dict(tags or {})

    # ── dialect: bind-parameter placeholder style ─────────────────────
    def param_placeholder(self, index: int) -> str:
        """The bind placeholder for the (1-based) i-th parameter in THIS engine's
        dialect. sqlite3 uses positional '?'; Postgres/PGlite uses '$1', '$2', …
        The RDS Data API core uses this to rewrite its named `:name` params to the
        engine's native style — so the dialect lives with the engine, not callers."""
        return "?"

    # ── the SQL engine (data plane) ───────────────────────────────────
    def _connect(self, db_id: str):
        """Open a fresh DB connection onto the instance's data. Override to back
        the engine with a real Postgres/MySQL or PGlite. Default: a shared-cache
        sqlite3 in-memory database keyed by instance id + this store's identity
        (`_tx_ns`) — "shared-cache" so a SECOND connection (held open for an
        explicit Data API transaction, see begin_transaction()) sees the SAME
        data as the one-shot connection open_engine() keeps for execute_sql().
        `isolation_level=None` puts sqlite in pure passthrough mode: statements
        commit immediately UNLESS an explicit BEGIN is outstanding on that
        connection, which is exactly the autocommit-by-default / explicit-
        transaction-when-asked contract the RDS Data API needs.
        `check_same_thread=False` because a threading HTTP server (dev_server.py, the
        offline appliance) may service the request that opens an instance and the request
        that later queries it on two different worker threads; `self._lock` below is what
        actually serializes access, the same pairing core/vyomi_platform.py uses."""
        import sqlite3  # lazy: a loadable package under Pyodide, stdlib on host
        uri = f"file:nano-rds-{self._tx_ns}-{db_id}?mode=memory&cache=shared"
        return sqlite3.connect(uri, uri=True, check_same_thread=False, isolation_level=None)

    def open_engine(self, db_id: str):
        if db_id not in self._conns:
            self._conns[db_id] = self._connect(db_id)
        return self._conns[db_id]

    def close_engine(self, db_id: str) -> None:
        conn = self._conns.pop(db_id, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        for tx_id in [t for t, d in self._tx_db.items() if d == db_id]:
            self._tx_db.pop(tx_id, None)
            tconn = self._tx_conns.pop(tx_id, None)
            if tconn is not None:
                try:
                    tconn.close()
                except Exception:
                    pass
        self._tx_count.pop(db_id, None)

    @staticmethod
    def _run_cursor(cur, sql: str, params: list | None) -> dict:
        cur.execute(sql, list(params or []))
        if cur.description:
            columns = [d[0] for d in cur.description]
            rows = [list(r) for r in cur.fetchall()]
            return {"columns": columns, "rows": rows, "rowcount": len(rows)}
        return {"columns": [], "rows": [], "rowcount": cur.rowcount}

    def execute_sql(self, db_id: str, sql: str, params: list | None = None) -> dict:
        """Run ONE SQL statement against the instance's real engine. Returns
        {columns, rows, rowcount} — rows for a SELECT, rowcount for DML. Always
        autocommits (no outstanding explicit BEGIN on this connection) — use
        begin_transaction()/execute_in_transaction() for cross-call atomicity."""
        with self._lock:
            conn = self.open_engine(db_id)
            cur = conn.cursor()
            try:
                result = self._run_cursor(cur, sql, params)
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

    # ── explicit, cross-call transactions (RDS Data API Begin/Execute/Commit/
    # RollbackTransaction) — a SECOND connection onto the SAME instance data,
    # held open across calls instead of the one-shot autocommit connection
    # above. Default (sqlite shared-cache): ONE open transaction at a time is
    # unlimited by the engine itself; `limit` (the instance's max_connections,
    # resolved by rds_core from its DB parameter group) is what RDS enforces. ─
    def begin_transaction(self, db_id: str, limit: int | None = None) -> str:
        with self._lock:
            if limit is not None and self._tx_count.get(db_id, 0) >= limit:
                raise TransactionLimitError(
                    f"DB instance {db_id} already has {limit} open connection(s) "
                    "(max_connections) — close one before starting another transaction.")
            self.open_engine(db_id)  # make sure the instance's data/engine already exists
            conn = self._connect(db_id)
            cur = conn.cursor()
            cur.execute("BEGIN")
            cur.close()
            tx_id = f"tx-{uuid.uuid4().hex[:24]}"
            self._tx_conns[tx_id] = conn
            self._tx_db[tx_id] = db_id
            self._tx_count[db_id] = self._tx_count.get(db_id, 0) + 1
            return tx_id

    def execute_in_transaction(self, tx_id: str, sql: str, params: list | None = None) -> dict:
        with self._lock:
            conn = self._tx_conns.get(tx_id)
            if conn is None:
                raise TransactionError(f"Invalid transaction ID: {tx_id}")
            cur = conn.cursor()
            try:
                return self._run_cursor(cur, sql, params)
            finally:
                cur.close()

    def _end_transaction(self, tx_id: str, commit: bool) -> bool:
        with self._lock:
            conn = self._tx_conns.pop(tx_id, None)
            db_id = self._tx_db.pop(tx_id, None)
            if conn is None or db_id is None:
                return False
            try:
                conn.commit() if commit else conn.rollback()
            finally:
                conn.close()
                self._tx_count[db_id] = max(0, self._tx_count.get(db_id, 1) - 1)
            return True

    def commit_transaction(self, tx_id: str) -> bool:
        return self._end_transaction(tx_id, commit=True)

    def rollback_transaction(self, tx_id: str) -> bool:
        return self._end_transaction(tx_id, commit=False)

    async def abegin_transaction(self, db_id: str, limit: int | None = None) -> str:
        """Async twin — see aexecute_sql. Overridden by PGliteSqlStore."""
        return self.begin_transaction(db_id, limit=limit)

    async def aexecute_in_transaction(self, tx_id: str, sql: str, params: list | None = None) -> dict:
        return self.execute_in_transaction(tx_id, sql, params)

    async def acommit_transaction(self, tx_id: str) -> bool:
        return self.commit_transaction(tx_id)

    async def arollback_transaction(self, tx_id: str) -> bool:
        return self.rollback_transaction(tx_id)

    # ── cross-call introspection (rds_core's activity-derived metrics/logs:
    # rds.monitoring pushes a real DatabaseConnections point off open_transaction_count,
    # rds.logs appends a real error-log line on a failed statement) ───────────
    def open_transaction_count(self, db_id: str) -> int:
        return self._tx_count.get(db_id, 0)

    def transaction_db_id(self, tx_id: str) -> str | None:
        return self._tx_db.get(tx_id)

    def append_log_line(self, db_id: str, line: str, ts: float | None = None) -> None:
        lines = self._log_lines.setdefault(db_id, [])
        lines.append((ts if ts is not None else time.time(), line))
        if len(lines) > LOG_LINES_KEPT:
            del lines[: len(lines) - LOG_LINES_KEPT]

    def log_lines(self, db_id: str) -> list[tuple[float, str]]:
        return list(self._log_lines.get(db_id, []))

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

    @staticmethod
    async def _arun(db, sql: str, params: list | None) -> dict:
        from pyodide.ffi import to_js  # lazy: Pyodide-only
        from js import Object
        opts = to_js({"rowMode": "array"}, dict_converter=Object.fromEntries)
        res = await db.query(sql, to_js(list(params or [])), opts)
        columns = [f.name for f in res.fields]
        rows = [list(r) for r in res.rows.to_py()]
        affected = getattr(res, "affectedRows", None)
        rowcount = int(affected) if affected is not None else len(rows)
        return {"columns": columns, "rows": rows, "rowcount": rowcount}

    async def aexecute_sql(self, db_id: str, sql: str, params: list | None = None) -> dict:
        db = await self._aopen(db_id)
        return await self._arun(db, sql, params)

    def close_engine(self, db_id: str) -> None:
        super().close_engine(db_id)
        self._aconns.pop(db_id, None)
        self._tx_db = {t: d for t, d in self._tx_db.items() if d != db_id}
        self._tx_count.pop(db_id, None)

    # ── explicit transactions — ONE PGlite connection per instance, so only
    # ONE open explicit transaction at a time is possible (there is no second
    # connection to hold open); `limit` (max_connections) can only ever shrink
    # that to zero, never raise it above one. ──────────────────────────────
    async def abegin_transaction(self, db_id: str, limit: int | None = None) -> str:
        if limit is not None and limit < 1:
            raise TransactionLimitError(
                f"DB instance {db_id} has max_connections={limit} — no connection available.")
        if self._tx_count.get(db_id, 0) > 0:
            raise TransactionLimitError(
                f"DB instance {db_id} already has an open transaction "
                "(the PGlite engine holds a single connection per instance).")
        db = await self._aopen(db_id)
        await db.query("BEGIN")
        tx_id = f"tx-{uuid.uuid4().hex[:24]}"
        self._tx_db[tx_id] = db_id
        self._tx_count[db_id] = 1
        return tx_id

    async def aexecute_in_transaction(self, tx_id: str, sql: str, params: list | None = None) -> dict:
        db_id = self._tx_db.get(tx_id)
        if db_id is None:
            raise TransactionError(f"Invalid transaction ID: {tx_id}")
        db = await self._aopen(db_id)
        return await self._arun(db, sql, params)

    async def _aend_transaction(self, tx_id: str, commit: bool) -> bool:
        db_id = self._tx_db.pop(tx_id, None)
        if db_id is None:
            return False
        self._tx_count[db_id] = max(0, self._tx_count.get(db_id, 1) - 1)
        db = await self._aopen(db_id)
        await db.query("COMMIT" if commit else "ROLLBACK")
        return True

    async def acommit_transaction(self, tx_id: str) -> bool:
        return await self._aend_transaction(tx_id, commit=True)

    async def arollback_transaction(self, tx_id: str) -> bool:
        return await self._aend_transaction(tx_id, commit=False)
