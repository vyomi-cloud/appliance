"""C8: AgentOps: spans from the agent run -> Application Insights (azure-monitor-opentelemetry-exporter), structured log lines, a custom metric, then read them back
with KQL from the linked Log Analytics workspace (azure-monitor-query) and read platform metrics from Azure Monitor."""
import json, time, uuid
from datetime import timedelta
from ..runtime import NAMES, LANE, RG, LOC, need_result


def _ns(t):
    return int(t * 1e9)


def run(ctx):
    res = ctx.state.get("result", {})
    spans = res.get("spans", [])
    tid = uuid.uuid4().hex
    ctx.state["trace_id"] = tid
    now = time.time()
    t0 = spans[0]["start"] if spans else now
    t1 = spans[-1]["end"] if spans else now + 0.05

    def have_run():
        need_result(ctx, "trace")
        return f"{len(spans)} agent spans to export"
    ctx.step("the agent run produced spans to export", have_run)

    def resources():
        from azure.mgmt.loganalytics import LogAnalyticsManagementClient
        from azure.mgmt.applicationinsights import ApplicationInsightsManagementClient
        ws = ctx.arm(LogAnalyticsManagementClient).workspaces.begin_create_or_update(RG, NAMES["workspace"], {"location": LOC}).result()
        c = ctx.arm(ApplicationInsightsManagementClient).components.create_or_update(RG, NAMES["insights"], {
            "location": LOC, "kind": "web", "application_type": "web", "workspace_resource_id": ctx.rid("Microsoft.OperationalInsights", "workspaces", NAMES["workspace"])})
        ctx.state.update(workspace_id=ws.customer_id, ai_cs=c.connection_string)
        ikey = c.connection_string.split("InstrumentationKey=")[1].split(";")[0]
        ctx.state["ingest_cs"] = f"InstrumentationKey={ikey};IngestionEndpoint={ctx.endpoint}/"
        return f"workspace {NAMES['workspace']} (customerId {ws.customer_id}) + workspace-based Application Insights {NAMES['insights']}"
    ctx.step("log analytics workspace + workspace-based application insights component via ARM", resources)

    def push():
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.trace import SpanKind
        exp = AzureMonitorTraceExporter(connection_string=ctx.state["ingest_cs"], disable_offline_storage=True)
        tp = TracerProvider()
        tp.add_span_processor(SimpleSpanProcessor(exp))
        tr = tp.get_tracer("facilities-supervisor")
        root = tr.start_span("facilities-supervisor", start_time=_ns(t0), kind=SpanKind.SERVER, attributes={"facilities.trace": tid, "user": ctx.state.get("user", "")})
        rctx = trace.set_span_in_context(root)
        for s in spans:
            c = tr.start_span(s["name"], context=rctx, start_time=_ns(s["start"]), attributes={"kind": s["kind"], "facilities.trace": tid})
            c.end(end_time=_ns(s["end"]))
        root.end(end_time=_ns(t1))
        tp.shutdown()
        ctx.state["otel_trace_id"] = format(root.get_span_context().trace_id, "032x")
        return f"{len(spans) + 1} spans exported to Application Insights (operation_Id {ctx.state['otel_trace_id']})"
    ctx.step("application insights: export one span per agent / tool step (azure-monitor-opentelemetry-exporter)", push, lane=LANE["runtime"])

    def logs():
        import logging
        from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
        lp = LoggerProvider()
        lp.add_log_record_processor(SimpleLogRecordProcessor(AzureMonitorLogExporter(connection_string=ctx.state["ingest_cs"], disable_offline_storage=True)))
        lg = logging.getLogger("facilities-agent-" + tid[:6])
        lg.setLevel(logging.INFO)
        lg.addHandler(LoggingHandler(level=logging.INFO, logger_provider=lp))
        lg.info("agent_run %s", json.dumps({"event": "agent_run", "trace": tid, "route": res.get("route"), "tools": [t["tool"] for t in res.get("tools", [])]}))
        lp.shutdown()
        return "structured agent log record exported to Application Insights"
    ctx.step("application insights: export a structured agent log line (azure-monitor-opentelemetry-exporter logs)", logs, lane=LANE["runtime"])

    def metric():
        from azure.monitor.opentelemetry.exporter import AzureMonitorMetricExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        n = len(res.get("tools", [])) or 1
        rd = PeriodicExportingMetricReader(AzureMonitorMetricExporter(connection_string=ctx.state["ingest_cs"], disable_offline_storage=True), export_interval_millis=3600_000)
        mp = MeterProvider(metric_readers=[rd])
        mp.get_meter("facilities").create_counter("facilities.tool_calls").add(n, {"agent": "facilities-supervisor"})
        mp.force_flush()
        mp.shutdown()
        ctx.state["tool_calls"] = n
        return f"custom metric facilities.tool_calls={n} exported"
    ctx.step("application insights: export a custom metric (facilities.tool_calls)", metric, lane=LANE["runtime"])

    def kql():
        from azure.monitor.query import LogsQueryClient
        c = LogsQueryClient(ctx.cred(), endpoint=ctx.endpoint + "/azure-data/loganalytics")

        def q(text):
            r = c.query_workspace(ctx.state["workspace_id"], text, timespan=timedelta(hours=2))
            return r.tables[0].rows if r.tables else []
        deps = []
        for _ in range(20):
            deps = q(f"AppDependencies | where OperationId == '{ctx.state['otel_trace_id']}' | project Name | order by Name asc")
            if deps:
                break
            time.sleep(1)
        assert deps, "no spans read back from AppDependencies / AppRequests for the exported trace"
        names = {r[0] for r in deps}
        assert any(n.startswith("agent:") for n in names), names
        traces = q(f"AppTraces | where Message has '{tid}' | project Message")
        assert traces, "the structured agent log line was not read back from AppTraces"
        return f"KQL read back {len(deps)} spans ({sorted(names)[:3]}...) and {len(traces)} log line(s) from the workspace"
    if ctx.state.get("otel_trace_id") and ctx.state.get("workspace_id"):
        ctx.step("log analytics: KQL (azure-monitor-query LogsQueryClient) reads the spans and the log line back", kql, lane=LANE["runtime"])

    def kql_metric():
        from azure.monitor.query import LogsQueryClient
        c = LogsQueryClient(ctx.cred(), endpoint=ctx.endpoint + "/azure-data/loganalytics")
        r = c.query_workspace(ctx.state["workspace_id"], "AppMetrics | where Name == 'facilities.tool_calls' | summarize total=sum(Sum)", timespan=timedelta(hours=2))
        rows = r.tables[0].rows
        assert rows and rows[0][0] == ctx.state["tool_calls"], rows
        return f"AppMetrics facilities.tool_calls total = {rows[0][0]}"
    if ctx.state.get("tool_calls"):
        ctx.step("log analytics: KQL reads the custom metric back from AppMetrics", kql_metric, lane=LANE["runtime"])

    def custom_table():
        """Direct ingestion into a custom table (HTTP Data Collector API) and KQL read-back: the AgentRun_CL table."""
        import requests
        from azure.monitor.query import LogsQueryClient
        r = requests.post(f"{ctx.endpoint}{ctx.rid('Microsoft.OperationalInsights', 'workspaces', NAMES['workspace'])}/api/logs", headers={"Log-Type": "AgentRun"},
                          json=[{"run": tid, "tool": t["tool"], "via": t["via"]} for t in res.get("tools", [])] or [{"run": tid, "tool": "none", "via": "none"}], timeout=20)
        assert r.status_code in (200, 202), f"HTTP {r.status_code}: {r.text[:120]}"
        c = LogsQueryClient(ctx.cred(), endpoint=ctx.endpoint + "/azure-data/loganalytics")
        rows = c.query_workspace(ctx.state["workspace_id"], f"AgentRun_CL | where run_s == '{tid}' | summarize n=count() by tool_s", timespan=timedelta(hours=2)).tables[0].rows
        assert rows, "ingested rows not returned"
        return f"AgentRun_CL: {len(rows)} tool group(s) read back with summarize"
    if ctx.state.get("workspace_id"):
        ctx.step("log analytics: custom table ingest (Data Collector) + KQL summarize read-back", custom_table, lane=LANE["runtime"])

    def metrics():
        from azure.mgmt.monitor import MonitorManagementClient
        rid = ctx.rid("Microsoft.Storage", "storageAccounts", NAMES["docs_account"])
        m = ctx.arm(MonitorManagementClient).metrics.list(rid, metricnames="Transactions", aggregation="Total", timespan="2026-11-17T00:00:00Z/2026-11-19T00:00:00Z", interval="PT1H")
        assert m.value, "no metrics returned"
        return [x.name.value for x in m.value]
    ctx.step("azure monitor: platform metrics.list on the docs storage account (azure-mgmt-monitor)", metrics)
