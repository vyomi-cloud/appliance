"""Nano store persistence + cross-context sync.

ONE mechanism for every service of every cloud: serialize the in-WASM stores to a
JSON-safe snapshot and restore them. This is the foundation for:

  • Fix #1 (persistence): on boot, restore the snapshot from the `nano-spaces`
    IndexedDB; after each mutation, capture + save it → state survives logout/login.
  • Fix #2 (console↔SDK parity): both contexts persist to + rehydrate from the SAME
    snapshot (and notify each other via BroadcastChannel), so a resource created in
    the console is seen by the SDK/relay and vice-versa.

Design: stores keep their whole state in PUBLIC dict attrs (buckets/tables/keys/
secrets/queues+topics/db_instances/…) and keep live/unpicklable things (`_conns`,
PGlite handles) under `_`-prefixed attrs. So a generic `vars()`-minus-underscore
capture covers every store with no per-class code. Bytes (S3 object bodies) ride a
base64 codec. The SQL DATA plane (rows) isn't in vars() — it lives in live
connections — so SqlStore instances are dumped per-DB via sqlite `iterdump()` and
replayed on restore (keyed by DB id → multi-instance safe).
"""
from __future__ import annotations

import base64
import copy
import json

_B64 = "__b64__"

# Every store the AwsWireRouter owns (AWS + GCP + Azure). Keyed names match the
# router attrs AND the shared-registry keys (nano_registry), so one snapshot maps
# cleanly onto either the router or the console adapter's registry.
STORE_ATTRS = [
    "s3", "ddb", "kms", "sec", "rds", "iam", "msg", "logs", "elbv2", "kinesis",
    "gcs", "gcp_fs", "gcp_kms", "gcp_sec", "gcp_msg", "gcp_iam", "gcp_sql", "gcp_ar",
    "az_blob", "az_cosmos", "az_kvsec", "az_kvkeys", "az_queue", "az_sb",
    "apigwv2",  # API Gateway V2 (core/apigatewayv2_core.ApiGwV2Store)
    "compute", "vpc_net", "extras",   # Lambda/API Gateway + VPC models (private _lambda_functions etc., see _DURABLE_PRIVATE)
    "az_arm",   # Azure ARM control plane (core/azure_arm_core.AzureArm.state — Container Apps, VMs, …)
    "ssm",      # Systems Manager (core/ssm_core.SsmStore)
    "gcp_gke",    # Kubernetes Engine (core/gcp_container_core.ContainerStore)
    "gcp_mon",    # Cloud Monitoring (core/gcp_monitoring_core.MonitoringStore)
    "gcp_redis",  # Memorystore for Redis (core/gcp_redis_core.RedisStore)
    "gcp_iamc",   # IAM Credentials issue log (core/gcp_iamcredentials_core.IamCredentialsStore)
    "gcp_sched",  # Cloud Scheduler (core/gcp_cloudscheduler_core.CloudSchedulerStore)
    "gcp_run",    # Cloud Run (core/gcp_run_core.RunStore) — backs /functions
    "resources",  # generic catalog CRUD (EC2, Lambda-adjacent, every GCP service; wasm/backends/store.ResourceStore)
    "compute",  # Lambda functions + API Gateway APIs + VPC model (core/nano_registry.ComputeStore)
    "sfn",      # Step Functions (core/stepfunctions_core.StepFunctionsStore)
    "cw",       # CloudWatch metrics / alarms / dashboards
    "events",   # per-resource cloudsim event/activity log (core/nano_events.EventStore)
]


# ── JSON-safe codec (handles bytes anywhere in the tree) ─────────────────────
def _enc(v):
    if isinstance(v, (bytes, bytearray)):
        return {_B64: base64.b64encode(bytes(v)).decode()}
    if isinstance(v, dict):
        return {k: _enc(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_enc(x) for x in v]
    return v


def _dec(v):
    if isinstance(v, dict):
        if set(v.keys()) == {_B64}:
            return base64.b64decode(v[_B64])
        return {k: _dec(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_dec(x) for x in v]
    return v


# Private (`_`-prefixed) attrs that hold durable resource state — cores that keep
# their model lazily on the store (getattr/setattr) rather than as a public dict.
# Without these, a Lambda function / API / VPC created in the console vanishes on
# the next reload. Add a core's attr here when it keeps state this way.
_DURABLE_PRIVATE = ("_lambda_functions", "_apigateway_apis", "_vpc_model")


def _public_state(store) -> dict:
    # Capture public DATA attrs (the state dicts). Skip helper OBJECTS a store may
    # hold in public attrs (e.g. a stateless crypto engine) by proving each attr is
    # JSON-safe before including it — guarantees the whole snapshot serializes.
    out = {}
    for k, v in vars(store).items():
        if (k.startswith("_") and k not in _DURABLE_PRIVATE) or callable(v):
            continue
        try:
            enc = _enc(copy.deepcopy(v))
            json.dumps(enc)
            out[k] = enc
        except Exception:
            continue  # not plain data (engine/handle/etc.) — not persistable state
    return out


def _sql_dumps(store) -> dict:
    """Per-DB SQL dump for the SqlStore data plane (sqlite3 connections). PGlite
    (browser async) persists via its own IndexedDB dataDir, so it's skipped here."""
    dumps = {}
    conns = getattr(store, "_conns", None)
    if isinstance(conns, dict):
        for db_id, conn in conns.items():
            try:
                dumps[db_id] = "\n".join(conn.iterdump())
            except Exception:
                pass
    return dumps


# ── Per-store capture / restore ──────────────────────────────────────────────
def capture_store(store) -> dict:
    snap = {"state": _public_state(store)}
    d = _sql_dumps(store)
    if d:
        snap["sql"] = d
    return snap


def restore_store(store, snap: dict) -> None:
    for k, v in (snap.get("state") or {}).items():
        try:
            dv = _dec(v)
            cur = getattr(store, k, None)
            # MERGE dict state (union) instead of REPLACING it: a restore can only
            # ADD resources from the other context, never wipe locally-held ones.
            # This makes console<->SDK sync additive-safe (no destructive overwrite)
            # and lets the console rehydrate before every op without losing unsaved
            # local state. (Deletions don't cross contexts — acceptable vs data loss.)
            if isinstance(cur, dict) and isinstance(dv, dict):
                cur.update(dv)
            else:
                setattr(store, k, dv)
        except Exception:
            pass
    for db_id, sqltext in (snap.get("sql") or {}).items():
        try:
            conn = store.open_engine(db_id)          # fresh connection for this DB
            conn.executescript(sqltext)              # replay CREATE/INSERT dump
        except Exception:
            pass


# ── Whole-registry (router or shared registry) capture / restore ─────────────
def _lookup(obj, name):
    """Get store `name` from either an AwsWireRouter (attr) or a registry (dict)."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def capture(obj) -> dict:
    """Snapshot every store present on `obj` (an AwsWireRouter OR a registry dict)."""
    out = {}
    for name in STORE_ATTRS:
        st = _lookup(obj, name)
        if st is not None:
            try:
                out[name] = capture_store(st)
            except Exception:
                pass
    return out


def restore(obj, blob: dict) -> None:
    for name, snap in (blob or {}).items():
        st = _lookup(obj, name)
        if st is not None and isinstance(snap, dict):
            try:
                restore_store(st, snap)
            except Exception:
                pass


# ── One-call entrypoints for the JS bridge (operate on the shared registry) ──
def capture_registry() -> dict:
    """Snapshot the shared in-context registry → JSON-safe dict (JS persists it)."""
    from core import nano_registry
    return capture(nano_registry.get())


def health_registry() -> dict:
    """Live engine check for the Service status cards (wasm/sw.js /api/runtime/readiness):
    every store in this runtime's registry must be built and its state must read back
    through the same snapshot persistence uses. {store: {"ok", "engine"[, "error"]}}."""
    from core import nano_registry
    out = {}
    for name, st in nano_registry.get().items():
        engine = type(st).__name__ if st is not None else ""
        try:
            if st is None:
                raise RuntimeError("not built")
            capture_store(st)
            out[name] = {"ok": True, "engine": engine}
        except Exception as e:
            out[name] = {"ok": False, "engine": engine, "error": f"{type(e).__name__}: {e}"[:200]}
    return out


def restore_registry(blob: dict) -> None:
    """Restore a snapshot into the shared in-context registry (JS calls on boot /
    on a cross-context 'changed' notification)."""
    from core import nano_registry
    restore(nano_registry.get(), blob or {})
