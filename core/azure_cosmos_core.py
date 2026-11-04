"""Azure Cosmos DB (SQL / Core API) data-plane core — substrate-independent,
the Azure NoSQL analogue of core/gcp_storage_core.py and core/dynamodb_core.py.

Speaks the native **Cosmos DB REST API (SQL / Core API)** wire so the native
`azure-cosmos` SDK works unchanged against it: database / collection (container)
/ document CRUD + SQL queries. All resources carry the Cosmos system props
(`_rid` unique, `_self`, `_etag`, `_ts` int) the SDK expects.

NO fastapi / azure / socket / subprocess imports → loads under Pyodide. State
lives in a self-contained in-memory `CosmosStore` in this module (no external
seam — the resource model is Cosmos-specific).

Wire summary (paths are the azure-cosmos resource hierarchy):
  POST   /dbs                              create database   {"id": "db"}
  GET    /dbs                              list databases    -> {"Databases", "_count"}
  GET    /dbs/{db}                         read database
  DELETE /dbs/{db}                         delete database
  POST   /dbs/{db}/colls                   create collection {"id","partitionKey"}
  GET    /dbs/{db}/colls                   list collections  -> {"DocumentCollections","_count"}
  GET    /dbs/{db}/colls/{c}               read collection
  DELETE /dbs/{db}/colls/{c}               delete collection
  POST   /dbs/{db}/colls/{c}/docs          create document (arbitrary JSON w/ id)
                                           OR query when x-ms-documentdb-isquery: true
  GET    /dbs/{db}/colls/{c}/docs          list documents    -> {"Documents","_count"}
  GET    /dbs/{db}/colls/{c}/docs/{id}     read document
  DELETE /dbs/{db}/colls/{c}/docs/{id}     delete document

Errors: JSON {"code": "NotFound", "message": ...} matching the HTTP status
(404 NotFound, 409 Conflict, 400 BadRequest).
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Response:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


# ── primitives ────────────────────────────────────────────────────────────
def _now_ts() -> int:
    return int(time.time())


def _rid() -> str:
    # Cosmos _rid is an opaque base64-ish token; uniqueness is what matters.
    return uuid.uuid4().hex[:16]


def _etag() -> str:
    return '"' + str(uuid.uuid4()) + '"'


def _json(status: int, obj: dict, headers: dict | None = None) -> Response:
    return Response(status=status, headers=headers or {},
                    body=json.dumps(obj).encode("utf-8"))


def _err(status: int, code: str, message: str) -> Response:
    return Response(status=status,
                    body=json.dumps({"code": code, "message": message}).encode("utf-8"))


# ── store ─────────────────────────────────────────────────────────────────
class CosmosStore:
    """Self-contained in-memory Cosmos state.

    dbs[db_id]                              = {sys props}
    colls[db_id][coll_id]                   = {sys props, "partitionKey": {...}}
    docs[db_id][coll_id][doc_id]            = {full document incl. system props}
    """

    def __init__(self) -> None:
        self.dbs: dict[str, dict] = {}
        self.colls: dict[str, dict[str, dict]] = {}
        self.docs: dict[str, dict[str, dict[str, dict]]] = {}

    def persist(self) -> None:
        """Write-through hook (no-op in-memory; a backed subclass overrides it)."""


# ── resource views ────────────────────────────────────────────────────────
def _db_view(db_id: str, entry: dict) -> dict:
    return {
        "id": db_id,
        "_rid": entry["_rid"],
        "_self": f"dbs/{entry['_rid']}/",
        "_etag": entry["_etag"],
        "_ts": entry["_ts"],
        "_colls": "colls/",
        "_users": "users/",
    }


def validate_partition_key(pk) -> str | None:
    """Error text for an invalid container partitionKey definition, else None. Hash = one path; MultiHash
    (hierarchical, version 2) = two or three distinct paths, as in the real service."""
    if not isinstance(pk, dict):
        return "partitionKey must be an object with 'paths' and 'kind'."
    paths = pk.get("paths")
    kind = pk.get("kind", "Hash")
    if kind not in ("Hash", "MultiHash"):
        return f"Unsupported partition key kind '{kind}'."
    if not isinstance(paths, list) or not paths or not all(isinstance(x, str) for x in paths):
        return "partitionKey.paths must be a non-empty list of paths."
    for x in paths:
        if not x.startswith("/") or len(x) < 2 or x.endswith("/") or "//" in x:
            return f"Partition key path '{x}' is invalid: a path starts with '/' and names a property (e.g. /tenantId)."
    if len({x.lower() for x in paths}) != len(paths):
        return "Partition key paths must be unique."
    if kind == "Hash" and len(paths) != 1:
        return "A Hash partition key takes exactly one path; use kind 'MultiHash' (version 2) for hierarchical partition keys."
    if kind == "MultiHash":
        if not 2 <= len(paths) <= 3:
            return "A hierarchical (MultiHash) partition key takes two or three paths."
        if pk.get("version", 2) != 2:
            return "Hierarchical partition keys require partition key version 2."
    return None


def _pk_from_doc(doc: dict, paths: list):
    out = []
    for path in paths:
        cur = doc
        for part in path.strip("/").split("/"):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        out.append(cur)
    return out


def _coll_view(db: dict, coll_id: str, entry: dict) -> dict:
    return {
        "id": coll_id,
        "partitionKey": entry.get("partitionKey",
                                  {"paths": ["/id"], "kind": "Hash"}),
        "_rid": entry["_rid"],
        "_self": f"dbs/{db['_rid']}/colls/{entry['_rid']}/",
        "_etag": entry["_etag"],
        "_ts": entry["_ts"],
        "_docs": "docs/",
        "_conflicts": "conflicts/",
        "indexingPolicy": entry.get("indexingPolicy", {
            "indexingMode": "consistent",
            "automatic": True,
            "includedPaths": [{"path": "/*"}],
            "excludedPaths": [],
        }),
    }


# ── SQL query (pragmatic SELECT subset) ─────────────────────────────────────
def _lit(rhs: str) -> Any:
    rhs = rhs.strip()
    if (rhs.startswith("'") and rhs.endswith("'")) or \
       (rhs.startswith('"') and rhs.endswith('"')):
        return rhs[1:-1]
    if rhs.lower() in ("true", "false"):
        return rhs.lower() == "true"
    if rhs.lower() == "null":
        return None
    try:
        return int(rhs)
    except ValueError:
        try:
            return float(rhs)
        except ValueError:
            return rhs


def _match_condition(doc: dict, cond: str) -> bool:
    """A single WHERE condition: a scalar function call, an IN membership
    test, or a comparison. Unrecognised conditions pass through (don't
    filter the document out) — same fallback the original subset used."""
    cond = cond.strip()

    fm = re.match(
        r"^(contains|startswith|endswith)\s*\(\s*(?:c|root)\.([A-Za-z_]\w*)\s*,\s*(.+?)\s*\)$",
        cond, re.IGNORECASE)
    if fm:
        fn, field_name, rhs = fm.group(1).lower(), fm.group(2), fm.group(3)
        actual, val = doc.get(field_name), _lit(rhs)
        if not isinstance(actual, str) or not isinstance(val, str):
            return False
        if fn == "contains":
            return val in actual
        if fn == "startswith":
            return actual.startswith(val)
        return actual.endswith(val)

    inm = re.match(r"^(?:c|root)\.([A-Za-z_]\w*)\s+in\s*\((.*)\)$",
                   cond, re.IGNORECASE | re.DOTALL)
    if inm:
        field_name = inm.group(1)
        members = [_lit(p) for p in inm.group(2).split(",")]
        return doc.get(field_name) in members

    cm = re.match(
        r"""^(?:c|root)\.([A-Za-z_]\w*)\s*
            (=|==|!=|<>|>=|<=|>|<)\s*
            (.+?)\s*$""",
        cond, re.VERBOSE)
    if not cm:
        return True  # unsupported predicate -> don't filter it out
    field_name, op, rhs = cm.group(1), cm.group(2), cm.group(3).strip()
    val: Any = _lit(rhs)
    actual = doc.get(field_name)
    if op in ("=", "=="):
        return actual == val
    if op in ("!=", "<>"):
        return actual != val
    try:
        if op == ">":
            return actual > val
        if op == "<":
            return actual < val
        if op == ">=":
            return actual >= val
        if op == "<=":
            return actual <= val
    except TypeError:
        return False
    return True


def _run_query(docs: list[dict], query: str) -> list[dict]:
    """A pragmatic subset of the Cosmos SQL grammar sufficient for the native
    SDK's common patterns: SELECT */fields/TOP n/VALUE, an optional WHERE
    combining comparisons (=,!=,>,<,>=,<=), IN (...) and CONTAINS/STARTSWITH/
    ENDSWITH(...) with a single logical operator throughout (either all AND
    or all OR — mixed/parenthesized boolean expressions are not parsed),
    ORDER BY one field, OFFSET n LIMIT n, and a top-level COUNT(...) / VALUE
    COUNT(...) aggregate. Unrecognised queries fall back to SELECT * / don't
    filter the predicate out, so the subset degrades gracefully rather than
    silently dropping rows."""
    q = query.strip()

    # TOP n — a row cap baked into the projection clause.
    top_n = None
    mtop = re.match(r"^\s*select\s+top\s+(\d+)\s+(.*)$", q, re.IGNORECASE | re.DOTALL)
    if mtop:
        top_n = int(mtop.group(1))
        q = "SELECT " + mtop.group(2)

    value_mode = bool(re.match(r"^\s*select\s+value\s+", q, re.IGNORECASE))

    # WHERE clause -> filter predicate, terminated by ORDER BY / OFFSET / end.
    where = None
    m = re.search(r"\bwhere\b(.*?)(?:\border\s+by\b|\boffset\b|$)", q, re.IGNORECASE | re.DOTALL)
    if m:
        where = m.group(1).strip()

    def _match(doc: dict) -> bool:
        if not where:
            return True
        # Pragmatic subset: a single logical operator throughout (no mixing,
        # no parentheses) — OR takes precedence over an all-AND reading.
        or_parts = re.split(r"\s+or\s+", where, flags=re.IGNORECASE)
        if len(or_parts) > 1:
            return any(_match_condition(doc, p) for p in or_parts)
        and_parts = re.split(r"\s+and\s+", where, flags=re.IGNORECASE)
        return all(_match_condition(doc, p) for p in and_parts)

    matched = [d for d in docs if _match(d)]

    # ORDER BY c.field [ASC|DESC] — Cosmos allows a single ordering key.
    om = re.search(r"\border\s+by\b\s+(?:c|root)\.([A-Za-z_][\w]*)\s*(asc|desc)?",
                   q, re.IGNORECASE)
    if om:
        order_field, direction = om.group(1), (om.group(2) or "asc").lower()
        # Cosmos orders with undefined/null last; keep it total + type-safe by
        # sorting on a (present?, coerced-key) tuple so mixed/absent values don't raise.
        def _sort_key(d: dict):
            v = d.get(order_field)
            present = order_field in d and v is not None
            # group by type then value to avoid str-vs-int TypeError on mixed docs.
            return (not present, type(v).__name__ if present else "", v if present else "")
        matched = sorted(matched, key=_sort_key, reverse=(direction == "desc"))

    # OFFSET n LIMIT n — a page of the (filtered, ordered) result set.
    offm = re.search(r"\boffset\s+(\d+)\s+limit\s+(\d+)\b", q, re.IGNORECASE)
    if offm:
        offset, limit = int(offm.group(1)), int(offm.group(2))
        matched = matched[offset:offset + limit]
    if top_n is not None:
        matched = matched[:top_n]

    # Aggregate: SELECT [VALUE] COUNT(...) FROM c — no GROUP BY.
    if re.match(r"^\s*select\s+(?:value\s+)?count\s*\([^)]*\)\s+from\b", q, re.IGNORECASE):
        n = len(matched)
        return [n] if value_mode else [{"$1": n}]

    # Projection: SELECT * / SELECT c.a, c.b [AS alias] / SELECT VALUE c.a
    sm = re.match(r"^\s*select\s+(?:value\s+)?(.*?)\s+from\b", q, re.IGNORECASE | re.DOTALL)
    proj = sm.group(1).strip() if sm else "*"
    if proj == "*":
        return matched

    if value_mode:
        vm = re.match(r"^(?:c|root)\.([A-Za-z_]\w*)$", proj, re.IGNORECASE)
        return [d.get(vm.group(1)) for d in matched] if vm else matched

    fields = []
    for part in proj.split(","):
        part = part.strip()
        pm = re.match(r"^(?:c|root)\.([A-Za-z_][\w]*)(?:\s+as\s+([A-Za-z_][\w]*))?$",
                      part, re.IGNORECASE)
        if pm:
            fields.append((pm.group(1), pm.group(2) or pm.group(1)))
    if not fields:
        return matched
    out = []
    for d in matched:
        row = {alias: d.get(src) for src, alias in fields if src in d}
        out.append(row)
    return out


# ── dispatch ──────────────────────────────────────────────────────────────
def _dispatch_inner(store: CosmosStore, method: str, path: str,
                    query: dict | None = None, headers: dict | None = None,
                    body: bytes = b"") -> Response:
    query = query or {}
    headers = {(k or "").lower(): v for k, v in (headers or {}).items()}
    method = method.upper()

    p = path.split("?", 1)[0].rstrip("/")
    segs = [s for s in p.split("/") if s != ""]

    # Database-account discovery: the azure-cosmos SDK issues `GET /` at init to
    # learn the account's regions. Empty location lists make it fall back to the
    # configured endpoint (this single in-WASM endpoint).
    if not segs and method == "GET":
        return _json(200, {
            "id": "localhost", "_self": "", "_rid": "localhost", "_dbs": "//dbs/",
            "writableLocations": [], "readableLocations": [],
            "enableMultipleWriteLocations": False,
            "userConsistencyPolicy": {"defaultConsistencyLevel": "Session"},
        })

    if not segs or segs[0] != "dbs":
        return _err(404, "NotFound", f"Unknown resource path: {path}")

    def _load_body() -> dict:
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return {}

    # ---- /dbs collection ----
    if len(segs) == 1:
        if method == "POST":                        # create database
            b = _load_body()
            db_id = b.get("id")
            if not db_id:
                return _err(400, "BadRequest", "The database id is required.")
            if db_id in store.dbs:
                return _err(409, "Conflict",
                            f"Database with id '{db_id}' already exists.")
            entry = {"_rid": _rid(), "_etag": _etag(), "_ts": _now_ts()}
            store.dbs[db_id] = entry
            store.colls[db_id] = {}
            store.docs[db_id] = {}
            store.persist()
            return _json(201, _db_view(db_id, entry),
                         {"etag": entry["_etag"]})
        if method == "GET":                          # list databases
            items = [_db_view(k, v) for k, v in store.dbs.items()]
            return _json(200, {"_rid": "", "Databases": items,
                               "_count": len(items)})
        return _err(400, "BadRequest", f"Unsupported method {method} on /dbs")

    db_id = segs[1]

    # ---- /dbs/{db} ----
    if len(segs) == 2:
        if db_id not in store.dbs:
            return _err(404, "NotFound", f"Database '{db_id}' not found.")
        if method == "GET":
            return _json(200, _db_view(db_id, store.dbs[db_id]))
        if method == "DELETE":
            store.dbs.pop(db_id, None)
            store.colls.pop(db_id, None)
            store.docs.pop(db_id, None)
            store.persist()
            return Response(status=204, body=b"", media_type=None)
        return _err(400, "BadRequest", f"Unsupported method {method} on database")

    if segs[2] != "colls":
        return _err(404, "NotFound", f"Unknown resource path: {path}")

    if db_id not in store.dbs:
        return _err(404, "NotFound", f"Database '{db_id}' not found.")
    db_entry = store.dbs[db_id]
    colls = store.colls[db_id]

    # ---- /dbs/{db}/colls collection ----
    if len(segs) == 3:
        if method == "POST":                         # create collection
            b = _load_body()
            coll_id = b.get("id")
            if not coll_id:
                return _err(400, "BadRequest", "The collection id is required.")
            if coll_id in colls:
                return _err(409, "Conflict",
                            f"Collection with id '{coll_id}' already exists.")
            pk = b.get("partitionKey", {"paths": ["/id"], "kind": "Hash"})
            pk_err = validate_partition_key(pk)
            if pk_err:
                return _err(400, "BadRequest", pk_err)
            if pk.get("kind") == "MultiHash":
                pk = {**pk, "version": 2}
            entry = {
                "_rid": _rid(), "_etag": _etag(), "_ts": _now_ts(),
                "partitionKey": pk,
            }
            if "indexingPolicy" in b:
                entry["indexingPolicy"] = b["indexingPolicy"]
            colls[coll_id] = entry
            store.docs[db_id][coll_id] = {}
            store.persist()
            return _json(201, _coll_view(db_entry, coll_id, entry),
                         {"etag": entry["_etag"]})
        if method == "GET":                          # list collections
            items = [_coll_view(db_entry, k, v) for k, v in colls.items()]
            return _json(200, {"_rid": db_entry["_rid"],
                               "DocumentCollections": items,
                               "_count": len(items)})
        return _err(400, "BadRequest", f"Unsupported method {method} on colls")

    coll_id = segs[3]

    # ---- /dbs/{db}/colls/{c} ----
    if len(segs) == 4:
        if coll_id not in colls:
            return _err(404, "NotFound", f"Collection '{coll_id}' not found.")
        if method == "GET":
            return _json(200, _coll_view(db_entry, coll_id, colls[coll_id]))
        if method == "DELETE":
            colls.pop(coll_id, None)
            store.docs[db_id].pop(coll_id, None)
            store.persist()
            return Response(status=204, body=b"", media_type=None)
        return _err(400, "BadRequest", f"Unsupported method {method} on collection")

    if segs[4] != "docs":
        return _err(404, "NotFound", f"Unknown resource path: {path}")

    if coll_id not in colls:
        return _err(404, "NotFound", f"Collection '{coll_id}' not found.")
    coll_entry = colls[coll_id]
    docs = store.docs[db_id][coll_id]

    # ---- /dbs/{db}/colls/{c}/docs collection ----
    if len(segs) == 5:
        is_query = str(headers.get("x-ms-documentdb-isquery", "")).lower() == "true"
        if method == "POST" and is_query:            # SQL query
            b = _load_body()
            qtext = b.get("query", "") if isinstance(b, dict) else ""
            results = _run_query(list(docs.values()), qtext)
            return _json(200, {"_rid": coll_entry["_rid"],
                               "Documents": results,
                               "_count": len(results)},
                         {"x-ms-item-count": str(len(results))})
        if method == "POST":                          # create document
            b = _load_body()
            if not isinstance(b, dict):
                return _err(400, "BadRequest", "Document body must be a JSON object.")
            doc_id = b.get("id")
            if not doc_id:
                return _err(400, "BadRequest", "The document must carry an 'id'.")
            is_upsert = str(headers.get("x-ms-documentdb-is-upsert", "")).lower() == "true"
            hdr = headers.get("x-ms-documentdb-partitionkey")
            if hdr:
                try:
                    want = json.loads(hdr)
                except ValueError:
                    return _err(400, "BadRequest", "The x-ms-documentdb-partitionkey header is not valid JSON.")
                have = _pk_from_doc(b, (coll_entry.get("partitionKey") or {"paths": ["/id"]}).get("paths", ["/id"]))
                if isinstance(want, list) and len(want) == len(have) and any(h is not None and h != w for h, w in zip(have, want)):
                    return _err(400, "BadRequest", "PartitionKey extracted from document doesn't match the one specified in the header.")
            if doc_id in docs and not is_upsert:
                return _err(409, "Conflict",
                            f"Document with id '{doc_id}' already exists.")
            doc = dict(b)
            doc["id"] = doc_id
            doc["_rid"] = _rid()
            doc["_self"] = (f"dbs/{db_entry['_rid']}/colls/"
                            f"{coll_entry['_rid']}/docs/{doc['_rid']}/")
            doc["_etag"] = _etag()
            doc["_ts"] = _now_ts()
            doc["_attachments"] = "attachments/"
            docs[doc_id] = doc
            store.persist()
            return _json(200 if (doc_id in docs and is_upsert) else 201, doc,
                         {"etag": doc["_etag"]})
        if method == "GET":                           # list documents
            items = list(docs.values())
            return _json(200, {"_rid": coll_entry["_rid"],
                               "Documents": items,
                               "_count": len(items)},
                         {"x-ms-item-count": str(len(items))})
        return _err(400, "BadRequest", f"Unsupported method {method} on docs")

    # ---- /dbs/{db}/colls/{c}/docs/{id} ----
    doc_id = "/".join(segs[5:])
    if method == "GET":
        if doc_id not in docs:
            return _err(404, "NotFound", f"Document '{doc_id}' not found.")
        return _json(200, docs[doc_id], {"etag": docs[doc_id]["_etag"]})
    if method == "PUT":                               # replace document
        if doc_id not in docs:
            return _err(404, "NotFound", f"Document '{doc_id}' not found.")
        b = _load_body()
        if not isinstance(b, dict):
            return _err(400, "BadRequest", "Document body must be a JSON object.")
        prev = docs[doc_id]
        doc = dict(b)
        doc["id"] = doc_id
        doc["_rid"] = prev["_rid"]
        doc["_self"] = prev["_self"]
        doc["_etag"] = _etag()
        doc["_ts"] = _now_ts()
        doc["_attachments"] = "attachments/"
        docs[doc_id] = doc
        store.persist()
        return _json(200, doc, {"etag": doc["_etag"]})
    if method == "DELETE":
        if doc_id not in docs:
            return _err(404, "NotFound", f"Document '{doc_id}' not found.")
        docs.pop(doc_id, None)
        store.persist()
        return Response(status=204, body=b"", media_type=None)
    return _err(400, "BadRequest", f"Unsupported method {method} on document")


# ── account-level enforcement (RU/s throughput + network rules) ───────────────────────────────────────
# The data-plane wire names no account, so the caller says which account it is talking to with `x-vyomi-account`
# (or a `{name}.documents.azure.com` Host); with neither, the ONLY Cosmos account in the ARM state is used; with
# several accounts and no signal nothing is enforced (the shared keyspace cannot attribute the call).
_TP_TYPES = ("microsoft.documentdb/databaseaccounts/sqldatabases/throughputsettings",
             "microsoft.documentdb/databaseaccounts/sqldatabases/containers/throughputsettings")
_clock = time.time            # tests replace it
_WINDOW: dict = {}            # (account_id, scope) -> [(ts, ru)] consumed in the trailing 1 s


def request_charge(method: str, nbytes: int, status: int = 200, is_query: bool = False) -> float:
    """Modelled RU charge (Microsoft's published cost model, same as observability_core): 1 KB point read = 1 RU,
    1 KB write ~ 5 RU, a query >= 2.5 RU. A MODEL on the measured request size, not a metering engine."""
    kb = max(1.0, nbytes / 1024.0)
    if status >= 400:
        return 1.0
    if method.upper() in ("POST", "PUT", "PATCH", "DELETE") and not is_query:
        return round(5.0 * kb, 2)
    return round(max(2.5, kb) if is_query else kb, 2)


def validate_throughput_settings(props: dict) -> str | None:
    """Error text for a throughputSettings `properties.resource`, else None (manual >= 400 in steps of 100; autoscale max
    >= 1000 in steps of 1000; exactly one of the two)."""
    res = (props or {}).get("resource")
    if not isinstance(res, dict):
        return "properties.resource is required."
    tp, au = res.get("throughput"), res.get("autoscaleSettings")
    if (tp is None) == (au is None):
        return "Specify exactly one of throughput (manual) or autoscaleSettings.maxThroughput (autoscale)."
    if tp is not None and (not isinstance(tp, int) or isinstance(tp, bool) or tp < 400 or tp % 100):
        return "The offer throughput must be at least 400 RU/s and a multiple of 100."
    if au is not None:
        mx = (au or {}).get("maxThroughput")
        if not isinstance(mx, int) or isinstance(mx, bool) or mx < 1000 or mx % 1000:
            return "autoscaleSettings.maxThroughput must be at least 1000 RU/s and a multiple of 1000."
    return None


def _cosmos_accounts(arm_state: dict) -> list:
    out = []
    for key, rec in (arm_state or {}).items():
        if str(rec.get("_type") or rec.get("type") or "").lower() == "microsoft.documentdb/databaseaccounts":
            out.append(rec if rec.get("id") else {**rec, "id": key})
    return out


def resolve_account(arm_state: dict | None, headers: dict) -> dict | None:
    accts = _cosmos_accounts(arm_state or {})
    name = str(headers.get("x-vyomi-account") or "").strip().lower()
    if not name:
        host = str(headers.get("host") or "").split(":")[0].lower()
        if host.endswith(".documents.azure.com"):
            name = host.split(".")[0]
    if name:
        for a in accts:
            if (a.get("name") or a["id"].rsplit("/", 1)[-1]).lower() == name:
                return a
        return None
    return accts[0] if len(accts) == 1 else None


def _limit_for(arm_state: dict, acct_id: str, db: str, coll: str):
    """(scope_key, limit RU/s, mode) — the container's own offer, else the database's shared offer, else None."""
    base = acct_id.lower()
    cands = []
    if coll:
        cands.append((f"{base}/sqldatabases/{db}/containers/{coll}/throughputsettings/default".lower(), f"{db}/{coll}"))
    if db:
        cands.append((f"{base}/sqldatabases/{db}/throughputsettings/default".lower(), db))
    for key, scope in cands:
        rec = (arm_state or {}).get(key)
        res = ((rec or {}).get("properties") or {}).get("resource") or {}
        if res.get("autoscaleSettings"):
            return scope, int(res["autoscaleSettings"].get("maxThroughput") or 0), "autoscale"
        if res.get("throughput"):
            return scope, int(res["throughput"]), "manual"
    return None


def _cosmos_net_denied(arm_state, acct, headers):
    try:
        from core import azure_netaccess as na
    except ImportError:  # pragma: no cover - Pyodide flat layout
        import azure_netaccess as na  # type: ignore
    props = acct.get("properties") or {}
    ctx = na.caller_context(headers)
    ip_rules = [r.get("ipAddressOrRange", "") for r in props.get("ipRules") or [] if isinstance(r, dict)]
    vn_rules = [r.get("id", "") for r in props.get("virtualNetworkRules") or [] if isinstance(r, dict)]
    if ctx and ctx.get("private_endpoint"):
        ok, why = na._pe_reaches(arm_state, ctx["private_endpoint"], acct["id"])
        return None if ok else (403, "Forbidden", f"Request is blocked: the private endpoint cannot reach this account ({why}).")
    if props.get("publicNetworkAccess") == "Disabled":
        return 403, "Forbidden", "Request is blocked because public network access is disabled for this account; use a private endpoint."
    if not ctx or not (props.get("isVirtualNetworkFilterEnabled") or ip_rules or vn_rules):
        return None
    ip, subnet = ctx.get("source_ip"), ctx.get("source_subnet")
    if ip and any(na._ip_in_rule(ip, r) for r in ip_rules):
        return None
    if subnet and any(v.lower() == subnet.lower() for v in vn_rules) and na._subnet_has_endpoint(arm_state, subnet, "Microsoft.AzureCosmosDB"):
        return None
    return 403, "Forbidden", (f"Request originated from client IP {ip or 'unknown'} through public internet. This is blocked by your "
                              "Cosmos DB account firewall settings.")


def dispatch(store: CosmosStore, method: str, path: str, query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", arm_state: dict | None = None) -> Response:
    """Data-plane dispatch. With `arm_state` (the Azure ARM state) the target account's network rules and provisioned /
    autoscale throughput are ENFORCED: a denied caller gets 403, a request that would exceed the offer in the trailing
    second gets 429 (RequestRateTooLarge) with x-ms-retry-after-ms; every response carries x-ms-request-charge (modelled RU)."""
    hdrs = {(k or "").lower(): v for k, v in (headers or {}).items()}
    acct = resolve_account(arm_state, hdrs) if arm_state else None
    segs = [s for s in path.split("?", 1)[0].split("/") if s]
    if acct is not None and segs:
        denied = _cosmos_net_denied(arm_state, acct, hdrs)
        if denied:
            return _err(*denied)
    is_query = str(hdrs.get("x-ms-documentdb-isquery", "")).lower() == "true"
    charge = request_charge(method, len(body or b""), 200, is_query)
    lim = None
    if acct is not None and len(segs) >= 4 and segs[0] == "dbs" and segs[2] == "colls" and (len(segs) >= 5 or method.upper() != "GET"):
        lim = _limit_for(arm_state, acct["id"], segs[1], segs[3])
    if lim is not None:
        scope, limit, mode = lim
        now = _clock()
        win = _WINDOW.setdefault((acct["id"].lower(), scope), [])
        win[:] = [(t, c) for t, c in win if now - t < 1.0]
        used = sum(c for _, c in win)
        if used + charge > limit and used > 0 or charge > limit:
            retry = max(1, int(1000 - (now - win[0][0]) * 1000)) if win else 1000
            r = _err(429, "RequestRateTooLarge",
                     f"Request rate is large. More Request Units may be needed, so no changes were made. Please retry this request later. "
                     f"({mode} offer {limit} RU/s on '{scope}', {round(used, 2)} RU used in the last second, this request costs {charge} RU)")
            r.headers.update({"x-ms-retry-after-ms": str(retry), "x-ms-request-charge": str(charge), "x-ms-substatus": "3200"})
            return r
        win.append((now, charge))
    r = _dispatch_inner(store, method, path, query, headers, body)
    if r.status < 400:
        r.headers.setdefault("x-ms-request-charge", str(charge))
    return r
