"""C8 Observability: Cloud Trace v2 batch_write_spans + v1 get_trace/list_traces, Cloud Logging write/list, Cloud Monitoring custom metric write/read (official google-cloud-* clients, REST)."""
from _common import *
import time
from datetime import datetime, timezone, timedelta

s = Step()
P = f"projects/{PROJECT}"
TRACE_ID = uuid.uuid4().hex


def trace_write():
    from google.cloud import trace_v2
    from google.protobuf import timestamp_pb2
    c = rest_client(trace_v2.TraceServiceClient)
    now = datetime.now(timezone.utc)

    def ts(d):
        t = timestamp_pb2.Timestamp(); t.FromDatetime(d); return t
    spans = [trace_v2.Span(name=f"{P}/traces/{TRACE_ID}/spans/{sid}", span_id=sid, display_name=trace_v2.TruncatableString(value=nm),
                           start_time=ts(now), end_time=ts(now + timedelta(milliseconds=40)), parent_span_id=par)
             for sid, nm, par in (("a" * 16, "agent.run", ""), ("b" * 16, "tool.asset_status", "a" * 16))]
    c.batch_write_spans(request={"name": P, "spans": spans})
    return "2 spans written"


def trace_read():
    from google.cloud import trace_v1
    c = rest_client(trace_v1.TraceServiceClient)
    tr = c.get_trace(request={"project_id": PROJECT, "trace_id": TRACE_ID})
    names = sorted(x.name for x in tr.spans)
    assert "agent.run" in names and "tool.asset_status" in names, names
    lst = list(c.list_traces(request={"project_id": PROJECT}))
    assert any(t.trace_id == TRACE_ID for t in lst), "trace not in list_traces"
    return f"v1 get_trace spans={names}"


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_raw():
    """Same calls over raw REST (what the gapic client would send if it had a REST transport)."""
    call("POST", "/v2/entries:write", {"logName": f"{P}/logs/raw", "resource": {"type": "global"}, "entries": [{"jsonPayload": {"event": "tool_call"}, "severity": "INFO"}]})
    r = call("POST", "/v2/entries:list", {"resourceNames": [P], "filter": f'logName="{P}/logs/raw"'})
    assert r.get("entries"), r
    return "raw REST write+list ok"


def log_ts_filter():
    """The high-level SDK appends timestamp>=\"<now-24h>+0000\" to every list_entries; the API accepts that offset form."""
    call("POST", "/v2/entries:write", {"logName": f"{P}/logs/tsf", "resource": {"type": "global"}, "entries": [{"jsonPayload": {"e": 1}}]})
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%f+0000")
    r = call("POST", "/v2/entries:list", {"resourceNames": [P], "filter": f'logName="{P}/logs/tsf" AND timestamp>="{since}"'})
    assert r.get("entries"), f"entry written seconds ago is not returned for timestamp>={since}"
    return "timestamp filter with +0000 offset honoured"


def log_write_list():
    from google.cloud.logging_v2.services.logging_service_v2 import LoggingServiceV2Client
    if "rest" not in LoggingServiceV2Client.get_transport_class.__self__._transport_registry:
        raise Blocked("google-cloud-logging gapic LoggingServiceV2Client has only grpc/grpc_asyncio transports; the simulator front door is HTTP/1.1 only, so this client cannot be pointed at it")
    from google.cloud.logging_v2.types import LogEntry, WriteLogEntriesRequest
    c = rest_client(LoggingServiceV2Client)
    lname = f"{P}/logs/facilities-agent"
    c.write_log_entries(request={"log_name": lname, "resource": {"type": "global", "labels": {"project_id": PROJECT}},
                                 "entries": [{"json_payload": {"event": "tool_call", "tool": "asset_status", "trace": TRACE_ID}, "severity": "INFO"}]})
    got = []
    for _ in range(10):
        got = list(c.list_log_entries(request={"resource_names": [P], "filter": f'logName="{lname}"'}))
        if got:
            break
        time.sleep(0.5)
    assert got and got[0].json_payload["event"] == "tool_call", got
    return f"{len(got)} entries"


def log_highlevel():
    from google.cloud import logging as gl
    c = gl.Client(project=PROJECT, credentials=creds(), _use_grpc=False)
    c._connection.API_BASE_URL = endpoint()
    lg = c.logger("facilities-hl")
    lg.log_struct({"event": "hl"}, severity="INFO")
    got = list(c.list_entries(filter_=f'logName="projects/{PROJECT}/logs/facilities-hl"'))
    assert got, "no entries"
    return f"{len(got)} entries via logging.Client(_use_grpc=False)"


def metric_raw():
    mt = "custom.googleapis.com/facilities/raw_calls"
    call("POST", f"/v3/{P}/metricDescriptors", {"type": mt, "metricKind": "GAUGE", "valueType": "INT64"})
    now = time.time()
    call("POST", f"/v3/{P}/timeSeries", {"timeSeries": [{"metric": {"type": mt}, "resource": {"type": "global", "labels": {"project_id": PROJECT}},
                                                         "points": [{"interval": {"endTime": iso(now)}, "value": {"int64Value": "7"}}]}]})
    r = call("GET", f"/v3/{P}/timeSeries", params={"filter": f'metric.type="{mt}"', "interval.startTime": iso(now - 600), "interval.endTime": iso(now + 60)})
    assert r["timeSeries"][0]["points"][0]["value"]["int64Value"] == "7", r
    return "raw REST custom metric write+read = 7"


def metric():
    from google.cloud import monitoring_v3
    from google.protobuf import timestamp_pb2
    if "rest" not in monitoring_v3.MetricServiceClient.get_transport_class.__self__._transport_registry:
        raise Blocked("google-cloud-monitoring MetricServiceClient has only grpc/grpc_asyncio transports; simulator is HTTP/1.1 only")
    c = rest_client(monitoring_v3.MetricServiceClient)
    mtype = "custom.googleapis.com/facilities/tool_calls"
    c.create_metric_descriptor(request={"name": P, "metric_descriptor": {"type": mtype, "metric_kind": "GAUGE", "value_type": "INT64", "description": "tool calls"}})
    now = time.time()
    ser = monitoring_v3.TimeSeries(metric={"type": mtype, "labels": {"tool": "asset_status"}}, resource={"type": "global", "labels": {"project_id": PROJECT}},
                                   points=[monitoring_v3.Point(interval={"end_time": {"seconds": int(now)}}, value={"int64_value": 7})])
    c.create_time_series(request={"name": P, "time_series": [ser]})
    ts = list(c.list_time_series(request={"name": P, "filter": f'metric.type="{mtype}"', "interval": {"start_time": {"seconds": int(now) - 600}, "end_time": {"seconds": int(now) + 60}},
                                          "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL}))
    assert ts and ts[0].points[0].value.int64_value == 7, ts
    return "custom metric written and read back = 7"


s("Cloud Trace v2: batch_write_spans", trace_write)
s("Cloud Trace v1: get_trace + list_traces read the spans back", trace_read)
s("Cloud Logging raw REST entries:write + entries:list", log_raw)
s("Cloud Logging entries:list honours the SDK's default timestamp>= \"...+0000\" filter", log_ts_filter)
s("Cloud Logging (gapic REST): write_log_entries + list_log_entries", log_write_list)
s("Cloud Logging (high-level logging.Client, HTTP): log_struct + list_entries", log_highlevel)
s("Cloud Monitoring raw REST custom metric write+read", metric_raw)
s("Cloud Monitoring (gapic MetricServiceClient): custom metric write + list", metric)
s.finish()
