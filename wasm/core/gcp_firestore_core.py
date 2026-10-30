# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Firestore document-core — substrate-independent, the GCP-NoSQL analogue of
core/gcp_storage_core.py. Speaks the native **Firestore REST API v1**
(`/v1/projects/{p}/databases/{db}/documents/...`) so the native
`google-cloud-firestore` client with `transport="rest"` works unchanged against
it (point it at the endpoint via `client_options.api_endpoint`), PLUS the
**Firestore Admin v1** control plane the console needs: databases, composite /
single-field indexes, per-field TTL config, backup schedules + backups, and
export/import operations.

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide.
Documents persist through the FirestoreStore seam (below): an in-memory dict
keyed by `{database}/{resource path relative to .../documents/}` (own
namespace, cloud-scoped like the GCS core's ObjectStore), so multiple
databases in the same project never collide.

Scope:
  Data plane  — create document (`POST .../documents/{collection}?documentId=`,
    auto-id when omitted), set/merge (`PATCH .../documents/{collection}/{doc}`),
    get (`GET`), delete (`DELETE`), list (`GET .../documents/{collection}`),
    `:listCollectionIds`, and a `:runQuery` (structuredQuery `from` + where
    clause: fieldFilter / unaryFilter / compositeFilter AND|OR, the full
    comparison + IN/NOT_IN + ARRAY_CONTAINS[_ANY] operator set, orderBy,
    offset, limit).
  Admin plane — `databases` (list/create/get/patch/delete — the default
    database is auto-provisioned on first document-plane use, exactly like
    real Firestore), `collectionGroups/{cid|-}/indexes` (composite indexes),
    `collectionGroups/{cid|-}/fields` (per-field TTL + index-exemption
    config), `backupSchedules` + `locations/{loc}/backups` (a schedule's
    first tick fires immediately — there is no background scheduler in this
    sim), `:exportDocuments` / `:importDocuments` (recorded as completed
    `Operation`s; the console's Import/Export page lists them — Vyomi does
    not actually read/write Cloud Storage objects for the transfer), and a
    pragmatic `:getSecurityRules` / `:updateSecurityRules` pair (real
    Firestore security rules live in the separate Firebase Rules API —
    Vyomi stores and returns the rules source verbatim but never evaluates
    it against a request).

Firestore's typed value encoding is preserved faithfully end-to-end: a document
is `{"name","fields":{field:{stringValue|integerValue|doubleValue|booleanValue|
nullValue|mapValue|arrayValue|timestampValue|bytesValue|...}},"createTime",
"updateTime"}`. The core stores the typed `fields` map verbatim, so every value
type round-trips exactly as the SDK encoded it.
"""
from __future__ import annotations

import json
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
    """In-memory Firestore state for one project: documents (data plane) plus
    databases / indexes / fields / backups / operations / security rules
    (admin plane). Subclass to add a mirror / persistence; the base is pure
    in-memory so it loads under Pyodide with zero external deps."""

    def __init__(self) -> None:
        # Data plane: key = "{database}/{rel}", rel relative to .../documents/
        self.documents: dict[str, dict[str, Any]] = {}
        # Admin plane, each keyed by database id except `backups` (project-wide,
        # like real Firestore: a backup outlives the database it was taken from).
        self.databases: dict[str, dict] = {}
        self.indexes: dict[str, dict[str, dict]] = {}          # db -> {indexId: Index}
        self.fields: dict[str, dict[str, dict]] = {}           # db -> {"{cid}/{fieldPath}": Field}
        self.backup_schedules: dict[str, dict[str, dict]] = {}  # db -> {scheduleId: BackupSchedule}
        self.backups: dict[str, dict] = {}                      # backupId -> Backup
        self.operations: dict[str, dict[str, dict]] = {}       # db -> {opId: Operation}
        self.security_rules: dict[str, str] = {}                # db -> rules source

    # -- documents ------------------------------------------------------------
    def get(self, db: str, rel: str) -> dict | None:
        d = self.documents.get(f"{db}/{rel}")
        return d if isinstance(d, dict) else None

    def put(self, db: str, rel: str, entry: dict) -> None:
        self.documents[f"{db}/{rel}"] = entry

    def delete(self, db: str, rel: str) -> None:
        self.documents.pop(f"{db}/{rel}", None)

    def in_collection(self, db: str, coll: str) -> list[tuple[str, dict]]:
        """Direct children documents of collection path `coll` (its own docs, not
        nested subcollection docs): rel paths that are exactly `coll/{docId}`."""
        prefix = f"{db}/{coll}/"
        depth = coll.count("/") + 2  # coll segments + one doc segment
        out = []
        for key, entry in self.documents.items():
            if not key.startswith(prefix):
                continue
            rel = key[len(db) + 1:]
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


def _load_json(body: bytes) -> dict:
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return {}


def _split_suffix(seg: str) -> tuple[str, str]:
    if ":" in seg:
        s, suf = seg.split(":", 1)
        return s, suf
    return seg, ""


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
def _parse_documents_path(path: str) -> tuple[str, str, str, str, str] | None:
    """Split a Firestore v1 **data-plane** path into
    `(project, database, base, rel, suffix)`.

    base   = `projects/{p}/databases/{db}/documents` (the document-name prefix)
    rel    = resource path under `.../documents/` (URL-decoded; may be "")
    suffix = a trailing colon-method like "runQuery" ("" if none)
    Returns None if `/documents` is not present (an admin-plane path instead).
    """
    p = path.split("?", 1)[0]
    marker = "/documents"
    idx = p.find(marker)
    if idx < 0:
        return None
    prefix = p[:idx]
    for pre in ("/v1beta1/", "/v1/"):
        if prefix.startswith(pre):
            prefix = prefix[len(pre):]
            break
    else:
        prefix = prefix.lstrip("/")
    segs = [s for s in prefix.split("/") if s]
    if len(segs) != 4 or segs[0] != "projects" or segs[2] != "databases":
        return None
    project, database = unquote(segs[1]), unquote(segs[3])
    base = f"projects/{project}/databases/{database}/documents"
    rest = p[idx + len(marker):]
    suffix = ""
    if ":" in rest:
        rest, suffix = rest.rsplit(":", 1)
    rel = unquote(rest.strip("/"))
    return project, database, base, rel, suffix


def _admin_segs(path: str) -> list[str]:
    p = path.split("?", 1)[0]
    for pre in ("/v1beta1/", "/v1/"):
        if p.startswith(pre):
            p = p[len(pre):]
            break
    else:
        p = p.lstrip("/")
    return [s for s in p.strip("/").split("/") if s != ""]


def _ensure_db(store: FirestoreStore, project: str, database: str) -> dict:
    """Auto-provision a database on first use, exactly like real Firestore
    creates `(default)` the first time a client writes to it."""
    if database not in store.databases:
        ts = _now()
        store.databases[database] = {
            "name": f"projects/{project}/databases/{database}",
            "uid": _auto_id(),
            "createTime": ts,
            "updateTime": ts,
            "locationId": "nam5",
            "type": "FIRESTORE_NATIVE",
            "concurrencyMode": "OPTIMISTIC",
            "appEngineIntegrationMode": "DISABLED",
            "keyPrefix": _auto_id()[:12],
            "deleteProtectionState": "DELETE_PROTECTION_DISABLED",
            "pointInTimeRecoveryEnablement": "POINT_IN_TIME_RECOVERY_DISABLED",
            "databaseEdition": "STANDARD",
            "etag": _auto_id(),
        }
    return store.databases[database]


# ── dispatch ───────────────────────────────────────────────────────────────
def dispatch(store: FirestoreStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> FirestoreResponse:
    query = query or {}
    method = method.upper()

    parsed = _parse_documents_path(path)
    if parsed is not None:
        project, database, base, rel, suffix = parsed
        _ensure_db(store, project, database)
        return _dispatch_documents(store, database, base, method, rel, suffix, query, body)
    return _admin_dispatch(store, method, path, query, body)


# ── data plane ─────────────────────────────────────────────────────────────
def _dispatch_documents(store: FirestoreStore, db: str, base: str, method: str,
                        rel: str, suffix: str, query: dict, body: bytes) -> FirestoreResponse:
    if suffix == "runQuery":
        return _run_query(store, db, base, rel, _load_json(body))
    if suffix == "listCollectionIds":
        return _list_collection_ids(store, db, rel)

    segs = [s for s in rel.split("/") if s != ""]
    is_collection = (len(segs) % 2 == 1)   # odd → collection, even → document
    is_document = (len(segs) != 0 and len(segs) % 2 == 0)

    # ---- collection: /{collection}
    if is_collection:
        coll = "/".join(segs)
        if method == "POST":               # create document
            data = _load_json(body)
            doc_id = query.get("documentId") or _auto_id()
            new_rel = f"{coll}/{doc_id}"
            if store.get(db, new_rel) is not None:
                return _err(409, "ALREADY_EXISTS",
                            f"Document already exists: {_doc_name(base, new_rel)}")
            ts = _now()
            entry = {"fields": data.get("fields", {}), "createTime": ts, "updateTime": ts}
            store.put(db, new_rel, entry)
            return _json(200, _doc_view(base, new_rel, entry))
        if method == "GET":                # list documents
            docs = [_doc_view(base, r, e) for r, e in
                    sorted(store.in_collection(db, coll), key=lambda kv: kv[0])]
            out: dict[str, Any] = {}
            if docs:
                out["documents"] = docs
            return _json(200, out)
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on collection")

    # ---- document: /{collection}/{doc}
    if is_document:
        entry = store.get(db, rel)
        if method == "GET":
            if entry is None:
                return _err(404, "NOT_FOUND",
                            f"Document not found: {_doc_name(base, rel)}")
            return _json(200, _doc_view(base, rel, entry))
        if method in ("PATCH", "PUT"):     # set / merge fields
            data = _load_json(body)
            new_fields = data.get("fields", {})
            if entry is None:              # create-on-set
                ts = _now()
                entry = {"fields": dict(new_fields), "createTime": ts, "updateTime": ts}
                store.put(db, rel, entry)
                return _json(200, _doc_view(base, rel, entry))
            merged = dict(entry.get("fields", {}))
            merged.update(new_fields)      # merge: add/overwrite named fields, keep others
            entry["fields"] = merged
            entry["updateTime"] = _now()
            store.put(db, rel, entry)
            return _json(200, _doc_view(base, rel, entry))
        if method == "DELETE":
            store.delete(db, rel)          # Firestore delete is idempotent → 200 {}
            return _json(200, {})
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on document")

    return _err(400, "INVALID_ARGUMENT", f"Unsupported request: {method} {rel!r}")


def _list_collection_ids(store: FirestoreStore, db: str, parent_rel: str) -> FirestoreResponse:
    prefix = f"{db}/{parent_rel}/" if parent_rel else f"{db}/"
    seen: set[str] = set()
    for key in store.documents:
        if not key.startswith(prefix):
            continue
        seen.add(key[len(prefix):].split("/", 1)[0])
    return _json(200, {"collectionIds": sorted(seen)})


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


def _run_query(store: FirestoreStore, db: str, base: str, parent_rel: str,
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
    for rel, entry in store.in_collection(db, coll):
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


# ── admin plane ─────────────────────────────────────────────────────────────
def _admin_dispatch(store: FirestoreStore, method: str, path: str,
                    query: dict, body: bytes) -> FirestoreResponse:
    segs = [unquote(s) for s in _admin_segs(path)]
    if len(segs) < 3 or segs[0] != "projects":
        return _err(404, "NOT_FOUND", f"Unknown path: {path}")
    project = segs[1]
    if segs[2] == "locations":
        return _dispatch_backups(store, project, method, segs[3:])
    if segs[2] != "databases":
        return _err(404, "NOT_FOUND", f"Unknown path: {path}")
    if len(segs) == 3:
        return _dispatch_databases_collection(store, project, method, query, body)
    dbid, suffix = _split_suffix(segs[3])
    if len(segs) == 4:
        return _dispatch_database_item(store, project, dbid, suffix, method, query, body)
    sub = segs[4]
    if sub == "operations":
        return _dispatch_operations(store, dbid, method, segs[5:])
    if sub == "backupSchedules":
        return _dispatch_backup_schedules(store, project, dbid, method, segs[5:], body)
    if sub == "collectionGroups" and len(segs) >= 7:
        cid, group_sub = segs[5], segs[6]
        if group_sub == "indexes":
            return _dispatch_indexes(store, project, dbid, cid, method, segs[7:], body)
        if group_sub == "fields":
            return _dispatch_fields(store, project, dbid, cid, method, segs[7:], query, body)
    return _err(404, "NOT_FOUND", f"Unknown path: {path}")


def _dispatch_databases_collection(store: FirestoreStore, project: str, method: str,
                                   query: dict, body: bytes) -> FirestoreResponse:
    if method == "GET":
        items = sorted(store.databases.values(), key=lambda d: d["name"])
        return _json(200, {"databases": items} if items else {})
    if method == "POST":
        data = _load_json(body)
        dbid = query.get("databaseId") or "(default)"
        if dbid in store.databases:
            return _err(409, "ALREADY_EXISTS", f"Database already exists: {dbid}")
        rec = _ensure_db(store, project, dbid)
        for k in ("locationId", "type", "concurrencyMode", "deleteProtectionState",
                  "pointInTimeRecoveryEnablement", "databaseEdition"):
            if k in data:
                rec[k] = data[k]
        return _json(200, rec)
    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on databases")


def _dispatch_database_item(store: FirestoreStore, project: str, dbid: str, suffix: str,
                            method: str, query: dict, body: bytes) -> FirestoreResponse:
    if suffix in ("exportDocuments", "importDocuments"):
        if dbid not in store.databases:
            return _err(404, "NOT_FOUND", f"Database does not exist: {dbid}")
        return _dispatch_export_import(store, project, dbid, suffix, body)
    if suffix in ("getSecurityRules", "updateSecurityRules"):
        if suffix == "getSecurityRules":
            return _json(200, {"rules": store.security_rules.get(dbid, "")})
        data = _load_json(body)
        store.security_rules[dbid] = data.get("rules", "")
        return _json(200, {"rules": store.security_rules[dbid]})

    db = store.databases.get(dbid)
    if method == "GET":
        if db is None:
            return _err(404, "NOT_FOUND", f"Database does not exist: projects/{project}/databases/{dbid}")
        return _json(200, db)
    if method in ("PATCH", "PUT"):
        if db is None:
            return _err(404, "NOT_FOUND", f"Database does not exist: projects/{project}/databases/{dbid}")
        data = _load_json(body)
        mask = [m.strip() for m in (query.get("updateMask") or "").split(",") if m.strip()]
        keys = mask or list(data.keys())
        for k in keys:
            if k in data:
                db[k] = data[k]
        db["updateTime"] = _now()
        db["etag"] = _auto_id()
        return _json(200, db)
    if method == "DELETE":
        if db is None:
            return _err(404, "NOT_FOUND", f"Database does not exist: projects/{project}/databases/{dbid}")
        store.databases.pop(dbid, None)
        prefix = f"{dbid}/"
        for key in [k for k in store.documents if k.startswith(prefix)]:
            store.documents.pop(key, None)
        store.indexes.pop(dbid, None)
        store.fields.pop(dbid, None)
        store.backup_schedules.pop(dbid, None)
        store.operations.pop(dbid, None)
        store.security_rules.pop(dbid, None)
        return _json(200, db)
    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on database")


def _dispatch_export_import(store: FirestoreStore, project: str, dbid: str, kind: str,
                            body: bytes) -> FirestoreResponse:
    data = _load_json(body)
    ops = store.operations.setdefault(dbid, {})
    opid = _auto_id()
    collection_ids = data.get("collectionIds") or []
    ts = _now()
    if kind == "exportDocuments":
        op_kind, location = "ExportDocuments", data.get("outputUriPrefix", "")
        meta_extra = {"outputUriPrefix": location}
        response = {"@type": "type.googleapis.com/google.firestore.admin.v1.ExportDocumentsResponse",
                    "outputUriPrefix": location}
    else:
        op_kind, location = "ImportDocuments", data.get("inputUriPrefix", "")
        meta_extra = {"inputUriPrefix": location}
        response = {"@type": "type.googleapis.com/google.protobuf.Empty"}
    op = {
        "name": f"projects/{project}/databases/{dbid}/operations/{opid}",
        "metadata": {
            "@type": f"type.googleapis.com/google.firestore.admin.v1.{op_kind}Metadata",
            "startTime": ts, "endTime": ts, "operationState": "SUCCESSFUL",
            "collectionIds": collection_ids, **meta_extra,
        },
        "done": True,
        "response": response,
    }
    ops[opid] = op
    return _json(200, op)


def _dispatch_operations(store: FirestoreStore, dbid: str, method: str,
                         rest: list[str]) -> FirestoreResponse:
    ops = store.operations.get(dbid, {})
    if not rest:
        if method != "GET":
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on operations")
        items = sorted(ops.values(), key=lambda o: o["name"])
        return _json(200, {"operations": items} if items else {})
    opid, _ = _split_suffix(rest[0])
    op = ops.get(opid)
    if op is None:
        return _err(404, "NOT_FOUND", f"Operation not found: {opid}")
    if method == "GET":
        return _json(200, op)
    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on operation")


def _dispatch_backup_schedules(store: FirestoreStore, project: str, dbid: str, method: str,
                               rest: list[str], body: bytes) -> FirestoreResponse:
    if dbid not in store.databases:
        return _err(404, "NOT_FOUND", f"Database does not exist: {dbid}")
    scheds = store.backup_schedules.setdefault(dbid, {})
    if not rest:
        if method == "GET":
            items = sorted(scheds.values(), key=lambda s: s["name"])
            return _json(200, {"backupSchedules": items} if items else {})
        if method == "POST":
            data = _load_json(body)
            sid = _auto_id()[:12]
            ts = _now()
            rec = {
                "name": f"projects/{project}/databases/{dbid}/backupSchedules/{sid}",
                "createTime": ts, "updateTime": ts,
                "retention": data.get("retention", "604800s"),
            }
            if "weeklyRecurrence" in data:
                rec["weeklyRecurrence"] = data["weeklyRecurrence"]
            else:
                rec["dailyRecurrence"] = data.get("dailyRecurrence", {})
            scheds[sid] = rec
            # No background scheduler in this sim: the first tick fires immediately.
            _take_backup(store, project, dbid)
            return _json(200, rec)
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on backupSchedules")
    sid, _ = _split_suffix(rest[0])
    rec = scheds.get(sid)
    if rec is None:
        return _err(404, "NOT_FOUND", f"Backup schedule not found: {sid}")
    if method == "GET":
        return _json(200, rec)
    if method in ("PATCH", "PUT"):
        data = _load_json(body)
        for k in ("retention", "dailyRecurrence", "weeklyRecurrence"):
            if k in data:
                rec[k] = data[k]
        rec["updateTime"] = _now()
        return _json(200, rec)
    if method == "DELETE":
        scheds.pop(sid, None)
        return _json(200, {})
    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on backup schedule")


def _take_backup(store: FirestoreStore, project: str, dbid: str) -> dict:
    bid = _auto_id()[:12]
    ts = _now()
    db = store.databases.get(dbid, {})
    rec = {
        "name": f"projects/{project}/locations/{db.get('locationId', 'nam5')}/backups/{bid}",
        "database": f"projects/{project}/databases/{dbid}",
        "databaseUid": db.get("uid", ""),
        "snapshotTime": ts,
        "expireTime": ts,
        "state": "READY",
    }
    store.backups[bid] = rec
    return rec


def _dispatch_backups(store: FirestoreStore, project: str, method: str,
                      rest: list[str]) -> FirestoreResponse:
    if len(rest) < 2 or rest[1] != "backups":
        return _err(404, "NOT_FOUND", "Unknown path")
    items = [b for b in store.backups.values() if b["database"].startswith(f"projects/{project}/")]
    if len(rest) == 2:
        if method != "GET":
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on backups")
        return _json(200, {"backups": sorted(items, key=lambda b: b["name"])} if items else {})
    bid, _ = _split_suffix(rest[2])
    rec = store.backups.get(bid)
    if rec is None or rec["database"].split("/")[1] != project:
        return _err(404, "NOT_FOUND", f"Backup not found: {bid}")
    if method == "GET":
        return _json(200, rec)
    if method == "DELETE":
        store.backups.pop(bid, None)
        return _json(200, {})
    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on backup")


def _dispatch_indexes(store: FirestoreStore, project: str, dbid: str, cid: str, method: str,
                      rest: list[str], body: bytes) -> FirestoreResponse:
    if dbid not in store.databases:
        return _err(404, "NOT_FOUND", f"Database does not exist: {dbid}")
    idxs = store.indexes.setdefault(dbid, {})
    if not rest:
        if method == "GET":
            items = sorted((i for i in idxs.values() if cid == "-" or i["collectionGroup"] == cid),
                           key=lambda i: i["name"])
            return _json(200, {"indexes": items} if items else {})
        if method == "POST":
            if cid == "-":
                return _err(400, "INVALID_ARGUMENT", "A specific collection group is required to create an index")
            data = _load_json(body)
            iid = _auto_id()[:16]
            rec = {
                "name": f"projects/{project}/databases/{dbid}/collectionGroups/{cid}/indexes/{iid}",
                "collectionGroup": cid,
                "queryScope": data.get("queryScope", "COLLECTION"),
                "fields": data.get("fields", []),
                "state": "READY",
            }
            idxs[iid] = rec
            return _json(200, rec)
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on indexes")
    iid, _ = _split_suffix(rest[0])
    rec = idxs.get(iid)
    if rec is None:
        return _err(404, "NOT_FOUND", f"Index not found: {iid}")
    if method == "GET":
        return _json(200, rec)
    if method == "DELETE":
        idxs.pop(iid, None)
        return _json(200, {})
    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on index")


def _dispatch_fields(store: FirestoreStore, project: str, dbid: str, cid: str, method: str,
                     rest: list[str], query: dict, body: bytes) -> FirestoreResponse:
    if dbid not in store.databases:
        return _err(404, "NOT_FOUND", f"Database does not exist: {dbid}")
    flds = store.fields.setdefault(dbid, {})
    if not rest:
        if method != "GET":
            return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on fields")
        wants_ttl = "ttlConfig" in (query.get("filter") or "")
        items = []
        for key, rec in flds.items():
            group, _fp = key.split("/", 1)
            if cid != "-" and group != cid:
                continue
            if wants_ttl and "ttlConfig" not in rec:
                continue
            items.append(rec)
        items.sort(key=lambda r: r["name"])
        return _json(200, {"fields": items} if items else {})
    field_path, _ = _split_suffix(unquote(rest[0]))
    key = f"{cid}/{field_path}"
    rec = flds.get(key) or {
        "name": f"projects/{project}/databases/{dbid}/collectionGroups/{cid}/fields/{field_path}",
        "indexConfig": {"indexes": [], "usesAncestorConfig": True},
    }
    if method == "GET":
        return _json(200, rec)
    if method in ("PATCH", "PUT"):
        data = _load_json(body)
        rec = dict(rec)
        if "ttlConfig" in data:
            if data["ttlConfig"] is None:
                rec.pop("ttlConfig", None)
            else:
                rec["ttlConfig"] = {"state": "ACTIVE"}
        if "indexConfig" in data:
            rec["indexConfig"] = data["indexConfig"]
        flds[key] = rec
        return _json(200, rec)
    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on field")
