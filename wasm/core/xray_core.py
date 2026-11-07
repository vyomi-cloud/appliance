# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS X-Ray (rest-json, signing name `xray`) over a durable trace bag, plus the Step Functions trace recorder.

Real: PutTraceSegments (segment documents are validated and grouped into traces by trace_id), BatchGetTraces,
GetTraceSummaries (time window + a small FilterExpression subset), GetServiceGraph (nodes/edges derived from the
stored segments), PutTelemetryRecords (accepted), and `record_sfn_execution` - when a state machine has
tracingConfiguration.enabled, every finished execution is turned into a REAL trace (one segment for the state machine
named after it, one subsegment per state visited with the state's own start/end time, Lambda task subsegments, fault
and error flags from the execution result) that the calls above - and `aws xray get-trace-summaries` /
`batch-get-traces` - return.

Not real: no X-Ray daemon/UDP ingest, no sampling rules, no groups/insights/encryption config, no analytics-grade
percentile statistics.

State lives in `store.xray_traces` (the Step Functions store's public dict attr, so it persists offline and on Nano):
{trace_id: {"segments": {segment_id: doc}}}.
"""
from __future__ import annotations

import json
import re
import secrets
import time

_TRACE_RE = re.compile(r"^1-[0-9a-f]{8}-[0-9a-f]{24}$")
MAX_TRACES = 1000


def new_trace_id(ts: float | None = None) -> str:
    return "1-%08x-%s" % (int(ts if ts is not None else time.time()), secrets.token_hex(12))


def _seg_id() -> str:
    return secrets.token_hex(8)


def _bag(store) -> dict:
    b = getattr(store, "xray_traces", None)
    if not isinstance(b, dict):
        b = {}
        store.xray_traces = b
    return b


def _trim(bag: dict) -> None:
    while len(bag) > MAX_TRACES:
        bag.pop(next(iter(bag)))


# ── Step Functions -> trace ─────────────────────────────────────────────────
def trace_header_root(header: str) -> str:
    m = re.search(r"Root=(1-[0-9a-f]{8}-[0-9a-f]{24})", header or "")
    return m.group(1) if m else ""


def record_sfn_execution(store, ex: dict, sm: dict) -> str:
    """Build and store the trace of a finished execution. Returns the trace id."""
    trace_id = ex.get("traceId") or new_trace_id(ex["startDate"])
    ex["traceId"] = trace_id
    hist = ex.get("_history") or []
    end = float(ex.get("stopDate") or time.time())
    start = float(ex["startDate"])
    subs = []
    open_states: list[dict] = []
    for ev in hist:
        t = ev.get("type", "")
        ts = float(ev.get("timestamp") or start)
        if t.endswith("StateEntered"):
            d = ev.get("stateEnteredEventDetails") or {}
            seg = {"id": _seg_id(), "name": d.get("name", "state"), "start_time": ts, "end_time": end,
                   "annotations": {"StateType": t[:-len("StateEntered")]}}
            subs.append(seg)
            open_states.append(seg)
        elif t.endswith("StateExited"):
            name = (ev.get("stateExitedEventDetails") or {}).get("name")
            for seg in reversed(open_states):
                if seg["name"] == name:
                    seg["end_time"] = ts
                    open_states.remove(seg)
                    break
        elif t == "TaskScheduled" and open_states:
            d = ev.get("taskScheduledEventDetails") or {}
            res = d.get("resource", "")
            fn = ""
            try:
                fn = str(json.loads(d.get("parameters") or "{}").get("FunctionName") or "")
            except Exception:
                pass
            if res.startswith("arn:aws:lambda") or fn or res == "invoke":
                fn = (fn or res).split(":")[-1] if (fn or res) else "lambda"
                open_states[-1].setdefault("subsegments", []).append(
                    {"id": _seg_id(), "name": fn, "namespace": "aws", "start_time": ts, "end_time": ts,
                     "aws": {"operation": "Invoke", "function_name": fn}})
        elif t in ("TaskFailed", "TaskTimedOut", "LambdaFunctionFailed", "ExecutionFailed") and open_states:
            open_states[-1]["fault"] = True
            d = ev.get("taskFailedEventDetails") or ev.get("executionFailedEventDetails") or {}
            if d.get("error"):
                open_states[-1]["cause"] = {"message": str(d.get("cause") or d["error"])[:500], "exceptions": [{"id": _seg_id(), "message": d["error"], "type": d["error"]}]}
    for seg in open_states:           # still-running states end at the execution end
        seg["end_time"] = end
    status = ex.get("status")
    root = {"id": _seg_id(), "trace_id": trace_id, "name": sm["name"], "start_time": start, "end_time": end,
            "origin": "AWS::StepFunctions::StateMachine",
            "aws": {"account_id": sm["stateMachineArn"].split(":")[4], "state_machine_arn": sm["stateMachineArn"],
                    "execution_arn": ex["executionArn"]},
            "http": {"response": {"status": 200 if status == "SUCCEEDED" else 500}},
            "subsegments": subs}
    if status in ("FAILED", "TIMED_OUT", "ABORTED"):
        root["fault"] = True
        root["cause"] = {"message": str(ex.get("cause") or ex.get("error") or status)[:500]}
    bag = _bag(store)
    bag.setdefault(trace_id, {"segments": {}})["segments"][root["id"]] = root
    _trim(bag)
    return trace_id


# ── REST API ────────────────────────────────────────────────────────────────
def _resp(status: int, doc: dict) -> dict:
    return {"status": status, "headers": {"content-type": "application/json"}, "body": json.dumps(doc).encode()}


def _err(status: int, code: str, msg: str) -> dict:
    r = _resp(status, {"message": msg})
    r["headers"]["x-amzn-errortype"] = code
    return r


def _times(seg_docs):
    s = min((d["start_time"] for d in seg_docs), default=0)
    e = max((d.get("end_time", d["start_time"]) for d in seg_docs), default=0)
    return s, e


def _walk(seg):
    yield seg
    for sub in seg.get("subsegments") or []:
        yield from _walk(sub)


def _put_segments(store, b):
    bad = []
    bag = _bag(store)
    for raw in b.get("TraceSegmentDocuments") or []:
        try:
            d = json.loads(raw)
            tid, sid = d["trace_id"], d["id"]
            if not _TRACE_RE.match(tid):
                raise ValueError("bad trace_id")
            if not d.get("name") or "start_time" not in d:
                raise ValueError("name and start_time are required")
            if not d.get("end_time") and not d.get("in_progress"):
                raise ValueError("end_time is required unless in_progress")
            d.setdefault("end_time", d["start_time"])
        except Exception as e:
            try:
                sid = json.loads(raw).get("id", "")
            except Exception:
                sid = ""
            bad.append({"Id": sid, "ErrorCode": "ParseError", "Message": str(e)})
            continue
        bag.setdefault(tid, {"segments": {}})["segments"][sid] = d
    _trim(bag)
    return _resp(200, {"UnprocessedTraceSegments": bad})


def _batch_get(store, b):
    bag = _bag(store)
    out, missing = [], []
    for tid in b.get("TraceIds") or []:
        t = bag.get(tid)
        if not t:
            missing.append(tid)
            continue
        docs = list(t["segments"].values())
        s, e = _times(docs)
        out.append({"Id": tid, "Duration": round(e - s, 3), "LimitExceeded": False,
                    "Segments": [{"Id": d["id"], "Document": json.dumps(d)} for d in docs]})
    return _resp(200, {"Traces": out, "UnprocessedTraceIds": missing})


def _flags(docs):
    fault = any(x.get("fault") for d in docs for x in _walk(d))
    error = any(x.get("error") for d in docs for x in _walk(d))
    return fault, error


def _filter_ok(expr: str, tid: str, docs) -> bool:
    expr = (expr or "").strip()
    if not expr:
        return True
    fault, error = _flags(docs)
    names = {d.get("name") for d in docs}
    ok = True
    for m in re.finditer(r'service\(\s*"([^"]+)"\s*\)', expr):
        ok = ok and m.group(1) in names
    low = expr.lower()
    if re.search(r"(^|\s)fault(\s|$)", low):
        ok = ok and fault
    if re.search(r"(^|\s)error(\s|$)", low):
        ok = ok and error
    m = re.search(r"duration\s*>=?\s*([0-9.]+)", low)
    if m:
        s, e = _times(docs)
        ok = ok and (e - s) >= float(m.group(1))
    return ok


def _summaries(store, b):
    lo, hi = float(b.get("StartTime") or 0), float(b.get("EndTime") or time.time() + 3600)
    out = []
    for tid, t in _bag(store).items():
        docs = list(t["segments"].values())
        s, e = _times(docs)
        if e < lo or s > hi or not _filter_ok(b.get("FilterExpression"), tid, docs):
            continue
        fault, error = _flags(docs)
        out.append({"Id": tid, "Duration": round(e - s, 3), "ResponseTime": round(e - s, 3), "HasFault": fault,
                    "HasError": error, "HasThrottle": False, "IsPartial": any(d.get("in_progress") for d in docs),
                    "Http": {}, "Annotations": {}, "Users": [],
                    "ServiceIds": [{"Name": d["name"], "Names": [d["name"]], "Type": d.get("origin") or "client",
                                    "AccountId": (d.get("aws") or {}).get("account_id", "")} for d in docs],
                    "_s": s})
    out.sort(key=lambda x: -x["_s"])
    for o in out:
        o.pop("_s")
    return _resp(200, {"TraceSummaries": out, "ApproximateTime": time.time(), "TracesProcessedCount": len(out)})


def _service_graph(store, b):
    lo, hi = float(b.get("StartTime") or 0), float(b.get("EndTime") or time.time() + 3600)
    nodes: dict[str, dict] = {}
    edges: dict[tuple, int] = {}

    def node(name, typ):
        n = nodes.setdefault(name, {"ReferenceId": len(nodes) + 1, "Name": name, "Names": [name], "Type": typ,
                                    "SummaryStatistics": {"OkCount": 0, "ErrorStatistics": {"TotalCount": 0}, "FaultStatistics": {"TotalCount": 0}, "TotalCount": 0, "TotalResponseTime": 0.0},
                                    "_e": {}})
        return n

    for t in _bag(store).values():
        docs = list(t["segments"].values())
        s, e = _times(docs)
        if e < lo or s > hi:
            continue
        for d in docs:
            n = node(d["name"], d.get("origin") or "client")
            st = n["SummaryStatistics"]
            st["TotalCount"] += 1
            st["TotalResponseTime"] += d.get("end_time", d["start_time"]) - d["start_time"]
            if d.get("fault"):
                st["FaultStatistics"]["TotalCount"] += 1
            elif d.get("error"):
                st["ErrorStatistics"]["TotalCount"] += 1
            else:
                st["OkCount"] += 1
            for sub in d.get("subsegments") or []:
                if sub.get("namespace") in ("aws", "remote"):
                    node(sub["name"], "remote")
                    n["_e"][sub["name"]] = n["_e"].get(sub["name"], 0) + 1
    out = []
    for n in nodes.values():
        n["Edges"] = [{"ReferenceId": nodes[t]["ReferenceId"], "StartTime": lo, "EndTime": hi,
                       "SummaryStatistics": {"OkCount": c, "ErrorStatistics": {"TotalCount": 0}, "FaultStatistics": {"TotalCount": 0}, "TotalCount": c, "TotalResponseTime": 0.0}}
                      for t, c in n.pop("_e").items()]
        n["StartTime"], n["EndTime"] = lo, hi
        out.append(n)
    return _resp(200, {"StartTime": lo, "EndTime": hi, "Services": out, "ContainsOldGroupVersions": False})


_ROUTES = {"/TraceSegments": _put_segments, "/Traces": _batch_get, "/TraceSummaries": _summaries,
           "/ServiceGraph": _service_graph, "/TelemetryRecords": lambda s, b: _resp(200, {}),
           "/GetSamplingRules": lambda s, b: _resp(200, {"SamplingRuleRecords": []}),
           "/SamplingTargets": lambda s, b: _resp(200, {"SamplingTargetDocuments": [], "UnprocessedStatistics": []})}


def dispatch(store, method: str, path: str, query, headers, body: bytes) -> dict:
    fn = _ROUTES.get(path.rstrip("/") or "/")
    if fn is None:
        return _err(404, "UnknownOperationException", f"{method} {path} is not an X-Ray operation")
    try:
        b = json.loads(body or b"{}") if method == "POST" else {}
    except Exception:
        return _err(400, "InvalidRequestException", "Invalid JSON body")
    return fn(store, b)
