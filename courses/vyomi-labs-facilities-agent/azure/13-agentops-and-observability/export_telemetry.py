import json
import logging
import time
import uuid
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import SpanKind, set_span_in_context
from azure.monitor.opentelemetry.exporter import AzureMonitorLogExporter, AzureMonitorMetricExporter, AzureMonitorTraceExporter

obs = json.load(open("obs.json"))
run = json.load(open("run.json"))
cs = obs["ingest"]
ns = lambda t: int(t * 1e9)
tag = uuid.uuid4().hex
spans = run["spans"]

tp = TracerProvider()
tp.add_span_processor(SimpleSpanProcessor(AzureMonitorTraceExporter(connection_string=cs, disable_offline_storage=True)))
tracer = tp.get_tracer("facilities-supervisor")
root = tracer.start_span("facilities-supervisor", start_time=ns(spans[0]["start"]), kind=SpanKind.SERVER, attributes={"facilities.trace": tag, "user": run["user"]})
ctx = set_span_in_context(root)
for s in spans:
    tracer.start_span(s["name"], context=ctx, start_time=ns(s["start"]), attributes={"kind": s["kind"], "facilities.trace": tag}).end(end_time=ns(s["end"]))
root.end(end_time=ns(spans[-1]["end"]))
tp.shutdown()
trace_id = format(root.get_span_context().trace_id, "032x")

lp = LoggerProvider()
lp.add_log_record_processor(SimpleLogRecordProcessor(AzureMonitorLogExporter(connection_string=cs, disable_offline_storage=True)))
log = logging.getLogger("facilities-agent-" + tag[:6])
log.setLevel(logging.INFO)
log.addHandler(LoggingHandler(level=logging.INFO, logger_provider=lp))
log.info("agent_run %s", json.dumps({"event": "agent_run", "trace": tag, "route": run["route"], "tools": [s["name"] for s in spans if s["kind"] == "tool"]}))
lp.shutdown()

n_tools = len([s for s in spans if s["kind"] == "tool"])
reader = PeriodicExportingMetricReader(AzureMonitorMetricExporter(connection_string=cs, disable_offline_storage=True), export_interval_millis=3600_000)
mp = MeterProvider(metric_readers=[reader])
mp.get_meter("facilities").create_counter("facilities.tool_calls").add(n_tools, {"agent": "facilities-supervisor"})
mp.force_flush()
mp.shutdown()

json.dump({"trace_id": trace_id, "tag": tag, "tool_calls": n_tools}, open("trace.json", "w"))
print("exported", len(spans) + 1, "spans, 1 log line and the metric facilities.tool_calls =", n_tools, "| trace id", trace_id)
