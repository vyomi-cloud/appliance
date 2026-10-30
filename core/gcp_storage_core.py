"""GCS object-CRUD core — substrate-independent, the GCP analogue of
core/s3_object_core.py. Speaks the **Google Cloud Storage JSON API v1**
(`/storage/v1/b`, `/upload/storage/v1/b/.../o`) so the native
`google-cloud-storage` SDK, `gsutil`, and `gcloud storage` work unchanged
against it (point them at the endpoint via STORAGE_EMULATOR_HOST / api_endpoint).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide.
Persists through the SAME ObjectStore seam as S3 (core/object_store.py); GCP
just gets its own store instance, so buckets/objects are cloud-namespaced.

Scope (v1 slice): bucket insert/list/get/patch/update/delete (labels, placement,
access-control mode, lifecycle rule definitions, retention policy — enforced on
object delete/overwrite); bucket IAM policy get/set; objects list with
prefix + delimiter (`prefixes`); object insert (media +
multipart upload), get (metadata + ?alt=media download), list, delete. Object
generations are modeled as a monotonic counter; a correct md5Hash and CRC32C are
returned so the SDK's client-side integrity check passes. Resumable uploads and
object PATCH slot in next behind the same helpers.
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote

from core.object_store import ObjectStore


@dataclass
class GcsResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


# ── primitives ────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _etag() -> str:
    return "CK" + uuid.uuid4().hex[:12]


# CRC32C (Castagnoli) — GCS integrity field. stdlib zlib.crc32 is the wrong
# polynomial, so we build the Castagnoli table once and roll our own.
_CRC32C_POLY = 0x82F63B78
_CRC32C_TABLE = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ (_CRC32C_POLY if (_c & 1) else 0)
    _CRC32C_TABLE.append(_c)


def _crc32c_b64(data: bytes) -> str:
    c = 0xFFFFFFFF
    for b in data:
        c = (c >> 8) ^ _CRC32C_TABLE[(c ^ b) & 0xFF]
    c ^= 0xFFFFFFFF
    return base64.b64encode(struct.pack(">I", c)).decode()


def _md5_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode()


def _err(status: int, reason: str, message: str) -> GcsResponse:
    body = {"error": {"code": status, "message": message,
                      "errors": [{"domain": "global", "reason": reason, "message": message}]}}
    return GcsResponse(status=status, body=json.dumps(body).encode())


def _json(status: int, obj: dict) -> GcsResponse:
    return GcsResponse(status=status, body=json.dumps(obj).encode())


# ── resource views ────────────────────────────────────────────────────────
# Bucket fields a client may set on insert / PATCH and read back. Only fields Vyomi
# either enforces (retentionPolicy) or that are pure metadata (labels, placement,
# access-control mode, lifecycle rule definitions) are kept. Behaviour Vyomi does not
# model (object versioning, soft delete, autoclass) is deliberately NOT echoed back, so
# a client never reads a setting that has no effect.
_BUCKET_SETTABLE = ("labels", "iamConfiguration", "lifecycle", "retentionPolicy",
                    "rpo", "customPlacementConfig", "storageClass")
_MULTI_REGIONS = {"US", "EU", "ASIA"}
_DUAL_REGIONS = {"NAM4", "EUR4", "EUR5", "EUR7", "EUR8", "ASIA1"}


def _location_type(loc: str) -> str:
    loc = (loc or "US").upper()
    if loc in _MULTI_REGIONS:
        return "multi-region"
    if loc in _DUAL_REGIONS:
        return "dual-region"
    return "region"


def _norm_iam_config(v: dict | None) -> dict:
    v = v or {}
    ubla = bool((v.get("uniformBucketLevelAccess") or v.get("bucketPolicyOnly") or {}).get("enabled", False))
    pap = v.get("publicAccessPrevention") or "inherited"
    if pap == "unspecified":
        pap = "inherited"
    return {"bucketPolicyOnly": {"enabled": ubla}, "uniformBucketLevelAccess": {"enabled": ubla},
            "publicAccessPrevention": pap}


def _apply_bucket_fields(meta: dict, body: dict, patch: bool) -> GcsResponse | None:
    """Merge settable fields from an insert/patch body into the bucket meta.
    Returns an error response for an invalid value, else None."""
    for k in _BUCKET_SETTABLE:
        if k not in body:
            continue
        v = body[k]
        if v is None:                                   # PATCH null clears the field
            meta.pop(k, None)
            continue
        if k == "labels":
            if not isinstance(v, dict):
                return _err(400, "invalid", "Invalid labels.")
            cur = dict(meta.get("labels") or {}) if patch else {}
            for lk, lv in v.items():
                if lv is None:
                    cur.pop(lk, None)
                else:
                    cur[str(lk)] = str(lv)
            meta["labels"] = cur
        elif k == "iamConfiguration":
            meta[k] = _norm_iam_config(v)
        elif k == "retentionPolicy":
            if (meta.get("retentionPolicy") or {}).get("isLocked"):
                return _err(403, "retentionPolicyNotMet", "Cannot modify a locked retention policy.")
            try:
                period = int(v.get("retentionPeriod", 0))
            except (TypeError, ValueError):
                return _err(400, "invalid", "Invalid argument: retentionPeriod.")
            if period <= 0:
                meta.pop(k, None)
                continue
            meta[k] = {"retentionPeriod": str(period), "effectiveTime": _now(), "isLocked": False}
        elif k == "lifecycle":
            rules = (v or {}).get("rule") or []
            if not isinstance(rules, list):
                return _err(400, "invalid", "Invalid lifecycle configuration.")
            meta[k] = {"rule": rules}
        else:
            meta[k] = v
    return None


def _bucket_view(store: ObjectStore, name: str) -> dict:
    meta = store.buckets.get(name, {})
    loc = (meta.get("location") or "US").upper()
    view = {
        "kind": "storage#bucket",
        "id": name,
        "name": name,
        "selfLink": f"https://www.googleapis.com/storage/v1/b/{name}",
        "projectNumber": "000000000000",
        "metageneration": str(meta.get("metageneration", 1)),
        "location": loc,
        "locationType": _location_type(loc),
        "storageClass": meta.get("storageClass", "STANDARD"),
        "etag": "CAE=",
        "timeCreated": meta.get("timeCreated", _now()),
        "updated": meta.get("updated", _now()),
        "iamConfiguration": _norm_iam_config(meta.get("iamConfiguration")),
        "rpo": meta.get("rpo", "DEFAULT") if _location_type(loc) == "dual-region" else None,
    }
    if view["rpo"] is None:
        view.pop("rpo")
    for k in ("labels", "lifecycle", "retentionPolicy", "customPlacementConfig"):
        if meta.get(k):
            view[k] = meta[k]
    return view


def _default_policy(store: ObjectStore, name: str) -> dict:
    proj = store.buckets.get(name, {}).get("project") or "vyomi-project"
    return {"kind": "storage#policy", "resourceId": f"projects/_/buckets/{name}", "version": 1,
            "etag": "CAE=",
            "bindings": [
                {"role": "roles/storage.legacyBucketOwner", "members": [f"projectEditor:{proj}", f"projectOwner:{proj}"]},
                {"role": "roles/storage.legacyBucketReader", "members": [f"projectViewer:{proj}"]},
                {"role": "roles/storage.legacyObjectOwner", "members": [f"projectEditor:{proj}", f"projectOwner:{proj}"]},
                {"role": "roles/storage.legacyObjectReader", "members": [f"projectViewer:{proj}"]},
            ]}


def _parse_ts(ts: str) -> float:
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


def _retention_block(store: ObjectStore, bucket: str, name: str, entry: dict | None) -> GcsResponse | None:
    """Bucket retention policy: an object can't be deleted or overwritten until it is
    older than the retention period (the native 403 retentionPolicyNotMet)."""
    rp = store.buckets.get(bucket, {}).get("retentionPolicy")
    if not rp or entry is None:
        return None
    until = _parse_ts(entry.get("updated") or entry.get("timeCreated") or "") + int(rp.get("retentionPeriod", 0))
    if datetime.now(timezone.utc).timestamp() < until:
        when = datetime.fromtimestamp(until, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return _err(403, "retentionPolicyNotMet",
                    f"Object '{bucket}/{name}' is subject to bucket's retention policy or object "
                    f"retention and cannot be deleted or overwritten until {when}")
    return None


def _object_view(bucket: str, name: str, entry: dict) -> dict:
    gen = str(entry.get("generation", "1"))
    enc = name.replace("/", "%2F")
    return {
        "kind": "storage#object",
        "id": f"{bucket}/{name}/{gen}",
        "name": name,
        "bucket": bucket,
        "generation": gen,
        "metageneration": "1",
        "contentType": entry.get("contentType", "application/octet-stream"),
        "timeCreated": entry.get("timeCreated", _now()),
        "updated": entry.get("updated", _now()),
        "storageClass": "STANDARD",
        "size": str(entry.get("size", 0)),
        "md5Hash": entry.get("md5Hash", ""),
        "crc32c": entry.get("crc32c", ""),
        "etag": entry.get("etag", _etag()),
        "selfLink": f"https://www.googleapis.com/storage/v1/b/{bucket}/o/{enc}",
        "mediaLink": f"https://storage.googleapis.com/download/storage/v1/b/{bucket}/o/{enc}?alt=media",
        **({"metadata": entry["metadata"]} if entry.get("metadata") else {}),
    }


# ── multipart/related upload parsing ──────────────────────────────────────
def _parse_multipart_related(body: bytes, content_type: str) -> tuple[dict, bytes, str]:
    """Split a GCS multipart/related upload into (metadata_json, media_bytes,
    media_content_type). Part 1 is JSON metadata, part 2 is the media."""
    boundary = ""
    for seg in content_type.split(";"):
        seg = seg.strip()
        if seg.startswith("boundary="):
            boundary = seg[len("boundary="):].strip().strip('"')
    if not boundary:
        return {}, body, "application/octet-stream"
    delim = ("--" + boundary).encode()
    parts = [p for p in body.split(delim) if p not in (b"", b"--", b"--\r\n", b"\r\n")]
    meta: dict = {}
    media = b""
    media_ct = "application/octet-stream"
    for idx, part in enumerate(parts):
        part = part.lstrip(b"\r\n")
        if b"\r\n\r\n" in part:
            head, payload = part.split(b"\r\n\r\n", 1)
        else:
            head, payload = b"", part
        payload = payload.rstrip(b"\r\n")
        head_l = head.decode("latin-1").lower()
        if idx == 0 and (not head or "application/json" in head_l):
            try:
                meta = json.loads(payload.decode("utf-8"))
            except Exception:
                meta = {}
        else:
            media = payload
            for line in head.decode("latin-1").split("\r\n"):
                if line.lower().startswith("content-type:"):
                    media_ct = line.split(":", 1)[1].strip()
    return meta, media, media_ct


# ── dispatch ──────────────────────────────────────────────────────────────
def _gcs_resumable(store: ObjectStore) -> dict:
    """In-progress resumable-upload sessions kept on the store.
    session_id -> {bucket, name, content_type, metadata}."""
    m = getattr(store, "_gcs_resumable_sessions", None)
    if m is None:
        m = {}
        store._gcs_resumable_sessions = m
    return m


def dispatch(store: ObjectStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> GcsResponse:
    query = query or {}
    headers = {(k or "").lower(): v for k, v in (headers or {}).items()}
    method = method.upper()

    # Normalise: strip a leading /storage/v1 or /upload/storage/v1 prefix.
    is_upload = "/upload/storage/v1/" in path
    p = path
    for pre in ("/upload/storage/v1", "/download/storage/v1", "/storage/v1"):
        if p.startswith(pre):
            p = p[len(pre):]
            break
    p = p.split("?", 1)[0].rstrip("/")
    segs = [s for s in p.split("/") if s != ""]

    # /b            → buckets collection
    # /b/{bucket}   → one bucket
    # /b/{bucket}/o → objects collection
    # /b/{bucket}/o/{object...} → one object
    if not segs or segs[0] != "b":
        return _err(404, "notFound", f"Unknown path: {path}")

    # ---- bucket collection ----
    if len(segs) == 1:
        if method == "POST":            # insert bucket
            try:
                meta = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                meta = {}
            name = meta.get("name") or query.get("name")
            if not name:
                return _err(400, "required", "Bucket name is required.")
            if store.bucket_exists(name):
                return _err(409, "conflict", f"You already own this bucket. Please select another name.")
            bmeta = {"timeCreated": _now(), "updated": _now(), "metageneration": 1,
                     "location": (meta.get("location") or "US").upper(),
                     "storageClass": meta.get("storageClass", "STANDARD"),
                     "project": query.get("project") or ""}
            bad = _apply_bucket_fields(bmeta, meta, patch=False)
            if bad:
                return bad
            store.create_bucket(name)
            store.buckets[name].update(bmeta)
            return _json(200, _bucket_view(store, name))
        if method == "GET":             # list buckets
            items = [_bucket_view(store, n) for n in sorted(store.buckets)]
            return _json(200, {"kind": "storage#buckets", "items": items})
        return _err(400, "invalid", f"Unsupported method {method} on /b")

    bucket = unquote(segs[1])

    # ---- single bucket ----
    if len(segs) == 2:
        if method == "GET":
            if not store.bucket_exists(bucket):
                return _err(404, "notFound", f"The specified bucket does not exist.")
            return _json(200, _bucket_view(store, bucket))
        if method == "DELETE":
            if not store.bucket_exists(bucket):
                return _err(404, "notFound", f"The specified bucket does not exist.")
            if store.bucket_objects(bucket):
                return _err(409, "conflict", "The bucket you tried to delete is not empty.")
            store.buckets.pop(bucket, None)
            store.objects.pop(bucket, None)
            return GcsResponse(status=204, body=b"", media_type=None)
        if method in ("PATCH", "PUT"):     # buckets.patch / buckets.update
            if not store.bucket_exists(bucket):
                return _err(404, "notFound", f"The specified bucket does not exist.")
            try:
                patch = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                return _err(400, "parseError", "Parse Error")
            bmeta = store.buckets[bucket]
            staged = dict(bmeta)
            bad = _apply_bucket_fields(staged, patch, patch=(method == "PATCH"))
            if bad:
                return bad
            staged["metageneration"] = int(bmeta.get("metageneration", 1)) + 1
            staged["updated"] = _now()
            bmeta.clear()
            bmeta.update(staged)
            return _json(200, _bucket_view(store, bucket))
        return _err(400, "invalid", f"Unsupported method {method} on bucket")

    # ---- bucket IAM policy: /b/{bucket}/iam ----
    if len(segs) == 3 and segs[2] == "iam":
        if not store.bucket_exists(bucket):
            return _err(404, "notFound", f"The specified bucket does not exist.")
        bmeta = store.buckets[bucket]
        if method == "GET":
            return _json(200, bmeta.get("iamPolicy") or _default_policy(store, bucket))
        if method == "PUT":
            try:
                pol = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                return _err(400, "parseError", "Parse Error")
            bindings = []
            for b in pol.get("bindings") or []:
                if not isinstance(b, dict) or not b.get("role"):
                    return _err(400, "invalid", "Invalid policy binding.")
                members = [str(m) for m in (b.get("members") or [])]
                if members:
                    bindings.append({"role": str(b["role"]), "members": members})
            stored = {"kind": "storage#policy", "resourceId": f"projects/_/buckets/{bucket}",
                      "version": int(pol.get("version") or 1), "etag": base64.b64encode(uuid.uuid4().bytes[:6]).decode(),
                      "bindings": bindings}
            bmeta["iamPolicy"] = stored
            return _json(200, stored)
        return _err(400, "invalid", f"Unsupported method {method} on bucket IAM policy")

    # ---- objects ----
    if segs[2] == "o":
        objs = store.bucket_objects(bucket)

        # object collection: /b/{bucket}/o
        if len(segs) == 3:
            # Resumable upload finalize: PUT to the session URI (?upload_id=...).
            if is_upload and method == "PUT" and query.get("upload_id"):
                sess = _gcs_resumable(store).get(query.get("upload_id"))
                if not sess or sess["bucket"] != bucket:
                    return _err(404, "notFound", "No such upload session.")
                media = bytes(body or b"")
                name = sess["name"]
                blocked = _retention_block(store, bucket, name, objs.get(name))
                if blocked:
                    return blocked
                content_type = sess.get("content_type") or headers.get("content-type") or "application/octet-stream"
                custom = sess.get("metadata") or {}
                gen = int(objs.get(name, {}).get("generation", "0")) + 1
                entry = {
                    "data": media, "size": len(media), "contentType": content_type,
                    "timeCreated": objs.get(name, {}).get("timeCreated", _now()),
                    "updated": _now(), "md5Hash": _md5_b64(media),
                    "crc32c": _crc32c_b64(media), "etag": _etag(),
                    "generation": gen, "metadata": custom,
                }
                objs[name] = entry
                store.mirror_put(bucket, name, media, content_type, custom)
                _gcs_resumable(store).pop(query.get("upload_id"), None)
                return _json(200, _object_view(bucket, name, entry))
            if method == "POST" or is_upload:      # insert object
                if not store.bucket_exists(bucket):
                    return _err(404, "notFound", "The specified bucket does not exist.")
                ct = headers.get("content-type", "")
                upload_type = query.get("uploadType", "media")
                # Resumable upload initiate: register a session, return its URI in Location.
                if upload_type == "resumable":
                    try:
                        meta = json.loads(body.decode("utf-8")) if body else {}
                    except Exception:
                        meta = {}
                    name = meta.get("name") or query.get("name")
                    if not name:
                        return _err(400, "required", "Object name is required.")
                    sid = uuid.uuid4().hex + uuid.uuid4().hex
                    _gcs_resumable(store)[sid] = {
                        "bucket": bucket, "name": name,
                        "content_type": meta.get("contentType") or query.get("contentType"),
                        "metadata": meta.get("metadata") or {}}
                    location = f"/upload/storage/v1/b/{bucket}/o?uploadType=resumable&upload_id={sid}"
                    return GcsResponse(status=200, body=b"", media_type=None,
                                       headers={"Location": location, "X-GUploader-UploadID": sid})
                if upload_type == "multipart" or ct.startswith("multipart/related"):
                    meta, media, media_ct = _parse_multipart_related(body, ct)
                    name = meta.get("name") or query.get("name")
                    content_type = meta.get("contentType") or media_ct
                    custom = meta.get("metadata") or {}
                else:                               # simple media upload
                    name = query.get("name")
                    media = body
                    content_type = ct or "application/octet-stream"
                    custom = {}
                if not name:
                    return _err(400, "required", "Object name is required.")
                blocked = _retention_block(store, bucket, name, objs.get(name))
                if blocked:
                    return blocked
                gen = int(objs.get(name, {}).get("generation", "0")) + 1
                entry = {
                    "data": media, "size": len(media), "contentType": content_type,
                    "timeCreated": objs.get(name, {}).get("timeCreated", _now()),
                    "updated": _now(), "md5Hash": _md5_b64(media),
                    "crc32c": _crc32c_b64(media), "etag": _etag(),
                    "generation": gen, "metadata": custom,
                }
                objs[name] = entry
                store.mirror_put(bucket, name, media, content_type, custom)
                return _json(200, _object_view(bucket, name, entry))
            if method == "GET":                     # list objects
                if not store.bucket_exists(bucket):
                    return _err(404, "notFound", "The specified bucket does not exist.")
                prefix = query.get("prefix", "")
                delim = query.get("delimiter", "")
                items, prefixes = [], []
                for k, v in sorted(objs.items()):
                    if not k.startswith(prefix):
                        continue
                    if delim:
                        cut = k.find(delim, len(prefix))
                        if cut >= 0:           # rolled up into a "directory" prefix
                            p = k[:cut + len(delim)]
                            if p not in prefixes:
                                prefixes.append(p)
                            continue
                    items.append(_object_view(bucket, k, v))
                out = {"kind": "storage#objects"}
                if prefixes:
                    out["prefixes"] = prefixes
                if items:
                    out["items"] = items
                return _json(200, out)
            return _err(400, "invalid", f"Unsupported method {method} on objects")

        # single object: /b/{bucket}/o/{object...}
        name = unquote("/".join(segs[3:]))
        entry = objs.get(name)
        if method == "GET":
            if entry is None:
                return _err(404, "notFound", f"No such object: {bucket}/{name}")
            if query.get("alt") == "media":         # download bytes
                return GcsResponse(status=200, headers={
                    "content-type": entry.get("contentType", "application/octet-stream"),
                    "x-goog-generation": str(entry.get("generation", "1")),
                    "x-goog-hash": f"crc32c={entry.get('crc32c','')},md5={entry.get('md5Hash','')}",
                }, body=entry.get("data", b""), media_type=entry.get("contentType"))
            return _json(200, _object_view(bucket, name, entry))   # metadata
        if method == "DELETE":
            if entry is None:
                return _err(404, "notFound", f"No such object: {bucket}/{name}")
            blocked = _retention_block(store, bucket, name, entry)
            if blocked:
                return blocked
            objs.pop(name, None)
            store.mirror_delete(bucket, name)
            return GcsResponse(status=204, body=b"", media_type=None)
        return _err(400, "invalid", f"Unsupported method {method} on object")

    return _err(404, "notFound", f"Unknown path: {path}")
