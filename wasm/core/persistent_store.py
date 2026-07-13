# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Persistent backed substrate for the store seams (v2.4.0 Phase 0).

The conformance cores are substrate-free and persist through a store SEAM. Nano
uses the InMemory* seams; Pro/Max uses real backends (MinIO/Vault/Postgres). This
module provides a THIRD substrate — a file-backed (stdlib sqlite3) implementation
of every seam — that the parametrized conformance suite runs against as the
**anti-drift gate**: the SAME core, on a non-in-memory substrate, must produce
state that survives a fresh instance load. No external processes; Pro/Max later
swaps SqliteStateBackend for the real backend behind the identical seam.

Design: the cores already call `store.persist()` after mutations (and
`mirror_put`/`mirror_delete` for the object seam). Each Persistent* store keeps
the in-memory working dicts (so the core mutates them exactly as before) and
write-throughs the full state to sqlite on every mutation hook; a fresh instance
loads it back on init. Bytes (object bodies, key material) survive via a
bytes-aware JSON codec.
"""
from __future__ import annotations

import base64
import json
import sqlite3
from typing import Any

from core.object_store import InMemoryObjectStore
from core.kv_store import InMemoryKvStore
from core.nosql_store import InMemoryNoSqlStore
from core.kms_keystore import InMemoryKeyStore
from core.messaging_store import InMemoryMessagingStore
from core.iam_store import InMemoryIamStore
from core.azure_blob_core import AzureBlobStore
from core.gcp_firestore_core import FirestoreStore


# ── bytes-aware JSON codec ────────────────────────────────────────────────
def _enc(o: Any):
    if isinstance(o, (bytes, bytearray)):
        return {"__b64__": base64.b64encode(bytes(o)).decode()}
    raise TypeError(f"not JSON-serializable: {type(o)}")


def _hook(d: dict):
    if len(d) == 1 and "__b64__" in d:
        return base64.b64decode(d["__b64__"])
    return d


def _dumps(state: dict) -> str:
    return json.dumps(state, default=_enc)


def _loads(s: str) -> dict:
    return json.loads(s, object_hook=_hook)


class SqliteStateBackend:
    """A real, file-backed substrate (stdlib sqlite3). One row per store id holds
    that store's serialized state. `:memory:` gives a shared in-process DB for
    tests that only need write-through semantics without a temp file."""

    def __init__(self, path: str = ":memory:"):
        self.path = path
        # A single shared connection so `:memory:` persists across save/load.
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS store_state (id TEXT PRIMARY KEY, blob TEXT)")
        self._conn.commit()

    def save(self, store_id: str, state: dict) -> None:
        self._conn.execute("INSERT OR REPLACE INTO store_state VALUES (?, ?)",
                           (store_id, _dumps(state)))
        self._conn.commit()

    def load(self, store_id: str) -> dict:
        row = self._conn.execute(
            "SELECT blob FROM store_state WHERE id = ?", (store_id,)).fetchone()
        return _loads(row[0]) if row else {}


class _PersistentMixin:
    """Load the state attrs from the backend on init; save them on every mutation
    hook. `_STATE_ATTRS` names the working dicts that make up the store's state."""
    _STATE_ATTRS: tuple[str, ...] = ()

    def _pinit(self, backend: SqliteStateBackend, store_id: str) -> None:
        self._backend = backend
        self._sid = store_id
        saved = backend.load(store_id)
        for attr in self._STATE_ATTRS:
            if attr in saved:
                setattr(self, attr, saved[attr])

    def _save(self) -> None:
        # Some cores attach lazy namespace dicts to the store (e.g. the GCP IAM
        # core's gcp_service_accounts); serialize only the attrs that exist.
        self._backend.save(self._sid,
                           {a: getattr(self, a) for a in self._STATE_ATTRS if hasattr(self, a)})

    # cores call persist() after mutations → write-through.
    def persist(self) -> None:
        self._save()


# ── per-family backed stores ──────────────────────────────────────────────
class PersistentKvStore(_PersistentMixin, InMemoryKvStore):
    _STATE_ATTRS = ("secrets",)

    def __init__(self, backend: SqliteStateBackend, store_id: str = "kv"):
        InMemoryKvStore.__init__(self)
        self._pinit(backend, store_id)


class PersistentNoSqlStore(_PersistentMixin, InMemoryNoSqlStore):
    _STATE_ATTRS = ("tables",)

    def __init__(self, backend: SqliteStateBackend, store_id: str = "nosql"):
        InMemoryNoSqlStore.__init__(self)
        self._pinit(backend, store_id)


class PersistentMessagingStore(_PersistentMixin, InMemoryMessagingStore):
    _STATE_ATTRS = ("queues", "topics")

    def __init__(self, backend: SqliteStateBackend, store_id: str = "messaging"):
        InMemoryMessagingStore.__init__(self)
        self._pinit(backend, store_id)


class PersistentKeyStore(_PersistentMixin, InMemoryKeyStore):
    # engine is stateless logic (not persisted); keys/material/aliases are state.
    _STATE_ATTRS = ("keys", "material", "aliases")

    def __init__(self, backend: SqliteStateBackend, store_id: str = "kms"):
        InMemoryKeyStore.__init__(self)
        self._pinit(backend, store_id)


class PersistentIamStore(_PersistentMixin, InMemoryIamStore):
    # incl. the GCP IAM core's lazy namespace dicts (attached on first use).
    _STATE_ATTRS = ("users", "groups", "roles", "policies", "access_keys",
                    "gcp_service_accounts", "gcp_iam_policies")

    def __init__(self, backend: SqliteStateBackend, store_id: str = "iam"):
        InMemoryIamStore.__init__(self)
        self._pinit(backend, store_id)


class PersistentObjectStore(_PersistentMixin, InMemoryObjectStore):
    """The object seam mutates self.objects directly + calls mirror_put/delete
    (it does NOT call persist()), so we write-through on the seam methods."""
    _STATE_ATTRS = ("buckets", "objects")

    def __init__(self, backend: SqliteStateBackend, store_id: str = "objects"):
        InMemoryObjectStore.__init__(self)
        self._pinit(backend, store_id)

    def create_bucket(self, name: str, versioning: str = "Disabled") -> None:
        super().create_bucket(name, versioning)
        self._save()

    def mirror_put(self, bucket, key, data, content_type="application/octet-stream",
                   metadata=None) -> None:
        self._save()   # the core has already written the full entry to self.objects

    def mirror_delete(self, bucket, key) -> None:
        self._save()


class PersistentAzureBlobStore(_PersistentMixin, AzureBlobStore):
    """Durable Azure Blob (v2.5.0): the bespoke AzureBlobStore state (containers +
    blobs) persisted to the file-backed substrate. The core calls persist() after
    each blob put/delete; container create/delete are overridden to persist too."""
    _STATE_ATTRS = ("containers", "blobs")

    def __init__(self, backend: SqliteStateBackend, store_id: str = "azblob"):
        AzureBlobStore.__init__(self)
        self._pinit(backend, store_id)

    def create_container(self, name: str) -> None:
        super().create_container(name)
        self._save()

    def delete_container(self, name: str) -> None:
        super().delete_container(name)
        self._save()


class PersistentFirestoreStore(_PersistentMixin, FirestoreStore):
    """Durable Firestore (v2.5.0): the FirestoreStore has clean put/delete methods,
    so we persist on those — no core edits needed."""
    _STATE_ATTRS = ("documents",)

    def __init__(self, backend: SqliteStateBackend, store_id: str = "firestore"):
        FirestoreStore.__init__(self)
        self._pinit(backend, store_id)

    def put(self, rel: str, entry: dict) -> None:
        super().put(rel, entry)
        self._save()

    def delete(self, rel: str) -> None:
        super().delete(rel)
        self._save()
