from __future__ import annotations

import copy
import base64
import json
import os
import pickle
import platform
import shutil
import sqlite3
import subprocess
import threading
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable, Optional


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _encode_state_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__cloudlearn_type__": "bytes", "base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {k: _encode_state_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_encode_state_value(v) for v in value]
    if isinstance(value, tuple):
        return [_encode_state_value(v) for v in value]
    return value


def _decode_state_value(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get("__cloudlearn_type__") == "bytes" and "base64" in value:
            return base64.b64decode(value["base64"])
        return {k: _decode_state_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_state_value(v) for v in value]
    return value


class SQLiteStateStore:
    def __init__(self, db_path: Path, legacy_pickle_path: Path | None = None):
        self.db_path = Path(db_path)
        self.legacy_pickle_path = Path(legacy_pickle_path) if legacy_pickle_path else None
        self.lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    def _read_state_json(self, conn: sqlite3.Connection) -> dict | None:
        row = conn.execute("SELECT value FROM metadata WHERE key = 'state_json'").fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["value"])
        except Exception:
            return None
        return _decode_state_value(payload) if isinstance(payload, dict) else None

    def _write_state_json(self, conn: sqlite3.Connection, state: dict) -> None:
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES('state_json', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(_encode_state_value(state), sort_keys=True, default=_json_default),),
        )
        conn.commit()

    def _load_legacy_pickle(self) -> dict | None:
        if not self.legacy_pickle_path or not self.legacy_pickle_path.exists():
            return None
        try:
            with self.legacy_pickle_path.open("rb") as f:
                payload = pickle.load(f)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def load_state(self, default_factory: Callable[[], dict]) -> dict:
        with self.lock:
            if self.db_path.exists():
                try:
                    with self._connect() as conn:
                        self._ensure_schema(conn)
                        state = self._read_state_json(conn)
                        if isinstance(state, dict):
                            return state
                except Exception:
                    pass

            state = self._load_legacy_pickle()
            if state is None:
                state = default_factory()

            try:
                self.save_state(state)
            except Exception:
                pass
            return state

    def save_state(self, state: dict) -> None:
        with self.lock:
            with self._connect() as conn:
                self._ensure_schema(conn)
                self._write_state_json(conn, state)

    def append_event(self, event: str, detail: dict | None, at: str) -> None:
        with self.lock:
            with self._connect() as conn:
                self._ensure_schema(conn)
                conn.execute(
                    "INSERT INTO events(event, detail_json, at) VALUES (?, ?, ?)",
                    (event, json.dumps(detail or {}, sort_keys=True, default=_json_default), at),
                )
                conn.commit()

    def save_snapshot(self, label: str, state: dict, created_at: str) -> int:
        with self.lock:
            with self._connect() as conn:
                self._ensure_schema(conn)
                cur = conn.execute(
                    "INSERT INTO snapshots(label, state_json, created_at) VALUES (?, ?, ?)",
                    (label, json.dumps(_encode_state_value(state), sort_keys=True, default=_json_default), created_at),
                )
                conn.commit()
                return int(cur.lastrowid)

    def restore_snapshot(self, snapshot_id: int) -> dict | None:
        with self.lock:
            with self._connect() as conn:
                self._ensure_schema(conn)
                row = conn.execute("SELECT state_json FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
                if not row:
                    return None
                try:
                    payload = json.loads(row["state_json"])
                except Exception:
                    return None
                return _decode_state_value(payload) if isinstance(payload, dict) else None


class SimulationKernel:
    def __init__(self, store: SQLiteStateStore, default_state_factory: Callable[[], dict]):
        self.store = store
        self._default_state_factory = default_state_factory
        self.state = self.store.load_state(default_state_factory)

    def persist(self) -> None:
        self.store.save_state(self.state)

    def record_event(self, event: str, detail: dict | None = None, at: str | None = None) -> None:
        payload = detail or {}
        at = at or _now()
        self.state.setdefault("usage", {}).setdefault("events", []).append({"event": event, "detail": payload, "at": at})
        self.state["usage"]["last_event_at"] = at
        self.store.append_event(event, payload, at)
        self.persist()

    def create_resource(self, service: str, resource_type: str, resource_id: str, payload: dict, region: str = "global") -> dict:
        graph = self.state.setdefault("resource_graph", {})
        service_graph = graph.setdefault(service, {})
        region_graph = service_graph.setdefault(region, {})
        resource = copy.deepcopy(payload)
        resource.setdefault("resource_id", resource_id)
        resource.setdefault("resource_type", resource_type)
        resource.setdefault("service", service)
        resource.setdefault("region", region)
        region_graph[resource_id] = resource
        self.persist()
        return resource

    def update_resource(self, service: str, resource_id: str, updates: dict, region: str = "global") -> dict:
        resource = self.query_resource(service, resource_id, region=region)
        if not resource:
            raise KeyError(resource_id)
        resource.update(copy.deepcopy(updates))
        self.persist()
        return resource

    def delete_resource(self, service: str, resource_id: str, region: str = "global") -> None:
        graph = self.state.setdefault("resource_graph", {})
        region_graph = graph.setdefault(service, {}).setdefault(region, {})
        region_graph.pop(resource_id, None)
        self.persist()

    def query_resource(self, service: str, resource_id: str, region: str = "global") -> dict | None:
        graph = self.state.setdefault("resource_graph", {})
        return graph.get(service, {}).get(region, {}).get(resource_id)

    def save_snapshot(self, label: str = "manual") -> int:
        from datetime import datetime, timezone

        return self.store.save_snapshot(label, self.state, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))

    def restore_snapshot(self, snapshot_id: int) -> dict:
        payload = self.store.restore_snapshot(snapshot_id)
        if not isinstance(payload, dict):
            raise KeyError(snapshot_id)
        self.state.clear()
        self.state.update(payload)
        self.persist()
        return self.state

    def evaluate_policy(self, principal: str, action: str, resource: str) -> bool:
        # Simple local simulator policy check: explicit deny wins, otherwise allow.
        policy_graph = self.state.get("iam", {}).get("policies", {})
        for policy in policy_graph.values():
            document = policy.get("document", {})
            statements = document.get("Statement", [])
            if not isinstance(statements, list):
                continue
            for statement in statements:
                if not isinstance(statement, dict):
                    continue
                effect = str(statement.get("Effect", "Allow")).lower()
                actions = statement.get("Action", [])
                resources = statement.get("Resource", [])
                if isinstance(actions, str):
                    actions = [actions]
                if isinstance(resources, str):
                    resources = [resources]
                action_match = "*" in actions or action in actions
                resource_match = "*" in resources or resource in resources
                if action_match and resource_match:
                    return effect != "deny"
        return True

    def allowed_capabilities(self, tier: str) -> set[str]:
        tier = tier.lower()
        base = {"cloudlearn.s3.basic", "cloudlearn.iam.basic", "cloudlearn.ec2.basic", "cloudlearn.vpc.basic", "cloudlearn.runtime.python"}
        if tier in {"free", "pro", "max", "enterprise"}:
            return base
        return base

    def check_license_for_pack(self, pack_id: str) -> None:
        license_info = self.state.get("license", {})
        if pack_id not in self.allowed_capabilities(license_info.get("tier", "free")):
            raise PermissionError("CapabilityLockedByTier")

    def activate_pack(self, pack_id: str) -> dict:
        packs = self.state.setdefault("packs", {})
        if pack_id not in packs:
            raise KeyError(pack_id)
        pack = packs[pack_id]
        api_contract = pack.get("api", {})
        if api_contract.get("protocol") != "aws-like":
            raise ValueError("PackRejected: missing AWS-like API contract")
        if not api_contract.get("actions") or not api_contract.get("requestSchemas") or not api_contract.get("responseSchemas"):
            raise ValueError("PackRejected: incomplete API contract")
        pack["active"] = True
        pack["state"] = "active"
        pack["activated_at"] = _now()
        self.persist()
        return pack

    def capability_for_path(self, path: str) -> str | None:
        if path == "/" or path.startswith("/ui") or path.startswith("/api/s3"):
            return "cloudlearn.s3.basic"
        if path.startswith("/api/iam"):
            return "cloudlearn.iam.basic"
        if path.startswith("/api/ec2"):
            return "cloudlearn.ec2.basic"
        if path.startswith("/api/vpc"):
            return "cloudlearn.vpc.basic"
        if path.startswith("/api/runtime"):
            return "cloudlearn.runtime.python"
        if path.startswith("/api/deployments"):
            return "cloudlearn.runtime.python"
        return None

    def ensure_capability(self, path: str) -> None:
        pack_id = self.capability_for_path(path)
        if not pack_id:
            return
        self.check_license_for_pack(pack_id)
        pack = self.state.setdefault("packs", {}).get(pack_id)
        if not pack:
            raise LookupError("CapabilityPackMissing")
        if not pack.get("active"):
            self.activate_pack(pack_id)

    def catalog(self) -> list[dict]:
        packs = self.state.setdefault("packs", {})
        return [
            {
                "id": pack["id"],
                "type": pack["type"],
                "version": pack["version"],
                "active": bool(pack.get("active")),
                "state": pack.get("state", "available"),
                "provider": pack.get("provider", "agnostic"),
                "api": pack.get("api", {}),
            }
            for pack in packs.values()
        ]


class RuntimeManager:
    def __init__(self, kernel: SimulationKernel):
        self.kernel = kernel
        self._bootstrap_lock = threading.RLock()
        self._bootstrap_thread: threading.Thread | None = None

    def docker_cli(self) -> str | None:
        return shutil.which("docker")

    def available(self) -> bool:
        binary = self.docker_cli()
        if not binary:
            return False
        try:
            completed = subprocess.run([binary, "info"], capture_output=True, text=True, timeout=15)
        except Exception:
            return False
        return completed.returncode == 0

    def bootstrap_target(self) -> dict:
        system = platform.system().lower()
        brew = shutil.which("brew")
        apt_get = shutil.which("apt-get")
        dnf = shutil.which("dnf")
        if system == "darwin" and brew:
            return {
                "helper": "brew-colima",
                "label": "Install Colima + Docker CLI",
                "message": "This will install Colima and the Docker CLI with Homebrew, then start Colima.",
                "commands": [
                    [brew, "install", "colima", "docker"],
                    ["colima", "start"],
                    ["docker", "context", "use", "colima"],
                ],
            }
        if system == "linux" and apt_get and hasattr(os, "geteuid") and os.geteuid() == 0:
            return {
                "helper": "apt-docker",
                "label": "Install Docker Engine",
                "message": "This will install Docker Engine with apt-get on the local machine.",
                "commands": [
                    [apt_get, "update"],
                    [apt_get, "install", "-y", "docker.io", "docker-compose-plugin"],
                ],
            }
        if system == "linux" and dnf and hasattr(os, "geteuid") and os.geteuid() == 0:
            return {
                "helper": "dnf-docker",
                "label": "Install Docker Engine",
                "message": "This will install Docker Engine with dnf on the local machine.",
                "commands": [
                    [dnf, "install", "-y", "docker", "docker-compose"],
                    ["systemctl", "enable", "--now", "docker"],
                ],
            }
        return {
            "helper": "manual",
            "label": "Open setup instructions",
            "message": "This host does not have an automated Docker bootstrap path. Use the visible instructions to install Docker manually.",
            "commands": [],
        }

    def bootstrap_status(self) -> dict:
        runtime_state = self.kernel.state.setdefault("runtime", {})
        runtime_state.setdefault("docker", {})
        runtime_state["docker"].setdefault("status", "missing")
        runtime_state["docker"].setdefault("message", "")
        runtime_state["docker"].setdefault("mode", "auto")
        runtime_state["docker"].setdefault("last_checked", "")
        status = copy.deepcopy(runtime_state["docker"])
        status["available"] = self.available()
        if status["available"]:
            status["status"] = "ready"
            status["message"] = "Docker runtime is available."
        else:
            target = self.bootstrap_target()
            status.setdefault("helper", target["helper"])
            status.setdefault("label", target["label"])
            status["message"] = status.get("message") or target["message"]
            status["target"] = {
                "helper": target["helper"],
                "label": target["label"],
                "message": target["message"],
            }
        return status

    def _run_bootstrap_command(self, args: list[str], timeout: int = 1200) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)

    def _apply_bootstrap_result(self, result: subprocess.CompletedProcess) -> None:
        runtime_state = self.kernel.state.setdefault("runtime", {})
        runtime_state.setdefault("docker", {})
        output = (result.stdout or "") + (result.stderr or "")
        runtime_state["docker"]["last_checked"] = _now()
        runtime_state["docker"]["message"] = output[-1000:].strip()
        runtime_state["docker"]["status"] = "ready" if result.returncode == 0 else "error"
        self.kernel.persist()

    def _bootstrap_worker(self) -> None:
        runtime_state = self.kernel.state.setdefault("runtime", {})
        runtime_state.setdefault("docker", {})
        target = self.bootstrap_target()
        with self._bootstrap_lock:
            runtime_state["docker"]["status"] = "installing"
            runtime_state["docker"]["helper"] = target["helper"]
            runtime_state["docker"]["label"] = target["label"]
            runtime_state["docker"]["message"] = target["message"]
            runtime_state["docker"]["started_at"] = _now()
            self.kernel.persist()

        try:
            if target["helper"] in {"brew-colima", "apt-docker", "dnf-docker"}:
                for command in target["commands"]:
                    completed = self._run_bootstrap_command(command, timeout=1800 if command[0] and "brew" in command[0] else 900)
                    self._apply_bootstrap_result(completed)
                    if completed.returncode != 0:
                        break
            else:
                runtime_state["docker"]["status"] = "manual"
                runtime_state["docker"]["message"] = target["message"]
                self.kernel.persist()
        except Exception as exc:
            runtime_state["docker"]["status"] = "error"
            runtime_state["docker"]["message"] = str(exc)
            runtime_state["docker"]["finished_at"] = _now()
            self.kernel.persist()
            return

        runtime_state["docker"]["finished_at"] = _now()
        if self.available():
            runtime_state["docker"]["status"] = "ready"
            runtime_state["docker"]["message"] = "Docker runtime is ready."
        elif runtime_state["docker"].get("status") not in {"manual", "error"}:
            runtime_state["docker"]["status"] = "error"
            if not runtime_state["docker"].get("message"):
                runtime_state["docker"]["message"] = "Docker bootstrap finished without a usable Docker CLI."
        self.kernel.persist()

    def start_bootstrap(self) -> dict:
        with self._bootstrap_lock:
            if self.available():
                runtime_state = self.kernel.state.setdefault("runtime", {})
                runtime_state.setdefault("docker", {})
                runtime_state["docker"]["status"] = "ready"
                runtime_state["docker"]["message"] = "Docker runtime is available."
                runtime_state["docker"]["last_checked"] = ""
                self.kernel.persist()
                return self.bootstrap_status()
            if self._bootstrap_thread and self._bootstrap_thread.is_alive():
                return self.bootstrap_status()
            runtime_state = self.kernel.state.setdefault("runtime", {})
            runtime_state.setdefault("docker", {})
            runtime_state["docker"]["helper"] = self.bootstrap_target()["helper"]
            runtime_state["docker"]["status"] = "installing"
            runtime_state["docker"]["message"] = "Starting Docker bootstrap."
            runtime_state["docker"]["started_at"] = _now()
            runtime_state["docker"]["last_checked"] = _now()
            self.kernel.persist()
            self._bootstrap_thread = threading.Thread(target=self._bootstrap_worker, daemon=True)
            self._bootstrap_thread.start()
            return self.bootstrap_status()

    def preferred_backend(self) -> str:
        return "docker" if self.available() else "simulated"


class CloudLearnPlatform:
    def __init__(
        self,
        state_path: Path,
        legacy_pickle_path: Path | None,
        default_state_factory: Callable[[], dict],
    ) -> None:
        self.store = SQLiteStateStore(state_path, legacy_pickle_path)
        self.kernel = SimulationKernel(self.store, default_state_factory)
        self.runtime = RuntimeManager(self.kernel)

    @property
    def state(self) -> dict:
        return self.kernel.state

    def persist(self) -> None:
        self.kernel.persist()

    def record_event(self, event: str, detail: dict | None = None) -> None:
        self.kernel.record_event(event, detail)

    def activate_pack(self, pack_id: str) -> dict:
        return self.kernel.activate_pack(pack_id)

    def ensure_capability(self, path: str) -> None:
        self.kernel.ensure_capability(path)

    def catalog(self) -> list[dict]:
        return self.kernel.catalog()
