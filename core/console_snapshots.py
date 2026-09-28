"""console-next Snapshots (§12.6, P2 slice 1) — capture / list / restore of the
console's IN-PROCESS backend store state.

WHAT THIS IS
------------
A snapshot bundles a point-in-time, JSON-serialisable capture of the control-plane
STATE held by the console facades' in-process stores (§12.6 "Control plane" row):

    Secrets  → core/console_secrets._STORE   (InMemoryKvStore.secrets)
    KMS      → core/console_kms._STORE        (InMemoryKeyStore.keys/aliases/material)
    Messaging→ core/console_messaging._STORE  (InMemoryMessagingStore.queues/topics)
    SQL/RDS  → core/console_sql._STORE        (InMemorySqlStore.db_instances/snapshots)

Each store is serialised to a plain dict; the manifest is held in memory (a list of
generations, newest kept, with a note + an approximate byte size). `capture()` makes a
new immutable generation, `list()` returns the manifest, `restore(id)` writes the
captured dicts back onto the live stores (in place, so the module singletons the
facades hold keep working).

HONEST CONSTRAINTS (surfaced in the UI — §12.6, §10, §14.5)
-----------------------------------------------------------
- This is the CONTROL-PLANE-FIRST slice: it captures the in-process store metadata
  and the message/secret/key state those stores hold in memory. It does NOT yet
  capture the heavier "full data" backends behind their seams — real MinIO objects,
  a real MySQL/Postgres data dir, PGlite rows, Docker/LXD volumes (§12.6 table). RDS
  in particular: the instance METADATA is captured, but the live SQL rows (the
  SqlStore data plane / sqlite3·PGlite connections) are a later fidelity slice
  (§14.5). That richer per-backend "full data" capture is a follow-up.
- FORK (§12.6) is now built (P2 slice 2): fork(snap_id, name) creates a new NAMED
  branch of state — a fresh snapshot generation seeded from the parent snapshot's
  captured payload, tagged {kind:"fork", parent:<snap_id>}. It reuses the capture/
  restore internals (same store table, same deep-copy discipline). list() surfaces
  the lineage (kind + parent) so the UI can draw the branch. REPLAY lives in the
  glass-box path (routes/console_next.py), not here — capture/list/restore/fork
  are the state-registry primitives.

DESIGN: additive, commonality-first (§15.2) — there is NO if(substrate) branching.
The registry just walks a table of (store singleton, serialiser, loader) tuples; each
facade exposes the same `store()` accessor, so the same code runs on every substrate.
"""

from __future__ import annotations

import base64
import copy
import json
import time
import uuid
from typing import Any, Callable

# ── per-store (de)serialisers ────────────────────────────────────────────────
# Each store is captured to a JSON-safe dict and loaded back IN PLACE (mutating the
# live singleton the facade holds, never rebinding it). All state is deep-copied on
# both capture and restore so a snapshot never aliases live state.


def _dump_secrets(store) -> dict:
    return {"secrets": copy.deepcopy(store.secrets)}


def _load_secrets(store, data: dict) -> None:
    store.secrets.clear()
    store.secrets.update(copy.deepcopy(data.get("secrets") or {}))


def _dump_kms(store) -> dict:
    # `material` is raw bytes (the key material) — base64 it to stay JSON-safe.
    material = {k: base64.b64encode(v).decode("ascii") for k, v in store.material.items()}
    return {
        "keys": copy.deepcopy(store.keys),
        "aliases": copy.deepcopy(store.aliases),
        "material_b64": material,
    }


def _load_kms(store, data: dict) -> None:
    store.keys.clear()
    store.keys.update(copy.deepcopy(data.get("keys") or {}))
    store.aliases.clear()
    store.aliases.update(copy.deepcopy(data.get("aliases") or {}))
    store.material.clear()
    for k, b64 in (data.get("material_b64") or {}).items():
        store.material[k] = base64.b64decode(b64)


def _dump_messaging(store) -> dict:
    return {
        "queues": copy.deepcopy(store.queues),
        "topics": copy.deepcopy(store.topics),
        "clock": store._clock,
    }


def _load_messaging(store, data: dict) -> None:
    store.queues.clear()
    store.queues.update(copy.deepcopy(data.get("queues") or {}))
    store.topics.clear()
    store.topics.update(copy.deepcopy(data.get("topics") or {}))
    store._clock = data.get("clock")


def _dump_sql(store) -> dict:
    # Control-plane only: instance + snapshot METADATA. The live SQL data plane
    # (sqlite3 / PGlite connections holding the rows) is a later fidelity slice.
    return {
        "db_instances": copy.deepcopy(store.db_instances),
        "snapshots": copy.deepcopy(store.snapshots),
    }


def _load_sql(store, data: dict) -> None:
    store.db_instances.clear()
    store.db_instances.update(copy.deepcopy(data.get("db_instances") or {}))
    store.snapshots.clear()
    store.snapshots.update(copy.deepcopy(data.get("snapshots") or {}))


# ── the store table (id → how to reach + (de)serialise it) ───────────────────
# `getter` is a lazy accessor so importing this module never imports the facades
# (and never touches ctx state) until a snapshot is actually taken.
_StoreSpec = tuple[str, Callable[[], Any], Callable[[Any], dict], Callable[[Any, dict], None]]


def _store_specs() -> list[_StoreSpec]:
    from core import console_kms, console_messaging, console_secrets, console_sql
    return [
        ("secrets", console_secrets.store, _dump_secrets, _load_secrets),
        ("kms", console_kms.store, _dump_kms, _load_kms),
        ("messaging", console_messaging.store, _dump_messaging, _load_messaging),
        ("sql", console_sql.store, _dump_sql, _load_sql),
    ]


class SnapshotError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class SnapshotRegistry:
    """In-memory registry of console state snapshots. Newest-first ordering.

    A snapshot is `{id, name, created, note, stores:{store_id: dict}, size}`. Held
    in memory only (this is a sandbox; nothing leaves the workspace — §12.7). A soft
    cap keeps the buffer bounded; oldest generations drop when it's exceeded.
    """

    def __init__(self, max_snapshots: int = 50) -> None:
        self._snaps: dict[str, dict] = {}
        self._order: list[str] = []  # newest-first
        self._max = max_snapshots

    # ── capture ──────────────────────────────────────────────────────────
    def capture(self, name: str = "", note: str = "") -> dict:
        stores: dict[str, dict] = {}
        for store_id, getter, dump, _load in _store_specs():
            try:
                stores[store_id] = dump(getter())
            except Exception as e:  # a store that can't serialise must not sink the snapshot
                stores[store_id] = {"__error__": str(e)}
        return self._store(name=name, note=note, stores=stores)

    def _store(self, *, name: str, note: str, stores: dict[str, dict],
               kind: str = "snapshot", parent: str | None = None) -> dict:
        """Persist a new generation from an already-built `stores` payload.

        Shared by capture() (payload from the live stores) and fork() (payload
        deep-copied from the parent snapshot) — one code path, one id/size/evict
        discipline, no branching on substrate."""
        snap_id = ("fork_" if kind == "fork" else "snap_") + uuid.uuid4().hex[:12]
        size = len(json.dumps(stores, default=str).encode("utf-8"))
        record = {
            "id": snap_id,
            "name": name or snap_id,
            "created": time.time(),
            "note": note or "",
            "stores": stores,
            "size": size,
            "kind": kind,
            "parent": parent,
        }
        self._snaps[snap_id] = record
        self._order.insert(0, snap_id)
        self._evict()
        return self._meta(record)

    # ── fork ───────────────────────────────────────────────────────────────
    def fork(self, snap_id: str, name: str = "") -> dict:
        """Create a new NAMED branch of state seeded from an existing snapshot.

        The fork is a fresh generation whose captured payload is a deep copy of
        the parent's — an independent line of state the user can restore into and
        evolve without touching the parent. Reuses the capture/restore internals:
        the same `stores` payload the parent holds is what `restore()` would load,
        so a fork restores byte-for-byte to the parent's captured point."""
        parent = self._snaps.get(snap_id)
        if parent is None:
            raise SnapshotError(f"snapshot {snap_id!r} not found", status=404)
        stores = copy.deepcopy(parent["stores"])
        default_name = f"{parent.get('name') or snap_id}-fork"
        note = f"forked from {parent.get('name') or snap_id} ({snap_id})"
        return self._store(name=name or default_name, note=note,
                           stores=stores, kind="fork", parent=snap_id)

    def _evict(self) -> None:
        while len(self._order) > self._max:
            old = self._order.pop()
            self._snaps.pop(old, None)

    # ── list ─────────────────────────────────────────────────────────────
    def list(self) -> list[dict]:
        """Manifest (newest-first) — metadata only, never the captured payload."""
        return [self._meta(self._snaps[i]) for i in self._order if i in self._snaps]

    # ── restore ──────────────────────────────────────────────────────────
    def restore(self, snap_id: str) -> dict:
        record = self._snaps.get(snap_id)
        if record is None:
            raise SnapshotError(f"snapshot {snap_id!r} not found", status=404)
        restored: list[str] = []
        for store_id, getter, _dump, load in _store_specs():
            data = record["stores"].get(store_id)
            if not isinstance(data, dict) or "__error__" in data:
                continue
            load(getter(), data)
            restored.append(store_id)
        return {"restored": True, "id": snap_id, "stores": restored}

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _meta(record: dict) -> dict:
        return {
            "id": record["id"],
            "name": record["name"],
            "created": record["created"],
            "note": record["note"],
            "size": record["size"],
            "stores": sorted(record["stores"].keys()),
            "kind": record.get("kind", "snapshot"),
            "parent": record.get("parent"),
        }


# module singleton — the console's snapshot registry
REGISTRY = SnapshotRegistry()


def capture(name: str = "", note: str = "") -> dict:
    return REGISTRY.capture(name=name, note=note)


def list_snapshots() -> list[dict]:
    return REGISTRY.list()


def restore(snap_id: str) -> dict:
    return REGISTRY.restore(snap_id)


def fork(snap_id: str, name: str = "") -> dict:
    return REGISTRY.fork(snap_id, name=name)
