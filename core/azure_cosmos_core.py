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


# ── SQL query (minimal SELECT support) ─────────────────────────────────────
def _run_query(docs: list[dict], query: str) -> list[dict]:
    """A pragmatic subset of the Cosmos SQL grammar sufficient for the native
    SDK's common patterns: SELECT * / SELECT c.a, c.b, with an optional
    WHERE c.field = value (=, !=, >, <, >=, <=). Unrecognised queries fall
    back to returning all documents (SELECT * semantics)."""
    q = query.strip()
    ql = q.lower()

    # WHERE clause -> filter predicate.
    where = None
    m = re.search(r"\bwhere\b(.*?)(?:\border\s+by\b|$)", q, re.IGNORECASE | re.DOTALL)
    if m:
        where = m.group(1).strip()

    def _match(doc: dict) -> bool:
        if not where:
            return True
        cm = re.match(
            r"""^\s*(?:c|root)\.([A-Za-z_][\w]*)\s*
                (=|==|!=|<>|>=|<=|>|<)\s*
                (.+?)\s*$""",
            where, re.VERBOSE)
        if not cm:
            return True  # unsupported predicate -> don't filter it out
        field_name, op, rhs = cm.group(1), cm.group(2), cm.group(3).strip()
        # parse rhs literal
        val: Any
        if (rhs.startswith("'") and rhs.endswith("'")) or \
           (rhs.startswith('"') and rhs.endswith('"')):
            val = rhs[1:-1]
        elif rhs.lower() in ("true", "false"):
            val = rhs.lower() == "true"
        elif rhs.lower() == "null":
            val = None
        else:
            try:
                val = int(rhs)
            except ValueError:
                try:
                    val = float(rhs)
                except ValueError:
                    val = rhs
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

    matched = [d for d in docs if _match(d)]

    # Projection: SELECT * vs SELECT c.a, c.b
    sm = re.match(r"^\s*select\s+(.*?)\s+from\b", ql, re.DOTALL)
    proj = sm.group(1).strip() if sm else "*"
    if proj == "*":
        return matched

    # projected fields
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
def dispatch(store: CosmosStore, method: str, path: str,
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
            entry = {
                "_rid": _rid(), "_etag": _etag(), "_ts": _now_ts(),
                "partitionKey": b.get("partitionKey",
                                      {"paths": ["/id"], "kind": "Hash"}),
            }
            if "indexingPolicy" in b:
                entry["indexingPolicy"] = b["indexingPolicy"]
            colls[coll_id] = entry
            store.docs[db_id][coll_id] = {}
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
        return _json(200, doc, {"etag": doc["_etag"]})
    if method == "DELETE":
        if doc_id not in docs:
            return _err(404, "NotFound", f"Document '{doc_id}' not found.")
        docs.pop(doc_id, None)
        return Response(status=204, body=b"", media_type=None)
    return _err(400, "BadRequest", f"Unsupported method {method} on document")
