# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""GCP Cloud Logging core — substrate-independent. Speaks the native **Cloud Logging
REST API v2** (`logging.googleapis.com/v2`) so `google-cloud-logging` / `gcloud logging ...`
work unchanged against it (point them at the endpoint via api_endpoint overrides).

NO fastapi / google-cloud / socket / subprocess imports -> loads under Pyodide, so the
SAME file runs offline and in Nano.

Resources (Discovery docs `logging/v2`):
    entries:write                               ingest LogEntry batch
    entries:list                                query with the logging filter language
    projects/{p}/logs                            list (distinct log names), delete
    projects/{p}/sinks/{id}                      create/get/list/patch/delete (Log Router)
    projects/{p}/metrics/{id}                     create/get/list/update/delete (log-based metrics)
    projects/{p}/locations/{loc}/buckets/{id}     create/get/list/patch/delete (Logs Storage,
                                                  Logging Config API v2, same REST surface)
    .../buckets/{id}/views/{id}                   create/get/list/delete (log views)

Errors use the Google shape `{"error":{"code","message","status"}}` (INVALID_ARGUMENT,
NOT_FOUND, ALREADY_EXISTS, FAILED_PRECONDITION).
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field

SEVERITIES = {"DEFAULT": 0, "DEBUG": 100, "INFO": 200, "NOTICE": 300, "WARNING": 400,
              "ERROR": 500, "CRITICAL": 600, "ALERT": 700, "EMERGENCY": 800}
MAX_ENTRIES_PER_WRITE = 1000
_LOGID_RE = re.compile(r"^[A-Za-z0-9_./\-]+$")
_BUCKET_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,100}$")
_PROTECTED_BUCKETS = {"_Default", "_Required"}
_DEST_RE = re.compile(
    r"^(storage\.googleapis\.com/[\w.\-]+"
    r"|bigquery\.googleapis\.com/projects/[^/]+/datasets/[\w\-]+"
    r"|pubsub\.googleapis\.com/projects/[^/]+/topics/[\w\-]+"
    r"|logging\.googleapis\.com/projects/[^/]+/locations/[^/]+/buckets/[\w\-]+)$"
)


class LoggingStore:
    """Seam: public dict/list attrs are the whole persisted state."""

    def __init__(self) -> None:
        self.entries: list[dict] = []                 # LogEntry, newest appended last
        self.sinks: dict[str, dict] = {}               # full resource name -> LogSink
        self.metrics: dict[str, dict] = {}             # full resource name -> LogMetric
        self.buckets: dict[str, dict] = {}             # full resource name -> LogBucket
        self.views: dict[str, dict] = {}               # full resource name -> LogView
        self._clock: float | None = None
        self.mon_store = None   # the shared Cloud Monitoring store (set by the wire router) —
        # real usage-alert metrics (logging.googleapis.com/byte_count, .../log_entry_count)

    def now(self) -> float:
        return self._clock if self._clock is not None else time.time()

    def set_time(self, t: float) -> None:
        self._clock = t

    def persist(self) -> None:  # overridden by durable substrates
        pass


@dataclass
class LogResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _bad(msg):
    return _E(400, "INVALID_ARGUMENT", msg)


def _notfound(msg):
    return _E(404, "NOT_FOUND", msg)


def _err(status, gcp_status, message):
    return LogResponse(status=status, body=json.dumps({"error": {"code": status, "message": message, "status": gcp_status}}).encode())


def _json(status, obj):
    return LogResponse(status=status, body=json.dumps(obj).encode())


def _copy(x):
    return json.loads(json.dumps(x))


def _now_iso(store):
    t = store.now()
    ms = int((t - int(t)) * 1000)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{ms:03d}Z"


def _rand_id(n=16):
    return uuid.uuid4().hex[:n]


# ── log names ────────────────────────────────────────────────────────────────
def _log_name(project, log_id):
    from urllib.parse import quote
    return f"projects/{project}/logs/{quote(str(log_id), safe='')}"


def _log_id(log_name):
    from urllib.parse import unquote
    return unquote(log_name.rsplit("/logs/", 1)[-1])


# ── entries ──────────────────────────────────────────────────────────────────
def _validate_entry(e, top):
    merged = dict(top)
    merged.update({k: v for k, v in e.items() if v is not None})
    log_name = merged.get("logName")
    if not log_name:
        raise _bad("entries[].log_name is required (directly or via the top-level logName).")
    sev = merged.get("severity", "DEFAULT")
    if sev not in SEVERITIES:
        raise _bad(f"Invalid severity '{sev}'.")
    payloads = [k for k in ("textPayload", "jsonPayload", "protoPayload") if k in merged]
    if len(payloads) > 1:
        raise _bad("entries[] must carry at most one of textPayload, jsonPayload, protoPayload.")
    if not payloads:
        merged["textPayload"] = ""
    return merged


def write_entries(store, project_hint, body):
    top = {k: body.get(k) for k in ("logName", "resource", "labels") if body.get(k) is not None}
    raw = body.get("entries")
    if not isinstance(raw, list) or not raw:
        raise _bad("Field entries is required: at least one LogEntry must be written.")
    if len(raw) > MAX_ENTRIES_PER_WRITE:
        raise _bad(f"Field entries has too many values: at most {MAX_ENTRIES_PER_WRITE} per request.")
    partial = bool(body.get("partialSuccess"))
    dry_run = bool(body.get("dryRun"))
    out, err_index = [], {}
    for i, e in enumerate(raw):
        try:
            merged = _validate_entry(e if isinstance(e, dict) else {}, top)
        except _E as exc:
            if partial:
                err_index[str(i)] = {"code": 3, "message": exc.message}
                continue
            raise
        merged.setdefault("resource", {"type": "global", "labels": {}})
        merged.setdefault("severity", "DEFAULT")
        merged["receiveTimestamp"] = _now_iso(store)
        merged.setdefault("timestamp", merged["receiveTimestamp"])
        merged.setdefault("insertId", _rand_id(20))
        merged.setdefault("labels", {})
        out.append(merged)
    if not dry_run:
        store.entries.extend(out)
        if len(store.entries) > 200000:
            del store.entries[: len(store.entries) - 200000]
        _route_to_sinks(store, out)
        for proj in {m.group(1) for e in out if (m := _PROJECT_OF_LOGNAME.match(e.get("logName", "")))}:
            _sync_usage_metrics(store, proj)
        store.persist()
    resp = {}
    if err_index:
        resp["error"] = {"code": 400, "message": "One or more LogEntries were not written due to permission or validity errors.",
                          "status": "PERMISSION_DENIED",
                          "details": [{"@type": "type.googleapis.com/google.logging.v2.WriteLogEntriesPartialErrors", "logEntryErrors": err_index}]}
    return _json(200, resp)


_TS_RE = re.compile(r"^(\d{4})-(\d\d)-(\d\d)[Tt](\d\d):(\d\d):(\d\d)(?:\.(\d+))?([Zz]|[+-]\d\d:?\d\d)?$")


def _parse_ts(s):
    m = _TS_RE.match(str(s or "").strip())
    if not m:
        raise _bad(f"Invalid timestamp '{s}': expected RFC 3339.")
    y, mo, d, h, mi, se, frac, tz = m.groups()
    import calendar
    t = calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(se)))
    t += float("0." + frac) if frac else 0.0
    if tz and tz not in "Zz":
        sign = 1 if tz[0] == "+" else -1
        raw = tz[1:].replace(":", "")
        t -= sign * (int(raw[:2]) * 3600 + int(raw[2:]) * 60)
    return t


def _entry_ts(e):
    try:
        return _parse_ts(e["timestamp"])
    except Exception:
        return 0.0


def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _split_and(filt):
    parts, cur, q = [], "", None
    i = 0
    while i < len(filt):
        c = filt[i]
        if q:
            cur += c
            if c == q:
                q = None
        elif c in "\"'":
            q = c
            cur += c
        elif filt[i:i + 5].upper() == " AND ":
            parts.append(cur)
            cur = ""
            i += 4
        elif c == "\n":
            parts.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    parts.append(cur)
    return [p for p in parts if p.strip()]


_CLAUSE = re.compile(r'^\s*(-)?([\w.\[\]]+)\s*(=~|!=|>=|<=|>|<|=)\s*(.+?)\s*$')


def _field(entry, path):
    if path == "severity":
        return entry.get("severity", "DEFAULT")
    if path in ("logName", "trace", "spanId", "insertId", "timestamp", "receiveTimestamp"):
        return entry.get(path)
    if path == "resource.type":
        return (entry.get("resource") or {}).get("type")
    if path.startswith("resource.labels."):
        return (entry.get("resource") or {}).get("labels", {}).get(path.split(".", 2)[2])
    if path.startswith("labels."):
        return entry.get("labels", {}).get(path.split(".", 1)[1])
    if path.startswith("jsonPayload."):
        cur = entry.get("jsonPayload")
        for part in path.split(".")[1:]:
            if isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
        return cur
    if path == "textPayload":
        return entry.get("textPayload")
    return None


def compile_log_filter(filt):
    """-> predicate(entry). Subset of the Cloud Logging query language: AND-joined
    clauses `field op "value"`, bare tokens matched as free-text substrings."""
    clauses = []
    for part in _split_and(filt or ""):
        m = _CLAUSE.match(part)
        if m:
            neg, lhs, op, rhs = m.groups()
            clauses.append(("field", bool(neg), lhs, op, _unquote(rhs)))
        else:
            clauses.append(("text", False, None, None, _unquote(part)))

    def pred(entry):
        for kind, neg, lhs, op, rhs in clauses:
            if kind == "text":
                hay = json.dumps(entry, default=str).lower()
                ok = rhs.lower() in hay
            else:
                v = _field(entry, lhs)
                if lhs == "severity" and op in (">=", "<=", ">", "<"):
                    a, b = SEVERITIES.get(str(v), -1), SEVERITIES.get(rhs, 10 ** 9)
                    ok = {">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}[op]
                elif op == "=~":
                    ok = re.search(rhs, str(v or "")) is not None
                else:
                    ok = (v is not None) and (str(v) == rhs or str(v).startswith(rhs))
                if op == "!=":
                    ok = not ok
            if neg:
                ok = not ok
            if not ok:
                return False
        return True
    return pred


def list_entries(store, body):
    names = body.get("resourceNames") or []
    pred = compile_log_filter(body.get("filter") or "")
    rows = [e for e in store.entries if (not names or any(e.get("logName", "").startswith(f"{n}/") for n in names)) and pred(e)]
    desc = (body.get("orderBy") or "timestamp desc").strip().lower() != "timestamp asc"
    rows = sorted(rows, key=_entry_ts, reverse=desc)
    size = int(body.get("pageSize") or 100) or 100
    tok = body.get("pageToken")
    start = int(tok) if tok else 0
    page = rows[start:start + size]
    out = {"entries": [_copy(e) for e in page]}
    if start + size < len(rows):
        out["nextPageToken"] = str(start + size)
    return _json(200, out)


def list_logs(store, project, parent_prefix):
    names = sorted({e["logName"] for e in store.entries if e["logName"].startswith(parent_prefix)})
    return _json(200, {"logNames": names} if names else {})


def delete_log(store, log_name):
    store.entries[:] = [e for e in store.entries if e.get("logName") != log_name]
    store.persist()
    return _json(200, {})


# ── sinks (Log Router) ──────────────────────────────────────────────────────
def _sink_name(project, sid):
    return f"projects/{project}/sinks/{sid}"


_SINK_WRITABLE = ("destination", "filter", "description", "disabled", "exclusions",
                  "includeChildren", "bigqueryOptions", "outputVersionFormat")


def _destination_kind(dest):
    if dest.startswith("storage.googleapis.com/"):
        return "Cloud Storage bucket"
    if dest.startswith("bigquery.googleapis.com/"):
        return "BigQuery dataset"
    if dest.startswith("pubsub.googleapis.com/"):
        return "Pub/Sub topic"
    if dest.startswith("logging.googleapis.com/"):
        return "Cloud Logging bucket"
    return "Other"


def _validate_sink(s):
    dest = s.get("destination")
    if not dest or not _DEST_RE.match(dest):
        raise _bad("Field sink.destination is required and must be one of storage.googleapis.com/<bucket>, "
                    "bigquery.googleapis.com/projects/<p>/datasets/<d>, pubsub.googleapis.com/projects/<p>/topics/<t> "
                    "or logging.googleapis.com/projects/<p>/locations/<l>/buckets/<b>.")
    for ex in s.get("exclusions") or []:
        if not str(ex.get("name") or "").strip():
            raise _bad("Field sink.exclusions[].name is required.")


def create_sink(store, project, body, unique_writer_identity):
    sid = str(body.get("name") or "").strip()
    if not sid or not _LOGID_RE.match(sid) or len(sid) > 100:
        raise _bad("Field sink.name is required and must match [A-Za-z0-9_./-]{1,100}.")
    name = _sink_name(project, sid)
    if name in store.sinks:
        raise _E(409, "ALREADY_EXISTS", f"Sink {sid} already exists.")
    s = {k: _copy(v) for k, v in body.items() if k in _SINK_WRITABLE}
    _validate_sink(s)
    s["name"] = name
    s.setdefault("filter", "")
    s.setdefault("description", "")
    s["disabled"] = bool(s.get("disabled", False))
    s.setdefault("exclusions", [])
    s["includeChildren"] = bool(s.get("includeChildren", False))
    sa = f"serviceAccount:service-{abs(hash(name)) % 10**12}@gcp-sa-logging.iam.gserviceaccount.com"
    s["writerIdentity"] = sa if unique_writer_identity else "serviceAccount:cloud-logs@system.gserviceaccount.com"
    s["createTime"] = _now_iso(store)
    s["updateTime"] = s["createTime"]
    s["matchedCount"] = 0
    s["matchedBytes"] = 0
    store.sinks[name] = s
    store.persist()
    return _copy(s)


def _get_sink(store, project, sid):
    s = store.sinks.get(_sink_name(project, sid))
    if not s:
        raise _notfound(f"Sink {sid} does not exist.")
    return s


def patch_sink(store, project, sid, body, mask):
    cur = _get_sink(store, project, sid)
    merged = dict(cur)
    fields = [f.strip() for f in (mask or "").split(",") if f.strip()] or list(_SINK_WRITABLE)
    for f in fields:
        if f not in _SINK_WRITABLE:
            continue
        if f in body:
            merged[f] = _copy(body[f])
        elif mask:
            merged.pop(f, None)
    _validate_sink(merged)
    merged["disabled"] = bool(merged.get("disabled", False))
    merged["name"] = cur["name"]
    merged["writerIdentity"] = cur["writerIdentity"]
    merged["createTime"] = cur["createTime"]
    merged["updateTime"] = _now_iso(store)
    merged["matchedCount"] = cur.get("matchedCount", 0)
    merged["matchedBytes"] = cur.get("matchedBytes", 0)
    store.sinks[cur["name"]] = merged
    store.persist()
    return _copy(merged)


def delete_sink(store, project, sid):
    name = _sink_name(project, sid)
    if name not in store.sinks:
        raise _notfound(f"Sink {sid} does not exist.")
    del store.sinks[name]
    store.persist()


def list_sinks(store, project):
    prefix = f"projects/{project}/"
    items = sorted((s for n, s in store.sinks.items() if n.startswith(prefix)), key=lambda s: s["name"])
    return _json(200, {"sinks": [_copy(s) for s in items]} if items else {})


def _route_to_sinks(store, new_entries):
    for s in store.sinks.values():
        if s.get("disabled"):
            continue
        pred = compile_log_filter(s.get("filter") or "")
        for e in new_entries:
            if pred(e):
                s["matchedCount"] = s.get("matchedCount", 0) + 1
                s["matchedBytes"] = s.get("matchedBytes", 0) + len(json.dumps(e))


# ── log-based metrics ────────────────────────────────────────────────────────
def _metric_name(project, mid):
    return f"projects/{project}/metrics/{mid}"


_METRIC_WRITABLE = ("description", "filter", "metricDescriptor", "valueExtractor", "labelExtractors",
                    "bucketOptions", "disabled")


def _validate_metric(m):
    if not str(m.get("filter") or "").strip():
        raise _bad("Field metric.filter is required.")


def create_metric(store, project, body):
    mid = str(body.get("name") or "").strip()
    if not mid or not _LOGID_RE.match(mid) or len(mid) > 100:
        raise _bad("Field metric.name is required and must match [A-Za-z0-9_./-]{1,100}.")
    name = _metric_name(project, mid)
    if name in store.metrics:
        raise _E(409, "ALREADY_EXISTS", f"Metric {mid} already exists.")
    m = {k: _copy(v) for k, v in body.items() if k in _METRIC_WRITABLE}
    _validate_metric(m)
    m["name"] = name
    m.setdefault("description", "")
    m["disabled"] = bool(m.get("disabled", False))
    m.setdefault("metricDescriptor", {"metricKind": "DELTA", "valueType": "INT64", "unit": "1"})
    m["createTime"] = _now_iso(store)
    m["updateTime"] = m["createTime"]
    store.metrics[name] = m
    store.persist()
    return _copy(m)


def _get_metric(store, project, mid):
    m = store.metrics.get(_metric_name(project, mid))
    if not m:
        raise _notfound(f"Metric {mid} does not exist.")
    return m


def update_metric(store, project, mid, body):
    cur = _get_metric(store, project, mid)
    m = {k: _copy(v) for k, v in body.items() if k in _METRIC_WRITABLE}
    _validate_metric(m)
    for k in _METRIC_WRITABLE:
        m.setdefault(k, cur.get(k))
    m["disabled"] = bool(m.get("disabled", False))
    m["name"] = cur["name"]
    m["createTime"] = cur["createTime"]
    m["updateTime"] = _now_iso(store)
    store.metrics[cur["name"]] = m
    store.persist()
    return _copy(m)


def delete_metric(store, project, mid):
    name = _metric_name(project, mid)
    if name not in store.metrics:
        raise _notfound(f"Metric {mid} does not exist.")
    del store.metrics[name]
    store.persist()


def list_metrics(store, project):
    prefix = f"projects/{project}/"
    items = sorted((m for n, m in store.metrics.items() if n.startswith(prefix)), key=lambda m: m["name"])
    return _json(200, {"metrics": [_copy(m) for m in items]} if items else {})


def metric_usage(store, m, now_t):
    """Count of entries matching the metric's filter this/last calendar month — a real,
    live-derived stand-in for GCP's billed-bytes usage figures."""
    import calendar
    g = time.gmtime(now_t)
    cur_start = calendar.timegm((g.tm_year, g.tm_mon, 1, 0, 0, 0))
    py, pm = (g.tm_year - 1, 12) if g.tm_mon == 1 else (g.tm_year, g.tm_mon - 1)
    prev_start = calendar.timegm((py, pm, 1, 0, 0, 0))
    pred = compile_log_filter(m.get("filter") or "")
    cur = prev = 0
    for e in store.entries:
        if not pred(e):
            continue
        ts = _entry_ts(e)
        if ts >= cur_start:
            cur += 1
        elif prev_start <= ts < cur_start:
            prev += 1
    return prev, cur


# ── usage (Logs Storage "Create usage alert" / "View usage data") ──────────
_PROJECT_OF_LOGNAME = re.compile(r"^projects/([^/]+)/logs/")


def usage_snapshot(store, project, now_t=None):
    """Live month-to-date (bytes, entry count) ingested for `project` — the same figures
    Logs Storage shows, recomputed from store.entries."""
    import calendar
    now_t = store.now() if now_t is None else now_t
    g = time.gmtime(now_t)
    cur_start = calendar.timegm((g.tm_year, g.tm_mon, 1, 0, 0, 0))
    prefix = f"projects/{project}/logs/"
    nbytes = nentries = 0
    for e in store.entries:
        if not e.get("logName", "").startswith(prefix) or _entry_ts(e) < cur_start:
            continue
        nbytes += len(json.dumps(e, default=str))
        nentries += 1
    return nbytes, nentries


def _sync_usage_metrics(store, project):
    """Best-effort: mirror `project`'s live month-to-date usage into the shared Cloud
    Monitoring store as the real system metrics logging.googleapis.com/byte_count and
    .../log_entry_count, so Logs Storage's "Create usage alert" hands off to Monitoring's
    OWN alert-policy engine (real policy, real incident sweep) over a metric Vyomi actually
    keeps live — the same hand-off the real console makes, just onto a core this appliance
    runs, instead of leaving it not_simulated. Never raises: a metrics mirror must not be
    able to break log ingestion."""
    mon_store = store.mon_store
    if mon_store is None:
        return
    try:
        from core import gcp_monitoring_core as mon
        nbytes, nentries = usage_snapshot(store, project)
        end_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(store.now())) + ".000000Z"
        resource = {"type": "global", "labels": {"project_id": project}}
        mon.record_system_point(mon_store, project, "logging.googleapis.com/byte_count", resource, nbytes, end_iso, unit="By")
        mon.record_system_point(mon_store, project, "logging.googleapis.com/log_entry_count", resource, nentries, end_iso, unit="1")
    except Exception:
        pass


# ── log buckets + views (Logs Storage) ──────────────────────────────────────
def _bucket_name(project, location, bid):
    return f"projects/{project}/locations/{location}/buckets/{bid}"


def _seed_builtin_buckets(store, project, location):
    for bid in _PROTECTED_BUCKETS:
        name = _bucket_name(project, location, bid)
        if name not in store.buckets:
            store.buckets[name] = {
                "name": name, "description": "", "createTime": _now_iso(store), "updateTime": _now_iso(store),
                "retentionDays": 30 if bid == "_Default" else 400, "locked": False, "lifecycleState": "ACTIVE",
                "analyticsEnabled": False, "bigQueryDataset": None,
            }


_BUCKET_WRITABLE = ("description", "retentionDays", "locked", "analyticsEnabled", "cmekSettings", "indexConfigs")


def _validate_bucket(b):
    days = b.get("retentionDays", 30)
    if not isinstance(days, int) or not (1 <= days <= 3650):
        raise _bad("Field bucket.retention_days must be between 1 and 3650.")


def create_bucket(store, project, location, bucket_id, body):
    _seed_builtin_buckets(store, project, location)
    if not bucket_id or not _BUCKET_ID_RE.match(bucket_id):
        raise _bad("bucketId must match [A-Za-z0-9_-]{1,100}.")
    name = _bucket_name(project, location, bucket_id)
    if name in store.buckets:
        raise _E(409, "ALREADY_EXISTS", f"Bucket {bucket_id} already exists.")
    b = {k: _copy(v) for k, v in (body or {}).items() if k in _BUCKET_WRITABLE}
    b.setdefault("retentionDays", 30)
    _validate_bucket(b)
    b["name"] = name
    b.setdefault("description", "")
    b["locked"] = bool(b.get("locked", False))
    b["analyticsEnabled"] = bool(b.get("analyticsEnabled", False))
    b["bigQueryDataset"] = f"{bucket_id.replace('-', '_')}_dataset" if b["analyticsEnabled"] else None
    b["lifecycleState"] = "ACTIVE"
    b["createTime"] = _now_iso(store)
    b["updateTime"] = b["createTime"]
    store.buckets[name] = b
    store.persist()
    return _copy(b)


def _get_bucket(store, project, location, bid):
    _seed_builtin_buckets(store, project, location)
    b = store.buckets.get(_bucket_name(project, location, bid))
    if not b:
        raise _notfound(f"Bucket {bid} does not exist.")
    return b


def patch_bucket(store, project, location, bid, body, mask):
    cur = _get_bucket(store, project, location, bid)
    merged = dict(cur)
    fields = [f.strip() for f in (mask or "").split(",") if f.strip()] or [k for k in body if k in _BUCKET_WRITABLE]
    for f in fields:
        if f in _BUCKET_WRITABLE and f in body:
            merged[f] = _copy(body[f])
    _validate_bucket(merged)
    merged["analyticsEnabled"] = bool(merged.get("analyticsEnabled", False))
    merged["bigQueryDataset"] = (cur.get("bigQueryDataset") or f"{bid.replace('-', '_')}_dataset") if merged["analyticsEnabled"] else None
    merged["name"] = cur["name"]
    merged["lifecycleState"] = cur["lifecycleState"]
    merged["createTime"] = cur["createTime"]
    merged["updateTime"] = _now_iso(store)
    store.buckets[cur["name"]] = merged
    store.persist()
    return _copy(merged)


def delete_bucket(store, project, location, bid):
    if bid in _PROTECTED_BUCKETS:
        raise _bad(f"Bucket {bid} is a required bucket and cannot be deleted.")
    name = _bucket_name(project, location, bid)
    if name not in store.buckets:
        raise _notfound(f"Bucket {bid} does not exist.")
    del store.buckets[name]
    for v in [v for v in store.views if v.startswith(name + "/views/")]:
        del store.views[v]
    store.persist()


def list_buckets(store, project, location):
    if location != "-":
        _seed_builtin_buckets(store, project, location)
    prefix = f"projects/{project}/locations/{location}/buckets/" if location != "-" else f"projects/{project}/locations/"
    items = sorted((b for n, b in store.buckets.items() if n.startswith(prefix)), key=lambda b: b["name"])
    return _json(200, {"buckets": [_copy(b) for b in items]} if items else {})


def _view_name(bucket_name, vid):
    return f"{bucket_name}/views/{vid}"


def create_view(store, bucket_name, vid, body):
    if bucket_name not in store.buckets:
        raise _notfound("The parent bucket does not exist.")
    if not vid or not _LOGID_RE.match(vid) or len(vid) > 100:
        raise _bad("viewId must match [A-Za-z0-9_./-]{1,100}.")
    name = _view_name(bucket_name, vid)
    if name in store.views:
        raise _E(409, "ALREADY_EXISTS", f"View {vid} already exists.")
    v = {"name": name, "description": str((body or {}).get("description") or ""),
         "filter": str((body or {}).get("filter") or ""),
         "createTime": _now_iso(store)}
    v["updateTime"] = v["createTime"]
    store.views[name] = v
    store.persist()
    return _copy(v)


def list_views(store, bucket_name):
    items = sorted((v for n, v in store.views.items() if n.startswith(bucket_name + "/views/")), key=lambda v: v["name"])
    return _json(200, {"views": [_copy(v) for v in items]} if items else {})


def delete_view(store, bucket_name, vid):
    name = _view_name(bucket_name, vid)
    if name not in store.views:
        raise _notfound(f"View {vid} does not exist.")
    del store.views[name]
    store.persist()


# ── router (console REST, shared by Nano / offline / unified ingress) ──────
_P = r"[^/]+"


def dispatch(store: LoggingStore, method: str, path: str, query: dict | None = None,
            headers: dict | None = None, body: bytes | None = None) -> LogResponse:
    """Native Cloud Logging v2 REST router. `path` carries the `/v2/...` prefix."""
    query = query or {}
    method = method.upper()
    p = path.split("?", 1)[0]
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    try:
        if p == "/v2/entries:write" and method == "POST":
            return write_entries(store, None, payload)
        if p == "/v2/entries:list" and method == "POST":
            return list_entries(store, payload)

        m = re.match(rf"^/v2/projects/({_P})/logs$", p)
        if m and method == "GET":
            return list_logs(store, m.group(1), f"projects/{m.group(1)}/logs/")
        m = re.match(rf"^/v2/(projects/{_P}/logs/{_P})$", p)
        if m and method == "DELETE":
            return delete_log(store, m.group(1))

        m = re.match(rf"^/v2/projects/({_P})/sinks$", p)
        if m:
            project = m.group(1)
            if method == "GET":
                return list_sinks(store, project)
            if method == "POST":
                uwi = str(query.get("uniqueWriterIdentity", "false")).lower() == "true"
                s = create_sink(store, project, payload, uwi)
                return _json(200, s)
        m = re.match(rf"^/v2/projects/({_P})/sinks/({_P})$", p)
        if m:
            project, sid = m.groups()
            if method == "GET":
                return _json(200, _copy(_get_sink(store, project, sid)))
            if method in ("PUT", "PATCH"):
                return _json(200, patch_sink(store, project, sid, payload, query.get("updateMask")))
            if method == "DELETE":
                delete_sink(store, project, sid)
                return _json(200, {})

        m = re.match(rf"^/v2/projects/({_P})/metrics$", p)
        if m:
            project = m.group(1)
            if method == "GET":
                return list_metrics(store, project)
            if method == "POST":
                return _json(200, create_metric(store, project, payload))
        m = re.match(rf"^/v2/projects/({_P})/metrics/({_P})$", p)
        if m:
            project, mid = m.groups()
            if method == "GET":
                return _json(200, _copy(_get_metric(store, project, mid)))
            if method in ("PUT", "PATCH"):
                return _json(200, update_metric(store, project, mid, payload))
            if method == "DELETE":
                delete_metric(store, project, mid)
                return _json(200, {})

        m = re.match(rf"^/v2/projects/({_P})/locations/({_P})/buckets$", p)
        if m:
            project, location = m.groups()
            if method == "GET":
                return list_buckets(store, project, location)
            if method == "POST":
                b = create_bucket(store, project, location, query.get("bucketId"), payload)
                return _json(200, b)
        m = re.match(rf"^/v2/projects/({_P})/locations/({_P})/buckets/({_P})$", p)
        if m:
            project, location, bid = m.groups()
            if method == "GET":
                return _json(200, _copy(_get_bucket(store, project, location, bid)))
            if method in ("PUT", "PATCH"):
                return _json(200, patch_bucket(store, project, location, bid, payload, query.get("updateMask")))
            if method == "DELETE":
                delete_bucket(store, project, location, bid)
                return _json(200, {})
        m = re.match(rf"^/v2/(projects/{_P}/locations/{_P}/buckets/{_P})/views$", p)
        if m:
            bname = m.group(1)
            if method == "GET":
                return list_views(store, bname)
            if method == "POST":
                v = create_view(store, bname, query.get("viewId"), payload)
                return _json(200, v)
        m = re.match(rf"^/v2/(projects/{_P}/locations/{_P}/buckets/{_P})/views/({_P})$", p)
        if m:
            bname, vid = m.groups()
            if method == "GET":
                v = store.views.get(_view_name(bname, vid))
                if not v:
                    raise _notfound(f"View {vid} does not exist.")
                return _json(200, _copy(v))
            if method == "DELETE":
                delete_view(store, bname, vid)
                return _json(200, {})

        return _err(404, "NOT_FOUND", f"Unknown Cloud Logging endpoint: {method} {p}")
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
