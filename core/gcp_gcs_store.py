"""Real Cloud Storage object bytes via fake-gcs-server.

The simulator keeps bucket/object metadata (for the console + space model) but
delegates the actual object bytes to a fake-gcs-server instance, which speaks the
full GCS upload protocol (media / multipart / resumable). Object uploads and
`?alt=media` downloads are proxied through to it so an unmodified GCS SDK or
gsutil pointed at the simulator round-trips byte-for-byte.

If fake-gcs-server is not configured/reachable the caller should fall back to the
metadata-only path.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request


def _base() -> str:
    return os.environ.get("CLOUDLEARN_GCS_URL", "").rstrip("/")


def available() -> bool:
    return bool(_base())


def _request(method: str, path: str, data: bytes | None = None,
             headers: dict | None = None, timeout: int = 30):
    req = urllib.request.Request(_base() + path, data=data, method=method, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout)


def ensure_bucket(bucket: str) -> None:
    """Create the bucket in the byte store (idempotent)."""
    try:
        _request(
            "POST", "/storage/v1/b?project=cloudlearn",
            data=json.dumps({"name": bucket}).encode(),
            headers={"Content-Type": "application/json"},
        )
    except urllib.error.HTTPError as exc:
        if exc.code not in (409,):  # 409 = already exists
            raise


def upload(bucket: str, query: str, body: bytes, content_type: str) -> tuple[int, bytes]:
    """Proxy an object upload (any uploadType) to the byte store. Returns
    (status, response_body) where the body is GCS object metadata JSON."""
    ensure_bucket(bucket)
    path = f"/upload/storage/v1/b/{bucket}/o"
    if query:
        path += "?" + query
    resp = _request("POST", path, data=body, headers={"Content-Type": content_type or "application/octet-stream"})
    return resp.status, resp.read()


def download(bucket: str, name: str) -> tuple[bytes, str]:
    """Fetch object bytes (?alt=media) from the byte store."""
    quoted = urllib.parse.quote(name, safe="")
    resp = _request("GET", f"/storage/v1/b/{bucket}/o/{quoted}?alt=media")
    return resp.read(), resp.headers.get("Content-Type", "application/octet-stream")


def delete(bucket: str, name: str) -> bool:
    quoted = urllib.parse.quote(name, safe="")
    try:
        _request("DELETE", f"/storage/v1/b/{bucket}/o/{quoted}")
        return True
    except urllib.error.HTTPError as exc:
        return exc.code == 404
    except Exception:
        return False


def put_text(bucket: str, name: str, text: str, content_type: str = "text/plain") -> tuple[int, bytes]:
    """Convenience upload for console/Terraform JSON-body objects (data string)."""
    query = "uploadType=media&name=" + urllib.parse.quote(name, safe="")
    return upload(bucket, query, text.encode("utf-8"), content_type)
