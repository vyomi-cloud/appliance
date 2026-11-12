"""MinIO-backed object substrate (v2.4.0 Phase 1; v4 C0 durable metadata) — Pro/Max only.

The real-backend implementation of the ObjectStore seam: the shared object cores
(S3 / GCS) run unchanged, but object bytes live in a real external MinIO
(S3-compatible) server instead of only in memory.

NOT substrate-free — imports boto3 — so it is **never vendored to WASM**. It runs
only in the server appliance (Pro/Max), behind the same seam the in-WASM stores
use in Nano. That's the whole point: one core, swap the substrate.

v4 C0 — durable state. Before C0 the store rebuilt its bucket list from MinIO on
start, so everything the cores keep in `store.buckets[name]` (versioning, the
`cfg` sub-resource documents, object lock, region, tags, notifications, GCS
labels / retention / IAM…) and every version chain / delete marker / tag edit
that never reached `mirror_put` was lost on restart. Now:

  * the cores call `store.persist()` after EVERY mutation; this store writes the
    complete state (buckets + object entries + in-flight multipart uploads) to a
    SQLite sidecar next to the appliance state (`CLOUDLEARN_STATE_FILE`'s
    directory, or `VYOMI_OBJECT_META_DB`) and restores it on start;
  * object bytes are still written through to MinIO as real objects, so external
    S3 tools see them;
  * a pre-C0 deployment (no sidecar row yet) is migrated by the old path: rebuild
    from the verbatim `__entries__/` sidecar objects kept in MinIO.

`build_object_store()` picks this store when MinIO answers, else a SQLite-only
`PersistentObjectStore` on the same sidecar (logged once) — so a bare
`uvicorn server:app` dev run still has durable S3 / GCS.
"""
from __future__ import annotations

import base64
import json
import logging
import os

from core.object_store import InMemoryObjectStore
from core.persistent_store import PersistentObjectStore, SqliteStateBackend

_ENTRIES = "__entries__/"   # pre-C0 sidecar key prefix holding the verbatim core entry
_log = logging.getLogger("vyomi.objects")
_BACKENDS: dict[str, SqliteStateBackend] = {}
_FALLBACK_LOGGED: set = set()


def _hook(d):
    if len(d) == 1 and "__b64__" in d:
        return base64.b64decode(d["__b64__"])
    return d


def default_sidecar_path() -> str:
    """The SQLite sidecar for object-store metadata: next to the appliance state."""
    explicit = os.environ.get("VYOMI_OBJECT_META_DB", "").strip()
    if explicit:
        return explicit
    state = os.environ.get("CLOUDLEARN_STATE_FILE", "").strip()
    base = os.path.dirname(os.path.abspath(state)) if state else "/tmp"
    return os.path.join(base, "vyomi-objects.sqlite")


def sidecar_backend(path: str | None = None) -> SqliteStateBackend:
    """One shared SqliteStateBackend per file (S3 and GCS stores share the file)."""
    p = path or default_sidecar_path()
    if p not in _BACKENDS:
        if p != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(p)) or ".", exist_ok=True)
        _BACKENDS[p] = SqliteStateBackend(p)
    return _BACKENDS[p]


class MinioBackedObjectStore(InMemoryObjectStore):
    def __init__(self, endpoint: str = "http://localhost:9100",
                 access_key: str = "cloudlearn", secret_key: str = "cloudlearn-dev-secret-key",
                 prefix: str = "v24-", region: str = "us-east-1",
                 sidecar_path: str | None = None, connect_timeout: float = 3.0):
        import boto3
        from botocore.client import Config

        super().__init__()
        self._prefix = prefix   # namespace real buckets so we never touch appliance data
        self._s3 = boto3.client(
            "s3", endpoint_url=endpoint, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          connect_timeout=connect_timeout, read_timeout=30,
                          retries={"max_attempts": 2}))
        self._meta = sidecar_backend(sidecar_path)
        self._sid = "minio-objects:" + prefix
        self._load()

    def _mb(self, bucket: str) -> str:
        return self._prefix + bucket

    def _logical(self, real: str) -> str:
        return real[len(self._prefix):]

    # ── durable state: SQLite sidecar (source of truth for metadata) ──────
    def persist(self) -> None:
        self._meta.save(self._sid, {"buckets": self.buckets, "objects": self.objects,
                                    "multipart": getattr(self, "_multipart_uploads", {}) or {}})

    def _load(self) -> None:
        saved = self._meta.load(self._sid)
        try:
            real = {b["Name"] for b in self._s3.list_buckets().get("Buckets", [])}
        except Exception:
            real = None   # MinIO down at start: trust the sidecar
        if saved:
            self.buckets = saved.get("buckets") or {}
            self.objects = saved.get("objects") or {}
            mpu = saved.get("multipart") or {}
            if mpu:
                self._multipart_uploads = mpu
            if real is not None:
                # a bucket removed out-of-band from MinIO is gone; re-create the ones
                # MinIO lost so later byte writes have a home
                for name in list(self.buckets):
                    if self._mb(name) not in real and not self.objects.get(name):
                        try:
                            self._s3.create_bucket(Bucket=self._mb(name))
                        except Exception:
                            pass
            return
        if real is None:
            return
        # pre-C0 migration: rebuild from the verbatim entries kept in MinIO
        pag = self._s3.get_paginator("list_objects_v2")
        for name in sorted(real):
            if not name.startswith(self._prefix):
                continue
            logical = self._logical(name)
            self.buckets.setdefault(logical, {"versioning": "Disabled"})
            objs = self.objects.setdefault(logical, {})
            for page in pag.paginate(Bucket=name, Prefix=_ENTRIES):
                for o in page.get("Contents", []):
                    key = o["Key"][len(_ENTRIES):]
                    body = self._s3.get_object(Bucket=name, Key=o["Key"])["Body"].read()
                    objs[key] = json.loads(body.decode("utf-8"), object_hook=_hook)
        if self.buckets:
            self.persist()

    # ── seam hooks → real MinIO write-through ─────────────────────────────
    def create_bucket(self, name: str, versioning: str = "Disabled") -> None:
        super().create_bucket(name, versioning)
        try:
            self._s3.create_bucket(Bucket=self._mb(name))
        except Exception:
            pass   # already exists

    def mirror_put(self, bucket, key, data, content_type="application/octet-stream",
                   metadata=None) -> None:
        try:
            self._s3.put_object(Bucket=self._mb(bucket), Key=key, Body=data, ContentType=content_type,
                                Metadata={k: str(v) for k, v in (metadata or {}).items()})
        except Exception as exc:   # the sidecar holds the bytes too; never fail the write
            _log.warning("MinIO write-through failed for %s/%s: %s", bucket, key, exc)

    def mirror_delete(self, bucket, key) -> None:
        for k in (key, _ENTRIES + key):
            try:
                self._s3.delete_object(Bucket=self._mb(bucket), Key=k)
            except Exception:
                pass

    def fetch_bytes(self, bucket, key):
        try:
            return self._s3.get_object(Bucket=self._mb(bucket), Key=key)["Body"].read()
        except Exception:
            return None


def minio_reachable(endpoint: str, access_key: str, secret_key: str, timeout: float = 2.0) -> bool:
    try:
        import boto3
        from botocore.client import Config
        c = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=access_key,
                         aws_secret_access_key=secret_key, region_name="us-east-1",
                         config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                       connect_timeout=timeout, read_timeout=timeout,
                                       retries={"max_attempts": 1}))
        c.list_buckets()
        return True
    except Exception:
        return False


def build_object_store(prefix: str, endpoint: str, access_key: str, secret_key: str,
                       sidecar_path: str | None = None):
    """MinIO-backed store when MinIO answers; otherwise a durable SQLite-only store on
    the same sidecar (logged once per prefix) so S3 / GCS keep working without MinIO."""
    if minio_reachable(endpoint, access_key, secret_key):
        return MinioBackedObjectStore(endpoint=endpoint, access_key=access_key, secret_key=secret_key,
                                      prefix=prefix, sidecar_path=sidecar_path)
    if prefix not in _FALLBACK_LOGGED:
        _FALLBACK_LOGGED.add(prefix)
        msg = (f"[objects] MinIO not reachable at {endpoint} — '{prefix}' object store falls back to "
               f"SQLite-only persistence ({sidecar_path or default_sidecar_path()})")
        _log.warning(msg)
        print(msg)
    return PersistentObjectStore(sidecar_backend(sidecar_path), store_id="sqlite-objects:" + prefix)
