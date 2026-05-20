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
import secrets
import uuid
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from pack_catalog import CORE_PACK_IDS


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


class FirestoreEngine:
    def __init__(self, store: SQLiteStateStore, kernel: SimulationKernel):
        self.store = store
        self.kernel = kernel
        self.lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.store.db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gcp_firestore_documents (
                space_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                database_id TEXT NOT NULL,
                collection_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                create_time TEXT NOT NULL,
                update_time TEXT NOT NULL,
                PRIMARY KEY(space_id, project_id, database_id, collection_id, doc_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_gcp_firestore_documents_lookup
            ON gcp_firestore_documents(space_id, project_id, database_id, collection_id, doc_id)
            """
        )
        conn.commit()

    def _space_id(self) -> str:
        active = self.kernel.get_active_space()
        return str(active.get("space_id") or "global") if isinstance(active, dict) else "global"

    def _project_id(self, project: str | None) -> str:
        project = str(project or "").strip()
        return project or self._space_id()

    def _doc_view(self, project: str, database: str, collection: str, doc_id: str, fields: dict[str, Any], created: str, updated: str) -> dict:
        root = "https://firestore.googleapis.com/v1"
        return {
            "name": f"{root}/projects/{project}/databases/{database}/documents/{collection}/{doc_id}",
            "fields": copy.deepcopy(fields or {}),
            "createTime": created,
            "updateTime": updated,
        }

    def _row_to_view(self, row: sqlite3.Row, database: str | None = None) -> dict:
        try:
            fields = json.loads(row["fields_json"]) if row["fields_json"] else {}
        except Exception:
            fields = {}
        return self._doc_view(
            row["project_id"],
            database or row["database_id"],
            row["collection_id"],
            row["doc_id"],
            fields,
            row["create_time"],
            row["update_time"],
        )

    def list_documents(self, project: str, database: str, collection: str) -> list[dict]:
        project = self._project_id(project)
        database = str(database or "(default)")
        collection = str(collection or "").strip()
        if not collection:
            return []
        with self.lock:
            with self._connect() as conn:
                self._ensure_schema(conn)
                rows = conn.execute(
                    """
                    SELECT project_id, database_id, collection_id, doc_id, fields_json, create_time, update_time
                    FROM gcp_firestore_documents
                    WHERE space_id = ? AND project_id = ? AND database_id = ? AND collection_id = ?
                    ORDER BY create_time ASC, doc_id ASC
                    """,
                    (self._space_id(), project, database, collection),
                ).fetchall()
        return [self._row_to_view(row, database) for row in rows]

    def list_root_documents(self, project: str, database: str) -> list[dict]:
        project = self._project_id(project)
        database = str(database or "(default)")
        with self.lock:
            with self._connect() as conn:
                self._ensure_schema(conn)
                rows = conn.execute(
                    """
                    SELECT project_id, database_id, collection_id, doc_id, fields_json, create_time, update_time
                    FROM gcp_firestore_documents
                    WHERE space_id = ? AND project_id = ? AND database_id = ?
                    ORDER BY collection_id ASC, create_time ASC, doc_id ASC
                    """,
                    (self._space_id(), project, database),
                ).fetchall()
        return [self._row_to_view(row, database) for row in rows]

    def get_document(self, project: str, database: str, collection: str, doc_id: str) -> dict | None:
        project = self._project_id(project)
        database = str(database or "(default)")
        collection = str(collection or "").strip()
        doc_id = str(doc_id or "").strip()
        if not collection or not doc_id:
            return None
        with self.lock:
            with self._connect() as conn:
                self._ensure_schema(conn)
                row = conn.execute(
                    """
                    SELECT project_id, database_id, collection_id, doc_id, fields_json, create_time, update_time
                    FROM gcp_firestore_documents
                    WHERE space_id = ? AND project_id = ? AND database_id = ? AND collection_id = ? AND doc_id = ?
                    """,
                    (self._space_id(), project, database, collection, doc_id),
                ).fetchone()
        return self._row_to_view(row, database) if row else None

    def create_document(self, project: str, database: str, collection: str, fields: dict | None = None, doc_id: str | None = None) -> dict:
        project = self._project_id(project)
        database = str(database or "(default)")
        collection = str(collection or "").strip() or "documents"
        doc_id = str(doc_id or "").strip() or f"doc-{uuid.uuid4().hex[:12]}"
        created_at = _now()
        payload = json.dumps(fields or {}, sort_keys=True, default=_json_default)
        with self.lock:
            with self._connect() as conn:
                self._ensure_schema(conn)
                existing = conn.execute(
                    """
                    SELECT create_time FROM gcp_firestore_documents
                    WHERE space_id = ? AND project_id = ? AND database_id = ? AND collection_id = ? AND doc_id = ?
                    """,
                    (self._space_id(), project, database, collection, doc_id),
                ).fetchone()
                create_time = existing["create_time"] if existing else created_at
                update_time = _now()
                conn.execute(
                    """
                    INSERT INTO gcp_firestore_documents(space_id, project_id, database_id, collection_id, doc_id, fields_json, create_time, update_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(space_id, project_id, database_id, collection_id, doc_id)
                    DO UPDATE SET fields_json = excluded.fields_json, update_time = excluded.update_time
                    """,
                    (self._space_id(), project, database, collection, doc_id, payload, create_time, update_time),
                )
                conn.commit()
        return self.get_document(project, database, collection, doc_id) or {}

    def update_document(self, project: str, database: str, collection: str, doc_id: str, fields: dict | None = None) -> dict:
        project = self._project_id(project)
        database = str(database or "(default)")
        collection = str(collection or "").strip()
        doc_id = str(doc_id or "").strip()
        if not collection or not doc_id:
            raise KeyError(doc_id)
        payload = json.dumps(fields or {}, sort_keys=True, default=_json_default)
        with self.lock:
            with self._connect() as conn:
                self._ensure_schema(conn)
                row = conn.execute(
                    """
                    SELECT create_time FROM gcp_firestore_documents
                    WHERE space_id = ? AND project_id = ? AND database_id = ? AND collection_id = ? AND doc_id = ?
                    """,
                    (self._space_id(), project, database, collection, doc_id),
                ).fetchone()
                if not row:
                    raise KeyError(doc_id)
                conn.execute(
                    """
                    UPDATE gcp_firestore_documents
                    SET fields_json = ?, update_time = ?
                    WHERE space_id = ? AND project_id = ? AND database_id = ? AND collection_id = ? AND doc_id = ?
                    """,
                    (payload, _now(), self._space_id(), project, database, collection, doc_id),
                )
                conn.commit()
        return self.get_document(project, database, collection, doc_id) or {}

    def delete_document(self, project: str, database: str, collection: str, doc_id: str) -> None:
        project = self._project_id(project)
        database = str(database or "(default)")
        collection = str(collection or "").strip()
        doc_id = str(doc_id or "").strip()
        with self.lock:
            with self._connect() as conn:
                self._ensure_schema(conn)
                cur = conn.execute(
                    """
                    DELETE FROM gcp_firestore_documents
                    WHERE space_id = ? AND project_id = ? AND database_id = ? AND collection_id = ? AND doc_id = ?
                    """,
                    (self._space_id(), project, database, collection, doc_id),
                )
                conn.commit()
                if cur.rowcount <= 0:
                    raise KeyError(doc_id)

    def run_query(self, project: str, database: str, collection: str = "", field_name: str | None = None, field_value: Any = None, limit: int = 50) -> list[dict]:
        docs = self.list_documents(project, database, collection)
        if field_name:
            docs = [doc for doc in docs if doc.get("fields", {}).get(field_name) == field_value]
        if limit and limit > 0:
            docs = docs[:limit]
        results: list[dict] = []
        for idx, doc in enumerate(docs):
            results.append({
                "document": copy.deepcopy(doc),
                "readTime": _now(),
                "done": False,
            })
        if not results:
            results.append({"readTime": _now(), "done": True})
        else:
            results[-1]["done"] = True
        return results
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
        base = set(CORE_PACK_IDS)
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
        protocol = str(api_contract.get("protocol") or "")
        if not protocol.endswith("-like"):
            raise ValueError("PackRejected: missing provider-like API contract")
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
        if path.startswith(("/storage/v1/", "/api/gcp/storage/", "/api/gcp/s3")):
            return "cloudlearn.gcp.storage.basic"
        if path.startswith("/api/iam"):
            return "cloudlearn.iam.basic"
        if any(token in path for token in (":getIamPolicy", ":setIamPolicy", ":testIamPermissions", "/serviceAccounts")) or path.startswith("/api/gcp/iam"):
            return "cloudlearn.gcp.iam.basic"
        if path.startswith(("/compute/v1", "/api/gcp/compute")):
            return "cloudlearn.gcp.compute.basic"
        if path.startswith("/api/ec2"):
            return "cloudlearn.ec2.basic"
        if path.startswith("/api/gcp/ec2"):
            return "cloudlearn.gcp.compute.basic"
        if path.startswith("/api/vpc"):
            return "cloudlearn.vpc.basic"
        if path.startswith("/compute/v1/projects/") or path.startswith("/api/gcp/vpc"):
            return "cloudlearn.gcp.vpc.basic"
        if path.startswith("/api/spaces") or path.startswith("/api/cloudsim") or path.startswith("/api/federations"):
            return "cloudlearn.cloudsim.basic"
        if path.startswith("/api/dynamodb") or path.startswith("/dynamodb"):
            return "cloudlearn.dynamodb.basic"
        if path.startswith(("/firestore/v1/", "/api/gcp/dynamodb")):
            return "cloudlearn.gcp.firestore.basic"
        if path.startswith("/api/runtime"):
            return "cloudlearn.runtime.python"
        if path.startswith("/api/deployments"):
            return "cloudlearn.runtime.python"
        if path.startswith(("/sql/v1beta4/", "/api/gcp/rds")):
            return "cloudlearn.gcp.cloudsql.basic"
        if path.startswith(("/pubsub/v1/", "/api/gcp/sqs")):
            return "cloudlearn.gcp.pubsub.basic"
        if (path.startswith("/api/gcp/lambda") or (path.startswith("/v1/projects/") and "/locations/" in path and "/functions" in path) or ":call" in path):
            return "cloudlearn.gcp.functions.basic"
        if path.startswith("/api/gcp/apigateway") or (path.startswith("/v1/projects/") and "/locations/" in path and any(token in path for token in ("/apis", "/apiConfigs", "/gateways"))):
            return "cloudlearn.gcp.apigateway.basic"
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
                "fragment_url": pack.get("fragment_url") or f"/api/packs/{pack['id']}/fragment",
                "html_fragment": pack.get("html_fragment", ""),
            }
            for pack in packs.values()
        ]

    def _spaces_state(self) -> dict:
        spaces_state = self.state.setdefault(
            "spaces",
            {
                "spaces": {},
                "active_space_id": "",
                "settings": {
                    "max_spaces": 6,
                    "default_provider": "aws",
                    "default_region": "us-east-1",
                    "max_memory_mb": 8192,
                    "max_disk_mb": 32768,
                },
            },
        )
        spaces_state.setdefault("spaces", {})
        spaces_state.setdefault("active_space_id", "")
        settings = spaces_state.setdefault("settings", {})
        settings.setdefault("max_spaces", 6)
        settings.setdefault("default_provider", "aws")
        settings.setdefault("default_region", "us-east-1")
        settings.setdefault("max_memory_mb", 8192)
        settings.setdefault("max_disk_mb", 32768)
        return spaces_state

    def list_spaces(self) -> list[dict]:
        spaces = self._spaces_state().setdefault("spaces", {})
        items = list(spaces.values())
        items.sort(key=lambda item: (item.get("created_at", ""), item.get("name", "")))
        return copy.deepcopy(items)

    def get_active_space(self) -> dict | None:
        spaces_state = self._spaces_state()
        active_id = spaces_state.get("active_space_id", "")
        if not active_id:
            return None
        space = spaces_state.get("spaces", {}).get(active_id)
        return copy.deepcopy(space) if isinstance(space, dict) else None

    def _space_count(self) -> int:
        return len(self._spaces_state().get("spaces", {}))

    def estimate_space_cost(self, spec: dict | None = None) -> dict:
        spec = copy.deepcopy(spec or {})
        provider = str(spec.get("provider") or self._spaces_state().get("settings", {}).get("default_provider", "aws")).lower()
        runtime_count = int(spec.get("runtime_count") or 0)
        ec2_count = int(spec.get("ec2_count") or 0)
        lambda_count = int(spec.get("lambda_count") or 0)
        rds_count = int(spec.get("rds_count") or 0)
        sqs_count = int(spec.get("sqs_count") or 0)
        ddb_count = int(spec.get("dynamodb_count") or 0)
        base_memory = 180 if provider == "aws" else 170 if provider == "gcp" else 175
        base_disk = 35 if provider == "aws" else 32 if provider == "gcp" else 34
        cloudsim_memory = 110
        lxd_memory = 75
        runtime_memory = runtime_count * 70
        ec2_memory = ec2_count * 140
        lambda_memory = lambda_count * 35
        rds_memory = rds_count * 220
        sqs_memory = sqs_count * 35
        ddb_memory = ddb_count * 95
        total_memory_mb = base_memory + cloudsim_memory + lxd_memory + runtime_memory + ec2_memory + lambda_memory + rds_memory + sqs_memory + ddb_memory
        total_disk_mb = base_disk + (runtime_count * 20) + (ec2_count * 120) + (lambda_count * 20) + (rds_count * 260) + (sqs_count * 5) + (ddb_count * 40)
        return {
            "provider": provider,
            "base_memory_mb": base_memory,
            "cloudsim_memory_mb": cloudsim_memory,
            "lxd_memory_mb": lxd_memory,
            "runtime_memory_mb": runtime_memory,
            "ec2_memory_mb": ec2_memory,
            "lambda_memory_mb": lambda_memory,
            "rds_memory_mb": rds_memory,
            "sqs_memory_mb": sqs_memory,
            "dynamodb_memory_mb": ddb_memory,
            "total_memory_mb": total_memory_mb,
            "base_disk_mb": base_disk,
            "runtime_disk_mb": runtime_count * 20,
            "ec2_disk_mb": ec2_count * 120,
            "lambda_disk_mb": lambda_count * 20,
            "rds_disk_mb": rds_count * 260,
            "sqs_disk_mb": sqs_count * 5,
            "dynamodb_disk_mb": ddb_count * 40,
            "total_disk_mb": total_disk_mb,
            "max_spaces": int(self._spaces_state().get("settings", {}).get("max_spaces", 6)),
            "max_memory_mb": int(self._spaces_state().get("settings", {}).get("max_memory_mb", 8192)),
            "max_disk_mb": int(self._spaces_state().get("settings", {}).get("max_disk_mb", 32768)),
            "current_spaces": self._space_count(),
        }

    def create_space(self, spec: dict) -> dict:
        spec = copy.deepcopy(spec or {})
        spaces_state = self._spaces_state()
        spaces = spaces_state.setdefault("spaces", {})
        settings = spaces_state.setdefault("settings", {})
        max_spaces = int(settings.get("max_spaces", 6))
        max_memory_mb = int(settings.get("max_memory_mb", 8192))
        max_disk_mb = int(settings.get("max_disk_mb", 32768))
        if len(spaces) >= max_spaces:
            raise ValueError("Maximum simulation space limit reached")

        provider = str(spec.get("provider") or settings.get("default_provider", "aws")).lower()
        name = str(spec.get("name") or f"{provider}-space-{len(spaces) + 1}").strip()
        region = str(spec.get("region") or settings.get("default_region", "us-east-1")).strip() or "us-east-1"
        space_id = str(spec.get("space_id") or f"space-{uuid.uuid4().hex[:12]}")
        now = _now()
        estimate = self.estimate_space_cost(
            {
                "provider": provider,
                "runtime_count": int(spec.get("runtime_count") or 0),
                "ec2_count": int(spec.get("ec2_count") or 0),
                "lambda_count": int(spec.get("lambda_count") or 0),
                "rds_count": int(spec.get("rds_count") or 0),
                "sqs_count": int(spec.get("sqs_count") or 0),
                "dynamodb_count": int(spec.get("dynamodb_count") or 0),
            }
        )
        if estimate["total_memory_mb"] > max_memory_mb:
            raise ValueError(f"Estimated memory usage {estimate['total_memory_mb']} MB exceeds local budget {max_memory_mb} MB")
        if estimate["total_disk_mb"] > max_disk_mb:
            raise ValueError(f"Estimated disk usage {estimate['total_disk_mb']} MB exceeds local budget {max_disk_mb} MB")
        space = {
            "space_id": space_id,
            "name": name,
            "provider": provider,
            "status": "running",
            "seed": spec.get("seed") or secrets.token_hex(8),
            "owner_id": spec.get("owner_id") or "local-user",
            "created_at": now,
            "updated_at": now,
            "cloudsim_runtime_id": f"cloudsim-{space_id}",
            "lxd_project_name": f"cl-{space_id}",
            "active_region": region,
            "active_account": spec.get("active_account") or "local-account",
            "max_instances": int(spec.get("max_instances") or 10),
            "max_memory_mb": int(spec.get("max_memory_mb") or estimate["total_memory_mb"] * 2),
            "max_disk_mb": int(spec.get("max_disk_mb") or estimate["total_disk_mb"] * 2),
            "estimated_memory_mb": estimate["total_memory_mb"],
            "estimated_disk_mb": estimate["total_disk_mb"],
            "estimated_runtime_mb": int(spec.get("estimated_runtime_mb") or estimate["runtime_memory_mb"]),
            "estimated_cost_notes": spec.get("estimated_cost_notes") or "Local resource estimate; not billing cost.",
            "runtime_count": int(spec.get("runtime_count") or 0),
            "ec2_count": int(spec.get("ec2_count") or 0),
            "lambda_count": int(spec.get("lambda_count") or 0),
            "rds_count": int(spec.get("rds_count") or 0),
            "sqs_count": int(spec.get("sqs_count") or 0),
            "dynamodb_count": int(spec.get("dynamodb_count") or 0),
            "cloudsim": {"summary": {}, "events": [], "last_tick": ""},
            "runtime": {"mode": "sandboxed", "instances": {}, "sandbox_count": 0},
            "resources": {},
            "events": [],
            "snapshots": [],
            "service_states": {
                "s3": {"buckets": {}, "objects": {}, "multiparts": {}},
                "ec2": {"instances": {}},
                "vpc": {"vpcs": {}, "subnets": {}, "security_groups": {}, "route_tables": {}, "internet_gateways": {}},
                "rds": {"db_instances": {}, "db_subnet_groups": {}, "db_parameter_groups": {}, "db_snapshots": {}, "events": []},
                "apigateway": {"apis": {}, "logs": []},
                "lambda": {"functions": {}, "events": [], "invocations": []},
                "sqs": {"queues": {}, "events": []},
                "dynamodb": {"tables": {}, "events": []},
            },
            "tags": copy.deepcopy(spec.get("tags") or {}),
        }
        spaces[space_id] = space
        if not spaces_state.get("active_space_id"):
            spaces_state["active_space_id"] = space_id
        self.persist()
        return copy.deepcopy(space)

    def switch_space(self, space_id: str) -> dict:
        spaces_state = self._spaces_state()
        space = spaces_state.get("spaces", {}).get(space_id)
        if not isinstance(space, dict):
            raise KeyError(space_id)
        spaces_state["active_space_id"] = space_id
        space["last_selected_at"] = _now()
        self.persist()
        return copy.deepcopy(space)

    def pause_space(self, space_id: str) -> dict:
        space = self._spaces_state().get("spaces", {}).get(space_id)
        if not isinstance(space, dict):
            raise KeyError(space_id)
        space["status"] = "paused"
        space["updated_at"] = _now()
        self.persist()
        return copy.deepcopy(space)

    def resume_space(self, space_id: str) -> dict:
        space = self._spaces_state().get("spaces", {}).get(space_id)
        if not isinstance(space, dict):
            raise KeyError(space_id)
        space["status"] = "running"
        space["updated_at"] = _now()
        self.persist()
        return copy.deepcopy(space)

    def archive_space(self, space_id: str) -> dict:
        space = self._spaces_state().get("spaces", {}).get(space_id)
        if not isinstance(space, dict):
            raise KeyError(space_id)
        space["status"] = "archived"
        space["updated_at"] = _now()
        self.persist()
        return copy.deepcopy(space)

    def delete_space(self, space_id: str) -> None:
        spaces_state = self._spaces_state()
        spaces = spaces_state.get("spaces", {})
        if space_id not in spaces:
            raise KeyError(space_id)
        spaces.pop(space_id, None)
        if spaces_state.get("active_space_id") == space_id:
            spaces_state["active_space_id"] = next(iter(spaces.keys()), "")
        self.persist()


for _kernel_method_name in (
    "evaluate_policy",
    "allowed_capabilities",
    "check_license_for_pack",
    "activate_pack",
    "capability_for_path",
    "ensure_capability",
    "catalog",
    "_spaces_state",
    "list_spaces",
    "get_active_space",
    "_space_count",
    "estimate_space_cost",
    "create_space",
    "switch_space",
    "pause_space",
    "resume_space",
    "archive_space",
    "delete_space",
):
    setattr(SimulationKernel, _kernel_method_name, getattr(FirestoreEngine, _kernel_method_name))


class CloudSimBridge:
    def __init__(self, kernel: SimulationKernel, repo_root: Path):
        self.kernel = kernel
        self.repo_root = Path(repo_root)
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._explicit_base_url = bool(os.environ.get("CLOUDLEARN_CLOUDSIM_URL", "").strip())
        self._base_url = os.environ.get("CLOUDLEARN_CLOUDSIM_URL", "").strip().rstrip("/")
        self._host = os.environ.get("CLOUDLEARN_CLOUDSIM_HOST", "127.0.0.1").strip() or "127.0.0.1"
        self._port = int(os.environ.get("CLOUDLEARN_CLOUDSIM_PORT", "9010"))
        jar_env = os.environ.get("CLOUDLEARN_CLOUDSIM_JAR", "").strip()
        self._jar_path = Path(jar_env) if jar_env else self._resolve_default_jar()

    def _resolve_default_jar(self) -> Path:
        candidate = self.repo_root / "cloudsim-backbone" / "target" / "cloudsim-backbone.jar"
        if candidate.exists():
            return candidate
        versioned_candidate = self.repo_root / "cloudsim-backbone" / "target" / "cloudsim-backbone-1.0.0.jar"
        if versioned_candidate.exists():
            return versioned_candidate
        tmp_candidate = Path("/tmp/cloudlearn-cloudsim-backbone/target/cloudsim-backbone.jar")
        if tmp_candidate.exists():
            return tmp_candidate
        tmp_versioned = Path("/tmp/cloudlearn-cloudsim-backbone/cloudsim-backbone-1.0.0.jar")
        if tmp_versioned.exists():
            return tmp_versioned
        target_dir = self.repo_root / "cloudsim-backbone" / "target"
        if target_dir.exists():
            jars = sorted(
                [
                    path
                    for path in target_dir.glob("*.jar")
                    if "sources" not in path.name and "javadoc" not in path.name and "original" not in path.name
                ],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if jars:
                return jars[0]
        tmp_root = Path("/tmp/cloudlearn-cloudsim-backbone")
        if tmp_root.exists():
            jars = sorted(
                [
                    path
                    for path in tmp_root.glob("*.jar")
                    if "sources" not in path.name and "javadoc" not in path.name and "original" not in path.name
                ],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if jars:
                return jars[0]
        tmp_dir = Path("/tmp/cloudlearn-cloudsim-backbone/target")
        if tmp_dir.exists():
            jars = sorted(
                [
                    path
                    for path in tmp_dir.glob("*.jar")
                    if "sources" not in path.name and "javadoc" not in path.name and "original" not in path.name
                ],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if jars:
                return jars[0]
        return candidate

    @property
    def base_url(self) -> str:
        return self._base_url

    def _set_base_url(self, url: str) -> None:
        self._base_url = url.rstrip("/")

    def _request(self, method: str, path: str, payload: dict | None = None, timeout: int = 8) -> dict:
        if not self._base_url:
            raise RuntimeError("CloudSim backbone URL not configured")
        url = f"{self._base_url}{path}"
        headers = {"Content-Type": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8") or "{}"
                return json.loads(body)
        except Exception:
            curl = shutil.which("curl")
            if not curl:
                raise
            curl_args = [curl, "-sS", "-X", method.upper(), url, "-H", "Content-Type: application/json"]
            if data is not None:
                curl_args.extend(["--data-binary", "@-"])
                completed = subprocess.run(curl_args, input=data, capture_output=True, timeout=timeout)
            else:
                completed = subprocess.run(curl_args, capture_output=True, timeout=timeout)
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or b"").decode("utf-8", errors="ignore") or "CloudSim HTTP request failed")
            body = (completed.stdout or b"{}").decode("utf-8") or "{}"
            return json.loads(body)

    def _probe(self) -> bool:
        if not self._base_url:
            return False
        try:
            payload = self._request("GET", "/health", timeout=2)
        except Exception:
            return False
        return str(payload.get("status", "")).lower() == "ok"

    def available(self) -> bool:
        return self._probe()

    def _launch_if_possible(self) -> bool:
        if self._explicit_base_url:
            return self._probe()
        if self._probe():
            return True
        if not self._jar_path.exists():
            return False
        with self._lock:
            if self._process and self._process.poll() is None:
                return self._probe()
            env = os.environ.copy()
            env.setdefault("CLOUDLEARN_CLOUDSIM_HOST", self._host)
            env.setdefault("CLOUDLEARN_CLOUDSIM_PORT", str(self._port))
            try:
                self._process = subprocess.Popen(
                    ["java", "-jar", str(self._jar_path)],
                    cwd=str(self.repo_root),
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                return False
        deadline = time.time() + 8
        while time.time() < deadline:
            if self._probe():
                if not self._base_url:
                    self._set_base_url(f"http://{self._host}:{self._port}")
                return True
            time.sleep(0.4)
        return self._probe()

    def ensure_running(self) -> bool:
        if self._probe():
            return True
        return self._launch_if_possible()

    def list_spaces(self) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        return self._request("GET", "/spaces")

    def get_space(self, space_id: str) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        return self._request("GET", f"/spaces/{urllib.parse.quote(space_id, safe='')}")

    def create_space(self, payload: dict) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        return self._request("POST", "/spaces", payload)

    def switch_space(self, space_id: str) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        return self._request("POST", f"/spaces/{urllib.parse.quote(space_id, safe='')}/switch", {})

    def pause_space(self, space_id: str) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        return self._request("POST", f"/spaces/{urllib.parse.quote(space_id, safe='')}/pause", {})

    def resume_space(self, space_id: str) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        return self._request("POST", f"/spaces/{urllib.parse.quote(space_id, safe='')}/resume", {})

    def archive_space(self, space_id: str) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        return self._request("POST", f"/spaces/{urllib.parse.quote(space_id, safe='')}/archive", {})

    def delete_space(self, space_id: str) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        return self._request("DELETE", f"/spaces/{urllib.parse.quote(space_id, safe='')}")

    def reconcile(self, space_id: str | None = None) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        if space_id:
            return self._request("POST", f"/spaces/{urllib.parse.quote(space_id, safe='')}/reconcile", {})
        return self._request("GET", "/summary")

    def current(self) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        summary = self._request("GET", "/summary")
        spaces = self._request("GET", "/spaces")
        active_id = summary.get("active_space_id", "")
        active_space = None
        for item in spaces.get("spaces", []):
            if item.get("space_id") == active_id:
                active_space = item
                break
        return {"summary": summary, "active_space": active_space}

    def summary(self) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        return self._request("GET", "/summary")

    def events(self) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        return self._request("GET", "/events")

    def record_event(self, space_id: str, payload: dict) -> dict:
        if not self.ensure_running():
            raise RuntimeError("CloudSim backbone unavailable")
        return self._request("POST", f"/spaces/{urllib.parse.quote(space_id, safe='')}/events", payload)


class RuntimeManager:
    def __init__(self, kernel: SimulationKernel):
        self.kernel = kernel
        self._bootstrap_lock = threading.RLock()
        self._bootstrap_thread: threading.Thread | None = None

    def host_os(self) -> str:
        return str(os.environ.get("CLOUDLEARN_PARENT_OS") or platform.system()).strip().lower()

    def supported_backends(self) -> list[str]:
        host_os = self.host_os()
        if host_os in {"windows", "darwin"}:
            return ["multipass"]
        return ["multipass", "lxd"]

    def cli_for(self, backend: str) -> str | None:
        backend = (backend or "").strip().lower()
        if backend == "lxd":
            return shutil.which("lxc")
        if backend == "multipass":
            return shutil.which("multipass")
        return None

    def inside_container(self) -> bool:
        return Path("/.dockerenv").exists() or "docker" in (Path("/proc/1/cgroup").read_text(errors="ignore").lower() if Path("/proc/1/cgroup").exists() else "")

    def lxd_cli(self) -> str | None:
        return self.cli_for("lxd")

    def multipass_cli(self) -> str | None:
        return self.cli_for("multipass")

    def docker_cli(self) -> str | None:
        return self.lxd_cli()

    def bridge_base_url(self) -> str:
        return str(os.environ.get("CLOUDLEARN_RUNTIME_BRIDGE_URL") or "").strip().rstrip("/")

    def bridge_token(self) -> str:
        return str(os.environ.get("CLOUDLEARN_RUNTIME_BRIDGE_TOKEN") or "").strip()

    def bridge_enabled(self) -> bool:
        return bool(self.bridge_base_url())

    def _bridge_request(self, method: str, path: str, payload: dict | None = None, timeout: int = 60) -> dict:
        base_url = self.bridge_base_url()
        if not base_url:
            raise RuntimeError("Runtime bridge is not configured")
        url = f"{base_url}/{path.lstrip('/')}"
        headers = {"Content-Type": "application/json"}
        token = self.bridge_token()
        if token:
            headers["X-CloudLearn-Bridge-Token"] = token
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                if not body:
                    return {}
                parsed = json.loads(body)
                return parsed if isinstance(parsed, dict) else {"result": parsed}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
            try:
                parsed = json.loads(body) if body else {}
            except Exception:
                parsed = {}
            if isinstance(parsed, dict) and parsed:
                parsed.setdefault("status_code", exc.code)
                return parsed
            return {"error": body or exc.reason or str(exc), "status_code": exc.code}
        except Exception as exc:
            return {"error": str(exc), "status_code": 503}

    def bridge_status(self, backend: str | None = None) -> dict | None:
        if not self.bridge_enabled():
            return None
        path = "/status"
        if backend:
            path += f"?backend={urllib.parse.quote(backend.strip().lower(), safe='')}"
        payload = self._bridge_request("GET", path, timeout=30)
        return payload if isinstance(payload, dict) else None

    def bridge_bootstrap(self, backend: str | None = None) -> dict | None:
        if not self.bridge_enabled():
            return None
        payload = {"backend": (backend or "").strip().lower()}
        response = self._bridge_request("POST", "/bootstrap", payload=payload, timeout=1800)
        return response if isinstance(response, dict) else None

    def bridge_ssh_identity(self) -> dict | None:
        if not self.bridge_enabled():
            return None
        response = self._bridge_request("GET", "/ssh-identity", timeout=30)
        return response if isinstance(response, dict) else None

    def run_backend(self, backend: str, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
        backend = (backend or "").strip().lower()
        if self.bridge_enabled():
            payload = {"backend": backend, "args": list(args), "timeout": int(timeout)}
            response = self._bridge_request("POST", "/run", payload=payload, timeout=max(30, timeout + 30))
            return subprocess.CompletedProcess(
                args=[backend, *args],
                returncode=int(response.get("returncode", 1)),
                stdout=str(response.get("stdout", "")),
                stderr=str(response.get("stderr", response.get("error", ""))),
            )
        binary = self.cli_for(backend)
        if not binary:
            raise RuntimeError(f"{backend or 'runtime'} is unavailable")
        try:
            return subprocess.run([binary, *args], capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as exc:
            return subprocess.CompletedProcess(args=[binary, *args], returncode=1, stdout="", stderr=str(exc))

    def available(self, backend: str | None = None) -> bool:
        if self.bridge_enabled():
            if backend:
                status = self.bridge_status(backend)
                return bool(status and status.get("available"))
            statuses = self.bridge_status()
            if isinstance(statuses, dict):
                if "backends" in statuses and isinstance(statuses["backends"], dict):
                    return any(bool(item.get("available")) for item in statuses["backends"].values() if isinstance(item, dict))
                return bool(statuses.get("available"))
            return False
        backends = [backend] if backend else self.supported_backends()
        for candidate in backends:
            binary = self.cli_for(candidate or "")
            if not binary:
                continue
            try:
                if candidate == "multipass":
                    completed = subprocess.run([binary, "list", "--format", "json"], capture_output=True, text=True, timeout=15)
                else:
                    completed = subprocess.run([binary, "info"], capture_output=True, text=True, timeout=15)
            except Exception:
                continue
            if completed.returncode == 0:
                return True
        return False

    def _backend_state(self, backend: str) -> dict:
        runtime_state = self.kernel.state.setdefault("runtime", {})
        runtime_state.setdefault("lxd", {})
        runtime_state.setdefault("multipass", {})
        state = runtime_state.setdefault(backend, {})
        state.setdefault("status", "missing")
        state.setdefault("message", "")
        state.setdefault("mode", "auto")
        state.setdefault("last_checked", "")
        state.setdefault("started_at", "")
        state.setdefault("finished_at", "")
        state.setdefault("helper", backend)
        state.setdefault("label", backend.upper())
        return state

    def _bootstrap_commands(self, backend: str) -> tuple[str, list[list[str]], str]:
        backend = (backend or "").strip().lower()
        host_os = self.host_os()
        if self.inside_container():
            if backend == "multipass":
                return (
                    "manual-multipass",
                    [],
                    "Multipass must be available on the host. CloudLearn cannot install host runtimes from inside the app container.",
                )
            if backend == "lxd":
                return (
                    "manual-lxd",
                    [],
                    "LXD must be available on the host. CloudLearn cannot install host runtimes from inside the app container.",
                )
        if backend == "multipass":
            if host_os == "windows":
                return ("winget-multipass", [["winget", "install", "Canonical.Multipass"]], "Multipass is required for EC2 instances on Windows. Install Multipass and retry.")
            if host_os == "darwin":
                return ("brew-multipass", [["brew", "install", "--cask", "multipass"]], "Multipass is required for EC2 instances on macOS. Install Multipass and retry.")
            if host_os == "linux":
                return ("snap-multipass", [["sh", "-lc", "sudo snap install multipass"]], "Multipass is required for EC2 instances. Install Multipass and retry.")
            return ("manual-multipass", [], "Multipass is required for EC2 instances. Install Multipass and retry.")
        if backend == "lxd":
            if host_os == "linux":
                return (
                    "snap-lxd",
                    [["sh", "-lc", "sudo snap install lxd && sudo usermod -aG lxd \"$(id -un)\" && sudo lxd init --auto"]],
                    "LXD is required for EC2 instances on Linux. Install and initialize LXD on the host, then retry.",
                )
            return ("manual-lxd", [], "LXD is required for EC2 instances on Linux hosts. Install and initialize LXD on a Linux host, then retry.")
        return ("manual", [], f"{backend or 'Multipass or LXD runtime'} is required for EC2 instances. Install and retry.")

    def bootstrap_target(self, backend: str | None = None) -> dict:
        backend = (backend or self.preferred_backend() or "multipass").strip().lower()
        helper, commands, message = self._bootstrap_commands(backend)
        label = "Multipass" if backend == "multipass" else "LXD" if backend == "lxd" else backend.upper()
        return {
            "backend": backend,
            "helper": helper,
            "label": label,
            "message": message,
            "commands": commands,
        }

    def bootstrap_status(self, backend: str | None = None) -> dict:
        if self.bridge_enabled():
            if backend:
                payload = self.bridge_status(backend)
                if isinstance(payload, dict):
                    payload.setdefault("host_os", self.host_os())
                    return payload
            payload = self.bridge_status()
            if isinstance(payload, dict):
                payload.setdefault("host_os", self.host_os())
                return payload
        runtime_state = self.kernel.state.setdefault("runtime", {})
        runtime_state.setdefault("lxd", {})
        runtime_state.setdefault("multipass", {})
        if backend:
            state = self._backend_state(backend)
            status = copy.deepcopy(state)
            status["available"] = self.available(backend)
            target = self.bootstrap_target(backend)
            status["helper"] = target["helper"]
            status["label"] = target["label"]
            if status["available"]:
                status["status"] = "ready"
                status["message"] = f"{target['label']} is available."
            else:
                status["message"] = status.get("message") or target["message"]
                status["target"] = {
                    "helper": target["helper"],
                    "label": target["label"],
                    "message": target["message"],
                }
            status["host_os"] = self.host_os()
            return status

        backends = {}
        for candidate in ("multipass", "lxd"):
            item = self.bootstrap_status(candidate)
            backends[candidate] = item
        preferred = self.preferred_backend()
        return {
            "available": any(item.get("available") for item in backends.values()),
            "host_os": self.host_os(),
            "preferred_backend": preferred,
            "backends": backends,
        }

    def _run_bootstrap_command(self, args: list[str], timeout: int = 1200) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)

    def _apply_bootstrap_result(self, backend: str, result: subprocess.CompletedProcess) -> None:
        runtime_state = self.kernel.state.setdefault("runtime", {})
        state = self._backend_state(backend)
        output = (result.stdout or "") + (result.stderr or "")
        state["last_checked"] = _now()
        state["message"] = output[-1000:].strip()
        state["status"] = "ready" if result.returncode == 0 else "error"
        target = self.bootstrap_target(backend)
        state["helper"] = target["helper"]
        state["label"] = target["label"]
        self.kernel.persist()

    def _bootstrap_worker(self) -> None:
        try:
            with self._bootstrap_lock:
                for backend in self.supported_backends():
                    state = self._backend_state(backend)
                    target = self.bootstrap_target(backend)
                    state["status"] = "ready" if self.available(backend) else "manual"
                    state["helper"] = target["helper"]
                    state["label"] = target["label"]
                    state["message"] = target["message"]
                    state["started_at"] = _now()
                    state["last_checked"] = _now()
                    state["finished_at"] = _now()
                self.kernel.persist()
            self.kernel.persist()
        finally:
            with self._bootstrap_lock:
                self._bootstrap_thread = None

    def start_bootstrap(self) -> dict:
        with self._bootstrap_lock:
            for backend in self.supported_backends():
                state = self._backend_state(backend)
                target = self.bootstrap_target(backend)
                state["helper"] = target["helper"]
                state["label"] = target["label"]
                state["status"] = "ready" if self.available(backend) else "manual"
                state["message"] = target["message"]
                state["started_at"] = _now()
                state["last_checked"] = _now()
                state["finished_at"] = _now()
            self.kernel.persist()
            return self.bootstrap_status()

    def preferred_backend(self) -> str:
        for backend in ("multipass", "lxd"):
            if self.available(backend):
                return backend
        return "multipass" if self.host_os() in {"windows", "darwin"} else "lxd"


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
        self.firestore = FirestoreEngine(self.store, self.kernel)
        self.cloudsim = CloudSimBridge(self.kernel, Path(state_path).resolve().parent)

    @property
    def state(self) -> dict:
        return self.kernel.state

    def persist(self) -> None:
        self.kernel.persist()

    def record_event(self, event: str, detail: dict | None = None) -> None:
        detail = detail or {}
        self.kernel.record_event(event, detail)
        try:
            space = self.get_active_space()
            if space and space.get("space_id"):
                self.cloudsim.record_event(space["space_id"], {"event": event, "detail": detail, "space_id": space["space_id"], "at": _now()})
        except Exception:
            active = self.kernel.get_active_space()
            if active and active.get("space_id"):
                cloudsim = active.setdefault("cloudsim", {"summary": {}, "events": [], "last_tick": ""})
                cloudsim.setdefault("events", []).append({"event": event, "detail": detail, "space_id": active["space_id"], "at": _now()})
                active.setdefault("events", []).append({"event": event, "detail": detail, "at": _now()})
                self.persist()

    def activate_pack(self, pack_id: str) -> dict:
        return self.kernel.activate_pack(pack_id)

    def ensure_capability(self, path: str) -> None:
        self.kernel.ensure_capability(path)

    def catalog(self) -> list[dict]:
        return self.kernel.catalog()

    def list_spaces(self) -> list[dict]:
        return self.kernel.list_spaces()

    def get_active_space(self) -> dict | None:
        return self.kernel.get_active_space()

    def estimate_space_cost(self, spec: dict | None = None) -> dict:
        return self.kernel.estimate_space_cost(spec)

    def create_space(self, spec: dict) -> dict:
        space = self.kernel.create_space(spec)
        fallback_summary = {
            "space_id": space.get("space_id", ""),
            "name": space.get("name", ""),
            "provider": space.get("provider", "aws"),
            "status": space.get("status", "running"),
            "active_region": space.get("active_region", "us-east-1"),
            "cloudsim_engine": "CloudSim Plus 8.5.7 (local fallback)",
            "cloudsim_runtime_id": space.get("cloudsim_runtime_id", ""),
            "datacenters": 1,
            "hosts": max(1, (int(space.get("runtime_count", 0)) + int(space.get("ec2_count", 0)) + int(space.get("lambda_count", 0)) + int(space.get("rds_count", 0)) + int(space.get("sqs_count", 0)) + int(space.get("dynamodb_count", 0)) + 1) // 2),
            "vms": max(1, int(space.get("runtime_count", 0)) + int(space.get("ec2_count", 0)) + int(space.get("lambda_count", 0)) + int(space.get("rds_count", 0)) + int(space.get("sqs_count", 0)) + int(space.get("dynamodb_count", 0))),
            "cloudlets": max(1, int(space.get("runtime_count", 0)) + int(space.get("ec2_count", 0)) + int(space.get("lambda_count", 0)) + int(space.get("rds_count", 0)) + int(space.get("sqs_count", 0)) + int(space.get("dynamodb_count", 0)) * 2),
            "finished_cloudlets": 0,
            "runtime_count": int(space.get("runtime_count", 0)),
            "ec2_count": int(space.get("ec2_count", 0)),
            "lambda_count": int(space.get("lambda_count", 0)),
            "rds_count": int(space.get("rds_count", 0)),
            "sqs_count": int(space.get("sqs_count", 0)),
            "dynamodb_count": int(space.get("dynamodb_count", 0)),
            "last_tick": _now(),
            "updated_at": space.get("updated_at", _now()),
            "created_at": space.get("created_at", _now()),
            "simulation_state": "local-fallback",
        }
        space["cloudsim"] = {"summary": fallback_summary, "events": [], "last_tick": fallback_summary["last_tick"]}
        try:
            remote = self.cloudsim.create_space(space)
            if isinstance(remote, dict):
                remote_space = remote.get("space") or {}
                remote_summary = remote.get("summary") or {}
                space["cloudsim"] = {
                    "summary": copy.deepcopy(remote_summary),
                    "events": copy.deepcopy(remote_space.get("cloudsim", {}).get("events", [])) if isinstance(remote_space, dict) else [],
                    "last_tick": remote_summary.get("last_tick", remote_space.get("last_tick", "")) if isinstance(remote_summary, dict) else "",
                }
                if remote_space.get("cloudsim_runtime_id"):
                    space["cloudsim_runtime_id"] = remote_space["cloudsim_runtime_id"]
                self.kernel.state.setdefault("spaces", {}).setdefault("spaces", {})[space["space_id"]] = space
                self.persist()
        except Exception:
            pass
        return space

    def switch_space(self, space_id: str) -> dict:
        space = self.kernel.switch_space(space_id)
        try:
            remote = self.cloudsim.switch_space(space_id)
            if isinstance(remote, dict):
                self.kernel.state.setdefault("spaces", {}).setdefault("spaces", {})[space_id] = remote.get("space", space)
                self.persist()
                return self.kernel.state["spaces"]["spaces"][space_id]
        except Exception:
            pass
        return space

    def pause_space(self, space_id: str) -> dict:
        space = self.kernel.pause_space(space_id)
        try:
            self.cloudsim.pause_space(space_id)
        except Exception:
            pass
        return space

    def resume_space(self, space_id: str) -> dict:
        space = self.kernel.resume_space(space_id)
        try:
            self.cloudsim.resume_space(space_id)
        except Exception:
            pass
        return space

    def archive_space(self, space_id: str) -> dict:
        space = self.kernel.archive_space(space_id)
        try:
            self.cloudsim.archive_space(space_id)
        except Exception:
            pass
        return space

    def delete_space(self, space_id: str) -> None:
        self.kernel.delete_space(space_id)
        try:
            self.cloudsim.delete_space(space_id)
        except Exception:
            pass

    def cloudsim_current(self) -> dict:
        try:
            payload = self.cloudsim.current()
            summary = payload.get("summary") if isinstance(payload, dict) else {}
            if not isinstance(summary, dict):
                summary = {}
            cloudsim_state = self.kernel.state.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})
            summary.setdefault("last_reconcile_at", cloudsim_state.get("last_reconcile_at", ""))
            if not summary.get("last_reconcile_at"):
                summary["last_reconcile_at"] = cloudsim_state.get("last_reconcile_at", "")
            payload["summary"] = summary
            return payload
        except Exception:
            spaces_state = self.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
            active_id = spaces_state.get("active_space_id", "")
            active = spaces_state.get("spaces", {}).get(active_id, {}) if active_id else {}
            summary = copy.deepcopy(self.kernel.state.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""}).get("summary", {}))
            summary["active_space_id"] = active_id
            summary["active_space_name"] = active.get("name", "")
            summary["spaces"] = len(spaces_state.get("spaces", {}))
            summary["last_reconcile_at"] = self.kernel.state.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""}).get("last_reconcile_at", "")
            return {"summary": summary, "active_space": active}

    def cloudsim_summary(self) -> dict:
        try:
            summary = self.cloudsim.summary()
            if not isinstance(summary, dict):
                summary = {}
            cloudsim_state = self.kernel.state.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})
            if not summary.get("last_reconcile_at"):
                summary["last_reconcile_at"] = cloudsim_state.get("last_reconcile_at", "")
            return {"summary": summary}
        except Exception:
            spaces_state = self.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
            cloudsim = self.kernel.state.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})
            cloudsim["summary"]["spaces"] = len(spaces_state.get("spaces", {}))
            cloudsim["summary"]["active_space_id"] = spaces_state.get("active_space_id", "")
            cloudsim["summary"]["max_spaces"] = int(spaces_state.get("settings", {}).get("max_spaces", 6))
            return {"summary": copy.deepcopy(cloudsim.get("summary", {}))}

    def cloudsim_reconcile(self) -> dict:
        try:
            payload = self.cloudsim.reconcile()
            if isinstance(payload, dict):
                cloudsim = self.kernel.state.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})
                summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else payload
                cloudsim["summary"].update(copy.deepcopy(summary))
                cloudsim["last_reconcile_at"] = summary.get("last_reconcile_at", _now())
                cloudsim.setdefault("events", []).append({"event": "cloudsim.reconcile", "at": cloudsim["last_reconcile_at"], "spaces": summary.get("spaces", 0)})
                self.persist()
            return payload
        except Exception:
            cloudsim = self.kernel.state.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})
            spaces_state = self.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
            cloudsim["summary"]["spaces"] = len(spaces_state.get("spaces", {}))
            cloudsim["summary"]["active_space_id"] = spaces_state.get("active_space_id", "")
            cloudsim["summary"]["max_spaces"] = int(spaces_state.get("settings", {}).get("max_spaces", 6))
            cloudsim["last_reconcile_at"] = _now()
            cloudsim.setdefault("events", []).append({"event": "cloudsim.reconcile", "at": _now(), "spaces": len(spaces_state.get("spaces", {}))})
            self.persist()
            return {"message": "CloudSim reconcile complete", "summary": copy.deepcopy(cloudsim["summary"]), "last_reconcile_at": cloudsim["last_reconcile_at"]}

    def cloudsim_events(self) -> dict:
        try:
            return self.cloudsim.events()
        except Exception:
            cloudsim = self.kernel.state.setdefault("cloudsim", {"summary": {}, "events": [], "last_reconcile_at": ""})
            return {"events": copy.deepcopy(cloudsim.get("events", [])), "count": len(cloudsim.get("events", []))}
