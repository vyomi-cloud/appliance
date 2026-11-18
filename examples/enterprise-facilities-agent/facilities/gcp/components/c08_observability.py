"""C8: AgentOps: spans from the agent run -> Cloud Trace, structured Cloud Logging entries, Cloud Monitoring custom metric, then read them back."""
import json, time, uuid
from datetime import datetime, timezone
from ..runtime import NAMES, LANE, Blocked, need_grpc, need_result, raw_log_entries


def run(ctx):
    res = ctx.state.get("result", {})
    spans = res.get("spans", [])
    P = f"projects/{ctx.project}"
    tid = uuid.uuid4().hex
    ctx.state["trace_id"] = tid
    now = time.time()
    t0 = spans[0]["start"] if spans else now
    t1 = spans[-1]["end"] if spans else now + 0.05

    def ts(t):
        from google.protobuf import timestamp_pb2
        x = timestamp_pb2.Timestamp()
        x.FromDatetime(datetime.fromtimestamp(t, timezone.utc))
        return x

    def have_run():
        need_result(ctx, "trace")
        return f"{len(spans)} agent spans to export"
    ctx.step("the agent run produced spans to export", have_run)

    def push():
        from google.cloud import trace_v2
        c = ctx.rest(trace_v2.TraceServiceClient)
        root = uuid.uuid4().hex[:16]
        out = [trace_v2.Span(name=f"{P}/traces/{tid}/spans/{root}", span_id=root, display_name=trace_v2.TruncatableString(value="facilities-supervisor"), start_time=ts(t0), end_time=ts(t1))]
        for s in spans:
            sid = uuid.uuid4().hex[:16]
            out.append(trace_v2.Span(name=f"{P}/traces/{tid}/spans/{sid}", span_id=sid, parent_span_id=root, display_name=trace_v2.TruncatableString(value=s["name"]),
                                     start_time=ts(s["start"]), end_time=ts(s["end"]), attributes=trace_v2.Span.Attributes(attribute_map={"kind": trace_v2.AttributeValue(string_value=trace_v2.TruncatableString(value=s["kind"]))})))
        c.batch_write_spans(request={"name": P, "spans": out})
        return f"{len(out)} spans sent (trace {tid})"
    ctx.step("cloud trace v2: batch_write_spans (one span per agent / tool step)", push)

    def read():
        from google.cloud import trace_v1
        c = ctx.rest(trace_v1.TraceServiceClient)
        tr = c.get_trace(request={"project_id": ctx.project, "trace_id": tid})
        names = {x.name for x in tr.spans}
        assert "agent:facilities" in names or len(names) > 1, names
        return f"v1 get_trace read back {len(tr.spans)} spans"
    ctx.step("cloud trace v1: get_trace reads the agent trace back", read, lane=LANE["core"])

    def listed():
        from google.cloud import trace_v1
        c = ctx.rest(trace_v1.TraceServiceClient)
        ids = {t.trace_id for t in c.list_traces(request={"project_id": ctx.project})}
        assert tid in ids, f"{len(ids)} traces listed, ours missing"
        return "trace listed by list_traces"
    ctx.step("cloud trace v1: list_traces lists it", listed, lane=LANE["core"])

    def logs():
        from google.cloud import logging as gl
        # google-cloud-logging's HTTP transport (the library's documented non-gRPC mode); the simulator front door is HTTP/1.1
        c = gl.Client(project=ctx.project, credentials=ctx.anon(), _use_grpc=False)
        c._connection.API_BASE_URL = ctx.endpoint
        lg = c.logger("facilities-agent")
        lg.log_struct({"event": "agent_run", "trace": f"{P}/traces/{tid}", "route": res.get("route"), "tools": [t["tool"] for t in res.get("tools", [])]}, severity="INFO")
        got = []
        for _ in range(10):
            got = list(c.list_entries(filter_=f'logName="{P}/logs/facilities-agent"'))
            if got:
                break
            time.sleep(0.5)
        if not got and raw_log_entries(ctx, f'logName="{P}/logs/facilities-agent"'):
            raise Blocked(LANE["core"], "entries:list with the SDK's default timestamp>= filter returns nothing although the entry exists (raw entries:list shows it)")
        assert got and tid in json.dumps(got[0].payload), got
        return "structured agent log written with logger.log_struct and read back with list_entries; carries the trace id"
    ctx.step("cloud logging: log_struct + list_entries (structured, trace-correlated)", logs, lane=LANE["core"])

    def metric():
        import grpc
        from google.cloud import monitoring_v3
        from google.cloud.monitoring_v3.services.metric_service import transports
        # Monitoring has no REST transport; its SDK default is gRPC. Plain channel to the simulator, like pointing the client at an emulator.
        need_grpc_target = ctx.state.get("monitoring_target") or __import__("urllib.parse", fromlist=["urlparse"]).urlparse(ctx.endpoint).netloc
        c = monitoring_v3.MetricServiceClient(transport=transports.MetricServiceGrpcTransport(channel=grpc.insecure_channel(need_grpc_target)))
        mt = "custom.googleapis.com/facilities/tool_calls"
        c.create_metric_descriptor(request={"name": P, "metric_descriptor": {"type": mt, "metric_kind": "GAUGE", "value_type": "INT64", "description": "tool calls"}}, timeout=15, retry=None)
        n = len(res.get("tools", [])) or 1
        ser = monitoring_v3.TimeSeries(metric={"type": mt, "labels": {"agent": "facilities-supervisor"}}, resource={"type": "global", "labels": {"project_id": ctx.project}},
                                       points=[monitoring_v3.Point(interval={"end_time": {"seconds": int(time.time())}}, value={"int64_value": n})])
        c.create_time_series(request={"name": P, "time_series": [ser]}, timeout=15, retry=None)
        ts_ = list(c.list_time_series(request={"name": P, "filter": f'metric.type="{mt}"', "interval": {"start_time": {"seconds": int(now) - 600}, "end_time": {"seconds": int(time.time()) + 60}},
                                               "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL}, timeout=15, retry=None))
        assert ts_ and ts_[0].points[0].value.int64_value == n, ts_
        return f"custom metric written and read back = {n}"
    ctx.step("cloud monitoring: custom metric create + write + list (SDK default gRPC)", metric, lane=LANE["real"])
