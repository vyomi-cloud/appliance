"""GCP BigQuery core — substrate-independent. Speaks the native **BigQuery REST API v2**
(`/bigquery/v2/projects/{p}/...`) so `google-cloud-bigquery` (Java/Go/Python) and the
`bq` / `gcloud` tools work unchanged against it (point the client's endpoint at the core).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, and the
very same file runs in the offline appliance and in Nano. SQL runs in-process on the
stdlib `sqlite3` engine (a small GoogleSQL → SQLite translation; see ``_translate``):
no container, no extra dependency.

Resources (the Discovery doc `bigquery/v2`):
  projects                         list · getServiceAccount
  datasets                         insert · get · list · patch · update · delete
  tables                           insert · get · list · patch · update · delete
                                   getIamPolicy · setIamPolicy · testIamPermissions
  tabledata                        insertAll · list
  jobs                             insert (query / copy) · get · list · query ·
                                   getQueryResults · cancel · delete
  routines                         insert · get · list · update · delete
  models                           list · get · delete

Query jobs complete synchronously (state DONE) exactly like a fast real query, so the
SDKs' `waitFor()` / `Read()` return at once. Errors use the native
{"error":{"code","message","errors":[{message,domain,reason}],"status"}} body.

State is plain JSON-safe dicts (``BigQueryStore``) so nano_persist and the offline
space slot can snapshot them; tables hold their rows natively.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

DEFAULT_LOCATION = "US"
LOCATIONS = ("US", "EU", "asia-northeast1", "asia-southeast1", "europe-west1", "europe-west2",
             "europe-west4", "us-central1", "us-east1", "us-east4", "us-west1")
_ID_DS = re.compile(r"^[A-Za-z0-9_]{1,1024}$")
_ID_TBL = re.compile(r"^[\w\- -￿ ]{1,1024}$")
_TYPE_ALIAS = {"INT64": "INTEGER", "INT": "INTEGER", "SMALLINT": "INTEGER", "BIGINT": "INTEGER",
               "TINYINT": "INTEGER", "BYTEINT": "INTEGER", "FLOAT64": "FLOAT", "BOOL": "BOOLEAN",
               "STRUCT": "RECORD", "DECIMAL": "NUMERIC", "BIGDECIMAL": "BIGNUMERIC"}
_TYPES = ("STRING", "BYTES", "INTEGER", "FLOAT", "NUMERIC", "BIGNUMERIC", "BOOLEAN", "TIMESTAMP",
          "DATE", "TIME", "DATETIME", "GEOGRAPHY", "JSON", "RECORD", "INTERVAL", "RANGE")
_MODES = ("NULLABLE", "REQUIRED", "REPEATED")
_SQLITE_AFFINITY = {"INTEGER": "INTEGER", "FLOAT": "REAL", "BOOLEAN": "INTEGER", "NUMERIC": "NUMERIC",
                    "BIGNUMERIC": "NUMERIC", "BYTES": "BLOB"}


@dataclass
class GcpResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class BigQueryStore:
    """Plain, JSON-safe state: datasets (each holding its tables / routines), jobs, IAM."""

    def __init__(self) -> None:
        self.datasets: dict[str, dict] = {}     # "project:dataset" -> dataset record
        self.jobs: dict[str, dict] = {}         # "project:jobId"   -> job record
        self.iam: dict[str, dict] = {}          # table / dataset id -> IAM policy

    def persist(self) -> None:
        """Hook: the offline appliance flushes the space slot, Nano snapshots to IDB."""


class BqError(Exception):
    def __init__(self, status: int, message: str, reason: str, token: str | None = None):
        super().__init__(message)
        self.status, self.message, self.reason, self.token = status, message, reason, token


# ── primitives ────────────────────────────────────────────────────────────
def _now_ms() -> str:
    return str(int(datetime.now(timezone.utc).timestamp() * 1000))


def _iso(ms: str | int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(status: int, obj: dict) -> GcpResponse:
    return GcpResponse(status=status, body=json.dumps(obj).encode())


_STATUS_TOKEN = {400: "INVALID_ARGUMENT", 403: "PERMISSION_DENIED", 404: "NOT_FOUND",
                 409: "ALREADY_EXISTS", 412: "FAILED_PRECONDITION", 501: "UNIMPLEMENTED", 500: "INTERNAL"}


def _err(status: int, message: str, reason: str = "invalid", token: str | None = None) -> GcpResponse:
    return _json(status, {"error": {"code": status, "message": message,
                                    "errors": [{"message": message, "domain": "global", "reason": reason}],
                                    "status": token or _STATUS_TOKEN.get(status, "UNKNOWN")}})


def _etag(obj) -> str:
    return hashlib.md5(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:22]


def _page(items: list, query: dict) -> tuple[list, str]:
    """Offset pagination with the real maxResults / pageToken / nextPageToken contract."""
    try:
        size = int(query.get("maxResults") or 0) or 1000
    except (TypeError, ValueError):
        size = 1000
    try:
        start = int(query.get("pageToken") or query.get("startIndex") or 0)
    except (TypeError, ValueError):
        start = 0
    chunk = items[start:start + size]
    return chunk, (str(start + size) if start + size < len(items) else "")


def _human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    f = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        f /= 1024
        if f < 1024 or unit == "TB":
            return f"{f:.1f} {unit}"
    return f"{n} B"


# ── schema + value handling ───────────────────────────────────────────────
def _norm_type(t: str) -> str:
    t = str(t or "STRING").upper()
    return _TYPE_ALIAS.get(t, t)


def _norm_fields(fields, path="") -> list:
    if not isinstance(fields, list) or not fields:
        raise BqError(400, "Schema must have at least one field.", "invalid")
    out, seen = [], set()
    for f in fields:
        name = str((f or {}).get("name") or "")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,299}$", name):
            raise BqError(400, f"Invalid field name \"{name}\". Fields must contain only letters, numbers, "
                               "and underscores, start with a letter or underscore, and be at most 300 characters long.",
                          "invalid")
        if name.lower() in seen:
            raise BqError(400, f"Field {name} already exists in schema", "invalid")
        seen.add(name.lower())
        ftype = _norm_type(f.get("type"))
        if ftype not in _TYPES:
            raise BqError(400, f"Invalid value for type: {f.get('type')} is not a valid value", "invalid")
        mode = str(f.get("mode") or "NULLABLE").upper()
        if mode not in _MODES:
            raise BqError(400, f"Invalid value for mode: {f.get('mode')} is not a valid value", "invalid")
        nf = {"name": name, "type": ftype, "mode": mode}
        if f.get("description"):
            nf["description"] = f["description"]
        if ftype == "RECORD":
            nf["fields"] = _norm_fields(f.get("fields"), path + name + ".")
        out.append(nf)
    return out


def _parse_ts(v) -> str:
    """Any accepted TIMESTAMP spelling → canonical 'YYYY-MM-DD HH:MM:SS[.ffffff] UTC'."""
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?([eE][+-]?\d+)?", v.strip())):
        d = datetime.fromtimestamp(float(v), timezone.utc)
    else:
        s = str(v).strip().replace(" UTC", "Z").replace("T", " ")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            d = datetime.fromisoformat(s)
        except ValueError:
            raise BqError(400, f"Could not parse '{v}' as a timestamp", "invalid")
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        d = d.astimezone(timezone.utc)
    frac = f".{d.microsecond:06d}" if d.microsecond else ""
    return d.strftime("%Y-%m-%d %H:%M:%S") + frac + " UTC"


def _coerce(field_: dict, v):
    """Wire / JSON value → stored native value, validated against the field."""
    if v is None:
        return None
    t = field_["type"]
    try:
        if field_["mode"] == "REPEATED":
            if not isinstance(v, list):
                raise ValueError("expected array")
            return [_coerce({**field_, "mode": "NULLABLE"}, x) for x in v]
        if t == "INTEGER":
            if isinstance(v, bool):
                raise ValueError("bool")
            return int(v) if not isinstance(v, float) or v == int(v) else (_ for _ in ()).throw(ValueError("float"))
        if t == "FLOAT":
            return float(v)
        if t == "BOOLEAN":
            if isinstance(v, str):
                if v.lower() in ("true", "t", "1", "yes", "y"):
                    return True
                if v.lower() in ("false", "f", "0", "no", "n"):
                    return False
                raise ValueError(v)
            return bool(v)
        if t == "TIMESTAMP":
            return _parse_ts(v)
        if t == "RECORD":
            if not isinstance(v, dict):
                raise ValueError("expected object")
            return _coerce_row(field_["fields"], v)
        if t in ("NUMERIC", "BIGNUMERIC"):
            return str(v)
        if isinstance(v, (dict, list)):
            return json.dumps(v)
        return str(v)
    except BqError:
        raise
    except (ValueError, TypeError):
        raise BqError(400, f"Cannot convert value to {t.lower()} (bad value): {v}", "invalid")


def _coerce_row(fields: list, row: dict) -> dict:
    names = {f["name"].lower(): f for f in fields}
    out = {}
    for k in row:
        if k.lower() not in names:
            raise BqError(400, f"no such field: {k}.", "invalid")
    for f in fields:
        raw = next((row[k] for k in row if k.lower() == f["name"].lower()), None)
        val = _coerce(f, raw)
        if val is None and f["mode"] == "REQUIRED":
            raise BqError(400, f"Missing required field: {f['name']}.", "invalid")
        out[f["name"]] = val
    return out


def _wire_value(f: dict, v):
    """Stored native value → the `{"v": …}` cell BigQuery sends."""
    if v is None:
        return {"v": None}
    if f["mode"] == "REPEATED":
        return {"v": [_wire_value({**f, "mode": "NULLABLE"}, x) for x in v]}
    t = f["type"]
    if t == "RECORD":
        return {"v": {"f": [_wire_value(sf, v.get(sf["name"])) for sf in f["fields"]]}}
    if t == "BOOLEAN":
        return {"v": "true" if v else "false"}
    if t == "TIMESTAMP":
        d = datetime.strptime(v[:-4], "%Y-%m-%d %H:%M:%S.%f" if "." in v else "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return {"v": repr(d.timestamp())}
    return {"v": str(v)}


def _wire_rows(fields: list, rows: list) -> list:
    return [{"f": [_wire_value(f, r.get(f["name"])) for f in fields]} for r in rows]


def _row_bytes(r: dict) -> int:
    return len(json.dumps(r, default=str)) if r else 0


# ── names / references ────────────────────────────────────────────────────
def _dkey(project: str, dsid: str) -> str:
    return f"{project}:{dsid}"


def _get_ds(store: BigQueryStore, project: str, dsid: str) -> dict:
    ds = store.datasets.get(_dkey(project, dsid))
    if ds is None:
        raise BqError(404, f"Not found: Dataset {project}:{dsid}", "notFound", "NOT_FOUND")
    return ds


def _get_tbl(store: BigQueryStore, project: str, dsid: str, tid: str) -> dict:
    t = _get_ds(store, project, dsid)["tables"].get(tid)
    if t is None:
        raise BqError(404, f"Not found: Table {project}:{dsid}.{tid}", "notFound", "NOT_FOUND")
    return t


# ── views ─────────────────────────────────────────────────────────────────
def _ds_ref(ds: dict) -> dict:
    return {"projectId": ds["project"], "datasetId": ds["id"]}


def _ds_view(ds: dict) -> dict:
    out = {"kind": "bigquery#dataset", "etag": _etag([ds["id"], ds["lastModifiedTime"]]),
           "id": f"{ds['project']}:{ds['id']}",
           "selfLink": f"https://bigquery.googleapis.com/bigquery/v2/projects/{ds['project']}/datasets/{ds['id']}",
           "datasetReference": _ds_ref(ds), "access": ds.get("access") or _default_access(),
           "creationTime": ds["creationTime"], "lastModifiedTime": ds["lastModifiedTime"],
           "location": ds["location"], "type": "DEFAULT"}
    for k in ("description", "friendlyName", "labels", "defaultTableExpirationMs",
              "defaultPartitionExpirationMs", "defaultEncryptionConfiguration", "storageBillingModel",
              "maxTimeTravelHours", "isCaseInsensitive"):
        if ds.get(k) not in (None, "", {}, []):
            out[k] = ds[k]
    return out


def _default_access() -> list:
    return [{"role": "WRITER", "specialGroup": "projectWriters"}, {"role": "OWNER", "specialGroup": "projectOwners"},
            {"role": "OWNER", "userByEmail": "owner@vyomi.local"}, {"role": "READER", "specialGroup": "projectReaders"}]


def _tbl_ref(t: dict) -> dict:
    return {"projectId": t["project"], "datasetId": t["dataset"], "tableId": t["id"]}


def _tbl_bytes(t: dict) -> int:
    return sum(_row_bytes(r) for r in t.get("rows", []))


def _tbl_view(t: dict, full: bool = True) -> dict:
    out = {"kind": "bigquery#table", "etag": _etag([t["id"], t["lastModifiedTime"]]),
           "id": f"{t['project']}:{t['dataset']}.{t['id']}",
           "selfLink": f"https://bigquery.googleapis.com/bigquery/v2/projects/{t['project']}/datasets/{t['dataset']}/tables/{t['id']}",
           "tableReference": _tbl_ref(t), "type": t["type"], "creationTime": t["creationTime"],
           "lastModifiedTime": t["lastModifiedTime"], "location": t.get("location", DEFAULT_LOCATION)}
    if not full:
        if t.get("labels"):
            out["labels"] = t["labels"]
        return out
    out["schema"] = {"fields": t["schema"]}
    if t["type"] == "TABLE":
        out.update({"numBytes": str(_tbl_bytes(t)), "numLongTermBytes": "0", "numRows": str(len(t["rows"])),
                    "numActiveLogicalBytes": str(_tbl_bytes(t)), "numTotalLogicalBytes": str(_tbl_bytes(t))})
    else:
        out.update({"numBytes": "0", "numRows": "0"})
    for k in ("description", "friendlyName", "labels", "expirationTime", "view", "timePartitioning",
              "rangePartitioning", "clustering", "encryptionConfiguration", "requirePartitionFilter"):
        if t.get(k) not in (None, "", {}, []):
            out[k] = t[k]
    return out


def _routine_view(r: dict) -> dict:
    out = {k: r[k] for k in ("routineReference", "routineType", "language", "definitionBody", "creationTime",
                              "lastModifiedTime", "arguments", "returnType", "description", "determinismLevel",
                              "importedLibraries") if r.get(k) not in (None, "", [])}
    out["etag"] = _etag([r["routineReference"], r["lastModifiedTime"]])
    return out


def _job_view(j: dict) -> dict:
    return {k: v for k, v in j.items() if not k.startswith("_")}


def _check_id(rx, value: str, what: str) -> None:
    if not rx.match(value or ""):
        raise BqError(400, f"Invalid {what}: \"{value}\". {what.capitalize()}s must contain only letters, numbers, "
                           "and underscores" + ("." if what == "dataset ID" else " (tables may also use hyphens)."), "invalid")


# ── datasets ──────────────────────────────────────────────────────────────
_DS_MUTABLE = ("description", "friendlyName", "labels", "defaultTableExpirationMs", "defaultPartitionExpirationMs",
               "defaultEncryptionConfiguration", "access", "storageBillingModel", "maxTimeTravelHours")


def _insert_dataset(store, project, query, body) -> GcpResponse:
    ref = body.get("datasetReference") or {}
    dsid = ref.get("datasetId") or ""
    if ref.get("projectId") and ref["projectId"] != project:
        raise BqError(400, f"Project id in datasetReference ({ref['projectId']}) does not match the request project ({project}).", "invalid")
    if not dsid:
        raise BqError(400, "Dataset ID must be specified in datasetReference.datasetId.", "invalid")
    _check_id(_ID_DS, dsid, "dataset ID")
    if _dkey(project, dsid) in store.datasets:
        raise BqError(409, f"Already Exists: Dataset {project}:{dsid}", "duplicate", "ALREADY_EXISTS")
    loc = body.get("location") or DEFAULT_LOCATION
    now = _now_ms()
    ds = {"id": dsid, "project": project, "location": loc, "creationTime": now, "lastModifiedTime": now,
          "tables": {}, "routines": {}}
    for k in _DS_MUTABLE:
        if body.get(k) is not None:
            ds[k] = body[k]
    store.datasets[_dkey(project, dsid)] = ds
    store.persist()
    return _json(200, _ds_view(ds))


def _list_datasets(store, project, query) -> GcpResponse:
    items = []
    for _, ds in sorted(store.datasets.items()):
        if ds["project"] != project:
            continue
        flt = query.get("filter") or ""
        if flt.startswith("labels."):
            k, _, v = flt[7:].partition(":")
            if (ds.get("labels") or {}).get(k) != v:
                continue
        item = {"kind": "bigquery#dataset", "id": f"{project}:{ds['id']}", "datasetReference": _ds_ref(ds),
                "location": ds["location"]}
        if ds.get("labels"):
            item["labels"] = ds["labels"]
        if ds.get("friendlyName"):
            item["friendlyName"] = ds["friendlyName"]
        items.append(item)
    chunk, nxt = _page(items, query)
    out = {"kind": "bigquery#datasetList", "etag": _etag([i["id"] for i in items])}
    if nxt:
        out["nextPageToken"] = nxt
    if chunk:
        out["datasets"] = chunk
    return _json(200, out)


def _patch_dataset(store, project, dsid, body, replace=False) -> GcpResponse:
    ds = _get_ds(store, project, dsid)
    for k in _DS_MUTABLE:
        if k in body:
            if body[k] is None:
                ds.pop(k, None)
            else:
                ds[k] = body[k]
        elif replace:
            ds.pop(k, None)
    ds["lastModifiedTime"] = _now_ms()
    store.persist()
    return _json(200, _ds_view(ds))


def _delete_dataset(store, project, dsid, query) -> GcpResponse:
    ds = _get_ds(store, project, dsid)
    contents = str(query.get("deleteContents", "false")).lower() == "true"
    if (ds["tables"] or ds["routines"]) and not contents:
        raise BqError(400, f"Dataset {project}:{dsid} is still in use", "resourceInUse")
    store.datasets.pop(_dkey(project, dsid))
    for k in [k for k in store.iam if k.startswith(f"{project}:{dsid}")]:
        store.iam.pop(k)
    store.persist()
    return GcpResponse(status=204, body=b"", media_type=None)


# ── tables ────────────────────────────────────────────────────────────────
_TBL_MUTABLE = ("description", "friendlyName", "labels", "expirationTime", "timePartitioning", "clustering",
                "rangePartitioning", "encryptionConfiguration", "requirePartitionFilter")


def _new_table(project, dsid, tid, body) -> dict:
    now = _now_ms()
    t = {"id": tid, "project": project, "dataset": dsid, "type": "TABLE", "creationTime": now,
         "lastModifiedTime": now, "rows": [], "location": DEFAULT_LOCATION}
    if body.get("view"):
        q = (body["view"] or {}).get("query")
        if not q:
            raise BqError(400, "Query must be specified for view.", "invalid")
        t["type"], t["view"] = "VIEW", {"query": q, "useLegacySql": bool((body["view"] or {}).get("useLegacySql", False))}
        t["schema"] = _norm_fields(body["schema"]["fields"]) if (body.get("schema") or {}).get("fields") else []
    else:
        t["schema"] = _norm_fields((body.get("schema") or {}).get("fields"))
    for k in _TBL_MUTABLE:
        if body.get(k) is not None:
            t[k] = body[k]
    return t


def _insert_table(store, project, dsid, body) -> GcpResponse:
    ds = _get_ds(store, project, dsid)
    ref = body.get("tableReference") or {}
    tid = ref.get("tableId") or ""
    if not tid:
        raise BqError(400, "Table ID must be specified in tableReference.tableId.", "invalid")
    _check_id(_ID_TBL, tid, "table ID")
    if tid in ds["tables"]:
        raise BqError(409, f"Already Exists: Table {project}:{dsid}.{tid}", "duplicate", "ALREADY_EXISTS")
    t = _new_table(project, dsid, tid, body)
    t["location"] = ds["location"]
    exp = ds.get("defaultTableExpirationMs")
    if exp and "expirationTime" not in t:
        t["expirationTime"] = str(int(t["creationTime"]) + int(exp))
    ds["tables"][tid] = t
    store.persist()
    return _json(200, _tbl_view(t))


def _list_tables(store, project, dsid, query) -> GcpResponse:
    ds = _get_ds(store, project, dsid)
    items = [{"kind": "bigquery#table", "id": f"{project}:{dsid}.{t['id']}", "tableReference": _tbl_ref(t),
              "type": t["type"], "creationTime": t["creationTime"],
              **({"labels": t["labels"]} if t.get("labels") else {})}
             for _, t in sorted(ds["tables"].items())]
    chunk, nxt = _page(items, query)
    out = {"kind": "bigquery#tableList", "etag": _etag([i["id"] for i in items]), "totalItems": len(items)}
    if nxt:
        out["nextPageToken"] = nxt
    if chunk:
        out["tables"] = chunk
    return _json(200, out)


def _patch_table(store, project, dsid, tid, body, replace=False) -> GcpResponse:
    t = _get_tbl(store, project, dsid, tid)
    if "schema" in body and body["schema"] and body["schema"].get("fields"):
        new = _norm_fields(body["schema"]["fields"])
        old = {f["name"]: f for f in t["schema"]}
        for f in new:   # schema updates may only add NULLABLE columns (BigQuery rule)
            if f["name"] not in old and f["mode"] == "REQUIRED" and t["rows"]:
                raise BqError(400, f"Provided Schema does not match Table {project}:{dsid}.{tid}. "
                                   f"Cannot add required field {f['name']}.", "invalid")
        for r in t["rows"]:
            for f in new:
                r.setdefault(f["name"], None)
        t["schema"] = new
    if "view" in body and t["type"] == "VIEW" and body["view"]:
        t["view"] = {"query": body["view"].get("query", t["view"]["query"]), "useLegacySql": False}
    for k in _TBL_MUTABLE:
        if k in body:
            if body[k] is None:
                t.pop(k, None)
            else:
                t[k] = body[k]
        elif replace:
            t.pop(k, None)
    t["lastModifiedTime"] = _now_ms()
    store.persist()
    return _json(200, _tbl_view(t))


def _delete_table(store, project, dsid, tid) -> GcpResponse:
    ds = _get_ds(store, project, dsid)
    if tid not in ds["tables"]:
        raise BqError(404, f"Not found: Table {project}:{dsid}.{tid}", "notFound", "NOT_FOUND")
    del ds["tables"][tid]
    store.iam.pop(f"{project}:{dsid}.{tid}", None)
    store.persist()
    return GcpResponse(status=204, body=b"", media_type=None)


def _tbl_iam(store, project, dsid, tid, verb, body) -> GcpResponse:
    _get_tbl(store, project, dsid, tid)
    key = f"{project}:{dsid}.{tid}"
    if verb == "getIamPolicy":
        return _json(200, store.iam.get(key) or {"version": 1, "etag": "ACAB"})
    if verb == "setIamPolicy":
        pol = dict(body.get("policy") or {})
        pol.setdefault("version", 1)
        pol["etag"] = _etag(pol.get("bindings", []))[:8]
        store.iam[key] = pol
        store.persist()
        return _json(200, pol)
    return _json(200, {"permissions": body.get("permissions", [])})


# ── table data ────────────────────────────────────────────────────────────
def _insert_all(store, project, dsid, tid, body) -> GcpResponse:
    t = _get_tbl(store, project, dsid, tid)
    if t["type"] != "TABLE":
        raise BqError(400, f"Cannot insert into {t['type'].lower()} {project}:{dsid}.{tid}", "invalid")
    rows = body.get("rows")
    if not isinstance(rows, list) or not rows:
        raise BqError(400, "No rows present in the request.", "invalid")
    errors, staged = [], []
    for i, r in enumerate(rows):
        try:
            staged.append(_coerce_row(t["schema"], (r or {}).get("json") or {}))
        except BqError as e:
            if body.get("skipInvalidRows"):
                errors.append({"index": i, "errors": [{"reason": "invalid", "location": "", "message": e.message}]})
            else:
                errors.append({"index": i, "errors": [{"reason": "invalid", "location": "", "message": e.message}]})
                errors.extend({"index": j, "errors": [{"reason": "stopped", "location": "", "message": ""}]}
                              for j in range(len(rows)) if j != i)
                staged = []
                break
    t["rows"].extend(staged)
    t["lastModifiedTime"] = _now_ms()
    store.persist()
    out = {"kind": "bigquery#tableDataInsertAllResponse"}
    if errors:
        out["insertErrors"] = sorted(errors, key=lambda e: e["index"])
    return _json(200, out)


def _list_data(store, project, dsid, tid, query) -> GcpResponse:
    t = _get_tbl(store, project, dsid, tid)
    rows = t["rows"]
    try:
        start = int(query.get("startIndex") or 0)
    except ValueError:
        start = 0
    if query.get("pageToken"):
        start = int(query["pageToken"])
    try:
        size = int(query.get("maxResults") or 0) or len(rows) or 1
    except ValueError:
        size = 1000
    chunk = rows[start:start + size]
    out = {"kind": "bigquery#tableDataList", "etag": _etag([t["id"], len(rows)]), "totalRows": str(len(rows))}
    if start + size < len(rows):
        out["pageToken"] = str(start + size)
    if chunk:
        out["rows"] = _wire_rows(t["schema"], chunk)
    return _json(200, out)


# ── SQL (GoogleSQL → SQLite) ──────────────────────────────────────────────
_TABLE_KW = re.compile(r"(?i)\b(FROM|JOIN|INTO|UPDATE|TABLE|VIEW|EXISTS)\b(\s+)(`[^`]+`|[A-Za-z_][\w\-]*(?:\.[\w\-]+){0,2})")
_NO_ALIAS_NEXT = {"WHERE", "GROUP", "ORDER", "LIMIT", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "ON",
                  "USING", "UNION", "INTERSECT", "EXCEPT", "HAVING", "SET", "VALUES", "SELECT", "OFFSET", "WINDOW",
                  "QUALIFY", "AS", "TABLESAMPLE", "FOR"}
_TYPE_WORDS = {"INT64": "INTEGER", "FLOAT64": "REAL", "STRING": "TEXT", "BOOL": "INTEGER", "BYTES": "BLOB",
               "TIMESTAMP": "TEXT", "DATETIME": "TEXT", "DATE": "TEXT", "TIME": "TEXT"}


def _mask_strings(sql: str) -> tuple[str, list]:
    lits: list = []

    def rep(m):
        lits.append(m.group(0))
        return f"\x00{len(lits) - 1}\x00"
    # '…' and "…" literals (GoogleSQL allows both); backtick identifiers are left alone.
    return re.sub(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.)*\"", rep, sql), lits


def _unmask(sql: str, lits: list) -> str:
    def rep(m):
        s = lits[int(m.group(1))]
        if s[0] == '"':          # GoogleSQL "text" is a string literal; SQLite wants '…'
            s = "'" + s[1:-1].replace("'", "''") + "'"
        return s
    return re.sub(r"\x00(\d+)\x00", rep, sql)


def _split_statements(sql: str) -> list:
    masked, lits = _mask_strings(re.sub(r"--[^\n]*|#[^\n]*|/\*.*?\*/", " ", sql, flags=re.S))
    return [_unmask(s, lits).strip() for s in masked.split(";") if s.strip()]


class _Ctx:
    """One statement's execution context: an in-memory SQLite DB loaded with the tables it touches."""

    def __init__(self, store, project, default_ds):
        self.store, self.project, self.default_ds = store, project, default_ds
        self.db = sqlite3.connect(":memory:")
        self.db.create_function("SAFE_DIVIDE", 2, lambda a, b: None if not b or a is None else a / b)
        self.db.create_function("CONCAT", -1, lambda *a: None if any(x is None for x in a) else "".join(str(x) for x in a))
        self.db.create_function("STARTS_WITH", 2, lambda a, b: None if a is None or b is None else int(str(a).startswith(str(b))))
        self.db.create_function("ENDS_WITH", 2, lambda a, b: None if a is None or b is None else int(str(a).endswith(str(b))))
        self.db.create_function("REGEXP_CONTAINS", 2, lambda a, p: None if a is None else int(re.search(p, str(a)) is not None))
        self.db.create_function("GENERATE_UUID", 0, lambda: str(uuid.uuid4()))
        self.db.create_function("ARRAY_LENGTH", 1, lambda a: None if a is None else len(json.loads(a)))

        class CountIf:
            def __init__(self): self.n = 0
            def step(self, v): self.n += 1 if v else 0
            def finalize(self): return self.n
        self.db.create_aggregate("COUNTIF", 1, CountIf)
        self.loaded: dict[tuple, str] = {}       # (project, dataset, table) -> sqlite name
        self.tables: dict[str, dict] = {}        # sqlite name -> table record
        self.touched: set = set()
        self.bytes = 0

    def ref(self, text: str) -> tuple:
        parts = [p for p in text.strip("`").split(".") if p]
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
        if len(parts) == 2:
            return self.project, parts[0], parts[1]
        if not self.default_ds:
            raise BqError(400, f"Table \"{parts[0]}\" must be qualified with a dataset (e.g. dataset.table).", "invalidQuery")
        return self.project, self.default_ds, parts[0]

    def load(self, key: tuple, depth: int = 0) -> str:
        if key in self.loaded:
            return self.loaded[key]
        p, d, t = key
        ds = self.store.datasets.get(_dkey(p, d))
        if ds is None:
            raise BqError(404, f"Not found: Dataset {p}:{d}", "notFound", "NOT_FOUND")
        tbl = ds["tables"].get(t)
        if tbl is None:
            raise BqError(404, f"Not found: Table {p}:{d}.{t}", "notFound", "NOT_FOUND")
        name = f"bq_{len(self.loaded)}"
        self.loaded[key] = name
        self.tables[name] = tbl
        self.touched.add(key)
        if tbl["type"] == "VIEW":
            if depth > 5:
                raise BqError(400, "View nesting too deep", "invalidQuery")
            inner = _translate(self, tbl["view"]["query"], depth + 1, view_ds=d, view_project=p)
            self.db.execute(f'CREATE VIEW "{name}" AS {inner}')
            return name
        cols = ", ".join(f'"{f["name"]}" {_SQLITE_AFFINITY.get(f["type"], "TEXT")}' for f in tbl["schema"])
        self.db.execute(f'CREATE TABLE "{name}" ({cols})')
        names = [f["name"] for f in tbl["schema"]]
        self.db.executemany(
            f'INSERT INTO "{name}" VALUES ({",".join("?" * len(names))})',
            [[_to_sqlite(r.get(n)) for n in names] for r in tbl["rows"]])
        self.bytes += _tbl_bytes(tbl)
        return name

    def dump(self, key: tuple) -> None:
        """Write a (DML-modified) SQLite table back into the store."""
        name, tbl = self.loaded[key], self.tables[self.loaded[key]]
        if tbl["type"] != "TABLE":
            return
        fields = tbl["schema"]
        cur = self.db.execute(f'SELECT {",".join(chr(34) + f["name"] + chr(34) for f in fields)} FROM "{name}"')
        rows = []
        for rec in cur.fetchall():
            row = {}
            for f, v in zip(fields, rec):
                if v is not None:
                    if f["type"] == "BOOLEAN":
                        v = bool(v)
                    elif f["type"] == "INTEGER":
                        v = int(v)
                    elif f["type"] == "FLOAT":
                        v = float(v)
                    elif f["type"] == "RECORD" or f["mode"] == "REPEATED":
                        v = json.loads(v) if isinstance(v, str) else v
                    elif f["type"] == "TIMESTAMP":
                        v = _parse_ts(v)
                    elif f["type"] in ("NUMERIC", "BIGNUMERIC"):
                        v = str(v)
                    else:
                        v = str(v)
                row[f["name"]] = v
            rows.append(row)
        tbl["rows"] = rows
        tbl["lastModifiedTime"] = _now_ms()


def _to_sqlite(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return v


def _translate(ctx: _Ctx, sql: str, depth: int = 0, view_ds=None, view_project=None, dml: bool = False) -> str:
    sql = re.sub(r"--[^\n]*|#[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip().rstrip(";")
    masked, lits = _mask_strings(sql)
    saved = (ctx.default_ds, ctx.project)
    if view_ds:
        ctx.default_ds, ctx.project = view_ds, view_project

    def table(m):
        kw, ws, target = m.group(1), m.group(2), m.group(3)
        if kw.upper() == "EXISTS" and not target.startswith("`") and "." not in target:
            return m.group(0)
        tail = masked[m.end():].lstrip()
        if tail.startswith("(") and kw.upper() in ("FROM", "JOIN"):
            return m.group(0)         # a function call such as UNNEST(...)
        key = ctx.ref(target)
        sname = ctx.load(key, depth)
        out = f'{kw}{ws}"{sname}"'
        nxt = re.match(r"[A-Za-z_]\w*", tail)
        if kw.upper() in ("FROM", "JOIN") and not dml and not (nxt and nxt.group(0).upper() not in _NO_ALIAS_NEXT):
            if not (nxt and nxt.group(0).upper() == "AS"):
                out += f' AS "{key[2]}"'
        return out
    out = _TABLE_KW.sub(table, masked)
    ctx.default_ds, ctx.project = saved
    out = out.replace("`", '"')
    out = re.sub(r"(?i)\bSAFE_CAST\s*\(", "CAST(", out)
    out = re.sub(r"(?i)\bIF\s*\(", "IIF(", out)
    out = re.sub(r"(?i)\bCURRENT_(TIMESTAMP|DATE)\s*\(\s*\)", r"CURRENT_\1", out)
    for k, v in _TYPE_WORDS.items():
        out = re.sub(rf"(?i)\bAS\s+{k}\b", f"AS {v}", out)
    out = re.sub(r"@([A-Za-z_]\w*)", r":\1", out)
    if re.search(r"(?i)\b(STRUCT|ARRAY|UNNEST)\s*[<(]|\bSELECT\s+(?:DISTINCT\s+)?\*\s+(EXCEPT|REPLACE)\b|\bMERGE\b|\bQUALIFY\b", out):
        raise BqError(400, "Syntax error: this construct is not supported by the Vyomi BigQuery SQL engine.", "invalidQuery")
    return _unmask(out, lits)


_SQL_TYPE_RX = re.compile(r"(?i)^\s*([A-Za-z_]\w*)\s+([A-Za-z0-9_]+)(?:\s*<.*>)?(\s+NOT\s+NULL)?")


def _param_value(p: dict):
    t = ((p.get("parameterType") or {}).get("type") or "STRING").upper()
    v = (p.get("parameterValue") or {}).get("value")
    if v is None:
        return None
    t = _norm_type(t)
    if t == "INTEGER":
        return int(v)
    if t == "FLOAT":
        return float(v)
    if t == "BOOLEAN":
        return 1 if str(v).lower() == "true" else 0
    return str(v)


def _infer_schema(ctx: _Ctx, names: list, rows: list) -> list:
    known = {}
    for tbl in ctx.tables.values():
        for f in tbl["schema"]:
            known.setdefault(f["name"], f)
    fields = []
    for i, n in enumerate(names):
        t = None
        if n in known:
            t = known[n]["type"]
        if t is None:
            sample = next((r[i] for r in rows if r[i] is not None), None)
            t = ("INTEGER" if isinstance(sample, int) else "FLOAT" if isinstance(sample, float) else "STRING")
        fields.append({"name": n, "type": t, "mode": "NULLABLE"})
    return fields


def _result_rows(fields: list, rows: list) -> list:
    out = []
    for r in rows:
        d = {}
        for f, v in zip(fields, r):
            if v is not None:
                if f["type"] == "BOOLEAN":
                    v = bool(v)
                elif f["type"] == "TIMESTAMP":
                    v = _parse_ts(v)
                elif f["type"] == "FLOAT":
                    v = float(v)
                elif f["type"] == "INTEGER":
                    v = int(v)
                else:
                    v = str(v) if not isinstance(v, (int, float)) else v
            d[f["name"]] = v
        out.append(d)
    return out


def _define_table(store, project, dsid, tid, schema, rows, replace=False) -> dict:
    ds = _get_ds(store, project, dsid)
    if tid in ds["tables"] and not replace:
        raise BqError(409, f"Already Exists: Table {project}:{dsid}.{tid}", "duplicate", "ALREADY_EXISTS")
    now = _now_ms()
    prev = ds["tables"].get(tid)
    t = {"id": tid, "project": project, "dataset": dsid, "type": "TABLE", "creationTime": prev["creationTime"] if prev else now,
         "lastModifiedTime": now, "rows": rows, "schema": schema, "location": ds["location"]}
    ds["tables"][tid] = t
    return t


def _run_statement(store, project, default_ds, stmt: str, params: list | None, mode: str) -> dict:
    """Execute ONE statement. Returns {schema, rows, statementType, affected, bytes, touched, created}."""
    head = re.match(r"(?is)^\s*\(?\s*([A-Za-z]+)", stmt)
    kw = head.group(1).upper() if head else ""
    ctx = _Ctx(store, project, default_ds)
    res = {"schema": [], "rows": [], "statementType": kw, "affected": None, "bytes": 0, "touched": [], "created": None}
    named = {}
    positional = []
    for p in params or []:
        if p.get("name"):
            named[p["name"]] = _param_value(p)
        else:
            positional.append(_param_value(p))
    bind = named if named else positional

    # ---- DDL handled by the engine (identifiers resolved against the store) ----
    m = re.match(r"(?is)^CREATE\s+(?:OR\s+REPLACE\s+)?(?:SCHEMA|DATASET)\s+(IF\s+NOT\s+EXISTS\s+)?`?([\w\-.]+)`?\s*(?:OPTIONS.*)?$", stmt)
    if m:
        parts = m.group(2).split(".")
        pj, dsid = (parts[0], parts[1]) if len(parts) == 2 else (project, parts[0])
        if _dkey(pj, dsid) in store.datasets:
            if not m.group(1):
                raise BqError(409, f"Already Exists: Dataset {pj}:{dsid}", "duplicate")
        else:
            _insert_dataset(store, pj, {}, {"datasetReference": {"datasetId": dsid}})
        res["statementType"] = "CREATE_SCHEMA"
        return res
    m = re.match(r"(?is)^DROP\s+(?:SCHEMA|DATASET)\s+(IF\s+EXISTS\s+)?`?([\w\-.]+)`?\s*(CASCADE|RESTRICT)?$", stmt)
    if m:
        parts = m.group(2).split(".")
        pj, dsid = (parts[0], parts[1]) if len(parts) == 2 else (project, parts[0])
        if _dkey(pj, dsid) not in store.datasets:
            if not m.group(1):
                raise BqError(404, f"Not found: Dataset {pj}:{dsid}", "notFound")
        else:
            _delete_dataset(store, pj, dsid, {"deleteContents": "true" if (m.group(3) or "").upper() == "CASCADE" else "false"})
        res["statementType"] = "DROP_SCHEMA"
        return res
    m = re.match(r"(?is)^DROP\s+(TABLE|VIEW)\s+(IF\s+EXISTS\s+)?(`[^`]+`|[\w\-]+(?:\.[\w\-]+){0,2})\s*$", stmt)
    if m:
        pj, dsid, tid = ctx.ref(m.group(3))
        ds = store.datasets.get(_dkey(pj, dsid))
        if ds is None or tid not in ds["tables"]:
            if not m.group(2):
                raise BqError(404, f"Not found: Table {pj}:{dsid}.{tid}", "notFound")
        else:
            _delete_table(store, pj, dsid, tid)
        res["statementType"] = "DROP_" + m.group(1).upper()
        return res
    m = re.match(r"(?is)^CREATE\s+(OR\s+REPLACE\s+)?(?:TEMP\s+|TEMPORARY\s+)?(TABLE|VIEW)\s+(IF\s+NOT\s+EXISTS\s+)?"
                 r"(`[^`]+`|[\w\-]+(?:\.[\w\-]+){0,2})\s*(.*)$", stmt)
    if m:
        replace, what, ine, target, rest = bool(m.group(1)), m.group(2).upper(), bool(m.group(3)), m.group(4), m.group(5)
        pj, dsid, tid = ctx.ref(target)
        ds = _get_ds(store, pj, dsid)
        exists = tid in ds["tables"]
        res["statementType"] = f"CREATE_{what}"
        if exists and ine:
            return res
        if exists and not replace:
            raise BqError(409, f"Already Exists: Table {pj}:{dsid}.{tid}", "duplicate")
        am = re.search(r"(?is)\bAS\s+(.*)$", rest)
        body = re.sub(r"(?is)\bOPTIONS\s*\(.*?\)\s*(?=AS\b|$)", "", rest[:am.start()] if am else rest).strip() if am else rest
        if what == "VIEW":
            if not am:
                raise BqError(400, "Syntax error: expected AS in CREATE VIEW.", "invalidQuery")
            sub = _run_statement(store, pj, default_ds, am.group(1), None, "query")
            t = _define_table(store, pj, dsid, tid, sub["schema"], [], replace=True)
            t["type"], t["view"] = "VIEW", {"query": am.group(1).strip(), "useLegacySql": False}
            return res
        if am and not body.strip():
            sub = _run_statement(store, pj, default_ds, am.group(1), None, "query")
            fields = [{**f, "mode": "NULLABLE"} for f in sub["schema"]]
            _define_table(store, pj, dsid, tid, fields, _result_rows(fields, [[r.get(f["name"]) for f in fields] for r in sub["rows"]]), replace=True)
            res["created"] = (pj, dsid, tid)
            return res
        inner = body.strip()
        if not inner.startswith("("):
            raise BqError(400, "Syntax error: expected column list in CREATE TABLE.", "invalidQuery")
        depth, buf, cols = 0, "", []
        for ch in inner[1:inner.rfind(")")]:
            depth += (ch in "(<") - (ch in ")>")
            if ch == "," and depth == 0:
                cols.append(buf); buf = ""
            else:
                buf += ch
        cols.append(buf)
        fields = []
        for c in cols:
            cm = _SQL_TYPE_RX.match(c)
            if not cm:
                raise BqError(400, f"Syntax error in column definition: {c.strip()}", "invalidQuery")
            fields.append({"name": cm.group(1), "type": cm.group(2), "mode": "REQUIRED" if cm.group(3) else "NULLABLE"})
        _define_table(store, pj, dsid, tid, _norm_fields(fields), [], replace=replace)
        res["created"] = (pj, dsid, tid)
        return res

    # ---- everything else runs on SQLite ----
    if kw not in ("SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
        raise BqError(400, f"Syntax error: Unexpected keyword {kw or stmt[:20]!r}. Statement type is not supported.", "invalidQuery")
    dml = kw in ("INSERT", "UPDATE", "DELETE")
    if kw == "TRUNCATE":
        m = re.match(r"(?is)^TRUNCATE\s+TABLE\s+(\S+)$", stmt)
        if not m:
            raise BqError(400, "Syntax error in TRUNCATE TABLE.", "invalidQuery")
        pj, dsid, tid = ctx.ref(m.group(1))
        t = _get_tbl(store, pj, dsid, tid)
        res["affected"], t["rows"], res["statementType"] = len(t["rows"]), [], "TRUNCATE_TABLE"
        t["lastModifiedTime"] = _now_ms()
        return res
    sql = _translate(ctx, stmt, dml=dml)
    try:
        cur = ctx.db.execute(sql, bind)
        rows = cur.fetchall() if kw in ("SELECT", "WITH") else []
        names = [d[0] for d in (cur.description or [])]
    except sqlite3.Error as e:
        raise BqError(400, f"Syntax error: {e}", "invalidQuery")
    res["bytes"] = ctx.bytes
    res["touched"] = sorted(ctx.touched)
    if dml:
        res["affected"] = cur.rowcount
        target = re.match(r"(?is)^\s*(?:INSERT\s+(?:INTO\s+)?|UPDATE\s+|DELETE\s+(?:FROM\s+)?)(`[^`]+`|[\w\-]+(?:\.[\w\-]+){0,2})", stmt)
        if target:
            key = ctx.ref(target.group(1))
            if key in ctx.loaded:
                ctx.dump(key)
        res["statementType"] = kw
        return res
    fields = _infer_schema(ctx, names, rows)
    res["schema"] = fields
    res["rows"] = _result_rows(fields, rows)
    return res


def _run_sql(store, project, default_ds, sql, params=None, mode="query") -> dict:
    stmts = _split_statements(sql)
    if not stmts:
        raise BqError(400, "Syntax error: Unexpected end of script", "invalidQuery")
    res = None
    total = 0
    touched: set = set()
    for s in stmts:
        res = _run_statement(store, project, default_ds, s, params, mode)
        total += res["bytes"]
        touched.update(res["touched"])
    res["bytes"], res["touched"] = total, sorted(touched)
    return res


# ── jobs ──────────────────────────────────────────────────────────────────
def _job_id() -> str:
    return "job_" + uuid.uuid4().hex[:24]


def _write_destination(store, project, dest: dict, res: dict, config: dict) -> None:
    pj, dsid, tid = dest.get("projectId") or project, dest.get("datasetId"), dest.get("tableId")
    ds = _get_ds(store, pj, dsid)
    wd = (config.get("writeDisposition") or "WRITE_EMPTY").upper()
    cur = ds["tables"].get(tid)
    fields = [{**f, "mode": "NULLABLE"} for f in res["schema"]]
    if cur is None:
        if (config.get("createDisposition") or "CREATE_IF_NEEDED") == "CREATE_NEVER":
            raise BqError(404, f"Not found: Table {pj}:{dsid}.{tid}", "notFound")
        _define_table(store, pj, dsid, tid, fields, res["rows"])
    elif wd == "WRITE_APPEND":
        cur["rows"].extend(res["rows"])
        cur["lastModifiedTime"] = _now_ms()
    elif wd == "WRITE_TRUNCATE":
        _define_table(store, pj, dsid, tid, fields, res["rows"], replace=True)
    elif cur["rows"]:
        raise BqError(409, f"Already Exists: Table {pj}:{dsid}.{tid}", "duplicate")
    else:
        _define_table(store, pj, dsid, tid, fields, res["rows"], replace=True)


def _execute_query_config(store, project, q: dict, dry: bool) -> dict:
    dd = q.get("defaultDataset") or {}
    res = _run_sql(store, project, dd.get("datasetId"), q.get("query") or "", q.get("queryParameters"))
    if q.get("destinationTable") and res["statementType"] in ("SELECT", "WITH") and not dry:
        _write_destination(store, project, q["destinationTable"], res, q)
    return res


def _make_job(store, project, jid, location, config, dry=False) -> tuple[dict, dict | None]:
    now = _now_ms()
    job = {"kind": "bigquery#job", "etag": _etag([jid, now]), "id": f"{project}:{location}.{jid}",
           "selfLink": f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/jobs/{jid}?location={location}",
           "jobReference": {"projectId": project, "jobId": jid, "location": location},
           "configuration": config, "user_email": "vyomi@vyomi.local",
           "status": {"state": "DONE"}, "statistics": {"creationTime": now, "startTime": now, "endTime": now}}
    res = None
    try:
        if config.get("query"):
            res = _execute_query_config(store, project, config["query"], dry)
            job["configuration"]["jobType"] = "QUERY"
            qs = {"statementType": res["statementType"], "totalBytesProcessed": str(res["bytes"]),
                  "totalBytesBilled": str(res["bytes"]), "cacheHit": False, "billingTier": 1}
            if res["affected"] is not None:
                qs["numDmlAffectedRows"] = str(res["affected"])
            if res["schema"]:
                qs["schema"] = {"fields": res["schema"]}
            job["statistics"]["totalBytesProcessed"] = str(res["bytes"])
            job["statistics"]["query"] = qs
            q = config["query"]
            if not dry:
                dest = q.get("destinationTable")
                if not dest and res["schema"]:
                    h = hashlib.md5(jid.encode()).hexdigest()[:16]
                    dest = {"projectId": project, "datasetId": "_" + h[:8], "tableId": "anon" + h}
                    job["_anon"] = True
                if dest:
                    q["destinationTable"] = dest
                job["_result"] = {"schema": res["schema"], "rows": res["rows"], "affected": res["affected"]}
                job["_datasets"] = sorted({t[1] for t in res["touched"]} | ({q["defaultDataset"]["datasetId"]} if q.get("defaultDataset") else set())
                                          | ({q["destinationTable"]["datasetId"]} if q.get("destinationTable") and not job.get("_anon") else set()))
        elif config.get("copy"):
            c = config["copy"]
            srcs = c.get("sourceTables") or ([c["sourceTable"]] if c.get("sourceTable") else [])
            dest = c.get("destinationTable") or {}
            rows, schema = [], None
            for s in srcs:
                t = _get_tbl(store, s.get("projectId") or project, s["datasetId"], s["tableId"])
                schema = schema or t["schema"]
                rows.extend(json.loads(json.dumps(t["rows"])))
            _write_destination(store, project, dest, {"schema": schema, "rows": rows}, {**c, "createDisposition": c.get("createDisposition")})
            d = _get_tbl(store, dest.get("projectId") or project, dest["datasetId"], dest["tableId"])
            d["schema"] = json.loads(json.dumps(schema))
            job["statistics"]["copy"] = {"copiedRows": str(len(rows)), "copiedLogicalBytes": str(sum(_row_bytes(r) for r in rows))}
            job["_datasets"] = sorted({dest["datasetId"]} | {s["datasetId"] for s in srcs})
        elif config.get("load") or config.get("extract"):
            raise BqError(400, "Load and extract jobs need Cloud Storage, which is not available in this simulator "
                               "(use tabledata.insertAll or a query job).", "notImplemented", "UNIMPLEMENTED")
        else:
            raise BqError(400, "Required parameter is missing: configuration must set one of query, load, copy or extract.", "invalid")
    except BqError as e:
        if dry:
            raise
        job["status"] = {"state": "DONE", "errorResult": {"message": e.message, "reason": e.reason},
                         "errors": [{"message": e.message, "reason": e.reason}]}
        job["_error"] = {"status": e.status, "message": e.message, "reason": e.reason, "token": e.token}
    return job, res


def _jobs_insert(store, project, body) -> GcpResponse:
    config = body.get("configuration") or {}
    ref = body.get("jobReference") or {}
    jid = ref.get("jobId") or _job_id()
    loc = ref.get("location") or DEFAULT_LOCATION
    key = f"{project}:{jid}"
    if key in store.jobs:
        raise BqError(409, f"Already Exists: Job {project}:{loc}.{jid}", "duplicate", "ALREADY_EXISTS")
    dry = bool(config.get("dryRun"))
    if dry and config.get("query"):
        # Validate the query without running it (a dry run changes nothing).
        snapshot = json.dumps({"d": store.datasets})
        job, _ = _make_job(store, project, jid, loc, config, dry=True)
        store.datasets = json.loads(snapshot)["d"]
        job["status"] = {"state": "DONE"}
        return _json(200, _job_view(job))
    job, _ = _make_job(store, project, jid, loc, config)
    store.jobs[key] = job
    store.persist()
    return _json(200, _job_view(job))


def _find_job(store, project, jid) -> dict:
    j = store.jobs.get(f"{project}:{jid}")
    if j is None:
        raise BqError(404, f"Not found: Job {project}:{jid}", "notFound", "NOT_FOUND")
    return j


def _list_jobs(store, project, query) -> GcpResponse:
    states = [s.lower() for s in (query.get("stateFilter") or "").split(",") if s]
    jobs = [j for j in store.jobs.values() if j["jobReference"]["projectId"] == project]
    jobs.sort(key=lambda j: int(j["statistics"]["creationTime"]), reverse=True)
    items = []
    for j in jobs:
        st = j["status"]["state"].lower()
        if states and st not in states:
            continue
        items.append({"id": j["id"], "kind": "bigquery#job", "jobReference": j["jobReference"], "state": j["status"]["state"],
                      "status": j["status"], "statistics": j["statistics"], "configuration": j["configuration"],
                      "user_email": j["user_email"]})
    chunk, nxt = _page(items, query)
    out = {"kind": "bigquery#jobList", "etag": _etag([i["id"] for i in items]), "jobs": chunk}
    if nxt:
        out["nextPageToken"] = nxt
    return _json(200, out)


def _results_payload(job: dict, query: dict, kind: str) -> dict:
    err = job.get("_error")
    if err:
        raise BqError(err["status"], err["message"], err["reason"], err["token"])
    r = job.get("_result") or {"schema": [], "rows": [], "affected": None}
    rows = r["rows"]
    try:
        start = int(query.get("startIndex") or 0)
    except ValueError:
        start = 0
    if query.get("pageToken"):
        start = int(query["pageToken"])
    try:
        size = int(query.get("maxResults") or 0) or max(len(rows), 1)
    except ValueError:
        size = 1000
    out = {"kind": kind, "etag": _etag([job["id"]]), "jobReference": job["jobReference"], "jobComplete": True,
           "cacheHit": False, "totalRows": str(len(rows)),
           "totalBytesProcessed": job["statistics"].get("totalBytesProcessed", "0")}
    if r["schema"]:
        out["schema"] = {"fields": r["schema"]}
        out["rows"] = _wire_rows(r["schema"], rows[start:start + size])
        if start + size < len(rows):
            out["pageToken"] = str(start + size)
    if r.get("affected") is not None:
        out["numDmlAffectedRows"] = str(r["affected"])
    return out


def _query(store, project, body) -> GcpResponse:
    jid = ((body.get("jobReference") or {}).get("jobId")) or _job_id()
    loc = body.get("location") or ((body.get("jobReference") or {}).get("location")) or DEFAULT_LOCATION
    cfg = {"query": {k: body[k] for k in ("query", "defaultDataset", "queryParameters", "parameterMode",
                                           "useLegacySql", "maximumBytesBilled") if k in body}}
    cfg["query"].setdefault("useLegacySql", False)
    if body.get("labels"):
        cfg["labels"] = body["labels"]
    if body.get("dryRun"):
        cfg["dryRun"] = True
    if not cfg["query"].get("query"):
        raise BqError(400, "Query is required (the `query` field of the request).", "invalid")
    job, res = _make_job(store, project, jid, loc, cfg, dry=bool(body.get("dryRun")))
    if job.get("_error"):
        e = job["_error"]
        raise BqError(e["status"], e["message"], e["reason"], e["token"])
    if body.get("dryRun"):
        return _json(200, {"kind": "bigquery#queryResponse", "jobComplete": True,
                           "totalBytesProcessed": job["statistics"].get("totalBytesProcessed", "0"),
                           "jobReference": job["jobReference"], "cacheHit": False,
                           **({"schema": {"fields": res["schema"]}} if res and res["schema"] else {})})
    store.jobs[f"{project}:{jid}"] = job
    store.persist()
    out = _results_payload(job, {"maxResults": body.get("maxResults")}, "bigquery#queryResponse")
    out.pop("etag", None)
    return _json(200, out)


def _cancel_job(store, project, jid) -> GcpResponse:
    j = _find_job(store, project, jid)
    return _json(200, {"kind": "bigquery#jobCancelResponse", "job": _job_view(j)})


# ── routines ──────────────────────────────────────────────────────────────
def _insert_routine(store, project, dsid, body) -> GcpResponse:
    ds = _get_ds(store, project, dsid)
    ref = body.get("routineReference") or {}
    rid = ref.get("routineId") or ""
    if not re.match(r"^[A-Za-z0-9_]{1,256}$", rid):
        raise BqError(400, f"Invalid routine ID \"{rid}\".", "invalid")
    if rid in ds["routines"]:
        raise BqError(409, f"Already Exists: Routine {project}:{dsid}.{rid}", "duplicate", "ALREADY_EXISTS")
    rtype = body.get("routineType") or ""
    if rtype not in ("SCALAR_FUNCTION", "PROCEDURE", "TABLE_VALUED_FUNCTION", "AGGREGATE_FUNCTION"):
        raise BqError(400, "Invalid value for routineType.", "invalid")
    if not body.get("definitionBody"):
        raise BqError(400, "Routine definitionBody must be specified.", "invalid")
    now = _now_ms()
    r = {**{k: body[k] for k in ("language", "definitionBody", "arguments", "returnType", "description",
                                   "determinismLevel", "importedLibraries") if k in body},
         "routineReference": {"projectId": project, "datasetId": dsid, "routineId": rid},
         "routineType": rtype, "creationTime": now, "lastModifiedTime": now}
    r.setdefault("language", "SQL")
    ds["routines"][rid] = r
    store.persist()
    return _json(200, _routine_view(r))


def _routines(store, method, project, dsid, rest, query, body) -> GcpResponse:
    if not rest:
        if method == "POST":
            return _insert_routine(store, project, dsid, body)
        ds = _get_ds(store, project, dsid)
        items = [_routine_view(r) for _, r in sorted(ds["routines"].items())]
        chunk, nxt = _page(items, query)
        out = {"routines": chunk} if chunk else {}
        if nxt:
            out["nextPageToken"] = nxt
        return _json(200, out)
    ds = _get_ds(store, project, dsid)
    r = ds["routines"].get(rest[0])
    if r is None:
        raise BqError(404, f"Not found: Routine {project}:{dsid}.{rest[0]}", "notFound", "NOT_FOUND")
    if method == "GET":
        return _json(200, _routine_view(r))
    if method in ("PUT", "PATCH"):
        for k in ("language", "definitionBody", "arguments", "returnType", "description", "routineType"):
            if k in body:
                r[k] = body[k]
        r["lastModifiedTime"] = _now_ms()
        store.persist()
        return _json(200, _routine_view(r))
    if method == "DELETE":
        del ds["routines"][rest[0]]
        store.persist()
        return GcpResponse(status=204, body=b"", media_type=None)
    raise BqError(400, f"Unsupported method {method} on routine.", "invalid")


# ── console (UI) facade — flat rows, the same engine ──────────────────────
def console_row(ds: dict) -> dict:
    """A flat console row: every grid column is filled."""
    nbytes = sum(_tbl_bytes(t) for t in ds["tables"].values())
    exp = ds.get("defaultTableExpirationMs")
    return {
        "name": ds["id"], "resourceName": f"{ds['project']}:{ds['id']}", "project": ds["project"],
        "location": ds["location"], "tables": len(ds["tables"]), "routines": len(ds["routines"]),
        "size": _human(nbytes), "sizeBytes": nbytes,
        "expiration": f"{int(int(exp) / 86400000) or 1} days" if exp else "Never",
        "encryption": "Customer-managed" if ds.get("defaultEncryptionConfiguration") else "Google-managed",
        "description": ds.get("description") or "No description",
        "created": _iso(ds["creationTime"]), "modified": _iso(ds["lastModifiedTime"]),
        "labels": ds.get("labels") or {}, "state": "ACTIVE",
    }


def console_list(store: BigQueryStore) -> list:
    return [console_row(d) for _, d in sorted(store.datasets.items())]


def console_create(store: BigQueryStore, project: str, body: dict) -> dict:
    name = str(body.get("name") or "").strip()
    try:
        _insert_dataset(store, project, {}, {
            "datasetReference": {"datasetId": name, "projectId": project},
            "location": str(body.get("location") or body.get("__region__") or DEFAULT_LOCATION),
            "description": body.get("description") or "", "labels": body.get("labels") or {}})
    except BqError as e:
        return {"ok": False, "code": "AlreadyExists" if e.status == 409 else "InvalidArgument",
                "name": name, "message": e.message}
    return {"ok": True, **console_row(store.datasets[_dkey(project, name)])}


def console_find(store: BigQueryStore, name: str):
    for k, d in store.datasets.items():
        if d["id"] == name or k == name:
            return k, d
    return None, None


def console_delete(store: BigQueryStore, name: str) -> dict:
    key, ds = console_find(store, name)
    if ds is None:
        return {"ok": False, "code": "NotFound", "name": name}
    store.datasets.pop(key)
    store.persist()
    return {"ok": True, "code": None, "name": name}


def console_children(store: BigQueryStore, name: str, kind: str) -> list:
    """Rows for the detail tabs: kind in tables | jobs | routines."""
    _, ds = console_find(store, name)
    if ds is None:
        return []
    out = []
    if kind == "tables":
        for t in sorted(ds["tables"].values(), key=lambda x: x["id"]):
            out.append({"name": t["id"], "type": t["type"].title(), "rows": len(t["rows"]),
                        "size": _human(_tbl_bytes(t)), "columns": len(t["schema"]),
                        "created": _iso(t["creationTime"])})
    elif kind == "routines":
        for r in sorted(ds["routines"].values(), key=lambda x: x["routineReference"]["routineId"]):
            out.append({"name": r["routineReference"]["routineId"], "type": r["routineType"].replace("_", " ").title(),
                        "language": r.get("language", "SQL"), "created": _iso(r["creationTime"]),
                        "modified": _iso(r["lastModifiedTime"])})
    elif kind == "jobs":
        for j in sorted(store.jobs.values(), key=lambda x: -int(x["statistics"]["creationTime"])):
            if ds["id"] not in j.get("_datasets", []):
                continue
            q = (j["configuration"].get("query") or {}).get("query")
            qs = j["statistics"].get("query") or {}
            out.append({"name": j["jobReference"]["jobId"], "type": "Query" if q else "Copy",
                        "state": j["status"]["state"] + (" (failed)" if j["status"].get("errorResult") else ""),
                        "statement": (q or "table copy").strip()[:80],
                        "bytes": _human(int(j["statistics"].get("totalBytesProcessed", 0) or 0)),
                        "created": _iso(j["statistics"]["creationTime"]),
                        "statementType": qs.get("statementType", "COPY")})
    return out


SAMPLE_SCHEMA = {"fields": [{"name": "id", "type": "INTEGER", "mode": "REQUIRED"},
                            {"name": "name", "type": "STRING", "mode": "NULLABLE"},
                            {"name": "score", "type": "FLOAT", "mode": "NULLABLE"},
                            {"name": "created", "type": "TIMESTAMP", "mode": "NULLABLE"}]}


def console_sample(store: BigQueryStore, name: str, op: str) -> dict:
    """Sample data actions used by the console: createTable (3 rows) / runQuery."""
    _, ds = console_find(store, name)
    if ds is None:
        return {"ok": False, "code": "NotFound", "name": name}
    project, dsid = ds["project"], ds["id"]
    if op == "createTable":
        tid = "sample_table"
        n = 1
        while tid in ds["tables"]:
            n += 1
            tid = f"sample_table_{n}"
        _insert_table(store, project, dsid, {"tableReference": {"tableId": tid}, "schema": SAMPLE_SCHEMA,
                                             "description": "Sample table created from the Vyomi console"})
        _insert_all(store, project, dsid, tid, {"rows": [
            {"json": {"id": i, "name": nm, "score": sc, "created": "2024-01-01 00:00:00"}}
            for i, nm, sc in ((1, "alpha", 1.5), (2, "beta", 2.5), (3, "gamma", 3.5))]})
        return {"ok": True, "name": name, "table": tid}
    if op == "runQuery":
        tid = next(iter(sorted(ds["tables"])), None)
        sql = f"SELECT COUNT(*) AS row_count FROM `{project}.{dsid}.{tid}`" if tid else "SELECT 1 AS one"
        r = _jobs_insert(store, project, {"configuration": {"query": {"query": sql, "useLegacySql": False,
                                                                       "defaultDataset": {"projectId": project, "datasetId": dsid}}}})
        return {"ok": r.status < 300, "name": name, "job": json.loads(r.body).get("jobReference", {}).get("jobId", "")}
    return {"ok": False, "code": "UnknownOperation", "name": op}


# ── dispatch ──────────────────────────────────────────────────────────────
_IAM_VERBS = ("getIamPolicy", "setIamPolicy", "testIamPermissions")


def dispatch(store: BigQueryStore, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> GcpResponse:
    query = query or {}
    method = method.upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if (headers or {}).get("x-http-method-override", "").upper() in ("GET", "PATCH", "PUT", "DELETE"):
        method = headers["x-http-method-override"].upper()
    try:
        return _route(store, method, path, query, payload)
    except BqError as e:
        return _err(e.status, e.message, e.reason, e.token)


def _route(store, method, path, query, payload) -> GcpResponse:
    p = path.split("?", 1)[0]
    if p.startswith("/upload/"):
        raise BqError(501, "Media upload (load jobs from local files) is not supported; use tabledata.insertAll "
                           "or a query job.", "notImplemented", "UNIMPLEMENTED")
    for pre in ("/bigquery/v2", "/v2"):
        if p.startswith(pre + "/") or p == pre:
            p = p[len(pre):]
            break
    p = p.strip("/")
    verb = ""
    if ":" in p and p.rsplit(":", 1)[1] in _IAM_VERBS:
        p, verb = p.rsplit(":", 1)
    segs = [s for s in p.split("/") if s]
    if not segs or segs[0] != "projects":
        raise BqError(404, f"Not found: {path}", "notFound", "NOT_FOUND")
    if len(segs) == 1:
        if method == "GET":
            projs = sorted({d["project"] for d in store.datasets.values()} | {j["jobReference"]["projectId"] for j in store.jobs.values()}
                           | {"vyomi-project"})
            return _json(200, {"kind": "bigquery#projectList", "etag": _etag(projs), "totalItems": len(projs),
                               "projects": [{"kind": "bigquery#project", "id": x, "numericId": str(int(hashlib.md5(x.encode()).hexdigest()[:8], 16)),
                                             "projectReference": {"projectId": x}, "friendlyName": x} for x in projs]})
        raise BqError(400, f"Unsupported method {method} on projects.", "invalid")
    project = segs[1]
    rest = segs[2:]
    if not rest:
        raise BqError(404, f"Not found: {path}", "notFound", "NOT_FOUND")
    kind = rest[0]
    if kind == "serviceAccount":
        return _json(200, {"kind": "bigquery#getServiceAccountResponse",
                           "email": f"bq-{hashlib.md5(project.encode()).hexdigest()[:10]}@bigquery-encryption.iam.gserviceaccount.com"})
    if kind == "queries":
        if len(rest) == 1 and method == "POST":
            return _query(store, project, payload)
        if len(rest) == 2 and method == "GET":
            j = _find_job(store, project, rest[1])
            return _json(200, _results_payload(j, query, "bigquery#getQueryResultsResponse"))
        raise BqError(400, f"Unsupported method {method} on queries.", "invalid")
    if kind == "jobs":
        if len(rest) == 1:
            if method == "POST":
                return _jobs_insert(store, project, payload)
            if method == "GET":
                return _list_jobs(store, project, query)
        else:
            j = _find_job(store, project, rest[1])
            if len(rest) == 2 and method == "GET":
                return _json(200, _job_view(j))
            if len(rest) == 3 and rest[2] == "cancel" and method == "POST":
                return _cancel_job(store, project, rest[1])
            if len(rest) == 3 and rest[2] == "delete" and method in ("DELETE", "POST"):
                store.jobs.pop(f"{project}:{rest[1]}", None)
                store.persist()
                return GcpResponse(status=204, body=b"", media_type=None)
        raise BqError(400, f"Unsupported method {method} on jobs.", "invalid")
    if kind != "datasets":
        raise BqError(404, f"Not found: {path}", "notFound", "NOT_FOUND")
    if len(rest) == 1:
        if method == "POST":
            return _insert_dataset(store, project, query, payload)
        if method == "GET":
            return _list_datasets(store, project, query)
        raise BqError(400, f"Unsupported method {method} on datasets.", "invalid")
    dsid = rest[1]
    sub = rest[2:]
    if not sub:
        if method == "GET":
            return _json(200, _ds_view(_get_ds(store, project, dsid)))
        if method == "PATCH":
            return _patch_dataset(store, project, dsid, payload)
        if method == "PUT":
            return _patch_dataset(store, project, dsid, payload, replace=True)
        if method == "DELETE":
            return _delete_dataset(store, project, dsid, query)
        raise BqError(400, f"Unsupported method {method} on dataset.", "invalid")
    if sub[0] == "routines":
        return _routines(store, method, project, dsid, sub[1:], query, payload)
    if sub[0] == "models":
        ds = _get_ds(store, project, dsid)
        if len(sub) == 1 and method == "GET":
            return _json(200, {})
        raise BqError(404, f"Not found: Model {project}:{dsid}.{sub[1] if len(sub) > 1 else ''}", "notFound", "NOT_FOUND")
    if sub[0] != "tables":
        raise BqError(404, f"Not found: {path}", "notFound", "NOT_FOUND")
    if len(sub) == 1:
        if method == "POST":
            return _insert_table(store, project, dsid, payload)
        if method == "GET":
            return _list_tables(store, project, dsid, query)
        raise BqError(400, f"Unsupported method {method} on tables.", "invalid")
    tid = sub[1]
    tail = sub[2:]
    if verb:
        return _tbl_iam(store, project, dsid, tid, verb, payload)
    if not tail:
        if method == "GET":
            return _json(200, _tbl_view(_get_tbl(store, project, dsid, tid)))
        if method == "PATCH":
            return _patch_table(store, project, dsid, tid, payload)
        if method == "PUT":
            return _patch_table(store, project, dsid, tid, payload, replace=True)
        if method == "DELETE":
            return _delete_table(store, project, dsid, tid)
        raise BqError(400, f"Unsupported method {method} on table.", "invalid")
    if tail == ["insertAll"] and method == "POST":
        return _insert_all(store, project, dsid, tid, payload)
    if tail == ["data"] and method == "GET":
        return _list_data(store, project, dsid, tid, query)
    raise BqError(404, f"Not found: {path}", "notFound", "NOT_FOUND")
