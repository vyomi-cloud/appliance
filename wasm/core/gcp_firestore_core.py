# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Firestore document-core — substrate-independent, the GCP-NoSQL analogue of
core/gcp_storage_core.py. Speaks the native **Firestore REST API v1**
(`/v1/projects/{p}/databases/(default)/documents/...`) so the native
`google-cloud-firestore` client with `transport="rest"` works unchanged against
it (point it at the endpoint via `client_options.api_endpoint`).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide.
Documents persist through the FirestoreStore seam (below): an in-memory dict
keyed by the document's resource path relative to `.../documents/` (own
namespace, cloud-scoped like the GCS core's ObjectStore).

Scope (v1 slice): create document (`POST .../documents/{collection}?documentId=`,
auto-id when omitted), set/merge (`PATCH .../documents/{collection}/{doc}`), get
(`GET`), delete (`DELETE`), list (`GET .../documents/{collection}`), and a basic
`:runQuery` (structuredQuery `from` + optional single `fieldFilter` EQUAL).

Firestore's typed value encoding is preserved faithfully end-to-end: a document
is `{"name","fields":{field:{stringValue|integerValue|doubleValue|booleanValue|
nullValue|mapValue|arrayValue|timestampValue|bytesValue|...}},"createTime",
"updateTime"}`. The core stores the typed `fields` map verbatim, so every value
type round-trips exactly as the SDK encoded it.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote


@dataclass
class FirestoreResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


# ── store seam ─────────────────────────────────────────────────────────────
class FirestoreStore:
    """In-memory document store. Keyed by the resource path relative to
    `.../documents/` — e.g. `"users/alice"` or `"users/alice/orders/o1"` for a
    subcollection. Each entry is `{"fields": {...}, "createTime", "updateTime"}`.
    Subclass to add a mirror / persistence; the base is pure in-memory so it
    loads under Pyodide with zero external deps."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        # projects.databases (Firestore Admin API): db id -> database record. Documents of
        # the (default) database are keyed by their bare path; a named database's by
        # "~{db}~/{path}" (see _DbDocs), so the original single-database layout still reads.
        self.databases: dict[str, dict[str, Any]] = {}
        # composite indexes: "{db}/{collectionGroup}/{indexId}" -> index record
        self.indexes: dict[str, dict[str, Any]] = {}

    def get(self, rel: str) -> dict | None:
        d = self.documents.get(rel)
        return d if isinstance(d, dict) else None

    def put(self, rel: str, entry: dict) -> None:
        self.documents[rel] = entry

    def delete(self, rel: str) -> None:
        self.documents.pop(rel, None)

    def in_collection(self, coll: str) -> list[tuple[str, dict]]:
        """Direct children documents of collection path `coll` (its own docs, not
        nested subcollection docs): rel paths that are exactly `coll/{docId}`."""
        depth = coll.count("/") + 2  # coll segments + one doc segment
        out = []
        for rel, entry in self.documents.items():
            if rel == coll or not rel.startswith(coll + "/"):
                continue
            if rel.count("/") + 1 == depth:
                out.append((rel, entry))
        return out


# ── primitives ─────────────────────────────────────────────────────────────
def _now() -> str:
    # RFC3339 / Timestamp with microsecond precision + Z, as Firestore returns.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _auto_id() -> str:
    # Firestore auto-ids are 20 alphanumeric chars; uuid hex is a faithful stand-in.
    return uuid.uuid4().hex[:20]


def _err(status: int, gstatus: str, message: str) -> FirestoreResponse:
    body = {"error": {"code": status, "message": message, "status": gstatus}}
    return FirestoreResponse(status=status, body=json.dumps(body).encode())


def _json(status: int, obj: dict | list) -> FirestoreResponse:
    return FirestoreResponse(status=status, body=json.dumps(obj).encode())


# ── document views ─────────────────────────────────────────────────────────
def _doc_name(base: str, rel: str) -> str:
    return f"{base}/{rel}"


def _doc_view(base: str, rel: str, entry: dict) -> dict:
    return {
        "name": _doc_name(base, rel),
        "fields": entry.get("fields", {}),
        "createTime": entry.get("createTime", _now()),
        "updateTime": entry.get("updateTime", _now()),
    }


# ── typed-value helpers (for :runQuery filtering) ──────────────────────────
def _scalar(v: dict) -> Any:
    """Collapse a single typed value to a comparable Python scalar (best-effort;
    used only by the EQUAL fieldFilter path)."""
    if not isinstance(v, dict) or not v:
        return None
    (kind, val), = v.items()
    if kind == "integerValue":
        try:
            return int(val)
        except (TypeError, ValueError):
            return val
    if kind == "doubleValue":
        try:
            return float(val)
        except (TypeError, ValueError):
            return val
    if kind == "nullValue":
        return None
    return val  # stringValue / booleanValue / etc. compare as-is


# ── request parsing ────────────────────────────────────────────────────────
def _parse_documents_path(path: str) -> tuple[str, str, str] | None:
    """Split a Firestore v1 path into (base, rel, method_suffix).

    base   = `projects/{p}/databases/{db}/documents` (the document-name prefix)
    rel    = resource path under `.../documents/` (URL-decoded; may be "")
    suffix = a trailing colon-method like "runQuery" ("" if none)
    Returns None if `/documents` is not present.
    """
    p = path.split("?", 1)[0]
    marker = "/documents"
    idx = p.find(marker)
    if idx < 0:
        return None
    base = p[:idx] + marker               # ".../databases/(default)/documents"
    for pre in ("/v1beta1/", "/v1/", "/"):
        if base.startswith(pre):
            base = base[len(pre):]        # doc names omit the /v1 API version
            break
    rest = p[idx + len(marker):]          # "", ":runQuery", "/coll", "/coll/doc:runQuery"
    suffix = ""
    if ":" in rest:
        rest, suffix = rest.rsplit(":", 1)
    rest = rest.strip("/")
    rel = unquote(rest)
    return base, rel, suffix


class _DbDocs:
    """The document store of ONE database: (default) reads/writes bare paths, a named
    database the same paths under its "~{db}~/" prefix."""

    def __init__(self, store: FirestoreStore, db: str) -> None:
        self.store = store
        self.pre = "" if db in ("(default)", "") else "~%s~/" % db

    def get(self, rel):
        return self.store.get(self.pre + rel)

    def put(self, rel, entry):
        self.store.put(self.pre + rel, entry)

    def delete(self, rel):
        self.store.delete(self.pre + rel)

    def in_collection(self, coll):
        return [(r[len(self.pre):], e) for r, e in self.store.in_collection(self.pre + coll)]

    def all(self):
        """Every (rel, entry) of this database."""
        if self.pre:
            return [(r[len(self.pre):], e) for r, e in self.store.documents.items() if r.startswith(self.pre)]
        return [(r, e) for r, e in self.store.documents.items() if not r.startswith("~")]


def _db_of(base: str) -> str:
    parts = base.split("/")
    return parts[parts.index("databases") + 1] if "databases" in parts else "(default)"


# ── projects.databases + composite indexes (Firestore Admin API) ───────────
_DB_ID = re.compile(r"^(\(default\)|[a-z][a-z0-9-]{2,61}[a-z0-9])$")


def database_view(project: str, db_id: str, rec: dict) -> dict:
    return {"name": f"projects/{project}/databases/{db_id}", "uid": rec.get("uid", ""),
            "createTime": rec.get("createTime", ""), "updateTime": rec.get("updateTime", rec.get("createTime", "")),
            "locationId": rec.get("locationId", "us-central1"), "type": rec.get("type", "FIRESTORE_NATIVE"),
            "concurrencyMode": rec.get("concurrencyMode", "OPTIMISTIC"),
            "appEngineIntegrationMode": rec.get("appEngineIntegrationMode", "DISABLED"),
            "pointInTimeRecoveryEnablement": rec.get("pointInTimeRecoveryEnablement", "POINT_IN_TIME_RECOVERY_DISABLED"),
            "deleteProtectionState": rec.get("deleteProtectionState", "DELETE_PROTECTION_DISABLED"),
            "etag": rec.get("etag", "")}


def validate_index(collection_group: str, body: dict) -> dict:
    fields = [f for f in (body.get("fields") or []) if isinstance(f, dict) and f.get("fieldPath") != "__name__"]
    if len(fields) < 2:
        raise ValueError("this index is not necessary, configure using single field index controls")
    out = []
    for f in fields:
        fp = str(f.get("fieldPath") or "").strip()
        if not fp:
            raise ValueError("Every index field needs a fieldPath.")
        if f.get("arrayConfig"):
            if f["arrayConfig"] != "CONTAINS":
                raise ValueError("arrayConfig must be CONTAINS.")
            out.append({"fieldPath": fp, "arrayConfig": "CONTAINS"})
        else:
            order = str(f.get("order") or "ASCENDING").upper()
            if order not in ("ASCENDING", "DESCENDING"):
                raise ValueError("order must be ASCENDING or DESCENDING.")
            out.append({"fieldPath": fp, "order": order})
    scope = str(body.get("queryScope") or "COLLECTION")
    if scope not in ("COLLECTION", "COLLECTION_GROUP"):
        raise ValueError("queryScope must be COLLECTION or COLLECTION_GROUP.")
    return {"queryScope": scope, "fields": out + [{"fieldPath": "__name__", "order": out[-1].get("order", "ASCENDING")}],
            "state": "READY", "apiScope": "ANY_API", "collectionGroup": collection_group}


def _admin(store: FirestoreStore, method: str, path: str, query: dict, body: bytes) -> FirestoreResponse | None:
    p = path.split("?", 1)[0]
    for pre in ("/v1beta1/", "/v1/", "/"):
        if p.startswith(pre):
            p = p[len(pre):]
            break
    segs = [unquote(s) for s in p.strip("/").split("/") if s]
    if len(segs) < 3 or segs[0] != "projects" or segs[2] != "databases":
        return None
    project = segs[1]
    try:
        data = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        data = {}
    dbs = store.databases
    if len(segs) == 3:
        if method == "GET":
            return _json(200, {"databases": [database_view(project, k, v) for k, v in sorted(dbs.items())]})
        if method == "POST":
            db_id = str(query.get("databaseId") or data.get("databaseId") or "").strip()
            if not _DB_ID.match(db_id):
                return _err(400, "INVALID_ARGUMENT", "Database ID '%s' is invalid: 4-63 characters, lowercase letters, digits and hyphens, starting with a letter (or '(default)')." % db_id)
            if db_id in dbs:
                return _err(409, "ALREADY_EXISTS", f"Database already exists. Please use another database_id")
            now = _now()
            dbs[db_id] = {"uid": uuid.uuid4().hex, "createTime": now, "updateTime": now, "etag": uuid.uuid4().hex[:16],
                          **{k: data[k] for k in ("locationId", "type", "concurrencyMode", "appEngineIntegrationMode",
                                                  "pointInTimeRecoveryEnablement", "deleteProtectionState") if data.get(k)}}
            _persist(store)
            return _json(200, {"name": f"projects/{project}/databases/{db_id}/operations/{uuid.uuid4().hex}", "done": True,
                               "response": database_view(project, db_id, dbs[db_id])})
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on databases")
    db = segs[3]
    if len(segs) == 4:
        if db not in dbs:
            return _err(404, "NOT_FOUND", f"The database {db} does not exist for project {project}")
        if method == "GET":
            return _json(200, database_view(project, db, dbs[db]))
        if method == "DELETE":
            if dbs[db].get("deleteProtectionState") == "DELETE_PROTECTION_ENABLED":
                return _err(400, "FAILED_PRECONDITION", "Delete protection is enabled for this database.")
            dbs.pop(db)
            view = _DbDocs(store, db)
            for rel, _ in view.all():
                view.delete(rel)
            for k in [k for k in store.indexes if k.startswith(db + "/")]:
                store.indexes.pop(k)
            _persist(store)
            return _json(200, {"done": True, "response": {"name": f"projects/{project}/databases/{db}"}})
        if method == "PATCH":
            for k in ("deleteProtectionState", "pointInTimeRecoveryEnablement", "concurrencyMode"):
                if k in data:
                    dbs[db][k] = data[k]
            dbs[db]["updateTime"] = _now()
            _persist(store)
            return _json(200, {"done": True, "response": database_view(project, db, dbs[db])})
    # .../collectionGroups/{cg}/indexes[/{id}]
    if len(segs) >= 7 and segs[4] == "collectionGroups" and segs[6] == "indexes":
        cg = segs[5]
        prefix = f"{db}/"
        if len(segs) == 7 and method == "GET":
            items = [dict(v, name=f"projects/{project}/databases/{db}/collectionGroups/{v['collectionGroup']}/indexes/{k.rsplit('/', 1)[-1]}")
                     for k, v in sorted(store.indexes.items()) if k.startswith(prefix) and (cg == "-" or v["collectionGroup"] == cg)]
            return _json(200, {"indexes": items} if items else {})
        if len(segs) == 7 and method == "POST":
            try:
                rec = validate_index(cg, data)
            except ValueError as e:
                return _err(400, "INVALID_ARGUMENT", str(e))
            for k, v in store.indexes.items():
                if k.startswith(prefix) and v["collectionGroup"] == cg and v["fields"] == rec["fields"] and v["queryScope"] == rec["queryScope"]:
                    return _err(409, "ALREADY_EXISTS", "Index already exists")
            iid = "CICAg" + uuid.uuid4().hex[:10]
            store.indexes[f"{db}/{cg}/{iid}"] = rec
            _persist(store)
            return _json(200, {"done": True, "response": dict(rec, name=f"projects/{project}/databases/{db}/collectionGroups/{cg}/indexes/{iid}")})
        if len(segs) == 8 and method == "DELETE":
            if store.indexes.pop(f"{db}/{cg}/{segs[7]}", None) is None:
                return _err(404, "NOT_FOUND", "Index not found")
            _persist(store)
            return _json(200, {})
    return None


def _persist(store) -> None:
    fn = getattr(store, "persist", None)
    if callable(fn):
        fn()


# ── dispatch ───────────────────────────────────────────────────────────────
def dispatch(store: FirestoreStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> FirestoreResponse:
    query = query or {}
    method = method.upper()

    parsed = _parse_documents_path(path)
    if parsed is None:
        admin = _admin(store, method, path, query, body)
        return admin if admin is not None else _err(404, "NOT_FOUND", f"Unknown path: {path}")
    base, rel, suffix = parsed
    store = _DbDocs(store, _db_of(base))   # this database's documents

    def _load_body() -> dict:
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return {}

    # ---- :runQuery (POST .../documents:runQuery or .../documents/{parent}:runQuery)
    if suffix == "runQuery":
        return _run_query(store, base, rel, _load_body())

    segs = [s for s in rel.split("/") if s != ""]
    is_collection = (len(segs) % 2 == 1)   # odd → collection, even → document
    is_document = (len(segs) != 0 and len(segs) % 2 == 0)

    # ---- collection: /{collection}
    if is_collection:
        coll = "/".join(segs)
        if method == "POST":               # create document
            data = _load_body()
            doc_id = query.get("documentId") or _auto_id()
            new_rel = f"{coll}/{doc_id}"
            if store.get(new_rel) is not None:
                return _err(409, "ALREADY_EXISTS",
                            f"Document already exists: {_doc_name(base, new_rel)}")
            ts = _now()
            entry = {"fields": data.get("fields", {}), "createTime": ts, "updateTime": ts}
            store.put(new_rel, entry)
            return _json(200, _doc_view(base, new_rel, entry))
        if method == "GET":                # list documents
            docs = [_doc_view(base, r, e) for r, e in
                    sorted(store.in_collection(coll), key=lambda kv: kv[0])]
            out: dict[str, Any] = {}
            if docs:
                out["documents"] = docs
            return _json(200, out)
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on collection")

    # ---- document: /{collection}/{doc}
    if is_document:
        entry = store.get(rel)
        if method == "GET":
            if entry is None:
                return _err(404, "NOT_FOUND",
                            f"Document not found: {_doc_name(base, rel)}")
            return _json(200, _doc_view(base, rel, entry))
        if method in ("PATCH", "PUT"):     # set / merge fields
            data = _load_body()
            new_fields = data.get("fields", {})
            if entry is None:              # create-on-set
                ts = _now()
                entry = {"fields": dict(new_fields), "createTime": ts, "updateTime": ts}
                store.put(rel, entry)
                return _json(200, _doc_view(base, rel, entry))
            merged = dict(entry.get("fields", {}))
            merged.update(new_fields)      # merge: add/overwrite named fields, keep others
            entry["fields"] = merged
            entry["updateTime"] = _now()
            store.put(rel, entry)
            return _json(200, _doc_view(base, rel, entry))
        if method == "DELETE":
            store.delete(rel)              # Firestore delete is idempotent → 200 {}
            return _json(200, {})
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on document")

    return _err(400, "INVALID_ARGUMENT", f"Unsupported request: {method} {path}")


def _scalar_list(v: dict) -> list:
    """Collapse an arrayValue typed value to a list of Python scalars."""
    vals = ((v or {}).get("arrayValue") or {}).get("values") or []
    return [_scalar(x) for x in vals]


def _eval_field_filter(fields: dict, ff: dict) -> bool:
    """One structuredQuery fieldFilter against a document's typed `fields` map.
    Supports the full comparison + membership + array operator set."""
    field_path = (ff.get("field") or {}).get("fieldPath")
    op = ff.get("op")
    stored = fields.get(field_path, {})
    actual = _scalar(stored)
    if op in ("EQUAL", "NOT_EQUAL"):
        target = _scalar(ff.get("value") or {})
        return (actual == target) if op == "EQUAL" else (actual != target)
    if op in ("LESS_THAN", "LESS_THAN_OR_EQUAL", "GREATER_THAN", "GREATER_THAN_OR_EQUAL"):
        target = _scalar(ff.get("value") or {})
        try:
            if op == "LESS_THAN":
                return actual < target
            if op == "LESS_THAN_OR_EQUAL":
                return actual <= target
            if op == "GREATER_THAN":
                return actual > target
            return actual >= target
        except TypeError:
            return False
    if op in ("IN", "NOT_IN"):
        members = _scalar_list(ff.get("value") or {})
        return (actual in members) if op == "IN" else (actual not in members)
    if op == "ARRAY_CONTAINS":
        target = _scalar(ff.get("value") or {})
        return target in _scalar_list(stored)
    if op == "ARRAY_CONTAINS_ANY":
        members = _scalar_list(ff.get("value") or {})
        return any(m in _scalar_list(stored) for m in members)
    return True   # unsupported operator → don't filter out


def _eval_filter(fields: dict, filt: dict) -> bool:
    """Evaluate a where clause: a single fieldFilter, a unaryFilter (IS_NULL /
    IS_NAN and their negations), or a compositeFilter (AND / OR of sub-filters)."""
    if not filt:
        return True
    if "fieldFilter" in filt:
        return _eval_field_filter(fields, filt["fieldFilter"])
    if "unaryFilter" in filt:
        uf = filt["unaryFilter"]
        fp = (uf.get("field") or {}).get("fieldPath")
        present = fp in fields
        val = _scalar(fields.get(fp, {})) if present else None
        oper = uf.get("op")
        if oper == "IS_NULL":
            return present and val is None
        if oper == "IS_NOT_NULL":
            return present and val is not None
        return True
    if "compositeFilter" in filt:
        cf = filt["compositeFilter"]
        subs = cf.get("filters") or []
        if str(cf.get("op", "AND")).upper() == "OR":
            return any(_eval_filter(fields, f) for f in subs)
        return all(_eval_filter(fields, f) for f in subs)
    return True


def _run_query(store: FirestoreStore, base: str, parent_rel: str,
               request: dict) -> FirestoreResponse:
    """structuredQuery: `from[0].collectionId` (relative to the query parent) with
    a where clause (fieldFilter / unaryFilter / compositeFilter AND|OR, full
    comparison + IN/NOT_IN + ARRAY_CONTAINS[_ANY] operators), plus orderBy,
    offset and limit. Returns the Firestore streaming shape — a JSON array of
    `{"document","readTime"}` rows."""
    sq = request.get("structuredQuery", {}) or {}
    froms = sq.get("from", []) or []
    if not froms:
        return _json(200, [])
    coll_id = froms[0].get("collectionId", "")
    coll = f"{parent_rel}/{coll_id}" if parent_rel else coll_id
    where = sq.get("where") or {}

    matched = []
    for rel, entry in store.in_collection(coll):
        if _eval_filter(entry.get("fields", {}), where):
            matched.append((rel, entry))

    # orderBy (may be multiple keys); default to document-name order.
    order_by = sq.get("orderBy") or []
    if order_by:
        for ob in reversed(order_by):
            fp = (ob.get("field") or {}).get("fieldPath")
            desc = str(ob.get("direction", "ASCENDING")).upper() == "DESCENDING"

            def _key(kv, fp=fp):
                v = _scalar(kv[1].get("fields", {}).get(fp, {}))
                return (v is None, type(v).__name__ if v is not None else "", v if v is not None else "")
            matched.sort(key=_key, reverse=desc)
    else:
        matched.sort(key=lambda kv: kv[0])

    offset = int(sq.get("offset", 0) or 0)
    if offset:
        matched = matched[offset:]
    limit = sq.get("limit")
    if limit is not None:
        matched = matched[:int(limit)]

    read_time = _now()
    rows = [{"document": _doc_view(base, rel, entry), "readTime": read_time}
            for rel, entry in matched]
    if not rows:
        return _json(200, [{"readTime": read_time}])
    return _json(200, rows)
