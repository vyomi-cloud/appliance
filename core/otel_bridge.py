"""AgentOps bridge: OTLP spans (what AgentCore Observability / ADOT / Strands / LangGraph emit) -> X-Ray traces,
CloudWatch Logs events and CloudWatch metrics.

The OTLP/HTTP receiver itself (observability_core, ``/_obs/v1/traces|metrics|logs``) is reused untouched; this module only
adds the thin fan-out the real AgentCore service performs after it receives spans:

  * X-Ray   - every trace becomes segments in the X-Ray trace bag (core/xray_core): one segment per service.name,
              same-service children nest as subsegments, a cross-service child becomes a `remote` subsegment on the
              caller plus a segment with parent_id on the callee, so BatchGetTraces / GetTraceSummaries / GetServiceGraph
              show supervisor -> sub-agent -> tool / model edges. gen_ai `chat` spans become `bedrock-runtime`
              subsegments (namespace aws), `execute_tool` spans become remote subsegments named after the tool.
  * Logs    - each span is one JSON event in log group `aws/spans` (the group real X-Ray Transaction Search / AgentCore
              write to). OTLP log records land in `/aws/bedrock-agentcore/runtimes/<service>/runtime-logs`. Logs Insights
              auto-discovers the JSON fields (attributes.gen_ai.usage.input_tokens ...).
  * Metrics - namespace `Bedrock-AgentCore`: Invocations/Latency/Errors (agent spans), ModelInvocations/ModelLatency/
              InputTokenCount/OutputTokenCount/ModelErrors (gen_ai chat spans), ToolInvocations/ToolLatency/ToolErrors.
  * Protobuf - `application/x-protobuf` OTLP bodies are decoded with the OpenTelemetry proto definitions when the
              `opentelemetry-proto` package (pure Python, 70 KB, + protobuf) is installed (Mesh); otherwise the receiver stays
              JSON-only (Nano: the browser OTLP/HTTP JSON exporter).

OSS reused: OpenTelemetry (OTLP wire format, GenAI semantic conventions, opentelemetry-proto, Apache-2.0). Hand-written is
only the span -> X-Ray/CloudWatch mapping.
"""
from __future__ import annotations

import json
import re

NAMESPACE = "Bedrock-AgentCore"
SPANS_GROUP = "aws/spans"
_LOGS_T = "Logs_20140328."


def _x_trace_id(tid: str) -> str:
    return "1-%s-%s" % (tid[:8], tid[8:32])


# ── protobuf (optional) ─────────────────────────────────────────────────────
def decode_protobuf(path: str, body: bytes):
    """OTLP protobuf -> the JSON-mapping dict, or None when opentelemetry-proto is not installed."""
    try:
        from google.protobuf.json_format import MessageToDict
        if path.endswith("/v1/traces"):
            from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest as M
        elif path.endswith("/v1/metrics"):
            from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest as M
        else:
            from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest as M
    except ImportError:
        return None
    m = M()
    m.ParseFromString(body)
    return MessageToDict(m)


def preprocess(method: str, path: str, headers: dict, body: bytes):
    """Returns (headers, body, payload|None). Converts OTLP protobuf to JSON when possible; payload is the parsed
    OTLP/JSON dict for /v1/traces and /v1/logs posts (what after_ingest needs)."""
    if method.upper() != "POST" or not re.search(r"/v1/(traces|logs)$", path):
        return headers, body, None
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    ct = (h.get("content-type") or "").split(";")[0].strip().lower()
    payload = None
    if ct in ("application/x-protobuf", "application/protobuf"):
        try:
            payload = decode_protobuf(path, body)
        except Exception:
            payload = None
        if payload is not None:
            h["content-type"] = "application/json"
            return h, json.dumps(payload).encode(), payload
        return headers, body, None
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        return headers, body, None
    return headers, body, payload if isinstance(payload, dict) else None


# ── span normalisation ──────────────────────────────────────────────────────
def _attr_map(lst) -> dict:
    out = {}
    for a in lst or []:
        v = a.get("value") or {}
        for kk in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if kk in v:
                x = v[kk]
                out[a.get("key", "")] = int(x) if kk == "intValue" else x
                break
    return out


def _hex(v: str, n: int) -> str:
    if re.fullmatch(r"[0-9a-fA-F]{%d}" % n, v or ""):
        return v.lower()
    import base64
    try:
        raw = base64.b64decode(v)
        return raw.hex() if len(raw) * 2 == n else ""
    except Exception:
        return ""


def _spans(payload: dict) -> list:
    out = []
    for rs in payload.get("resourceSpans") or []:
        rattr = _attr_map((rs.get("resource") or {}).get("attributes"))
        svc = rattr.get("service.name") or "unknown_service"
        for ss in rs.get("scopeSpans") or []:
            scope = (ss.get("scope") or {}).get("name", "")
            for sp in ss.get("spans") or []:
                tid, sid = _hex(sp.get("traceId", ""), 32), _hex(sp.get("spanId", ""), 16)
                try:
                    st, en = int(sp.get("startTimeUnixNano", 0)), int(sp.get("endTimeUnixNano", 0))
                except (TypeError, ValueError):
                    continue
                if not tid or not sid or not sp.get("name") or en < st or not st:
                    continue
                status = sp.get("status") or {}
                code = status.get("code", 0)
                code = {"STATUS_CODE_ERROR": 2, "STATUS_CODE_OK": 1}.get(code, code) if isinstance(code, str) else code
                out.append({"traceId": tid, "spanId": sid,
                            "parentSpanId": _hex(sp.get("parentSpanId", ""), 16) if sp.get("parentSpanId") else "",
                            "name": sp["name"], "kind": sp.get("kind", 0), "start": st, "end": en, "service": svc,
                            "scope": scope, "attrs": _attr_map(sp.get("attributes")), "resource": rattr,
                            "error": int(code or 0) == 2, "statusMessage": status.get("message", ""),
                            "events": sp.get("events") or []})
    return out


def _op(sp: dict) -> str:
    a = sp["attrs"]
    op = a.get("gen_ai.operation.name")
    if op:
        return {"invoke_agent": "agent", "chat": "model", "text_completion": "model", "generate_content": "model",
                "execute_tool": "tool", "create_agent": "agent"}.get(op, op)
    if a.get("gen_ai.tool.name"):
        return "tool"
    if a.get("gen_ai.request.model") or a.get("gen_ai.usage.input_tokens") is not None:
        return "model"
    if a.get("gen_ai.agent.name"):
        return "agent"
    return ""


# ── X-Ray ───────────────────────────────────────────────────────────────────
def _xray_docs(spans: list) -> dict:
    """{x_trace_id: [segment docs]} for the spans of one batch (grouped per trace)."""
    from core import xray_core
    by_trace: dict = {}
    for sp in spans:
        by_trace.setdefault(sp["traceId"], []).append(sp)
    out = {}
    for tid, sps in by_trace.items():
        sps.sort(key=lambda s: s["start"])
        xt = _x_trace_id(tid)
        node: dict = {}      # spanId -> (doc, is_segment)
        roots: list = []
        for sp in sps:
            op = _op(sp)
            a = sp["attrs"]
            doc = {"id": sp["spanId"], "name": sp["service"], "start_time": sp["start"] / 1e9, "end_time": sp["end"] / 1e9}
            ann = {k.replace(".", "_"): v for k, v in a.items() if isinstance(v, (str, int, float, bool)) and k.startswith("gen_ai.")}
            if ann:
                doc["annotations"] = ann
            doc["metadata"] = {"otel": {"span_name": sp["name"], "kind": sp["kind"], "scope": sp["scope"]}}
            if sp["error"]:
                doc["fault"] = True
                doc["cause"] = {"message": (sp["statusMessage"] or "error")[:500],
                                "exceptions": [{"id": xray_core._seg_id(), "message": sp["statusMessage"] or "error", "type": "SpanError"}]}
            parent = node.get(sp["parentSpanId"])
            if op == "model":
                doc.update({"name": "bedrock-runtime", "namespace": "aws",
                            "aws": {"operation": "Converse", "model_id": a.get("gen_ai.request.model", "")}})
            elif op == "tool":
                doc.update({"name": a.get("gen_ai.tool.name") or sp["name"], "namespace": "remote"})
            elif parent is not None and parent[2] == sp["service"]:
                doc["name"] = sp["name"]
            if parent is not None and (op in ("model", "tool") or parent[2] == sp["service"]):
                parent[0].setdefault("subsegments", []).append(doc)
                node[sp["spanId"]] = (doc, False, sp["service"])
                continue
            # a service boundary (or an orphan): this span is a segment of its service
            doc.update({"name": sp["service"], "trace_id": xt, "origin": "AWS::BedrockAgentCore::Runtime"})
            doc.pop("namespace", None)
            doc.pop("aws", None)
            if parent is not None:
                link = {"id": xray_core._seg_id(), "name": sp["service"], "namespace": "remote",
                        "start_time": doc["start_time"], "end_time": doc["end_time"]}
                parent[0].setdefault("subsegments", []).append(link)
                doc["parent_id"] = link["id"]
            elif sp["parentSpanId"]:
                doc["parent_id"] = sp["parentSpanId"]
            node[sp["spanId"]] = (doc, True, sp["service"])
            roots.append(doc)
        out[xt] = roots
    return out


def _norm_obs_span(o: dict) -> dict:
    """observability_core's stored span -> the normalised form used here."""
    return {"traceId": o["traceId"], "spanId": o["spanId"], "parentSpanId": o.get("parentSpanId", ""), "name": o["name"],
            "kind": o.get("kind", 0), "start": o["startTimeUnixNano"], "end": o["endTimeUnixNano"], "service": o.get("service", "unknown_service"),
            "scope": "", "attrs": o.get("attributes") or {}, "resource": {}, "error": (o.get("status") or {}).get("code") == 2,
            "statusMessage": (o.get("status") or {}).get("message", ""), "events": o.get("events") or []}


def _to_xray(router, spans: list) -> None:
    """Spans of one trace arrive over several posts and in any order (children end before parents), so each trace touched by
    this batch is rebuilt from ALL of its spans held by the OTLP store."""
    store = router.sfn
    from core import xray_core
    bag = xray_core._bag(store)
    touched = {s["traceId"] for s in spans}
    full = [_norm_obs_span(o) for tid in touched for o in router.obs.spans.get(tid, [])] or spans
    for xt, docs in _xray_docs(full).items():
        bag[xt] = {"segments": {d["id"]: d for d in docs}}
    xray_core._trim(bag)
    if hasattr(store, "persist"):
        try:
            store.persist()
        except Exception:
            pass


# ── CloudWatch Logs ─────────────────────────────────────────────────────────
def _log_put(logs_store, logs_mod, group: str, stream: str, events: list) -> None:
    for op, body in (("CreateLogGroup", {"logGroupName": group}),
                     ("CreateLogStream", {"logGroupName": group, "logStreamName": stream})):
        logs_mod.dispatch(logs_store, _LOGS_T + op, body)      # AlreadyExists is a benign 400
    for i in range(0, len(events), 500):
        logs_mod.dispatch(logs_store, _LOGS_T + "PutLogEvents",
                          {"logGroupName": group, "logStreamName": stream, "logEvents": events[i:i + 500]})


def _span_event(sp: dict) -> dict:
    msg = {"traceId": sp["traceId"], "spanId": sp["spanId"], "parentSpanId": sp["parentSpanId"], "name": sp["name"],
           "kind": sp["kind"], "startTimeUnixNano": sp["start"], "endTimeUnixNano": sp["end"],
           "durationMs": round((sp["end"] - sp["start"]) / 1e6, 3), "status": "ERROR" if sp["error"] else "OK",
           "operation": _op(sp), "serviceName": sp["service"], "resource": {"attributes": sp["resource"]},
           "scope": {"name": sp["scope"]}, "attributes": sp["attrs"]}
    if sp["statusMessage"]:
        msg["statusMessage"] = sp["statusMessage"]
    return {"timestamp": int(sp["end"] / 1e6), "message": json.dumps(msg, separators=(",", ":"))}


def _to_logs(router, spans: list) -> None:
    from core import logs_core
    evs = [_span_event(s) for s in spans]
    if evs:
        _log_put(router.logs, logs_core, SPANS_GROUP, "default", evs)


# ── CloudWatch metrics ──────────────────────────────────────────────────────
def _to_metrics(router, spans: list) -> None:
    from core import cloudwatch_core as cw

    def put(name, dims, val, unit, ts):   # CloudWatch keys series on name-sorted dimensions
        cw.ingest_internal_metric(router.cw, NAMESPACE, name, [{"Name": k, "Value": str(v)} for k, v in sorted(dims)], val, unit=unit, ts=ts)
    for sp in spans:
        op = _op(sp)
        if not op:
            continue
        a, ts, ms = sp["attrs"], sp["end"] / 1e9, (sp["end"] - sp["start"]) / 1e6
        svc = [("Service", sp["service"])]
        if op == "agent":
            d = svc + [("AgentName", a.get("gen_ai.agent.name") or sp["service"])]
            put("Invocations", d, 1, "Count", ts)
            put("Latency", d, round(ms, 3), "Milliseconds", ts)
            put("Errors", d, 1 if sp["error"] else 0, "Count", ts)
        elif op == "model":
            d = svc + [("ModelId", a.get("gen_ai.request.model") or "unknown")]
            put("ModelInvocations", d, 1, "Count", ts)
            put("ModelLatency", d, round(ms, 3), "Milliseconds", ts)
            put("ModelErrors", d, 1 if sp["error"] else 0, "Count", ts)
            for key, nm in (("gen_ai.usage.input_tokens", "InputTokenCount"), ("gen_ai.usage.output_tokens", "OutputTokenCount")):
                if a.get(key) is not None:
                    put(nm, d, float(a[key]), "Count", ts)
        elif op == "tool":
            d = svc + [("ToolName", a.get("gen_ai.tool.name") or sp["name"])]
            put("ToolInvocations", d, 1, "Count", ts)
            put("ToolLatency", d, round(ms, 3), "Milliseconds", ts)
            put("ToolErrors", d, 1 if sp["error"] else 0, "Count", ts)


# ── entry points ────────────────────────────────────────────────────────────
def after_ingest(router, path: str, payload: dict) -> None:
    """Fan one accepted OTLP post out to X-Ray / CloudWatch Logs / CloudWatch metrics. Never fails the ingest."""
    try:
        if path.endswith("/v1/traces"):
            spans = _spans(payload)
            if spans:
                _to_xray(router, spans)
                _to_logs(router, spans)
                _to_metrics(router, spans)
        elif path.endswith("/v1/logs"):
            from core import logs_core
            by_svc: dict = {}
            for rl in payload.get("resourceLogs") or []:
                svc = _attr_map((rl.get("resource") or {}).get("attributes")).get("service.name", "unknown_service")
                for sl in rl.get("scopeLogs") or []:
                    for lr in sl.get("logRecords") or []:
                        body = lr.get("body") or {}
                        rec = {"body": body.get("stringValue", json.dumps(body)), "severity": lr.get("severityText", ""),
                               "traceId": lr.get("traceId", ""), "spanId": lr.get("spanId", ""),
                               "attributes": _attr_map(lr.get("attributes"))}
                        t = int(lr.get("timeUnixNano") or 0) // 1_000_000
                        if not t:
                            import time
                            t = int(time.time() * 1000)
                        by_svc.setdefault(svc, []).append({"timestamp": t, "message": json.dumps(rec, separators=(",", ":"))})
            for svc, evs in by_svc.items():
                _log_put(router.logs, logs_core, "/aws/bedrock-agentcore/runtimes/%s/runtime-logs" % svc, "otel", evs)
    except Exception:
        pass
