# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""GCS object-CRUD core — substrate-independent, the GCP analogue of
core/s3_object_core.py. Speaks the **Google Cloud Storage JSON API v1**
(`/storage/v1/b`, `/upload/storage/v1/b/.../o`) so the native
`google-cloud-storage` SDK, `gsutil`, and `gcloud storage` work unchanged
against it (point them at the endpoint via STORAGE_EMULATOR_HOST / api_endpoint).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide.
Persists through the SAME ObjectStore seam as S3 (core/object_store.py); GCP
just gets its own store instance, so buckets/objects are cloud-namespaced.

Scope (v1 slice): bucket insert/list/get/delete; object insert (media +
multipart upload), get (metadata + ?alt=media download), list, delete. Object
generations are modeled as a monotonic counter; a correct md5Hash and CRC32C are
returned so the SDK's client-side integrity check passes. Resumable uploads and
object PATCH slot in next behind the same helpers.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
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


# ── bucket settings (buckets.patch) ───────────────────────────────────────
# Lifecycle, retention, default encryption, versioning, soft delete, storage class and
# labels: the bucket-level settings the console's Lifecycle / Encryption / Retention /
# Configuration tabs edit. One validator for both runtimes — the offline appliance's
# bucket PATCH calls validate_bucket_patch() too.
STORAGE_CLASSES = ("STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE")
BUCKET_SETTINGS = ("lifecycle", "retentionPolicy", "encryption", "versioning", "softDeletePolicy",
                   "storageClass", "labels")
_LIFECYCLE_ACTIONS = ("Delete", "SetStorageClass", "AbortIncompleteMultipartUpload")
_LIFECYCLE_CONDITIONS = ("age", "createdBefore", "isLive", "matchesStorageClass", "numNewerVersions",
                         "matchesPrefix", "matchesSuffix", "daysSinceNoncurrentTime", "noncurrentTimeBefore",
                         "daysSinceCustomTime", "customTimeBefore")
_KMS_KEY = re.compile(r"^projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+$")


class BucketPatchError(Exception):
    def __init__(self, status: int, reason: str, message: str):
        super().__init__(message)
        self.status, self.reason, self.message = status, reason, message


def _int(v, what):
    try:
        n = int(str(v))
    except (TypeError, ValueError):
        raise BucketPatchError(400, "invalid", "Invalid value for %s: '%s' is not an integer." % (what, v))
    if n < 0:
        raise BucketPatchError(400, "invalid", "Invalid value for %s: must not be negative." % what)
    return n


def _lifecycle(v) -> dict | None:
    if v is None:
        return None
    rules = (v or {}).get("rule") if isinstance(v, dict) else None
    if not isinstance(rules, list):
        raise BucketPatchError(400, "invalid", "lifecycle.rule must be a list of rules.")
    if len(rules) > 100:
        raise BucketPatchError(400, "invalid", "A bucket can have at most 100 lifecycle rules.")
    out = []
    for i, r in enumerate(rules):
        act = (r or {}).get("action") or {}
        cond = (r or {}).get("condition") or {}
        if act.get("type") not in _LIFECYCLE_ACTIONS:
            raise BucketPatchError(400, "invalid", "lifecycle.rule[%d].action.type must be one of %s." % (i, ", ".join(_LIFECYCLE_ACTIONS)))
        a = {"type": act["type"]}
        if act["type"] == "SetStorageClass":
            if act.get("storageClass") not in STORAGE_CLASSES:
                raise BucketPatchError(400, "invalid", "lifecycle.rule[%d].action.storageClass must be one of %s." % (i, ", ".join(STORAGE_CLASSES)))
            a["storageClass"] = act["storageClass"]
        if not isinstance(cond, dict) or not cond:
            raise BucketPatchError(400, "invalid", "lifecycle.rule[%d] needs at least one condition." % i)
        c = {}
        for k, val in cond.items():
            if k not in _LIFECYCLE_CONDITIONS:
                raise BucketPatchError(400, "invalid", "Unknown lifecycle condition '%s'." % k)
            if k in ("age", "numNewerVersions", "daysSinceNoncurrentTime", "daysSinceCustomTime"):
                c[k] = _int(val, "lifecycle.rule[%d].condition.%s" % (i, k))
            elif k == "isLive":
                c[k] = val if isinstance(val, bool) else str(val).lower() == "true"
            elif k in ("matchesStorageClass", "matchesPrefix", "matchesSuffix"):
                c[k] = [str(x) for x in (val if isinstance(val, list) else [val]) if str(x)]
            else:
                c[k] = str(val)
        out.append({"action": a, "condition": c})
    return {"rule": out}


def validate_bucket_patch(cur: dict, patch: dict) -> dict:
    """The bucket fields a buckets.patch body sets, validated against the bucket's
    current settings `cur`. A key mapped to None clears that setting."""
    out = {}
    for key in BUCKET_SETTINGS:
        if key not in patch:
            continue
        v = patch[key]
        if key == "lifecycle":
            out[key] = _lifecycle(v)
        elif key == "retentionPolicy":
            old = cur.get("retentionPolicy") or {}
            if v is None:
                if old.get("isLocked"):
                    raise BucketPatchError(403, "forbidden", "Cannot remove a locked retention policy.")
                out[key] = None
                continue
            period = _int((v or {}).get("retentionPeriod"), "retentionPolicy.retentionPeriod")
            if period < 1 or period > 3155760000:
                raise BucketPatchError(400, "invalid", "retentionPolicy.retentionPeriod must be between 1 second and 100 years.")
            if old.get("isLocked") and period < int(old.get("retentionPeriod") or 0):
                raise BucketPatchError(403, "forbidden", "Cannot reduce the retention period of a locked retention policy.")
            out[key] = {"retentionPeriod": str(period), "effectiveTime": _now(), "isLocked": bool(old.get("isLocked"))}
        elif key == "encryption":
            kms = str(((v or {}).get("defaultKmsKeyName")) or "").strip()
            if kms and not _KMS_KEY.match(kms):
                raise BucketPatchError(400, "invalid",
                                       "encryption.defaultKmsKeyName must be a Cloud KMS key name: "
                                       "projects/PROJECT/locations/LOCATION/keyRings/RING/cryptoKeys/KEY.")
            out[key] = {"defaultKmsKeyName": kms} if kms else None
        elif key == "versioning":
            out[key] = {"enabled": bool((v or {}).get("enabled"))}
        elif key == "softDeletePolicy":
            secs = _int((v or {}).get("retentionDurationSeconds", 0), "softDeletePolicy.retentionDurationSeconds")
            if secs and not (604800 <= secs <= 7776000):
                raise BucketPatchError(400, "invalid", "softDeletePolicy.retentionDurationSeconds must be 0 or between 7 and 90 days.")
            out[key] = {"retentionDurationSeconds": str(secs), "effectiveTime": _now()}
        elif key == "storageClass":
            if v not in STORAGE_CLASSES:
                raise BucketPatchError(400, "invalid", "storageClass must be one of %s." % ", ".join(STORAGE_CLASSES))
            out[key] = v
        elif key == "labels":
            out[key] = {str(a): str(b) for a, b in (v or {}).items()} if isinstance(v, dict) else {}
    return out


def apply_bucket_patch(meta: dict, fields: dict) -> None:
    for k, v in fields.items():
        if v is None:
            meta.pop(k, None)
        else:
            meta[k] = v
    meta["updated"] = _now()
    meta["metageneration"] = str(int(meta.get("metageneration") or 1) + 1)


def lock_retention(meta: dict) -> dict:
    pol = meta.get("retentionPolicy")
    if not pol:
        raise BucketPatchError(400, "invalid", "The bucket has no retention policy to lock.")
    pol = dict(pol, isLocked=True)
    meta["retentionPolicy"] = pol
    meta["metageneration"] = str(int(meta.get("metageneration") or 1) + 1)
    return pol


def retention_blocks(meta: dict, bucket: str, name: str, entry: dict) -> str | None:
    """Why the bucket's retention policy forbids deleting/overwriting the object (or None)."""
    pol = (meta or {}).get("retentionPolicy") or {}
    try:
        period = int(pol.get("retentionPeriod") or 0)
        created = datetime.strptime(str(entry.get("timeCreated"))[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None
    if not period:
        return None
    until = created.timestamp() + period
    if datetime.now(timezone.utc).timestamp() >= until:
        return None
    return ("Object '%s/%s' is subject to bucket's retention policy or object retention and cannot be deleted or "
            "overwritten until %s" % (bucket, name, datetime.fromtimestamp(until, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))


def bucket_settings_view(meta: dict) -> dict:
    out = {k: meta[k] for k in BUCKET_SETTINGS if k in meta and k not in ("storageClass", "labels")}
    return out


# ── resource views ────────────────────────────────────────────────────────
def _bucket_view(store: ObjectStore, name: str) -> dict:
    meta = store.buckets.get(name, {})
    return {
        **bucket_settings_view(meta),
        **({"labels": meta["labels"]} if meta.get("labels") else {}),
        "kind": "storage#bucket",
        "id": name,
        "name": name,
        "selfLink": f"https://www.googleapis.com/storage/v1/b/{name}",
        "projectNumber": "000000000000",
        "metageneration": str(meta.get("metageneration") or "1"),
        "location": meta.get("location", "US"),
        "storageClass": meta.get("storageClass", "STANDARD"),
        "etag": "CAE=",
        "timeCreated": meta.get("timeCreated", _now()),
        "updated": meta.get("updated", _now()),
    }


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
            store.create_bucket(name)
            store.buckets[name].update({"timeCreated": _now(), "updated": _now(),
                                        "location": meta.get("location", "US"),
                                        "storageClass": meta.get("storageClass", "STANDARD")})
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
        if method in ("PATCH", "PUT"):           # buckets.patch / buckets.update
            if not store.bucket_exists(bucket):
                return _err(404, "notFound", f"The specified bucket does not exist.")
            try:
                patch = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                return _err(400, "parseError", "Parse Error")
            meta = store.buckets[bucket]
            try:
                apply_bucket_patch(meta, validate_bucket_patch(meta, patch if isinstance(patch, dict) else {}))
            except BucketPatchError as e:
                return _err(e.status, e.reason, e.message)
            return _json(200, _bucket_view(store, bucket))
        return _err(400, "invalid", f"Unsupported method {method} on bucket")

    # ---- buckets.lockRetentionPolicy ----
    if len(segs) == 3 and segs[2] == "lockRetentionPolicy" and method == "POST":
        if not store.bucket_exists(bucket):
            return _err(404, "notFound", f"The specified bucket does not exist.")
        try:
            lock_retention(store.buckets[bucket])
        except BucketPatchError as e:
            return _err(e.status, e.reason, e.message)
        return _json(200, _bucket_view(store, bucket))

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
                held = name in objs and retention_blocks(store.buckets.get(bucket, {}), bucket, name, objs[name])
                if held:
                    return _err(403, "retentionPolicyNotMet", held)
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
                items = [_object_view(bucket, k, v) for k, v in sorted(objs.items())
                         if k.startswith(prefix)]
                out = {"kind": "storage#objects"}
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
            held = retention_blocks(store.buckets.get(bucket, {}), bucket, name, entry)
            if held:
                return _err(403, "retentionPolicyNotMet", held)
            objs.pop(name, None)
            store.mirror_delete(bucket, name)
            return GcsResponse(status=204, body=b"", media_type=None)
        return _err(400, "invalid", f"Unsupported method {method} on object")

    return _err(404, "notFound", f"Unknown path: {path}")
