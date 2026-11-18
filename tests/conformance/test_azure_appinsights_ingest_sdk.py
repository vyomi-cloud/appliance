"""Application Insights telemetry reaches the Log Analytics workspace tables, written by the REAL exporters, read with the REAL query SDK
(v4 lane az-ref-runtime).

* azure-mgmt-loganalytics + azure-mgmt-applicationinsights create a workspace-based component; its connection string points at the simulator
  (`IngestionEndpoint=<base>/`), so no endpoint override is needed.
* azure-monitor-opentelemetry-exporter (trace, log, metric exporters) and opencensus-ext-azure (AzureLogHandler, AzureEventHandler) POST to
  `/v2.1/track` / `/v2/track`; a raw track call and gzip + NDJSON bodies are covered too.
* azure-monitor-query `LogsQueryClient.query_workspace` runs KQL over AppRequests, AppDependencies, AppTraces, AppExceptions, AppMetrics, AppEvents.

Needs: requirements.txt + azure-mgmt-loganalytics/-applicationinsights/-resource, azure-monitor-query, azure-monitor-opentelemetry-exporter,
opentelemetry-sdk (opencensus-ext-azure optional). Run: PYTHONPATH=. python tests/conformance/test_azure_appinsights_ingest_sdk.py
"""
import gzip
import json
import os
import socket
import sys
import tempfile
import unittest
import threading
import time
import uuid

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
for _m in ("azure.mgmt.loganalytics", "azure.mgmt.applicationinsights", "azure.mgmt.resource", "azure.monitor.query", "azure.monitor.opentelemetry.exporter",
           "opentelemetry.sdk", "requests"):
    try:
        __import__(_m)
    except ImportError as _e:
        print("SKIP: %s not installed (%s)" % (_m, _e))
        sys.exit(0)

_work = tempfile.mkdtemp(prefix="az-ai-ingest-")
os.environ.update({"CLOUDLEARN_STATE_FILE": os.path.join(_work, "state.sqlite3"), "VYOMI_DATA_DIR": _work, "CLOUDLEARN_TIER_ENFORCE": "0",
                   "VYOMI_AZSB_DB": os.path.join(_work, "azsb.sqlite")})
SUB, RG, LOC, TAG = "00000000-0000-0000-0000-cloudlearn01", "rg-obs", "eastus", uuid.uuid4().hex[:6]
RESULTS = []


def _free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def start():
    port, amqp = _free(), _free()
    os.environ.update({"VYOMI_AMQP_PORT": str(amqp), "VYOMI_AMQPS_PORT": "0", "VYOMI_AMQP_HOST": "127.0.0.1"})
    os.chdir(ROOT)
    import uvicorn
    import server
    try:
        from core import azure_arm_core
        azure_arm_core.AzureArm.STRICT_SUBSCRIPTION = False
    except Exception:
        pass
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    t0 = time.time()
    while not srv.started:
        if time.time() - t0 > 240:
            raise SystemExit("appliance did not start")
        time.sleep(0.1)
    time.sleep(1.0)
    return "http://127.0.0.1:%d" % port


def check(name, fn):
    try:
        out = fn()
        print("[PASS] %s%s" % (name, (" -> " + str(out)[:220]) if out else ""), flush=True)
        RESULTS.append(True)
        return out
    except unittest.SkipTest as e:
        print("[SKIP] %s: %s" % (name, e), flush=True)
    except Exception as e:  # noqa: BLE001
        print("[FAIL] %s: %s: %s" % (name, type(e).__name__, str(e)[:500]), flush=True)
        RESULTS.append(False)


def must(cond, msg="assertion failed"):
    if not cond:
        raise AssertionError(msg)
    return True


class Cred:
    def get_token(self, *a, **k):
        from azure.core.credentials import AccessToken
        return AccessToken("vyomi-test-token", 4102444800)


def arm(cls, base):
    from azure.core.pipeline.policies import SansIOHTTPPolicy
    return cls(Cred(), SUB, base_url=base, authentication_policy=SansIOHTTPPolicy(), polling_interval=0)


def main():
    import requests
    from azure.core.pipeline.policies import SansIOHTTPPolicy
    from azure.mgmt.applicationinsights import ApplicationInsightsManagementClient
    from azure.mgmt.loganalytics import LogAnalyticsManagementClient
    from azure.mgmt.resource.resources import ResourceManagementClient
    from azure.monitor.query import LogsQueryClient

    base = start()
    arm(ResourceManagementClient, base).resource_groups.create_or_update(RG, {"location": LOC})
    la = arm(LogAnalyticsManagementClient, base)
    ws = la.workspaces.begin_create_or_update(RG, "law-" + TAG, {"location": LOC}).result()
    wsid = "/subscriptions/%s/resourceGroups/%s/providers/Microsoft.OperationalInsights/workspaces/law-%s" % (SUB, RG, TAG)
    comp = arm(ApplicationInsightsManagementClient, base).components.create_or_update(
        RG, "ai-" + TAG, {"location": LOC, "kind": "web", "application_type": "web", "workspace_resource_id": wsid})
    cs = comp.connection_string
    ikey = cs.split("InstrumentationKey=")[1].split(";")[0]
    q = LogsQueryClient(Cred(), endpoint=base + "/azure-data/loganalytics", authentication_policy=SansIOHTTPPolicy())

    def kql(query):
        r = q.query_workspace("law-" + TAG, query, timespan=None)
        t = r.tables[0]
        return [dict(zip(t.columns, row)) for row in t.rows]

    def wait(query, pred, timeout=20):
        t0 = time.time()
        rows = []
        while time.time() - t0 < timeout:
            rows = kql(query)
            if pred(rows):
                return rows
            time.sleep(0.5)
        raise AssertionError("no matching rows for %s: %s" % (query, rows[:3]))

    check("component connection string points at the simulator (absolute IngestionEndpoint)", lambda: must(
        "IngestionEndpoint=%s;" % base in cs and ikey, cs) and cs)

    # ── azure-monitor-opentelemetry-exporter ──
    def otel_traces():
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.trace import SpanKind
        exp = AzureMonitorTraceExporter(connection_string=cs, disable_offline_storage=True)
        tp = TracerProvider(resource=Resource.create({"service.name": "facilities-supervisor"}))
        tp.add_span_processor(SimpleSpanProcessor(exp))
        tr = tp.get_tracer("t")
        with tr.start_as_current_span("supervisor.run", kind=SpanKind.SERVER, attributes={"http.method": "POST", "http.url": "http://x/run", "http.status_code": 200, "run": TAG}):
            with tr.start_as_current_span("tool.lookup_asset", kind=SpanKind.CLIENT, attributes={"http.url": "http://tools/api/lookup", "http.status_code": 200, "http.method": "GET"}):
                pass
            try:
                with tr.start_as_current_span("tool.fail", kind=SpanKind.INTERNAL):
                    raise ValueError("boom-" + TAG)
            except ValueError:
                pass
        tp.force_flush(); tp.shutdown()
        req = wait("AppRequests | where Properties.run == '%s' | project Name, Success, ResultCode, DurationMs, AppRoleName" % TAG, lambda r: r)
        must(req[0]["Success"] is True and req[0]["AppRoleName"] == "facilities-supervisor", req)
        dep = wait("AppDependencies | where Data contains 'api/lookup' | project Name, Target, Success, DurationMs", lambda r: r)
        exc = wait("AppExceptions | where ExceptionType == 'ValueError' and OuterMessage contains '%s'" % TAG, lambda r: r)
        must("boom-" + TAG in str(exc[0]["OuterMessage"]), exc)
        return "AppRequests %d, AppDependencies %d, AppExceptions %d" % (len(req), len(dep), len(exc))
    check("OpenTelemetry trace exporter: server span -> AppRequests, client span -> AppDependencies, exception event -> AppExceptions", otel_traces)

    def otel_logs():
        import logging
        from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
        lp = LoggerProvider()
        lp.add_log_record_processor(SimpleLogRecordProcessor(AzureMonitorLogExporter(connection_string=cs, disable_offline_storage=True)))
        lg = logging.getLogger("otel-" + TAG)
        lg.setLevel(logging.INFO)
        lg.addHandler(LoggingHandler(level=logging.INFO, logger_provider=lp))
        lg.warning("approval pending %s", TAG)
        lp.force_flush(); lp.shutdown()
        rows = wait("AppTraces | where Message contains 'approval pending %s' | project Message, SeverityLevel" % TAG, lambda r: r)
        return rows[0]
    check("OpenTelemetry log exporter: logging records -> AppTraces", otel_logs)

    def otel_metrics():
        from azure.monitor.opentelemetry.exporter import AzureMonitorMetricExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        rd = PeriodicExportingMetricReader(AzureMonitorMetricExporter(connection_string=cs, disable_offline_storage=True), export_interval_millis=3600000)
        mp = MeterProvider(metric_readers=[rd])
        c = mp.get_meter("m").create_counter("agent.tool_calls_" + TAG)
        c.add(3)
        mp.force_flush(); mp.shutdown()
        rows = wait("AppMetrics | where Name == 'agent.tool_calls_%s' | project Name, Sum, ItemCount" % TAG, lambda r: r)
        must(rows[0]["Sum"] == 3, rows)
        return rows[0]
    check("OpenTelemetry metric exporter: counter -> AppMetrics", otel_metrics)

    # ── opencensus-ext-azure ──
    def oc_check():
        import logging
        from opencensus.ext.azure.log_exporter import AzureEventHandler, AzureLogHandler
        lg = logging.getLogger("oc-" + TAG)
        lg.setLevel(logging.INFO)
        h = AzureLogHandler(connection_string=cs, export_interval=0.2)
        e = AzureEventHandler(connection_string=cs, export_interval=0.2)
        lg.addHandler(h)
        try:
            lg.warning("opencensus trace %s", TAG)
        except TypeError as e:      # opencensus-ext-azure 1.1.x never initialises the Handler lock: broken on Python >= 3.13 (upstream), not a simulator issue
            raise unittest.SkipTest("opencensus-ext-azure is incompatible with this Python (%s)" % e)
        ev = logging.getLogger("oc-ev-" + TAG)
        ev.setLevel(logging.INFO)
        ev.addHandler(e)
        ev.info("tool_called_" + TAG, extra={"custom_dimensions": {"tool": "lookup_asset"}})
        h.flush(); e.flush(); time.sleep(0.5)
        t = wait("AppTraces | where Message contains 'opencensus trace %s'" % TAG, lambda r: r)
        ev_rows = wait("AppEvents | where Name == 'tool_called_%s'" % TAG, lambda r: r)
        return "AppTraces %d, AppEvents %d" % (len(t), len(ev_rows))
    try:
        import opencensus.ext.azure  # noqa: F401
        check("opencensus-ext-azure: AzureLogHandler -> AppTraces, AzureEventHandler -> AppEvents", oc_check)
    except ImportError:
        print("[SKIP] opencensus-ext-azure not installed")

    # ── raw track API variants ──
    def raw_track():
        item = {"name": "Microsoft.ApplicationInsights.Event", "time": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()), "iKey": ikey,
                "tags": {"ai.cloud.role": "raw-role"}, "data": {"baseType": "EventData", "baseData": {"ver": 2, "name": "raw_event_" + TAG, "properties": {"k": "v-" + TAG}}}}
        r = requests.post(base + "/v2/track", json=[item], timeout=10)
        must(r.status_code == 200 and r.json() == {"itemsReceived": 1, "itemsAccepted": 1, "errors": []}, (r.status_code, r.text))
        r = requests.post(base + "/v2.1/track", data=gzip.compress(json.dumps([item]).encode()), headers={"Content-Encoding": "gzip"}, timeout=10)
        must(r.status_code == 200, r.text)
        r = requests.post(base + "/_obs/v2.1/track", data=(json.dumps(item) + "\n" + json.dumps(item)), timeout=10)
        must(r.status_code == 200 and r.json()["itemsAccepted"] == 2, r.text)
        rows = wait("AppEvents | where Name == 'raw_event_%s' | where Properties.k == 'v-%s' | summarize n = count() by AppRoleName" % (TAG, TAG), lambda r: r)
        must(rows[0]["n"] == 4, rows)
        bad = requests.post(base + "/v2/track", json=[dict(item, iKey="00000000-0000-0000-0000-000000000000")], timeout=10)
        must(bad.status_code == 400 and bad.json()["itemsAccepted"] == 0 and "Invalid instrumentation key" in bad.text, bad.text)
        return "/v2/track, /v2.1/track (gzip), /_obs/v2.1/track (NDJSON), dynamic Properties.k filter, unknown iKey -> 400"
    check("raw track API: array, gzip, NDJSON bodies; KQL on dynamic Properties; unknown iKey rejected", raw_track)

    def tables_defined():
        for t in ("AppRequests", "AppDependencies", "AppTraces", "AppExceptions", "AppMetrics", "AppEvents", "AppPageViews", "AppAvailabilityResults"):
            kql("%s | take 1" % t)
        return "8 App* tables resolve"
    check("every App* table is defined in the workspace (empty query still resolves)", tables_defined)

    def kql_analysis():
        rows = kql("AppRequests | where TimeGenerated > ago(1h) | summarize n = count(), avg_ms = avg(DurationMs) by Name | order by n desc")
        must(rows and rows[0]["n"] >= 1, rows)
        return rows[0]
    check("KQL summarize/avg over AppRequests through LogsQueryClient", kql_analysis)

    print("\n%d/%d passed" % (sum(RESULTS), len(RESULTS)), flush=True)
    os._exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()
