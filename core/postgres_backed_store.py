"""Postgres-backed SQL substrate (v2.4.0 Phase 2) — Pro/Max only.

The real-backend implementation of the SqlStore seam: the RDS + Cloud SQL cores
run their data plane against a real PostgreSQL server instead of the in-memory
sqlite3 default. The seam was designed for exactly this — `_connect()` and
`param_placeholder()` are the only overrides needed — so the cores are unchanged.

NOT substrate-free (imports psycopg2) → never vendored to WASM. It runs only in
the server appliance (Pro/Max); Nano uses InMemorySqlStore (sqlite3) / PGliteSqlStore.
Each RDS instance id maps to its own Postgres SCHEMA for isolation.
"""
from __future__ import annotations

import psycopg2

from core.sql_store import SqlStore, DEFAULT_ACCOUNT_ID


class PostgresBackedSqlStore(SqlStore):
    def __init__(self, dsn: str, schema_prefix: str = "rds_",
                 account_id: str = DEFAULT_ACCOUNT_ID) -> None:
        super().__init__(account_id)
        self._dsn = dsn
        self._prefix = schema_prefix

    def param_placeholder(self, index: int) -> str:
        return "%s"   # psycopg2 / libpq positional style

    def _schema(self, db_id: str) -> str:
        # keep it a safe identifier
        safe = "".join(c if c.isalnum() else "_" for c in db_id)
        return f"{self._prefix}{safe}"

    def _connect(self):
        # base open_engine() calls this per db_id; we can't see db_id here, so a
        # per-instance connection is opened via open_engine override below.
        return psycopg2.connect(self._dsn)

    def open_engine(self, db_id: str):
        if db_id not in self._conns:
            conn = psycopg2.connect(self._dsn)
            schema = self._schema(db_id)
            cur = conn.cursor()
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            cur.execute(f'SET search_path TO "{schema}"')
            conn.commit()
            cur.close()
            self._conns[db_id] = conn
        return self._conns[db_id]

    def drop_schema(self, db_id: str) -> None:
        """Deprovision an instance's schema (test cleanup / instance delete)."""
        self.close_engine(db_id)
        conn = psycopg2.connect(self._dsn)
        cur = conn.cursor()
        cur.execute(f'DROP SCHEMA IF EXISTS "{self._schema(db_id)}" CASCADE')
        conn.commit()
        cur.close()
        conn.close()
