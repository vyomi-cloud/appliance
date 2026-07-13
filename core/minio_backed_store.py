"""MinIO-backed object substrate (v2.4.0 Phase 1) — Pro/Max only.

The real-backend implementation of the ObjectStore seam: the shared object cores
(S3 / GCS / Azure Blob) run unchanged, but object bytes live in a real external
MinIO (S3-compatible) server instead of memory. This is the production substrate
the plan's matrix calls for (S3→MinIO); GCS→fake-gcs-server and Azure Blob→Azurite
follow the identical pattern against their native backends.

NOT substrate-free — imports boto3 — so it is **never vendored to WASM**. It runs
only in the server appliance (Pro/Max), behind the same seam the in-WASM stores
use in Nano. That's the whole point: one core, swap the substrate.

Core-agnostic persistence: `mirror_put` fires AFTER the core has written its full
(core-specific) entry to `self.objects[bucket][key]`, so we persist that entry
verbatim as a sidecar object — any object core (S3/GCS/Azure) round-trips exactly.
The raw bytes are also stored as the real object so external S3 tools see them.
"""
from __future__ import annotations

import base64
import json

import boto3
from botocore.client import Config

from core.object_store import InMemoryObjectStore

_ENTRIES = "__entries__/"   # sidecar key prefix holding the verbatim core entry


def _enc(o):
    if isinstance(o, (bytes, bytearray)):
        return {"__b64__": base64.b64encode(bytes(o)).decode()}
    raise TypeError


def _hook(d):
    if len(d) == 1 and "__b64__" in d:
        return base64.b64decode(d["__b64__"])
    return d


class MinioBackedObjectStore(InMemoryObjectStore):
    def __init__(self, endpoint: str = "http://localhost:9100",
                 access_key: str = "cloudlearn", secret_key: str = "cloudlearn-dev-secret-key",
                 prefix: str = "v24-", region: str = "us-east-1"):
        super().__init__()
        self._prefix = prefix   # namespace real buckets so we never touch appliance data
        self._s3 = boto3.client(
            "s3", endpoint_url=endpoint, aws_access_key_id=access_key,
            aws_secret_access_key=secret_key, region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
        self._load()

    def _mb(self, bucket: str) -> str:
        return self._prefix + bucket

    def _logical(self, real: str) -> str:
        return real[len(self._prefix):]

    # ── load the in-memory view from MinIO on init ────────────────────────
    def _load(self) -> None:
        try:
            buckets = self._s3.list_buckets().get("Buckets", [])
        except Exception:
            return
        pag = self._s3.get_paginator("list_objects_v2")
        for b in buckets:
            real = b["Name"]
            if not real.startswith(self._prefix):
                continue
            logical = self._logical(real)
            self.buckets.setdefault(logical, {"versioning": "Disabled"})
            objs = self.objects.setdefault(logical, {})
            for page in pag.paginate(Bucket=real, Prefix=_ENTRIES):
                for o in page.get("Contents", []):
                    key = o["Key"][len(_ENTRIES):]
                    body = self._s3.get_object(Bucket=real, Key=o["Key"])["Body"].read()
                    objs[key] = json.loads(body.decode("utf-8"), object_hook=_hook)

    # ── seam hooks → real MinIO write-through ─────────────────────────────
    def create_bucket(self, name: str, versioning: str = "Disabled") -> None:
        super().create_bucket(name, versioning)
        try:
            self._s3.create_bucket(Bucket=self._mb(name))
        except Exception:
            pass   # already exists

    def mirror_put(self, bucket, key, data, content_type="application/octet-stream",
                   metadata=None) -> None:
        real = self._mb(bucket)
        entry = self.objects.get(bucket, {}).get(key, {})   # the full core-specific entry
        # the real object (external-visible bytes)
        self._s3.put_object(Bucket=real, Key=key, Body=data, ContentType=content_type,
                            Metadata={k: str(v) for k, v in (metadata or {}).items()})
        # the sidecar (verbatim core entry, so any object core round-trips exactly)
        self._s3.put_object(Bucket=real, Key=_ENTRIES + key,
                            Body=json.dumps(entry, default=_enc).encode("utf-8"))

    def mirror_delete(self, bucket, key) -> None:
        real = self._mb(bucket)
        for k in (key, _ENTRIES + key):
            try:
                self._s3.delete_object(Bucket=real, Key=k)
            except Exception:
                pass
