# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure Blob Storage object-CRUD core — substrate-independent, the Azure
analogue of core/gcp_storage_core.py / core/s3_object_core.py. Speaks the
native **Azure Blob REST API** so the native `azure-storage-blob` SDK, the
`az storage blob` CLI, and Azurite-style clients work unchanged against it
(point them at the endpoint / connection string).

NO fastapi / azure-* / socket / subprocess imports → loads under Pyodide.
Self-contained: bundles its own in-memory `AzureBlobStore` (does NOT import
core/azure_blob_store.py) so the core is a single portable unit.

Scope (data-plane slice):
  - create container   PUT  /{container}?restype=container            -> 201
  - list containers    GET  /?comp=list                              -> 200 XML
  - put block blob     PUT  /{container}/{blob}  x-ms-blob-type       -> 201
  - get blob           GET  /{container}/{blob}                       -> 200 bytes
  - head blob props    HEAD /{container}/{blob}                       -> 200
  - list blobs         GET  /{container}?restype=container&comp=list  -> 200 XML
  - delete blob        DELETE /{container}/{blob}                     -> 202
  - delete container   DELETE /{container}?restype=container          -> 202

Errors carry status + `x-ms-error-code` header + an `<Error><Code>..</Code>`
XML body (ContainerNotFound / BlobNotFound / ContainerAlreadyExists).
Every response carries `x-ms-request-id` + `x-ms-version` headers.

An OPTIONAL leading `/{account}` path segment (Azurite style
`/{account}/{container}/{blob}`) is tolerated — the well-known
`/devstoreaccount1/` prefix is stripped.
"""
from __future__ import annotations

import base64
import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote
from xml.sax.saxutils import escape

X_MS_VERSION = "2021-12-02"


@dataclass
class Response:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/xml"


# ── self-contained in-memory store ─────────────────────────────────────────
class AzureBlobStore:
    """In-memory Azure Blob namespace. containers: name -> {meta}. blobs:
    container -> {blob_name -> entry}. Fully self-contained; no external seam."""

    def __init__(self) -> None:
        self.containers: dict[str, dict] = {}
        self.blobs: dict[str, dict[str, dict]] = {}

    def container_exists(self, name: str) -> bool:
        return name in self.containers

    def create_container(self, name: str) -> None:
        self.containers[name] = {"created": _now_http()}
        self.blobs.setdefault(name, {})

    def delete_container(self, name: str) -> None:
        self.containers.pop(name, None)
        self.blobs.pop(name, None)

    def container_blobs(self, name: str) -> dict[str, dict]:
        return self.blobs.setdefault(name, {})


# ── primitives ─────────────────────────────────────────────────────────────
def _now_http() -> str:
    # RFC 1123, e.g. "Wed, 13 Jul 2026 12:00:00 GMT"
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _etag() -> str:
    return '"0x8D' + uuid.uuid4().hex[:13].upper() + '"'


def _md5_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode()


def _request_id() -> str:
    return str(uuid.uuid4())


def _base_headers() -> dict:
    return {
        "x-ms-request-id": _request_id(),
        "x-ms-version": X_MS_VERSION,
        "date": _now_http(),
    }


def _err(status: int, code: str, message: str) -> Response:
    h = _base_headers()
    h["x-ms-error-code"] = code
    h["content-type"] = "application/xml"
    body = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f"<Error><Code>{escape(code)}</Code>"
        f"<Message>{escape(message)}</Message></Error>"
    ).encode()
    return Response(status=status, headers=h, body=body)


def _xml(status: int, body: str) -> Response:
    h = _base_headers()
    h["content-type"] = "application/xml"
    return Response(status=status, headers=h, body=body.encode())


# ── path handling ──────────────────────────────────────────────────────────
def _strip_account(p: str) -> str:
    """Tolerate an optional leading /{account} segment (Azurite style).
    Strip the well-known devstoreaccount1 prefix robustly."""
    if p.startswith("/devstoreaccount1/"):
        return p[len("/devstoreaccount1"):]
    if p == "/devstoreaccount1":
        return "/"
    return p


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: AzureBlobStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> Response:
    query = query or {}
    headers = {(k or "").lower(): v for k, v in (headers or {}).items()}
    method = method.upper()

    p = path.split("?", 1)[0]
    p = _strip_account(p)
    p = p.rstrip("/") if p != "/" else p
    segs = [unquote(s) for s in p.split("/") if s != ""]

    comp = query.get("comp", "")
    restype = query.get("restype", "")

    # ---- account-level: list containers  GET /?comp=list ----
    if not segs:
        if method == "GET" and comp == "list":
            return _list_containers(store)
        return _err(400, "InvalidUri", f"Unsupported account operation {method}")

    container = segs[0]

    # ---- container-level: /{container} ----
    if len(segs) == 1:
        if restype == "container":
            if method == "PUT":                       # create container
                if store.container_exists(container):
                    return _err(409, "ContainerAlreadyExists",
                                "The specified container already exists.")
                store.create_container(container)
                h = _base_headers()
                h["etag"] = _etag()
                h["last-modified"] = _now_http()
                return Response(status=201, headers=h, body=b"", media_type=None)
            if method == "DELETE":                    # delete container
                if not store.container_exists(container):
                    return _err(404, "ContainerNotFound",
                                "The specified container does not exist.")
                store.delete_container(container)
                return Response(status=202, headers=_base_headers(),
                                body=b"", media_type=None)
            if method == "GET" and comp == "list":    # list blobs
                if not store.container_exists(container):
                    return _err(404, "ContainerNotFound",
                                "The specified container does not exist.")
                return _list_blobs(store, container, query)
            if method in ("GET", "HEAD"):             # get container props
                if not store.container_exists(container):
                    return _err(404, "ContainerNotFound",
                                "The specified container does not exist.")
                h = _base_headers()
                h["last-modified"] = store.containers[container].get("created", _now_http())
                h["etag"] = _etag()
                return Response(status=200, headers=h, body=b"", media_type=None)
        return _err(400, "InvalidQueryParameterValue",
                    f"Unsupported container operation {method}")

    # ---- blob-level: /{container}/{blob...} ----
    blob = "/".join(segs[1:])

    if method == "PUT":                               # put block blob
        if not store.container_exists(container):
            return _err(404, "ContainerNotFound",
                        "The specified container does not exist.")
        blob_type = headers.get("x-ms-blob-type", "BlockBlob")
        content_type = headers.get("content-type", "application/octet-stream")
        entry = {
            "data": body,
            "size": len(body),
            "content_type": content_type,
            "blob_type": blob_type,
            "etag": _etag(),
            "last_modified": _now_http(),
            "md5": _md5_b64(body),
            "metadata": {k[len("x-ms-meta-"):]: v for k, v in headers.items()
                         if k.startswith("x-ms-meta-")},
        }
        store.container_blobs(container)[blob] = entry
        h = _base_headers()
        h["etag"] = entry["etag"]
        h["last-modified"] = entry["last_modified"]
        h["content-md5"] = entry["md5"]
        h["x-ms-request-server-encrypted"] = "true"
        return Response(status=201, headers=h, body=b"", media_type=None)

    blobs = store.container_blobs(container) if store.container_exists(container) else {}
    entry = blobs.get(blob)

    if method in ("GET", "HEAD"):                      # get / head blob
        if not store.container_exists(container):
            return _err(404, "ContainerNotFound",
                        "The specified container does not exist.")
        if entry is None:
            return _err(404, "BlobNotFound", "The specified blob does not exist.")
        h = _base_headers()
        h["etag"] = entry["etag"]
        h["last-modified"] = entry["last_modified"]
        h["content-length"] = str(entry["size"])
        h["content-type"] = entry["content_type"]
        h["content-md5"] = entry["md5"]
        h["x-ms-blob-type"] = entry["blob_type"]
        h["accept-ranges"] = "bytes"
        h["x-ms-server-encrypted"] = "true"
        for mk, mv in entry.get("metadata", {}).items():
            h[f"x-ms-meta-{mk}"] = mv
        if method == "HEAD":
            return Response(status=200, headers=h, body=b"", media_type=None)
        # Range support — the azure-storage-blob SDK downloads via a ranged GET
        # (Range / x-ms-range: bytes=start-end) and requires 206 + Content-Range.
        data = entry["data"]
        rng = headers.get("x-ms-range") or headers.get("range") or ""
        m = re.match(r"bytes=(\d*)-(\d*)", rng.strip()) if rng else None
        if m and (m.group(1) or m.group(2)):
            total = len(data)
            start = int(m.group(1)) if m.group(1) else 0
            end = int(m.group(2)) if m.group(2) else total - 1
            end = min(end, total - 1)
            if start > end or start >= total:
                er = _err(416, "InvalidRange", "The range specified is invalid.")
                er.headers["content-range"] = f"bytes */{total}"
                return er
            sl = data[start:end + 1]
            h["content-length"] = str(len(sl))
            h["content-range"] = f"bytes {start}-{end}/{total}"
            return Response(status=206, headers=h, body=sl, media_type=entry["content_type"])
        return Response(status=200, headers=h, body=data, media_type=entry["content_type"])

    if method == "DELETE":                             # delete blob
        if not store.container_exists(container):
            return _err(404, "ContainerNotFound",
                        "The specified container does not exist.")
        if entry is None:
            return _err(404, "BlobNotFound", "The specified blob does not exist.")
        blobs.pop(blob, None)
        return Response(status=202, headers=_base_headers(), body=b"", media_type=None)

    return _err(400, "UnsupportedHttpVerb", f"Unsupported blob operation {method}")


# ── XML builders ────────────────────────────────────────────────────────────
def _list_containers(store: AzureBlobStore) -> Response:
    parts = ['<?xml version="1.0" encoding="utf-8"?>',
             '<EnumerationResults><Containers>']
    for name in sorted(store.containers):
        meta = store.containers[name]
        parts.append(
            "<Container>"
            f"<Name>{escape(name)}</Name>"
            "<Properties>"
            f"<Last-Modified>{escape(meta.get('created', _now_http()))}</Last-Modified>"
            f"<Etag>{escape(_etag())}</Etag>"
            "<LeaseStatus>unlocked</LeaseStatus>"
            "<LeaseState>available</LeaseState>"
            "</Properties>"
            "</Container>"
        )
    parts.append("</Containers><NextMarker /></EnumerationResults>")
    return _xml(200, "".join(parts))


def _list_blobs(store: AzureBlobStore, container: str, query: dict) -> Response:
    prefix = query.get("prefix", "") or ""
    blobs = store.container_blobs(container)
    parts = ['<?xml version="1.0" encoding="utf-8"?>',
             f'<EnumerationResults ContainerName="{escape(container)}"><Blobs>']
    for name in sorted(blobs):
        if not name.startswith(prefix):
            continue
        e = blobs[name]
        parts.append(
            "<Blob>"
            f"<Name>{escape(name)}</Name>"
            "<Properties>"
            f"<Last-Modified>{escape(e['last_modified'])}</Last-Modified>"
            f"<Etag>{escape(e['etag'])}</Etag>"
            f"<Content-Length>{e['size']}</Content-Length>"
            f"<Content-Type>{escape(e['content_type'])}</Content-Type>"
            f"<Content-MD5>{escape(e['md5'])}</Content-MD5>"
            f"<BlobType>{escape(e['blob_type'])}</BlobType>"
            "</Properties>"
            "</Blob>"
        )
    parts.append("</Blobs><NextMarker /></EnumerationResults>")
    return _xml(200, "".join(parts))
