"""S3 object-CRUD core — substrate-independent, faithfully extracted from
routes/aws_s3.py so the SAME logic runs in Pro/Max (FastAPI), Nano (Pyodide),
and tests. NO fastapi / boto3 / socket / subprocess imports → loads under
Pyodide. Persists through the ObjectStore seam (core/object_store.py).

Each operation takes plain inputs (bytes/dicts) and returns an `S3Response`
(status, headers, body) — the native AWS S3 wire shapes (XML errors, ETag,
x-amz-version-id, ListBucketResult, byte-range 206). A thin FastAPI adapter
(Pro/Max) or the service-worker bridge (Nano) maps Request<->S3Response.

Scope (v1 slice): PutObject, GetObject (+range), HeadObject, DeleteObject,
ListObjectsV2 — the conformance core. Multipart / tagging / ACL / copy reuse
the same helpers and slot in next.
"""
from __future__ import annotations

import copy
import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.object_store import ObjectStore

S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"


@dataclass
class S3Response:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = None


# ── primitives (verbatim from routes/aws_s3.py) ───────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _iso_to_http_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
    except Exception:
        return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _etag(data: bytes) -> str:
    return f'"{hashlib.md5(data).hexdigest()}"'


def _req_id() -> str:
    return uuid.uuid4().hex.upper()[:16]


def _decode_aws_chunked(body: bytes, headers: dict) -> bytes:
    """Strip AWS SDK v2 ``aws-chunked`` framing (see routes/aws_s3.py for the
    full rationale — modern SDKs stream PutObject with chunk-signature headers
    that would corrupt the stored object if kept)."""
    ce = (headers.get("content-encoding") or "").lower()
    sha = headers.get("x-amz-content-sha256", "") or ""
    if "aws-chunked" not in ce and not sha.startswith("STREAMING"):
        return body
    out = bytearray()
    i, n = 0, len(body)
    while i < n:
        j = body.find(b"\r\n", i)
        if j == -1:
            break
        size_field = body[i:j].split(b";", 1)[0].strip()
        i = j + 2
        try:
            size = int(size_field, 16)
        except ValueError:
            break
        if size == 0:
            break
        out += body[i:i + size]
        i += size
        if body[i:i + 2] == b"\r\n":
            i += 2
    return bytes(out)


# ── response builders (return S3Response, not FastAPI Response) ────────────
def _amz_headers(extra: dict | None = None) -> dict:
    h = {"x-amz-request-id": _req_id(), "x-amz-id-2": uuid.uuid4().hex}
    if extra:
        h.update(extra)
    return h


def _xml_response(content: str, status: int = 200, extra: dict | None = None) -> S3Response:
    return S3Response(status=status, headers=_amz_headers(extra),
                      body=content.encode(), media_type="application/xml")


def _empty_response(status: int = 204, extra: dict | None = None) -> S3Response:
    return S3Response(status=status, headers=_amz_headers(extra), body=b"")


def _error_xml(code: str, message: str, resource: str = "/", status: int = 400) -> S3Response:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f"<Error><Code>{code}</Code><Message>{message}</Message>"
           f"<Resource>{resource}</Resource><RequestId>{_req_id()}</RequestId></Error>")
    return _xml_response(xml, status=status)


def _delete_marker_response(resource: str, last_modified: str, status: int = 405) -> S3Response:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           "<Error><Code>MethodNotAllowed</Code>"
           "<Message>The specified version is a delete marker.</Message>"
           f"<Resource>{resource}</Resource><RequestId>{_req_id()}</RequestId></Error>")
    return _xml_response(xml, status=status, extra={
        "x-amz-delete-marker": "true", "Last-Modified": _iso_to_http_date(last_modified)})


# ── versioning + entry helpers (verbatim, but over `store` not globals) ────
def _new_version_id(store: ObjectStore, bucket: str) -> str:
    return "null" if store.versioning_status(bucket) == "Suspended" else uuid.uuid4().hex


def _refresh_object_entry(entry: dict) -> None:
    versions = entry.get("versions", [])
    for idx, v in enumerate(versions):
        v["is_latest"] = idx == 0
    if not versions:
        entry.update({"current_version_id": "", "is_delete_marker": False, "data": b"",
                      "size": 0, "content_type": "application/octet-stream",
                      "last_modified": _now(), "etag": "", "storage_class": "STANDARD",
                      "metadata": {}, "tags": {}})
        return
    cur = versions[0]
    entry.update({
        "current_version_id": cur.get("version_id", "null"),
        "version_id": cur.get("version_id", "null"),
        "is_delete_marker": bool(cur.get("is_delete_marker", False)),
        "data": cur.get("data", b"") if not cur.get("is_delete_marker") else b"",
        "size": int(cur.get("size", 0) or 0),
        "content_type": cur.get("content_type", "application/octet-stream"),
        "last_modified": cur.get("last_modified", _now()),
        "etag": cur.get("etag", ""),
        "storage_class": cur.get("storage_class", "STANDARD"),
        "metadata": copy.deepcopy(cur.get("metadata", {})),
        "tags": copy.deepcopy(cur.get("tags", {})),
    })


def _ensure_object_entry(store: ObjectStore, bucket: str, key: str, create: bool = False) -> dict | None:
    bucket_objects = store.bucket_objects(bucket)
    entry = bucket_objects.get(key)
    if not isinstance(entry, dict):
        if not create:
            return None
        entry = {"versions": []}
        bucket_objects[key] = entry
    if not isinstance(entry.get("versions"), list):
        entry["versions"] = []
    if entry["versions"]:
        _refresh_object_entry(entry)
    return entry


def _make_version_record(*, data: bytes = b"", content_type: str = "application/octet-stream",
                         storage_class: str = "STANDARD", metadata: dict | None = None,
                         tags: dict | None = None, version_id: str | None = None,
                         delete_marker: bool = False, last_modified: str | None = None,
                         etag: str | None = None) -> dict:
    return {
        "version_id": version_id or "null",
        "is_delete_marker": delete_marker,
        "data": b"" if delete_marker else data,
        "size": 0 if delete_marker else len(data),
        "content_type": "application/octet-stream" if delete_marker else content_type,
        "last_modified": last_modified or _now(),
        "etag": etag or ("" if delete_marker else _etag(data)),
        "storage_class": storage_class,
        "metadata": copy.deepcopy(metadata or {}),
        "tags": copy.deepcopy(tags or {}),
    }


def _find_version(entry: dict | None, version_id: str | None) -> dict | None:
    if not entry:
        return None
    versions = entry.get("versions", [])
    if not version_id:
        return versions[0] if versions else None
    for v in versions:
        if str(v.get("version_id")) == str(version_id):
            return v
    return None


def _write_object_version(store: ObjectStore, bucket: str, key: str, version: dict,
                          replace_version_id: str | None = None) -> dict:
    if not version.get("is_delete_marker"):
        store.enforce_storage_cap(int(version.get("size") or len(version.get("data") or b"")))
    entry = _ensure_object_entry(store, bucket, key, create=True)
    versions = entry.setdefault("versions", [])
    if replace_version_id == "__overwrite__":
        versions = [version]
    elif replace_version_id is not None:
        for idx, ex in enumerate(versions):
            if str(ex.get("version_id")) == str(replace_version_id):
                versions[idx] = version
                break
        else:
            versions.insert(0, version)
    else:
        versions.insert(0, version)
    entry["versions"] = [copy.deepcopy(v) for v in versions]
    _refresh_object_entry(entry)
    if not version.get("is_delete_marker") and version.get("data") is not None:
        store.mirror_put(bucket, key, version["data"],
                         content_type=version.get("content_type", "application/octet-stream"),
                         metadata=version.get("metadata"))
    return entry


def _delete_version(store: ObjectStore, bucket: str, key: str, version_id: str) -> bool:
    entry = _ensure_object_entry(store, bucket, key, create=False)
    if not entry:
        return False
    versions = entry.get("versions", [])
    for idx, v in enumerate(versions):
        if str(v.get("version_id")) == str(version_id):
            versions.pop(idx)
            if versions:
                _refresh_object_entry(entry)
            else:
                store.bucket_objects(bucket).pop(key, None)
            return True
    return False


def _insert_simple_delete_marker(store: ObjectStore, bucket: str, key: str) -> dict:
    vid = _new_version_id(store, bucket)
    marker = _make_version_record(delete_marker=True, version_id=vid)
    return _write_object_version(store, bucket, key, marker)


# ── the 5 operations (faithful ports of the handler bodies) ───────────────
def put_object(store: ObjectStore, bucket: str, key: str, body: bytes, headers: dict) -> S3Response:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    data = _decode_aws_chunked(body or b"", headers)
    content_type = headers.get("content-type", "application/octet-stream")
    storage_class = headers.get("x-amz-storage-class", "STANDARD")
    user_meta = {h[11:]: v for h, v in headers.items() if h.startswith("x-amz-meta-")}
    vstatus = store.versioning_status(bucket)
    vid = _new_version_id(store, bucket) if vstatus == "Enabled" else "null"
    version = _make_version_record(data=data, content_type=content_type,
                                   storage_class=storage_class, metadata=user_meta,
                                   version_id=vid, delete_marker=False)
    replace = "__overwrite__" if vstatus == "Disabled" else ("null" if vstatus == "Suspended" else None)
    entry = _write_object_version(store, bucket, key, version, replace_version_id=replace)
    return _empty_response(200, {"ETag": version["etag"],
                                 "x-amz-version-id": entry.get("current_version_id", vid)})


def head_object(store: ObjectStore, bucket: str, key: str, query: dict, headers: dict) -> S3Response:
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}/{key}", 404)
    entry = _ensure_object_entry(store, bucket, key, create=False)
    obj = _find_version(entry, (query or {}).get("versionId"))
    if obj and obj.get("is_delete_marker"):
        if (query or {}).get("versionId"):
            return _delete_marker_response(f"/{bucket}/{key}", obj.get("last_modified", _now()))
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    if not obj:
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    h = {"Content-Length": str(obj["size"]), "Content-Type": obj["content_type"],
         "ETag": obj["etag"], "Last-Modified": _iso_to_http_date(obj["last_modified"]),
         "x-amz-storage-class": obj.get("storage_class", "STANDARD"),
         "x-amz-version-id": obj.get("version_id", "null")}
    for k, v in obj.get("metadata", {}).items():
        h[f"x-amz-meta-{k}"] = v
    return _empty_response(200, h)


def get_object(store: ObjectStore, bucket: str, key: str, query: dict, headers: dict) -> S3Response:
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    query = query or {}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    entry = _ensure_object_entry(store, bucket, key, create=False)
    obj = _find_version(entry, query.get("versionId"))
    if obj and obj.get("is_delete_marker"):
        if query.get("versionId"):
            return _delete_marker_response(f"/{bucket}/{key}", obj.get("last_modified", _now()))
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    if not obj:
        return _error_xml("NoSuchKey", "The specified key does not exist.", f"/{bucket}/{key}", 404)
    data = obj["data"]
    status = 200
    content_range = None
    rng = headers.get("range")
    if rng:
        m = re.match(r"bytes=(\d+)-(\d*)", rng)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else len(data) - 1
            end = min(end, len(data) - 1)
            data = data[start:end + 1]
            status = 206
            content_range = f"bytes {start}-{end}/{obj['size']}"
    h = {"Content-Type": obj["content_type"], "ETag": obj["etag"],
         "Last-Modified": _iso_to_http_date(obj["last_modified"]),
         "Content-Length": str(len(data)),
         "x-amz-storage-class": obj.get("storage_class", "STANDARD"),
         "x-amz-version-id": obj.get("version_id", "null"),
         "x-amz-request-id": _req_id(), "x-amz-id-2": uuid.uuid4().hex}
    if content_range:
        h["Content-Range"] = content_range
    for k, v in obj.get("metadata", {}).items():
        h[f"x-amz-meta-{k}"] = v
    return S3Response(status=status, headers=h, body=data, media_type=obj["content_type"])


def delete_object(store: ObjectStore, bucket: str, key: str, query: dict, headers: dict) -> S3Response:
    query = query or {}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    vid = query.get("versionId")
    if vid:
        if not _delete_version(store, bucket, key, vid):
            return _error_xml("NoSuchVersion", "The specified version does not exist.", f"/{bucket}/{key}", 404)
        return _empty_response(204, {"x-amz-version-id": vid})
    status = store.versioning_status(bucket)
    if status == "Disabled":
        store.bucket_objects(bucket).pop(key, None)
        store.mirror_delete(bucket, key)
        return _empty_response(204)
    entry = _insert_simple_delete_marker(store, bucket, key)
    vid = entry.get("current_version_id", "null") if isinstance(entry, dict) else "null"
    return _empty_response(204, {"x-amz-delete-marker": "true", "x-amz-version-id": vid})


def list_objects_v2(store: ObjectStore, bucket: str, query: dict) -> S3Response:
    query = query or {}
    if not store.bucket_exists(bucket):
        return _error_xml("NoSuchBucket", "The specified bucket does not exist.", f"/{bucket}", 404)
    prefix = query.get("prefix", "") or ""
    delimiter = query.get("delimiter", "") or ""
    try:
        max_keys = int(query.get("max-keys", 1000))
    except (TypeError, ValueError):
        max_keys = 1000
    bucket_objects = store.bucket_objects(bucket)
    keys, common = [], set()
    for key in sorted(bucket_objects):
        entry = bucket_objects[key]
        versions = entry.get("versions", []) if isinstance(entry, dict) else []
        if not versions or versions[0].get("is_delete_marker"):
            continue
        if prefix and not key.startswith(prefix):
            continue
        if delimiter:
            rest = key[len(prefix):]
            if delimiter in rest:
                common.add(prefix + rest.split(delimiter, 1)[0] + delimiter)
                continue
        keys.append((key, versions[0]))
    truncated = len(keys) > max_keys
    keys = keys[:max_keys]
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', f'<ListBucketResult xmlns="{S3_NS}">',
             f"<Name>{bucket}</Name>", f"<Prefix>{prefix}</Prefix>",
             f"<KeyCount>{len(keys)}</KeyCount>", f"<MaxKeys>{max_keys}</MaxKeys>",
             f"<Delimiter>{delimiter}</Delimiter>" if delimiter else "",
             f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>"]
    for key, v in keys:
        parts += ["<Contents>", f"<Key>{key}</Key>",
                  f"<LastModified>{v.get('last_modified', _now())}</LastModified>",
                  f"<ETag>{v.get('etag', '')}</ETag>", f"<Size>{v.get('size', 0)}</Size>",
                  "<StorageClass>STANDARD</StorageClass>",
                  "<Owner><ID>simulator</ID><DisplayName>cloudlearn-simulator</DisplayName></Owner>",
                  "</Contents>"]
    for cp in sorted(common):
        parts += ["<CommonPrefixes>", f"<Prefix>{cp}</Prefix>", "</CommonPrefixes>"]
    parts.append("</ListBucketResult>")
    return _xml_response("".join(parts))


# ── native-S3 wire dispatcher (method + path → operation) ─────────────────
# The single routing point for the native AWS S3 wire protocol — what an
# unmodified aws-cli / SDK speaks. Shared by the Nano relay/bridge (tab side)
# and, on convergence, the appliance's routes/aws_s3.py. Path is the raw
# request path, e.g. "/my-bucket/a/key.txt".
def dispatch(store: ObjectStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> S3Response:
    query = query or {}
    headers = headers or {}
    raw = (path or "/").lstrip("/")
    bucket, _, key = raw.partition("/")
    method = (method or "GET").upper()
    if not bucket:
        return _error_xml("InvalidRequest", "Missing bucket.", "/", 400)
    if not key:
        # bucket-level
        if method in ("PUT",):
            store.create_bucket(bucket)
            return _empty_response(200, {"Location": f"/{bucket}"})
        if method in ("GET",):
            return list_objects_v2(store, bucket, query)
        if method in ("HEAD",):
            return _empty_response(200 if store.bucket_exists(bucket) else 404)
        if method in ("DELETE",):
            store.objects.pop(bucket, None)
            store.buckets.pop(bucket, None)
            return _empty_response(204)
        return _error_xml("MethodNotAllowed", method, f"/{bucket}", 405)
    # object-level
    if method == "PUT":
        return put_object(store, bucket, key, body, headers)
    if method == "GET":
        return get_object(store, bucket, key, query, headers)
    if method == "HEAD":
        return head_object(store, bucket, key, query, headers)
    if method == "DELETE":
        return delete_object(store, bucket, key, query, headers)
    return _error_xml("MethodNotAllowed", method, f"/{bucket}/{key}", 405)
