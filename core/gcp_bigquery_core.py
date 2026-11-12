"""A small BigQuery (bigquery.googleapis.com/bigquery/v2) — datasets, tables, rows and SQL queries — substrate-free
(stdlib only: runs on Nano/Pyodide and offline). State is a public dict on the Cloud Storage store (``store.bigquery``) so
it persists with the rest of the project and Storage Insights can populate it.

Queries are REAL SQL, executed by the SQLite engine (stdlib ``sqlite3``) over the table rows: `proj.dataset.table`
references are rewritten to the stored table, so SELECT/WHERE/GROUP BY/ORDER BY/LIMIT/JOIN/aggregates all run. It is
SQLite's dialect, not GoogleSQL: GoogleSQL-only syntax (STRUCT/ARRAY/UNNEST, SAFE_ functions, QUALIFY, ...) fails with the
engine's own error. DML/DDL is refused (read-only query surface).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field

TYPES = ("STRING", "INTEGER", "INT64", "FLOAT", "FLOAT64", "BOOLEAN", "BOOL", "TIMESTAMP", "BYTES", "JSON", "DATE", "NUMERIC")
_ID = re.compile(r"^[A-Za-z0-9_]{1,1024}$")
MAX_ROWS = 100000


class BqError(Exception):
    def __init__(self, status, reason, message):
        super().__init__(message)
        self.status, self.reason, self.message = status, reason, message


@dataclass
class Resp:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str = "application/json"


def _ms():
    return str(int(time.time() * 1000))


def state(store) -> dict:
    s = getattr(store, "bigquery", None)
    if s is None:
        s = {"datasets": {}, "jobs": {}}
        store.bigquery = s
    return s


def handles(path):
    return path.startswith("/bigquery/v2/") or path.startswith("/upload/bigquery/v2/")


# ── programmatic API (Storage Insights uses these) ────────────────────────
def ensure_dataset(store, project, dataset, location="US", description="", labels=None):
    st = state(store)
    key = f"{project}:{dataset}"
    if key not in st["datasets"]:
        st["datasets"][key] = {"project": project, "id": dataset, "location": location, "description": description,
                               "labels": labels or {}, "creationTime": _ms(), "lastModifiedTime": _ms(), "tables": {}}
    return st["datasets"][key]


def put_table(store, project, dataset, table, schema, rows, description="", labels=None):
    """Create/replace a table with ``schema`` [{name,type}] and ``rows`` (list of dicts)."""
    ds = ensure_dataset(store, project, dataset)
    ds["tables"][table] = {"id": table, "schema": [{"name": f["name"], "type": f.get("type", "STRING"), "mode": f.get("mode", "NULLABLE")} for f in schema],
                           "rows": [dict(r) for r in rows[:MAX_ROWS]], "description": description, "labels": labels or {},
                           "creationTime": _ms(), "lastModifiedTime": _ms()}
    return ds["tables"][table]


# ── views ─────────────────────────────────────────────────────────────────
def _ds_view(d):
    return {"kind": "bigquery#dataset", "id": f"{d['project']}:{d['id']}", "datasetReference": {"projectId": d["project"], "datasetId": d["id"]},
            "location": d["location"], "friendlyName": d.get("friendlyName", ""), "description": d.get("description", ""), "labels": d.get("labels", {}),
            "creationTime": d["creationTime"], "lastModifiedTime": d["lastModifiedTime"], "selfLink": f"https://bigquery.googleapis.com/bigquery/v2/projects/{d['project']}/datasets/{d['id']}"}


def _tbl_view(d, t, full=True):
    out = {"kind": "bigquery#table", "id": f"{d['project']}:{d['id']}.{t['id']}", "tableReference": {"projectId": d["project"], "datasetId": d["id"], "tableId": t["id"]},
           "type": "TABLE", "creationTime": t["creationTime"], "location": d["location"]}
    if full:
        out.update({"schema": {"fields": t["schema"]}, "numRows": str(len(t["rows"])), "numBytes": str(len(json.dumps(t["rows"]))),
                    "description": t.get("description", ""), "labels": t.get("labels", {}), "lastModifiedTime": t["lastModifiedTime"]})
    return out


_PY = {"STRING": str, "BYTES": str, "JSON": str, "DATE": str, "TIMESTAMP": str, "NUMERIC": str}


def _cell(v):
    return {"v": None if v is None else (("true" if v else "false") if isinstance(v, bool) else str(v))}


def _row(t, r):
    return {"f": [_cell(r.get(f["name"])) for f in t["schema"]]}


# ── SQL ───────────────────────────────────────────────────────────────────
_FROM = re.compile(r"(?i)\b(from|join)\s+(`[^`]+`|[A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*){0,2})")


def _run_query(store, project, sql, default_dataset=None, max_results=None):
    st = state(store)
    s = sql.strip().rstrip(";")
    if not re.match(r"(?is)^(select|with)\b", s):
        raise BqError(400, "invalidQuery", "Only SELECT queries are supported by this simulator (no DML/DDL).")
    con = sqlite3.connect(":memory:")
    try:
        loaded = {}

        def sub(m):
            ref = m.group(2).strip("`")
            parts = ref.split(".")
            if len(parts) == 3:
                p, d, t = parts
            elif len(parts) == 2:
                p, d, t = project, parts[0], parts[1]
            elif default_dataset:
                p, d, t = project, default_dataset, parts[0]
            else:
                raise BqError(400, "invalidQuery", "Table name %r must be qualified with a dataset." % ref)
            ds = st["datasets"].get(f"{p}:{d}")
            tb = ds and ds["tables"].get(t)
            if not tb:
                raise BqError(404, "notFound", "Not found: Table %s:%s.%s" % (p, d, t))
            local = "t_" + hashlib.md5(f"{p}.{d}.{t}".encode()).hexdigest()[:10]
            if local not in loaded:
                cols = ", ".join('"%s" %s' % (f["name"], "INTEGER" if f["type"] in ("INTEGER", "INT64", "BOOLEAN", "BOOL") else "REAL" if f["type"] in ("FLOAT", "FLOAT64") else "TEXT") for f in tb["schema"])
                con.execute("CREATE TABLE %s (%s)" % (local, cols))
                names = [f["name"] for f in tb["schema"]]
                con.executemany("INSERT INTO %s VALUES (%s)" % (local, ",".join("?" * len(names))),
                                [tuple(int(r[n]) if isinstance(r.get(n), bool) else r.get(n) for n in names) for r in tb["rows"]])
                loaded[local] = tb
            return "%s %s" % (m.group(1), local)
        rewritten = _FROM.sub(sub, s)
        try:
            cur = con.execute(rewritten)
            rows = cur.fetchmany(MAX_ROWS)
        except sqlite3.Error as e:
            raise BqError(400, "invalidQuery", "Query error: %s (note: this simulator runs queries on SQLite, not GoogleSQL)" % e)
        names = [d[0] for d in cur.description or []]
        types = []
        for i in range(len(names)):
            v = next((r[i] for r in rows if r[i] is not None), None)
            types.append("INTEGER" if isinstance(v, int) else "FLOAT" if isinstance(v, float) else "STRING")
        return names, types, rows
    finally:
        con.close()


def _query_response(project, job_id, location, names, types, rows, max_results=None):
    shown = rows if not max_results else rows[:int(max_results)]
    return {"kind": "bigquery#queryResponse", "jobComplete": True, "totalRows": str(len(rows)),
            "schema": {"fields": [{"name": n, "type": t, "mode": "NULLABLE"} for n, t in zip(names, types)]},
            "jobReference": {"projectId": project, "jobId": job_id, "location": location},
            "rows": [{"f": [_cell(v) for v in r]} for r in shown], "totalBytesProcessed": "0", "cacheHit": False}


# ── REST ──────────────────────────────────────────────────────────────────
def _json(status, obj):
    return Resp(status, json.dumps(obj).encode())


def _err(e):
    return _json(e.status, {"error": {"code": e.status, "message": e.message, "errors": [{"message": e.message, "domain": "global", "reason": e.reason}],
                                      "status": {404: "NOT_FOUND", 409: "ALREADY_EXISTS", 400: "INVALID_ARGUMENT"}.get(e.status, "UNKNOWN")}})


def dispatch(store, method, path, query=None, headers=None, body=b"", **_):
    try:
        return _dispatch(store, method.upper(), path.split("?", 1)[0], query or {}, body)
    except BqError as e:
        return _err(e)


def _body(body):
    if not body:
        return {}
    try:
        v = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)
    except Exception:
        raise BqError(400, "parseError", "Request body is not valid JSON.")
    return v if isinstance(v, dict) else {}


def _dispatch(store, method, path, query, body):
    st = state(store)
    segs = [x for x in path.replace("/upload/", "/").split("/") if x]          # bigquery v2 projects P ...
    if len(segs) < 4 or segs[:3] != ["bigquery", "v2", "projects"]:
        raise BqError(404, "notFound", "Not found: %s" % path)
    project, rest = segs[3], segs[4:]
    if not rest:
        return _json(200, {"kind": "bigquery#project", "id": project, "numericId": "0", "projectReference": {"projectId": project}})
    if rest[0] == "datasets":
        if len(rest) == 1:
            if method == "GET":
                return _json(200, {"kind": "bigquery#datasetList", "datasets": [_ds_view(d) for d in st["datasets"].values() if d["project"] == project]})
            if method == "POST":
                b = _body(body)
                did = (b.get("datasetReference") or {}).get("datasetId", "")
                if not _ID.match(did):
                    raise BqError(400, "invalid", "Invalid dataset ID %r. Dataset IDs must be alphanumeric (plus underscores)." % did)
                if f"{project}:{did}" in st["datasets"]:
                    raise BqError(409, "duplicate", "Already Exists: Dataset %s:%s" % (project, did))
                d = ensure_dataset(store, project, did, b.get("location") or "US", b.get("description", ""), b.get("labels"))
                if b.get("friendlyName"):
                    d["friendlyName"] = b["friendlyName"]
                return _json(200, _ds_view(d))
        else:
            d = st["datasets"].get(f"{project}:{rest[1]}")
            if d is None:
                raise BqError(404, "notFound", "Not found: Dataset %s:%s" % (project, rest[1]))
            if len(rest) == 2:
                if method == "GET":
                    return _json(200, _ds_view(d))
                if method in ("PATCH", "PUT"):
                    b = _body(body)
                    for k in ("friendlyName", "description", "labels"):
                        if k in b:
                            d[k] = b[k]
                    d["lastModifiedTime"] = _ms()
                    return _json(200, _ds_view(d))
                if method == "DELETE":
                    if d["tables"] and str(query.get("deleteContents", "")).lower() != "true":
                        raise BqError(400, "resourceInUse", "Dataset %s:%s is still in use" % (project, rest[1]))
                    del st["datasets"][f"{project}:{rest[1]}"]
                    return Resp(204, b"", media_type=None)
            elif rest[2] == "tables":
                if len(rest) == 3:
                    if method == "GET":
                        return _json(200, {"kind": "bigquery#tableList", "totalItems": len(d["tables"]), "tables": [_tbl_view(d, t, False) for t in d["tables"].values()]})
                    if method == "POST":
                        b = _body(body)
                        tid = (b.get("tableReference") or {}).get("tableId", "")
                        if not _ID.match(tid):
                            raise BqError(400, "invalid", "Invalid table ID %r." % tid)
                        if tid in d["tables"]:
                            raise BqError(409, "duplicate", "Already Exists: Table %s:%s.%s" % (project, d["id"], tid))
                        fields = (b.get("schema") or {}).get("fields") or []
                        for f in fields:
                            if f.get("type", "STRING").upper() not in TYPES:
                                raise BqError(400, "invalid", "Unsupported column type %s." % f.get("type"))
                        t = put_table(store, project, d["id"], tid, [{**f, "type": f.get("type", "STRING").upper()} for f in fields], [], b.get("description", ""), b.get("labels"))
                        return _json(200, _tbl_view(d, t))
                else:
                    t = d["tables"].get(rest[3])
                    if t is None:
                        raise BqError(404, "notFound", "Not found: Table %s:%s.%s" % (project, d["id"], rest[3]))
                    if len(rest) == 4:
                        if method == "GET":
                            return _json(200, _tbl_view(d, t))
                        if method == "DELETE":
                            del d["tables"][rest[3]]
                            return Resp(204, b"", media_type=None)
                    elif rest[4] == "data" and method == "GET":
                        start = int(query.get("startIndex") or 0)
                        n = int(query.get("maxResults") or 50)
                        return _json(200, {"kind": "bigquery#tableDataList", "totalRows": str(len(t["rows"])),
                                           "rows": [_row(t, r) for r in t["rows"][start:start + n]]})
                    elif rest[4] == "insertAll" and method == "POST":
                        errs = []
                        for i, r in enumerate(_body(body).get("rows") or []):
                            js = r.get("json") or {}
                            bad = [k for k in js if k not in [f["name"] for f in t["schema"]]]
                            if bad:
                                errs.append({"index": i, "errors": [{"reason": "invalid", "message": "no such field: %s" % bad[0]}]})
                            else:
                                t["rows"].append(js)
                        t["lastModifiedTime"] = _ms()
                        return _json(200, {"kind": "bigquery#tableDataInsertAllResponse", **({"insertErrors": errs} if errs else {})})
    elif rest[0] == "queries" and len(rest) == 2 and method == "GET" and rest[1] in st["jobs"]:   # getQueryResults
        j = st["jobs"][rest[1]]
        return _json(200, _query_response(project, rest[1], "US", j["names"], j["types"], j["rows"], query.get("maxResults")))
    elif rest[0] == "queries" and method == "POST":
        b = _body(body)
        dd = (b.get("defaultDataset") or {}).get("datasetId")
        job_id = "job_" + uuid.uuid4().hex[:20]
        names, types, rows = _run_query(store, project, b.get("query", ""), dd)
        st["jobs"][job_id] = {"project": project, "query": b.get("query", ""), "names": names, "types": types, "rows": [list(r) for r in rows], "creationTime": _ms()}
        return _json(200, _query_response(project, job_id, "US", names, types, rows, b.get("maxResults")))
    elif rest[0] == "jobs":
        if len(rest) == 1 and method == "POST":
            b = _body(body)
            q = (b.get("configuration") or {}).get("query") or {}
            if not q.get("query"):
                raise BqError(400, "invalid", "Only query jobs are supported (configuration.query).")
            job_id = (b.get("jobReference") or {}).get("jobId") or "job_" + uuid.uuid4().hex[:20]
            names, types, rows = _run_query(store, project, q["query"], (q.get("defaultDataset") or {}).get("datasetId"))
            st["jobs"][job_id] = {"project": project, "query": q["query"], "names": names, "types": types, "rows": [list(r) for r in rows], "creationTime": _ms()}
            return _json(200, {"kind": "bigquery#job", "id": f"{project}:{job_id}", "jobReference": {"projectId": project, "jobId": job_id, "location": "US"},
                               "configuration": {"query": {"query": q["query"]}}, "status": {"state": "DONE"}})
        if len(rest) >= 2 and rest[1] in st["jobs"]:
            j = st["jobs"][rest[1]]
            if len(rest) == 2 and method == "GET":
                return _json(200, {"kind": "bigquery#job", "id": f"{project}:{rest[1]}", "jobReference": {"projectId": project, "jobId": rest[1], "location": "US"}, "status": {"state": "DONE"}})
        if len(rest) == 3 and rest[2] == "queries" and method == "GET" and rest[1] in st["jobs"]:   # jobs.getQueryResults
            j = st["jobs"][rest[1]]
            return _json(200, _query_response(project, rest[1], "US", j["names"], j["types"], j["rows"], query.get("maxResults")))
    raise BqError(404, "notFound", "Not found: %s" % path)
