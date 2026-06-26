"""KvStore — the data-plane seam for versioned secret storage (ADR-001).

The secret-management protocol logic (versioning, version stages, native wire
shapes) is substrate-independent and lives in core/secrets_core.py. THIS is the
seam it persists through, so the same handler runs on any substrate:

    Pro/Max : VaultKvBackedStore — appliance ctx dict + Vault KV v2 mirror
    Nano    : InMemoryKvStore — pure in-WASM (Pyodide); IndexedDB/OPFS later
    tests   : InMemoryKvStore

The store owns the one state dict the handler reads/writes — a namespaced
{name -> secret} map — plus persist/mirror hooks that default to no-ops. Nothing
here imports fastapi / boto3 / socket / hvac, so it loads under Pyodide.

Generic on purpose: AWS Secrets Manager maps here today; Azure Key Vault secrets
and GCP Secret Manager map onto the SAME store later (namespaced), exactly the
ADR-001 "one primitive, many clouds" model. The secret RECORD shape is owned by
the core (like NoSqlStore holds table dicts owned by dynamodb_core).
"""
from __future__ import annotations

from typing import Any

DEFAULT_ACCOUNT_ID = "123456789012"  # matches core.app_context.AWS_ACCOUNT_ID


class KvStore:
    """Base seam. In-memory by default; subclass to add a mirror / persistence."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID) -> None:
        self.secrets: dict[str, dict[str, Any]] = {}
        self.account_id = account_id

    # ── secret map accessors (the {name -> secret} dict) ──────────────
    def secret_exists(self, name: str) -> bool:
        return name in self.secrets

    def get_secret(self, name: str) -> dict | None:
        s = self.secrets.get(name)
        return s if isinstance(s, dict) else None

    def put_secret(self, name: str, secret: dict) -> None:
        self.secrets[name] = secret

    def drop_secret(self, name: str) -> None:
        self.secrets.pop(name, None)

    def names(self) -> list[str]:
        return sorted(self.secrets)

    # ── optional hooks (no-ops in the base) ───────────────────────────
    def persist(self) -> None:
        """Flush state to durable storage (appliance ctx in Pro/Max, IDB/OPFS in
        Nano later). The in-memory dict is the source of truth either way."""

    def mirror_put(self, name: str, secret: dict) -> None:
        """Best-effort write-through to an external backend (Vault KV v2)."""

    def mirror_delete(self, name: str) -> None:
        """Best-effort delete in the external mirror."""


class InMemoryKvStore(KvStore):
    """The Nano / test substrate: pure in-memory, zero external deps."""
