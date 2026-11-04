"""Observability stack core — shared request telemetry + OTLP/HTTP ingest + Jaeger query + Prometheus/Grafana backing.

Substrate-independent (stdlib only, Pyodide-loadable). One ``ObsStore`` holds everything measured:

  * the REQUEST-TELEMETRY RECORDER: every request a substrate serves is ``record()``-ed with its resource, operation, status
    and wall-clock latency. Per-resource cumulative counters + latency histograms and (sampled) auto-instrumented SERVER spans
    are derived from it. Nothing is invented: an idle resource has no samples.
  * OTLP/HTTP ingest (the OpenTelemetry-collector receiver): POST {base}/v1/traces|metrics|logs with the JSON encoding
    (``Content-Type: application/json``). Spans land in the trace store, metrics become Prometheus series, logs are kept.
    Protobuf bodies are rejected 415 (JSON encoding only — an honest limitation).
  * a Jaeger-compatible query API  (GET {base}/jaeger/api/services | services/{s}/operations | traces | traces/{id})
  * a Prometheus-compatible API    (GET/POST {base}/prom/api/v1/query | query_range | labels | label/{l}/values | series |
    metadata | status/buildinfo, {base}/prom/-/healthy, {base}/metrics) with a PromQL-lite evaluator (selectors with
    =, !=, =~, !~; rate/irate/increase/delta; sum/avg/min/max/count [by|without]; histogram_quantile; scalar arithmetic).
    That is exactly what a Grafana "Prometheus" data source (Azure Managed Grafana) speaks.
  * publishers that turn the measured requests into each cloud's native metric stores (CloudWatch, Cloud Monitoring) and
    into storage-account availability/latency metrics for Azure Monitor.

Base path for all of it: ``/_obs`` (an OTLP SDK given endpoint ``http://host/_obs`` posts to ``/_obs/v1/traces``).
"""
from __future__ import annotations

import bisect
import json
import math
import os
import re
import time
import uuid
from urllib.parse import unquote

BASE = "/_obs"
MAX_SPANS = 20000
MAX_SERIES_SAMPLES = 4000
MAX_LOGS = 5000
LOOKBACK = 300.0
BUCKETS_MS = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
HEX32, HEX16 = re.compile(r"^[0-9a-f]{32}$"), re.compile(r"^[0-9a-f]{16}$")


# ───────────────────────────── store ─────────────────────────────
class ObsStore:
    def __init__(self) -> None:
        self.auto_spans = True                  # sample every recorded request as an auto-instrumented span
        self.counters: dict = {}                # (cloud, service, resource, code) -> [(ts, n, dur_sum, bucket_counts)]
        self.recent: list = []                  # last raw rows (ts, cloud, service, resource, op, status, ms) for publishers
        self.spans: dict = {}                   # traceId -> [span dict]
        self.span_count = 0
        self.otlp_series: dict = {}             # (name, labels tuple) -> {"type","unit","help","samples":[(ts,v)]}
        self.logs: list = []
        self.pub_mark: dict = {}                # publisher watermarks

    def persist(self) -> None:
        """Flush hook (no-op in memory)."""


_DEFAULT = None


def default_store() -> ObsStore:
    """Process-wide recorder for the offline appliance (the Nano router owns its own ObsStore)."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ObsStore()
    return _DEFAULT


def get_store(holder) -> ObsStore:
    s = getattr(holder, "obs", None)
    if s is None:
        s = ObsStore()
        try:
            holder.obs = s
        except Exception:
            pass
    return s


def _hex(n: int) -> str:
    return uuid.uuid4().hex[: n] if n <= 32 else uuid.uuid4().hex


# ───────────────────────────── recorder ─────────────────────────────
def extract_resource(cloud: str, service: str, method: str, path: str, headers: dict | None = None, body: bytes = b"") -> tuple:
    """(resource, operation) for a request, best-effort per service. Empty resource when the request names none."""
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    segs = [unquote(s) for s in path.split("/") if s]
    low = [s.lower() for s in segs]
    op = ""
    res = ""
    svc = (service or "").lower()
    if svc in ("s3", "gcp-gcs", "gcs"):
        host = (h.get("host") or "").split(":")[0]
        if low[:1] == ["api"] and "buckets" in low:           # console REST: /api/aws/s3/buckets/{name}/...
            res = segs[low.index("buckets") + 1] if low.index("buckets") + 1 < len(segs) else ""
        elif cloud == "gcp" and "b" in low[:4]:
            res = segs[low.index("b") + 1] if low.index("b") + 1 < len(segs) else ""
        elif host.count(".") >= 2 and "s3" in host.split(".", 1)[1]:
            res = host.split(".", 1)[0]
        else:
            res = segs[0] if segs else ""
        if low[:1] == ["api"] and not res:
            res = ""
        op = {"GET": "GetObject" if len(segs) > 1 else "ListObjects", "PUT": "PutObject", "DELETE": "DeleteObject",
              "HEAD": "HeadObject", "POST": "PostObject"}.get(method.upper(), method.upper())
        if len(segs) <= (0 if host.count(".") >= 2 else 1) and method.upper() == "PUT":
            op = "CreateBucket"
    elif svc == "lambda":
        for i, s in enumerate(low):
            if s == "functions" and i + 1 < len(segs):
                res = segs[i + 1]
                break
        op = "Invoke" if "invocations" in low else ("Lambda:" + method.upper())
    elif svc in ("dynamodb", "ddb"):
        tgt = h.get("x-amz-target", "")
        op = tgt.split(".")[-1]
        try:
            res = (json.loads(body or b"{}") or {}).get("TableName", "")
        except Exception:
            res = ""
        if not res and "tables" in low and low.index("tables") + 1 < len(segs):
            res = segs[low.index("tables") + 1]
    elif svc in ("sqs", "sns"):
        if len(segs) >= 2 and segs[0].isdigit():
            res = segs[1]
        try:
            op = (h.get("x-amz-target", "").split(".")[-1]) or ""
        except Exception:
            op = ""
    elif svc in ("rds", "rds-data"):
        try:
            d = json.loads(body or b"{}")
            res = d.get("DBInstanceIdentifier") or d.get("resourceArn", "").split(":")[-1]
        except Exception:
            res = ""
    elif cloud == "azure":
        for k in ("accounts", "storageaccounts", "sites", "servers", "databaseaccounts", "service", "virtualmachines"):
            if k in low and low.index(k) + 1 < len(segs):
                res = segs[low.index(k) + 1]
                break
        if not res and segs:
            res = segs[0]
        op = method.upper()
    elif cloud == "gcp":
        for k in ("instances", "functions", "services", "topics", "subscriptions", "buckets", "clusters"):
            if k in low and low.index(k) + 1 < len(segs):
                res = segs[low.index(k) + 1].split(":")[0]
                break
        op = method.upper()
    else:
        op = method.upper()
    return res, op


def _cls(status: int) -> str:
    return "%dxx" % (int(status) // 100)


def record(obs: ObsStore, cloud: str, service: str, resource: str, op: str, status: int, ms: float,
           ts: float | None = None, traceparent: str = "", nbytes_in: int = 0, nbytes_out: int = 0) -> None:
    """Record ONE measured request."""
    ts = ts if ts is not None else time.time()
    k = (cloud or "", service or "", resource or "", _cls(status))
    lst = obs.counters.setdefault(k, [])
    if lst:
        _, n, ssum, bk = lst[-1]
        bk = list(bk)
    else:
        n, ssum, bk = 0, 0.0, [0] * (len(BUCKETS_MS) + 1)
    i = bisect.bisect_left(BUCKETS_MS, ms)
    for j in range(i, len(bk)):                                   # cumulative le-buckets (last = +Inf)
        bk[j] += 1
    lst.append((ts, n + 1, ssum + float(ms), tuple(bk)))
    if len(lst) > MAX_SERIES_SAMPLES:
        del lst[: len(lst) - MAX_SERIES_SAMPLES]
    obs.recent.append((ts, cloud or "", service or "", resource or "", op or "", int(status), float(ms), int(nbytes_in), int(nbytes_out)))
    if len(obs.recent) > 20000:
        del obs.recent[:5000]
    if obs.auto_spans:
        tid, pid = _parse_traceparent(traceparent)
        sp = {"traceId": tid or _hex(32), "spanId": _hex(16), "parentSpanId": pid or "", "name": (op or "request") + (" " + resource if resource else ""),
              "kind": 2, "startTimeUnixNano": int((ts - ms / 1000.0) * 1e9), "endTimeUnixNano": int(ts * 1e9),
              "attributes": {"vyomi.auto": True, "cloud.provider": cloud, "service": service, "resource": resource, "operation": op,
                             "http.status_code": int(status)},
              "status": {"code": 2 if status >= 500 else 0}, "service": "%s-%s" % (cloud or "vyomi", service or "api")}
        _add_span(obs, sp)


def _parse_traceparent(tp: str) -> tuple:
    m = re.match(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$", (tp or "").strip())
    return (m.group(1), m.group(2)) if m else ("", "")


def _add_span(obs: ObsStore, sp: dict) -> None:
    obs.spans.setdefault(sp["traceId"], []).append(sp)
    obs.span_count += 1
    while obs.span_count > MAX_SPANS and obs.spans:
        old = next(iter(obs.spans))
        obs.span_count -= len(obs.spans.pop(old))


# ───────────────────────────── rollups / latency analytics ─────────────────────────────
def _pct(vals: list, q: float) -> float:
    if not vals:
        return 0.0
    vals = sorted(vals)
    return round(vals[min(len(vals) - 1, int(q * len(vals)))], 3)


def rollup(obs: ObsStore, cloud: str = "", service: str = "", resource: str = "", since: float = 0.0, until: float | None = None,
           by_op: bool = False) -> dict:
    """{(cloud, service, resource[, op]): {count, errors, p50, p95, p99, avg, bytes_in, bytes_out}} over measured rows."""
    until = until if until is not None else time.time() + 1
    groups: dict = {}
    for ts, c, s, r, op, st, ms, bi, bo in obs.recent:
        if ts < since or ts > until or (cloud and c != cloud) or (service and s != service) or (resource and r != resource):
            continue
        g = groups.setdefault((c, s, r, op) if by_op else (c, s, r), {"lat": [], "errors": 0, "e4": 0, "e5": 0, "bi": 0, "bo": 0})
        g["lat"].append(ms)
        if st >= 400:
            g["errors"] += 1
        if 400 <= st < 500:
            g["e4"] += 1
        if st >= 500:
            g["e5"] += 1
        g["bi"] += bi
        g["bo"] += bo
    out = {}
    for k, g in groups.items():
        lat = g["lat"]
        out[k] = {"count": len(lat), "errors": g["errors"], "errors4xx": g["e4"], "errors5xx": g["e5"],
                  "p50": _pct(lat, .5), "p95": _pct(lat, .95), "p99": _pct(lat, .99), "avg": round(sum(lat) / len(lat), 3),
                  "max": round(max(lat), 3), "bytes_in": g["bi"], "bytes_out": g["bo"]}
    return out


def trace_latency_stats(obs: ObsStore, service: str = "", start_ns: int = 0, end_ns: int | None = None, bins: int = 12) -> dict:
    """Cloud Trace-explorer data: root-span latency percentiles + a time x latency heatmap, from real spans."""
    end_ns = end_ns if end_ns is not None else int(time.time() * 1e9) + 1
    durs, pts = [], []
    for spans in obs.spans.values():
        roots = [s for s in spans if not s.get("parentSpanId")] or spans[:1]
        for s in roots:
            if service and s.get("service") != service:
                continue
            if not (start_ns <= int(s["startTimeUnixNano"]) <= end_ns):
                continue
            d = (int(s["endTimeUnixNano"]) - int(s["startTimeUnixNano"])) / 1e6
            durs.append(d)
            pts.append((int(s["startTimeUnixNano"]), d))
    out = {"count": len(durs), "p50_ms": _pct(durs, .5), "p90_ms": _pct(durs, .9), "p95_ms": _pct(durs, .95), "p99_ms": _pct(durs, .99),
           "heatmap": {"latencyBucketsMs": [], "timeBuckets": [], "cells": []}}
    if not pts:
        return out
    lo, hi = min(p[0] for p in pts), max(p[0] for p in pts)
    span = max(1, hi - lo)
    mx = max(durs)
    edges = [0.0] + [mx * (2 ** (i - bins + 1)) if i < bins else mx for i in range(1, bins + 1)]
    edges = sorted(set(round(e, 3) for e in edges))
    cells = [[0] * (len(edges)) for _ in range(bins)]
    for t, d in pts:
        ti = min(bins - 1, int((t - lo) / span * bins))
        li = max(0, bisect.bisect_left(edges, d) - 1) if d > 0 else 0
        cells[ti][min(li, len(edges) - 1)] += 1
    out["heatmap"] = {"latencyBucketsMs": edges, "timeBuckets": [lo + int(span * i / bins) for i in range(bins)], "cells": cells}
    return out


# ───────────────────────────── OTLP/HTTP ingest ─────────────────────────────
def _attrs(lst) -> dict:
    out = {}
    for a in lst or []:
        v = a.get("value") or {}
        for kk in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if kk in v:
                x = v[kk]
                out[a.get("key", "")] = int(x) if kk == "intValue" else x
                break
        else:
            out[a.get("key", "")] = json.dumps(v)
    return out


def _b64hex(v: str, n: int) -> str:
    """OTLP JSON carries ids as hex; tolerate base64 (what the proto3 JSON mapping would give)."""
    if re.fullmatch(r"[0-9a-fA-F]{%d}" % n, v or ""):
        return v.lower()
    import base64
    try:
        raw = base64.b64decode(v)
        return raw.hex() if len(raw) * 2 == n else ""
    except Exception:
        return ""


def ingest_traces(obs: ObsStore, payload: dict) -> dict:
    rejected, msgs = 0, []
    for rs in payload.get("resourceSpans") or []:
        rattr = _attrs((rs.get("resource") or {}).get("attributes"))
        svc = rattr.get("service.name") or "unknown_service"
        for ss in rs.get("scopeSpans") or []:
            for sp in ss.get("spans") or []:
                tid, sid = _b64hex(sp.get("traceId", ""), 32), _b64hex(sp.get("spanId", ""), 16)
                pid = _b64hex(sp.get("parentSpanId", ""), 16) if sp.get("parentSpanId") else ""
                try:
                    st, en = int(sp.get("startTimeUnixNano", 0)), int(sp.get("endTimeUnixNano", 0))
                except (TypeError, ValueError):
                    st = en = 0
                if not tid or not sid or not sp.get("name") or en < st or not st:
                    rejected += 1
                    msgs.append("span %r rejected: needs 32-hex traceId, 16-hex spanId, name and start<=end" % sp.get("name"))
                    continue
                kind = sp.get("kind", 0)
                kind = {"SPAN_KIND_INTERNAL": 1, "SPAN_KIND_SERVER": 2, "SPAN_KIND_CLIENT": 3, "SPAN_KIND_PRODUCER": 4,
                        "SPAN_KIND_CONSUMER": 5}.get(kind, kind) if isinstance(kind, str) else kind
                status = sp.get("status") or {}
                code = status.get("code", 0)
                code = {"STATUS_CODE_ERROR": 2, "STATUS_CODE_OK": 1}.get(code, code) if isinstance(code, str) else code
                _add_span(obs, {"traceId": tid, "spanId": sid, "parentSpanId": pid, "name": sp["name"], "kind": int(kind or 0),
                                "startTimeUnixNano": st, "endTimeUnixNano": en, "attributes": {**rattr, **_attrs(sp.get("attributes"))},
                                "status": {"code": int(code or 0), "message": status.get("message", "")},
                                "events": sp.get("events") or [], "service": svc})
    obs.persist()
    out = {}
    if rejected:
        out["partialSuccess"] = {"rejectedSpans": rejected, "errorMessage": "; ".join(msgs[:5])}
    return out


def ingest_metrics(obs: ObsStore, payload: dict) -> dict:
    n = 0
    for rm in payload.get("resourceMetrics") or []:
        rattr = _attrs((rm.get("resource") or {}).get("attributes"))
        job = rattr.get("service.name", "")
        for sm in rm.get("scopeMetrics") or []:
            for m in sm.get("metrics") or []:
                name = re.sub(r"[^a-zA-Z0-9_:]", "_", m.get("name", ""))
                if not name:
                    continue
                kind = next((k for k in ("gauge", "sum", "histogram") if k in m), None)
                if not kind:
                    continue
                for dp in (m[kind].get("dataPoints") or []):
                    lab = {"job": job, **{re.sub(r"[^a-zA-Z0-9_]", "_", k): str(v) for k, v in _attrs(dp.get("attributes")).items()}}
                    ts = int(dp.get("timeUnixNano") or time.time() * 1e9) / 1e9

                    def put(nm, val, extra=None, typ="gauge"):
                        key = (nm, tuple(sorted({**lab, **(extra or {})}.items())))
                        s = obs.otlp_series.setdefault(key, {"type": typ, "unit": m.get("unit", ""), "help": m.get("description", ""), "samples": []})
                        s["samples"].append((ts, float(val)))
                        del s["samples"][:-MAX_SERIES_SAMPLES]
                    if kind == "histogram":
                        put(name + "_count", dp.get("count", 0), typ="counter")
                        put(name + "_sum", dp.get("sum", 0), typ="counter")
                        cum, bounds = 0, dp.get("explicitBounds") or []
                        for i, c in enumerate(dp.get("bucketCounts") or []):
                            cum += int(c)
                            put(name + "_bucket", cum, {"le": repr(float(bounds[i])) if i < len(bounds) else "+Inf"}, "counter")
                    else:
                        val = dp.get("asDouble", dp.get("asInt", 0))
                        put(name, val, typ="counter" if kind == "sum" and m["sum"].get("isMonotonic") else "gauge")
                    n += 1
    return {}


def ingest_logs(obs: ObsStore, payload: dict) -> dict:
    for rl in payload.get("resourceLogs") or []:
        rattr = _attrs((rl.get("resource") or {}).get("attributes"))
        for sl in rl.get("scopeLogs") or []:
            for lr in sl.get("logRecords") or []:
                body = lr.get("body") or {}
                obs.logs.append({"time": int(lr.get("timeUnixNano") or time.time() * 1e9), "severity": lr.get("severityText", ""),
                                 "body": body.get("stringValue", json.dumps(body)), "traceId": lr.get("traceId", ""),
                                 "spanId": lr.get("spanId", ""), "service": rattr.get("service.name", ""), "attributes": _attrs(lr.get("attributes"))})
    del obs.logs[:-MAX_LOGS]
    return {}


# ───────────────────────────── Jaeger query ─────────────────────────────
def _jaeger_trace(tid: str, spans: list) -> dict:
    procs, pmap, out = {}, {}, []
    for s in spans:
        svc = s.get("service", "unknown_service")
        if svc not in pmap:
            pmap[svc] = "p%d" % (len(pmap) + 1)
            procs[pmap[svc]] = {"serviceName": svc, "tags": []}
        tags = [{"key": k, "type": "string" if isinstance(v, str) else ("bool" if isinstance(v, bool) else "float64"), "value": v}
                for k, v in (s.get("attributes") or {}).items()]
        if (s.get("status") or {}).get("code") == 2:
            tags.append({"key": "error", "type": "bool", "value": True})
        out.append({"traceID": tid, "spanID": s["spanId"], "operationName": s["name"], "flags": 1,
                    "references": [{"refType": "CHILD_OF", "traceID": tid, "spanID": s["parentSpanId"]}] if s.get("parentSpanId") else [],
                    "startTime": int(s["startTimeUnixNano"]) // 1000, "duration": (int(s["endTimeUnixNano"]) - int(s["startTimeUnixNano"])) // 1000,
                    "tags": tags, "logs": [], "processID": pmap[svc]})
    return {"traceID": tid, "spans": out, "processes": procs}


def jaeger(obs: ObsStore, path: str, query: dict) -> tuple:
    """(status, obj) for GET /api/services | /api/services/{s}/operations | /api/traces | /api/traces/{id}."""
    segs = [s for s in path.split("/") if s]
    if segs[:2] == ["api", "services"] and len(segs) == 2:
        svcs = sorted({s.get("service", "") for sp in obs.spans.values() for s in sp})
        return 200, {"data": svcs, "total": len(svcs), "limit": 0, "offset": 0, "errors": None}
    if segs[:2] == ["api", "services"] and len(segs) == 4 and segs[3] == "operations":
        ops = sorted({s["name"] for sp in obs.spans.values() for s in sp if s.get("service") == unquote(segs[2])})
        return 200, {"data": ops, "total": len(ops), "errors": None}
    if segs[:2] == ["api", "traces"] and len(segs) == 3:
        tid = segs[2].lower().zfill(32)
        if tid not in obs.spans:
            return 404, {"data": None, "errors": [{"code": 404, "msg": "trace not found"}]}
        return 200, {"data": [_jaeger_trace(tid, obs.spans[tid])], "errors": None}
    if segs[:2] == ["api", "traces"] and len(segs) == 2:
        svc, op = query.get("service", ""), query.get("operation", "")
        if not svc:
            return 400, {"data": None, "errors": [{"code": 400, "msg": "parameter 'service' is required"}]}
        lim = int(query.get("limit") or 20)
        mn = int(query.get("minDuration", "0").rstrip("mus") or 0) if query.get("minDuration") else 0
        res = []
        for tid, spans in reversed(list(obs.spans.items())):
            if not any(s.get("service") == svc and (not op or s["name"] == op) for s in spans):
                continue
            if mn and max((int(s["endTimeUnixNano"]) - int(s["startTimeUnixNano"])) // 1000 for s in spans) < mn:
                continue
            res.append(_jaeger_trace(tid, spans))
            if len(res) >= lim:
                break
        return 200, {"data": res, "errors": None}
    return 404, {"errors": [{"code": 404, "msg": "unknown Jaeger API path"}]}


# ───────────────────────────── Prometheus data model ─────────────────────────────
def _all_series(obs: ObsStore) -> list:
    """[(name, labels dict, kind, samples [(ts, value)])] — recorder-derived + OTLP-ingested."""
    out = []
    for (cloud, service, resource, code), lst in obs.counters.items():
        base = {"cloud": cloud, "service": service, "resource": resource, "code": code}
        ts = [x[0] for x in lst]
        out.append(("vyomi_requests_total", base, "counter", list(zip(ts, [x[1] for x in lst]))))
        out.append(("vyomi_request_duration_ms_count", base, "counter", list(zip(ts, [x[1] for x in lst]))))
        out.append(("vyomi_request_duration_ms_sum", base, "counter", list(zip(ts, [round(x[2], 6) for x in lst]))))
        for bi in range(len(BUCKETS_MS) + 1):
            le = repr(float(BUCKETS_MS[bi])) if bi < len(BUCKETS_MS) else "+Inf"
            out.append(("vyomi_request_duration_ms_bucket", {**base, "le": le}, "counter", list(zip(ts, [x[3][bi] for x in lst]))))
    for (name, lab), s in obs.otlp_series.items():
        out.append((name, dict(lab), s["type"], s["samples"]))
    return out


METRIC_HELP = {"vyomi_requests_total": ("counter", "Requests served, measured per cloud/service/resource/status class."),
               "vyomi_request_duration_ms": ("histogram", "Measured request latency in milliseconds.")}


def exposition(obs: ObsStore, now: float | None = None) -> str:
    """Prometheus text exposition of the latest value of every series (what a scraper pulls from /_obs/metrics)."""
    lines, seen = [], set()
    for name, lab, kind, samples in _all_series(obs):
        if not samples:
            continue
        if name not in seen:
            seen.add(name)
            base = re.sub(r"_(total|count|sum|bucket)$", "", name)
            lines.append("# TYPE %s %s" % (name, "counter" if kind == "counter" else "gauge"))
        lab_s = ",".join('%s="%s"' % (k, str(v).replace("\\", "\\\\").replace('"', '\\"')) for k, v in sorted(lab.items()) if v != "")
        lines.append("%s%s %s" % (name, "{" + lab_s + "}" if lab_s else "", _fmt(samples[-1][1])))
    return "\n".join(lines) + "\n"


def _fmt(v: float) -> str:
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


# ───────────────────────────── PromQL-lite ─────────────────────────────
class PromError(Exception):
    def __init__(self, typ, msg):
        super().__init__(msg)
        self.typ, self.msg = typ, msg


_TOK = re.compile(r'\s*(?:(?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(?P<id>[a-zA-Z_:][a-zA-Z0-9_:]*)|(?P<str>"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')|(?P<op>=~|!~|!=|==|[{}()\[\],=+\-*/%]))')
_DUR = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
AGGS = {"sum", "avg", "min", "max", "count"}
FUNCS = {"rate", "irate", "increase", "delta", "histogram_quantile", "abs", "ceil", "floor", "round", "clamp_min", "clamp_max"}


def _tokenize(q: str) -> list:
    toks, pos = [], 0
    q = q.strip()
    while pos < len(q):
        m = _TOK.match(q, pos)
        if not m or m.end() == pos:
            raise PromError("bad_data", "parse error: unexpected character %r at position %d" % (q[pos:pos + 1].strip() or q[pos:pos + 2], pos))
        pos = m.end()
        kind = m.lastgroup
        toks.append((kind, m.group(kind)))
    return toks


def _dur(s: str) -> float:
    m = re.fullmatch(r"(\d+)([smhdw])", s)
    if not m:
        raise PromError("bad_data", "parse error: bad duration %r" % s)
    return int(m.group(1)) * _DUR[m.group(2)]


class _P:
    def __init__(self, q):
        self.t, self.i = _tokenize(q), 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def eat(self, v=None):
        k, x = self.peek()
        if k is None or (v is not None and x != v):
            raise PromError("bad_data", "parse error: expected %r, got %r" % (v, x))
        self.i += 1
        return x

    def parse(self):
        e = self.expr()
        if self.i != len(self.t):
            raise PromError("bad_data", "parse error: unexpected %r" % (self.peek()[1],))
        return e

    def expr(self, prec=0):
        left = self.unary()
        ops = {"+": 1, "-": 1, "*": 2, "/": 2, "%": 2}
        while True:
            k, x = self.peek()
            if k == "op" and x in ops and ops[x] > prec:
                self.i += 1
                right = self.expr(ops[x])
                left = ("bin", x, left, right)
            else:
                return left

    def unary(self):
        k, x = self.peek()
        if k == "op" and x == "-":
            self.i += 1
            return ("bin", "-", ("num", 0.0), self.unary())
        return self.primary()

    def primary(self):
        k, x = self.peek()
        if k == "num":
            self.i += 1
            return ("num", float(x))
        if k == "op" and x == "(":
            self.i += 1
            e = self.expr()
            self.eat(")")
            return e
        if k == "id":
            if x in AGGS and self._agg_follows():
                return self.agg()
            if x in FUNCS and self.peek(1)[1] == "(":
                self.i += 1
                self.eat("(")
                args = [self.expr()]
                while self.peek()[1] == ",":
                    self.i += 1
                    args.append(self.expr())
                self.eat(")")
                return ("fn", x, args)
            return self.selector()
        if k == "op" and x == "{":
            return self.selector()
        raise PromError("bad_data", "parse error: unexpected %r" % (x,))

    def _agg_follows(self):
        return self.peek(1)[1] in ("(", ) or self.peek(1)[1] in ("by", "without")

    def agg(self):
        op = self.eat()
        mode, labels = None, []

        def grouping():
            nonlocal mode, labels
            if self.peek()[1] in ("by", "without"):
                mode = self.eat()
                self.eat("(")
                while self.peek()[1] != ")":
                    labels.append(self.eat())
                    if self.peek()[1] == ",":
                        self.i += 1
                self.eat(")")
        grouping()
        self.eat("(")
        e = self.expr()
        self.eat(")")
        grouping()
        return ("agg", op, mode, labels, e)

    def selector(self):
        name = None
        if self.peek()[0] == "id":
            name = self.eat()
        matchers = []
        if self.peek()[1] == "{":
            self.i += 1
            while self.peek()[1] != "}":
                ln = self.eat()
                mo = self.eat()
                if mo not in ("=", "!=", "=~", "!~"):
                    raise PromError("bad_data", "parse error: bad matcher operator %r" % mo)
                kk, vv = self.peek()
                if kk != "str":
                    raise PromError("bad_data", "parse error: matcher value must be a string")
                self.i += 1
                matchers.append((ln, mo, bytes(vv[1:-1], "utf-8").decode("unicode_escape")))
                if self.peek()[1] == ",":
                    self.i += 1
            self.eat("}")
        if name is None and not matchers:
            raise PromError("bad_data", "parse error: vector selector must contain at least one non-empty matcher")
        if name:
            matchers.append(("__name__", "=", name))
        rng = None
        if self.peek()[1] == "[":
            self.i += 1
            num = self.eat()
            unit = self.eat()
            rng = _dur(num + unit)
            self.eat("]")
        return ("sel", matchers, rng)


def _match(lab: dict, matchers) -> bool:
    for ln, op, val in matchers:
        v = lab.get(ln, "")
        if op == "=" and v != val:
            return False
        if op == "!=" and v == val:
            return False
        if op == "=~" and not re.fullmatch(val, v):
            return False
        if op == "!~" and re.fullmatch(val, v):
            return False
    return True


def _select(series, matchers) -> list:
    return [(name, lab, samples) for name, lab, _k, samples in series if _match({**lab, "__name__": name}, matchers)]


def _key(lab: dict) -> tuple:
    return tuple(sorted(lab.items()))


def _at(samples, t):
    i = bisect.bisect_right([s[0] for s in samples], t) - 1
    if i < 0 or t - samples[i][0] > LOOKBACK:
        return None
    return samples[i][1]


def _window(samples, t, w):
    return [s for s in samples if t - w < s[0] <= t]


def _eval(node, series, t):
    """Instant-evaluate -> ("scalar", v) | ("vector", {labelkey: (labels, value)})"""
    k = node[0]
    if k == "num":
        return ("scalar", node[1])
    if k == "sel":
        _, matchers, rng = node
        if rng is not None:
            raise PromError("bad_data", "invalid expression type \"range vector\" for instant query")
        vec = {}
        for name, lab, samples in _select(series, matchers):
            v = _at(samples, t)
            if v is not None:
                full = {"__name__": name, **lab}
                vec[_key(full)] = (full, v)
        return ("vector", vec)
    if k == "fn":
        fn, args = node[1], node[2]
        if fn in ("rate", "irate", "increase", "delta"):
            if not args or args[0][0] != "sel" or args[0][2] is None:
                raise PromError("bad_data", "parse error: %s() expects a range vector argument" % fn)
            _, matchers, rng = args[0]
            vec = {}
            for name, lab, samples in _select(series, matchers):
                w = _window(samples, t, rng)
                if len(w) < 2:
                    continue
                if fn == "irate":
                    (t0, v0), (t1, v1) = w[-2], w[-1]
                    val = (v1 - v0) / (t1 - t0) if t1 > t0 else 0.0
                else:
                    inc = w[-1][1] - w[0][1]
                    if fn in ("rate", "increase") and inc < 0:
                        inc = w[-1][1]                          # counter reset
                    val = inc / (w[-1][0] - w[0][0]) if fn == "rate" and w[-1][0] > w[0][0] else (0.0 if fn == "rate" else inc)
                vec[_key(lab)] = (dict(lab), val)
            return ("vector", vec)
        if fn == "histogram_quantile":
            q = _eval(args[0], series, t)[1]
            kind, vec = _eval(args[1], series, t)
            groups = {}
            for _, (lab, v) in vec.items():
                if "le" not in lab:
                    continue
                g = {a: b for a, b in lab.items() if a not in ("le", "__name__")}
                groups.setdefault(_key(g), (g, []))[1].append((float(lab["le"].replace("+Inf", "inf")), v))
            out = {}
            for gk, (g, bs) in groups.items():
                bs.sort()
                total = bs[-1][1]
                if total <= 0:
                    continue
                rank, lo_b, lo_c, val = q * total, 0.0, 0.0, bs[-1][0]
                for ub, c in bs:
                    if c >= rank:
                        val = lo_b if math.isinf(ub) else lo_b + (ub - lo_b) * ((rank - lo_c) / (c - lo_c) if c > lo_c else 0)
                        break
                    lo_b, lo_c = ub, c
                out[gk] = (g, val)
            return ("vector", out)
        kind, vec = _eval(args[0], series, t)
        f = {"abs": abs, "ceil": math.ceil, "floor": math.floor, "round": round}.get(fn)
        if fn in ("clamp_min", "clamp_max"):
            lim = _eval(args[1], series, t)[1]
            f = (lambda x: max(x, lim)) if fn == "clamp_min" else (lambda x: min(x, lim))
        if kind == "scalar":
            return ("scalar", f(vec))
        return ("vector", {kk: ({a: b for a, b in lab.items() if a != "__name__"}, f(v)) for kk, (lab, v) in vec.items()})
    if k == "agg":
        _, op, mode, labels, e = node
        kind, vec = _eval(e, series, t)
        if kind != "vector":
            raise PromError("bad_data", "aggregation requires an instant vector")
        groups = {}
        for _, (lab, v) in vec.items():
            lab = {a: b for a, b in lab.items() if a != "__name__"}
            if mode == "by":
                g = {a: lab[a] for a in labels if a in lab}
            elif mode == "without":
                g = {a: b for a, b in lab.items() if a not in labels}
            else:
                g = {}
            groups.setdefault(_key(g), (g, []))[1].append(v)
        f = {"sum": sum, "avg": lambda x: sum(x) / len(x), "min": min, "max": max, "count": len}[op]
        return ("vector", {gk: (g, float(f(vs))) for gk, (g, vs) in groups.items()})
    if k == "bin":
        _, op, a, b = node
        ka, va = _eval(a, series, t)
        kb, vb = _eval(b, series, t)
        fn = {"+": lambda x, y: x + y, "-": lambda x, y: x - y, "*": lambda x, y: x * y,
              "/": lambda x, y: x / y if y else float("nan"), "%": lambda x, y: math.fmod(x, y) if y else float("nan")}[op]
        if ka == "scalar" and kb == "scalar":
            return ("scalar", fn(va, vb))
        if ka == "vector" and kb == "scalar":
            return ("vector", {kk: ({x: y for x, y in lab.items() if x != "__name__"}, fn(v, vb)) for kk, (lab, v) in va.items()})
        if ka == "scalar" and kb == "vector":
            return ("vector", {kk: ({x: y for x, y in lab.items() if x != "__name__"}, fn(va, v)) for kk, (lab, v) in vb.items()})
        out = {}
        strip = lambda lab: {x: y for x, y in lab.items() if x != "__name__"}
        for _, (la, v1) in va.items():
            for _, (lb, v2) in vb.items():
                if strip(la) == strip(lb):
                    out[_key(strip(la))] = (strip(la), fn(v1, v2))
        return ("vector", out)
    raise PromError("bad_data", "unsupported expression")


def _num(v: float) -> str:
    if isinstance(v, float) and math.isnan(v):
        return "NaN"
    return _fmt(float(v))


def query_instant(obs: ObsStore, q: str, t: float | None = None) -> dict:
    t = t if t is not None else time.time()
    ast = _P(q).parse()
    kind, val = _eval(ast, _all_series(obs), t)
    if kind == "scalar":
        return {"resultType": "scalar", "result": [t, _num(val)]}
    return {"resultType": "vector", "result": [{"metric": lab, "value": [t, _num(v)]} for lab, v in val.values()]}


def query_range(obs: ObsStore, q: str, start: float, end: float, step: float) -> dict:
    if step <= 0:
        raise PromError("bad_data", "zero or negative query resolution step widths are not accepted. Try a positive integer")
    if end < start:
        raise PromError("bad_data", "end timestamp must not be before start time")
    if (end - start) / step > 11000:
        raise PromError("bad_data", "exceeded maximum resolution of 11,000 points per timeseries. Try decreasing the query resolution (?step=XX)")
    ast = _P(q).parse()
    series = _all_series(obs)
    res, t = {}, start
    while t <= end + 1e-9:
        kind, val = _eval(ast, series, t)
        if kind == "scalar":
            res.setdefault((), ({}, []))[1].append([t, _num(val)])
        else:
            for kk, (lab, v) in val.items():
                res.setdefault(kk, (lab, []))[1].append([t, _num(v)])
        t += step
    return {"resultType": "matrix", "result": [{"metric": lab, "values": vals} for lab, vals in res.values()]}


# ───────────────────────────── HTTP-shaped dispatch ─────────────────────────────
class Resp:
    def __init__(self, status, obj=None, body=None, ctype="application/json"):
        self.status = status
        self.headers = {"Content-Type": ctype}
        self.media_type = ctype
        self.body = body if body is not None else json.dumps(obj).encode()


def _prom_err(e: PromError, status=400) -> Resp:
    return Resp(status, {"status": "error", "errorType": e.typ, "error": e.msg})


def _ts(v, default):
    if v in (None, ""):
        return default
    try:
        return float(v)
    except ValueError:
        from datetime import datetime
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except ValueError:
            raise PromError("bad_data", "invalid parameter: cannot parse %r to a valid timestamp" % v)


def _form(body: bytes) -> dict:
    from urllib.parse import parse_qsl
    return dict(parse_qsl((body or b"").decode("utf-8", "replace")))


def dispatch(obs: ObsStore, method: str, path: str, query: dict | None = None, headers: dict | None = None, body: bytes = b"") -> Resp:
    """Serve one /_obs/... request. `path` may include the /_obs prefix."""
    query = dict(query or {})
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    p = path.split("?", 1)[0]
    if p.startswith(BASE):
        p = p[len(BASE):]
    p = p or "/"
    m = method.upper()
    try:
        if m == "POST" and p in ("/v1/traces", "/v1/metrics", "/v1/logs"):
            ct = (h.get("content-type") or "").split(";")[0].strip().lower()
            if ct != "application/json":
                return Resp(415, {"code": 415, "message": "this OTLP receiver accepts the JSON encoding (Content-Type: application/json); "
                                                          "protobuf is not supported"})
            try:
                payload = json.loads(body or b"{}")
            except ValueError:
                return Resp(400, {"code": 3, "message": "invalid JSON body"})
            if not isinstance(payload, dict):
                return Resp(400, {"code": 3, "message": "body must be a JSON object"})
            fn = {"/v1/traces": ingest_traces, "/v1/metrics": ingest_metrics, "/v1/logs": ingest_logs}[p]
            return Resp(200, fn(obs, payload))
        if p.startswith("/jaeger/") and m == "GET":
            st, o = jaeger(obs, p[len("/jaeger"):], query)
            return Resp(st, o)
        if p == "/metrics" and m == "GET":
            return Resp(200, body=exposition(obs).encode(), ctype="text/plain; version=0.0.4")
        if p in ("/prom/-/healthy", "/prom/-/ready"):
            return Resp(200, body=b"Prometheus Server is Healthy.\n", ctype="text/plain")
        if p.startswith("/prom/api/v1/"):
            return _prom_api(obs, m, p[len("/prom/api/v1/"):], {**query, **(_form(body) if m == "POST" else {})})
        if p == "/trace-stats" and m == "GET":
            return Resp(200, trace_latency_stats(obs, query.get("service", "")))
        if p == "/rollup" and m == "GET":
            r = rollup(obs, query.get("cloud", ""), query.get("service", ""), query.get("resource", ""),
                       since=time.time() - float(query.get("seconds", 3600)))
            return Resp(200, {"resources": [{"cloud": k[0], "service": k[1], "resource": k[2], **v} for k, v in r.items()]})
        return Resp(404, {"error": "unknown observability path %s" % p})
    except PromError as e:
        return _prom_err(e)


def _prom_api(obs: ObsStore, m: str, rest: str, q: dict) -> Resp:
    ok = lambda data: Resp(200, {"status": "success", "data": data})
    now = time.time()
    if rest == "query":
        if not q.get("query"):
            raise PromError("bad_data", "invalid parameter \"query\": no expression")
        return ok(query_instant(obs, q["query"], _ts(q.get("time"), now)))
    if rest == "query_range":
        if not q.get("query"):
            raise PromError("bad_data", "invalid parameter \"query\": no expression")
        step = q.get("step", "60")
        try:
            step_s = float(step)
        except ValueError:
            step_s = _dur(step)
        return ok(query_range(obs, q["query"], _ts(q.get("start"), now - 3600), _ts(q.get("end"), now), step_s))
    series = _all_series(obs)
    if rest == "labels":
        names = {"__name__"}
        for _, lab, _k, _s in series:
            names.update(lab)
        return ok(sorted(names))
    mm = re.fullmatch(r"label/([^/]+)/values", rest)
    if mm:
        ln, vals = unquote(mm.group(1)), set()
        for name, lab, _k, _s in series:
            if ln == "__name__":
                vals.add(name)
            elif ln in lab and lab[ln] != "":
                vals.add(lab[ln])
        return ok(sorted(vals))
    if rest == "series":
        sel = q.get("match[]") or q.get("match")
        if not sel:
            raise PromError("bad_data", "no match[] parameter provided")
        node = _P(sel).parse()
        if node[0] != "sel":
            raise PromError("bad_data", "match[] must be a series selector")
        return ok([{"__name__": n, **lab} for n, lab, _s in _select(series, node[1])])
    if rest == "metadata":
        out = {}
        for name, _lab, kind, _s in series:
            out.setdefault(name, [{"type": kind, "help": "", "unit": ""}])
        return ok(out)
    if rest == "status/buildinfo":
        return ok({"version": "2.54.0-vyomi", "revision": "vyomi", "branch": "main", "buildUser": "vyomi", "buildDate": "", "goVersion": "n/a"})
    if rest == "status/config":
        return ok({"yaml": "# vyomi observability: scrape = /_obs/metrics, ingest = OTLP/HTTP\n"})
    if rest == "rules" or rest == "alerts":
        return ok({"groups": []} if rest == "rules" else {"alerts": []})
    if rest in ("targets",):
        return ok({"activeTargets": [], "droppedTargets": []})
    return Resp(404, {"status": "error", "errorType": "not_found", "error": "unknown Prometheus API path /api/v1/%s" % rest})


# ───────────────────────────── cloud metric publishers ─────────────────────────────
def _buckets_since(obs: ObsStore, mark_key: str, now: float, period: int = 60) -> tuple:
    """Rows recorded in whole `period` buckets finished since the last publish -> (start, end, rows)."""
    end = int(now // period) * period
    start = obs.pub_mark.get(mark_key) or (int(obs.recent[0][0] // period) * period if obs.recent else end)
    if end <= start:
        return start, end, []
    obs.pub_mark[mark_key] = end
    return start, end, [r for r in obs.recent if start <= r[0] < end]


def publish_cloudwatch(obs: ObsStore, cw_store, now: float | None = None, period: int = 60) -> list:
    """Publish the MEASURED per-resource request series into CloudWatch (real AWS/* names). Returns published metric names."""
    try:
        from core import cloudwatch_core as cw
    except ImportError:
        import cloudwatch_core as cw  # type: ignore
    now = now if now is not None else time.time()
    start, end, rows = _buckets_since(obs, "cw", now, period)
    groups: dict = {}
    for ts, cloud, svc, res, op, st, ms, bi, bo in rows:
        if cloud != "aws" or not res:
            continue
        b = int(ts // period) * period
        groups.setdefault((svc, res, b), []).append((op, st, ms))
    out = []
    for (svc, res, b), rs in groups.items():
        errs = sum(1 for _o, st, _m in rs if st >= 400)
        e5 = sum(1 for _o, st, _m in rs if st >= 500)
        lat = [m for _o, _s, m in rs]

        def put(ns, name, dims, val, unit):
            cw.ingest_internal_metric(cw_store, ns, name, [{"Name": k, "Value": v} for k, v in dims], val, unit=unit, ts=b)
            out.append(name)
        if svc == "lambda":
            inv = [r for r in rs if r[0] == "Invoke"]
            if inv:
                put("AWS/Lambda", "Invocations", [("FunctionName", res)], len(inv), "Count")
                put("AWS/Lambda", "Errors", [("FunctionName", res)], sum(1 for r in inv if r[1] >= 400), "Count")
                put("AWS/Lambda", "Duration", [("FunctionName", res)], round(sum(r[2] for r in inv) / len(inv), 3), "Milliseconds")
        elif svc == "s3":
            d = [("BucketName", res), ("FilterId", "EntireBucket")]
            put("AWS/S3", "AllRequests", d, len(rs), "Count")
            put("AWS/S3", "4xxErrors", d, errs - e5, "Count")
            put("AWS/S3", "5xxErrors", d, e5, "Count")
            put("AWS/S3", "TotalRequestLatency", d, round(sum(lat) / len(lat), 3), "Milliseconds")
        elif svc in ("dynamodb", "ddb"):
            by_op: dict = {}
            for o, st, m in rs:
                by_op.setdefault(o or "Unknown", []).append(m)
            for o, ms_ in by_op.items():
                put("AWS/DynamoDB", "SuccessfulRequestLatency", [("TableName", res), ("Operation", o)], round(sum(ms_) / len(ms_), 3), "Milliseconds")
            put("AWS/DynamoDB", "UserErrors", [], errs - e5, "Count") if errs - e5 else None
            put("AWS/DynamoDB", "SystemErrors", [("TableName", res)], e5, "Count") if e5 else None
        elif svc in ("apigateway", "apigatewayv2"):
            d = [("ApiName", res)]
            put("AWS/ApiGateway", "Count", d, len(rs), "Count")
            put("AWS/ApiGateway", "4XXError", d, errs - e5, "Count")
            put("AWS/ApiGateway", "5XXError", d, e5, "Count")
            put("AWS/ApiGateway", "Latency", d, round(sum(lat) / len(lat), 3), "Milliseconds")
        elif svc in ("sqs",):
            put("AWS/SQS", "NumberOfMessagesSent", [("QueueName", res)], sum(1 for r in rs if r[0] == "SendMessage"), "Count")
    obs.persist()
    return out


def publish_rds_stats(cw_store, db_id: str, stats: dict, ts: float | None = None, engine: str = "postgres") -> list:
    """RDS CloudWatch metrics + Database Insights from REAL runtime counters.
    `stats` is whatever the substrate could measure; absent keys publish nothing (never invented):
      cpu_pct, mem_used_bytes, mem_limit_bytes, disk_used_bytes, disk_total_bytes, net_rx_bytes, net_tx_bytes, blk_read_ops,
      blk_write_ops  — from `docker stats`/cgroup (offline) ; connections, xact_commit, xact_rollback, blks_read, blks_hit,
      tup_returned, tup_fetched, tup_inserted, tup_updated, tup_deleted, active_backends, deadlocks — from pg_stat_database /
      pg_stat_activity (offline Postgres container AND Nano PGlite)."""
    try:
        from core import cloudwatch_core as cw
    except ImportError:
        import cloudwatch_core as cw  # type: ignore
    ts = ts if ts is not None else time.time()
    dims = [{"Name": "DBInstanceIdentifier", "Value": db_id}]
    out = []

    def put(name, val, unit):
        if val is None:
            return
        cw.ingest_internal_metric(cw_store, "AWS/RDS", name, dims, float(val), unit=unit, ts=ts)
        out.append(name)
    g = stats.get
    put("CPUUtilization", None if g("cpu_pct") is None else min(100.0, max(0.0, g("cpu_pct"))), "Percent")
    if g("mem_limit_bytes") and g("mem_used_bytes") is not None:
        put("FreeableMemory", max(0, g("mem_limit_bytes") - g("mem_used_bytes")), "Bytes")
    if g("disk_total_bytes") and g("disk_used_bytes") is not None:
        put("FreeStorageSpace", max(0, g("disk_total_bytes") - g("disk_used_bytes")), "Bytes")
    put("NetworkReceiveThroughput", g("net_rx_bytes"), "Bytes")
    put("NetworkTransmitThroughput", g("net_tx_bytes"), "Bytes")
    put("ReadIOPS", g("blk_read_ops"), "Count/Second")
    put("WriteIOPS", g("blk_write_ops"), "Count/Second")
    put("DatabaseConnections", g("connections"), "Count")
    put("Deadlocks", g("deadlocks"), "Count")
    # Database Insights: DBLoad = average active sessions (pg_stat_activity state='active'); real definition, measured.
    put("DBLoad", g("active_backends"), "None")
    put("DBLoadCPU", None if g("active_backends") is None or g("cpu_pct") is None else g("active_backends") * min(1.0, g("cpu_pct") / 100.0), "None")
    if g("blks_read") is not None and g("blks_hit") is not None and (g("blks_read") + g("blks_hit")) > 0:
        put("BufferCacheHitRatio", 100.0 * g("blks_hit") / (g("blks_read") + g("blks_hit")), "Percent")
    put("TransactionCommits", g("xact_commit"), "Count")
    put("TransactionRollbacks", g("xact_rollback"), "Count")
    return out


def gcp_project_of(path: str) -> str:
    m = re.search(r"/projects/([^/:]+)", path or "")
    return m.group(1) if m else "my-project"


def publish_gcp(obs: ObsStore, mon_store, project: str, now: float | None = None, period: int = 60) -> list:
    """Publish measured request series into Cloud Monitoring time series (serviceruntime request_count / latencies style).
    Writes straight into the Monitoring store's time_series (system metrics are service-written, not user-writable)."""
    now = now if now is not None else time.time()
    start, end, rows = _buckets_since(obs, "gcp:" + project, now, period)
    from datetime import datetime, timezone
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    groups: dict = {}
    for ts, cloud, svc, res, op, st, ms, bi, bo in rows:
        if cloud != "gcp" or not res:
            continue
        groups.setdefault((svc, res, int(ts // period) * period), []).append((st, ms))
    out = []
    types = {"gcp-gcs": ("storage.googleapis.com/api/request_count", "gcs_bucket", "bucket_name"),
             "gcs": ("storage.googleapis.com/api/request_count", "gcs_bucket", "bucket_name"),
             "gcp-redis": ("redis.googleapis.com/commands/calls", "redis_instance", "instance_id"),
             "gcp-run": ("run.googleapis.com/request_count", "cloud_run_revision", "service_name"),
             "gcp-cloudsql": ("cloudsql.googleapis.com/database/network/connections", "cloudsql_database", "database_id")}
    for (svc, res, b), rs in groups.items():
        spec = types.get(svc)
        if not spec:
            continue
        mtype, rtype, rlabel = spec
        rlabs = {rlabel: res, "project_id": project}
        key = "%s|%s||%s|%s" % (project, mtype, rtype, ",".join("%s=%s" % kv for kv in sorted(rlabs.items())))
        s = mon_store.time_series.setdefault(key, {"metric": {"type": mtype, "labels": {}}, "resource": {"type": rtype, "labels": rlabs},
                                                   "metricKind": "DELTA", "valueType": "INT64", "points": []})
        s["points"].append({"interval": {"startTime": iso(b), "endTime": iso(b + period)}, "value": {"int64Value": str(len(rs))}})
        out.append(mtype)
    return out


def azure_storage_request_metrics(obs: ObsStore, account: str, window: float = 3600.0, now: float | None = None) -> dict:
    """Storage-account Availability / SuccessE2ELatency / SuccessServerLatency / ClientOtherError / Transactions derived from
    MEASURED blob-service requests (`service` = blob, resource = the account). Absent when the account saw no traffic."""
    now = now if now is not None else time.time()
    rows = [r for r in obs.recent if r[1] == "azure" and r[3].lower() == account.lower() and r[2] in ("blob", "az-blob", "storage")
            and r[0] >= now - window]
    if not rows:
        return {}
    ok = [r for r in rows if r[5] < 400]
    out = {"Transactions": float(len(rows)), "Availability": round(100.0 * (len(rows) - sum(1 for r in rows if r[5] >= 500)) / len(rows), 4)}
    if ok:
        out["SuccessE2ELatency"] = round(sum(r[6] for r in ok) / len(ok), 3)
        out["SuccessServerLatency"] = out["SuccessE2ELatency"]
    out["ClientOtherError"] = float(sum(1 for r in rows if 400 <= r[5] < 500))
    return out


def sync_gcp_traces(obs: ObsStore, mon_store, project: str) -> int:
    """Mirror spans into the Cloud Trace store (so the Trace explorer / traces.list sees OTLP + auto-instrumented spans)."""
    try:
        from core import gcp_trace_core as tr
    except ImportError:
        import gcp_trace_core as tr  # type: ignore
    from datetime import datetime, timezone
    mark = obs.pub_mark.get("gcptrace:" + project, 0)
    spans = []
    iso = lambda ns: datetime.fromtimestamp(ns / 1e9, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    newest = mark
    for tid, ss in obs.spans.items():
        for s in ss:
            if int(s["endTimeUnixNano"]) <= mark:
                continue
            newest = max(newest, int(s["endTimeUnixNano"]))
            sp = {"name": "projects/%s/traces/%s/spans/%s" % (project, tid, s["spanId"]), "spanId": s["spanId"],
                  "displayName": {"value": s["name"][:128]}, "startTime": iso(int(s["startTimeUnixNano"])),
                  "endTime": iso(int(s["endTimeUnixNano"])), "spanKind": {2: "SERVER", 3: "CLIENT"}.get(s.get("kind"), "INTERNAL"),
                  "attributes": {"attributeMap": {str(k)[:128]: ({"intValue": str(v)} if isinstance(v, int) and not isinstance(v, bool)
                                                                else {"boolValue": v} if isinstance(v, bool) else {"stringValue": {"value": str(v)[:256]}})
                                                  for k, v in list((s.get("attributes") or {}).items())[:30]}}}
            if s.get("parentSpanId"):
                sp["parentSpanId"] = s["parentSpanId"]
            spans.append(sp)
    n = 0
    for i in range(0, len(spans), 500):
        try:
            tr.batch_write(mon_store, project, {"spans": spans[i:i + 500]})
            n += len(spans[i:i + 500])
        except Exception:
            pass
    obs.pub_mark["gcptrace:" + project] = newest
    return n
