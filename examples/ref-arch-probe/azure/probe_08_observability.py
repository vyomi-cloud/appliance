"""Component 8 Observability: Application Insights ingest, Log Analytics ingest + KQL read-back, Azure Monitor metrics."""
import json, time, requests
from _common import *

P = Probe(8, "observability", "Observability: App Insights + Log Analytics + Monitor metrics")
B = endpoint(); ensure_rg(B)
S = {}
WS = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.OperationalInsights/workspaces/law1"


def workspace_and_ai():
    from azure.mgmt.loganalytics import LogAnalyticsManagementClient
    from azure.mgmt.applicationinsights import ApplicationInsightsManagementClient
    arm(LogAnalyticsManagementClient, B).workspaces.begin_create_or_update(RG, "law1", {"location": LOC}).result()
    c = arm(ApplicationInsightsManagementClient, B).components.create_or_update(RG, "ai1", {"location": LOC, "kind": "web", "application_type": "web", "workspace_resource_id": WS})
    S["cs"] = c.connection_string
    return c.connection_string


def ingest_exporter():
    """Real exporter (azure-monitor-opentelemetry-exporter) posting spans to the connection string's IngestionEndpoint."""
    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    ikey = S["cs"].split("InstrumentationKey=")[1].split(";")[0]
    exp = AzureMonitorTraceExporter(connection_string=f"InstrumentationKey={ikey};IngestionEndpoint={B}/")
    tp = TracerProvider(); tp.add_span_processor(SimpleSpanProcessor(exp))
    with tp.get_tracer("probe").start_as_current_span("agent.run"):
        pass
    tp.shutdown()
    return "span exported without error"


def ingest_track_raw():
    ikey = S["cs"].split("InstrumentationKey=")[1].split(";")[0]
    r = requests.post(B + "/v2/track", json=[{"name": "Microsoft.ApplicationInsights.Message", "time": "2026-11-18T00:00:00Z", "iKey": ikey,
        "data": {"baseType": "MessageData", "baseData": {"ver": 2, "message": "probe-trace-line"}}}], timeout=10)
    assert r.status_code == 200, (r.status_code, r.text[:120])


def kql(q):
    r = requests.post(B + WS + "/api/query", params={"api-version": "2017-10-01"}, json={"query": q}, timeout=20)
    assert r.status_code == 200, (r.status_code, r.text[:150])
    t = r.json()["tables"][0]
    return t["columns"], t["rows"]


def kql_apptraces():
    c, rows = kql("AppTraces | where Message == 'probe-trace-line'")
    assert rows, "telemetry sent to App Insights is not queryable in the linked workspace (AppTraces empty)"
    return len(rows)


def custom_ingest():
    """HTTP Data Collector (api/logs) then KQL read-back of the custom table."""
    r = requests.post(B + WS + "/api/logs", headers={"Log-Type": "AgentRun"}, json=[{"run": "r1", "tool": "lookup_asset", "ms": 12}], timeout=10)
    assert r.status_code in (200, 202), (r.status_code, r.text[:100])
    c, rows = kql("AgentRun_CL | where run_s == 'r1'")
    assert rows, "ingested row not returned"
    return {"cols": c and [x["name"] for x in c][:6], "rows": len(rows)}


def kql_summarize():
    c, rows = kql("AgentRun_CL | summarize n=count() by tool_s")
    assert rows and rows[0][-1] in (1, "1"), rows


def kql_realistic():
    """A typical trace analysis: extend + where on a time window + summarize avg + render. Real Kusto only."""
    c, rows = kql("AgentRun_CL | where TimeGenerated > ago(1h) | extend slow = ms_d > 5 | summarize avg(ms_d) by tool_s | order by avg_ms_d desc")
    assert rows, "no rows (extend / ago() / avg / order by not understood)"


def logsquery_sdk():
    from azure.monitor.query import LogsQueryClient
    c = LogsQueryClient(Cred(), endpoint=B)
    r = c.query_workspace("law1", "AgentRun_CL | take 1", timespan=None)
    assert r.tables


def metrics():
    from azure.mgmt.monitor import MonitorManagementClient
    from azure.mgmt.storage import StorageManagementClient
    arm(StorageManagementClient, B).storage_accounts.begin_create(RG, "stobs1", {"location": LOC, "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}).result()
    rid = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Storage/storageAccounts/stobs1"
    m = arm(MonitorManagementClient, B).metrics.list(rid, metricnames="Transactions", aggregation="Total", timespan="2026-11-17T00:00:00Z/2026-11-19T00:00:00Z", interval="PT1H")
    assert m.value, "no metric definitions returned"
    return [x.name.value for x in m.value]


def otlp():
    r = requests.post(B + "/_obs/v1/traces", json={"resourceSpans": []}, timeout=10)
    assert r.status_code in (200, 204), r.status_code


P.step("Log Analytics workspace + Application Insights component (workspace-based) via ARM", workspace_and_ai)
P.step("ingest a span with azure-monitor-opentelemetry-exporter", ingest_exporter)
P.step("ingest a MessageData item at /v2/track (App Insights wire)", ingest_track_raw)
P.step("read App Insights telemetry back with KQL (AppTraces)", kql_apptraces)
if P.step("Log Analytics custom-table ingest (Data Collector) + KQL where read-back", custom_ingest):
    P.step("KQL summarize count() by", kql_summarize)
    P.step("KQL extend + ago() + avg() + order by", kql_realistic)
P.step("azure-monitor-query LogsQueryClient (api.loganalytics.io host form)", logsquery_sdk)
P.step("Azure Monitor metrics.list on a storage account (azure-mgmt-monitor)", metrics)
P.step("OTLP/HTTP ingest at /_obs/v1/traces", otlp)
P.finish()
