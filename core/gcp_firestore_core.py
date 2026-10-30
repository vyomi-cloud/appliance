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
        self.backup_snapshots: dict[str, dict] = {}             # backupId -> internal restore payload (not API-visible)
        self.operations: dict[str, dict[str, dict]] = {}       # db -> {opId: Operation}
        self.security_rules: dict[str, str] = {}                # db -> rules source
        # Point-in-time recovery: per-document version history, recorded only while
        # the owning database has pointInTimeRecoveryEnablement ON (real Firestore's
        # PITR window). key = "{database}/{rel}" -> [(timestamp, entry|None), ...] oldest-first.
        self.history: dict[str, list[tuple[str, dict | None]]] = {}
        # Usage metering: running totals only (no time-series) — db -> {"reads","writes","deletes"}.
        self.usage: dict[str, dict[str, int]] = {}

    # -- documents ------------------------------------------------------------
    def get(self, db: str, rel: str) -> dict | None:
        d = self.documents.get(f"{db}/{rel}")
        return d if isinstance(d, dict) else None

    def put(self, db: str, rel: str, entry: dict) -> None:
        self.documents[f"{db}/{rel}"] = entry
        self._record_history(db, rel, entry)

    def delete(self, db: str, rel: str) -> None:
        self.documents.pop(f"{db}/{rel}", None)
        self._record_history(db, rel, None)

    def _record_history(self, db: str, rel: str, entry: dict | None) -> None:
        if (self.databases.get(db) or {}).get("pointInTimeRecoveryEnablement") != "POINT_IN_TIME_RECOVERY_ENABLED":
            return
        snap = json.loads(json.dumps(entry)) if entry is not None else None
        ts = entry.get("updateTime") if entry else _now()
        self.history.setdefault(f"{db}/{rel}", []).append((ts, snap))

    def bump_usage(self, db: str, kind: str, n: int = 1) -> None:
        u = self.usage.setdefault(db, {"reads": 0, "writes": 0, "deletes": 0})
        u[kind] = u.get(kind, 0) + n

    def persist(self) -> None:
        """Durable subclasses save here; called after every mutating request."""

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


# ── TTL enforcement (lazy sweep) ────────────────────────────────────────────
def _ttl_fields_by_group(store: FirestoreStore, db: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for key, rec in store.fields.get(db, {}).items():
        if "ttlConfig" not in rec:
            continue
        group, fp = key.split("/", 1)
        out.setdefault(group, set()).add(fp)
    return out


def _sweep_ttl(store: FirestoreStore, db: str) -> None:
    """Delete documents past an ACTIVE ttlConfig timestamp, checked lazily on every
    access to this database (real Firestore's own TTL sweep is also best-effort, not
    immediate — the functional difference is only in timing, not outcome)."""
    ttl_fields = _ttl_fields_by_group(store, db)
    if not ttl_fields:
        return
    now = datetime.now(timezone.utc)
    prefix = f"{db}/"
    doomed = []
    for key, entry in store.documents.items():
        if not key.startswith(prefix):
            continue
        rel = key[len(prefix):]
        segs = rel.split("/")
        if len(segs) < 2:
            continue
        fps = ttl_fields.get(segs[-2])
        if not fps:
            continue
        fields = entry.get("fields", {})
        for fp in fps:
            v = fields.get(fp)
            if not (isinstance(v, dict) and "timestampValue" in v):
                continue
            try:
                ts = datetime.fromisoformat(str(v["timestampValue"]).replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts <= now:
                doomed.append(key)
                break
    for key in doomed:
        store.documents.pop(key, None)


# ── point-in-time recovery (version history reads) ─────────────────────────
def _entry_at(store: FirestoreStore, db: str, rel: str, read_time: str) -> dict | None:
    """The document's state as of `read_time`, from its recorded history (falls back
    to the current state if no history was kept — e.g. PITR was never enabled)."""
    hist = store.history.get(f"{db}/{rel}")
    if not hist:
        return store.get(db, rel)
    try:
        rt = datetime.fromisoformat(str(read_time).replace("Z", "+00:00"))
    except ValueError:
        return store.get(db, rel)
    result: dict | None = None
    found = False
    for ts, snap in hist:
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            continue
        if t <= rt:
            result, found = snap, True
        else:
            break
    return result if found else None


def _historical_in_collection(store: FirestoreStore, db: str, coll: str,
                              read_time: str) -> list[tuple[str, dict]]:
    prefix = f"{db}/{coll}/"
    depth = coll.count("/") + 2
    rels: set[str] = set()
    for key in store.documents:
        if key.startswith(prefix):
            rels.add(key[len(db) + 1:])
    for key in store.history:
        if key.startswith(prefix):
            rels.add(key[len(db) + 1:])
    out = []
    for rel in rels:
        if rel.count("/") + 1 != depth:
            continue
        entry = _entry_at(store, db, rel, read_time)
        if entry is not None:
            out.append((rel, entry))
    return out


# ── single-field index-exemption enforcement ────────────────────────────────
_INEQUALITY_OPS = {"LESS_THAN", "LESS_THAN_OR_EQUAL", "GREATER_THAN", "GREATER_THAN_OR_EQUAL",
                    "NOT_EQUAL", "NOT_IN"}


def _collect_filter_needs(filt: dict, needs: dict[str, set[str]]) -> None:
    if not filt:
        return
    if "fieldFilter" in filt:
        ff = filt["fieldFilter"]
        fp = (ff.get("field") or {}).get("fieldPath")
        op = ff.get("op")
        if fp and op in _INEQUALITY_OPS:
            needs.setdefault(fp, set()).update({"ASCENDING", "DESCENDING"})
        elif fp and op in ("ARRAY_CONTAINS", "ARRAY_CONTAINS_ANY"):
            needs.setdefault(fp, set()).add("CONTAINS")
    elif "compositeFilter" in filt:
        for sub in filt["compositeFilter"].get("filters") or []:
            _collect_filter_needs(sub, needs)


def _index_exempted(store: FirestoreStore, db: str, group: str, field_path: str, kind: str) -> bool:
    """True if `field_path` has an explicit single-field exemption removing the
    automatic index `kind` would otherwise provide (no fields record = still
    automatic = never exempted)."""
    rec = store.fields.get(db, {}).get(f"{group}/{field_path}")
    if not rec:
        return False
    indexes = (rec.get("indexConfig") or {}).get("indexes")
    if indexes is None:
        return False
    provided = set()
    for i in indexes:
        if i.get("order"):
            provided.add(i["order"])
        if i.get("arrayConfig"):
            provided.add("CONTAINS")
    return kind not in provided


def _covered_by_composite(store: FirestoreStore, db: str, group: str, field_path: str, kind: str) -> bool:
    for idx in store.indexes.get(db, {}).values():
        if idx.get("collectionGroup") != group:
            continue
        for f in idx.get("fields") or []:
            if f.get("fieldPath") == field_path and (f.get("order") == kind or f.get("arrayConfig") == kind):
                return True
    return False


def _check_index_requirements(store: FirestoreStore, db: str, group: str, where: dict,
                              order_by: list) -> FirestoreResponse | None:
    needs: dict[str, set[str]] = {}
    _collect_filter_needs(where, needs)
    for ob in order_by or []:
        fp = (ob.get("field") or {}).get("fieldPath")
        if fp:
            needs.setdefault(fp, set()).add(str(ob.get("direction", "ASCENDING")).upper())
    for fp, kinds in needs.items():
        missing = [k for k in kinds if _index_exempted(store, db, group, fp, k)]
        if not missing:
            continue
        if not any(_covered_by_composite(store, db, group, fp, k) for k in missing):
            return _err(400, "FAILED_PRECONDITION",
                        f'The query requires an index on field "{fp}": automatic single-field '
                        f'indexing is disabled for it (see Indexes > Single field) and no composite '
                        f'index on collection group "{group}" covers it.')
    return None


# ── export / import <-> real Cloud Storage objects ──────────────────────────
def _parse_gs_uri(uri: str) -> tuple[str | None, str]:
    if not uri.startswith("gs://"):
        return None, ""
    bucket, _, path = uri[5:].partition("/")
    return (bucket or None), path.strip("/")


def _collect_export_docs(store: FirestoreStore, db: str, collection_ids: list[str]) -> list[dict]:
    prefix = f"{db}/"
    out = []
    for key, entry in store.documents.items():
        if not key.startswith(prefix):
            continue
        rel = key[len(prefix):]
        if collection_ids and rel.split("/", 1)[0] not in collection_ids:
            continue
        out.append({"rel": rel, "fields": entry.get("fields", {}),
                    "createTime": entry.get("createTime"), "updateTime": entry.get("updateTime")})
    return out


def _export_key(path: str) -> str:
    return f"{path}/export.json" if path else "export.json"


def _gcs_write_export(gcs_store, bucket: str, path: str, payload: dict) -> None:
    from core.gcp_storage_core import _new_entry  # local import: avoid a module-load cycle
    gcs_store.create_bucket(bucket)
    objs = gcs_store.bucket_objects(bucket)
    key = _export_key(path)
    media = json.dumps(payload).encode()
    objs[key] = _new_entry(objs, key, media, "application/json", {})


def _gcs_read_export(gcs_store, bucket: str, path: str) -> dict | None:
    from core.gcp_storage_core import _entry_bytes
    objs = gcs_store.bucket_objects(bucket)
    key = _export_key(path)
    entry = objs.get(key)
    if entry is None:
        return None
    try:
        return json.loads(_entry_bytes(gcs_store, bucket, key, entry).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


# ── dispatch ───────────────────────────────────────────────────────────────
def _upgrade_legacy_keys(store: FirestoreStore) -> None:
    """Documents saved before multi-database support are keyed by `rel` alone
    (`users/alice`, an even number of segments); the current key is `{db}/{rel}`
    (odd). Move legacy keys under `(default)` — once per documents dict, so a
    restore that swaps the dict in (Nano IndexedDB, durable stores) is re-checked."""
    docs = store.documents
    if getattr(store, "_keys_checked", None) is docs:
        return
    for k in [k for k in docs if k.count("/") % 2 == 1]:
        docs.setdefault(f"(default)/{k}", docs.pop(k))
    store._keys_checked = docs


def dispatch(store: FirestoreStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"", gcs_store=None) -> FirestoreResponse:
    query = query or {}
    method = method.upper()
    _upgrade_legacy_keys(store)

    parsed = _parse_documents_path(path)
    if parsed is not None:
        project, database, base, rel, suffix = parsed
        _ensure_db(store, project, database)
        _sweep_ttl(store, database)
        r = _dispatch_documents(store, database, base, method, rel, suffix, query, body)
    else:
        r = _admin_dispatch(store, method, path, query, body, gcs_store)
    if method != "GET":
        store.persist()
    return r


# ── data plane ─────────────────────────────────────────────────────────────
def _dispatch_documents(store: FirestoreStore, db: str, base: str, method: str,
                        rel: str, suffix: str, query: dict, body: bytes) -> FirestoreResponse:
    if suffix == "runQuery":
        return _run_query(store, db, base, rel, _load_json(body))
    if suffix == "listCollectionIds":
        return _list_collection_ids(store, db, rel)
    if suffix == "batchGet":
        return _batch_get(store, db, base, _load_json(body))
    if suffix == "commit":
        return _commit(store, db, base, _load_json(body))
    if suffix == "beginTransaction":
        return _json(200, {"transaction": uuid.uuid4().hex})
    if suffix == "rollback":
        return _json(200, {})

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
            store.bump_usage(db, "writes")
            return _json(200, _doc_view(base, new_rel, entry))
        if method == "GET":                # list documents
            read_time = query.get("readTime")
            rows = (_historical_in_collection(store, db, coll, read_time) if read_time
                    else sorted(store.in_collection(db, coll), key=lambda kv: kv[0]))
            docs = [_doc_view(base, r, e) for r, e in rows]
            store.bump_usage(db, "reads", max(1, len(docs)))
            out: dict[str, Any] = {}
            if docs:
                out["documents"] = docs
            return _json(200, out)
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on collection")

    # ---- document: /{collection}/{doc}
    if is_document:
        entry = store.get(db, rel)
        if method == "GET":
            read_time = query.get("readTime")
            if read_time:
                entry = _entry_at(store, db, rel, read_time)
            if entry is None:
                return _err(404, "NOT_FOUND",
                            f"Document not found: {_doc_name(base, rel)}")
            store.bump_usage(db, "reads")
            return _json(200, _doc_view(base, rel, entry))
        if method in ("PATCH", "PUT"):     # set / merge fields
            data = _load_json(body)
            new_fields = data.get("fields", {})
            exists = str(query.get("currentDocument.exists", "")).lower()
            if exists == "true" and entry is None:
                return _err(404, "NOT_FOUND", f"No document to update: {_doc_name(base, rel)}")
            if exists == "false" and entry is not None:
                return _err(409, "ALREADY_EXISTS", f"Document already exists: {_doc_name(base, rel)}")
            mask = _mask_paths(query.get("updateMask.fieldPaths"))
            if mask is not None:           # updateMask: only the named fields change
                ts = _now()                # (a masked field absent from the body is deleted)
                entry = entry or {"fields": {}, "createTime": ts}
                entry["fields"] = _apply_mask(dict(entry.get("fields", {})), new_fields, mask)
                entry["updateTime"] = ts
                store.put(db, rel, entry)
                store.bump_usage(db, "writes")
                return _json(200, _doc_view(base, rel, entry))
            if entry is None:              # create-on-set
                ts = _now()
                entry = {"fields": dict(new_fields), "createTime": ts, "updateTime": ts}
                store.put(db, rel, entry)
                store.bump_usage(db, "writes")
                return _json(200, _doc_view(base, rel, entry))
            merged = dict(entry.get("fields", {}))
            merged.update(new_fields)      # merge: add/overwrite named fields, keep others
            entry["fields"] = merged
            entry["updateTime"] = _now()
            store.put(db, rel, entry)
            store.bump_usage(db, "writes")
            return _json(200, _doc_view(base, rel, entry))
        if method == "DELETE":
            store.delete(db, rel)          # Firestore delete is idempotent → 200 {}
            store.bump_usage(db, "deletes")
            return _json(200, {})
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on document")

    return _err(400, "INVALID_ARGUMENT", f"Unsupported request: {method} {rel!r}")


# ── updateMask / commit / batchGet (the RPCs google-cloud-firestore's DocumentReference
#    set()/update()/create()/delete()/get() and WriteBatch use) ─────────────
def _mask_paths(raw) -> list | None:
    if raw is None:
        return None
    vals = raw if isinstance(raw, (list, tuple)) else [raw]
    out = []
    for v in vals:
        out += [p.strip() for p in str(v).split(",") if p.strip()]
    return out


def _split_field_path(fp: str) -> list:
    parts, cur, quoted = [], "", False
    for ch in fp:
        if ch == "`":
            quoted = not quoted
        elif ch == "." and not quoted:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p for p in parts if p != ""]


def _get_path(fields: dict, path: list):
    cur = fields
    for i, seg in enumerate(path):
        v = cur.get(seg) if isinstance(cur, dict) else None
        if v is None:
            return None
        if i == len(path) - 1:
            return v
        cur = (v.get("mapValue") or {}).get("fields") if isinstance(v, dict) else None
    return None


def _set_path(fields: dict, path: list, value) -> None:
    cur = fields
    for seg in path[:-1]:
        nxt = cur.get(seg)
        if not (isinstance(nxt, dict) and "mapValue" in nxt):
            nxt = {"mapValue": {"fields": {}}}
            cur[seg] = nxt
        nxt["mapValue"].setdefault("fields", {})
        cur = nxt["mapValue"]["fields"]
    if value is None:
        cur.pop(path[-1], None)
    else:
        cur[path[-1]] = value


def _apply_mask(current: dict, new_fields: dict, mask: list) -> dict:
    out = json.loads(json.dumps(current))
    for fp in mask:
        path = _split_field_path(fp)
        if path:
            _set_path(out, path, _get_path(new_fields, path))
    return out


def _rel_of(base: str, name: str) -> str | None:
    name = str(name or "")
    marker = base + "/"
    i = name.find(marker)
    return unquote(name[i + len(marker):].strip("/")) if i >= 0 else None


def _num(v: dict):
    if "integerValue" in v:
        return int(v["integerValue"]), True
    if "doubleValue" in v:
        return float(v["doubleValue"]), False
    return 0, True


def _apply_transform(fields: dict, t: dict, ts: str) -> dict:
    path = _split_field_path(t.get("fieldPath", ""))
    if not path:
        return {"nullValue": None}
    cur = _get_path(fields, path) or {}
    if t.get("setToServerValue") in ("REQUEST_TIME", 1, "1"):   # (enum-encoding=int sends 1)
        val = {"timestampValue": ts}
    elif "increment" in t or "maximum" in t or "minimum" in t:
        op = "increment" if "increment" in t else ("maximum" if "maximum" in t else "minimum")
        a, ai = _num(cur if isinstance(cur, dict) else {})
        b, bi = _num(t[op])
        r = a + b if op == "increment" else (max(a, b) if op == "maximum" else min(a, b))
        val = {"integerValue": str(int(r))} if (ai and bi) else {"doubleValue": float(r)}
    elif "appendMissingElements" in t or "removeAllFromArray" in t:
        have = list(((cur or {}).get("arrayValue") or {}).get("values") or [])
        if "appendMissingElements" in t:
            for e in (t["appendMissingElements"].get("values") or []):
                if e not in have:
                    have.append(e)
        else:
            rm = t["removeAllFromArray"].get("values") or []
            have = [e for e in have if e not in rm]
        val = {"arrayValue": {"values": have}}
    else:
        return {"nullValue": None}
    _set_path(fields, path, val)
    return val


def _commit(store: FirestoreStore, db: str, base: str, request: dict) -> FirestoreResponse:
    """`documents:commit` — the writes apply in order, all or none (each precondition is
    checked against the state the earlier writes of the same commit produced). Supports
    update (+updateMask), delete, currentDocument preconditions and updateTransforms
    (server timestamp, increment, maximum/minimum, array union/remove)."""
    ts = _now()
    staged: dict = {}          # rel -> entry | None (deleted), in write order
    results = []
    for w in request.get("writes") or []:
        name = (w.get("update") or {}).get("name") if "update" in w else (w.get("delete") or w.get("transform", {}).get("document"))
        rel = _rel_of(base, name)
        if rel is None or rel.count("/") % 2 == 0:
            return _err(400, "INVALID_ARGUMENT", f"Invalid document name: {name}")
        cur = staged[rel] if rel in staged else store.get(db, rel)
        pre = w.get("currentDocument") or {}
        if "exists" in pre:
            if pre["exists"] and cur is None:
                return _err(404, "NOT_FOUND", f"No document to update: {_doc_name(base, rel)}")
            if not pre["exists"] and cur is not None:
                return _err(409, "ALREADY_EXISTS", f"Document already exists: {_doc_name(base, rel)}")
        if pre.get("updateTime") and (cur is None or cur.get("updateTime") != pre["updateTime"]):
            return _err(400, "FAILED_PRECONDITION", f"The document was modified: {_doc_name(base, rel)}")
        if "delete" in w:
            staged[rel] = None
            results.append({"updateTime": ts})
            continue
        entry = json.loads(json.dumps(cur)) if cur else {"fields": {}, "createTime": ts}
        if "update" in w:
            new_fields = (w["update"] or {}).get("fields") or {}
            # an empty mask arrives as `"updateMask": {}` (proto JSON drops the empty list)
            mask = (_mask_paths((w.get("updateMask") or {}).get("fieldPaths")) or []) if "updateMask" in w else None
            entry["fields"] = (_apply_mask(entry.get("fields") or {}, new_fields, mask) if mask is not None
                               else json.loads(json.dumps(new_fields)))
        tr = [_apply_transform(entry["fields"], t, ts)
              for t in (w.get("updateTransforms") or (w.get("transform") or {}).get("fieldTransforms") or [])]
        entry["updateTime"] = ts
        staged[rel] = entry
        results.append({"updateTime": ts, **({"transformResults": tr} if tr else {})})
    for rel, entry in staged.items():
        if entry is None:
            store.delete(db, rel)
            store.bump_usage(db, "deletes")
        else:
            store.put(db, rel, entry)
            store.bump_usage(db, "writes")
    return _json(200, {"writeResults": results, "commitTime": ts})


def _batch_get(store: FirestoreStore, db: str, base: str, request: dict) -> FirestoreResponse:
    """`documents:batchGet` — the streaming shape: a JSON array of {found|missing, readTime}."""
    ts = _now()
    read_time = request.get("readTime")
    out = []
    for name in request.get("documents") or []:
        rel = _rel_of(base, name)
        entry = (_entry_at(store, db, rel, read_time) if read_time else store.get(db, rel)) if rel else None
        if entry is None:
            out.append({"missing": name, "readTime": ts})
        else:
            out.append({"found": _doc_view(base, rel, entry), "readTime": ts})
    store.bump_usage(db, "reads", max(1, len(out)))
    return _json(200, out)


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


_FIELD_OPS = {1: "LESS_THAN", 2: "LESS_THAN_OR_EQUAL", 3: "GREATER_THAN", 4: "GREATER_THAN_OR_EQUAL",
              5: "EQUAL", 6: "NOT_EQUAL", 7: "ARRAY_CONTAINS", 8: "IN", 9: "ARRAY_CONTAINS_ANY", 10: "NOT_IN"}
_UNARY_OPS = {2: "IS_NAN", 3: "IS_NULL", 4: "IS_NOT_NAN", 5: "IS_NOT_NULL"}
_COMPOSITE_OPS = {1: "AND", 2: "OR"}
_DIRECTIONS = {1: "ASCENDING", 2: "DESCENDING"}


def _norm_query_enums(sq):
    """google-cloud-firestore's REST transport asks for `enum-encoding=int`, so operators
    and directions may arrive as numbers; map them to the names the evaluator uses."""
    def enum(v, table):
        if isinstance(v, bool):
            return v
        if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
            return table.get(int(v), v)
        return v

    def filt(f):
        if not isinstance(f, dict):
            return f
        f = dict(f)
        if isinstance(f.get("fieldFilter"), dict):
            f["fieldFilter"] = dict(f["fieldFilter"], op=enum(f["fieldFilter"].get("op"), _FIELD_OPS))
        if isinstance(f.get("unaryFilter"), dict):
            f["unaryFilter"] = dict(f["unaryFilter"], op=enum(f["unaryFilter"].get("op"), _UNARY_OPS))
        if isinstance(f.get("compositeFilter"), dict):
            cf = f["compositeFilter"]
            f["compositeFilter"] = dict(cf, op=enum(cf.get("op"), _COMPOSITE_OPS),
                                        filters=[filt(x) for x in (cf.get("filters") or [])])
        return f

    if not isinstance(sq, dict):
        return {}
    sq = dict(sq)
    if "where" in sq:
        sq["where"] = filt(sq["where"])
    if isinstance(sq.get("orderBy"), list):
        sq["orderBy"] = [dict(o, direction=enum(o.get("direction", "ASCENDING"), _DIRECTIONS))
                         if isinstance(o, dict) else o for o in sq["orderBy"]]
    return sq


def _run_query(store: FirestoreStore, db: str, base: str, parent_rel: str,
               request: dict) -> FirestoreResponse:
    """structuredQuery: `from[0].collectionId` (relative to the query parent) with
    a where clause (fieldFilter / unaryFilter / compositeFilter AND|OR, full
    comparison + IN/NOT_IN + ARRAY_CONTAINS[_ANY] operators), plus orderBy,
    offset and limit. Returns the Firestore streaming shape — a JSON array of
    `{"document","readTime"}` rows."""
    sq = _norm_query_enums(request.get("structuredQuery", {}) or {})
    froms = sq.get("from", []) or []
    if not froms:
        return _json(200, [])
    coll_id = froms[0].get("collectionId", "")
    coll = f"{parent_rel}/{coll_id}" if parent_rel else coll_id
    where = sq.get("where") or {}
    order_by = sq.get("orderBy") or []

    index_err = _check_index_requirements(store, db, coll_id, where, order_by)
    if index_err:
        return index_err

    as_of = request.get("readTime")
    candidates = _historical_in_collection(store, db, coll, as_of) if as_of else store.in_collection(db, coll)
    matched = []
    for rel, entry in candidates:
        if _eval_filter(entry.get("fields", {}), where):
            matched.append((rel, entry))

    # orderBy (may be multiple keys); default to document-name order.
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

    store.bump_usage(db, "reads", max(1, len(matched)))
    read_time = _now()
    rows = [{"document": _doc_view(base, rel, entry), "readTime": read_time}
            for rel, entry in matched]
    if not rows:
        return _json(200, [{"readTime": read_time}])
    return _json(200, rows)


# ── admin plane ─────────────────────────────────────────────────────────────
def _admin_dispatch(store: FirestoreStore, method: str, path: str,
                    query: dict, body: bytes, gcs_store=None) -> FirestoreResponse:
    segs = [unquote(s) for s in _admin_segs(path)]
    if len(segs) < 3 or segs[0] != "projects":
        return _err(404, "NOT_FOUND", f"Unknown path: {path}")
    project = segs[1]
    if segs[2] == "locations":
        return _dispatch_backups(store, project, method, segs[3:])
    base_seg, admin_suffix = _split_suffix(segs[2])
    if base_seg != "databases":
        return _err(404, "NOT_FOUND", f"Unknown path: {path}")
    if admin_suffix == "restore" and len(segs) == 3:
        return _dispatch_database_restore(store, project, method, body)
    if len(segs) == 3:
        return _dispatch_databases_collection(store, project, method, query, body)
    dbid, suffix = _split_suffix(segs[3])
    if len(segs) == 4:
        return _dispatch_database_item(store, project, dbid, suffix, method, query, body, gcs_store)
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
                            method: str, query: dict, body: bytes, gcs_store=None) -> FirestoreResponse:
    if suffix in ("exportDocuments", "importDocuments"):
        if dbid not in store.databases:
            return _err(404, "NOT_FOUND", f"Database does not exist: {dbid}")
        return _dispatch_export_import(store, project, dbid, suffix, body, gcs_store)
    if suffix in ("getSecurityRules", "updateSecurityRules"):
        if suffix == "getSecurityRules":
            return _json(200, {"rules": store.security_rules.get(dbid, "")})
        data = _load_json(body)
        store.security_rules[dbid] = data.get("rules", "")
        return _json(200, {"rules": store.security_rules[dbid]})
    if suffix == "usage":
        if dbid not in store.databases:
            return _err(404, "NOT_FOUND", f"Database does not exist: {dbid}")
        u = store.usage.get(dbid, {"reads": 0, "writes": 0, "deletes": 0})
        prefix = f"{dbid}/"
        doc_count = sum(1 for k in store.documents if k.startswith(prefix))
        storage_bytes = sum(len(json.dumps(e.get("fields", {}))) for k, e in store.documents.items()
                            if k.startswith(prefix))
        return _json(200, {"documentCount": doc_count, "storageBytes": storage_bytes, **u})

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
        store.usage.pop(dbid, None)
        for key in [k for k in store.history if k.startswith(prefix)]:
            store.history.pop(key, None)
        return _json(200, db)
    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on database")


def _dispatch_export_import(store: FirestoreStore, project: str, dbid: str, kind: str,
                            body: bytes, gcs_store=None) -> FirestoreResponse:
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
        if gcs_store is not None:
            bucket, gpath = _parse_gs_uri(location)
            if bucket:
                payload = {"project": project, "database": dbid,
                           "documents": _collect_export_docs(store, dbid, collection_ids)}
                _gcs_write_export(gcs_store, bucket, gpath, payload)
    else:
        op_kind, location = "ImportDocuments", data.get("inputUriPrefix", "")
        meta_extra = {"inputUriPrefix": location}
        response = {"@type": "type.googleapis.com/google.protobuf.Empty"}
        if gcs_store is not None:
            bucket, gpath = _parse_gs_uri(location)
            if bucket:
                payload = _gcs_read_export(gcs_store, bucket, gpath)
                for doc in (payload or {}).get("documents", []):
                    rel = doc.get("rel")
                    if not rel or (collection_ids and rel.split("/", 1)[0] not in collection_ids):
                        continue
                    store.put(dbid, rel, {"fields": doc.get("fields", {}),
                                          "createTime": doc.get("createTime") or ts,
                                          "updateTime": doc.get("updateTime") or ts})
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
    # A real document-data snapshot (not API-visible) so `databases:restore` can
    # actually reconstruct a new database from this backup.
    prefix = f"{dbid}/"
    store.backup_snapshots[bid] = {
        "documents": {k[len(prefix):]: json.loads(json.dumps(v))
                      for k, v in store.documents.items() if k.startswith(prefix)},
        "indexes": json.loads(json.dumps(store.indexes.get(dbid) or {})),
        "fields": json.loads(json.dumps(store.fields.get(dbid) or {})),
        "pitr": db.get("pointInTimeRecoveryEnablement", "POINT_IN_TIME_RECOVERY_DISABLED"),
    }
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
        store.backup_snapshots.pop(bid, None)
        return _json(200, {})
    return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on backup")


def _dispatch_database_restore(store: FirestoreStore, project: str, method: str,
                               body: bytes) -> FirestoreResponse:
    """`databases:restore` — real Firestore's restore-a-backup-into-a-new-database RPC
    (`databaseId` + `backup`). Synchronous here (no LRO) but genuinely repopulates the
    new database's documents/indexes/fields from the backup's snapshot."""
    if method != "POST":
        return _err(400, "INVALID_ARGUMENT", f"Unsupported method {method} on databases:restore")
    data = _load_json(body)
    dbid = data.get("databaseId")
    backup_name = data.get("backup", "")
    if not dbid:
        return _err(400, "INVALID_ARGUMENT", "databaseId is required")
    if dbid in store.databases:
        return _err(409, "ALREADY_EXISTS", f"Database already exists: {dbid}")
    bid = backup_name.rsplit("/", 1)[-1]
    backup = store.backups.get(bid)
    snap = store.backup_snapshots.get(bid)
    if backup is None or snap is None or backup["database"].split("/")[1] != project:
        return _err(404, "NOT_FOUND", f"Backup not found: {backup_name}")
    rec = _ensure_db(store, project, dbid)
    rec["pointInTimeRecoveryEnablement"] = snap.get("pitr", "POINT_IN_TIME_RECOVERY_DISABLED")
    for rel, entry in snap["documents"].items():
        store.put(dbid, rel, json.loads(json.dumps(entry)))
    store.indexes[dbid] = json.loads(json.dumps(snap.get("indexes") or {}))
    store.fields[dbid] = json.loads(json.dumps(snap.get("fields") or {}))
    return _json(200, rec)


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
