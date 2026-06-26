# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""ObjectStore — the data-plane seam for S3 object storage (ADR-001).

The S3 protocol logic (versioning, ETag, delete markers, list/XML, ranges) is
substrate-independent and lives in core/s3_object_core.py. THIS is the seam it
persists through, so the same handler runs on any substrate:

    Pro/Max : MinioBackedStore  — appliance ctx dicts + best-effort MinIO mirror
    Nano    : InMemoryObjectStore — pure in-WASM (Pyodide); OPFS later
    tests   : InMemoryObjectStore

The store owns the two state dicts the handler reads/writes — exactly the
`buckets` and `objects` module globals the original route used — plus three
optional hooks (mirror + tier cap) that default to no-ops. Nothing here imports
fastapi / boto3 / socket, so it loads under Pyodide.

State shapes (unchanged from routes/aws_s3.py):
    buckets: { name -> { "versioning": "Enabled"|"Suspended"|"Disabled", ... } }
    objects: { bucket -> { key -> entry } }
    entry  : { "versions": [version, ...newest-first], "current_version_id", ... }
    version: { version_id, is_delete_marker, data(bytes), size, content_type,
               last_modified(iso), etag, storage_class, metadata, tags }
"""
from __future__ import annotations

from typing import Any


class ObjectStore:
    """Base seam. In-memory by default; subclass to add a mirror / persistence."""

    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, Any]] = {}
        self.objects: dict[str, dict[str, Any]] = {}

    # ── bucket helpers ────────────────────────────────────────────────
    def bucket_exists(self, name: str) -> bool:
        return name in self.buckets

    def create_bucket(self, name: str, versioning: str = "Disabled") -> None:
        self.buckets.setdefault(name, {"versioning": versioning})

    def versioning_status(self, bucket: str) -> str:
        status = self.buckets.get(bucket, {}).get("versioning", "Disabled")
        return status if status in {"Enabled", "Suspended", "Disabled"} else "Disabled"

    # ── object-entry map for a bucket (the {key -> entry} dict) ────────
    def bucket_objects(self, bucket: str) -> dict[str, Any]:
        return self.objects.setdefault(bucket, {})

    # ── optional hooks (no-ops in the base) ───────────────────────────
    def mirror_put(self, bucket: str, key: str, data: bytes,
                   content_type: str = "application/octet-stream",
                   metadata: dict | None = None) -> None:
        """Best-effort write-through to an external store (MinIO in Pro/Max,
        OPFS in Nano). The in-memory dict is the source of truth either way."""

    def mirror_delete(self, bucket: str, key: str) -> None:
        """Best-effort delete in the external mirror."""

    def enforce_storage_cap(self, additional_bytes: int) -> None:
        """Tier storage-quota gate (Pro/Max wires this to server.py). No-op in
        Nano/tests — the WASM tab has no tier server to consult."""


class InMemoryObjectStore(ObjectStore):
    """The Nano / test substrate: pure in-memory, zero external deps. Identical
    to the appliance's in-memory behavior minus the MinIO mirror."""
