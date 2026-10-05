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
from core.nano_events import EventStore

_REG: dict | None = None


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
        }
    return _REG
