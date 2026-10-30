"""Appliance store seams for the ONE engine (v4 C0) — Pro/Max only, never vendored.

In v4 the offline appliance serves native S3 / DynamoDB / GCS wire through the SAME
conformance cores Nano uses (core/s3_object_core.py, core/dynamodb_core.py,
core/gcp_storage_core.py via core/aws_wire_router.py). The cores persist through a
store seam; these are the appliance's implementations of that seam.

Design — one state, not two. Each store's working dicts ARE the appliance's existing
space-scoped state (core.app_context `_SpaceScopedDictProxy`):

    S3        buckets / objects / multipart  -> service_states["s3"]{buckets,objects,multiparts}
    GCS       buckets / objects              -> service_states["gcp_gcp_storage"]{buckets,objects}
    DynamoDB  tables                         -> service_states["dynamodb"]{tables}

The cores were extracted from the appliance handlers, so the shapes are identical.
Consequences:
  * every v3 consumer of that state — the classic console REST (/api/s3/*,
    /api/dynamodb/*, /api/console/gcs/*, GCS folders / transfer jobs), Lambda
    triggers, inventory, Terraform — sees exactly what the native wire wrote, and
    vice-versa (no sync, no second copy);
  * tenant / space / provider isolation is the proxy's (unchanged);
  * durability is the kernel state store (CLOUDLEARN_STATE_FILE, SQLite), which
    the tier middleware flushes after every POST/PUT/PATCH/DELETE — the same
    write path every other appliance service uses, so a restart restores bucket
    config, version chains, GCS labels/retention and DynamoDB tables;
  * object bytes are additionally written through to the real byte stores
    (S3 -> MinIO via core.minio_mirror, GCS -> fake-gcs-server when configured)
    so external tools see them; when MinIO is not reachable the mirror is
    skipped (logged once) and the inline bytes in the state keep S3 working.
"""
from __future__ import annotations

import logging
import threading
import time

from core.nosql_store import NoSqlStore
from core.object_store import ObjectStore

_log = logging.getLogger("vyomi.engine")


def _proxy(service_key: str, factory, nested: str):
    from core.app_context import _SpaceScopedDictProxy
    return _SpaceScopedDictProxy(service_key, factory, nested)


class _MirrorGate:
    """Probe a byte store at most once a minute; log the first time it is down."""

    def __init__(self, name: str, probe):
        self._name, self._probe = name, probe
        self._ok, self._at, self._logged = False, 0.0, False
        self._lock = threading.Lock()

    def ok(self) -> bool:
        now = time.monotonic()
        if now - self._at < 60:
            return self._ok
        with self._lock:
            if now - self._at < 60:
                return self._ok
            try:
                self._ok = bool(self._probe())
            except Exception:
                self._ok = False
            self._at = now
            if not self._ok and not self._logged:
                self._logged = True
                msg = (f"[engine] {self._name} not reachable — object bytes stay in the appliance "
                       f"state store only (persistent); write-through resumes when it returns")
                print(msg)   # once; stdout reaches the appliance log under uvicorn
        return self._ok


class AppStateObjectStore(ObjectStore):
    """ObjectStore whose state dicts are the appliance's space-scoped state."""

    def __init__(self, buckets, objects, multiparts=None, *, mirror=None, events=None,
                 fetch=None, storage_cap=None, quantity_cap=None):
        # NB: no super().__init__() — buckets/objects are the shared proxies, not new dicts.
        self._b, self._o = buckets, objects
        self._m = multiparts
        self._mirror = mirror            # (put(bucket,key,data,ct,meta), delete(bucket,key)) or None
        self._events = events
        self._fetch = fetch
        self._storage_cap = storage_cap
        self._quantity_cap = quantity_cap

    buckets = property(lambda self: self._b)
    objects = property(lambda self: self._o)

    @property
    def _multipart_uploads(self):
        if self._m is None:
            self._m = {}
        return self._m

    @_multipart_uploads.setter
    def _multipart_uploads(self, value):
        self._m = value

    def mirror_put(self, bucket, key, data, content_type="application/octet-stream", metadata=None):
        if self._mirror:
            try:
                self._mirror[0](bucket, key, data, content_type, metadata)
            except Exception:
                pass

    def mirror_delete(self, bucket, key):
        if self._mirror:
            try:
                self._mirror[1](bucket, key)
            except Exception:
                pass

    def emit_event(self, bucket, key, event_name, version=None, source=""):
        if self._events:
            self._events(bucket, key, event_name, version, source)

    def fetch_bytes(self, bucket, key):
        if self._fetch:
            try:
                return self._fetch(bucket, key)
            except Exception:
                return None
        return None

    def enforce_storage_cap(self, additional_bytes):
        if self._storage_cap:
            self._storage_cap(additional_bytes)

    def enforce_quantity_cap(self, resource_type):
        if self._quantity_cap:
            self._quantity_cap(resource_type)

    # persist(): no-op — the tier middleware persists the kernel state after every
    # mutating request (and the S3/GCS/DDB state lives inside it).


class AppStateNoSqlStore(NoSqlStore):
    """NoSqlStore whose `tables` map is the appliance's space-scoped ddb_state["tables"]."""

    def __init__(self, tables, account_id: str):
        self._t = tables
        self.account_id = account_id

    tables = property(lambda self: self._t)


# ── singletons ─────────────────────────────────────────────────────────────
_S3 = _GCS = _DDB = None


def s3_store() -> AppStateObjectStore:
    global _S3
    if _S3 is None:
        from core import app_context as ctx
        from core import minio_mirror as mm
        gate = _MirrorGate(f"MinIO ({mm._MINIO_URL})", mm.available)

        def put(bucket, key, data, ct, meta):
            if gate.ok():
                mm.put_object(bucket, key, data, content_type=ct, metadata=meta)

        def delete(bucket, key):
            if gate.ok():
                mm.delete_object(bucket, key)

        def fetch(bucket, key):
            return mm.get_object(bucket, key) if gate.ok() else None

        def events(bucket, key, event_name, version, source):
            from routes import aws_s3
            aws_s3._s3_emit_event(bucket, key, event_name, version, source=source)

        def storage_cap(n):
            import server
            server._enforce_storage_cap(n)

        def quantity_cap(kind):
            import server
            server._enforce_quantity_cap(kind)

        _S3 = AppStateObjectStore(ctx.buckets, ctx.objects, ctx.multiparts, mirror=(put, delete),
                                  events=events, fetch=fetch, storage_cap=storage_cap,
                                  quantity_cap=quantity_cap)
    return _S3


def gcs_store() -> AppStateObjectStore:
    global _GCS
    if _GCS is None:
        from core import app_context as ctx
        from core import gcp_gcs_store as gs
        factory = ctx.gcp_storage_state.default_factory
        gate = _MirrorGate("fake-gcs-server (CLOUDLEARN_GCS_URL)",
                           lambda: gs.available() and gs._base().startswith(("http://", "https://")))

        def put(bucket, key, data, ct, meta):
            if gate.ok():
                import urllib.parse
                gs.upload(ctx.tenant_scoped_bucket(bucket),
                          "uploadType=media&name=" + urllib.parse.quote(key, safe=""), data, ct)

        def delete(bucket, key):
            if gate.ok():
                gs.delete(ctx.tenant_scoped_bucket(bucket), key)

        def fetch(bucket, key):
            # pre-v4 objects: metadata in the state, bytes only in fake-gcs
            return gs.download(ctx.tenant_scoped_bucket(bucket), key)[0] if gate.ok() else None

        _GCS = AppStateObjectStore(_proxy("gcp_storage", factory, "buckets"),
                                   _proxy("gcp_storage", factory, "objects"),
                                   mirror=(put, delete), fetch=fetch)
    return _GCS


def ddb_store() -> AppStateNoSqlStore:
    global _DDB
    if _DDB is None:
        from core import app_context as ctx
        _DDB = AppStateNoSqlStore(_proxy("dynamodb", ctx.ddb_state.default_factory, "tables"),
                                  account_id=ctx.AWS_ACCOUNT_ID)
    return _DDB
