# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Cloud Trace (v1 + v2) span store, Trace scopes (observability v1) and Log scopes (logging v2).

Substrate-independent (stdlib only). State lives on the Cloud Monitoring store (public dict attrs, so it
persists/syncs like the rest of Monitoring):
  store.traces        "project/traceId" -> {spanId: v2 Span}
  store.trace_scopes  full name -> TraceScope
  store.log_scopes    full name -> LogScope

Wire surface (what google-cloud-trace / gcloud / the console speak):
  POST   /v2/projects/{p}/traces:batchWrite              spans.batchWrite
  POST   /v2/projects/{p}/traces/{t}/spans/{s}           spans.createSpan
  PATCH  /v1/projects/{p}/traces                          patchTraces
  GET    /v1/projects/{p}/traces[/{t}]                    traces.list (filter / view / orderBy / paging) / get
  *      /v1/projects/{p}/locations/global/traceScopes    observability TraceScopes CRUD (+ _Default)
  *      /v2/projects/{p}/locations/global/logScopes      logging LogScopes CRUD (+ _Default)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
SPAN_ID = re.compile(r"^[0-9a-f]{16}$")
SCOPE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")
SPAN_NAME = re.compile(r"^projects/([^/]+)/traces/([0-9a-f]{32})/spans/([0-9a-f]{16})$")
MAX_BATCH = 1000
MAX_ATTRS = 32
MAX_TRACE_SCOPE_PROJECTS = 20
MAX_LOG_SCOPE_RESOURCES = 100
LOG_VIEW = re.compile(r"^projects/[^/]+/locations/[^/]+/buckets/[^/]+/views/[^/]+$")
PROJECT_RN = re.compile(r"^projects/[a-z][a-z0-9-]{4,28}[a-z0-9]$")
KIND_V1 = {"SERVER": "RPC_SERVER", "CLIENT": "RPC_CLIENT"}


class Resp:
    media_type = "application/json"

    def __init__(self, status, obj):
        self.status, self.headers = status, {}
        self.body = json.dumps(obj).encode()


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _bad(msg):
    return _E(400, "INVALID_ARGUMENT", msg)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _ns(store, attr):
    d = getattr(store, attr, None)
    if d is None:
        d = {}
        setattr(store, attr, d)
    return d


def _ts(v, field):
    if not isinstance(v, str):
        raise _bad("Invalid value for %s: expected an RFC 3339 timestamp." % field)
    try:
        s = v.replace("Z", "+00:00")
        s = re.sub(r"(\.\d{6})\d+", r"\1", s)
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        raise _bad("Invalid value for %s: %r is not an RFC 3339 timestamp." % (field, v))


def _page(items, query, key, default=100, cap=1000):
    try:
        size = int(query.get("pageSize") or default)
    except Exception:
        raise _bad("pageSize must be an integer.")
    if size < 0:
        raise _bad("pageSize must not be negative.")
    size = min(size or default, cap)
    try:
        off = int(query.get("pageToken") or 0)
    except Exception:
        raise _bad("Invalid pageToken.")
    out = {key: items[off:off + size]}
    if off + size < len(items):
        out["nextPageToken"] = str(off + size)
    return out


# ── spans ───────────────────────────────────────────────────────────────────
def _validate_span(project, sp):
    if not isinstance(sp, dict):
        raise _bad("Span must be an object.")
    m = SPAN_NAME.match(str(sp.get("name") or ""))
    if not m:
        raise _bad("Span name must be projects/{project}/traces/{32 hex}/spans/{16 hex}.")
    if m.group(1) != project:
        raise _bad("Span name project %r does not match the request project %r." % (m.group(1), project))
    if sp.get("spanId") != m.group(3):
        raise _bad("spanId must match the span id in name (%s)." % m.group(3))
    dn = (sp.get("displayName") or {}).get("value")
    if not dn:
        raise _bad("displayName.value is required.")
    if len(dn.encode()) > 128:
        raise _bad("displayName.value must be at most 128 bytes.")
    st, en = _ts(sp.get("startTime"), "startTime"), _ts(sp.get("endTime"), "endTime")
    if en < st:
        raise _bad("endTime must not be before startTime.")
    if sp.get("parentSpanId") and not SPAN_ID.match(sp["parentSpanId"]):
        raise _bad("parentSpanId must be 16 hex characters.")
    if sp.get("spanKind") and sp["spanKind"] not in ("SPAN_KIND_UNSPECIFIED", "INTERNAL", "SERVER", "CLIENT", "PRODUCER", "CONSUMER"):
        raise _bad("Invalid spanKind %r." % sp["spanKind"])
    attrs = (sp.get("attributes") or {}).get("attributeMap") or {}
    if len(attrs) > MAX_ATTRS:
        raise _bad("A span may have at most %d attributes." % MAX_ATTRS)
    return m.group(2), m.group(3)


def _store_span(store, project, sp):
    tid, sid = _validate_span(project, sp)
    rec = dict(sp)
    rec.setdefault("parentSpanId", "")
    _ns(store, "traces").setdefault("%s/%s" % (project, tid), {})[sid] = rec
    return rec


def batch_write(store, project, payload):
    spans = payload.get("spans")
    if not isinstance(spans, list) or not spans:
        raise _bad("spans is required and must not be empty.")
    if len(spans) > MAX_BATCH:
        raise _bad("A batch may contain at most %d spans." % MAX_BATCH)
    for sp in spans:   # all-or-nothing, like the real API
        _validate_span(project, sp)
    for sp in spans:
        _store_span(store, project, sp)
    return {}


def _v1_span(sp):
    labels = {}
    for k, v in ((sp.get("attributes") or {}).get("attributeMap") or {}).items():
        sv = v.get("stringValue", {}).get("value") if isinstance(v.get("stringValue"), dict) else None
        if sv is None and "intValue" in v:
            sv = str(v["intValue"])
        if sv is not None:
            labels[k] = sv
    out = {"spanId": sp["spanId"], "kind": KIND_V1.get(sp.get("spanKind"), "SPAN_KIND_UNSPECIFIED"),
           "name": sp["displayName"]["value"], "startTime": sp["startTime"], "endTime": sp["endTime"]}
    if sp.get("parentSpanId"):
        out["parentSpanId"] = sp["parentSpanId"]
    if labels:
        out["labels"] = labels
    return out


def patch_traces(store, project, payload):
    traces = payload.get("traces")
    if not isinstance(traces, list) or not traces:
        raise _bad("traces is required.")
    for t in traces:
        if t.get("projectId") not in (None, "", project):
            raise _bad("traces[].projectId must match the request project.")
        if not TRACE_ID.match(str(t.get("traceId") or "")):
            raise _bad("traceId must be 32 lowercase hex characters.")
        for s in t.get("spans") or []:
            if not s.get("spanId") or not str(s["spanId"]).isdigit():
                pass   # v1 span ids are uint64 decimals; hex v2 ids are also accepted below
    for t in traces:
        for s in t.get("spans") or []:
            sid = format(int(s["spanId"]), "016x") if str(s.get("spanId", "")).isdigit() else str(s.get("spanId"))
            if not SPAN_ID.match(sid):
                raise _bad("spanId must be a uint64.")
            psid = s.get("parentSpanId")
            sp = {"name": "projects/%s/traces/%s/spans/%s" % (project, t["traceId"], sid), "spanId": sid,
                  "displayName": {"value": s.get("name") or ""}, "startTime": s.get("startTime"), "endTime": s.get("endTime"),
                  "parentSpanId": format(int(psid), "016x") if psid and str(psid).isdigit() else (psid or ""),
                  "spanKind": {"RPC_SERVER": "SERVER", "RPC_CLIENT": "CLIENT"}.get(s.get("kind"), "SPAN_KIND_UNSPECIFIED"),
                  "attributes": {"attributeMap": {k: {"stringValue": {"value": v}} for k, v in (s.get("labels") or {}).items()}}}
            _store_span(store, project, sp)
    return {}


def _trace_view(project, tid, spans, view):
    ordered = sorted(spans.values(), key=lambda s: (_ts(s["startTime"], "startTime"), s["spanId"]))
    v1 = [_v1_span(s) for s in ordered]
    out = {"projectId": project, "traceId": tid}
    if view == "COMPLETE":
        out["spans"] = v1
    elif view == "ROOTSPAN":
        roots = [s for s in v1 if not s.get("parentSpanId")]
        out["spans"] = roots[:1]
    return out


def _bounds(spans):
    ss = [_ts(s["startTime"], "startTime") for s in spans.values()]
    ee = [_ts(s["endTime"], "endTime") for s in spans.values()]
    return min(ss), max(ee)


def _filter_match(spans, expr):
    """Cloud Trace v1 filter subset: bare/`span:`/`+span:` names, `root:`/`+root:`, `label:k[:v]`, `latency:Nms`, `-` NOT is unsupported."""
    names = [s["displayName"]["value"] for s in spans.values()]
    roots = [s["displayName"]["value"] for s in spans.values() if not s.get("parentSpanId")]
    for tok in re.findall(r'(?:[^\s"]+|"[^"]*")+', expr or ""):
        exact = tok.startswith("+")
        t = tok.lstrip("+").strip('"')
        key, _, val = t.partition(":")
        val = val.strip('"')
        if key == "root":
            hit = any((n == val) if exact else (val in n) for n in roots)
        elif key == "span":
            hit = any((n == val) if exact else (val in n) for n in names)
        elif key == "label":
            k, _, v = val.partition(":")
            hit = any(((_v1_span(s).get("labels") or {}).get(k) == v) if v else k in (_v1_span(s).get("labels") or {}) for s in spans.values())
        elif key == "latency":
            m = re.match(r"^(\d+)(ms|s|us)$", val)
            if not m:
                raise _bad("Invalid latency filter %r (use e.g. latency:100ms)." % val)
            lo, hi = _bounds(spans)
            ms = int(m.group(1)) * {"ms": 1, "s": 1000, "us": 0.001}[m.group(2)]
            hit = (hi - lo) >= timedelta(milliseconds=ms)
        elif key in ("method", "url"):
            hit = any(val in (_v1_span(s).get("labels") or {}).get("/http/" + key, "") for s in spans.values())
        else:
            hit = any(t in n for n in names)
        if not hit:
            return False
    return True


def list_traces(store, project, query):
    view = (query.get("view") or "MINIMAL").upper()
    if view not in ("MINIMAL", "ROOTSPAN", "COMPLETE", "VIEW_TYPE_UNSPECIFIED"):
        raise _bad("Invalid view %r." % view)
    lo = _ts(query["startTime"], "startTime") if query.get("startTime") else None
    hi = _ts(query["endTime"], "endTime") if query.get("endTime") else None
    if lo and hi and hi < lo:
        raise _bad("endTime must not be before startTime.")
    order = query.get("orderBy") or ""
    rows = []
    for key, spans in _ns(store, "traces").items():
        p, tid = key.split("/")
        if p != project or not spans:
            continue
        s0, e0 = _bounds(spans)
        if (lo and e0 < lo) or (hi and s0 > hi):
            continue
        if not _filter_match(spans, query.get("filter")):
            continue
        rows.append((tid, spans, s0, e0))
    desc = order.endswith(" desc")
    field = order.replace(" desc", "").strip()
    if field and field not in ("trace_id", "name", "start", "duration"):
        raise _bad("Invalid orderBy %r (trace_id, name, start, duration)." % order)
    keyf = {"trace_id": lambda r: r[0], "start": lambda r: r[2], "duration": lambda r: r[3] - r[2],
            "name": lambda r: sorted(r[1].values(), key=lambda s: _ts(s["startTime"], "startTime"))[0]["displayName"]["value"]}.get(field, lambda r: r[2])
    rows.sort(key=keyf, reverse=desc or not field)
    return _page([_trace_view(project, r[0], r[1], view) for r in rows], query, "traces")


def get_trace(store, project, tid):
    spans = _ns(store, "traces").get("%s/%s" % (project, tid))
    if not spans:
        raise _E(404, "NOT_FOUND", "Requested entity was not found.")
    return _trace_view(project, tid, spans, "COMPLETE")


# ── scopes ──────────────────────────────────────────────────────────────────
def _scope_default(kind, project):
    if kind == "trace":
        return {"name": "projects/%s/locations/global/traceScopes/_Default" % project, "description": "Default trace scope for the project.",
                "resourceNames": ["projects/%s" % project], "createTime": "2024-01-01T00:00:00Z", "updateTime": "2024-01-01T00:00:00Z"}
    return {"name": "projects/%s/locations/global/logScopes/_Default" % project, "description": "Default log scope for the project.",
            "resourceNames": ["projects/%s/locations/global/buckets/_Default/views/_AllLogs" % project],
            "createTime": "2024-01-01T00:00:00Z", "updateTime": "2024-01-01T00:00:00Z"}


def _check_resources(kind, project, names):
    if not isinstance(names, list) or not names:
        raise _bad("resourceNames is required and must not be empty.")
    if len(set(names)) != len(names):
        raise _bad("resourceNames must not contain duplicates.")
    if kind == "trace":
        if len(names) > MAX_TRACE_SCOPE_PROJECTS:
            raise _bad("A trace scope may include at most %d projects." % MAX_TRACE_SCOPE_PROJECTS)
        for n in names:
            if not PROJECT_RN.match(str(n)):
                raise _bad("Invalid resource name %r: expected projects/{project_id}." % n)
    else:
        if len(names) > MAX_LOG_SCOPE_RESOURCES:
            raise _bad("A log scope may include at most %d log views." % MAX_LOG_SCOPE_RESOURCES)
        for n in names:
            if not (LOG_VIEW.match(str(n)) or PROJECT_RN.match(str(n))):
                raise _bad("Invalid resource name %r: expected projects/{p}/locations/{l}/buckets/{b}/views/{v} or projects/{p}." % n)


def _scopes(store, kind, method, project, rest, query, payload):
    attr, coll = ("trace_scopes", "traceScopes") if kind == "trace" else ("log_scopes", "logScopes")
    ns = _ns(store, attr)
    base = "projects/%s/locations/global/%s/" % (project, coll)
    dflt = _scope_default(kind, project)
    if not rest:
        if method == "GET":
            items = [dflt] + sorted([v for n, v in ns.items() if n.startswith("projects/%s/" % project)], key=lambda v: v["name"])
            return _page(items, query, coll)
        if method == "POST":
            sid = query.get("traceScopeId" if kind == "trace" else "logScopeId") or ""
            if not SCOPE_ID.match(sid):
                raise _bad("%sScopeId is required: 1-100 characters of letters, digits, '_' and '-'." % kind)
            if sid == "_Default" or base + sid in ns:
                raise _E(409, "ALREADY_EXISTS", "Requested entity already exists")
            _check_resources(kind, project, payload.get("resourceNames"))
            if len(payload.get("description") or "") > 8000:
                raise _bad("description must be at most 8000 characters.")
            now = _now()
            sc = {"name": base + sid, "description": payload.get("description", ""), "resourceNames": list(payload["resourceNames"]),
                  "createTime": now, "updateTime": now}
            ns[sc["name"]] = sc
            return sc
        raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)
    sid = rest[0]
    name = base + sid
    cur = dflt if sid == "_Default" else ns.get(name)
    if cur is None:
        raise _E(404, "NOT_FOUND", "Requested entity was not found.")
    if method == "GET":
        return cur
    if sid == "_Default":
        raise _E(400, "FAILED_PRECONDITION", "The _Default scope cannot be modified or deleted.")
    if method == "DELETE":
        del ns[name]
        return {}
    if method == "PATCH":
        mask = [m for m in (query.get("updateMask") or "").split(",") if m] or [k for k in ("description", "resourceNames") if k in payload]
        for m in mask:
            if m not in ("description", "resourceNames"):
                raise _bad("Unsupported update_mask path %r." % m)
        if "resourceNames" in mask:
            _check_resources(kind, project, payload.get("resourceNames"))
        merged = dict(cur)
        for m in mask:
            merged[m] = payload.get(m, "" if m == "description" else merged[m])
        merged["updateTime"] = _now()
        ns[name] = merged
        return merged
    raise _E(405, "UNIMPLEMENTED", "Method %s not supported." % method)


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store, method, path, query=None, headers=None, body=b""):
    query, method = query or {}, method.upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        return _err(_bad("Invalid JSON payload received."))
    p = path.split("?", 1)[0].strip("/")
    verb = ""
    if ":" in p.rsplit("/", 1)[-1]:
        p, verb = p.rsplit(":", 1)
    segs = p.split("/")
    try:
        ver, project = segs[0], segs[2] if len(segs) > 2 else ""
        rest = segs[3:]
        if rest[:2] == ["locations", "global"] and len(rest) >= 3:
            if ver == "v1" and rest[2] == "traceScopes":
                out = _scopes(store, "trace", method, project, rest[3:], query, payload)
            elif ver == "v2" and rest[2] == "logScopes":
                out = _scopes(store, "log", method, project, rest[3:], query, payload)
            else:
                raise _E(404, "NOT_FOUND", "Unknown path: %s" % path)
            if method != "GET" and hasattr(store, "persist"):
                store.persist()
            return Resp(200, out)
        if rest[:1] != ["traces"]:
            raise _E(404, "NOT_FOUND", "Unknown path: %s" % path)
        if ver == "v2":
            if verb == "batchWrite" and method == "POST" and len(rest) == 1:
                out = batch_write(store, project, payload)
            elif len(rest) == 4 and rest[2] == "spans" and method == "POST":
                payload.setdefault("name", "projects/%s/traces/%s/spans/%s" % (project, rest[1], rest[3]))
                _store_span(store, project, payload)
                out = payload
            else:
                raise _E(404, "NOT_FOUND", "Unknown path: %s" % path)
            if hasattr(store, "persist"):
                store.persist()
            return Resp(200, out)
        if ver == "v1":
            if len(rest) == 1 and method == "GET":
                return Resp(200, list_traces(store, project, query))
            if len(rest) == 1 and method == "PATCH":
                out = patch_traces(store, project, payload)
                if hasattr(store, "persist"):
                    store.persist()
                return Resp(200, out)
            if len(rest) == 2 and method == "GET":
                return Resp(200, get_trace(store, project, rest[1]))
        raise _E(404, "NOT_FOUND", "Unknown path: %s" % path)
    except _E as e:
        return _err(e)


def _err(e):
    return Resp(e.status, {"error": {"code": e.status, "message": e.message, "status": e.gcp_status}})
