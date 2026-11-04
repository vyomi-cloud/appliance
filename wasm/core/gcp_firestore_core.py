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

import hashlib
import json
import re
import math
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
        # Insights: derived purely from real query/index activity, never synthetic —
        # db -> "{collectionGroup}:{fieldPath}:{kinds}" -> recommendation record.
        self.index_recommendations: dict[str, dict[str, dict]] = {}
        # db -> indexId -> {"hits", "lastUsed"} — bumped when a query's filter/orderBy/
        # vector-search fields actually overlap a composite/vector index's fields.
        self.index_usage: dict[str, dict[str, dict]] = {}
        self.query_count: dict[str, int] = {}           # db -> total :runQuery calls
        # Key Visualizer: real per-document access counts (reads + writes + deletes),
        # bucketed by a hash of the key at render time — db -> rel -> count.
        self.key_access: dict[str, dict[str, int]] = {}

    # -- documents ------------------------------------------------------------
    def get(self, db: str, rel: str) -> dict | None:
        d = self.documents.get(f"{db}/{rel}")
        return d if isinstance(d, dict) else None

    on_doc_event = None   # optional hook(db, rel, old_entry|None, new_entry|None) — Eventarc Firestore triggers

    def put(self, db: str, rel: str, entry: dict) -> None:
        old = self.documents.get(f"{db}/{rel}") if self.on_doc_event else None
        if old is not None and "datastore" in old:
            old = None
        self.documents[f"{db}/{rel}"] = entry
        self._record_history(db, rel, entry)
        if self.on_doc_event and "datastore" not in entry:
            self._fire_doc_event(db, rel, old, entry)

    def delete(self, db: str, rel: str) -> None:
        old = self.documents.get(f"{db}/{rel}") if self.on_doc_event else None
        self.documents.pop(f"{db}/{rel}", None)
        self._record_history(db, rel, None)
        if self.on_doc_event and old is not None and "datastore" not in old:
            self._fire_doc_event(db, rel, old, None)

    def _fire_doc_event(self, db, rel, old, new) -> None:
        try:
            self.on_doc_event(db, rel, json.loads(json.dumps(old)) if old else None, json.loads(json.dumps(new)) if new else None)
        except Exception:   # a trigger problem never fails the write (real Eventarc is async)
            pass

    def _record_history(self, db: str, rel: str, entry: dict | None) -> None:
        if (self.databases.get(db) or {}).get("pointInTimeRecoveryEnablement") != "POINT_IN_TIME_RECOVERY_ENABLED":
            return
        snap = json.loads(json.dumps(entry)) if entry is not None else None
        ts = entry.get("updateTime") if entry else _now()
        self.history.setdefault(f"{db}/{rel}", []).append((ts, snap))

    def bump_usage(self, db: str, kind: str, n: int = 1) -> None:
        u = self.usage.setdefault(db, {"reads": 0, "writes": 0, "deletes": 0})
        u[kind] = u.get(kind, 0) + n

    def bump_key_access(self, db: str, rel: str, n: int = 1) -> None:
        ka = self.key_access.setdefault(db, {})
        ka[rel] = ka.get(rel, 0) + n

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
            _record_index_recommendation(store, db, group, fp, set(missing))
            return _err(400, "FAILED_PRECONDITION",
                        f'The query requires an index on field "{fp}": automatic single-field '
                        f'indexing is disabled for it (see Indexes > Single field) and no composite '
                        f'index on collection group "{group}" covers it.')
    return None


# ── Insights (real query/index telemetry) ───────────────────────────────────
def _record_index_recommendation(store: FirestoreStore, db: str, group: str, fp: str,
                                 kinds: set[str]) -> None:
    recs = store.index_recommendations.setdefault(db, {})
    key = f"{group}:{fp}:{','.join(sorted(kinds))}"
    rec = recs.setdefault(key, {"collectionGroup": group, "fieldPath": fp,
                                 "kinds": sorted(kinds), "occurrences": 0, "firstSeen": _now()})
    rec["occurrences"] += 1
    rec["lastSeen"] = _now()


def _bump_matching_index_usage(store: FirestoreStore, db: str, group: str, where: dict,
                               order_by: list) -> None:
    """A real, if heuristic, signal for "Unused indexes": a composite index is counted
    as used whenever a query on its collection group filters/orders by at least one of
    its fields — derived from genuine :runQuery traffic, never synthesized."""
    used_fields: set[str] = set()

    def _walk(f):
        if not f:
            return
        if "fieldFilter" in f:
            fp = ((f["fieldFilter"].get("field") or {}).get("fieldPath"))
            if fp:
                used_fields.add(fp)
        elif "unaryFilter" in f:
            fp = ((f["unaryFilter"].get("field") or {}).get("fieldPath"))
            if fp:
                used_fields.add(fp)
        elif "compositeFilter" in f:
            for sub in f["compositeFilter"].get("filters") or []:
                _walk(sub)
    _walk(where)
    for ob in order_by or []:
        fp = (ob.get("field") or {}).get("fieldPath")
        if fp:
            used_fields.add(fp)
    if not used_fields:
        return
    for iid, idx in store.indexes.get(db, {}).items():
        if idx.get("collectionGroup") != group:
            continue
        idx_fields = {f.get("fieldPath") for f in (idx.get("fields") or []) if f.get("fieldPath")}
        if idx_fields & used_fields:
            rec = store.index_usage.setdefault(db, {}).setdefault(iid, {"hits": 0})
            rec["hits"] += 1
            rec["lastUsed"] = _now()


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
        ctxinfo = client_rules_context(headers, query)
        if ctxinfo is not None:
            denied = _enforce_rules(store, database, base, method, rel, suffix, query, body, ctxinfo)
            if denied is not None:
                return denied
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
            store.bump_key_access(db, new_rel)
            return _json(200, _doc_view(base, new_rel, entry))
        if method == "GET":                # list documents
            read_time = query.get("readTime")
            rows = (_historical_in_collection(store, db, coll, read_time) if read_time
                    else sorted(store.in_collection(db, coll), key=lambda kv: kv[0]))
            docs = [_doc_view(base, r, e) for r, e in rows]
            store.bump_usage(db, "reads", max(1, len(docs)))
            for r, _e in rows:
                store.bump_key_access(db, r)
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
            store.bump_key_access(db, rel)
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
                store.bump_key_access(db, rel)
                return _json(200, _doc_view(base, rel, entry))
            if entry is None:              # create-on-set
                ts = _now()
                entry = {"fields": dict(new_fields), "createTime": ts, "updateTime": ts}
                store.put(db, rel, entry)
                store.bump_usage(db, "writes")
                store.bump_key_access(db, rel)
                return _json(200, _doc_view(base, rel, entry))
            merged = dict(entry.get("fields", {}))
            merged.update(new_fields)      # merge: add/overwrite named fields, keep others
            entry["fields"] = merged
            entry["updateTime"] = _now()
            store.put(db, rel, entry)
            store.bump_usage(db, "writes")
            store.bump_key_access(db, rel)
            return _json(200, _doc_view(base, rel, entry))
        if method == "DELETE":
            store.delete(db, rel)          # Firestore delete is idempotent → 200 {}
            store.bump_usage(db, "deletes")
            store.bump_key_access(db, rel)
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
        store.bump_key_access(db, rel)
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
        if rel is not None:
            store.bump_key_access(db, rel)
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
    offset and limit — or a `findNearest` vector-similarity search. Returns the
    Firestore streaming shape — a JSON array of `{"document","readTime"}` rows."""
    sq = _norm_query_enums(request.get("structuredQuery", {}) or {})
    froms = sq.get("from", []) or []
    if not froms:
        return _json(200, [])
    coll_id = froms[0].get("collectionId", "")
    coll = f"{parent_rel}/{coll_id}" if parent_rel else coll_id
    where = sq.get("where") or {}
    order_by = sq.get("orderBy") or []
    store.query_count[db] = store.query_count.get(db, 0) + 1

    find_nearest = sq.get("findNearest")
    if find_nearest:
        return _run_find_nearest(store, db, base, coll, coll_id, find_nearest, where)

    index_err = _check_index_requirements(store, db, coll_id, where, order_by)
    if index_err:
        return index_err
    _bump_matching_index_usage(store, db, coll_id, where, order_by)

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
    for rel, _e in matched:
        store.bump_key_access(db, rel)
    read_time = _now()
    rows = [{"document": _doc_view(base, rel, entry), "readTime": read_time}
            for rel, entry in matched]
    if not rows:
        return _json(200, [{"readTime": read_time}])
    return _json(200, rows)


# ── vector search (findNearest) ─────────────────────────────────────────────
_VECTOR_TYPE_MARKER = "__vector__"
_DISTANCE_MEASURES = {1: "EUCLIDEAN", 2: "COSINE", 3: "DOT_PRODUCT"}


def _is_vector_value(v: dict) -> bool:
    fields = ((v or {}).get("mapValue") or {}).get("fields") or {}
    return fields.get("__type__", {}).get("stringValue") == _VECTOR_TYPE_MARKER and "value" in fields


def _vector_floats(v: dict) -> list[float]:
    fields = ((v or {}).get("mapValue") or {}).get("fields") or {}
    vals = ((fields.get("value") or {}).get("arrayValue") or {}).get("values") or []
    out = []
    for x in vals:
        if "doubleValue" in x:
            out.append(float(x["doubleValue"]))
        elif "integerValue" in x:
            out.append(float(x["integerValue"]))
        else:
            out.append(0.0)
    return out


def _encode_vector(values: list) -> dict:
    return {"mapValue": {"fields": {
        "__type__": {"stringValue": _VECTOR_TYPE_MARKER},
        "value": {"arrayValue": {"values": [{"doubleValue": float(x)} for x in values]}},
    }}}


def _vector_distance(a: list[float], b: list[float], measure: str) -> float:
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    if measure == "DOT_PRODUCT":
        return -sum(x * y for x, y in zip(a, b))
    if measure == "COSINE":
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1e-12
        nb = math.sqrt(sum(y * y for y in b)) or 1e-12
        return 1.0 - dot / (na * nb)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))   # EUCLIDEAN (default)


def _vector_index_exists(store: FirestoreStore, db: str, group: str, field_path: str, dim: int) -> bool:
    for idx in store.indexes.get(db, {}).values():
        if idx.get("collectionGroup") != group:
            continue
        for f in idx.get("fields") or []:
            if f.get("fieldPath") == field_path and (f.get("vectorConfig") or {}).get("dimension") == dim:
                return True
    return False


def _run_find_nearest(store: FirestoreStore, db: str, base: str, coll: str, group: str,
                      fn: dict, where: dict) -> FirestoreResponse:
    """`findNearest` — a brute-force (exact, not approximate-nearest-neighbor) k-NN scan
    over the collection's real document vectors, same as what a local Firestore emulator
    does at small scale. Requires a matching vector index to exist on `vectorField` +
    dimension, exactly like production Firestore, so creating one is genuinely required —
    not decorative console-only bookkeeping."""
    field_path = (fn.get("vectorField") or {}).get("fieldPath")
    qv_raw = fn.get("queryVector") or {}
    query_vec = _vector_floats(qv_raw) if _is_vector_value(qv_raw) else _scalar_list(qv_raw)
    if not field_path or not query_vec:
        return _err(400, "INVALID_ARGUMENT", "findNearest requires vectorField and queryVector")
    measure_raw = fn.get("distanceMeasure", "EUCLIDEAN")
    if isinstance(measure_raw, int) or (isinstance(measure_raw, str) and measure_raw.isdigit()):
        measure = _DISTANCE_MEASURES.get(int(measure_raw), "EUCLIDEAN")
    else:
        measure = measure_raw
    dim = len(query_vec)
    if not _vector_index_exists(store, db, group, field_path, dim):
        _record_index_recommendation(store, db, group, field_path, {f"VECTOR:{dim}"})
        return _err(400, "FAILED_PRECONDITION",
                    f'findNearest on "{field_path}" ({dim} dimensions) requires a vector index on '
                    f'collection group "{group}" — create one from Indexes > Vector.')

    scored = []
    for rel, entry in store.in_collection(db, coll):
        if not _eval_filter(entry.get("fields", {}), where):
            continue
        fv = (entry.get("fields") or {}).get(field_path)
        if not (isinstance(fv, dict) and _is_vector_value(fv)):
            continue
        vec = _vector_floats(fv)
        if len(vec) != dim:
            continue
        scored.append((_vector_distance(query_vec, vec, measure), rel, entry))
    scored.sort(key=lambda t: t[0])

    threshold = fn.get("distanceThreshold")
    if threshold is not None:
        scored = [s for s in scored if s[0] <= float(threshold)]
    limit = fn.get("limit")
    if isinstance(limit, dict):
        limit = limit.get("value")
    if limit is not None:
        scored = scored[:int(limit)]

    for iid, idx in store.indexes.get(db, {}).items():
        if idx.get("collectionGroup") == group and any(f.get("fieldPath") == field_path for f in idx.get("fields") or []):
            rec = store.index_usage.setdefault(db, {}).setdefault(iid, {"hits": 0})
            rec["hits"] += 1
            rec["lastUsed"] = _now()

    store.bump_usage(db, "reads", max(1, len(scored)))
    read_time = _now()
    result_field = fn.get("distanceResultField")
    rows = []
    for dist, rel, entry in scored:
        store.bump_key_access(db, rel)
        doc = _doc_view(base, rel, entry)
        if result_field:
            doc = dict(doc, fields=dict(doc["fields"], **{result_field: {"doubleValue": dist}}))
        rows.append({"document": doc, "readTime": read_time})
    if not rows:
        return _json(200, [{"readTime": read_time}])
    return _json(200, rows)


# ── security rules ─────────────────────────────────────────────────────────────────────
# The rules language lives in core/firestore_rules_core.py (functions, get()/exists(), map/list/
# string methods, ...). Here: the playground shim and the client-SDK enforcement on the data plane.
try:
    from core import firestore_rules_core as _rules
except ImportError:  # pragma: no cover - Pyodide flat layout
    import firestore_rules_core as _rules  # type: ignore


def evaluate_security_rules(rules_src: str, *, method: str, db: str, rel_path: str,
                            auth: dict | None, resource_data: dict | None,
                            request_resource_data: dict | None, fetch=None) -> dict:
    """Evaluate `rules_src` against one simulated request (Rules Playground / :testSecurityRules).
    Returns `{"allow", "matchedPath", "error", "trace"}`."""
    segs = [s for s in rel_path.split("/") if s]
    doc_id = segs[-1] if segs else ""
    res = None if method in ("create",) and resource_data is None else {
        "data": resource_data if resource_data is not None else (request_resource_data or {}),
        "id": doc_id, "__name__": _rules.Path(["databases", db, "documents"] + segs)}
    request = _rules_request(method, db, segs, auth, request_resource_data)
    return _rules.evaluate(rules_src, method=method, rel_path=rel_path, db=db, request=request, resource=res, fetch=fetch)


def _rules_request(method: str, db: str, segs: list, auth: dict | None, request_data, query: dict | None = None) -> dict:
    a = None
    if auth:
        tok = dict(auth.get("token") or {})
        tok.setdefault("sub", auth.get("uid"))
        a = {"uid": auth.get("uid"), "token": tok}
    return {"auth": a, "method": method, "time": _rules.parse_ts(_now()),
            "path": _rules.Path(["databases", db, "documents"] + list(segs)),
            "resource": {"data": request_data, "id": segs[-1] if segs else ""} if request_data is not None else None,
            "query": query or {"limit": None, "offset": 0, "orderBy": None}}


def _jwt_claims(token: str) -> dict | None:
    import base64
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        raw = parts[1] + "=" * (-len(parts[1]) % 4)
        c = json.loads(base64.urlsafe_b64decode(raw))
        return c if isinstance(c, dict) else None
    except Exception:
        return None


def client_rules_context(headers: dict | None, query: dict) -> dict | None:
    """None -> a privileged caller (Admin SDK / gcloud / the console's data viewer / emulator
    `Bearer owner`): rules are bypassed, exactly as in production. Otherwise the request is an
    end-user client-SDK request and carries {"auth": {...} | None}. Client = a Firebase ID token
    (Bearer JWT issued by securetoken.google.com/<project>), or an API-key-only request
    (`?key=` / X-Goog-Api-Key) which is an unauthenticated client. The token is decoded, not
    signature-verified (as the Firebase emulator does)."""
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    authz = str(h.get("authorization") or "")
    if authz.lower().startswith("bearer "):
        tok = authz[7:].strip()
        claims = _jwt_claims(tok)
        if claims and ("securetoken.google.com" in str(claims.get("iss", "")) or "firebase" in claims):
            uid = claims.get("user_id") or claims.get("sub")
            return {"auth": {"uid": uid, "token": {k: v for k, v in claims.items() if k not in ("firebase",)}}}
        return None
    if h.get("x-goog-api-key") or h.get("x-firebase-gmpid") or query.get("key"):
        return {"auth": None}
    return None


def _entry_ctx(db: str, rel: str, entry: dict | None) -> dict | None:
    if entry is None:
        return None
    segs = [s for s in rel.split("/") if s]
    return {"data": _rules.fields_to_data(entry.get("fields")), "id": segs[-1],
            "__name__": _rules.Path(["databases", db, "documents"] + segs)}


def _rules_check(store: FirestoreStore, db: str, method: str, rel: str, ctxinfo: dict, entry, new_fields,
                 query: dict | None = None, staged: dict | None = None) -> str | None:
    """-> None when allowed, else the denial reason."""
    src = store.security_rules.get(db) if isinstance(store.security_rules.get(db), str) else None
    if not src:
        return "No security rules are published for this database; client access is denied by default."

    def fetch(r):
        e = store.get(db, r)
        return _entry_ctx(db, r, e)

    def fetch_after(r):
        if staged is not None and r in staged:
            return _entry_ctx(db, r, staged[r])
        return fetch(r)

    segs = [s for s in rel.split("/") if s]
    req_data = _rules.fields_to_data(new_fields) if new_fields is not None else None
    request = _rules_request(method if method not in ("get", "list") else method, db, segs, ctxinfo.get("auth"), req_data, query)
    if method in ("get", "list"):
        request["resource"] = None
    res = _entry_ctx(db, rel, entry) if method not in ("create",) else None
    out = _rules.evaluate(src, method=method, rel_path=rel, db=db, request=request, resource=res,
                          fetch=fetch, fetch_after=fetch_after)
    if out["allow"]:
        return None
    return out.get("error") or "Missing or insufficient permissions."


_DENIED = "Missing or insufficient permissions."


def _denied(reason: str | None = None) -> FirestoreResponse:
    return _err(403, "PERMISSION_DENIED", _DENIED)


def _eq_filters(where: dict | None) -> dict:
    """Equality constraints (field -> python value) a query guarantees on every result."""
    out: dict = {}

    def walk(f):
        if not isinstance(f, dict):
            return
        if "compositeFilter" in f and str(f["compositeFilter"].get("op", "AND")) in ("AND", "1"):
            for x in f["compositeFilter"].get("filters", []):
                walk(x)
        elif "fieldFilter" in f and str(f["fieldFilter"].get("op")) in ("EQUAL", "5"):
            ff = f["fieldFilter"]
            out[(ff.get("field") or {}).get("fieldPath", "")] = _rules.from_fs_value(ff.get("value"))
    walk(where)
    return out


def _nest(flat: dict) -> dict:
    out: dict = {}
    for path, v in flat.items():
        cur = out
        parts = path.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = v
    return out


def _enforce_rules(store: FirestoreStore, db: str, base: str, method: str, rel: str, suffix: str,
                   query: dict, body: bytes, ctxinfo: dict) -> FirestoreResponse | None:
    """Evaluate the database's published rules for a client-SDK request. None = proceed."""
    segs = [s for s in rel.split("/") if s]
    is_doc = len(segs) != 0 and len(segs) % 2 == 0
    if suffix in ("beginTransaction", "rollback"):
        return None
    if suffix == "listCollectionIds":
        return _denied()
    if suffix == "batchGet":
        for name in _load_json(body).get("documents") or []:
            r = _rel_of(base, name)
            if r is None or _rules_check(store, db, "get", r, ctxinfo, store.get(db, r), None):
                return _denied()
        return None
    if suffix == "runQuery":
        sq = _load_json(body).get("structuredQuery") or {}
        q = {"limit": sq.get("limit") if not isinstance(sq.get("limit"), dict) else sq["limit"].get("value"),
             "offset": sq.get("offset", 0), "orderBy": [(o.get("field") or {}).get("fieldPath") for o in sq.get("orderBy") or []]}
        eq = _nest(_eq_filters(sq.get("where")))
        for frm in sq.get("from") or [{}]:
            coll = (rel + "/" if rel else "") + frm.get("collectionId", "")
            group = bool(frm.get("allDescendants"))
            probe = (coll + "/__query__") if not group else frm.get("collectionId", "") + "/__query__"
            # a collection-group query is checked against `/{path=**}/<cid>/{doc}`
            stub = {"fields": {}}
            fields = {k: _to_fs(v) for k, v in eq.items()}
            stub["fields"] = fields
            if _rules_check(store, db, "list", probe if not group else "__group__/" + probe, ctxinfo, stub, None, q):
                return _denied()
        return None
    if suffix == "commit":
        staged: dict = {}
        for w in _load_json(body).get("writes") or []:
            name = (w.get("update") or {}).get("name") if "update" in w else (w.get("delete") or (w.get("transform") or {}).get("document"))
            r = _rel_of(base, name)
            if r is None:
                return None
            cur = staged[r] if r in staged else store.get(db, r)
            if "delete" in w:
                if _rules_check(store, db, "delete", r, ctxinfo, cur, None, staged=staged):
                    return _denied()
                staged[r] = None
                continue
            entry = json.loads(json.dumps(cur)) if cur else {"fields": {}}
            if "update" in w:
                nf = (w["update"] or {}).get("fields") or {}
                mask = (_mask_paths((w.get("updateMask") or {}).get("fieldPaths")) or []) if "updateMask" in w else None
                entry["fields"] = _apply_mask(entry.get("fields") or {}, nf, mask) if mask is not None else json.loads(json.dumps(nf))
            for t in (w.get("updateTransforms") or []):
                _apply_transform(entry["fields"], t, _now())
            op = "update" if cur is not None else "create"
            staged[r] = entry
            if _rules_check(store, db, op, r, ctxinfo, cur, entry["fields"], staged=staged):
                return _denied()
        return None
    if is_doc:
        entry = store.get(db, rel)
        if method == "GET":
            return _denied() if _rules_check(store, db, "get", rel, ctxinfo, entry, None) else None
        if method == "DELETE":
            return _denied() if _rules_check(store, db, "delete", rel, ctxinfo, entry, None) else None
        if method in ("PATCH", "PUT"):
            nf = _load_json(body).get("fields", {})
            result = dict((entry or {}).get("fields") or {})
            mask = _mask_paths(query.get("updateMask.fieldPaths"))
            result = _apply_mask(result, nf, mask) if mask is not None else (nf if entry is None else {**result, **nf})
            return _denied() if _rules_check(store, db, "update" if entry is not None else "create", rel, ctxinfo, entry, result) else None
        return None
    # collection
    if method == "POST":
        doc_id = query.get("documentId") or "__auto__"
        nf = _load_json(body).get("fields", {})
        return _denied() if _rules_check(store, db, "create", f"{rel}/{doc_id}", ctxinfo, None, nf) else None
    if method == "GET":
        q = {"limit": query.get("pageSize"), "offset": 0, "orderBy": query.get("orderBy")}
        return _denied() if _rules_check(store, db, "list", f"{rel}/__query__", ctxinfo, None, None, q) else None
    return None


def _to_fs(v) -> dict:
    if v is None: return {"nullValue": None}
    if isinstance(v, bool): return {"booleanValue": v}
    if isinstance(v, int): return {"integerValue": str(v)}
    if isinstance(v, float): return {"doubleValue": v}
    if isinstance(v, str): return {"stringValue": v}
    if isinstance(v, dict): return {"mapValue": {"fields": {k: _to_fs(x) for k, x in v.items()}}}
    if isinstance(v, list): return {"arrayValue": {"values": [_to_fs(x) for x in v]}}
    return {"stringValue": str(v)}


# ── admin plane ─────────────────────────────────────────────────────────────
# ── Firebase Rules API (firebaserules.googleapis.com v1): rulesets, releases, :test ─────────
_RS = "__rulesets__"
_REL = "__releases__"


def _rs(store):
    return store.security_rules.setdefault(_RS, {})


def _rel(store):
    return store.security_rules.setdefault(_REL, {})


def _db_of_release(rname: str) -> str:
    # projects/{p}/releases/cloud.firestore[/{db}]
    tail = rname.split("/releases/", 1)[1]
    parts = tail.split("/", 1)
    return parts[1] if len(parts) > 1 and parts[1] else "(default)"


def _ruleset_source(rs: dict) -> str:
    files = (rs.get("source") or {}).get("files") or []
    return "\n".join(f.get("content", "") for f in files)


def _publish_rules(store, project: str, db: str, src: str) -> dict:
    """Console/legacy publish: create a ruleset and (re)point the database's release at it."""
    now = _now()
    rid = uuid.uuid4().hex[:8] + "-" + uuid.uuid4().hex[:4] + "-" + uuid.uuid4().hex[:4] + "-" + uuid.uuid4().hex[:12]
    name = f"projects/{project}/rulesets/{rid}"
    _rs(store)[name] = {"name": name, "createTime": now,
                        "source": {"files": [{"name": "firestore.rules", "content": src}]}}
    rname = f"projects/{project}/releases/cloud.firestore" + ("" if db == "(default)" else f"/{db}")
    prev = _rel(store).get(rname)
    _rel(store)[rname] = {"name": rname, "rulesetName": name, "createTime": (prev or {}).get("createTime", now), "updateTime": now}
    store.security_rules[db] = src
    return _rel(store)[rname]


def _test_case(src_ast, case: dict, fetch_docs: dict) -> dict:
    method = str(case.get("method") or "GET").lower()
    path = str(case.get("path") or "")
    m = re.match(r"^/databases/([^/]+)/documents/?(.*)$", path)
    if not m:
        return {"state": "FAILURE", "debugMessages": [f"Invalid path {path!r}; expected /databases/(default)/documents/..."]}
    db, rel = m.group(1), m.group(2)
    req = case.get("request") or {}
    auth = req.get("auth")
    res = case.get("resource")
    r = evaluate_security_rules_ast(src_ast, method=method, db=db, rel_path=rel, auth=auth,
                                   resource_data=(res or {}).get("data") if res is not None else None,
                                   request_resource_data=(req.get("resource") or {}).get("data") if "resource" in req else (req.get("data")),
                                   fetch=lambda rr: ({"data": fetch_docs[rr]} if rr in fetch_docs else None))
    expect = str(case.get("expectation") or "ALLOW").upper()
    ok = (r["allow"] and expect == "ALLOW") or (not r["allow"] and expect == "DENY")
    out = {"state": "SUCCESS" if ok else "FAILURE",
           "debugMessages": ([] if ok else [f"Expected {expect} but the request was {'ALLOWED' if r['allow'] else 'DENIED'}."])
           + ([r["error"]] if r.get("error") else [])}
    out["visitedExpressions"] = [{"sourcePosition": {"fileName": "firestore.rules", "line": t["line"]}, "value": {"boolValue": t["result"]}}
                                 for t in r.get("trace", [])]
    return out


def evaluate_security_rules_ast(ast, **kw) -> dict:
    segs = [x for x in kw["rel_path"].split("/") if x]
    method = kw["method"]
    rd = kw["resource_data"]
    res = None if rd is None and method == "create" else {
        "data": rd if rd is not None else (kw["request_resource_data"] or {}), "id": segs[-1] if segs else "",
        "__name__": _rules.Path(["databases", kw["db"], "documents"] + segs)}
    request = _rules_request(method, kw["db"], segs, kw["auth"], kw["request_resource_data"])
    return _rules.evaluate(ast, method=method, rel_path=kw["rel_path"], db=kw["db"], request=request, resource=res, fetch=kw.get("fetch"))


def _dispatch_rules_api(store, project: str, method: str, segs: list, body: bytes) -> FirestoreResponse:
    data = _load_json(body)
    head = segs[0]
    if head.endswith(":test") or head == "test":
        src = _ruleset_source({"source": data.get("source")}) if data.get("source") else None
        if src is None:
            return _err(400, "INVALID_ARGUMENT", "source is required.")
        issues = _rules.validate(src)
        if issues:
            return _json(200, {"issues": issues})
        ast = _rules.compile_rules(src)
        docs = {}
        for d in data.get("fixtures") or []:
            pass
        results = [_test_case(ast, c, docs) for c in (data.get("testSuite") or {}).get("testCases") or []]
        return _json(200, {"testResults": results})
    if head == "rulesets":
        if len(segs) == 1:
            if method == "POST":
                src = _ruleset_source(data)
                if not (data.get("source") or {}).get("files"):
                    return _err(400, "INVALID_ARGUMENT", "Ruleset.source.files is required.")
                issues = _rules.validate(src)
                if issues:
                    i = issues[0]
                    return _err(400, "INVALID_ARGUMENT", f"Invalid argument: line {i['sourcePosition']['line']}, column {i['sourcePosition']['column']}: {i['description']}")
                rid = str(uuid.uuid4())
                name = f"projects/{project}/rulesets/{rid}"
                rec = {"name": name, "createTime": _now(), "source": data["source"]}
                _rs(store)[name] = rec
                return _json(200, rec)
            if method == "GET":
                items = sorted(_rs(store).values(), key=lambda r: r["createTime"], reverse=True)
                return _json(200, {"rulesets": [{k: v for k, v in r.items() if k != "source"} for r in items
                                                if r["name"].startswith(f"projects/{project}/")]})
        elif len(segs) == 2:
            name = f"projects/{project}/rulesets/{segs[1]}"
            rec = _rs(store).get(name)
            if rec is None:
                return _err(404, "NOT_FOUND", f"Requested entity was not found. ({name})")
            if method == "GET":
                return _json(200, rec)
            if method == "DELETE":
                if any(r["rulesetName"] == name for r in _rel(store).values()):
                    return _err(400, "FAILED_PRECONDITION", "Cannot delete a ruleset that is referenced by a release.")
                _rs(store).pop(name)
                return _json(200, {})
    if head == "releases":
        rels = _rel(store)
        if len(segs) == 1:
            if method == "GET":
                return _json(200, {"releases": [r for r in sorted(rels.values(), key=lambda r: r["name"]) if r["name"].startswith(f"projects/{project}/")]})
            if method == "POST":
                rname, rsname = data.get("name"), data.get("rulesetName")
                if not rname or not rsname:
                    return _err(400, "INVALID_ARGUMENT", "name and rulesetName are required.")
                if rname in rels:
                    return _err(409, "ALREADY_EXISTS", f"Release already exists: {rname}")
                if rsname not in _rs(store):
                    return _err(404, "NOT_FOUND", f"Requested entity was not found. ({rsname})")
                if not re.match(r"^projects/[^/]+/releases/cloud\.firestore(/.+)?$", rname):
                    return _err(400, "INVALID_ARGUMENT", "Only cloud.firestore releases are supported by Vyomi.")
                now = _now()
                rels[rname] = {"name": rname, "rulesetName": rsname, "createTime": now, "updateTime": now}
                store.security_rules[_db_of_release(rname)] = _ruleset_source(_rs(store)[rsname])
                return _json(200, rels[rname])
        else:
            rname = f"projects/{project}/releases/" + "/".join(segs[1:])
            tail = segs[-1]
            if tail == "executable" and method == "GET":
                rname = f"projects/{project}/releases/" + "/".join(segs[1:-1])
                rel = rels.get(rname)
                if not rel:
                    return _err(404, "NOT_FOUND", f"Requested entity was not found. ({rname})")
                return _json(200, {"rulesetName": rel["rulesetName"], "executable": "FIRESTORE", "language": "FIRESTORE"})
            rel = rels.get(rname)
            if method == "GET":
                return _json(200, rel) if rel else _err(404, "NOT_FOUND", f"Requested entity was not found. ({rname})")
            if method == "PATCH":
                if not rel:
                    return _err(404, "NOT_FOUND", f"Requested entity was not found. ({rname})")
                new = (data.get("release") or data).get("rulesetName")
                if new not in _rs(store):
                    return _err(404, "NOT_FOUND", f"Requested entity was not found. ({new})")
                rel["rulesetName"], rel["updateTime"] = new, _now()
                store.security_rules[_db_of_release(rname)] = _ruleset_source(_rs(store)[new])
                return _json(200, rel)
            if method == "DELETE":
                if not rel:
                    return _err(404, "NOT_FOUND", f"Requested entity was not found. ({rname})")
                rels.pop(rname)
                store.security_rules.pop(_db_of_release(rname), None)
                return _json(200, {})
    return _err(400, "INVALID_ARGUMENT", f"Unsupported Firebase Rules request {method} {'/'.join(segs)}")


def _admin_dispatch(store: FirestoreStore, method: str, path: str,
                    query: dict, body: bytes, gcs_store=None) -> FirestoreResponse:
    segs = [unquote(s) for s in _admin_segs(path)]
    if len(segs) == 2 and segs[0] == "projects" and segs[1].endswith(":test"):
        return _dispatch_rules_api(store, segs[1][:-5], method, ["test"], body)
    if len(segs) < 3 or segs[0] != "projects":
        return _err(404, "NOT_FOUND", f"Unknown path: {path}")
    project = segs[1]
    if segs[2] in ("rulesets", "releases") or segs[2] == "test" or (len(segs) == 3 and segs[2].endswith(":test")):
        return _dispatch_rules_api(store, project, method, segs[2:], body)
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


_KEY_VISUALIZER_BUCKETS = 8


def _dispatch_database_item(store: FirestoreStore, project: str, dbid: str, suffix: str,
                            method: str, query: dict, body: bytes, gcs_store=None) -> FirestoreResponse:
    if suffix in ("exportDocuments", "importDocuments"):
        if dbid not in store.databases:
            return _err(404, "NOT_FOUND", f"Database does not exist: {dbid}")
        return _dispatch_export_import(store, project, dbid, suffix, body, gcs_store)
    if suffix in ("getSecurityRules", "updateSecurityRules", "testSecurityRules"):
        if suffix == "getSecurityRules":
            return _json(200, {"rules": store.security_rules.get(dbid, "")})
        if suffix == "updateSecurityRules":
            data = _load_json(body)
            src = data.get("rules", "")
            issues = _rules.validate(src) if src else []
            if issues:
                return _err(400, "INVALID_ARGUMENT", "Rules failed validation: " + "; ".join(
                    f"L{i['sourcePosition']['line']}:{i['sourcePosition']['column']} {i['description']}" for i in issues))
            _publish_rules(store, project, dbid, src)
            return _json(200, {"rules": store.security_rules[dbid]})
        data = _load_json(body)
        rules_src = data.get("rules")
        if rules_src is None:
            rules_src = store.security_rules.get(dbid, "")
        req = data.get("request") or {}
        result = evaluate_security_rules(
            rules_src, method=req.get("method", "get"), db=dbid,
            rel_path=str(req.get("path", "")).strip("/"), auth=req.get("auth"),
            resource_data=req.get("resourceData"), request_resource_data=req.get("requestResourceData"))
        return _json(200, result)
    if suffix == "usage":
        if dbid not in store.databases:
            return _err(404, "NOT_FOUND", f"Database does not exist: {dbid}")
        u = store.usage.get(dbid, {"reads": 0, "writes": 0, "deletes": 0})
        prefix = f"{dbid}/"
        doc_count = sum(1 for k in store.documents if k.startswith(prefix))
        storage_bytes = sum(len(json.dumps(e.get("fields", {}))) for k, e in store.documents.items()
                            if k.startswith(prefix))
        return _json(200, {"documentCount": doc_count, "storageBytes": storage_bytes, **u})
    if suffix == "insights":
        if dbid not in store.databases:
            return _err(404, "NOT_FOUND", f"Database does not exist: {dbid}")
        recs = sorted(store.index_recommendations.get(dbid, {}).values(), key=lambda r: -r["occurrences"])
        used_ids = set(store.index_usage.get(dbid, {}).keys())
        unused = [{"indexId": iid, "collectionGroup": idx["collectionGroup"],
                   "fields": [f.get("fieldPath") for f in idx.get("fields") or []]}
                  for iid, idx in store.indexes.get(dbid, {}).items() if iid not in used_ids]
        return _json(200, {
            "indexRecommendations": recs,
            "unusedIndexes": sorted(unused, key=lambda u: u["indexId"]),
            "totalQueries": store.query_count.get(dbid, 0),
            "queriesMissingIndex": sum(r["occurrences"] for r in recs),
        })
    if suffix == "keyVisualizer":
        if dbid not in store.databases:
            return _err(404, "NOT_FOUND", f"Database does not exist: {dbid}")
        ka = store.key_access.get(dbid, {})
        groups: dict[str, list[int]] = {}
        for rel, count in ka.items():
            segs = rel.split("/")
            group = "/".join(segs[:-1]) if len(segs) > 1 else rel
            bucket = int(hashlib.md5(rel.encode()).hexdigest(), 16) % _KEY_VISUALIZER_BUCKETS
            row = groups.setdefault(group, [0] * _KEY_VISUALIZER_BUCKETS)
            row[bucket] += count
        rows = sorted(({"collection": g, "buckets": b, "total": sum(b)} for g, b in groups.items()),
                      key=lambda r: -r["total"])
        hottest = sorted(ka.items(), key=lambda kv: -kv[1])[:10]
        return _json(200, {"rows": rows, "hottestKeys": [{"key": rel, "count": n} for rel, n in hottest]})

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
        store.index_recommendations.pop(dbid, None)
        store.index_usage.pop(dbid, None)
        store.query_count.pop(dbid, None)
        store.key_access.pop(dbid, None)
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
