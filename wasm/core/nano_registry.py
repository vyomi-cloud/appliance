# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Single in-context store registry (Fix #2, Python half).

ONE source of truth both the console adapter (providers/aws_core_adapter) and the
native-wire relay (core/aws_wire_router via its `stores=` seam) read/write — so a
resource created in the console is seen by the SDK/relay and vice-versa *within a
Pyodide context*. Cross-CONTEXT parity (console page ↔ relay page) is added on top by
nano_persist + the IndexedDB/BroadcastChannel sync.

ALL THREE CLOUDS: the AWS console adapter, the GCP console adapter, the Azure
console adapter AND the native-wire relay (AwsWireRouter via `stores=`) all draw
from this one registry — so a resource created in ANY console (UI) is seen by the
SDK/CLI/curl (relay) and vice-versa, for every service of every cloud. Keys match
the AwsWireRouter `stores=` attrs AND nano_persist's STORE_ATTRS, so nano_persist
captures/restores the whole set for cross-context + reload persistence.
"""
from __future__ import annotations

from core.object_store import InMemoryObjectStore
from core.nosql_store import InMemoryNoSqlStore
from core.kms_keystore import InMemoryKeyStore
from core.kv_store import InMemoryKvStore
from core.sql_store import InMemorySqlStore
from core.iam_store import InMemoryIamStore
from core.messaging_store import InMemoryMessagingStore
from core.gcp_firestore_core import FirestoreStore
from core.azure_blob_core import AzureBlobStore
from core.azure_cosmos_core import CosmosStore
from core.azure_queue_core import AzureQueueStore
from core.azure_arm_core import AzureArm
from core.nano_events import EventStore

_REG: dict | None = None


def _new_resource_store():
    """The generic catalog-CRUD store (backends.store.ResourceStore). It lives in
    the `wasm` package, not in `core`, so import it LAZILY + GUARDED: the console
    context (nano-boot) has `wasm` on sys.path and binds this as the ONE store its
    catalog CRUD + nano_persist both use; the native-wire RELAY context doesn't
    load the `wasm` package and doesn't need the catalog store, so a failed import
    simply omits the key (capture/restore tolerate a missing store). Falls back to
    a plain dict-backed shim if the class can't be imported, keeping the registry
    well-formed and still persistable (public `collections` dict)."""
    for mod in ("wasm.backends.store", "backends.store"):
        try:
            __import__(mod)
            import sys
            return sys.modules[mod].ResourceStore()
        except Exception:
            continue
    return None


def get() -> dict:
    """The shared store registry — a singleton per Pyodide context. Keys match the
    AwsWireRouter `stores=` names, nano_persist STORE_ATTRS, and the per-cloud
    console adapter store maps. One store per service, shared by UI + CLI/SDK/curl."""
    global _REG
    if _REG is None:
        _REG = {
            # ── AWS ──
            "s3":  InMemoryObjectStore(),
            "ddb": InMemoryNoSqlStore(),
            "kms": InMemoryKeyStore(),
            "sec": InMemoryKvStore(),
            "rds": InMemorySqlStore(),
            "iam": InMemoryIamStore(),
            "msg": InMemoryMessagingStore(),   # SHARED by sqs + sns (fan-out)
            # ── GCP ── (storage/firestore/kms/secretmanager/pubsub/iam/cloudsql)
            "gcs":     InMemoryObjectStore(),
            "gcp_fs":  FirestoreStore(),
            "gcp_kms": InMemoryKeyStore(),
            "gcp_sec": InMemoryKvStore(),
            "gcp_msg": InMemoryMessagingStore(),
            "gcp_iam": InMemoryIamStore(),
            "gcp_sql": InMemorySqlStore(),
            # ── Azure ── (blob/cosmos/keyvault secrets+keys/queue/servicebus)
            "az_blob":   AzureBlobStore(),
            "az_cosmos": CosmosStore(),
            "az_kvsec":  InMemoryKvStore(),
            "az_kvkeys": InMemoryKeyStore(),
            "az_queue":  AzureQueueStore(),
            "az_sb":     InMemoryMessagingStore(),   # Service Bus (router-only today)
            # ── cross-cloud ── per-resource cloudsim event / activity log. DURABLE
            # + bounded: recorded on every mutating dispatch; persisted + cross-tab
            # synced via nano_persist (public dict attr `by_resource`, union-merge).
            "events": EventStore(),
            # ── generic catalog CRUD + Azure ARM control plane ──
            # Both were previously built per-page inside Backends() with their state
            # in underscore attrs (ResourceStore._c, AzureArm._state) → NOT captured,
            # so second-level sub-resources + editable settings were LOST on reload.
            # Now they're registry-backed with PUBLIC dict attrs (ResourceStore
            # .collections, AzureArm.state) and listed in nano_persist.STORE_ATTRS,
            # so EVERYTHING created through the generic path (AWS /api/aws/sub/*
            # children + settings, GCP compute/vpc/functions/apigateway/eventarc
            # parents AND their record-kind children) and every Azure ARM resource +
            # ARM-core child (servicebus topics/subs, vnet peerings, slots) survives
            # a full page reload and cross-tab syncs. Backends() binds these SAME
            # instances (see backends/store.py).
            "resources": _new_resource_store(),   # generic catalog store (may be None in the relay)
            "az_arm":    AzureArm(),               # Azure ARM control plane (resources + ARM children)
        }
        # Drop a None `resources` so the registry stays {str: store} (the relay
        # context, which never loads the catalog store, simply has no such key).
        if _REG.get("resources") is None:
            _REG.pop("resources", None)
    return _REG
