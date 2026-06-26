"""Console ↔ conformance-core adapter (the Nano substrate's analogue of the
Pro/Max FastAPI adapter).

The three SPA consoles speak a small REST-ish API (`/api/s3/buckets/...`,
`/api/dynamodb/tables/...`) with friendly JSON envelopes (`{buckets:[...]}`,
`{tables:[...]}`, `{objects:[...]}`, native item dicts). The PROVEN conformance
cores speak the NATIVE cloud wire (S3: method+path; DynamoDB: X-Amz-Target +
typed attribute values). This module is the thin translation between them — so
the in-browser console's S3 + DynamoDB data-plane is served by the SAME logic
the conformance suite proves (core/s3_object_core.py, core/dynamodb_core.py),
not a stub. Mutations and reads ALL flow through the cores; this file only
reshapes requests/responses, exactly the role the FastAPI route plays in Pro/Max.

The two `InMemory*Store`s here are the single in-tab source of truth. (Unifying
them with the relay endpoint's store — so an external `aws s3` call and the
console see one dataset — is a later step; today each page owns its store.)
"""
from __future__ import annotations

import base64
import copy
import re

from core.object_store import InMemoryObjectStore
from core import s3_object_core as s3
from core.nosql_store import InMemoryNoSqlStore
from core import dynamodb_core as ddb

OBJ = InMemoryObjectStore()
DDB = InMemoryNoSqlStore()
REGION = "us-east-1"

_CODE_RE = re.compile(rb"<Code>([^<]+)</Code>")


def _s3_code(body: bytes) -> str:
    m = _CODE_RE.search(body or b"")
    return m.group(1).decode() if m else "Error"


# ── S3 ─────────────────────────────────────────────────────────────────────
def _bucket_view(name: str) -> dict:
    b = OBJ.buckets.get(name, {})
    ver = b.get("versioning", "Disabled")
    return {"name": name, "creation_date": b.get("creation_date", ""), "region": REGION,
            "versioning": ver, "versioning_enabled": ver == "Enabled"}


def s3_create_bucket(p: dict) -> dict:
    name = str(p.get("name") or p.get("bucket") or p.get("Bucket") or "").strip()
    if not name:
        return {"ok": False, "code": "InvalidBucketName"}
    existed = OBJ.bucket_exists(name)
    OBJ.create_bucket(name)
    OBJ.buckets[name].setdefault("creation_date", s3._now())
    if p.get("versioning_enabled") in (True, "true", "Enabled", "on"):
        OBJ.buckets[name]["versioning"] = "Enabled"
    return {"ok": True, "created": not existed, **_bucket_view(name)}


def s3_list_buckets(p: dict | None = None) -> dict:
    return {"ok": True, "buckets": [_bucket_view(n) for n in sorted(OBJ.buckets)]}


def s3_get_bucket(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    if not OBJ.bucket_exists(name):
        return {"ok": False, "code": "NoSuchBucket", "name": name}
    return {"ok": True, **_bucket_view(name)}


def s3_delete_bucket(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    r = s3.dispatch(OBJ, "DELETE", "/" + name)
    return {"ok": r.status in (200, 204), "name": name}


def s3_set_versioning(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    if not OBJ.bucket_exists(name):
        return {"ok": False, "code": "NoSuchBucket", "name": name}
    status = str(p.get("status") or "Suspended")
    OBJ.buckets[name]["versioning"] = status if status in ("Enabled", "Suspended", "Disabled") else "Suspended"
    return {"ok": True, "status": OBJ.buckets[name]["versioning"]}


def s3_list_objects(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    if not OBJ.bucket_exists(name):
        return {"ok": False, "code": "NoSuchBucket", "name": name}
    bucket_objects = OBJ.bucket_objects(name)
    objs = []
    for key in sorted(bucket_objects):
        versions = bucket_objects[key].get("versions", [])
        if not versions or versions[0].get("is_delete_marker"):
            continue
        v = versions[0]
        objs.append({"key": key, "name": key, "size": v.get("size", 0),
                     "content_length": v.get("size", 0),
                     "last_modified": v.get("last_modified", ""),
                     "etag": v.get("etag", ""),
                     "storage_class": v.get("storage_class", "STANDARD")})
    return {"ok": True, "objects": objs}


def s3_put_object(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    key = str(p.get("key") or "")
    body = base64.b64decode(p.get("body_b64") or "")
    ct = str(p.get("content_type") or "application/octet-stream")
    r = s3.dispatch(OBJ, "PUT", f"/{name}/{key}", headers={"content-type": ct}, body=body)
    if r.status != 200:
        return {"ok": False, "code": _s3_code(r.body), "status": r.status}
    return {"ok": True, "key": key, "etag": r.headers.get("ETag", ""), "size": len(body)}


def s3_get_object(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    key = str(p.get("key") or "")
    r = s3.dispatch(OBJ, "GET", f"/{name}/{key}")
    if r.status not in (200, 206):
        return {"ok": False, "code": _s3_code(r.body), "status": r.status}
    return {"ok": True, "key": key, "body_b64": base64.b64encode(r.body or b"").decode(),
            "content_type": r.headers.get("Content-Type", ""),
            "etag": r.headers.get("ETag", ""), "size": len(r.body or b"")}


def s3_delete_object(p: dict) -> dict:
    name = str(p.get("bucket") or p.get("name") or "")
    key = str(p.get("key") or "")
    r = s3.dispatch(OBJ, "DELETE", f"/{name}/{key}")
    return {"ok": r.status in (200, 204), "key": key}


# ── DynamoDB ───────────────────────────────────────────────────────────────
def _table_view(name: str) -> dict:
    t = DDB.get_table(name) or {}
    return {"table_name": name, "name": name,
            "partition_key_name": t.get("partition_key_name", "id"),
            "partition_key_type": t.get("partition_key_type", "S"),
            "sort_key_name": t.get("sort_key_name", ""),
            "billing_mode": t.get("billing_mode", "PAY_PER_REQUEST"),
            "item_count": len(t.get("items", {})),
            "table_status": t.get("table_status", "ACTIVE"),
            "table_arn": t.get("table_arn", "")}


def _ddb_err(r) -> dict:
    return {"ok": False, "code": r.body.get("__type", "Error"), "message": r.body.get("message", "")}


def ddb_create_table(p: dict) -> dict:
    name = str(p.get("name") or p.get("TableName") or "").strip()
    pk = str(p.get("partition_key") or p.get("partition_key_name") or "id").strip() or "id"
    sk = str(p.get("sort_key") or p.get("sort_key_name") or "").strip()
    billing = str(p.get("billing_mode") or "PAY_PER_REQUEST")
    payload = {"TableName": name, "BillingMode": billing,
               "AttributeDefinitions": [{"AttributeName": pk, "AttributeType": "S"}],
               "KeySchema": [{"AttributeName": pk, "KeyType": "HASH"}]}
    if sk:
        payload["AttributeDefinitions"].append({"AttributeName": sk, "AttributeType": "S"})
        payload["KeySchema"].append({"AttributeName": sk, "KeyType": "RANGE"})
    r = ddb.dispatch(DDB, "DynamoDB_20120810.CreateTable", payload)
    if r.status != 200:
        return _ddb_err(r)
    return {"ok": True, **_table_view(name)}


def ddb_list_tables(p: dict | None = None) -> dict:
    return {"ok": True, "tables": [_table_view(n) for n in DDB.table_names()]}


def ddb_get_table(p: dict) -> dict:
    name = str(p.get("table") or p.get("name") or "")
    if not DDB.table_exists(name):
        return {"ok": False, "code": "ResourceNotFoundException", "name": name}
    return {"ok": True, **_table_view(name)}


def ddb_delete_table(p: dict) -> dict:
    name = str(p.get("table") or p.get("name") or "")
    r = ddb.dispatch(DDB, "DynamoDB_20120810.DeleteTable", {"TableName": name})
    if r.status != 200:
        return _ddb_err(r)
    return {"ok": True, "name": name}


def _looks_typed(item: dict) -> bool:
    return bool(item) and all(ddb._is_typed_value(v) for v in item.values())


def ddb_put_item(p: dict) -> dict:
    name = str(p.get("table") or p.get("name") or "")
    item = p.get("item") or {}
    # Console may post a plain native item ({"id":"u1","age":30}); the native wire
    # wants typed values. Wrap plain values, pass already-typed items through.
    typed = item if _looks_typed(item) else {k: ddb.native_to_json(v) for k, v in item.items()}
    r = ddb.dispatch(DDB, "DynamoDB_20120810.PutItem", {"TableName": name, "Item": typed})
    if r.status != 200:
        return _ddb_err(r)
    return {"ok": True}


def ddb_list_items(p: dict) -> dict:
    name = str(p.get("table") or p.get("name") or "")
    t = DDB.get_table(name)
    if t is None:
        return {"ok": False, "code": "ResourceNotFoundException", "name": name}
    items = [copy.deepcopy(rec.get("item", {})) for rec in t.get("items", {}).values()]
    return {"ok": True, "items": items}


def _scan_query_params(p: dict) -> dict:
    # The console posts the query body either nested under `params` (SW tuple) or
    # flat. The core's filters accept the console's snake_case shape directly.
    return p.get("params") if isinstance(p.get("params"), dict) else p


def ddb_query(p: dict) -> dict:
    name = str(p.get("table") or p.get("name") or "")
    t = ddb._find_table(DDB, name)
    if t is None:
        return {"ok": False, "code": "ResourceNotFoundException", "name": name}
    matched, scanned = ddb._query_filter(t, _scan_query_params(p))
    return {"ok": True, "items": [copy.deepcopy(r.get("item", {})) for r in matched],
            "count": len(matched), "scanned_count": scanned}


def ddb_scan(p: dict) -> dict:
    name = str(p.get("table") or p.get("name") or "")
    t = ddb._find_table(DDB, name)
    if t is None:
        return {"ok": False, "code": "ResourceNotFoundException", "name": name}
    matched, scanned = ddb._scan_filter(t, _scan_query_params(p))
    return {"ok": True, "items": [copy.deepcopy(r.get("item", {})) for r in matched],
            "count": len(matched), "scanned_count": scanned}
