"""GCP Cloud Logging core — substrate-independent. Speaks the native **Cloud Logging
REST API v2** (`/v2/entries:write`, `/v2/entries:list`, `/v2/projects/{p}/logs|sinks|
metrics|exclusions|locations/{l}/buckets...`) so `google-cloud-logging` and
`gcloud logging` work unchanged against it (point them at the endpoint).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, so the
SAME file runs offline and in Nano.

Resources (Discovery doc `logging/v2`):
    projects/{p}/logs/{log_id}                 (derived from written entries)
    projects/{p}/sinks/{sink}                  LogSink
    projects/{p}/metrics/{metric}              LogMetric
    projects/{p}/exclusions/{exclusion}        LogExclusion
    projects/{p}/locations/{l}/buckets/{b}     LogBucket (+ views/_AllLogs)
Methods: entries.write/list, monitoredResourceDescriptors.list, logs.list/delete,
sinks / metrics / exclusions create/get/list/update(patch)/delete, buckets
create/get/list/patch/delete/undelete, locations.list.

`entries.list` evaluates the Logging query language over the stored entries: AND / OR /
NOT (and `-`), parentheses, the comparison operators `= != > >= < <= : =~ !~`, field
paths (`resource.labels.zone`, `jsonPayload.a.b`, `severity>=ERROR`, `timestamp>="…"`)
and bare global-search terms. Sinks / metrics / exclusions filters are parsed with the
same grammar at create/update time, so an unparseable filter is INVALID_ARGUMENT exactly
as in the real service. Errors use the Google shape `{"error":{"code","message","status"}}`.
"""
from __future__ import annotations

import json
import re
import uuid
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote

SEVERITIES = ["DEFAULT", "DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"]
SEV_NUM = {n: i * 100 for i, n in enumerate(SEVERITIES)}
SEV_NAME = {v: k for k, v in SEV_NUM.items()}
LOCATIONS = ["global", "us", "eu", "us-central1", "us-east1", "us-east4", "us-west1", "europe-west1",
             "europe-west2", "europe-west4", "asia-east1", "asia-northeast1", "asia-south1",
             "asia-southeast1", "australia-southeast1"]
MAX_ENTRIES_PER_PROJECT = 5000
MAX_PAGE = 1000
DEFAULT_RETENTION = 30
_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")

# Proto enums are strings on the wire by default, but the Go / Java gapic REST clients send
# `$alt=json;enum-encoding=int` and expect integers back (and may send integers in bodies).
_ENUMS = {
    "severity": SEV_NUM,
    "lifecycleState": {"LIFECYCLE_STATE_UNSPECIFIED": 0, "ACTIVE": 1, "DELETE_REQUESTED": 2,
                       "UPDATING": 3, "CREATING": 4, "FAILED": 5},
    "version": {"V2": 0, "V1": 1},
    "outputVersionFormat": {"VERSION_FORMAT_UNSPECIFIED": 0, "V2": 1, "V1": 2},
    "metricKind": {"METRIC_KIND_UNSPECIFIED": 0, "GAUGE": 1, "DELTA": 2, "CUMULATIVE": 3},
    "valueType": {"VALUE_TYPE_UNSPECIFIED": 0, "BOOL": 1, "INT64": 2, "DOUBLE": 3, "STRING": 4,
                  "DISTRIBUTION": 5, "MONEY": 6},
}
_OPAQUE = ("jsonPayload", "protoPayload", "labels", "textPayload", "resource", "labelExtractors",
           "httpRequest", "operation", "sourceLocation", "metadata")


# ── store ──────────────────────────────────────────────────────────────────
class LoggingStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.entries: dict = {}      # project -> [LogEntry, ...] (oldest first)
        self.sinks: dict = {}        # "projects/p/sinks/id" -> LogSink
        self.metrics: dict = {}      # "projects/p/metrics/id" -> LogMetric
        self.exclusions: dict = {}   # "projects/p/exclusions/id" -> LogExclusion
        self.buckets: dict = {}      # "projects/p/locations/l/buckets/id" -> LogBucket


_SHARED: LoggingStore | None = None


def shared_store() -> LoggingStore:
    """The appliance-wide store: the native wire and the console REST share it."""
    global _SHARED
    if _SHARED is None:
        _SHARED = LoggingStore()
    return _SHARED


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


def _err(status, gcp_status, message):
    body = {"error": {"code": status, "message": message, "status": gcp_status}}
    return LogResponse(status=status, body=json.dumps(body).encode())


def _json(status, obj):
    return LogResponse(status=status, body=json.dumps(obj).encode())


def _now_dt():
    return datetime.now(timezone.utc)


def _ts(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_ts(s):
    """RFC 3339 → aware datetime (accepts Z / offsets / 0-9 fractional digits)."""
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)[Tt ](\d\d):(\d\d):(\d\d)(?:\.(\d+))?([Zz]|[+-]\d\d:?\d\d)?$", str(s).strip())
    if not m:
        raise ValueError("bad timestamp %r" % s)
    y, mo, d, h, mi, se, frac, tz = m.groups()
    dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(se), int((frac or "0")[:6].ljust(6, "0")), tzinfo=timezone.utc)
    if tz and tz not in "Zz":
        sign = 1 if tz[0] == "+" else -1
        t = tz[1:].replace(":", "")
        dt -= sign * timedelta(hours=int(t[:2]), minutes=int(t[2:]))
    return dt


def project_number(project):
    """Deterministic 12-digit project number derived from the project id."""
    return str(100000000000 + zlib.crc32(project.encode()) % 800000000000)


# ── filter language ────────────────────────────────────────────────────────
class FilterError(ValueError):
    pass


_OPS = (">=", "<=", "!=", "=~", "!~", "=", ">", "<", ":")


def _tokenize(text):
    toks, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            toks.append((c, c))
            i += 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    j += 1
                buf.append(text[j])
                j += 1
            if j >= n:
                raise FilterError("unterminated string")
            toks.append(("str", "".join(buf)))
            i = j + 1
        elif any(text.startswith(o, i) for o in _OPS):
            op = next(o for o in _OPS if text.startswith(o, i))
            toks.append(("op", op))
            i += len(op)
        elif c == "-" and i + 1 < n and not text[i + 1].isspace():
            toks.append(("not", "-"))
            i += 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '()"=!<>:~':
                j += 1
            if j == i:
                raise FilterError("unexpected character %r" % c)
            w = text[i:j]
            up = w.upper()
            toks.append((up if up in ("AND", "OR", "NOT") and w == up else "word", w))
            i = j
    return toks


class _Parser:
    """and := or (AND? or)* ; or := not (OR not)* ; not := (NOT|-)? atom"""

    def __init__(self, text):
        self.t = _tokenize(text)
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def eat(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        if not self.t:
            return ("true",)
        node = self.p_and()
        if self.i != len(self.t):
            raise FilterError("unexpected token %r" % (self.peek()[1],))
        return node

    def p_and(self):
        node = self.p_or()
        while self.peek()[0] in ("AND", "word", "str", "not", "NOT", "("):
            if self.peek()[0] == "AND":
                self.eat()
            node = ("and", node, self.p_or())
        return node

    def p_or(self):
        node = self.p_not()
        while self.peek()[0] == "OR":
            self.eat()
            node = ("or", node, self.p_not())
        return node

    def p_not(self):
        if self.peek()[0] in ("not", "NOT"):
            self.eat()
            return ("not", self.p_not())
        return self.p_atom()

    def p_atom(self):
        kind, val = self.peek()
        if kind == "(":
            self.eat()
            node = self.p_and()
            if self.eat()[0] != ")":
                raise FilterError("missing ')'")
            return node
        if kind in ("word", "str"):
            self.eat()
            if kind == "word" and self.peek()[0] == "op":
                op = self.eat()[1]
                vk, vv = self.eat()
                if vk == "(":   # field:(a OR b) — a value list
                    vals = []
                    while self.peek()[0] not in (")", None):
                        k2, v2 = self.eat()
                        if k2 in ("word", "str"):
                            vals.append(v2)
                    if self.eat()[0] != ")":
                        raise FilterError("missing ')'")
                    node = ("cmp", val, op, vals[0] if vals else "")
                    for v2 in vals[1:]:
                        node = ("or", node, ("cmp", val, op, v2))
                    return node
                if vk not in ("word", "str"):
                    raise FilterError("expected a value after %r" % op)
                return ("cmp", val, op, vv)
            return ("text", val)
        raise FilterError("unexpected %r" % (val,))


def parse_filter(text):
    return _Parser(text or "").parse()


def validate_filter(text, what="filter"):
    try:
        parse_filter(text)
    except FilterError as e:
        raise _E(400, "INVALID_ARGUMENT", "Unparseable filter: %s" % e)


def _lookup(entry, path):
    cur = entry
    for part in path.replace("`", "").split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _flatten(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _flatten(x)
    elif isinstance(v, list):
        for x in v:
            yield from _flatten(x)
    elif v is not None:
        yield str(v)


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _cmp_values(path, got, op, want):
    if path == "severity":
        g, w = SEV_NUM.get(str(got).upper()), SEV_NUM.get(str(want).upper(), _num(want))
        if g is None or w is None:
            return False
        return {"=": g == w, "!=": g != w, ">": g > w, ">=": g >= w, "<": g < w, "<=": g <= w,
                ":": g == w}.get(op, False)
    if path in ("timestamp", "receiveTimestamp") and op in ("=", "!=", ">", ">=", "<", "<="):
        try:
            g, w = _parse_ts(got), _parse_ts(want)
        except ValueError:
            return False
        return {"=": g == w, "!=": g != w, ">": g > w, ">=": g >= w, "<": g < w, "<=": g <= w}[op]
    if op in (">", ">=", "<", "<="):
        g, w = _num(got), _num(want)
        if g is None or w is None:
            g, w = str(got), str(want)
        return {">": g > w, ">=": g >= w, "<": g < w, "<=": g <= w}[op]
    gs = [s for s in _flatten(got)]
    if op in ("=", "!="):
        eq = any(s.lower() == str(want).lower() or (_num(s) is not None and _num(s) == _num(want)) for s in gs)
        return eq if op == "=" else (not eq and got is not None)
    if op == ":":
        if want == "*":
            return got is not None
        return any(str(want).lower() in s.lower() for s in gs)
    if op in ("=~", "!~"):
        try:
            rx = re.compile(str(want))
        except re.error:
            return False
        hit = any(rx.search(s) for s in gs)
        return hit if op == "=~" else (not hit and got is not None)
    return False


def _eval(node, entry):
    k = node[0]
    if k == "true":
        return True
    if k == "and":
        return _eval(node[1], entry) and _eval(node[2], entry)
    if k == "or":
        return _eval(node[1], entry) or _eval(node[2], entry)
    if k == "not":
        return not _eval(node[1], entry)
    if k == "text":
        needle = node[1].lower()
        return any(needle in s.lower() for s in _flatten(
            [entry.get("textPayload"), entry.get("jsonPayload"), entry.get("protoPayload"), entry.get("logName"),
             entry.get("labels"), entry.get("resource")]))
    _, path, op, want = node
    got = _lookup(entry, path)
    if got is None and op in ("=", ":", "=~", ">", ">=", "<", "<="):
        return False
    if got is None:
        return False
    return _cmp_values(path, got, op, want)


def matches(tree, entry):
    return _eval(tree, entry)


# ── helpers ────────────────────────────────────────────────────────────────
def _page(items, query, key):
    try:
        size = int(query.get("pageSize") or 0) or MAX_PAGE
        start = int(query.get("pageToken") or 0)
    except ValueError:
        raise _E(400, "INVALID_ARGUMENT", "Invalid page token or page size.")
    if size < 0:
        raise _E(400, "INVALID_ARGUMENT", "Page size must be non-negative.")
    size = min(size, MAX_PAGE)
    out = {key: [json.loads(json.dumps(x)) for x in items[start:start + size]]}
    if not out[key]:
        out = {}   # proto3 JSON omits empty repeated fields
    if start + size < len(items):
        out["nextPageToken"] = str(start + size)
    return out


def _norm_mask(mask):
    out = []
    for m in (mask or "").split(","):
        m = m.strip()
        if m:
            out.append(re.sub(r"_([a-z])", lambda x: x.group(1).upper(), m))
    return out


def _check_id(kind, ident):
    if not ident or not _ID.match(ident):
        raise _E(400, "INVALID_ARGUMENT", "%s name must be 1-100 characters of letters, numbers, '_', '-' and '.'; got %r." % (kind, ident))


def log_name(project, log_id):
    return "projects/%s/logs/%s" % (project, quote(unquote(log_id), safe=""))


def _norm_log_name(raw, default_project=None):
    m = re.match(r"^(projects|organizations|folders|billingAccounts)/([^/]+)/logs/(.+)$", str(raw or ""))
    if not m:
        raise _E(400, "INVALID_ARGUMENT", "Invalid log name %r: must be of the form projects/[PROJECT_ID]/logs/[LOG_ID]." % (raw,))
    return m.group(1), m.group(2), unquote(m.group(3))


# ── entries ────────────────────────────────────────────────────────────────
def _sev_in(v):
    if isinstance(v, int):
        if v not in SEV_NAME:
            raise _E(400, "INVALID_ARGUMENT", "Invalid severity %s." % v)
        return SEV_NAME[v]
    s = str(v).upper()
    if s not in SEV_NUM:
        raise _E(400, "INVALID_ARGUMENT", "Invalid severity %r." % (v,))
    return s


def write_entries(store, payload):
    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        raise _E(400, "INVALID_ARGUMENT", "entries must be a list.")
    dflt_log = payload.get("logName")
    dflt_res = payload.get("resource") or {}
    dflt_labels = payload.get("labels") or {}
    if dflt_log:
        _norm_log_name(dflt_log)
    staged = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise _E(400, "INVALID_ARGUMENT", "entries[%d] must be an object." % i)
        e = json.loads(json.dumps(e))
        name = e.get("logName") or dflt_log
        if not name:
            raise _E(400, "INVALID_ARGUMENT", "Log name must be specified (entries[%d])." % i)
        kind, owner, lid = _norm_log_name(name)
        if kind != "projects":
            raise _E(400, "INVALID_ARGUMENT", "Only project-scoped log names are supported; got %s." % name)
        if not lid or len(lid) > 512:
            raise _E(400, "INVALID_ARGUMENT", "Log ID must be 1-512 characters.")
        e["logName"] = log_name(owner, lid)
        res = e.get("resource") or dflt_res or {"type": "global"}
        if not res.get("type"):
            res = dict(res, type="global")
        e["resource"] = res
        labels = dict(dflt_labels)
        labels.update(e.get("labels") or {})
        if labels:
            e["labels"] = labels
        payloads = [k for k in ("textPayload", "jsonPayload", "protoPayload") if k in e]
        if len(payloads) > 1:
            raise _E(400, "INVALID_ARGUMENT", "Only one of textPayload, jsonPayload, protoPayload may be set.")
        e["severity"] = _sev_in(e["severity"]) if e.get("severity") not in (None, "") else "DEFAULT"
        try:
            e["timestamp"] = _ts(_parse_ts(e["timestamp"])) if e.get("timestamp") else _ts(_now_dt())
        except ValueError:
            raise _E(400, "INVALID_ARGUMENT", "Invalid timestamp in entries[%d]." % i)
        e["receiveTimestamp"] = _ts(_now_dt())
        e.setdefault("insertId", uuid.uuid4().hex[:20])
        staged.append((owner, e))
    if payload.get("dryRun"):
        return {}
    for owner, e in staged:
        lst = store.entries.setdefault(owner, [])
        lst.append(e)
        if len(lst) > MAX_ENTRIES_PER_PROJECT:
            del lst[:len(lst) - MAX_ENTRIES_PER_PROJECT]
    return {}


def list_entries(store, payload):
    names = payload.get("resourceNames") or ([("projects/" + p) for p in payload.get("projectIds", [])])
    if not names:
        raise _E(400, "INVALID_ARGUMENT", "resourceNames must contain at least one resource name.")
    projects, buckets = [], []
    for n in names:
        m = re.match(r"^projects/([^/]+)(/locations/[^/]+/buckets/[^/]+(?:/views/[^/]+)?)?$", str(n))
        if not m:
            raise _E(400, "INVALID_ARGUMENT", "Invalid resource name %r." % (n,))
        projects.append(m.group(1))
    flt = payload.get("filter") or ""
    validate_filter(flt)
    tree = parse_filter(flt)
    order = str(payload.get("orderBy") or "timestamp asc").strip().lower()
    if order not in ("timestamp asc", "timestamp desc", "timestamp", "receivetimestamp asc", "receivetimestamp desc"):
        raise _E(400, "INVALID_ARGUMENT", "Unsupported orderBy %r." % payload.get("orderBy"))
    rows = [e for p in dict.fromkeys(projects) for e in store.entries.get(p, []) if matches(tree, e)]
    key = "receiveTimestamp" if order.startswith("receive") else "timestamp"
    rows.sort(key=lambda e: e.get(key, ""), reverse=order.endswith("desc"))
    out = _page(rows, {"pageSize": payload.get("pageSize"), "pageToken": payload.get("pageToken")}, "entries")
    return out


def delete_log(store, project, log_id):
    name = log_name(project, log_id)
    lst = store.entries.get(project, [])
    keep = [e for e in lst if e["logName"] != name]
    if len(keep) == len(lst):
        raise _E(404, "NOT_FOUND", "Log %s does not exist." % name)
    store.entries[project] = keep
    return {}


def list_logs(store, project, query):
    names = sorted({e["logName"] for e in store.entries.get(project, [])})
    return _page(names, query, "logNames")


def log_summaries(store, project=None):
    """Console helper: per-log counts."""
    out = {}
    for p, lst in store.entries.items():
        if project and p != project:
            continue
        for e in lst:
            out.setdefault(e["logName"], 0)
            out[e["logName"]] += 1
    return out


MONITORED_RESOURCES = [
    ("global", "Global", "A resource type that is not associated with any specific resource.", ["project_id"]),
    ("gce_instance", "VM Instance", "A virtual machine instance hosted in Compute Engine.", ["project_id", "instance_id", "zone"]),
    ("gcs_bucket", "GCS Bucket", "A Cloud Storage bucket.", ["project_id", "bucket_name", "location"]),
    ("k8s_cluster", "Kubernetes Cluster", "A Kubernetes cluster.", ["project_id", "location", "cluster_name"]),
    ("k8s_container", "Kubernetes Container", "A Kubernetes container instance.",
     ["project_id", "location", "cluster_name", "namespace_name", "pod_name", "container_name"]),
    ("cloud_function", "Cloud Function", "A Cloud Function.", ["project_id", "function_name", "region"]),
    ("cloud_run_revision", "Cloud Run Revision", "A Cloud Run revision.", ["project_id", "service_name", "revision_name", "location", "configuration_name"]),
    ("cloud_scheduler_job", "Cloud Scheduler Job", "A Cloud Scheduler job.", ["project_id", "job_id", "location"]),
    ("pubsub_topic", "Cloud Pub/Sub Topic", "A Pub/Sub topic.", ["project_id", "topic_id"]),
    ("bigquery_resource", "BigQuery", "A BigQuery resource.", ["project_id"]),
]


def monitored_resource_descriptors(query):
    items = [{"type": t, "displayName": d, "description": desc,
              "labels": [{"key": k, "valueType": "STRING", "description": k.replace("_", " ").capitalize()} for k in ks],
              "name": "monitoredResourceDescriptors/" + t}
             for t, d, desc, ks in MONITORED_RESOURCES]
    return _page(items, query, "resourceDescriptors")


# ── sinks ──────────────────────────────────────────────────────────────────
_SINK_DEST = [
    (re.compile(r"^storage\.googleapis\.com/[a-z0-9][a-z0-9._-]{1,220}$"), "Cloud Storage bucket"),
    (re.compile(r"^bigquery\.googleapis\.com/projects/[^/]+/datasets/[^/]+$"), "BigQuery dataset"),
    (re.compile(r"^pubsub\.googleapis\.com/projects/[^/]+/topics/[^/]+$"), "Pub/Sub topic"),
    (re.compile(r"^logging\.googleapis\.com/projects/[^/]+/locations/[^/]+/buckets/[^/]+$"), "Cloud Logging bucket"),
    (re.compile(r"^logging\.googleapis\.com/projects/[^/]+$"), "Project"),
]
_SINK_FIELDS = ("destination", "filter", "description", "disabled", "exclusions", "outputVersionFormat",
                "includeChildren", "bigqueryOptions")
_SINK_DEFAULT_MASK = ("destination", "filter", "includeChildren")


def sink_destination_type(dest):
    for rx, label in _SINK_DEST:
        if rx.match(dest or ""):
            return label
    return "Unknown"


def _validate_sink(s):
    dest = s.get("destination") or ""
    if not dest:
        raise _E(400, "INVALID_ARGUMENT", "Sink destination must be provided.")
    if sink_destination_type(dest) == "Unknown":
        raise _E(400, "INVALID_ARGUMENT",
                 "Sink destination %r is not valid: expected storage.googleapis.com/[BUCKET], "
                 "bigquery.googleapis.com/projects/[P]/datasets/[D], pubsub.googleapis.com/projects/[P]/topics/[T], "
                 "or logging.googleapis.com/projects/[P]/locations/[L]/buckets/[B]." % dest)
    validate_filter(s.get("filter", ""))
    for ex in s.get("exclusions") or []:
        _check_id("Exclusion", ex.get("name", ""))
        validate_filter(ex.get("filter", ""))


def create_sink(store, project, payload, query):
    s = json.loads(json.dumps(payload or {}))
    sid = s.get("name") or ""
    _check_id("Sink", sid)
    full = "projects/%s/sinks/%s" % (project, sid)
    if full in store.sinks:
        raise _E(409, "ALREADY_EXISTS", "Sink %s already exists." % sid)
    _validate_sink(s)
    unique = str(query.get("uniqueWriterIdentity", "")).lower() == "true"
    now = _ts(_now_dt())
    rec = {k: s[k] for k in _SINK_FIELDS if k in s and s[k] not in (None, "")}
    if "outputVersionFormat" in rec:
        rec["outputVersionFormat"] = rec["outputVersionFormat"] if isinstance(rec["outputVersionFormat"], str) else "V2"
    rec.update({"name": sid, "outputVersionFormat": rec.get("outputVersionFormat", "V2"),
                "writerIdentity": ("serviceAccount:service-%s@gcp-sa-logging.iam.gserviceaccount.com" % project_number(project))
                if unique else "serviceAccount:cloud-logs@system.gserviceaccount.com",
                "createTime": now, "updateTime": now})
    store.sinks[full] = rec
    return rec


def _sink(store, project, sid):
    rec = store.sinks.get("projects/%s/sinks/%s" % (project, sid))
    if not rec:
        raise _E(404, "NOT_FOUND", "Sink %s does not exist." % sid)
    return rec


def update_sink(store, project, sid, payload, query):
    rec = _sink(store, project, sid)
    mask = _norm_mask(query.get("updateMask")) or list(_SINK_DEFAULT_MASK)
    body = payload or {}
    cand = dict(rec)
    for m in mask:
        if m not in _SINK_FIELDS:
            raise _E(400, "INVALID_ARGUMENT", "Invalid update mask path %r for LogSink." % m)
        if m in body:
            cand[m] = body[m]
        else:
            cand.pop(m, None)
    _validate_sink(cand)
    if str(query.get("uniqueWriterIdentity", "")).lower() == "true":
        cand["writerIdentity"] = "serviceAccount:service-%s@gcp-sa-logging.iam.gserviceaccount.com" % project_number(project)
    cand["updateTime"] = _ts(_now_dt())
    rec.clear()
    rec.update(cand)
    return rec


# ── metrics ────────────────────────────────────────────────────────────────
def _metric_defaults(project, mid, m):
    md = dict(m.get("metricDescriptor") or {})
    md.setdefault("name", "projects/%s/metricDescriptors/logging.googleapis.com/user/%s" % (project, mid))
    md.setdefault("type", "logging.googleapis.com/user/%s" % mid)
    md.setdefault("metricKind", "DELTA")
    md.setdefault("valueType", "INT64")
    md.setdefault("unit", "1")
    for k in ("metricKind", "valueType"):
        if isinstance(md[k], int):
            md[k] = {v: n for n, v in _ENUMS[k].items()}.get(md[k], md[k])
    return md


def _validate_metric(m):
    if not (m.get("filter") or "").strip():
        raise _E(400, "INVALID_ARGUMENT", "A log-based metric must have a non-empty filter.")
    validate_filter(m["filter"])


def create_metric(store, project, payload):
    m = json.loads(json.dumps(payload or {}))
    mid = m.get("name") or ""
    _check_id("Metric", mid)
    full = "projects/%s/metrics/%s" % (project, mid)
    if full in store.metrics:
        raise _E(409, "ALREADY_EXISTS", "Metric %s already exists." % mid)
    _validate_metric(m)
    now = _ts(_now_dt())
    rec = {k: m[k] for k in ("description", "filter", "disabled", "valueExtractor", "labelExtractors", "bucketOptions")
           if m.get(k) not in (None, "")}
    rec.update({"name": mid, "metricDescriptor": _metric_defaults(project, mid, m), "version": "V2",
                "createTime": now, "updateTime": now})
    store.metrics[full] = rec
    return rec


def _metric(store, project, mid):
    rec = store.metrics.get("projects/%s/metrics/%s" % (project, mid))
    if not rec:
        raise _E(404, "NOT_FOUND", "Metric %s does not exist." % mid)
    return rec


def update_metric(store, project, mid, payload):
    rec = _metric(store, project, mid)
    m = json.loads(json.dumps(payload or {}))
    m.setdefault("filter", rec.get("filter"))
    _validate_metric(m)
    new = {k: m[k] for k in ("description", "filter", "disabled", "valueExtractor", "labelExtractors", "bucketOptions")
           if m.get(k) not in (None, "")}
    new.update({"name": mid, "metricDescriptor": _metric_defaults(project, mid, m if m.get("metricDescriptor") else rec),
                "version": "V2", "createTime": rec["createTime"], "updateTime": _ts(_now_dt())})
    rec.clear()
    rec.update(new)
    return rec


# ── exclusions ─────────────────────────────────────────────────────────────
_EXCL_FIELDS = ("description", "filter", "disabled")


def create_exclusion(store, project, payload):
    x = json.loads(json.dumps(payload or {}))
    xid = x.get("name") or ""
    _check_id("Exclusion", xid)
    full = "projects/%s/exclusions/%s" % (project, xid)
    if full in store.exclusions:
        raise _E(409, "ALREADY_EXISTS", "Exclusion %s already exists." % xid)
    if not (x.get("filter") or "").strip():
        raise _E(400, "INVALID_ARGUMENT", "An exclusion must have a non-empty filter.")
    validate_filter(x["filter"])
    now = _ts(_now_dt())
    rec = {k: x[k] for k in _EXCL_FIELDS if x.get(k) not in (None, "")}
    rec.update({"name": xid, "createTime": now, "updateTime": now})
    store.exclusions[full] = rec
    return rec


def _exclusion(store, project, xid):
    rec = store.exclusions.get("projects/%s/exclusions/%s" % (project, xid))
    if not rec:
        raise _E(404, "NOT_FOUND", "Exclusion %s does not exist." % xid)
    return rec


def update_exclusion(store, project, xid, payload, query):
    rec = _exclusion(store, project, xid)
    mask = _norm_mask(query.get("updateMask"))
    if not mask:
        raise _E(400, "INVALID_ARGUMENT", "updateMask is required for exclusions.patch.")
    cand = dict(rec)
    for m in mask:
        if m not in _EXCL_FIELDS:
            raise _E(400, "INVALID_ARGUMENT", "Invalid update mask path %r for LogExclusion." % m)
        if m in (payload or {}):
            cand[m] = payload[m]
        else:
            cand.pop(m, None)
    if not (cand.get("filter") or "").strip():
        raise _E(400, "INVALID_ARGUMENT", "An exclusion must have a non-empty filter.")
    validate_filter(cand["filter"])
    cand["updateTime"] = _ts(_now_dt())
    rec.clear()
    rec.update(cand)
    return rec


# ── buckets ────────────────────────────────────────────────────────────────
def _ensure_default_buckets(store, project):
    now = _ts(_now_dt())
    for bid, days, locked, desc in (("_Default", DEFAULT_RETENTION, False, "Default bucket"),
                                    ("_Required", 400, True, "Audit bucket")):
        full = "projects/%s/locations/global/buckets/%s" % (project, bid)
        if full not in store.buckets:
            store.buckets[full] = {"name": full, "description": desc, "createTime": now, "updateTime": now,
                                   "retentionDays": days, "locked": locked, "lifecycleState": "ACTIVE"}


def _bucket_fields(b):
    return {k: b[k] for k in ("description", "retentionDays", "locked", "analyticsEnabled", "restrictedFields", "cmekSettings")
            if b.get(k) not in (None, "")}


def create_bucket(store, project, location, payload, query):
    if location not in LOCATIONS:
        raise _E(404, "NOT_FOUND", "Location '%s' is not a valid location." % location)
    bid = query.get("bucketId") or ""
    _check_id("Bucket", bid)
    if bid.startswith("_"):
        raise _E(400, "INVALID_ARGUMENT", "Bucket IDs starting with '_' are reserved.")
    _ensure_default_buckets(store, project)
    full = "projects/%s/locations/%s/buckets/%s" % (project, location, bid)
    if full in store.buckets:
        raise _E(409, "ALREADY_EXISTS", "Bucket %s already exists." % bid)
    b = _bucket_fields(payload or {})
    days = b.get("retentionDays", DEFAULT_RETENTION)
    if not isinstance(days, int) or not 1 <= days <= 3650:
        raise _E(400, "INVALID_ARGUMENT", "retentionDays must be between 1 and 3650.")
    now = _ts(_now_dt())
    rec = dict(b, name=full, retentionDays=days, createTime=now, updateTime=now, lifecycleState="ACTIVE")
    rec.setdefault("locked", False)
    store.buckets[full] = rec
    return rec


def _bucket(store, project, location, bid):
    _ensure_default_buckets(store, project)
    rec = store.buckets.get("projects/%s/locations/%s/buckets/%s" % (project, location, bid))
    if not rec:
        raise _E(404, "NOT_FOUND", "Bucket %s does not exist." % bid)
    return rec


def update_bucket(store, project, location, bid, payload, query):
    rec = _bucket(store, project, location, bid)
    if rec.get("lifecycleState") == "DELETE_REQUESTED":
        raise _E(400, "FAILED_PRECONDITION", "Bucket %s is pending deletion." % bid)
    mask = _norm_mask(query.get("updateMask"))
    if not mask:
        raise _E(400, "INVALID_ARGUMENT", "updateMask is required.")
    allowed = ("description", "retentionDays", "locked", "analyticsEnabled", "restrictedFields", "cmekSettings")
    for m in mask:
        if m not in allowed:
            raise _E(400, "INVALID_ARGUMENT", "Invalid update mask path %r for LogBucket." % m)
        if rec.get("locked") and m == "retentionDays" and (payload or {}).get(m, 0) < rec.get("retentionDays", 0):
            raise _E(400, "FAILED_PRECONDITION", "Cannot shorten retention of a locked bucket.")
        if m in (payload or {}):
            rec[m] = payload[m]
    if "retentionDays" in rec and not (isinstance(rec["retentionDays"], int) and 1 <= rec["retentionDays"] <= 3650):
        raise _E(400, "INVALID_ARGUMENT", "retentionDays must be between 1 and 3650.")
    rec["updateTime"] = _ts(_now_dt())
    return rec


def delete_bucket(store, project, location, bid):
    rec = _bucket(store, project, location, bid)
    if bid.startswith("_"):
        raise _E(400, "FAILED_PRECONDITION", "Bucket %s cannot be deleted." % bid)
    rec["lifecycleState"] = "DELETE_REQUESTED"
    rec["updateTime"] = _ts(_now_dt())
    return {}


def undelete_bucket(store, project, location, bid):
    rec = _bucket(store, project, location, bid)
    if rec.get("lifecycleState") != "DELETE_REQUESTED":
        raise _E(400, "FAILED_PRECONDITION", "Bucket %s is not pending deletion." % bid)
    rec["lifecycleState"] = "ACTIVE"
    rec["updateTime"] = _ts(_now_dt())
    return {}


def _view(bucket_name):
    return {"name": bucket_name + "/views/_AllLogs", "description": "Log view for all logs in the bucket",
            "createTime": "2020-01-01T00:00:00Z", "updateTime": "2020-01-01T00:00:00Z"}


# ── console ────────────────────────────────────────────────────────────────
def sink_console_view(project, rec):
    """Flat row for the console grid / detail: every column filled."""
    v = json.loads(json.dumps(rec))
    dest = rec.get("destination", "")
    v.update({
        "id": rec["name"], "resourceName": "projects/%s/sinks/%s" % (project, rec["name"]), "project": project,
        "region": "global", "location": "global",
        "destination_type": sink_destination_type(dest),
        "destination_name": dest.split("googleapis.com/", 1)[-1],
        "filter_text": rec.get("filter") or "All log entries (no filter)",
        "state": "Disabled" if rec.get("disabled") else "Enabled",
        "writer": rec.get("writerIdentity", ""),
        "description_text": rec.get("description") or "No description",
        "exclusion_count": len(rec.get("exclusions") or []),
        "include_children": "Yes" if rec.get("includeChildren") else "No",
        "created": rec.get("createTime", ""), "updated": rec.get("updateTime", ""),
    })
    return v


def list_all(store, project=None):
    return [sink_console_view(n.split("/")[1], r) for n, r in sorted(store.sinks.items())
            if project is None or n.startswith("projects/%s/" % project)]


def sink_from_form(b):
    """Console create form (catalog createFields) → REST LogSink. Shared by the offline
    console REST and the Nano adapter so both consoles create identical sinks."""
    dest_type = str(b.get("destinationType") or "Cloud Storage bucket")
    target = str(b.get("destination") or "").strip()
    project = str(b.get("project") or "demo")
    if dest_type == "Cloud Storage bucket":
        dest = "storage.googleapis.com/" + target
    elif dest_type == "BigQuery dataset":
        dest = "bigquery.googleapis.com/projects/%s/datasets/%s" % (project, target)
    elif dest_type == "Pub/Sub topic":
        dest = "pubsub.googleapis.com/projects/%s/topics/%s" % (project, target)
    else:
        dest = "logging.googleapis.com/projects/%s/locations/global/buckets/%s" % (project, target)
    sink = {"name": str(b.get("name") or "").strip(), "destination": dest}
    if b.get("filter"):
        sink["filter"] = str(b["filter"])
    if b.get("description"):
        sink["description"] = str(b["description"])
    return sink


# ── dispatch ───────────────────────────────────────────────────────────────
def _enum_out(obj, top=True):
    if isinstance(obj, list):
        return [_enum_out(x, top) for x in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        if k in _OPAQUE:
            out[k] = v
        elif k in _ENUMS and isinstance(v, str) and v in _ENUMS[k]:
            out[k] = _ENUMS[k][v]
        else:
            out[k] = _enum_out(v, False)
    return out


def _enum_in(obj):
    if isinstance(obj, list):
        return [_enum_in(x) for x in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        if k in _OPAQUE:
            out[k] = v
        elif k in _ENUMS and isinstance(v, int) and not isinstance(v, bool):
            out[k] = {num: name for name, num in _ENUMS[k].items()}.get(v, v)
        else:
            out[k] = _enum_in(v)
    return out


def _entries_enum_out(body):
    """Entries keep payloads opaque, but their top-level `severity` is an enum."""
    if isinstance(body, dict) and isinstance(body.get("entries"), list):
        body = dict(body, entries=[dict(e, severity=SEV_NUM.get(e.get("severity"), e.get("severity"))) if "severity" in e else e
                                   for e in body["entries"]])
    return body


def _wants_int_enums(query):
    return "enum-encoding=int" in (query.get("$alt") or query.get("alt") or "").replace("%3D", "=")


def dispatch(store, method, path, query=None, headers=None, body=b""):
    query = query or {}
    r = _dispatch(store, method, path, query, headers or {}, body)
    if r.status == 200 and _wants_int_enums(query):
        try:
            out = _enum_out(_entries_enum_out(json.loads(r.body)))
            r.body = json.dumps(out).encode()
        except Exception:
            pass
    return r


def _dispatch(store, method, path, query, headers, body):
    method = method.upper()
    for k, v in headers.items():   # REST clients without PATCH tunnel it over POST
        if k.lower() == "x-http-method-override" and method == "POST" and v:
            method = str(v).upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if not isinstance(payload, dict):
        payload = {}
    payload = _enum_in_payload(payload)
    p = path.split("?", 1)[0]
    for pre in ("/v2beta1", "/v2"):
        if p.startswith(pre + "/") or p == pre:
            p = p[len(pre):]
            break
    p = p.strip("/")
    verb = ""
    if ":" in p.rsplit("/", 1)[-1]:
        p, verb = p.rsplit(":", 1)
    segs = [s for s in p.split("/") if s]
    try:
        return _route(store, method, segs, verb, payload, query)
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)


def _enum_in_payload(payload):
    ents = payload.get("entries")
    if isinstance(ents, list):
        payload = dict(payload, entries=[dict(e, severity=SEV_NAME.get(e["severity"], e["severity"]))
                                         if isinstance(e, dict) and isinstance(e.get("severity"), int) else e for e in ents])
    keep = {k: payload.pop(k) for k in ("entries",) if k in payload}
    payload = _enum_in(payload)
    payload.update(keep)
    return payload


def _route(store, method, segs, verb, payload, query):
    if segs == ["entries"] and verb == "write" and method == "POST":
        return _json(200, write_entries(store, payload))
    if segs == ["entries"] and verb == "list" and method == "POST":
        return _json(200, list_entries(store, payload))
    if segs == ["monitoredResourceDescriptors"] and method == "GET":
        return _json(200, monitored_resource_descriptors(query))
    if len(segs) < 2 or segs[0] != "projects":
        return _err(404, "NOT_FOUND", "Unknown path: /%s" % "/".join(segs))
    project = segs[1]
    rest = segs[2:]
    if rest == ["locations"] and method == "GET":
        return _json(200, {"locations": [{"name": "projects/%s/locations/%s" % (project, l), "locationId": l,
                                          "labels": {"cloud.googleapis.com/region": l}} for l in LOCATIONS]})
    if rest and rest[0] == "logs":
        if len(rest) == 1 and method == "GET":
            return _json(200, list_logs(store, project, query))
        if len(rest) >= 2 and method == "DELETE":
            return _json(200, delete_log(store, project, "/".join(rest[1:])))
    elif rest and rest[0] == "sinks":
        if len(rest) == 1 and method == "POST":
            return _json(200, create_sink(store, project, payload, query))
        if len(rest) == 1 and method == "GET":
            return _json(200, _page([r for n, r in sorted(store.sinks.items()) if n.startswith("projects/%s/sinks/" % project)], query, "sinks"))
        if len(rest) == 2:
            if method == "GET":
                return _json(200, json.loads(json.dumps(_sink(store, project, rest[1]))))
            if method in ("PUT", "PATCH"):
                return _json(200, json.loads(json.dumps(update_sink(store, project, rest[1], payload, query))))
            if method == "DELETE":
                _sink(store, project, rest[1])
                del store.sinks["projects/%s/sinks/%s" % (project, rest[1])]
                return _json(200, {})
    elif rest and rest[0] == "metrics":
        if len(rest) == 1 and method == "POST":
            return _json(200, create_metric(store, project, payload))
        if len(rest) == 1 and method == "GET":
            return _json(200, _page([r for n, r in sorted(store.metrics.items()) if n.startswith("projects/%s/metrics/" % project)], query, "metrics"))
        if len(rest) == 2:
            if method == "GET":
                return _json(200, json.loads(json.dumps(_metric(store, project, rest[1]))))
            if method in ("PUT", "PATCH"):
                return _json(200, json.loads(json.dumps(update_metric(store, project, rest[1], payload))))
            if method == "DELETE":
                _metric(store, project, rest[1])
                del store.metrics["projects/%s/metrics/%s" % (project, rest[1])]
                return _json(200, {})
    elif rest and rest[0] == "exclusions":
        if len(rest) == 1 and method == "POST":
            return _json(200, create_exclusion(store, project, payload))
        if len(rest) == 1 and method == "GET":
            return _json(200, _page([r for n, r in sorted(store.exclusions.items()) if n.startswith("projects/%s/exclusions/" % project)], query, "exclusions"))
        if len(rest) == 2:
            if method == "GET":
                return _json(200, json.loads(json.dumps(_exclusion(store, project, rest[1]))))
            if method in ("PUT", "PATCH"):
                return _json(200, json.loads(json.dumps(update_exclusion(store, project, rest[1], payload, query))))
            if method == "DELETE":
                _exclusion(store, project, rest[1])
                del store.exclusions["projects/%s/exclusions/%s" % (project, rest[1])]
                return _json(200, {})
    elif len(rest) >= 3 and rest[0] == "locations" and rest[2] == "buckets":
        loc = rest[1]
        if len(rest) == 3 and method == "POST":
            return _json(200, json.loads(json.dumps(create_bucket(store, project, loc, payload, query))))
        if len(rest) == 3 and method == "GET":
            _ensure_default_buckets(store, project)
            return _json(200, _page([r for n, r in sorted(store.buckets.items())
                                     if n.startswith("projects/%s/locations/%s/buckets/" % (project, loc))], query, "buckets"))
        if len(rest) == 4:
            if verb == "undelete" and method == "POST":
                return _json(200, undelete_bucket(store, project, loc, rest[3]))
            if method == "GET":
                return _json(200, json.loads(json.dumps(_bucket(store, project, loc, rest[3]))))
            if method in ("PATCH", "PUT"):
                return _json(200, json.loads(json.dumps(update_bucket(store, project, loc, rest[3], payload, query))))
            if method == "DELETE":
                return _json(200, delete_bucket(store, project, loc, rest[3]))
        if len(rest) == 5 and rest[4] == "views" and method == "GET":
            b = _bucket(store, project, loc, rest[3])
            return _json(200, {"views": [_view(b["name"])]})
    return _err(404, "NOT_FOUND", "Unknown path or method: %s /%s" % (method, "/".join(segs)))
