"""MinIO write-through for AWS S3 — real bytes on disk in the cloudlearn-minio
container.

We don't replace the existing in-memory S3 store (too invasive for MVP); we
mirror writes to MinIO so the same bytes are durably accessible via real S3
SDKs hitting MinIO directly. This gives us:

  * Real bytes on disk (survive container restarts via the cloudlearn-minio volume)
  * Real S3 wire protocol downstream (MinIO speaks full SigV4)
  * Conformance can assert ``mc cat cloudlearn/<bucket>/<key>`` returns the
    same bytes that were PUT via the simulator

Read-back is preferred from MinIO when available (real-bytes-on-read path),
otherwise falls back to the in-memory copy.

Operation is best-effort + non-blocking on the request path: a MinIO outage
must NEVER break the simulator's S3 surface.
"""
from __future__ import annotations

import os
import threading
from typing import Any

try:
    import boto3
    from botocore.client import Config as _BotoConfig
except ImportError:
    boto3 = None  # type: ignore[assignment]
    _BotoConfig = None  # type: ignore[assignment]


_MINIO_URL = os.environ.get("CLOUDLEARN_MINIO_URL", "http://cloudlearn-minio:9000")
_ACCESS_KEY = os.environ.get("CLOUDLEARN_MINIO_ACCESS_KEY", "cloudlearn")
_SECRET_KEY = os.environ.get("CLOUDLEARN_MINIO_SECRET_KEY", "cloudlearn-dev-secret-key")

_client: Any | None = None
_lock = threading.Lock()
_bucket_cache: set[str] = set()


def _get_client() -> Any | None:
    global _client
    if boto3 is None:
        return None
    if _client is not None:
        return _client
    with _lock:
        if _client is None:
            try:
                _client = boto3.client(
                    "s3",
                    endpoint_url=_MINIO_URL,
                    aws_access_key_id=_ACCESS_KEY,
                    aws_secret_access_key=_SECRET_KEY,
                    region_name="us-east-1",
                    config=_BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
                )
            except Exception:
                _client = None
    return _client


def available() -> bool:
    c = _get_client()
    if c is None:
        return False
    try:
        c.list_buckets()
        return True
    except Exception:
        return False


def _ensure_bucket(bucket: str) -> bool:
    """Idempotent CreateBucket on MinIO. Best-effort; cached for the process."""
    if bucket in _bucket_cache:
        return True
    c = _get_client()
    if c is None:
        return False
    try:
        # head first; if 404, create. boto3 raises on 404.
        c.head_bucket(Bucket=bucket)
        _bucket_cache.add(bucket)
        return True
    except Exception:
        try:
            c.create_bucket(Bucket=bucket)
            _bucket_cache.add(bucket)
            return True
        except Exception:
            return False


def put_object(bucket: str, key: str, data: bytes,
               content_type: str = "application/octet-stream",
               metadata: dict | None = None) -> bool:
    """Write-through to MinIO. Returns True on success."""
    c = _get_client()
    if c is None:
        return False
    if not _ensure_bucket(bucket):
        return False
    try:
        kwargs: dict = {
            "Bucket": bucket,
            "Key": key,
            "Body": data,
            "ContentType": content_type,
        }
        if metadata:
            # boto3 lowercases custom metadata keys per S3 convention.
            kwargs["Metadata"] = {str(k): str(v) for k, v in metadata.items()}
        c.put_object(**kwargs)
        return True
    except Exception:
        return False


def get_object(bucket: str, key: str) -> bytes | None:
    """Read from MinIO. Returns the bytes or None on miss/error."""
    c = _get_client()
    if c is None:
        return None
    try:
        r = c.get_object(Bucket=bucket, Key=key)
        return r["Body"].read()
    except Exception:
        return None


def delete_object(bucket: str, key: str) -> bool:
    c = _get_client()
    if c is None:
        return False
    try:
        c.delete_object(Bucket=bucket, Key=key)
        return True
    except Exception:
        return False


def list_objects(bucket: str, prefix: str = "") -> list[dict]:
    c = _get_client()
    if c is None:
        return []
    try:
        r = c.list_objects_v2(Bucket=bucket, Prefix=prefix)
        return [
            {"key": o["Key"], "size": o["Size"], "etag": o.get("ETag", "").strip('"')}
            for o in r.get("Contents", [])
        ]
    except Exception:
        return []
