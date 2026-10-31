"""App state store — persistent secrets and app resource records.

Part of the app profile runtime (§4, §6, AE2).
Stores generated secrets (alphanumeric, 32 characters) and per-app resource
configurations in SQLite (VYOMI_APPS_DB, on the persistent /data volume).
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import string
import threading
from pathlib import Path
from typing import Any

_SECRET_ALPHABET = string.ascii_letters + string.digits  # 62 alphanumeric chars (safe in URLs and dotenv)
_SECRET_LEN = 32

_state_lock = threading.Lock()
_backends: dict[str, AppStateStore] = {}


def _default_db_path() -> str:
    override = os.environ.get("VYOMI_APPS_DB")
    if override:
        return override
    # If /data exists and is writable, use it; else fallback to local file
    if os.path.exists("/data") and os.access("/data", os.W_OK):
        return "/data/vyomi_apps.sqlite3"
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), ".vyomi_apps.sqlite3")


class AppStateStore:
    """Thread-safe SQLite store for app-level secrets and registered resources."""

    def __init__(self, db_path: str | None = None) -> None:
        self.path = db_path or _default_db_path()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_secrets (
                    app_name TEXT NOT NULL,
                    secret_name TEXT NOT NULL,
                    secret_value TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (app_name, secret_name)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_resources (
                    app_name TEXT PRIMARY KEY,
                    resources_json TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get_secret(self, app_name: str, secret_name: str) -> str | None:
        with _state_lock:
            cur = self._conn.execute(
                "SELECT secret_value FROM app_secrets WHERE app_name = ? AND secret_name = ?",
                (app_name, secret_name),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def get_or_create_secret(self, app_name: str, secret_name: str) -> str:
        with _state_lock:
            cur = self._conn.execute(
                "SELECT secret_value FROM app_secrets WHERE app_name = ? AND secret_name = ?",
                (app_name, secret_name),
            )
            row = cur.fetchone()
            if row:
                return row[0]
            # Generate 32-character random alphanumeric secret
            val = "".join(secrets.choice(_SECRET_ALPHABET) for _ in range(_SECRET_LEN))
            self._conn.execute(
                "INSERT INTO app_secrets (app_name, secret_name, secret_value) VALUES (?, ?, ?)",
                (app_name, secret_name, val),
            )
            self._conn.commit()
            return val

    def save_resources(self, app_name: str, resources: dict[str, Any]) -> None:
        with _state_lock:
            payload = json.dumps(resources, sort_keys=True)
            self._conn.execute(
                """
                INSERT INTO app_resources (app_name, resources_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(app_name) DO UPDATE SET
                    resources_json = excluded.resources_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (app_name, payload),
            )
            self._conn.commit()

    def get_resources(self, app_name: str) -> dict[str, Any] | None:
        with _state_lock:
            cur = self._conn.execute(
                "SELECT resources_json FROM app_resources WHERE app_name = ?",
                (app_name,),
            )
            row = cur.fetchone()
            if not row:
                return None
            try:
                return json.loads(row[0])
            except Exception:
                return {}

    def list_apps(self) -> list[str]:
        with _state_lock:
            cur = self._conn.execute("SELECT app_name FROM app_resources ORDER BY app_name")
            return [row[0] for row in cur.fetchall()]

    def reset(self, app_name: str | None = None) -> None:
        """Helper for tests."""
        with _state_lock:
            if app_name:
                self._conn.execute("DELETE FROM app_secrets WHERE app_name = ?", (app_name,))
                self._conn.execute("DELETE FROM app_resources WHERE app_name = ?", (app_name,))
            else:
                self._conn.execute("DELETE FROM app_secrets")
                self._conn.execute("DELETE FROM app_resources")
            self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


def get_store(db_path: str | None = None) -> AppStateStore:
    """Singleton getter for the app state store."""
    path = db_path or _default_db_path()
    with _state_lock:
        if path not in _backends:
            _backends[path] = AppStateStore(path)
        return _backends[path]
