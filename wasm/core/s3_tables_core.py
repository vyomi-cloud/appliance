# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Amazon S3 Tables (service `s3tables`, SigV4 signing name `s3tables`, rest-json) — substrate-independent.

Table buckets -> namespaces -> Iceberg tables, with the real REST shapes (PUT /buckets,
/namespaces/{tableBucketARN}, /tables/{tableBucketARN}/{namespace}/{name}/…, /get-table, /tag/{arn}).
State lives in `store.account["s3tables"]` of the S3 ObjectStore, so every substrate persists it with the
buckets and Nano's generic store snapshot carries it. Each table owns a hidden backing bucket
`<table-uuid>--table-s3` (its `warehouseLocation`) INSIDE the object store: an initial Iceberg
`metadata/00000-<uuid>.metadata.json` is written there and anything uploaded under `data/` / `metadata/`
through the S3 API is the table's data. The hidden bucket is omitted from ListBuckets like real S3 does.

Loaded by core/s3_object_core.py (routed from AwsWireRouter on the `s3tables` signing name). NO fastapi/boto3.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import uuid
from datetime import datetime, timezone

_ACCOUNT = "123456789012"
_BUCKET_ARN = r"arn:aws[-a-z0-9]*:s3tables:[-a-z0-9]*:\d{12}:bucket/[a-z0-9_-]{3,63}"
_TABLE_ARN_RE = re.compile(rf"^({_BUCKET_ARN})/table/([a-zA-Z0-9_-]{{1,255}})$")
_BUCKET_ARN_RE = re.compile(rf"^({_BUCKET_ARN})$")
_BUCKET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_IDENT_RE = re.compile(r"^[0-9a-z_]+$")
_RESERVED_PREFIXES = ("xn--", "sthree-", "amzn-s3-demo-")
_RESERVED_SUFFIXES = ("-s3alias", "--ol-s3", "--x-s3", "--table-s3", "-s3")
_MAINT_BUCKET = ("icebergUnreferencedFileRemoval",)
_MAINT_TABLE = ("icebergCompaction", "icebergSnapshotManagement")
_NOT_IMPLEMENTED = ("table-bucket-replication", "table-replication", "replication-status", "table-record-expiration",
                    "table-record-expiration-job-status")


def _s3c():
    try:
        from core import s3_object_core as m
    except ImportError:                                    # Pyodide flat layout
        import s3_object_core as m                         # type: ignore
    return m


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _state(store) -> dict:
    return store.account.setdefault("s3tables", {"buckets": {}})


# ── wire helpers ───────────────────────────────────────────────────────────────────────
def _resp(status: int, doc=None):
    m = _s3c()
    hdr = m._amz_headers()
    body = b"" if doc is None or status == 204 else json.dumps(doc).encode()
    return m.S3Response(status=status, headers=hdr, body=body, media_type="application/json" if body else None)


def _err(code: str, message: str, status: int):
    m = _s3c()
    hdr = m._amz_headers({"x-amzn-errortype": code})
    return m.S3Response(status=status, headers=hdr, body=json.dumps({"message": message}).encode(), media_type="application/json")


def _bad(msg):
    return _err("BadRequestException", msg, 400)


def _not_found(what: str):
    return _err("NotFoundException", f"The specified {what} does not exist.", 404)


def _conflict(msg):
    return _err("ConflictException", msg, 409)


def _page(items: list, query: dict, size_key: str, default: int = 1000):
    try:
        start = int(query.get("continuationToken") or 0)
        size = max(1, min(int(query.get(size_key) or default), default))
    except (TypeError, ValueError):
        start, size = 0, default
    nxt = str(start + size) if start + size < len(items) else None
    return items[start:start + size], nxt


def _region(headers: dict) -> str:
    m = re.search(r"Credential=[^/]+/\d+/([^/]+)/", str((headers or {}).get("authorization", "")))
    return m.group(1) if m else "us-east-1"


# ── validation ─────────────────────────────────────────────────────────────────────────
def _validate_bucket_name(name: str):
    if not isinstance(name, str) or not (3 <= len(name) <= 63):
        return "Table bucket names must be between 3 and 63 characters long."
    if not _BUCKET_NAME_RE.match(name):
        return ("Table bucket names can consist only of lowercase letters, numbers, and hyphens (-), and must begin and end "
                "with a letter or number.")
    if name.startswith(_RESERVED_PREFIXES) or name.endswith(_RESERVED_SUFFIXES):
        return "Table bucket names cannot start with xn--, sthree-, amzn-s3-demo- or end with -s3alias, --ol-s3, --x-s3, --table-s3 or -s3."
    return None


def _validate_ident(kind: str, name: str):
    if not isinstance(name, str) or not (1 <= len(name) <= 255):
        return f"{kind} names must be between 1 and 255 characters long."
    if not _IDENT_RE.match(name):
        return f"{kind} names can consist only of lowercase letters, numbers, and underscores (_)."
    if name.startswith("_") or name.endswith("_"):
        return f"{kind} names must begin and end with a letter or number."
    if kind == "Namespace" and (name.startswith("aws") or name == "information_schema"):
        return "Namespace names cannot start with 'aws' and 'information_schema' is reserved."
    return None


def _parse_json(body: bytes):
    if not body:
        return {}
    try:
        d = json.loads(body)
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _validate_encryption(cfg):
    if not isinstance(cfg, dict):
        return "encryptionConfiguration must be an object."
    alg = cfg.get("sseAlgorithm")
    if alg not in ("AES256", "aws:kms"):
        return "sseAlgorithm must be AES256 or aws:kms."
    if alg == "aws:kms" and not cfg.get("kmsKeyArn"):
        return "kmsKeyArn is required when sseAlgorithm is aws:kms."
    if alg == "AES256" and cfg.get("kmsKeyArn"):
        return "kmsKeyArn is only valid with sseAlgorithm aws:kms."
    return None


def _validate_tags(tags):
    if not isinstance(tags, dict) or len(tags) > 50:
        return "tags must be an object of at most 50 entries."
    for k, v in tags.items():
        if not k or len(k) > 128 or not isinstance(v, str) or len(v) > 256 or k.lower().startswith("aws:"):
            return f"Invalid tag '{k}'."
    return None


def _validate_policy(doc):
    try:
        p = json.loads(doc)
    except Exception:
        return "The resource policy must be valid JSON."
    if not isinstance(p, dict) or not p.get("Statement"):
        return "The resource policy must contain at least one statement."
    return None


# ── defaults / maintenance ─────────────────────────────────────────────────────────────
def _default_bucket_maintenance() -> dict:
    return {"icebergUnreferencedFileRemoval": {"status": "enabled", "settings": {
        "icebergUnreferencedFileRemoval": {"unreferencedDays": 3, "nonCurrentDays": 10}}}}


def _default_table_maintenance() -> dict:
    return {"icebergCompaction": {"status": "enabled", "settings": {"icebergCompaction": {"targetFileSizeMB": 512, "strategy": "auto"}}},
            "icebergSnapshotManagement": {"status": "enabled", "settings": {
                "icebergSnapshotManagement": {"minSnapshotsToKeep": 1, "maxSnapshotAgeHours": 120}}}}


def _validate_maintenance(types: tuple, mtype: str, value):
    if mtype not in types:
        return f"Unsupported maintenance type '{mtype}'. Supported: {', '.join(types)}."
    if not isinstance(value, dict) or value.get("status") not in ("enabled", "disabled"):
        return "value.status must be 'enabled' or 'disabled'."
    st = value.get("settings")
    if st is not None:
        if not isinstance(st, dict) or set(st) - {mtype}:
            return f"value.settings must contain only '{mtype}'."
        for k, v in (st.get(mtype) or {}).items():
            if k == "strategy":
                if v not in ("auto", "binpack", "sort", "z-order"):
                    return "strategy must be one of auto, binpack, sort, z-order."
            elif not isinstance(v, int) or isinstance(v, bool) or v < 1:
                return f"{k} must be an integer >= 1."
    return None


# ── resource helpers ───────────────────────────────────────────────────────────────────
def _tb_arn(region: str, name: str) -> str:
    return f"arn:aws:s3tables:{region}:{_ACCOUNT}:bucket/{name}"


def _find_bucket(store, arn: str):
    m = _BUCKET_ARN_RE.match(arn or "")
    if not m:
        return None, _bad("Invalid table bucket ARN.")
    name = arn.rsplit("bucket/", 1)[1]
    b = _state(store)["buckets"].get(name)
    if b is None or b["arn"] != arn:
        return None, _not_found("table bucket")
    return b, None


def _bucket_summary(b: dict) -> dict:
    return {"arn": b["arn"], "name": b["name"], "ownerAccountId": _ACCOUNT, "createdAt": b["created"], "tableBucketId": b["id"], "type": "customer"}


def _table_summary(b: dict, t: dict) -> dict:
    return {"namespace": [t["ns"]], "name": t["name"], "type": "customer", "tableARN": t["arn"], "createdAt": t["created"],
            "modifiedAt": t["modified"], "namespaceId": b["namespaces"][t["ns"]]["id"], "tableBucketId": b["id"]}


def _find_table(b: dict, ns: str, name: str):
    if ns not in b["namespaces"]:
        return None, _not_found("namespace")
    t = b["tables"].get(f"{ns}/{name}")
    if t is None:
        return None, _not_found("table")
    return t, None


def _table_by_arn(store, arn: str):
    m = _TABLE_ARN_RE.match(arn or "")
    if not m:
        return None, None
    b = _state(store)["buckets"].get(m.group(1).rsplit("bucket/", 1)[1])
    if not b:
        return None, None
    t = next((x for x in b["tables"].values() if x["id"] == m.group(2) or x["arn"] == arn), None)
    return b, t


def table_files(store, table_arn: str) -> list:
    """(key, size) of every object in a table's warehouse (console helper)."""
    _b, t = _table_by_arn(store, table_arn)
    if not t:
        return []
    out = []
    for key, entry in sorted(store.bucket_objects(t["warehouse_bucket"]).items()):
        vs = entry.get("versions") or [] if isinstance(entry, dict) else []
        if vs and not vs[0].get("is_delete_marker"):
            out.append((key, int(vs[0].get("size") or 0)))
    return out


def _iceberg_metadata(t: dict, meta: dict) -> dict:
    ice = (meta or {}).get("iceberg") or {}
    fields = []
    if (ice.get("schemaV2") or {}).get("fields"):
        for i, f in enumerate(ice["schemaV2"]["fields"], 1):
            fields.append({"id": f.get("id", i), "name": f["name"], "required": bool(f.get("required")), "type": f.get("type", "string"),
                           **({"doc": f["doc"]} if f.get("doc") else {})})
    else:
        for i, f in enumerate((ice.get("schema") or {}).get("fields") or [], 1):
            fields.append({"id": f.get("id", i), "name": f["name"], "required": bool(f.get("required")), "type": f.get("type", "string")})
    schema = {"type": "struct", "schema-id": 0, "fields": fields}
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return {"format-version": 2, "table-uuid": t["id"], "location": f"s3://{t['warehouse_bucket']}", "last-sequence-number": 0,
            "last-updated-ms": now_ms, "last-column-id": max([f["id"] for f in fields] or [0]), "current-schema-id": 0, "schemas": [schema],
            "default-spec-id": 0, "partition-specs": [{"spec-id": (ice.get("partitionSpec") or {}).get("specId", 0), "fields": [
                {"source-id": p.get("sourceId"), "field-id": p.get("fieldId", 1000 + i), "name": p.get("name"), "transform": p.get("transform")}
                for i, p in enumerate((ice.get("partitionSpec") or {}).get("fields") or [])]}],
            "last-partition-id": 999 + len((ice.get("partitionSpec") or {}).get("fields") or []),
            "default-sort-order-id": 0, "sort-orders": [{"order-id": 0, "fields": []}],
            "properties": dict(ice.get("properties") or {}), "current-snapshot-id": -1, "snapshots": [], "snapshot-log": [], "metadata-log": []}


def _make_backing_bucket(store, name: str) -> None:
    store.create_bucket(name)
    meta = store.buckets[name]
    now = _now()
    meta.update({"region": "us-east-1", "created": now, "creation_date": now, "versioning": "Disabled", "arn": f"arn:aws:s3:::{name}",
                 "tags": {}, "internal": "s3tables", "access": "Bucket and objects not public"})
    store.bucket_objects(name)


def _drop_backing_bucket(store, name: str) -> None:
    store.objects.pop(name, None)
    store.buckets.pop(name, None)


def _put_file(store, bucket: str, key: str, data: bytes, ctype: str = "application/json") -> None:
    m = _s3c()
    m.put_object(store, bucket, key, data, {"content-type": ctype})


def _obj_exists(store, bucket: str, key: str) -> bool:
    e = store.bucket_objects(bucket).get(key) if store.bucket_exists(bucket) else None
    vs = (e or {}).get("versions") or []
    return bool(vs) and not vs[0].get("is_delete_marker")


# ── dispatch ───────────────────────────────────────────────────────────────────────────
def dispatch(store, method: str, raw_path: str, query: dict, headers: dict, body: bytes):
    """`raw_path` is the REST path (/buckets, /tables/<arn>/…), possibly still percent-encoded."""
    m = _s3c()
    method = method.upper()
    path = urllib.parse.unquote(raw_path.split("?", 1)[0])
    query = query or {}
    lh = {str(k).lower(): v for k, v in (headers or {}).items()}
    segs = path.strip("/")
    first, _, rest = segs.partition("/")
    mutating = method != "GET"
    try:
        if first == "buckets":
            r = _buckets(store, method, rest, query, lh, body)
        elif first == "namespaces":
            r = _namespaces(store, method, rest, query, body)
        elif first == "tables":
            r = _tables(store, method, rest, query, lh, body)
        elif first == "get-table" and method == "GET":
            r = _get_table(store, query)
        elif first == "tag":
            r = _tags(store, method, rest, query, body)
        elif first in _NOT_IMPLEMENTED:
            r = _err("NotImplementedException", f"{first} is not implemented by Vyomi.", 501)
        else:
            r = _err("NotFoundException", f"Unknown S3 Tables operation: {method} /{segs}", 404)
    except KeyError as e:                                 # missing required body member
        r = _bad(f"Missing required parameter: {e.args[0]}")
    if mutating:
        store.persist()
    return r


def _split_arn(rest: str):
    """Leading table bucket ARN of a path remainder + what follows it ('' or '/…')."""
    mt = re.match(rf"^({_BUCKET_ARN})(?=/|$)", rest)
    if not mt:
        return None, ""
    return mt.group(1), rest[len(mt.group(1)):]


# ── table buckets ──────────────────────────────────────────────────────────────────────
def _buckets(store, method, rest, query, lh, body):
    st = _state(store)
    if not rest:
        if method == "PUT":
            d = _parse_json(body)
            if d is None:
                return _bad("The request body must be a JSON object.")
            name = d["name"]
            msg = _validate_bucket_name(name)
            if msg:
                return _bad(msg)
            if name in st["buckets"]:
                return _conflict("A table bucket with this name already exists.")
            enc = d.get("encryptionConfiguration")
            if enc is not None and _validate_encryption(enc):
                return _bad(_validate_encryption(enc))
            tags = d.get("tags") or {}
            if _validate_tags(tags):
                return _bad(_validate_tags(tags))
            sc = d.get("storageClassConfiguration") or {"storageClass": "STANDARD"}
            if sc.get("storageClass") not in ("STANDARD", "INTELLIGENT_TIERING"):
                return _bad("storageClass must be STANDARD or INTELLIGENT_TIERING.")
            region = _region(lh)
            b = {"name": name, "arn": _tb_arn(region, name), "id": uuid.uuid4().hex, "created": _now(), "tags": dict(tags), "policy": None,
                 "encryption": enc or {"sseAlgorithm": "AES256"}, "storage_class": sc, "maintenance": {}, "namespaces": {}, "tables": {}}
            st["buckets"][name] = b
            return _resp(200, {"arn": b["arn"]})
        if method == "GET":
            pre = query.get("prefix") or ""
            rows = [_bucket_summary(b) for n, b in sorted(st["buckets"].items()) if n.startswith(pre)]
            if query.get("type") == "aws":
                rows = []
            page, nxt = _page(rows, query, "maxBuckets")
            return _resp(200, {"tableBuckets": page, **({"continuationToken": nxt} if nxt else {})})
        return _err("MethodNotAllowedException", method, 405)
    arn, sub = _split_arn(rest)
    if arn is None:
        return _bad("Invalid table bucket ARN.")
    b, err = _find_bucket(store, arn)
    if err:
        return err
    sub = sub.strip("/")
    if not sub:
        if method == "GET":
            return _resp(200, _bucket_summary(b))
        if method == "DELETE":
            if b["namespaces"]:
                return _conflict("The table bucket is not empty. Delete all namespaces (and their tables) first.")
            del st["buckets"][b["name"]]
            return _resp(204)
    elif sub == "policy":
        if method == "PUT":
            d = _parse_json(body)
            if d is None:
                return _bad("The request body must be a JSON object.")
            msg = _validate_policy(d["resourcePolicy"])
            if msg:
                return _bad(msg)
            b["policy"] = d["resourcePolicy"]
            return _resp(200)
        if method == "GET":
            if not b["policy"]:
                return _not_found("table bucket policy")
            return _resp(200, {"resourcePolicy": b["policy"]})
        if method == "DELETE":
            if not b["policy"]:
                return _not_found("table bucket policy")
            b["policy"] = None
            return _resp(204)
    elif sub == "encryption":
        if method == "PUT":
            d = _parse_json(body)
            if d is None:
                return _bad("The request body must be a JSON object.")
            msg = _validate_encryption(d["encryptionConfiguration"])
            if msg:
                return _bad(msg)
            b["encryption"] = d["encryptionConfiguration"]
            return _resp(200)
        if method == "GET":
            return _resp(200, {"encryptionConfiguration": b["encryption"]})
        if method == "DELETE":
            b["encryption"] = {"sseAlgorithm": "AES256"}
            return _resp(204)
    elif sub == "storage-class":
        if method == "PUT":
            d = _parse_json(body) or {}
            sc = d.get("storageClassConfiguration") or {}
            if sc.get("storageClass") not in ("STANDARD", "INTELLIGENT_TIERING"):
                return _bad("storageClass must be STANDARD or INTELLIGENT_TIERING.")
            b["storage_class"] = sc
            return _resp(200)
        if method == "GET":
            return _resp(200, {"storageClassConfiguration": b["storage_class"]})
    elif sub == "maintenance" and method == "GET":
        cfg = {**_default_bucket_maintenance(), **b["maintenance"]}
        return _resp(200, {"tableBucketARN": b["arn"], "configuration": cfg})
    elif sub.startswith("maintenance/") and method == "PUT":
        mtype = sub.split("/", 1)[1]
        d = _parse_json(body)
        if d is None:
            return _bad("The request body must be a JSON object.")
        msg = _validate_maintenance(_MAINT_BUCKET, mtype, d["value"])
        if msg:
            return _bad(msg)
        b["maintenance"][mtype] = d["value"]
        return _resp(204)
    elif sub == "metrics":
        return _err("NotImplementedException", "Table bucket metrics configuration is not implemented by Vyomi.", 501)
    return _err("MethodNotAllowedException", f"{method} /buckets/{{arn}}/{sub}", 405)


# ── namespaces ─────────────────────────────────────────────────────────────────────────
def _namespaces(store, method, rest, query, body):
    arn, sub = _split_arn(rest)
    if arn is None:
        return _bad("Invalid table bucket ARN.")
    b, err = _find_bucket(store, arn)
    if err:
        return err
    sub = sub.strip("/")
    summ = lambda ns, n: {"namespace": [ns], "createdAt": n["created"], "createdBy": _ACCOUNT, "ownerAccountId": _ACCOUNT,
                          "namespaceId": n["id"], "tableBucketId": b["id"]}
    if not sub:
        if method == "PUT":
            d = _parse_json(body)
            if d is None:
                return _bad("The request body must be a JSON object.")
            nsl = d["namespace"]
            if not isinstance(nsl, list) or len(nsl) != 1:
                return _bad("namespace must be a list with exactly one name.")
            ns = nsl[0]
            msg = _validate_ident("Namespace", ns)
            if msg:
                return _bad(msg)
            if ns in b["namespaces"]:
                return _conflict("A namespace with this name already exists in the table bucket.")
            b["namespaces"][ns] = {"id": uuid.uuid4().hex, "created": _now()}
            return _resp(200, {"tableBucketARN": b["arn"], "namespace": [ns]})
        if method == "GET":
            pre = query.get("prefix") or ""
            rows = [summ(ns, n) for ns, n in sorted(b["namespaces"].items()) if ns.startswith(pre)]
            page, nxt = _page(rows, query, "maxNamespaces")
            return _resp(200, {"namespaces": page, **({"continuationToken": nxt} if nxt else {})})
    else:
        ns = sub
        n = b["namespaces"].get(ns)
        if n is None:
            return _not_found("namespace")
        if method == "GET":
            return _resp(200, summ(ns, n))
        if method == "DELETE":
            if any(t["ns"] == ns for t in b["tables"].values()):
                return _conflict("The namespace is not empty. Delete all tables in it first.")
            del b["namespaces"][ns]
            return _resp(204)
    return _err("MethodNotAllowedException", method, 405)


# ── tables ─────────────────────────────────────────────────────────────────────────────
def _tables(store, method, rest, query, lh, body):
    arn, sub = _split_arn(rest)
    if arn is None:
        return _bad("Invalid table bucket ARN.")
    b, err = _find_bucket(store, arn)
    if err:
        return err
    parts = [p for p in sub.split("/") if p]
    if not parts:
        if method != "GET":
            return _err("MethodNotAllowedException", method, 405)
        ns, pre = query.get("namespace"), query.get("prefix") or ""
        if ns and ns not in b["namespaces"]:
            return _not_found("namespace")
        rows = [_table_summary(b, t) for k, t in sorted(b["tables"].items()) if (not ns or t["ns"] == ns) and t["name"].startswith(pre)]
        page, nxt = _page(rows, query, "maxTables")
        return _resp(200, {"tables": page, **({"continuationToken": nxt} if nxt else {})})
    ns = parts[0]
    if len(parts) == 1:
        if method != "PUT":
            return _err("MethodNotAllowedException", method, 405)
        return _create_table(store, b, ns, lh, body)
    name = parts[1]
    action = "/".join(parts[2:])
    if not action and method == "DELETE":
        t, err = _find_table(b, ns, name)
        if err:
            return err
        tok = query.get("versionToken")
        if tok and tok != t["version_token"]:
            return _conflict("The version token does not match the table's current version token.")
        _drop_backing_bucket(store, t["warehouse_bucket"])
        del b["tables"][f"{ns}/{name}"]
        return _resp(204)
    t, err = _find_table(b, ns, name)
    if err:
        return err
    if action == "metadata-location":
        if method == "GET":
            return _resp(200, {"versionToken": t["version_token"], "metadataLocation": t["metadata_location"], "warehouseLocation": f"s3://{t['warehouse_bucket']}"})
        if method == "PUT":
            d = _parse_json(body)
            if d is None:
                return _bad("The request body must be a JSON object.")
            if d["versionToken"] != t["version_token"]:
                return _conflict("The version token does not match the table's current version token.")
            loc = d["metadataLocation"]
            mt = re.match(rf"^s3://{re.escape(t['warehouse_bucket'])}/(metadata/.+\.metadata\.json)$", loc or "")
            if not mt:
                return _bad(f"metadataLocation must be an s3://{t['warehouse_bucket']}/metadata/<name>.metadata.json URI.")
            if not _obj_exists(store, t["warehouse_bucket"], mt.group(1)):
                return _bad("The metadata file does not exist at the given location; upload it to the table's warehouse first.")
            t["metadata_location"] = loc
            t["version_token"] = uuid.uuid4().hex[:16]
            t["modified"] = _now()
            return _resp(200, {"name": t["name"], "tableARN": t["arn"], "namespace": [t["ns"]], "versionToken": t["version_token"], "metadataLocation": loc})
    elif action == "rename" and method == "PUT":
        d = _parse_json(body)
        if d is None:
            return _bad("The request body must be a JSON object.")
        nns, nname = d.get("newNamespaceName") or ns, d.get("newName") or name
        if not d.get("newNamespaceName") and not d.get("newName"):
            return _bad("newNamespaceName or newName is required.")
        for kind, v in (("Namespace", nns), ("Table", nname)):
            msg = _validate_ident(kind, v)
            if msg:
                return _bad(msg)
        if d.get("versionToken") and d["versionToken"] != t["version_token"]:
            return _conflict("The version token does not match the table's current version token.")
        if nns not in b["namespaces"]:
            return _not_found("namespace")
        if f"{nns}/{nname}" in b["tables"]:
            return _conflict("A table with the new name already exists in the namespace.")
        del b["tables"][f"{ns}/{name}"]
        t.update({"ns": nns, "name": nname, "modified": _now()})
        b["tables"][f"{nns}/{nname}"] = t
        return _resp(204)
    elif action == "policy":
        if method == "PUT":
            d = _parse_json(body)
            if d is None:
                return _bad("The request body must be a JSON object.")
            msg = _validate_policy(d["resourcePolicy"])
            if msg:
                return _bad(msg)
            t["policy"] = d["resourcePolicy"]
            return _resp(200)
        if method == "GET":
            if not t["policy"]:
                return _not_found("table policy")
            return _resp(200, {"resourcePolicy": t["policy"]})
        if method == "DELETE":
            if not t["policy"]:
                return _not_found("table policy")
            t["policy"] = None
            return _resp(204)
    elif action == "encryption" and method == "GET":
        return _resp(200, {"encryptionConfiguration": t["encryption"] or b["encryption"]})
    elif action == "storage-class" and method == "GET":
        return _resp(200, {"storageClassConfiguration": t["storage_class"] or b["storage_class"]})
    elif action == "maintenance" and method == "GET":
        return _resp(200, {"tableARN": t["arn"], "configuration": {**_default_table_maintenance(), **t["maintenance"]}})
    elif action.startswith("maintenance/") and method == "PUT":
        mtype = action.split("/", 1)[1]
        d = _parse_json(body)
        if d is None:
            return _bad("The request body must be a JSON object.")
        msg = _validate_maintenance(_MAINT_TABLE, mtype, d["value"])
        if msg:
            return _bad(msg)
        t["maintenance"][mtype] = d["value"]
        return _resp(204)
    elif action == "maintenance-job-status" and method == "GET":
        cfg = {**_default_table_maintenance(), **t["maintenance"]}
        return _resp(200, {"tableARN": t["arn"], "status": {k: {"status": "Not_Yet_Run" if v["status"] == "enabled" else "Disabled"} for k, v in cfg.items()}})
    return _err("MethodNotAllowedException", f"{method} /tables/…/{action}", 405)


def _create_table(store, b, ns, lh, body):
    d = _parse_json(body)
    if d is None:
        return _bad("The request body must be a JSON object.")
    name, fmt = d["name"], d["format"]
    if ns not in b["namespaces"]:
        return _not_found("namespace")
    msg = _validate_ident("Table", name)
    if msg:
        return _bad(msg)
    if fmt != "ICEBERG":
        return _bad("format must be ICEBERG.")
    if f"{ns}/{name}" in b["tables"]:
        return _conflict("A table with this name already exists in the namespace.")
    meta = d.get("metadata") or {}
    ice = meta.get("iceberg") or {}
    flds = (ice.get("schema") or {}).get("fields") or (ice.get("schemaV2") or {}).get("fields") or []
    seen = set()
    for f in flds:
        if not isinstance(f, dict) or not f.get("name") or f.get("type") in (None, ""):
            return _bad("Every schema field needs a name and a type.")
        if f["name"] in seen:
            return _bad(f"Duplicate schema field name '{f['name']}'.")
        seen.add(f["name"])
    enc = d.get("encryptionConfiguration")
    if enc is not None and _validate_encryption(enc):
        return _bad(_validate_encryption(enc))
    tags = d.get("tags") or {}
    if _validate_tags(tags):
        return _bad(_validate_tags(tags))
    tid = str(uuid.uuid4())
    t = {"id": tid, "name": name, "ns": ns, "arn": f"{b['arn']}/table/{tid}", "created": _now(), "modified": _now(), "format": "ICEBERG",
         "warehouse_bucket": f"{tid}--table-s3", "version_token": uuid.uuid4().hex[:16], "metadata_location": "", "policy": None,
         "encryption": enc, "storage_class": d.get("storageClassConfiguration"), "maintenance": {}, "tags": dict(tags), "iceberg": meta}
    _make_backing_bucket(store, t["warehouse_bucket"])
    mkey = f"metadata/00000-{uuid.uuid4()}.metadata.json"
    _put_file(store, t["warehouse_bucket"], mkey, json.dumps(_iceberg_metadata(t, meta), indent=2).encode())
    t["metadata_location"] = f"s3://{t['warehouse_bucket']}/{mkey}"
    b["tables"][f"{ns}/{name}"] = t
    return _resp(200, {"tableARN": t["arn"], "versionToken": t["version_token"]})


def _get_table(store, query):
    if query.get("tableArn"):
        b, t = _table_by_arn(store, query["tableArn"])
        if not t:
            return _not_found("table")
    else:
        if not (query.get("tableBucketARN") and query.get("namespace") and query.get("name")):
            return _bad("Specify tableArn, or tableBucketARN with namespace and name.")
        b, err = _find_bucket(store, query["tableBucketARN"])
        if err:
            return err
        t, err = _find_table(b, query["namespace"], query["name"])
        if err:
            return err
    return _resp(200, {"name": t["name"], "type": "customer", "tableARN": t["arn"], "namespace": [t["ns"]], "namespaceId": b["namespaces"][t["ns"]]["id"],
                       "versionToken": t["version_token"], "metadataLocation": t["metadata_location"], "warehouseLocation": f"s3://{t['warehouse_bucket']}",
                       "createdAt": t["created"], "createdBy": _ACCOUNT, "modifiedAt": t["modified"], "modifiedBy": _ACCOUNT, "ownerAccountId": _ACCOUNT,
                       "format": t["format"], "tableBucketId": b["id"]})


# ── tagging (/tag/{resourceArn}) ───────────────────────────────────────────────────────
def _tag_target(store, arn):
    if _BUCKET_ARN_RE.match(arn or ""):
        b, err = _find_bucket(store, arn)
        return (b, err)
    b, t = _table_by_arn(store, arn)
    if t:
        return t, None
    return None, _not_found("resource")


def _tags(store, method, rest, query, body):
    obj, err = _tag_target(store, rest)
    if err:
        return err
    if method == "GET":
        return _resp(200, {"tags": dict(obj["tags"])})
    if method == "POST":
        d = _parse_json(body)
        if d is None:
            return _bad("The request body must be a JSON object.")
        merged = {**obj["tags"], **d["tags"]}
        msg = _validate_tags(merged)
        if msg:
            return _bad(msg)
        obj["tags"] = merged
        return _resp(200, {})
    if method == "DELETE":
        raw = query.get("tagKeys") or ""
        keys = raw if isinstance(raw, list) else [k for k in str(raw).split(",") if k]
        for k in keys:
            obj["tags"].pop(k, None)
        return _resp(204)
    return _err("MethodNotAllowedException", method, 405)
