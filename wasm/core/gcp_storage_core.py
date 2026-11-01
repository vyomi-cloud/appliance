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
                    "cors", "website", "billing", "objectRetention", "encryption",
                    "versioning", "softDeletePolicy", "hierarchicalNamespace")
_MULTI_REGIONS = {"US", "EU", "ASIA"}
_DUAL_REGIONS = {"NAM4", "EUR4", "EUR5", "EUR7", "EUR8", "ASIA1"}
# Public members that bucket/project public access prevention (enforced) blocks a
# setIamPolicy call from granting — the one PAP check Vyomi can make for real,
# since it has no per-request authorization layer to also block anonymous reads.
_PUBLIC_MEMBERS = {"allUsers", "allAuthenticatedUsers"}
# Cloud KMS CryptoKey resource name shape (Vyomi validates the shape, not that the
# key exists/is enabled — see gcp.storage.encryption in core/capabilities/gcp/storage.json).
_KMS_KEY_RE = re.compile(r"^projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+$")


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
        elif k == "encryption":
            key_name = (v or {}).get("defaultKmsKeyName")
            if key_name and not _KMS_KEY_RE.match(key_name):
                return _err(400, "invalid", "Invalid CMEK key: defaultKmsKeyName must be a full Cloud KMS "
                            "CryptoKey resource name (projects/P/locations/L/keyRings/R/cryptoKeys/K).")
            meta[k] = {"defaultKmsKeyName": key_name} if key_name else {}
        elif k == "versioning":
            meta[k] = {"enabled": bool((v or {}).get("enabled"))}
        elif k == "hierarchicalNamespace":
            if patch:   # immutable after bucket creation, same as the real API
                return _err(400, "invalid", "hierarchicalNamespace cannot be changed after bucket creation.")
            if bool((v or {}).get("enabled")) and not (meta.get("iamConfiguration") or {}).get("uniformBucketLevelAccess", {}).get("enabled"):
                return _err(400, "invalid", "A hierarchical namespace bucket requires uniform bucket-level access.")
            meta[k] = {"enabled": bool((v or {}).get("enabled"))}
        elif k == "softDeletePolicy":
            try:
                secs = int((v or {}).get("retentionDurationSeconds", 0))
            except (TypeError, ValueError):
                return _err(400, "invalid", "Invalid argument: retentionDurationSeconds.")
            if secs <= 0:
                meta.pop(k, None)
                continue
            meta[k] = {"retentionDurationSeconds": str(secs), "effectiveTime": _now()}
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
              "cors", "website", "billing", "objectRetention", "encryption",
              "versioning", "softDeletePolicy", "hierarchicalNamespace"):
        if meta.get(k):
            view[k] = meta[k]
    return view


def _hns_enabled(store: ObjectStore, bucket: str) -> bool:
    hns = (store.buckets.get(bucket) or {}).get("hierarchicalNamespace")
    return bool(hns.get("enabled")) if isinstance(hns, dict) else False


def _bucket_kms_key(store: ObjectStore, bucket: str) -> str | None:
    return (store.buckets.get(bucket, {}).get("encryption") or {}).get("defaultKmsKeyName")


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


def _requester_pays_block(store: ObjectStore, bucket: str, query: dict) -> GcsResponse | None:
    """Requester Pays (billing.requesterPays): every object data-plane request on such a
    bucket must carry a userProject — the real API's UserProjectMissing error — or it is
    rejected. Vyomi has no distinct owner/requester identity to exempt the bucket's own
    project, so any non-empty userProject is accepted and its request count tracked, but
    never actually billed (see gcp.storage.requester-pays)."""
    if not (store.buckets.get(bucket, {}).get("billing") or {}).get("requesterPays"):
        return None
    user_project = query.get("userProject")
    if not user_project:
        return _err(400, "UserProjectMissing",
                    "Bucket is a requester pays bucket but no user project provided.")
    usage = store.buckets[bucket].setdefault("_requesterPaysUsage", {})
    usage[user_project] = usage.get(user_project, 0) + 1
    return None


# ── Object versioning + soft delete (noncurrent-version history) ──────────────────────
# A single archive backs both features: an overwrite or delete on a bucket that has
# versioning.enabled OR a softDeletePolicy snapshots the object BEFORE mutating it, so
# the prior generation stays retrievable by generation number (versioning) or
# restorable (soft delete) instead of disappearing — see gcp.storage.versioning /
# gcp.storage.soft-delete. A bucket with neither set behaves exactly as before (hard
# delete, single generation): no existing caller is affected.
def _versions_map(store: ObjectStore) -> dict:
    m = getattr(store, "_gcs_versions", None)
    if m is None:
        m = {}
        store._gcs_versions = m
    return m


def _tracks_versions(store: ObjectStore, bucket: str) -> bool:
    meta = store.buckets.get(bucket) or {}
    return bool((meta.get("versioning") or {}).get("enabled")) or bool(meta.get("softDeletePolicy"))


def _archive_entry(store: ObjectStore, bucket: str, name: str, old_entry: dict | None, deleted: bool) -> None:
    """Snapshot `old_entry` (about to be overwritten or deleted) into the bucket's
    noncurrent-version history, if this bucket keeps one."""
    if old_entry is None or not _tracks_versions(store, bucket):
        return
    snap = dict(old_entry)
    snap["archivedAt"] = _now()
    if deleted:
        snap["timeDeleted"] = _now()
    _versions_map(store).setdefault(bucket, {}).setdefault(name, []).append(snap)


def _soft_delete_retention(store: ObjectStore, bucket: str) -> int:
    try:
        return int((store.buckets.get(bucket, {}).get("softDeletePolicy") or {}).get("retentionDurationSeconds", 0))
    except (TypeError, ValueError):
        return 0


def _sweep_soft_deleted(store: ObjectStore, bucket: str) -> None:
    """Permanently purge archived versions whose soft-delete retention window has
    elapsed. Versions with no timeDeleted (plain versioning overwrites) or whose
    bucket has no softDeletePolicy are never purged by this sweep — only a real
    lifecycle Delete rule or an explicit generation delete removes those."""
    retention = _soft_delete_retention(store, bucket)
    if not retention:
        return
    by_name = _versions_map(store).get(bucket)
    if not by_name:
        return
    now = datetime.now(timezone.utc).timestamp()
    changed = False
    for name, versions in list(by_name.items()):
        kept = [v for v in versions if not (v.get("timeDeleted") and now - _parse_ts(v["timeDeleted"]) > retention)]
        if len(kept) != len(versions):
            changed = True
        if kept:
            by_name[name] = kept
        else:
            by_name.pop(name, None)
    if changed:
        store.persist()


def _find_version(store: ObjectStore, bucket: str, name: str, generation: str) -> dict | None:
    for v in _versions_map(store).get(bucket, {}).get(name, []):
        if str(v.get("generation")) == str(generation):
            return v
    return None


def _restore_object(store: ObjectStore, bucket: str, name: str, query: dict) -> GcsResponse:
    """POST /b/{bucket}/o/{object}/restore?generation=N — bring back a noncurrent or
    soft-deleted generation as a NEW current generation, same as the real API."""
    gen = query.get("generation")
    if not gen:
        return _err(400, "required", "generation is required to restore an object.")
    objs = store.bucket_objects(bucket)
    cur = objs.get(name)
    if cur and str(cur.get("generation")) == str(gen):
        return _json(200, _object_view(bucket, name, cur))   # already current — idempotent
    versions = _versions_map(store).get(bucket, {}).get(name, [])
    idx = next((i for i, v in enumerate(versions) if str(v.get("generation")) == str(gen)), None)
    if idx is None:
        return _err(404, "notFound", f"No such object version: {bucket}/{name}#{gen}")
    snap = versions.pop(idx)
    _archive_entry(store, bucket, name, cur, deleted=False)
    restored = dict(snap)
    restored.pop("timeDeleted", None)
    restored.pop("archivedAt", None)
    known_gens = [int(snap.get("generation", 0) or 0)] + [int(v.get("generation", 0) or 0) for v in versions]
    if cur:
        known_gens.append(int(cur.get("generation", 0) or 0))
    restored["generation"] = max(known_gens) + 1
    restored["metageneration"] = 1
    restored["updated"] = _now()
    objs[name] = restored
    store.mirror_put(bucket, name, restored.get("data") or b"", restored.get("contentType", "application/octet-stream"),
                      restored.get("metadata") or {})
    store.persist()
    return _json(200, _object_view(bucket, name, restored))


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
                if _tracks_versions(store, bucket):
                    _archive_entry(store, bucket, name, entry, deleted=True)
                else:
                    store.mirror_delete(bucket, name)
                objs.pop(name, None)
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


def _apply_lifecycle_noncurrent(store: ObjectStore, bucket: str) -> None:
    """Evaluate numNewerVersions / daysSinceNoncurrentTime / noncurrentTimeBefore for
    real against the noncurrent-version archive (see gcp.storage.versioning) — the one
    piece of _condition_met that bucket lifecycle rules can never satisfy against LIVE
    objects, now real against the versions Vyomi actually keeps."""
    rules = ((store.buckets.get(bucket) or {}).get("lifecycle") or {}).get("rule") or []
    by_name = _versions_map(store).get(bucket)
    if not rules or not by_name:
        return
    now = datetime.now(timezone.utc).timestamp()
    changed = False
    for name, versions in list(by_name.items()):
        versions.sort(key=lambda v: int(v.get("generation", 0)), reverse=True)
        kept = []
        for idx, v in enumerate(versions):
            since = _parse_ts(v.get("archivedAt") or "")
            acted = False
            for rule in rules:
                cond = rule.get("condition") or {}
                if not ({"numNewerVersions", "daysSinceNoncurrentTime", "noncurrentTimeBefore"} & cond.keys()):
                    continue
                # idx+1 counts the live current generation itself as always "newer"
                # than every noncurrent one, matching the real API's definition.
                if "numNewerVersions" in cond and (idx + 1) < int(cond["numNewerVersions"]):
                    continue
                if "daysSinceNoncurrentTime" in cond and (not since or (now - since) / 86400 < int(cond["daysSinceNoncurrentTime"])):
                    continue
                if cond.get("noncurrentTimeBefore"):
                    before = _parse_date_only(cond["noncurrentTimeBefore"])
                    if not since or not before or since >= before:
                        continue
                action = rule.get("action") or {}
                if action.get("type") == "Delete":
                    acted = True
                    changed = True
                    break
                if action.get("type") == "SetStorageClass" and action.get("storageClass"):
                    v["storageClass"] = action["storageClass"]
                    changed = True
                    break
            if not acted:
                kept.append(v)
        by_name[name] = kept
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
                                 "temporaryHold", "eventBasedHold", "customTime", "componentCount", "kmsKeyName",
                                 "timeDeleted")
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


def _new_entry(objs: dict, name: str, media: bytes, content_type: str, custom: dict, storage_class: str = "STANDARD",
               kms_key: str | None = None) -> dict:
    gen = int(objs.get(name, {}).get("generation", "0") or 0) + 1
    entry = {"data": media, "size": len(media), "contentType": content_type,
             "timeCreated": objs.get(name, {}).get("timeCreated", _now()),
             "updated": _now(), "md5Hash": _md5_b64(media), "crc32c": _crc32c_b64(media),
             "etag": _etag(), "generation": gen, "metageneration": 1, "metadata": custom or {},
             "storageClass": storage_class}
    if kms_key:
        entry["kmsKeyName"] = kms_key
    return entry


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
                       store.buckets.get(bucket, {}).get("storageClass", "STANDARD"),
                       kms_key=_bucket_kms_key(store, bucket))
    entry["componentCount"] = len(sources)
    _archive_entry(store, bucket, dest, objs.get(dest), deleted=False)
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
            if _tracks_versions(store, bucket):
                _archive_entry(store, bucket, name, entry, deleted=True)
            else:
                store.mirror_delete(bucket, name)
            objs.pop(name, None)
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


# ── Long-running bucket operations (Operations tab) ───────────────────────
# Real GCS keeps this as a genuine async long-running-operation resource for
# cross-location bucket moves and the Turbo replication switch; Vyomi's bucket
# ops (buckets.patch) complete synchronously, so every operation Vyomi records
# is already DONE at creation time — but it is a real, listable resource, not a
# hand-written disclaimer.
def _bucket_ops(store: ObjectStore) -> dict:
    m = getattr(store, "_gcs_bucket_ops", None)
    if m is None:
        m = {}
        store._gcs_bucket_ops = m
    return m


def _op_view(bucket: str, op_id: str, op: dict) -> dict:
    return {"kind": "storage#operation", "name": f"projects/_/buckets/{bucket}/operations/{op_id}",
            "done": True, "metadata": {"type": op["type"], "createTime": op["createTime"],
                                        "endTime": op["createTime"], "requestedCancellation": False}}


def _record_op(store: ObjectStore, bucket: str, op_type: str) -> None:
    ops = _bucket_ops(store)
    ops[uuid.uuid4().hex[:12]] = {"bucket": bucket, "type": op_type, "createTime": _now()}


# ── Monitoring: real per-bucket request-count metering ─────────────────────────────────
# `store.mon_store` is the shared Cloud Monitoring store, linked in by the wire router
# (same pattern as Cloud Logging's usage-alert byte/entry counters) — None outside a
# router that wires it, so a bare InMemoryObjectStore in a unit test is unaffected.
# record_system_point drops a write whose endTime isn't STRICTLY after the series' last
# point, so two requests landing in the same wall-clock second need distinct timestamps —
# a small per-second sequence number (real elapsed time, just disambiguated below
# whole-second resolution) gives every real request its own point. See
# gcp.storage.observability.
def _record_request_metric(store: ObjectStore, bucket: str) -> None:
    mon_store = getattr(store, "mon_store", None)
    if mon_store is None:
        return
    from core import gcp_monitoring_core as mon
    meta = store.buckets.get(bucket) or {}
    sec = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    seq = getattr(store, "_gcs_metric_seq", None)
    if seq is None:
        seq = {}
        store._gcs_metric_seq = seq
    n = seq.get(sec, 0) + 1
    seq[sec] = n
    if len(seq) > 4:   # only the current burst of seconds matters — bound memory
        for k in sorted(seq)[:-4]:
            seq.pop(k, None)
    resource = {"type": "gcs_bucket", "labels": {
        "project_id": meta.get("project") or "vyomi-project", "bucket_name": bucket,
        "location": (meta.get("location") or "US").lower()}}
    mon.record_system_point(mon_store, meta.get("project") or "vyomi-project",
                             "storage.googleapis.com/api/request_count", resource, 1,
                             f"{sec}.{min(n, 999999):06d}Z", unit="1")


# ── Hierarchical namespace: Folders (real sub-resource, not zero-byte placeholder
# objects) — a bucket created with hierarchicalNamespace.enabled gets atomic folder
# rename/delete: renaming a folder moves every object and subfolder under it in ONE
# operation, instead of the flat-namespace console's copy-then-delete-each-object dance.
# See gcp.storage.hierarchical-namespace.
def _folders(store: ObjectStore) -> dict:
    m = getattr(store, "_gcs_folders", None)
    if m is None:
        m = {}
        store._gcs_folders = m
    return m


def _bucket_folders(store: ObjectStore, bucket: str) -> dict:
    return _folders(store).setdefault(bucket, {})


def _folder_view(bucket: str, folder_id: str, f: dict) -> dict:
    return {"kind": "storage#folder", "name": folder_id, "bucket": bucket,
            "metageneration": str(f.get("metageneration", 1)),
            "createTime": f["createTime"], "updateTime": f.get("updateTime", f["createTime"])}


def _parent_folder(folder_id: str) -> str | None:
    trimmed = folder_id.rstrip("/")
    parent = trimmed.rsplit("/", 1)[0] if "/" in trimmed else ""
    return parent + "/" if parent else None


def _create_folder(store: ObjectStore, bucket: str, folder_id: str, recursive: bool) -> GcsResponse:
    if not folder_id.endswith("/"):
        return _err(400, "invalid", "Folder name must end with '/'.")
    folders = _bucket_folders(store, bucket)
    if folder_id in folders:
        return _err(409, "conflict", f"Folder {folder_id} already exists.")
    parent = _parent_folder(folder_id)
    if parent and parent not in folders and not recursive:
        return _err(404, "notFound", f"Parent folder {parent} does not exist (pass recursive=true to create it).")
    if parent and parent not in folders and recursive:
        _create_folder(store, bucket, parent, recursive=True)
    now = _now()
    folders[folder_id] = {"createTime": now, "updateTime": now, "metageneration": 1}
    store.persist()
    return _json(200, _folder_view(bucket, folder_id, folders[folder_id]))


def _rename_folder(store: ObjectStore, bucket: str, src: str, dst: str) -> GcsResponse:
    folders = _bucket_folders(store, bucket)
    if src not in folders:
        return _err(404, "notFound", f"No such folder: {src}")
    if dst in folders:
        return _err(409, "conflict", f"Folder {dst} already exists.")
    # Atomically move the folder AND everything under it (subfolders + objects) — the
    # one thing a flat namespace cannot do without touching every object individually.
    for fid in [f for f in folders if f == src or f.startswith(src)]:
        suffix = fid[len(src):]
        new_id = dst + suffix
        folders[new_id] = folders.pop(fid)
        folders[new_id]["updateTime"] = _now()
    objs = store.bucket_objects(bucket)
    for name in [n for n in objs if n.startswith(src)]:
        objs[dst + name[len(src):]] = objs.pop(name)
    store.persist()
    return _json(200, _folder_view(bucket, dst, folders[dst]))


# ── Interoperability: HMAC keys for service/user accounts ─────────────────
# Real resource: storage/v1/projects/{projectId}/hmacKeys. Issuance, listing,
# the ACTIVE/INACTIVE state toggle and delete-when-INACTIVE round-trip for
# real; Vyomi's wire layer never verifies an HMAC-signed request against the
# secret (the separate S3-compatible XML endpoint these keys authenticate
# against is not implemented) — see gcp.storage.interoperability.
def _hmac_keys(store: ObjectStore) -> dict:
    m = getattr(store, "_gcs_hmac_keys", None)
    if m is None:
        m = {}
        store._gcs_hmac_keys = m
    return m


def _hmac_key_view(access_id: str, key: dict, with_secret: bool = False) -> dict:
    meta = {"kind": "storage#hmacKeyMetadata", "accessId": access_id, "etag": "CAE=",
            "id": f"{key['project']}/{access_id}", "projectId": key["project"],
            "serviceAccountEmail": key["serviceAccountEmail"], "state": key["state"],
            "timeCreated": key["timeCreated"], "updated": key["updated"]}
    if with_secret:
        return {"kind": "storage#hmacKey", "metadata": meta, "secret": key["secret"]}
    return meta


# ── CORS response headers ──────────────────────────────────────────────────
# Real GCS relies on the browser, not the server, to enforce CORS: it always
# serves the request and only ADDS Access-Control-* headers when the Origin
# matches a configured rule, letting the browser block the response client-side
# otherwise. Vyomi now does the same on OPTIONS preflights and on matching
# object/bucket responses — see gcp.storage.cors.
def _bucket_from_path(path: str) -> str | None:
    p = path
    for pre in ("/upload/storage/v1", "/download/storage/v1", "/storage/v1"):
        if p.startswith(pre):
            p = p[len(pre):]
            break
    p = p.split("?", 1)[0].rstrip("/")
    segs = [s for s in p.split("/") if s != ""]
    if len(segs) >= 2 and segs[0] == "b":
        return unquote(segs[1])
    return None


def _cors_match(store: ObjectStore, bucket: str, origin: str) -> dict | None:
    for rule in (store.buckets.get(bucket) or {}).get("cors") or []:
        origins = rule.get("origin") or []
        if "*" in origins or origin in origins:
            return rule
    return None


def _cors_response_headers(rule: dict, origin: str) -> dict:
    hdrs = {"access-control-allow-origin": origin, "vary": "Origin"}
    if rule.get("method"):
        hdrs["access-control-allow-methods"] = ",".join(rule["method"])
    if rule.get("responseHeader"):
        hdrs["access-control-expose-headers"] = ",".join(rule["responseHeader"])
    if rule.get("maxAgeSeconds"):
        hdrs["access-control-max-age"] = str(rule["maxAgeSeconds"])
    return hdrs


def _cors_preflight(store: ObjectStore, path: str, origin: str | None) -> GcsResponse:
    bucket = _bucket_from_path(path)
    rule = bucket and origin and _cors_match(store, bucket, origin)
    if not rule:
        return GcsResponse(status=200, headers={}, body=b"", media_type=None)
    hdrs = _cors_response_headers(rule, origin)
    hdrs["access-control-allow-headers"] = ",".join(rule.get("responseHeader") or ["*"])
    return GcsResponse(status=200, headers=hdrs, body=b"", media_type=None)


# ── Static website serving ──────────────────────────────────────────────────
# Real GCS serves a bucket's website config on its OWN public host
# (storage.googleapis.com, bucket-named subdomain, or a custom domain) — a request with
# no object name serves the mainPageSuffix object, a miss serves notFoundPage (404) or a
# generic 404. Vyomi exposes the equivalent on its own wire at /storage/website/{bucket}/
# (never a real internet host — see the "nothing leaves the simulator" rule) so a browser
# pointed at it gets the actual configured page bytes back, not a disclaimer.
def _website_serve(store: ObjectStore, bucket: str, obj_path: str) -> GcsResponse:
    website = (store.buckets.get(bucket) or {}).get("website") if store.bucket_exists(bucket) else None
    if not website:
        return GcsResponse(status=404, body=b"Not Found", media_type="text/html")
    objs = store.bucket_objects(bucket)
    name = obj_path or ""
    if not name or name.endswith("/"):
        name += website.get("mainPageSuffix") or "index.html"
    entry = objs.get(name)
    if entry is not None:
        data = _entry_bytes(store, bucket, name, entry)
        return GcsResponse(status=200, body=data, media_type=entry.get("contentType", "text/html"))
    not_found_name = website.get("notFoundPage")
    nf_entry = objs.get(not_found_name) if not_found_name else None
    if nf_entry is not None:
        data = _entry_bytes(store, bucket, not_found_name, nf_entry)
        return GcsResponse(status=404, body=data, media_type=nf_entry.get("contentType", "text/html"))
    return GcsResponse(status=404, body=b"Not Found", media_type="text/html")


def dispatch(store: ObjectStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> GcsResponse:
    """Public entry point: handles the CORS preflight/header concern (see the
    `_cors_*` helpers above), then hands off to `_dispatch` for the real routing."""
    headers = headers or {}
    origin = next((v for k, v in headers.items() if (k or "").lower() == "origin"), None)
    if method.upper() == "OPTIONS":
        return _cors_preflight(store, path, origin)
    resp = _dispatch(store, method, path, query, headers, body)
    if origin:
        bucket = _bucket_from_path(path)
        rule = bucket and _cors_match(store, bucket, origin)
        if rule:
            resp.headers = {**(resp.headers or {}), **_cors_response_headers(rule, origin)}
    return resp


def _dispatch(store: ObjectStore, method: str, path: str,
              query: dict | None = None, headers: dict | None = None,
              body: bytes = b"") -> GcsResponse:
    query = query or {}
    headers = {(k or "").lower(): v for k, v in (headers or {}).items()}
    method = method.upper()

    # /storage/website/{bucket}/{path...} — the simulated public static-website host
    # (see _website_serve above), checked before the JSON-API prefix stripping below
    # since it is a different, unauthenticated surface.
    website_path = path.split("?", 1)[0]
    if website_path.startswith("/storage/website/") and method in ("GET", "HEAD"):
        rest = website_path[len("/storage/website/"):]
        wbucket, _, wobj = rest.partition("/")
        return _website_serve(store, unquote(wbucket), wobj)

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

    # /projects/{project}/hmacKeys[/{accessId}] — Interoperable access (see _hmac_keys above).
    if len(segs) >= 3 and segs[0] == "projects" and segs[2] == "hmacKeys":
        project = unquote(segs[1])
        keys = _hmac_keys(store)
        if len(segs) == 3:
            if method == "POST":
                try:
                    req = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    return _err(400, "parseError", "Parse Error")
                sa = req.get("serviceAccountEmail") or query.get("serviceAccountEmail")
                if not sa:
                    return _err(400, "required", "serviceAccountEmail is required.")
                access_id = "GOOG1" + uuid.uuid4().hex[:18].upper()
                secret = base64.b64encode(uuid.uuid4().bytes + uuid.uuid4().bytes).decode()
                keys[access_id] = {"project": project, "serviceAccountEmail": sa, "secret": secret,
                                   "state": "ACTIVE", "timeCreated": _now(), "updated": _now()}
                return _json(200, _hmac_key_view(access_id, keys[access_id], with_secret=True))
            if method == "GET":
                items = [_hmac_key_view(i, k) for i, k in sorted(keys.items()) if k["project"] == project]
                return _json(200, {"kind": "storage#hmacKeysMetadata", "items": items})
            return _err(400, "invalid", f"Unsupported method {method} on hmacKeys")
        access_id = unquote(segs[3])
        key = keys.get(access_id)
        if key is None or key["project"] != project:
            return _err(404, "notFound", f"No such HMAC key: {access_id}")
        if method == "GET":
            return _json(200, _hmac_key_view(access_id, key))
        if method in ("PUT", "PATCH"):
            try:
                req = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                return _err(400, "parseError", "Parse Error")
            state = req.get("state")
            if state not in ("ACTIVE", "INACTIVE"):
                return _err(400, "invalid", "state must be ACTIVE or INACTIVE.")
            key["state"] = state
            key["updated"] = _now()
            return _json(200, _hmac_key_view(access_id, key))
        if method == "DELETE":
            if key["state"] != "INACTIVE":
                return _err(400, "invalid", "HMAC key must be in INACTIVE state before it can be deleted.")
            keys.pop(access_id, None)
            return GcsResponse(status=204, body=b"", media_type=None)
        return _err(400, "invalid", f"Unsupported method {method} on an HMAC key")

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
            store.buckets[name].pop("versioning", None)   # drop ObjectStore's S3-shaped default (a string); GCS's own "versioning" is a dict, set only when a client opts in
            store.buckets[name].update(bmeta)
            store.bucket_objects(name)
            store.persist()
            return _json(200, _bucket_view(store, name))
        if method == "GET":             # list buckets (single simulated project: ?project is not a filter)
            items = [_bucket_view(store, n) for n in sorted(store.buckets)]
            return _json(200, {"kind": "storage#buckets", "items": items})
        return _err(400, "invalid", f"Unsupported method {method} on /b")

    bucket = unquote(segs[1])
    if store.bucket_exists(bucket):
        _record_request_metric(store, bucket)

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
            if "rpo" in staged and staged.get("rpo") != bmeta.get("rpo"):
                _record_op(store, bucket, "ChangeTurboReplication" if staged.get("rpo") == "ASYNC_TURBO" else "ChangeDefaultReplication")
            staged["metageneration"] = int(bmeta.get("metageneration", 1)) + 1
            staged["updated"] = _now()
            bmeta.clear()
            bmeta.update(staged)
            store.persist()
            return _json(200, _bucket_view(store, bucket))
        return _err(400, "invalid", f"Unsupported method {method} on bucket")

    # ---- bucket long-running operations: /b/{bucket}/operations[/{id}] ----
    if len(segs) >= 3 and segs[2] == "operations":
        if not store.bucket_exists(bucket):
            return _err(404, "notFound", f"The specified bucket does not exist.")
        ops = {oid: o for oid, o in _bucket_ops(store).items() if o["bucket"] == bucket}
        if len(segs) == 3:
            if method == "GET":
                return _json(200, {"kind": "storage#operations", "items": [_op_view(bucket, i, o) for i, o in sorted(ops.items())]})
            return _err(400, "invalid", f"Unsupported method {method} on bucket operations")
        op_id = unquote(segs[3])
        op = ops.get(op_id)
        if op is None:
            return _err(404, "notFound", f"No such operation: {op_id}")
        if method == "GET":
            return _json(200, _op_view(bucket, op_id, op))
        return _err(400, "invalid", f"Unsupported method {method} on a bucket operation")

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
            pap_enforced = (bmeta.get("iamConfiguration") or {}).get("publicAccessPrevention") == "enforced"
            bindings = []
            for b in pol.get("bindings") or []:
                if not isinstance(b, dict) or not b.get("role"):
                    return _err(400, "invalid", "Invalid policy binding.")
                members = [str(m) for m in (b.get("members") or [])]
                public = [m for m in members if m in _PUBLIC_MEMBERS]
                if pap_enforced and public:
                    return _err(400, "publicAccessPrevention",
                                f"Public access prevention is enforced on bucket '{bucket}'; cannot grant "
                                f"access to {', '.join(public)}.")
                if members:
                    bindings.append({"role": str(b["role"]), "members": members})
            stored = {"kind": "storage#policy", "resourceId": f"projects/_/buckets/{bucket}",
                      "version": int(pol.get("version") or 1), "etag": base64.b64encode(uuid.uuid4().bytes[:6]).decode(),
                      "bindings": bindings}
            bmeta["iamPolicy"] = stored
            store.persist()
            return _json(200, stored)
        return _err(400, "invalid", f"Unsupported method {method} on bucket IAM policy")

    # ---- hierarchical namespace folders: /b/{bucket}/folders[/{folder}[:renameTo]] ----
    if segs[2] == "folders":
        if not store.bucket_exists(bucket):
            return _err(404, "notFound", "The specified bucket does not exist.")
        if not _hns_enabled(store, bucket):
            return _err(400, "invalid", "This bucket does not have a hierarchical namespace.")
        folders = _bucket_folders(store, bucket)
        if len(segs) == 3:
            if method == "POST":
                try:
                    req = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    return _err(400, "parseError", "Parse Error")
                name = req.get("name") or query.get("folderId")
                if not name:
                    return _err(400, "required", "name is required.")
                return _create_folder(store, bucket, name, recursive=str(query.get("recursive", "")).lower() == "true")
            if method == "GET":
                prefix = query.get("prefix", "")
                items = [_folder_view(bucket, fid, f) for fid, f in sorted(folders.items()) if fid.startswith(prefix)]
                return _json(200, {"kind": "storage#folders", "items": items} if items else {"kind": "storage#folders"})
            return _err(400, "invalid", f"Unsupported method {method} on folders")
        rest = "/".join(segs[3:])
        if rest.endswith(":renameTo"):
            folder_id = unquote(rest[: -len(":renameTo")])
            dest = query.get("destinationFolderId")
            if not dest and body:
                try:
                    dest = json.loads(body.decode("utf-8")).get("destinationFolderId")
                except Exception:
                    dest = None
            if not dest:
                return _err(400, "required", "destinationFolderId is required.")
            return _rename_folder(store, bucket, folder_id, dest if dest.endswith("/") else dest + "/")
        folder_id = unquote(rest)
        f = folders.get(folder_id)
        if f is None:
            return _err(404, "notFound", f"No such folder: {folder_id}")
        if method == "GET":
            return _json(200, _folder_view(bucket, folder_id, f))
        if method == "DELETE":
            has_children = any(o != folder_id and o.startswith(folder_id) for o in folders) or \
                any(n.startswith(folder_id) for n in store.bucket_objects(bucket))
            if has_children:
                return _err(409, "conflict", f"Folder {folder_id} is not empty.")
            folders.pop(folder_id, None)
            store.persist()
            return GcsResponse(status=204, body=b"", media_type=None)
        return _err(400, "invalid", f"Unsupported method {method} on a folder")

    # ---- objects ----
    if segs[2] == "o":
        blocked = _requester_pays_block(store, bucket, query)
        if blocked:
            return blocked
        objs = store.bucket_objects(bucket)
        _apply_lifecycle(store, bucket)
        _apply_lifecycle_noncurrent(store, bucket)
        _sweep_soft_deleted(store, bucket)

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
                entry = _new_entry(objs, name, media, content_type, custom, store.buckets.get(bucket, {}).get("storageClass", "STANDARD"),
                                   kms_key=_bucket_kms_key(store, bucket))
                _archive_entry(store, bucket, name, objs.get(name), deleted=False)
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
                entry = _new_entry(objs, name, media, content_type, custom, store.buckets.get(bucket, {}).get("storageClass", "STANDARD"),
                                   kms_key=_bucket_kms_key(store, bucket))
                _archive_entry(store, bucket, name, objs.get(name), deleted=False)
                objs[name] = entry
                store.mirror_put(bucket, name, media, content_type, custom)
                store.persist()
                return _json(200, _object_view(bucket, name, entry))
            if method == "GET":                     # list objects
                if not store.bucket_exists(bucket):
                    return _err(404, "notFound", "The specified bucket does not exist.")
                prefix = query.get("prefix", "")
                delim = query.get("delimiter", "")
                want_versions = str(query.get("versions", "")).lower() == "true"
                want_soft_deleted = str(query.get("softDeleted", "")).lower() == "true"
                items, prefixes = [], []
                if not want_soft_deleted:
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
                if want_versions or want_soft_deleted:
                    # List all versions / soft-deleted objects — merge in the noncurrent
                    # archive (see gcp.storage.versioning / gcp.storage.soft-delete).
                    for k, versions in _versions_map(store).get(bucket, {}).items():
                        if not k.startswith(prefix):
                            continue
                        for v in versions:
                            if want_soft_deleted and not v.get("timeDeleted"):
                                continue
                            items.append(_object_view(bucket, k, v))
                    items.sort(key=lambda o: (o["name"], -int(o["generation"])))
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
        if method == "POST" and len(segs) >= 5 and segs[-1] == "restore":
            return _restore_object(store, bucket, unquote("/".join(segs[3:-1])), query)
        name = unquote("/".join(segs[3:]))
        entry = objs.get(name)
        if method == "GET" and query.get("generation") and (entry is None or str(entry.get("generation")) != str(query["generation"])):
            entry = _find_version(store, bucket, name, query["generation"])
            if entry is None:
                return _err(404, "notFound", f"No such object version: {bucket}/{name}#{query['generation']}")
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
            gen_param = query.get("generation")
            if gen_param:
                # A generation-targeted delete permanently removes exactly that version,
                # bypassing versioning/soft delete — same as the real API.
                removed = False
                if entry is not None and str(entry.get("generation")) == str(gen_param):
                    blocked = _retention_block(store, bucket, name, entry) or _hold_block(bucket, name, entry)
                    if blocked:
                        return blocked
                    objs.pop(name, None)
                    store.mirror_delete(bucket, name)
                    removed = True
                versions = _versions_map(store).get(bucket, {}).get(name)
                if versions is not None:
                    before = len(versions)
                    versions[:] = [v for v in versions if str(v.get("generation")) != str(gen_param)]
                    removed = removed or len(versions) != before
                if not removed:
                    return _err(404, "notFound", f"No such object version: {bucket}/{name}#{gen_param}")
                store.persist()
                return GcsResponse(status=204, body=b"", media_type=None)
            if entry is None:
                return _err(404, "notFound", f"No such object: {bucket}/{name}")
            blocked = _retention_block(store, bucket, name, entry) or _hold_block(bucket, name, entry)
            if blocked:
                return blocked
            if _tracks_versions(store, bucket):
                _archive_entry(store, bucket, name, entry, deleted=True)
            else:
                store.mirror_delete(bucket, name)
            objs.pop(name, None)
            store.persist()
            return GcsResponse(status=204, body=b"", media_type=None)
        return _err(400, "invalid", f"Unsupported method {method} on object")

    return _err(404, "notFound", f"Unknown path: {path}")
