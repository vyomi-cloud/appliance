"""console-next object-store facade (Azure Blob Storage) — the Azure lens's
object-browser data plane.

The SAME object-browser widget renders Azure Blob under lens=azure; the ONLY
difference is the manifest `api` block pointing at /api/console/azure-blob/*
instead of /api/s3/* or /api/console/gcs/* (§15.2 — no if(cloud) branching in the
widget). This module is the Azure sibling of the GCS console facade
(routes/console_next.py's /api/console/gcs/*): it returns the SAME JSON response
shapes the widget consumes (list buckets, create bucket, list objects, upload,
object meta, download), so the widget stays cloud-agnostic.

Azure Blob terminology: a "bucket" is a CONTAINER and an "object" is a BLOB. The
container name plays the role of the S3 bucket and the blob name the object key,
so the same bucket/object UX works with no widget changes.

Purely additive + substrate-free (no fastapi / azure-sdk / socket imports): it
holds its OWN module-level in-memory blob store so the Azure lens's object state is
independent of the AWS/GCP lenses', exactly like core/console_cloudsql mirrors
core/console_sql. It never touches any native Azure Blob core or its routes.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from typing import Any

# In-memory store: { container_name: {"meta": {...}, "blobs": { blob_name: {
#   "data": bytes, "content_type": str, "created": iso, "updated": iso,
#   "etag": str, "md5": str } } } }
_STORE: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AzureBlobError(Exception):
    """Facade error carrying an HTTP status + message (mapped to HTTPException)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _fmt_size(n) -> str:
    size = float(int(n or 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{int(size)} B"


def _container(name: str) -> dict:
    c = _STORE.get(name)
    if c is None:
        raise AzureBlobError(404, "ContainerNotFound")
    return c


# ── public API (mirrors the GCS/S3 console object-browser surface) ──────────

def list_buckets() -> dict:
    return {
        "owner": "vyomi-azure-simulator",
        "buckets": [{"name": n,
                     "location": (c.get("meta") or {}).get("location", "eastus"),
                     "storage_class": (c.get("meta") or {}).get("accessTier", "Hot"),
                     "created": (c.get("meta") or {}).get("created", "")}
                    for n, c in sorted(_STORE.items())],
        "count": len(_STORE),
    }


def create_bucket(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise AzureBlobError(400, "ValidationError: container name is required")
    if name in _STORE:
        raise AzureBlobError(409, "Conflict: container already exists")
    _STORE[name] = {
        "meta": {"name": name, "account": "vyomistorage", "location": "eastus",
                 "accessTier": "Hot", "publicAccess": "None", "created": _now(),
                 "updated": _now()},
        "blobs": {},
    }
    return {"message": f"Container '{name}' created", "location": f"/{name}"}


def list_objects(bucket: str, prefix: str = "") -> dict:
    c = _container(bucket)
    result = []
    for name in sorted(c.get("blobs", {})):
        if prefix and not name.startswith(prefix):
            continue
        blob = c["blobs"][name]
        size = int(blob.get("size", 0) or 0)
        result.append({
            "key": name,
            "size": size,
            "size_human": _fmt_size(size),
            "content_type": blob.get("content_type", "application/octet-stream"),
            "last_modified": blob.get("updated", blob.get("created", "")),
            "etag": blob.get("etag", ""),
            "storage_class": blob.get("access_tier", "Hot"),
        })
    return {"bucket": bucket, "prefix": prefix, "objects": result, "count": len(result)}


def put_object(bucket: str, key: str, data: bytes, content_type: str = "") -> dict:
    c = _container(bucket)
    key = (key or "").strip() or "console-blob"
    data = data or b""
    md5 = base64.b64encode(hashlib.md5(data).digest()).decode("ascii")
    etag = '"0x' + hashlib.md5(data).hexdigest().upper() + '"'
    now = _now()
    existing = c["blobs"].get(key)
    c["blobs"][key] = {
        "data": data,
        "size": len(data),
        "content_type": content_type or "application/octet-stream",
        "created": (existing or {}).get("created", now),
        "updated": now,
        "etag": etag,
        "md5": md5,
        "access_tier": "Hot",
        "blob_type": "BlockBlob",
    }
    return {"message": f"Blob '{key}' uploaded", "etag": etag, "size": len(data)}


def _get_blob(bucket: str, key: str) -> dict:
    c = _container(bucket)
    blob = c.get("blobs", {}).get(key)
    if blob is None:
        raise AzureBlobError(404, "BlobNotFound")
    return blob


def object_meta(bucket: str, key: str) -> dict:
    blob = _get_blob(bucket, key)
    size = int(blob.get("size", 0) or 0)
    return {
        "key": key, "bucket": bucket,
        "content_type": blob.get("content_type", "application/octet-stream"),
        "size": size, "size_human": _fmt_size(size),
        "etag": blob.get("etag", ""),
        "last_modified": blob.get("updated", blob.get("created", "")),
        "storage_class": blob.get("access_tier", "Hot"),
    }


def object_bytes(bucket: str, key: str) -> tuple[bytes, str]:
    blob = _get_blob(bucket, key)
    data = blob.get("data", b"")
    if isinstance(data, str):
        data = data.encode()
    return bytes(data or b""), blob.get("content_type", "application/octet-stream")
