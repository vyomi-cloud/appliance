"""Real Azure Blob object bytes via Azurite.

Mirror of ``core/gcp_gcs_store`` (fake-gcs) for Azure: the simulator keeps
*speaking* the Azurite-compatible Blob REST surface to clients (so unmodified
``azure-storage-blob`` SDKs round-trip), but the actual object bytes are stored
in **Azurite** — the official open-source Azure Storage emulator — instead of an
in-process dict. Bytes therefore survive simulator restarts and use a real,
well-known emulator (parity with MinIO for S3 + fake-gcs-server for GCS).

If ``CLOUDLEARN_AZURITE_URL`` is unset/unreachable, callers fall back to the
in-process store in ``core/azure_dataplane`` (so dev/test without the container
still works).

Storage model
-------------
The simulator supports arbitrary ``(space, account, container)`` triples, but
Azurite (default) only knows the well-known ``devstoreaccount1`` account. To map
the richer namespace onto a single Azurite account *reversibly*, we use **one
Azurite container per (space, account)** and fold the simulator container + blob
into the Azurite **blob name**:

    azurite_container = "vyomi-" + sha1(space|account)[:24]   # always valid
    azurite_blob      = "{sim_container}/{sim_blob}"

Azure blob names are permissive (UTF-8, slashes allowed), so this round-trips
cleanly. An empty simulator container is represented by a marker blob so it
still enumerates.
"""
from __future__ import annotations

import email.utils
import hashlib
import os

# Azurite's well-known development account + key.
_WK_ACCOUNT = "devstoreaccount1"
_WK_KEY = ("Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
           "K1SZFPTOtr/KBHBeksoGMGw==")
_MARKER = ".vyomi-container-keep"


def _base() -> str:
    return os.environ.get("CLOUDLEARN_AZURITE_URL", "").rstrip("/")


def available() -> bool:
    return bool(_base())


def _conn_str() -> str:
    return ("DefaultEndpointsProtocol=http;"
            f"AccountName={_WK_ACCOUNT};AccountKey={_WK_KEY};"
            f"BlobEndpoint={_base()}/{_WK_ACCOUNT};")


def _svc():
    from azure.storage.blob import BlobServiceClient
    return BlobServiceClient.from_connection_string(_conn_str())


def _azurite_container(sid: str, account: str) -> str:
    """Deterministic, always-valid Azurite container name for a (space, account).
    Need not be reversible — it is recomputed from (sid, account) every time."""
    h = hashlib.sha1(f"{sid}|{account}".encode("utf-8")).hexdigest()[:24]
    return "vyomi-" + h


def _http_date(dt=None) -> str:
    if dt is None:
        return email.utils.formatdate(usegmt=True)
    try:
        return email.utils.format_datetime(dt, usegmt=True)
    except Exception:
        return email.utils.formatdate(usegmt=True)


def _client(sid: str, account: str, blob_name: str):
    return _svc().get_blob_client(_azurite_container(sid, account), blob_name)


def _ccli(sid: str, account: str):
    return _svc().get_container_client(_azurite_container(sid, account))


def ensure_container(sid: str, account: str) -> None:
    """Create the backing Azurite container (idempotent)."""
    from azure.core.exceptions import ResourceExistsError
    try:
        _ccli(sid, account).create_container()
    except ResourceExistsError:
        pass


# ---------------------------------------------------------------------------
# Simulator-container operations (a sim container == a blob-name prefix)
# ---------------------------------------------------------------------------
def create_container(sid: str, account: str, container: str, public_access: str | None = None) -> None:
    """Mark a simulator container as existing (so it enumerates while empty),
    storing public_access level as metadata on the marker blob."""
    ensure_container(sid, account)
    meta = {"public_access": public_access} if public_access else {}
    _client(sid, account, f"{container}/{_MARKER}").upload_blob(b"", overwrite=True, metadata=meta)


def get_container_props(sid: str, account: str, container: str) -> dict:
    try:
        props = _client(sid, account, f"{container}/{_MARKER}").get_blob_properties()
        meta = props.metadata or {}
        return {
            "name": container,
            "created": _http_date(props.last_modified),
            "public_access": meta.get("public_access"),
        }
    except Exception:
        return {"name": container, "created": _http_date()}


def list_containers(sid: str, account: str) -> list[str]:
    names: set[str] = set()
    try:
        for b in _ccli(sid, account).list_blobs():
            seg = str(b.name).split("/", 1)[0]
            if seg:
                names.add(seg)
    except Exception:
        return []
    return sorted(names)


def delete_container(sid: str, account: str, container: str) -> int:
    n = 0
    try:
        cc = _ccli(sid, account)
        prefix = f"{container}/"
        for b in list(cc.list_blobs(name_starts_with=prefix)):
            try:
                cc.delete_blob(b.name)
                if not str(b.name).endswith("/" + _MARKER):
                    n += 1
            except Exception:
                pass
    except Exception:
        pass
    return n


# ---------------------------------------------------------------------------
# Blob operations
# ---------------------------------------------------------------------------
def put_blob(sid: str, account: str, container: str, blob: str, data: bytes,
             props: dict | str | None = None, meta: dict | None = None) -> dict:
    from azure.storage.blob import ContentSettings
    from core.azure_blob_core import blob_content_headers
    if isinstance(props, str) or props is None:
        props = blob_content_headers({"content-type": props} if props else {})
    ensure_container(sid, account)
    bc = _client(sid, account, f"{container}/{blob}")
    cs = ContentSettings(
        content_type=props.get("content_type") or "application/octet-stream",
        cache_control=props.get("cache_control"),
        content_disposition=props.get("content_disposition"),
        content_encoding=props.get("content_encoding"),
        content_language=props.get("content_language"),
    )
    bc.upload_blob(data, overwrite=True, content_settings=cs,
                   metadata={k: str(v) for k, v in (meta or {}).items()})
    p = bc.get_blob_properties()
    cs_res = p.content_settings
    ret_props = {
        "content_type": (cs_res.content_type if cs_res and cs_res.content_type else props.get("content_type")) or "application/octet-stream",
    }
    if cs_res and cs_res.cache_control:
        ret_props["cache_control"] = cs_res.cache_control
    elif props.get("cache_control"):
        ret_props["cache_control"] = props["cache_control"]
    if cs_res and cs_res.content_disposition:
        ret_props["content_disposition"] = cs_res.content_disposition
    elif props.get("content_disposition"):
        ret_props["content_disposition"] = props["content_disposition"]
    if cs_res and cs_res.content_encoding:
        ret_props["content_encoding"] = cs_res.content_encoding
    elif props.get("content_encoding"):
        ret_props["content_encoding"] = props["content_encoding"]
    if cs_res and cs_res.content_language:
        ret_props["content_language"] = cs_res.content_language
    elif props.get("content_language"):
        ret_props["content_language"] = props["content_language"]

    return {"etag": p.etag, "mtime": _http_date(p.last_modified),
            "ct": ret_props["content_type"], "props": ret_props}


def get_blob(sid: str, account: str, container: str, blob: str) -> dict | None:
    from azure.core.exceptions import ResourceNotFoundError
    try:
        bc = _client(sid, account, f"{container}/{blob}")
        stream = bc.download_blob()
        data = stream.readall()
        props = bc.get_blob_properties()
        cs_res = props.content_settings
        ret_props = {
            "content_type": (cs_res.content_type if cs_res and cs_res.content_type else "application/octet-stream")
        }
        if cs_res:
            if cs_res.cache_control:
                ret_props["cache_control"] = cs_res.cache_control
            if cs_res.content_disposition:
                ret_props["content_disposition"] = cs_res.content_disposition
            if cs_res.content_encoding:
                ret_props["content_encoding"] = cs_res.content_encoding
            if cs_res.content_language:
                ret_props["content_language"] = cs_res.content_language
        return {"data": data, "ct": ret_props["content_type"], "props": ret_props,
                "etag": props.etag, "mtime": _http_date(props.last_modified),
                "meta": dict(props.metadata or {})}
    except ResourceNotFoundError:
        return None
    except Exception:
        return None


def blob_props(sid: str, account: str, container: str, blob: str) -> dict | None:
    from azure.core.exceptions import ResourceNotFoundError
    try:
        props = _client(sid, account, f"{container}/{blob}").get_blob_properties()
        cs_res = props.content_settings
        ret_props = {
            "content_type": (cs_res.content_type if cs_res and cs_res.content_type else "application/octet-stream")
        }
        if cs_res:
            if cs_res.cache_control:
                ret_props["cache_control"] = cs_res.cache_control
            if cs_res.content_disposition:
                ret_props["content_disposition"] = cs_res.content_disposition
            if cs_res.content_encoding:
                ret_props["content_encoding"] = cs_res.content_encoding
            if cs_res.content_language:
                ret_props["content_language"] = cs_res.content_language
        return {"size": props.size, "ct": ret_props["content_type"], "props": ret_props,
                "etag": props.etag, "mtime": _http_date(props.last_modified),
                "meta": dict(props.metadata or {})}
    except ResourceNotFoundError:
        return None
    except Exception:
        return None


def list_blobs(sid: str, account: str, container: str, prefix: str = "") -> list[dict]:
    out: list[dict] = []
    try:
        cc = _ccli(sid, account)
        base = f"{container}/"
        for b in cc.list_blobs(name_starts_with=base + prefix, include=["metadata"]):
            rel = str(b.name)[len(base):]
            if rel == _MARKER:
                continue
            cs = getattr(b, "content_settings", None)
            ret_props = {
                "content_type": (cs.content_type if cs and cs.content_type else "application/octet-stream")
            }
            if cs:
                if cs.cache_control:
                    ret_props["cache_control"] = cs.cache_control
                if cs.content_disposition:
                    ret_props["content_disposition"] = cs.content_disposition
                if cs.content_encoding:
                    ret_props["content_encoding"] = cs.content_encoding
                if cs.content_language:
                    ret_props["content_language"] = cs.content_language
            out.append({"name": rel, "size": int(b.size or 0),
                        "contentType": ret_props["content_type"],
                        "props": ret_props,
                        "etag": getattr(b, "etag", ""),
                        "lastModified": _http_date(getattr(b, "last_modified", None))})
    except Exception:
        return []
    return sorted(out, key=lambda o: o["name"])


def delete_blob(sid: str, account: str, container: str, blob: str) -> bool:
    from azure.core.exceptions import ResourceNotFoundError
    try:
        _client(sid, account, f"{container}/{blob}").delete_blob()
        return True
    except ResourceNotFoundError:
        return False
    except Exception:
        return False
