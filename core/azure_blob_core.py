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

v4 C0b — the offline appliance serves its Blob wire through THIS core (over
core/appliance_stores.py) instead of the retired core/azure_dataplane handler. The
legacy-only behaviours were ported here (tests/conformance/test_c0b_legacy_parity_core.py):
`x-ms-blob-content-type` wins over the request Content-Type, suffix ranges
(`bytes=-N`), `x-ms-creation-time`, lease properties in listings, and store hooks
for an external byte store (Azurite write-through + lazy fetch of pre-v4 blobs).
The appliance names the account explicitly (`dispatch(..., account=...)`, the
`/azure-data/blob/{account}/...` route) instead of sniffing it from SharedKey.

An OPTIONAL leading `/{account}` path segment (Azurite style
`/{account}/{container}/{blob}`) is tolerated — the well-known
`/devstoreaccount1/` prefix is stripped.

Per-account namespaces: a path-style request whose `Authorization: SharedKey
{account}:{sig}` (the header every azure-storage-blob SDK sends) names the
account in its first path segment is scoped to THAT account — its containers
are invisible to other accounts, like separate `{account}.blob.core.windows.net`
endpoints. Requests without a SharedKey account (or for `devstoreaccount1`)
use the default namespace, exactly as before.
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

    def persist(self) -> None:
        """Write-through hook (no-op in-memory; a backed subclass overrides it)."""

    # ── optional external byte-store hooks (no-ops here; the appliance mirrors
    #    blob bytes to Azurite when it is configured) ──────────────────────
    def mirror_put(self, container: str, blob: str, entry: dict) -> None:
        """Best-effort write-through of a blob to an external byte store."""

    def mirror_delete(self, container: str, blob: str) -> None:
        """Best-effort delete in the external byte store."""

    def mirror_delete_container(self, container: str) -> None:
        """Best-effort container delete in the external byte store."""

    def fetch_bytes(self, container: str, blob: str):
        """Bytes of a blob whose entry carries no inline data (pre-v4 blobs that
        live only in the external byte store). None = unknown."""
        return None


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


_SHAREDKEY_RE = re.compile(r"^\s*SharedKey(?:Lite)?\s+([a-z0-9]{1,64}):", re.I)


def _account_scope(p: str, headers: dict) -> tuple[str, str]:
    """(account, path-without-account) when the SharedKey account names the first
    path segment (path-style `/{account}/...`); ("", p) otherwise."""
    m = _SHAREDKEY_RE.match(headers.get("authorization", "") or "")
    acct = m.group(1) if m else ""
    if not acct or acct == "devstoreaccount1":
        return "", p
    if p == "/" + acct:
        return acct, "/"
    if p.startswith("/" + acct + "/"):
        return acct, p[len(acct) + 1:]
    return "", p


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store: AzureBlobStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", account: str | None = None) -> Response:
    """`account` (appliance): the storage account the route already resolved — the
    path is then relative to it (`/{container}[/{blob}]`) and the namespace is that
    account's. None (Nano / dev_server): the account is read from SharedKey."""
    query = query or {}
    headers = {(k or "").lower(): v for k, v in (headers or {}).items()}
    method = method.upper()

    p = path.split("?", 1)[0]
    if account is not None:
        acct = account.lower()
        p = p or "/"
    else:
        p = _strip_account(p)
        acct, p = _account_scope(p, headers)
    p = p.rstrip("/") if p != "/" else p
    segs = [unquote(s) for s in p.split("/") if s != ""]

    comp = query.get("comp", "")
    restype = query.get("restype", "")

    # ---- account-level: list containers  GET /?comp=list ----
    if not segs:
        if method == "GET" and comp == "list":
            return _list_containers(store, acct)
        return _err(400, "InvalidUri", f"Unsupported account operation {method}")

    display = segs[0]
    # Container names never contain "/", so "{account}/{container}" keys cannot
    # collide with default-namespace containers.
    container = f"{acct}/{display}" if acct else display

    # ---- container-level: /{container} ----
    if len(segs) == 1:
        if restype == "container":
            if method == "PUT":                       # create container
                if store.container_exists(container):
                    return _err(409, "ContainerAlreadyExists",
                                "The specified container already exists.")
                store.create_container(container)
                store.persist()
                h = _base_headers()
                h["etag"] = _etag()
                h["last-modified"] = _now_http()
                return Response(status=201, headers=h, body=b"", media_type=None)
            if method == "DELETE":                    # delete container
                if not store.container_exists(container):
                    return _err(404, "ContainerNotFound",
                                "The specified container does not exist.")
                store.delete_container(container)
                store.persist()
                store.mirror_delete_container(container)
                return Response(status=202, headers=_base_headers(),
                                body=b"", media_type=None)
            if method == "GET" and comp == "list":    # list blobs
                if not store.container_exists(container):
                    return _err(404, "ContainerNotFound",
                                "The specified container does not exist.")
                return _list_blobs(store, container, query, display)
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
        # The blob's Content-Type is `x-ms-blob-content-type` when sent (that is what
        # azure-storage-blob's ContentSettings / `az storage blob upload
        # --content-type` set); the request's own Content-Type is the fallback.
        content_type = (headers.get("x-ms-blob-content-type") or headers.get("content-type")
                        or "application/octet-stream")
        now = _now_http()
        prev = store.container_blobs(container).get(blob) or {}
        entry = {
            "data": body,
            "size": len(body),
            "content_type": content_type,
            "blob_type": blob_type,
            "etag": _etag(),
            "last_modified": now,
            "created": prev.get("created") or now,
            "md5": _md5_b64(body),
            "metadata": {k[len("x-ms-meta-"):]: v for k, v in headers.items()
                         if k.startswith("x-ms-meta-")},
        }
        store.container_blobs(container)[blob] = entry
        store.persist()
        store.mirror_put(container, blob, entry)
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
        if entry.get("md5"):
            h["content-md5"] = entry["md5"]
        h["x-ms-blob-type"] = entry["blob_type"]
        h["accept-ranges"] = "bytes"
        h["x-ms-server-encrypted"] = "true"
        h["x-ms-creation-time"] = entry.get("created") or entry["last_modified"]
        h["x-ms-lease-status"] = "unlocked"
        h["x-ms-lease-state"] = "available"
        for mk, mv in entry.get("metadata", {}).items():
            h[f"x-ms-meta-{mk}"] = mv
        if method == "HEAD":
            return Response(status=200, headers=h, body=b"", media_type=None)
        # Range support — the azure-storage-blob SDK downloads via a ranged GET
        # (Range / x-ms-range: bytes=start-end) and requires 206 + Content-Range.
        data = _entry_bytes(store, container, blob, entry)
        rng = headers.get("x-ms-range") or headers.get("range") or ""
        m = re.match(r"bytes=(\d*)-(\d*)", rng.strip()) if rng else None
        if m and (m.group(1) or m.group(2)):
            total = len(data)
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else total - 1
            else:                                     # suffix range: the last N bytes
                start, end = max(total - int(m.group(2)), 0), total - 1
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
        store.persist()
        store.mirror_delete(container, blob)
        return Response(status=202, headers=_base_headers(), body=b"", media_type=None)

    return _err(400, "UnsupportedHttpVerb", f"Unsupported blob operation {method}")


def _entry_bytes(store: AzureBlobStore, container: str, blob: str, entry: dict) -> bytes:
    """A blob's bytes: inline `data`, else the store's external byte store."""
    data = entry.get("data")
    if data is None:
        data = store.fetch_bytes(container, blob)
    if isinstance(data, str):
        data = data.encode("utf-8")
    return bytes(data or b"")


# ── XML builders ────────────────────────────────────────────────────────────
def _list_containers(store: AzureBlobStore, acct: str = "") -> Response:
    parts = ['<?xml version="1.0" encoding="utf-8"?>',
             '<EnumerationResults><Containers>']
    for key in sorted(store.containers):
        if acct:
            if not key.startswith(acct + "/"):
                continue
            name = key[len(acct) + 1:]
        elif "/" in key:
            continue                      # another account's container
        else:
            name = key
        meta = store.containers[key]
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


def _list_blobs(store: AzureBlobStore, container: str, query: dict, display: str | None = None) -> Response:
    prefix = query.get("prefix", "") or ""
    blobs = store.container_blobs(container)
    parts = ['<?xml version="1.0" encoding="utf-8"?>',
             f'<EnumerationResults ContainerName="{escape(display or container)}"><Blobs>']
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
            + (f"<Content-MD5>{escape(e['md5'])}</Content-MD5>" if e.get("md5") else "") +
            f"<BlobType>{escape(e['blob_type'])}</BlobType>"
            "<LeaseStatus>unlocked</LeaseStatus><LeaseState>available</LeaseState>"
            f"<Creation-Time>{escape(e.get('created') or e['last_modified'])}</Creation-Time>"
            "</Properties>"
            "</Blob>"
        )
    parts.append("</Blobs><NextMarker /></EnumerationResults>")
    return _xml(200, "".join(parts))
