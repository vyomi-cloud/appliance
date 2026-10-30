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
# Bucket fields a client may set on insert / PATCH and read back. retentionPolicy and
# lifecycle (Delete / SetStorageClass, see _apply_lifecycle) are ENFORCED. cors, website
# and billing round-trip exactly as a client sets them (config_only — Vyomi's wire layer
# does not add CORS response headers, run a separate static-website serving host, or
# model a distinct "requester" identity to bill). objectRetention is the bucket-level
# switch that lets objects carry an enforced retention.retainUntilTime (see
# _hold_block). Behaviour Vyomi does not model at all (object versioning, soft delete,
# autoclass, CMEK) is deliberately NOT echoed back, so a client never reads a setting
# that has no effect.
_BUCKET_SETTABLE = ("labels", "iamConfiguration", "lifecycle", "retentionPolicy",
                    "rpo", "customPlacementConfig", "storageClass",
                    "cors", "website", "billing", "objectRetention")
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
        elif k == "cors":
            if not isinstance(v, list):
                return _err(400, "invalid", "Invalid CORS configuration.")
            meta[k] = v
        elif k == "objectRetention":
            mode = (v or {}).get("mode")
            meta[k] = {"mode": "Enabled" if mode == "Enabled" else "Disabled"}
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
    for k in ("labels", "lifecycle", "retentionPolicy", "customPlacementConfig",
              "cors", "website", "billing", "objectRetention"):
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


def _parse_date_only(d: str) -> float:
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
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


def _hold_block(bucket: str, name: str, entry: dict | None) -> GcsResponse | None:
    """Object holds (temporaryHold / eventBasedHold) and per-object retention
    (retention.retainUntilTime) block delete and overwrite, same as real GCS."""
    if entry is None:
        return None
    if entry.get("temporaryHold"):
        return _err(403, "conditionNotMet", f"Object '{bucket}/{name}' has a temporary hold and "
                    f"cannot be deleted or overwritten.")
    if entry.get("eventBasedHold"):
        return _err(403, "conditionNotMet", f"Object '{bucket}/{name}' has an event-based hold and "
                    f"cannot be deleted or overwritten.")
    ret = entry.get("retention") or {}
    until = _parse_ts(ret.get("retainUntilTime") or "")
    if until and datetime.now(timezone.utc).timestamp() < until:
        return _err(403, "conditionNotMet", f"Object '{bucket}/{name}' is subject to object retention "
                    f"and cannot be deleted or overwritten until {ret['retainUntilTime']}.")
    return None


# ── lifecycle rule enforcement (lazy sweep on every /o request, like DynamoDB's lazy
# TTL expiry) — real GCS evaluates rules roughly once a day; Vyomi evaluates them on
# every request against the bucket's objects, which is observably stricter but never
# wrong (a matched object is always eligible to be acted on). ────────────────────────
def _condition_met(cond: dict, name: str, entry: dict) -> bool:
    if {"numNewerVersions", "daysSinceNoncurrentTime", "noncurrentTimeBefore"} & cond.keys():
        return False   # Vyomi keeps no noncurrent versions, so these can never be satisfied.
    created = _parse_ts(entry.get("timeCreated") or "")
    now = datetime.now(timezone.utc).timestamp()
    if "age" in cond and (not created or (now - created) / 86400 < int(cond["age"])):
        return False
    if cond.get("createdBefore"):
        before = _parse_date_only(cond["createdBefore"])
        if not created or not before or created >= before:
            return False
    if cond.get("matchesStorageClass") and entry.get("storageClass", "STANDARD") not in cond["matchesStorageClass"]:
        return False
    if cond.get("matchesPrefix") and not any(name.startswith(p) for p in cond["matchesPrefix"]):
        return False
    if cond.get("matchesSuffix") and not any(name.endswith(s) for s in cond["matchesSuffix"]):
        return False
    if cond.get("daysSinceCustomTime") is not None:
        ct = _parse_ts(entry.get("customTime") or "")
        if not ct or (now - ct) / 86400 < int(cond["daysSinceCustomTime"]):
            return False
    if cond.get("customTimeBefore"):
        ct = _parse_ts(entry.get("customTime") or "")
        before = _parse_date_only(cond["customTimeBefore"])
        if not ct or not before or ct >= before:
            return False
    return True


def _apply_lifecycle(store: ObjectStore, bucket: str) -> None:
    rules = ((store.buckets.get(bucket) or {}).get("lifecycle") or {}).get("rule") or []
    if not rules:
        return
    objs = store.bucket_objects(bucket)
    changed = False
    for name, entry in list(objs.items()):
        if name.endswith("/"):             # folder placeholders aren't lifecycle-managed
            continue
        for rule in rules:
            if not _condition_met(rule.get("condition") or {}, name, entry):
                continue
            action = rule.get("action") or {}
            if action.get("type") == "Delete":
                objs.pop(name, None)
                store.mirror_delete(bucket, name)
                changed = True
                break
            if action.get("type") == "SetStorageClass" and action.get("storageClass") and entry.get("storageClass", "STANDARD") != action["storageClass"]:
                entry["storageClass"] = action["storageClass"]
                changed = True
                break
            # AbortIncompleteMultipartUpload: Vyomi's resumable-upload sessions carry no
            # persistent "incomplete upload" record to sweep against, so this action never fires.
    if changed:
        store.persist()


def _object_view(bucket: str, name: str, entry: dict) -> dict:
    gen = str(entry.get("generation", "1"))
    enc = name.replace("/", "%2F")
    return {
        "kind": "storage#object",
        "id": f"{bucket}/{name}/{gen}",
        "name": name,
        "bucket": bucket,
        "generation": gen,
        "metageneration": str(entry.get("metageneration", 1)),
        "contentType": entry.get("contentType", "application/octet-stream"),
        "timeCreated": entry.get("timeCreated", _now()),
        "updated": entry.get("updated", _now()),
        "storageClass": entry.get("storageClass", "STANDARD"),
        "size": str(entry.get("size", 0)),
        "md5Hash": entry.get("md5Hash", ""),
        "crc32c": entry.get("crc32c", ""),
        "etag": entry.get("etag", _etag()),
        "selfLink": f"https://www.googleapis.com/storage/v1/b/{bucket}/o/{enc}",
        "mediaLink": f"https://storage.googleapis.com/download/storage/v1/b/{bucket}/o/{enc}?alt=media",
        **({"metadata": entry["metadata"]} if entry.get("metadata") else {}),
        **({"retention": entry["retention"]} if entry.get("retention") else {}),
        **{k: entry[k] for k in ("contentEncoding", "contentDisposition", "contentLanguage", "cacheControl",
                                 "temporaryHold", "eventBasedHold", "customTime", "componentCount")
           if entry.get(k) not in (None, "")},
    }


def _entry_bytes(store: ObjectStore, bucket: str, name: str, entry: dict) -> bytes:
    """An object's bytes: inline `data`, else `data_b64` (console facade), else the
    substrate's external byte store (pre-v4 metadata whose bytes live elsewhere)."""
    data = entry.get("data")
    if data is None and entry.get("data_b64"):
        try:
            data = base64.b64decode(entry["data_b64"])
        except Exception:
            data = None
    if data is None:
        data = store.fetch_bytes(bucket, name)
    if isinstance(data, str):
        data = data.encode("utf-8")
    return bytes(data or b"")


def _new_entry(objs: dict, name: str, media: bytes, content_type: str, custom: dict, storage_class: str = "STANDARD") -> dict:
    gen = int(objs.get(name, {}).get("generation", "0") or 0) + 1
    return {"data": media, "size": len(media), "contentType": content_type,
            "timeCreated": objs.get(name, {}).get("timeCreated", _now()),
            "updated": _now(), "md5Hash": _md5_b64(media), "crc32c": _crc32c_b64(media),
            "etag": _etag(), "generation": gen, "metageneration": 1, "metadata": custom or {},
            "storageClass": storage_class}


# Object metadata fields settable via objects.patch / objects.update.
_OBJECT_SETTABLE = ("contentType", "contentEncoding", "contentDisposition", "contentLanguage",
                    "cacheControl", "metadata", "temporaryHold", "eventBasedHold", "customTime", "retention")


def _compose(store: ObjectStore, bucket: str, dest: str, body: bytes) -> GcsResponse:
    """POST /b/{bucket}/o/{destination}/compose — concatenate source objects."""
    try:
        req = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return _err(400, "parseError", "Parse Error")
    sources = req.get("sourceObjects") or []
    if not sources:
        return _err(400, "required", "Required field sourceObjects is missing.")
    objs = store.bucket_objects(bucket)
    chunks = []
    for src in sources:
        name = (src or {}).get("name", "")
        ent = objs.get(name)
        if ent is None:
            return _err(404, "notFound", f"No such object: {bucket}/{name}")
        chunks.append(_entry_bytes(store, bucket, name, ent))
    blocked = _retention_block(store, bucket, dest, objs.get(dest)) or _hold_block(bucket, dest, objs.get(dest))
    if blocked:
        return blocked
    dmeta = req.get("destination") or {}
    media = b"".join(chunks)
    first = objs.get(sources[0].get("name", ""), {})
    entry = _new_entry(objs, dest, media, dmeta.get("contentType") or first.get("contentType") or
                       "application/octet-stream", dmeta.get("metadata") or {},
                       store.buckets.get(bucket, {}).get("storageClass", "STANDARD"))
    entry["componentCount"] = len(sources)
    objs[dest] = entry
    store.mirror_put(bucket, dest, media, entry["contentType"], entry["metadata"])
    store.persist()
    view = _object_view(bucket, dest, entry)
    view["componentCount"] = len(sources)
    return _json(200, view)


# ── multipart/related upload parsing ──────────────────────────────────────
def _parse_multipart_related(body: bytes, content_type: str) -> tuple[dict, bytes, str]:
    """Split a GCS multipart/related upload into (metadata_json, media_bytes,
    media_content_type). Part 1 is JSON metadata, part 2 is the media."""
    boundary = ""
    for seg in content_type.split(";"):
        seg = seg.strip()
        if seg.startswith("boundary="):
            # gcloud sends boundary='===…==' (single quotes); most clients use double quotes.
            boundary = seg[len("boundary="):].strip().strip('"').strip("'")
    if not boundary:
        return {}, body, "application/octet-stream"
    delim = ("--" + boundary).encode()
    parts = [p for p in body.split(delim) if p not in (b"", b"--", b"--\r\n", b"--\n", b"\r\n", b"\n")]
    meta: dict = {}
    media = b""
    media_ct = "application/octet-stream"
    for idx, part in enumerate(parts):
        part = part.lstrip(b"\r\n")
        # Header/body separator: CRLF CRLF per RFC 2046; Python's email generator (gcloud) emits LF LF.
        sep = b"\r\n\r\n" if b"\r\n\r\n" in part else b"\n\n"
        if sep in part:
            head, payload = part.split(sep, 1)
        else:
            head, payload = b"", part
        # Only the single line break before the next delimiter is framing — keep the media's own bytes.
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        elif payload.endswith(b"\n"):
            payload = payload[:-1]
        head_l = head.decode("latin-1").lower()
        if idx == 0 and (not head or "application/json" in head_l):
            try:
                meta = json.loads(payload.decode("utf-8"))
            except Exception:
                meta = {}
        else:
            media = payload
            for line in head.decode("latin-1").splitlines():
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


# ── Batch Operations (Storage Intelligence) ───────────────────────────────
# Modeled sub-resource under /storage/v1 (the real product is a separate API,
# storagebatchoperations.googleapis.com, that no google-cloud-storage client calls —
# Vyomi exposes an equivalent job resource on its own wire instead of replicating a
# second service). A job runs synchronously and for real: it applies its action
# (Delete / SetStorageClass) to every object under bucket+prefix right away, exactly
# the single-bucket bulk edit the console's "Batch Operations" page offers.
def _batch_jobs(store: ObjectStore) -> dict:
    m = getattr(store, "_gcs_batch_jobs", None)
    if m is None:
        m = {}
        store._gcs_batch_jobs = m
    return m


def _batch_job_view(job_id: str, job: dict) -> dict:
    return {"name": f"batchOperations/{job_id}", "bucket": job["bucket"], "prefix": job.get("prefix", ""),
            "action": job["action"], "state": job["state"], "createTime": job["createTime"],
            "completeTime": job.get("completeTime"), "counts": job.get("counts", {})}


def _run_batch_job(store: ObjectStore, bucket: str, prefix: str, action: dict) -> dict:
    objs = store.bucket_objects(bucket)
    matched = failed = succeeded = 0
    for name, entry in list(objs.items()):
        if name.endswith("/") or not name.startswith(prefix):
            continue
        matched += 1
        if action.get("type") == "Delete":
            if _retention_block(store, bucket, name, entry) or _hold_block(bucket, name, entry):
                failed += 1
                continue
            objs.pop(name, None)
            store.mirror_delete(bucket, name)
            succeeded += 1
        elif action.get("type") == "SetStorageClass" and action.get("storageClass"):
            entry["storageClass"] = action["storageClass"]
            succeeded += 1
    store.persist()
    return {"matched": matched, "succeeded": succeeded, "failed": failed}


# ── Insights datasets (Storage Intelligence) ───────────────────────────────
# Modeled sub-resource under /storage/v1 (the real product, storageinsights.
# googleapis.com, exports an object inventory into a BigQuery dataset on a
# schedule). Vyomi stores and returns the dataset config exactly as a client sets
# it — config_only: no BigQuery export job ever actually runs.
def _insights_datasets(store: ObjectStore) -> dict:
    m = getattr(store, "_gcs_insights_datasets", None)
    if m is None:
        m = {}
        store._gcs_insights_datasets = m
    return m


def _insights_dataset_view(ds_id: str, ds: dict) -> dict:
    return {"name": f"insightsDatasets/{ds_id}", "displayName": ds.get("displayName", ds_id),
            "sourceBucketPrefix": ds.get("sourceBucketPrefix", ""), "state": "ACTIVE", "createTime": ds["createTime"]}


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

    # /batchOperations[/{id}] and /insightsDatasets[/{id}] — Storage Intelligence
    # sub-resources (see _run_batch_job / _insights_datasets above), checked before the
    # bucket-collection fallthrough since they don't start with "b".
    if segs and segs[0] == "batchOperations":
        jobs = _batch_jobs(store)
        if len(segs) == 1:
            if method == "POST":
                try:
                    req = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    return _err(400, "parseError", "Parse Error")
                bucket = req.get("bucket")
                action = req.get("action") or {}
                if not bucket or not store.bucket_exists(bucket):
                    return _err(404, "notFound", "The specified bucket does not exist.")
                if action.get("type") not in ("Delete", "SetStorageClass"):
                    return _err(400, "invalid", "action.type must be Delete or SetStorageClass.")
                job_id = req.get("jobId") or uuid.uuid4().hex[:12]
                counts = _run_batch_job(store, bucket, req.get("prefix", ""), action)
                jobs[job_id] = {"bucket": bucket, "prefix": req.get("prefix", ""), "action": action,
                                "state": "SUCCEEDED", "createTime": _now(), "completeTime": _now(), "counts": counts}
                return _json(200, _batch_job_view(job_id, jobs[job_id]))
            if method == "GET":
                return _json(200, {"jobs": [_batch_job_view(i, j) for i, j in sorted(jobs.items())]})
            return _err(400, "invalid", f"Unsupported method {method} on batchOperations")
        job_id = unquote(segs[1])
        job = jobs.get(job_id)
        if job is None:
            return _err(404, "notFound", f"No such job: {job_id}")
        if method == "GET":
            return _json(200, _batch_job_view(job_id, job))
        if method == "DELETE":
            jobs.pop(job_id, None)
            return GcsResponse(status=204, body=b"", media_type=None)
        return _err(400, "invalid", f"Unsupported method {method} on a batch job")

    if segs and segs[0] == "insightsDatasets":
        datasets = _insights_datasets(store)
        if len(segs) == 1:
            if method == "POST":
                try:
                    req = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    return _err(400, "parseError", "Parse Error")
                if not req.get("displayName"):
                    return _err(400, "invalid", "displayName is required.")
                ds_id = req.get("datasetConfigId") or uuid.uuid4().hex[:12]
                if ds_id in datasets:
                    return _err(409, "conflict", f"Dataset config {ds_id} already exists.")
                datasets[ds_id] = {"displayName": req["displayName"], "sourceBucketPrefix": req.get("sourceBucketPrefix", ""), "createTime": _now()}
                return _json(200, _insights_dataset_view(ds_id, datasets[ds_id]))
            if method == "GET":
                return _json(200, {"datasets": [_insights_dataset_view(i, d) for i, d in sorted(datasets.items())]})
            return _err(400, "invalid", f"Unsupported method {method} on insightsDatasets")
        ds_id = unquote(segs[1])
        ds = datasets.get(ds_id)
        if ds is None:
            return _err(404, "notFound", f"No such dataset config: {ds_id}")
        if method == "GET":
            return _json(200, _insights_dataset_view(ds_id, ds))
        if method == "DELETE":
            datasets.pop(ds_id, None)
            return GcsResponse(status=204, body=b"", media_type=None)
        return _err(400, "invalid", f"Unsupported method {method} on a dataset config")

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
            store.bucket_objects(name)
            store.persist()
            return _json(200, _bucket_view(store, name))
        if method == "GET":             # list buckets (single simulated project: ?project is not a filter)
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
            store.persist()
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
            store.persist()
            return _json(200, _bucket_view(store, bucket))
        return _err(400, "invalid", f"Unsupported method {method} on bucket")

    # ---- bucket IAM policy: /b/{bucket}/iam ----
    if len(segs) == 3 and segs[2] == "iam":
        if not store.bucket_exists(bucket):
            return _err(404, "notFound", f"The specified bucket does not exist.")
        bmeta = store.buckets[bucket]
        if method == "GET":
            return _json(200, bmeta.get("iamPolicy") or _default_policy(store, bucket))
        if method in ("PUT", "POST"):   # setIamPolicy (POST: pre-v4 appliance console alias)
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
            store.persist()
            return _json(200, stored)
        return _err(400, "invalid", f"Unsupported method {method} on bucket IAM policy")

    # ---- objects ----
    if segs[2] == "o":
        objs = store.bucket_objects(bucket)
        _apply_lifecycle(store, bucket)

        # object collection: /b/{bucket}/o
        if len(segs) == 3:
            # Resumable upload finalize: PUT to the session URI (?upload_id=...).
            if is_upload and method == "PUT" and query.get("upload_id"):
                sess = _gcs_resumable(store).get(query.get("upload_id"))
                if not sess or sess["bucket"] != bucket:
                    return _err(404, "notFound", "No such upload session.")
                media = bytes(body or b"")
                name = sess["name"]
                blocked = _retention_block(store, bucket, name, objs.get(name)) or _hold_block(bucket, name, objs.get(name))
                if blocked:
                    return blocked
                content_type = sess.get("content_type") or headers.get("content-type") or "application/octet-stream"
                custom = sess.get("metadata") or {}
                entry = _new_entry(objs, name, media, content_type, custom, store.buckets.get(bucket, {}).get("storageClass", "STANDARD"))
                objs[name] = entry
                store.mirror_put(bucket, name, media, content_type, custom)
                _gcs_resumable(store).pop(query.get("upload_id"), None)
                store.persist()
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
                if not is_upload and "json" in ct.lower():
                    # Pre-v4 appliance console insert: JSON {name, data|content, contentType}
                    # on the non-upload URL (no real GCS client sends this).
                    try:
                        meta = json.loads(body.decode("utf-8")) if body else {}
                    except Exception:
                        return _err(400, "parseError", "Parse Error")
                    name = meta.get("name") or meta.get("object") or query.get("name")
                    raw = meta.get("data", meta.get("content", ""))
                    media = raw.encode("utf-8") if isinstance(raw, str) else json.dumps(raw).encode("utf-8")
                    content_type = meta.get("contentType") or "text/plain"
                    custom = meta.get("metadata") or {}
                elif upload_type == "multipart" or ct.startswith("multipart/related"):
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
                blocked = _retention_block(store, bucket, name, objs.get(name)) or _hold_block(bucket, name, objs.get(name))
                if blocked:
                    return blocked
                entry = _new_entry(objs, name, media, content_type, custom, store.buckets.get(bucket, {}).get("storageClass", "STANDARD"))
                objs[name] = entry
                store.mirror_put(bucket, name, media, content_type, custom)
                store.persist()
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
        if not store.bucket_exists(bucket):
            return _err(404, "notFound", "The specified bucket does not exist.")
        if method == "POST" and len(segs) >= 5 and segs[-1] == "compose":
            return _compose(store, bucket, unquote("/".join(segs[3:-1])), body)
        name = unquote("/".join(segs[3:]))
        entry = objs.get(name)
        if method == "GET":
            if entry is None:
                return _err(404, "notFound", f"No such object: {bucket}/{name}")
            if query.get("alt") == "media":         # download bytes
                data = _entry_bytes(store, bucket, name, entry)
                hdrs = {"content-type": entry.get("contentType", "application/octet-stream"),
                        "x-goog-generation": str(entry.get("generation", "1")),
                        "x-goog-metageneration": str(entry.get("metageneration", 1)),
                        "x-goog-stored-content-length": str(len(data)),
                        "x-goog-hash": f"crc32c={entry.get('crc32c') or _crc32c_b64(data)},"
                                       f"md5={entry.get('md5Hash') or _md5_b64(data)}"}
                status = 200
                rng = headers.get("range", "")
                if rng.startswith("bytes=") and data:
                    a, _, b = rng[6:].partition("-")
                    try:
                        start = int(a) if a else max(0, len(data) - int(b))
                        end = int(b) if (a and b) else len(data) - 1
                    except ValueError:
                        start, end = 0, len(data) - 1
                    end = min(end, len(data) - 1)
                    if start <= end:
                        hdrs["content-range"] = f"bytes {start}-{end}/{len(data)}"
                        data, status = data[start:end + 1], 206
                return GcsResponse(status=status, headers=hdrs, body=data, media_type=entry.get("contentType"))
            return _json(200, _object_view(bucket, name, entry))   # metadata
        if method in ("PATCH", "PUT"):              # objects.patch / objects.update (metadata only)
            if entry is None:
                return _err(404, "notFound", f"No such object: {bucket}/{name}")
            try:
                patch = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                return _err(400, "parseError", "Parse Error")
            if method == "PUT":
                for k in _OBJECT_SETTABLE:
                    if k != "contentType":
                        entry.pop(k, None)
            for k in _OBJECT_SETTABLE:
                if k not in patch:
                    continue
                v = patch[k]
                if k == "retention" and v is not None:
                    if (store.buckets.get(bucket, {}).get("objectRetention") or {}).get("mode") != "Enabled":
                        return _err(400, "invalid", "Object retention is not enabled on this bucket.")
                    if not isinstance(v, dict) or not v.get("retainUntilTime"):
                        return _err(400, "invalid", "retention.retainUntilTime is required.")
                if k == "metadata" and isinstance(v, dict) and method == "PATCH":
                    cur = dict(entry.get("metadata") or {})
                    for mk, mv in v.items():
                        if mv is None:
                            cur.pop(mk, None)
                        else:
                            cur[str(mk)] = str(mv)
                    entry["metadata"] = cur
                elif v is None:
                    entry.pop(k, None)
                else:
                    entry[k] = v
            entry["metageneration"] = int(entry.get("metageneration", 1) or 1) + 1
            entry["updated"] = _now()
            store.persist()
            return _json(200, _object_view(bucket, name, entry))
        if method == "DELETE":
            if entry is None:
                return _err(404, "notFound", f"No such object: {bucket}/{name}")
            blocked = _retention_block(store, bucket, name, entry) or _hold_block(bucket, name, entry)
            if blocked:
                return blocked
            objs.pop(name, None)
            store.mirror_delete(bucket, name)
            store.persist()
            return GcsResponse(status=204, body=b"", media_type=None)
        return _err(400, "invalid", f"Unsupported method {method} on object")

    return _err(404, "notFound", f"Unknown path: {path}")
