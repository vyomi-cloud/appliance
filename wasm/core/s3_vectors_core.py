# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Amazon S3 Vectors (service `s3vectors`, SigV4 signing name `s3vectors`, rest-json) — substrate-independent.

Vector buckets -> vector indexes -> vectors, with the real operation shapes (every operation is `POST /<Operation>`
with a JSON body): Create/Get/List/DeleteVectorBucket, Put/Get/DeleteVectorBucketPolicy, Create/Get/List/DeleteIndex,
PutVectors / GetVectors / ListVectors / DeleteVectors and QueryVectors (exact brute-force nearest neighbour over the
index with the real metadata-filter grammar). State lives in `store.account["s3vectors"]` of the S3 ObjectStore, so
every substrate persists it. Pure Python, no numpy / fastapi / boto3 — loads under Pyodide.

Honest limits: the search is an exact scan, not an approximate (ANN) index, so it is fine for thousands of vectors,
not millions; no throughput/latency/recall characteristics are modelled.
"""
from __future__ import annotations

import json
import math
import re
import urllib.parse
from datetime import datetime, timezone

_ACCOUNT = "123456789012"
_REGION = "us-east-1"
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_INDEX_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_MAX_DIM = 4096
_MAX_TOPK = 100
_MAX_PUT = 500
_MAX_META_KEYS = 50
_MAX_META_BYTES = 40 * 1024
_MAX_FILTERABLE_BYTES = 2 * 1024
_METRICS = ("euclidean", "cosine")


class _Err(Exception):
    def __init__(self, code, message, status):
        self.code, self.message, self.status = code, message, status


def _bad(msg):
    return _Err("ValidationException", msg, 400)


def _nf(msg):
    return _Err("NotFoundException", msg, 404)


def _s3c():
    try:
        from core import s3_object_core as m
    except ImportError:                                    # Pyodide flat layout
        import s3_object_core as m                         # type: ignore
    return m


def _state(store) -> dict:
    return store.account.setdefault("s3vectors", {"buckets": {}})


def _bucket_arn(name):
    return f"arn:aws:s3vectors:{_REGION}:{_ACCOUNT}:bucket/{name}"


def _index_arn(b, i):
    return f"arn:aws:s3vectors:{_REGION}:{_ACCOUNT}:bucket/{b}/index/{i}"


def _ts() -> float:
    return round(datetime.now(timezone.utc).timestamp(), 3)


# ── resolution ────────────────────────────────────────────────────────────────────────
def _bucket(st, p):
    name = p.get("vectorBucketName")
    arn = p.get("vectorBucketArn")
    if not name and arn:
        mt = re.match(r"^arn:aws[-a-z0-9]*:s3vectors:[-a-z0-9]*:\d{12}:bucket/([^/]+)$", arn)
        if not mt:
            raise _bad("Invalid vectorBucketArn")
        name = mt.group(1)
    if not name:
        raise _bad("Either vectorBucketName or vectorBucketArn is required")
    b = st["buckets"].get(name)
    if b is None:
        raise _nf(f"Vector bucket {name} does not exist")
    return b


def _index(st, p):
    b = _bucket(st, p)
    name = p.get("indexName")
    arn = p.get("indexArn")
    if not name and arn:
        mt = re.match(r"^arn:aws[-a-z0-9]*:s3vectors:[-a-z0-9]*:\d{12}:bucket/[^/]+/index/([^/]+)$", arn)
        if not mt:
            raise _bad("Invalid indexArn")
        name = mt.group(1)
    if not name:
        raise _bad("Either indexName or indexArn is required")
    ix = b["indexes"].get(name)
    if ix is None:
        raise _nf(f"Index {name} does not exist in vector bucket {b['name']}")
    return b, ix


def _page(items, p, key_fn):
    mx = p.get("maxResults", 500)
    if not isinstance(mx, int) or mx < 1 or mx > 500:
        raise _bad("maxResults must be between 1 and 500")
    tok = p.get("nextToken")
    items = sorted(items, key=key_fn)
    if tok:
        items = [i for i in items if key_fn(i) > tok]
    out = items[:mx]
    return out, (key_fn(out[-1]) if len(items) > mx else None)


# ── vector buckets ────────────────────────────────────────────────────────────────────
def _enc(p):
    cfg = p.get("encryptionConfiguration") or {"sseType": "AES256"}
    t = cfg.get("sseType", "AES256")
    if t not in ("AES256", "aws:kms"):
        raise _bad("sseType must be AES256 or aws:kms")
    out = {"sseType": t}
    if t == "aws:kms" and cfg.get("kmsKeyArn"):
        out["kmsKeyArn"] = cfg["kmsKeyArn"]
    return out


def _bsum(b):
    return {"vectorBucketName": b["name"], "vectorBucketArn": _bucket_arn(b["name"]), "creationTime": b["created"]}


def _create_bucket(st, p):
    n = p.get("vectorBucketName")
    if not isinstance(n, str) or not _BUCKET_RE.match(n):
        raise _bad("vectorBucketName must be 3-63 characters: lowercase letters, numbers and hyphens")
    if n in st["buckets"]:
        raise _Err("ConflictException", f"Vector bucket {n} already exists", 409)
    st["buckets"][n] = {"name": n, "created": _ts(), "enc": _enc(p), "policy": None, "indexes": {}}
    return {"vectorBucketArn": _bucket_arn(n)}


def _get_bucket(st, p):
    b = _bucket(st, p)
    return {"vectorBucket": {**_bsum(b), "encryptionConfiguration": b["enc"]}}


def _list_buckets(st, p):
    items = [b for b in st["buckets"].values() if b["name"].startswith(p.get("prefix") or "")]
    page, nxt = _page(items, p, lambda b: b["name"])
    out = {"vectorBuckets": [_bsum(b) for b in page]}
    if nxt:
        out["nextToken"] = nxt
    return out


def _delete_bucket(st, p):
    b = _bucket(st, p)
    if b["indexes"]:
        raise _Err("ConflictException", "The vector bucket still contains indexes; delete them first", 409)
    del st["buckets"][b["name"]]
    return {}


def _put_policy(st, p):
    b = _bucket(st, p)
    pol = p.get("policy")
    try:
        json.loads(pol)
    except (TypeError, ValueError):
        raise _bad("policy must be a valid JSON policy document")
    b["policy"] = pol
    return {}


def _get_policy(st, p):
    b = _bucket(st, p)
    if not b["policy"]:
        raise _nf("The vector bucket policy does not exist")
    return {"policy": b["policy"]}


def _delete_policy(st, p):
    _bucket(st, p)["policy"] = None
    return {}


# ── indexes ───────────────────────────────────────────────────────────────────────────
def _isum(b, ix):
    return {"vectorBucketName": b["name"], "indexName": ix["name"], "indexArn": _index_arn(b["name"], ix["name"]),
            "creationTime": ix["created"]}


def _create_index(st, p):
    b = _bucket(st, p)
    n = p.get("indexName")
    if not isinstance(n, str) or not _INDEX_RE.match(n):
        raise _bad("indexName must be 3-63 characters: lowercase letters, numbers, hyphens and dots")
    if p.get("dataType") != "float32":
        raise _bad("dataType must be float32")
    d = p.get("dimension")
    if not isinstance(d, int) or isinstance(d, bool) or not 1 <= d <= _MAX_DIM:
        raise _bad(f"dimension must be an integer between 1 and {_MAX_DIM}")
    if p.get("distanceMetric") not in _METRICS:
        raise _bad("distanceMetric must be euclidean or cosine")
    nf = (p.get("metadataConfiguration") or {}).get("nonFilterableMetadataKeys") or []
    if not isinstance(nf, list) or len(nf) > 10 or not all(isinstance(k, str) and k for k in nf):
        raise _bad("nonFilterableMetadataKeys must be a list of up to 10 key names")
    if n in b["indexes"]:
        raise _Err("ConflictException", f"Index {n} already exists in vector bucket {b['name']}", 409)
    b["indexes"][n] = {"name": n, "created": _ts(), "dim": d, "metric": p["distanceMetric"], "dataType": "float32",
                       "nonFilterable": nf, "vectors": {}}
    return {"indexArn": _index_arn(b["name"], n)}


def _get_index(st, p):
    b, ix = _index(st, p)
    out = {**_isum(b, ix), "dataType": ix["dataType"], "dimension": ix["dim"], "distanceMetric": ix["metric"]}
    if ix["nonFilterable"]:
        out["metadataConfiguration"] = {"nonFilterableMetadataKeys": ix["nonFilterable"]}
    return {"index": out}


def _list_indexes(st, p):
    b = _bucket(st, p)
    items = [i for i in b["indexes"].values() if i["name"].startswith(p.get("prefix") or "")]
    page, nxt = _page(items, p, lambda i: i["name"])
    out = {"indexes": [_isum(b, i) for i in page]}
    if nxt:
        out["nextToken"] = nxt
    return out


def _delete_index(st, p):
    b, ix = _index(st, p)
    del b["indexes"][ix["name"]]
    return {}


# ── vectors ───────────────────────────────────────────────────────────────────────────
def _vec(ix, data, what="data"):
    v = (data or {}).get("float32") if isinstance(data, dict) else None
    if not isinstance(v, list) or not v:
        raise _bad(f"{what}.float32 must be a non-empty list of numbers")
    if len(v) != ix["dim"]:
        raise _bad(f"Vector dimension {len(v)} does not match the index dimension {ix['dim']}")
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
            raise _bad(f"{what}.float32 must contain only finite numbers")
        out.append(float(x))
    return out


def _check_meta(ix, meta):
    if meta is None:
        return None
    if not isinstance(meta, dict):
        raise _bad("metadata must be a JSON object")
    if len(meta) > _MAX_META_KEYS:
        raise _bad(f"metadata may have at most {_MAX_META_KEYS} keys")
    if len(json.dumps(meta)) > _MAX_META_BYTES:
        raise _bad("metadata is larger than 40 KB")
    fil = {k: v for k, v in meta.items() if k not in ix["nonFilterable"]}
    if len(json.dumps(fil)) > _MAX_FILTERABLE_BYTES:
        raise _bad("filterable metadata is larger than 2 KB; list large keys in nonFilterableMetadataKeys")
    return meta


def _put_vectors(st, p):
    b, ix = _index(st, p)
    vs = p.get("vectors")
    if not isinstance(vs, list) or not 1 <= len(vs) <= _MAX_PUT:
        raise _bad(f"vectors must contain between 1 and {_MAX_PUT} items")
    staged = []
    for v in vs:
        k = v.get("key") if isinstance(v, dict) else None
        if not isinstance(k, str) or not 1 <= len(k) <= 1024:
            raise _bad("each vector needs a key of 1-1024 characters")
        staged.append((k, _vec(ix, v.get("data")), _check_meta(ix, v.get("metadata"))))
    for k, data, meta in staged:                                  # all-or-nothing: validated before any write
        ix["vectors"][k] = {"data": data, "metadata": meta}
    return {}


def _shape(ix, k, rec, p, dist=None):
    o = {"key": k}
    if p.get("returnData"):
        o["data"] = {"float32": rec["data"]}
    if p.get("returnMetadata") and rec["metadata"] is not None:
        o["metadata"] = rec["metadata"]
    if dist is not None:
        o["distance"] = dist
    return o


def _get_vectors(st, p):
    _, ix = _index(st, p)
    ks = p.get("keys")
    if not isinstance(ks, list) or not 1 <= len(ks) <= 100:
        raise _bad("keys must contain between 1 and 100 items")
    return {"vectors": [_shape(ix, k, ix["vectors"][k], p) for k in ks if k in ix["vectors"]]}


def _list_vectors(st, p):
    _, ix = _index(st, p)
    page, nxt = _page(list(ix["vectors"]), p, lambda k: k)
    out = {"vectors": [_shape(ix, k, ix["vectors"][k], p) for k in page]}
    if nxt:
        out["nextToken"] = nxt
    return out


def _delete_vectors(st, p):
    _, ix = _index(st, p)
    ks = p.get("keys")
    if not isinstance(ks, list) or not 1 <= len(ks) <= _MAX_PUT:
        raise _bad(f"keys must contain between 1 and {_MAX_PUT} items")
    for k in ks:
        ix["vectors"].pop(k, None)                                # absent keys are not an error (idempotent, like S3)
    return {}


def _distance(metric, a, b):
    if metric == "euclidean":
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - sum(x * y for x, y in zip(a, b)) / (na * nb)    # cosine distance = 1 - cosine similarity


_CMP = {"$gt": lambda a, b: a > b, "$gte": lambda a, b: a >= b,
        "$lt": lambda a, b: a < b, "$lte": lambda a, b: a <= b}


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _eq(a, b):
    return a == b if (_num(a) and _num(b)) else (type(a) is type(b) and a == b)


def _scalar_ok(x):
    return isinstance(x, str) or _num(x) or isinstance(x, bool)


def _match(meta, flt):
    """The documented metadata-filter grammar: implicit AND of field conditions, $and / $or, and the operators
    $eq $ne $gt $gte $lt $lte $in $nin $exists."""
    if not isinstance(flt, dict):
        raise _bad("filter must be a JSON object")
    meta = meta or {}
    for k, cond in flt.items():
        if k in ("$and", "$or"):
            if not isinstance(cond, list) or not cond:
                raise _bad(f"{k} needs a non-empty list of filters")
            rs = [_match(meta, c) for c in cond]
            if not (all(rs) if k == "$and" else any(rs)):
                return False
            continue
        if k.startswith("$"):
            raise _bad(f"Unsupported filter operator {k}")
        has, val = k in meta, meta.get(k)
        conds = cond if isinstance(cond, dict) and cond and all(c.startswith("$") for c in cond) else {"$eq": cond}
        for op, arg in conds.items():
            if op == "$exists":
                if not isinstance(arg, bool):
                    raise _bad("$exists needs a boolean")
                ok = has == arg
            elif op in ("$in", "$nin"):
                if not isinstance(arg, list) or not all(_scalar_ok(a) for a in arg):
                    raise _bad(f"{op} needs a list of strings, numbers or booleans")
                ok = has and ((val in arg) if op == "$in" else (val not in arg))
                if op == "$nin" and not has:
                    ok = True
            elif op in ("$eq", "$ne"):
                if not _scalar_ok(arg):
                    raise _bad(f"{op} needs a string, number or boolean")
                ok = (has and _eq(val, arg)) if op == "$eq" else (not has or not _eq(val, arg))
            elif op in ("$gt", "$gte", "$lt", "$lte"):
                if not _num(arg):
                    raise _bad(f"{op} needs a number")
                ok = has and _num(val) and _CMP[op](val, arg)
            else:
                raise _bad(f"Unsupported filter operator {op}")
            if not ok:
                return False
    return True


def _query(st, p):
    _, ix = _index(st, p)
    q = _vec(ix, p.get("queryVector"), "queryVector")
    k = p.get("topK")
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= _MAX_TOPK:
        raise _bad(f"topK must be an integer between 1 and {_MAX_TOPK}")
    flt = p.get("filter")
    scored = []
    for key, rec in ix["vectors"].items():
        if flt is not None and not _match(rec["metadata"], flt):
            continue
        scored.append((_distance(ix["metric"], q, rec["data"]), key))
    scored.sort()
    out = []
    for d, key in scored[:k]:
        o = {"key": key}
        if p.get("returnDistance"):
            o["distance"] = d
        if p.get("returnMetadata") and ix["vectors"][key]["metadata"] is not None:
            o["metadata"] = ix["vectors"][key]["metadata"]
        out.append(o)
    return {"vectors": out, "distanceMetric": ix["metric"]}


_OPS = {
    "CreateVectorBucket": _create_bucket, "GetVectorBucket": _get_bucket, "ListVectorBuckets": _list_buckets,
    "DeleteVectorBucket": _delete_bucket, "PutVectorBucketPolicy": _put_policy, "GetVectorBucketPolicy": _get_policy,
    "DeleteVectorBucketPolicy": _delete_policy, "CreateIndex": _create_index, "GetIndex": _get_index,
    "ListIndexes": _list_indexes, "DeleteIndex": _delete_index, "PutVectors": _put_vectors, "GetVectors": _get_vectors,
    "ListVectors": _list_vectors, "DeleteVectors": _delete_vectors, "QueryVectors": _query,
}
_MUTATING = {"CreateVectorBucket", "DeleteVectorBucket", "PutVectorBucketPolicy", "DeleteVectorBucketPolicy",
             "CreateIndex", "DeleteIndex", "PutVectors", "DeleteVectors"}


def dispatch(store, method: str, raw_path: str, query: dict, headers: dict, body: bytes):
    """`raw_path` is `/<Operation>`; every S3 Vectors operation is a JSON POST."""
    m = _s3c()
    op = urllib.parse.unquote(raw_path.split("?", 1)[0]).strip("/")

    def resp(status, doc):
        return m.S3Response(status=status, headers=m._amz_headers(), body=json.dumps(doc).encode(), media_type="application/json")

    fn = _OPS.get(op)
    if fn is None:
        return resp(404, {"__type": "NotFoundException", "message": f"Unknown S3 Vectors operation: {method} /{op}"})
    if method.upper() != "POST":
        return resp(405, {"__type": "MethodNotAllowedException", "message": f"{op} must be called with POST"})
    try:
        p = json.loads(body or b"{}")
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return resp(400, {"__type": "ValidationException", "message": "The request body must be a JSON object"})
    try:
        out = fn(_state(store), p)
    except _Err as e:
        return resp(e.status, {"__type": e.code, "message": e.message})
    if op in _MUTATING:
        store.persist()
    return resp(200, out)
