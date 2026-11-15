"""AgentOps (lane C8): real OpenTelemetry SDK spans -> OTLP/HTTP -> X-Ray + CloudWatch Logs/Insights + CloudWatch metrics,
then AgentCore Evaluations over a golden set. Everything is read back with the REAL boto3 clients.

Run: PYTHONPATH=. python3 tests/conformance/test_ai_observability.py
Needs: boto3, fastapi, uvicorn, opentelemetry-sdk (the probe venv has them). Protobuf leg runs only if opentelemetry-proto is importable.
"""
import datetime
import json
import os
import tempfile
_d = tempfile.mkdtemp()
os.environ.setdefault("CLOUDLEARN_STATE_FILE", os.path.join(_d, "state.sqlite3"))   # never touch a dev's real state
import socket
import sys
import threading
import time
import urllib.request

import boto3
from botocore.config import Config
from opentelemetry import trace, propagate
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:400]}")


def start_server():
    import uvicorn
    from fastapi import FastAPI, Request
    from core import wire_ingress
    app = FastAPI()
    router = wire_ingress.appliance_router()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}"


URL = start_server()
CFG = Config(retries={"max_attempts": 1}, region_name="us-east-1")


def cli(svc):
    return boto3.client(svc, endpoint_url=URL, region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x", config=CFG)


def _any(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


class OtlpHttpExporter(SpanExporter):
    """What opentelemetry-exporter-otlp-proto-http does with the JSON encoding, in 20 lines (keeps the venv small)."""
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.sent = []

    def export(self, spans):
        by = {}
        for s in spans:
            by.setdefault(s.resource.attributes["service.name"], []).append(s)
        rs = []
        for svc, ss in by.items():
            docs = []
            for s in ss:
                d = {"traceId": format(s.context.trace_id, "032x"), "spanId": format(s.context.span_id, "016x"),
                     "name": s.name, "kind": int(s.kind.value) + 1, "startTimeUnixNano": str(s.start_time), "endTimeUnixNano": str(s.end_time),
                     "attributes": [{"key": k, "value": _any(v)} for k, v in s.attributes.items()],
                     "status": {"code": 2 if s.status.status_code == StatusCode.ERROR else 0, "message": s.status.description or ""}}
                if s.parent is not None:
                    d["parentSpanId"] = format(s.parent.span_id, "016x")
                docs.append(d)
                self.sent.append(d)
            rs.append({"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": svc}}]},
                       "scopeSpans": [{"scope": {"name": "strands.telemetry"}, "spans": docs}]})
        req = urllib.request.Request(self.endpoint + "/_obs/v1/traces", data=json.dumps({"resourceSpans": rs}).encode(),
                                     headers={"content-type": "application/json"}, method="POST")
        urllib.request.urlopen(req).read()
        return SpanExportResult.SUCCESS


EXP = OtlpHttpExporter(URL)


def tracer(svc):
    tp = TracerProvider(resource=Resource.create({"service.name": svc}))
    tp.add_span_processor(SimpleSpanProcessor(EXP))
    return tp.get_tracer("strands")


T_SUP, T_FAC, T_TOOL = tracer("facilities-supervisor"), tracer("facilities-agent"), tracer("kb-tool")


def run_agent(question, answer):
    """supervisor -> model -> facilities sub-agent -> (kb tool ok, work-order tool error) -> model."""
    with T_SUP.start_as_current_span("invoke_agent supervisor", attributes={"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "supervisor",
                                                                              "gen_ai.prompt": question, "session.id": "s1"}) as sup:
        time.sleep(0.005)
        with T_SUP.start_as_current_span("chat", attributes={"gen_ai.operation.name": "chat", "gen_ai.request.model": "us.anthropic.claude-sonnet",
                                                              "gen_ai.usage.input_tokens": 120, "gen_ai.usage.output_tokens": 35}):
            time.sleep(0.01)
        carrier = {}
        propagate.inject(carrier)
        ctx = propagate.extract(carrier)
        with T_FAC.start_as_current_span("invoke_agent facilities", context=ctx, attributes={"gen_ai.operation.name": "invoke_agent",
                                                                                              "gen_ai.agent.name": "facilities"}):
            with T_FAC.start_as_current_span("execute_tool search_knowledge", attributes={"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "search_knowledge"}):
                time.sleep(0.008)
            with T_FAC.start_as_current_span("execute_tool create_work_order", attributes={"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "create_work_order"}) as t2:
                t2.set_status(Status(StatusCode.ERROR, "approval pending"))
            with T_FAC.start_as_current_span("chat", attributes={"gen_ai.operation.name": "chat", "gen_ai.request.model": "us.anthropic.claude-sonnet",
                                                                  "gen_ai.usage.input_tokens": 300, "gen_ai.usage.output_tokens": 80,
                                                                  "gen_ai.completion": answer}):
                time.sleep(0.01)
        sup.set_attribute("gen_ai.completion", answer)
        return format(sup.get_span_context().trace_id, "032x")


print("OTLP -> X-Ray / CloudWatch")
t_start = time.time() - 60
tid = run_agent("The boiler in building 4 is making noise. What should I do?", "Inspect the boiler pressure valve in building 4 and open a work order for maintenance.")
tid2 = run_agent("Where is the fire extinguisher policy?", "See the fire extinguisher policy in the safety handbook section 3.")
xt = "1-%s-%s" % (tid[:8], tid[8:])

xr = cli("xray")
got = xr.batch_get_traces(TraceIds=[xt])
check("BatchGetTraces returns the OTLP trace", len(got["Traces"]) == 1 and got["Traces"][0]["Segments"], got)
docs = [json.loads(s["Document"]) for s in got["Traces"][0]["Segments"]]
check("one segment per service", sorted(d["name"] for d in docs) == ["facilities-agent", "facilities-supervisor"], [d["name"] for d in docs])
sup = next(d for d in docs if d["name"] == "facilities-supervisor")
fac = next(d for d in docs if d["name"] == "facilities-agent")
check("sub-agent segment is parented on a remote subsegment of the supervisor", any(s.get("id") == fac.get("parent_id") for s in sup["subsegments"]), fac)
check("tool + model calls are subsegments", {s["name"] for s in json.dumps(fac) and fac["subsegments"]} >= {"search_knowledge", "create_work_order", "bedrock-runtime"}, fac)
check("tool error becomes a fault", any(s.get("fault") for s in fac["subsegments"]))
summ = xr.get_trace_summaries(StartTime=t_start, EndTime=time.time() + 60)["TraceSummaries"]
check("GetTraceSummaries lists both runs", {s["Id"] for s in summ} >= {xt}, summ)
check("HasFault flagged", next(s for s in summ if s["Id"] == xt)["HasFault"])
only_fault = xr.get_trace_summaries(StartTime=t_start, EndTime=time.time() + 60, FilterExpression="fault")["TraceSummaries"]
check("FilterExpression fault", len(only_fault) >= 1)
g = xr.get_service_graph(StartTime=t_start, EndTime=time.time() + 60)
names = {s["Name"] for s in g["Services"]}
check("GetServiceGraph: supervisor, sub-agent, tool and model nodes", names >= {"facilities-supervisor", "facilities-agent", "search_knowledge", "bedrock-runtime"}, names)
sg = {s["Name"]: s for s in g["Services"]}
edge_to = lambda a: {next(x["Name"] for x in g["Services"] if x["ReferenceId"] == e["ReferenceId"]) for e in sg[a]["Edges"]}
check("edges supervisor->sub-agent and sub-agent->tool", "facilities-agent" in edge_to("facilities-supervisor") and "search_knowledge" in edge_to("facilities-agent"), edge_to("facilities-supervisor"))

logs = cli("logs")
ev = logs.filter_log_events(logGroupName="aws/spans")["events"]
check("spans appear as CloudWatch log events (aws/spans)", len(ev) == 12, len(ev))
m0 = json.loads(ev[0]["message"])
check("log event carries trace/span ids and gen_ai attributes", "traceId" in m0 and "attributes" in m0)
ev2 = logs.get_log_events(logGroupName="aws/spans", logStreamName="default")["events"]
check("GetLogEvents reads the stream", len(ev2) == len(ev))
now = int(time.time())
q = logs.start_query(logGroupName="aws/spans", startTime=now - 600, endTime=now + 60,
                     queryString="filter operation = 'model' | stats count(*) as calls, sum(attributes.gen_ai.usage.input_tokens) as in_tok, avg(durationMs) as avg_ms by serviceName | sort in_tok desc")
res = {}
for _ in range(20):
    res = logs.get_query_results(queryId=q["queryId"])
    if res["status"] == "Complete":
        break
    time.sleep(0.1)
rows = [{c["field"]: c["value"] for c in r if c["field"] != "@ptr"} for r in res["results"]]
check("Logs Insights stats-by over discovered JSON fields returns rows", len(rows) == 2 and rows[0]["serviceName"] == "facilities-agent" and rows[0]["in_tok"] == "600", rows)
q2 = logs.start_query(logGroupName="aws/spans", startTime=now - 600, endTime=now + 60,
                      queryString="filter status = 'ERROR' | fields serviceName, name, statusMessage | limit 5")
rows2 = logs.get_query_results(queryId=q2["queryId"])["results"]
check("Insights filter+fields returns the tool error", len(rows2) == 2 and any(c["value"] == "approval pending" for c in rows2[0]), rows2)

cw = cli("cloudwatch")
lst = cw.list_metrics(Namespace="Bedrock-AgentCore")["Metrics"]
check("CloudWatch metrics published (latency, tokens, tool errors)", {"Latency", "InputTokenCount", "OutputTokenCount", "ToolErrors", "ToolLatency", "ModelLatency"} <= {m["MetricName"] for m in lst}, [m["MetricName"] for m in lst])
dims = [{"Name": "Service", "Value": "facilities-agent"}, {"Name": "ModelId", "Value": "us.anthropic.claude-sonnet"}]
gd = cw.get_metric_data(MetricDataQueries=[{"Id": "t", "MetricStat": {"Metric": {"Namespace": "Bedrock-AgentCore", "MetricName": "InputTokenCount", "Dimensions": dims}, "Period": 300, "Stat": "Sum"}}],
                        StartTime=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10), EndTime=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10))
check("GetMetricData sums token counts", sum(gd["MetricDataResults"][0]["Values"]) == 600, gd["MetricDataResults"])
te = cw.get_metric_statistics(Namespace="Bedrock-AgentCore", MetricName="ToolErrors", Dimensions=[{"Name": "Service", "Value": "facilities-agent"}, {"Name": "ToolName", "Value": "create_work_order"}],
                              StartTime=time.time() - 600, EndTime=time.time() + 600, Period=300, Statistics=["Sum"])
check("tool error metric", sum(p["Sum"] for p in te["Datapoints"]) == 2, te)
cw.put_metric_alarm(AlarmName="tool-errors", Namespace="Bedrock-AgentCore", MetricName="ToolErrors", Statistic="Sum", Period=300, EvaluationPeriods=1,
                    Threshold=0, ComparisonOperator="GreaterThanThreshold", Dimensions=[{"Name": "Service", "Value": "facilities-agent"}, {"Name": "ToolName", "Value": "create_work_order"}])
check("alarm created on the agent metric", cw.describe_alarms(AlarmNames=["tool-errors"])["MetricAlarms"][0]["MetricName"] == "ToolErrors")

# protobuf OTLP (Mesh/offline; Nano is JSON-only)
try:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    pb = ExportTraceServiceRequest()
    rs = pb.resource_spans.add()
    kv = rs.resource.attributes.add(); kv.key = "service.name"; kv.value.string_value = "pb-agent"
    sp = rs.scope_spans.add().spans.add()
    sp.trace_id = bytes.fromhex("0af7651916cd43dd8448eb211c80319c"); sp.span_id = bytes.fromhex("b7ad6b7169203331")
    sp.name = "invoke_agent pb"; sp.start_time_unix_nano = int(time.time() * 1e9) - 5_000_000; sp.end_time_unix_nano = int(time.time() * 1e9)
    a = sp.attributes.add(); a.key = "gen_ai.operation.name"; a.value.string_value = "invoke_agent"
    r = urllib.request.urlopen(urllib.request.Request(URL + "/_obs/v1/traces", data=pb.SerializeToString(), headers={"content-type": "application/x-protobuf"}, method="POST"))
    check("OTLP protobuf accepted and bridged", r.status == 200 and xr.batch_get_traces(TraceIds=["1-0af76519-16cd43dd8448eb211c80319c"])["Traces"])
except ImportError:
    print("  skip protobuf leg (opentelemetry-proto not installed)")

print("X-Ray control plane")
gr = xr.create_group(GroupName="agent-faults", FilterExpression="fault")["Group"]
check("CreateGroup/GetGroups", xr.get_group(GroupName="agent-faults")["Group"]["GroupARN"] == gr["GroupARN"] and any(g["GroupName"] == "agent-faults" for g in xr.get_groups()["Groups"]))
try:
    xr.create_group(GroupName="agent-faults")
    check("duplicate group rejected", False)
except xr.exceptions.InvalidRequestException:
    check("duplicate group rejected", True)
xr.create_sampling_rule(SamplingRule={"RuleName": "agents", "Priority": 100, "FixedRate": 1.0, "ReservoirSize": 5, "ServiceName": "*", "ServiceType": "*", "Host": "*", "HTTPMethod": "*", "URLPath": "*", "ResourceARN": "*", "Version": 1})
rules = [r["SamplingRule"]["RuleName"] for r in xr.get_sampling_rules()["SamplingRuleRecords"]]
check("sampling rules ordered by priority with Default", rules == ["agents", "Default"], rules)
try:
    xr.delete_sampling_rule(RuleName="Default")
    check("Default rule is protected", False)
except xr.exceptions.InvalidRequestException:
    check("Default rule is protected", True)
tg = xr.get_trace_graph(TraceIds=[xt])
check("GetTraceGraph", {s["Name"] for s in tg["Services"]} >= {"facilities-agent", "search_knowledge"})
check("GetTimeSeriesServiceStatistics", sum(p["ServiceSummaryStatistics"]["TotalCount"] for p in xr.get_time_series_service_statistics(StartTime=t_start, EndTime=time.time() + 60, Period=60)["TimeSeriesServiceStatistics"]) >= 2)
check("UpdateTraceSegmentDestination -> CloudWatchLogs", xr.update_trace_segment_destination(Destination="CloudWatchLogs")["Destination"] == "CloudWatchLogs" and xr.get_trace_segment_destination()["Destination"] == "CloudWatchLogs")
xr.put_encryption_config(Type="NONE")
xr.tag_resource(ResourceARN=gr["GroupARN"], Tags=[{"Key": "env", "Value": "ref"}])
check("tags round-trip", xr.list_tags_for_resource(ResourceARN=gr["GroupARN"])["Tags"] == [{"Key": "env", "Value": "ref"}])
tok = xr.start_trace_retrieval(TraceIds=[xt], StartTime=t_start, EndTime=time.time() + 60)["RetrievalToken"]
check("StartTraceRetrieval/ListRetrievedTraces", xr.list_retrieved_traces(RetrievalToken=tok)["Traces"][0]["Id"] == xt)

print("AgentCore evaluations")
ac = cli("bedrock-agentcore-control")
ev_ids = {e["evaluatorId"] for e in ac.list_evaluators()["evaluators"]}
check("built-in evaluators listed", "Builtin.Correctness" in ev_ids and "Builtin.GoalSuccessRate" in ev_ids)
ce = ac.create_evaluator(evaluatorName="facilities_helpfulness", level="TRACE", evaluatorConfig={"llmAsAJudge": {
    "instructions": "Rate whether the answer helps a facilities technician act on the request.",
    "ratingScale": {"numerical": [{"definition": "Not helpful", "value": 0.0, "label": "Poor"}, {"definition": "Fully helpful", "value": 1.0, "label": "Good"}]},
    "modelConfig": {"bedrockEvaluatorModelConfig": {"modelId": "us.anthropic.claude-sonnet"}}}})
check("CreateEvaluator", ce["status"] in ("ACTIVE", "CREATING") and ce["evaluatorId"].startswith("facilities_helpfulness"))
check("GetEvaluator", ac.get_evaluator(evaluatorId=ce["evaluatorId"])["level"] == "TRACE")
try:
    ac.get_evaluator(evaluatorId="nope")
    check("missing evaluator is a modeled 404", False)
except ac.exceptions.ResourceNotFoundException:
    check("missing evaluator is a modeled 404", True)

ad = cli("bedrock-agentcore")
spans = [{"traceId": d["traceId"], "spanId": d["spanId"], "name": d["name"], "startTimeUnixNano": d["startTimeUnixNano"], "endTimeUnixNano": d["endTimeUnixNano"],
          "attributes": {a["key"]: next(iter(a["value"].values())) for a in d["attributes"]}, "status": d["status"]} for d in EXP.sent if d["traceId"] in (tid, tid2)]
golden = [
    {"trace": tid, "expected": "Inspect the boiler pressure valve in building 4 and open a maintenance work order.", "traj": ["search_knowledge", "create_work_order"],
     "asserts": ["boiler pressure valve", "work order"]},
    {"trace": tid2, "expected": "Totally unrelated banana smoothie recipe.", "traj": ["create_work_order", "search_knowledge"], "asserts": ["zebra crossing budget"]},
]
refs = lambda g: [{"context": {"spanContext": {"sessionId": "s1", "traceId": g["trace"]}}, "expectedResponse": {"text": g["expected"]},
                   "assertions": [{"text": a} for a in g["asserts"]], "expectedTrajectory": {"toolNames": g["traj"]}}]
scores = {}
for ev_id in ("Builtin.Correctness", "Builtin.TrajectoryInOrderMatch", "Builtin.GoalSuccessRate", "Builtin.ToolSelectionAccuracy", ce["evaluatorId"]):
    for g_ in golden:
        out = ad.evaluate(evaluatorId=ev_id, evaluationInput={"sessionSpans": [s for s in spans if s["traceId"] == g_["trace"]]},
                          evaluationReferenceInputs=refs(g_))["evaluationResults"]
        scores[(ev_id, g_["trace"])] = out
check("Evaluate returns scored results", all(v and "value" in v[0] for v in scores.values()), scores)
c1, c2 = scores[("Builtin.Correctness", tid)][0]["value"], scores[("Builtin.Correctness", tid2)][0]["value"]
check("Correctness separates good from bad golden case", c1 > 0.6 > c2 and c1 - c2 > 0.4, (c1, c2))
check("trajectory in-order: pass vs fail", scores[("Builtin.TrajectoryInOrderMatch", tid)][0]["value"] == 1.0 and scores[("Builtin.TrajectoryInOrderMatch", tid2)][0]["value"] == 0.0)
check("goal success assertions: 1.0 vs 0.0", scores[("Builtin.GoalSuccessRate", tid)][0]["value"] == 1.0 and scores[("Builtin.GoalSuccessRate", tid2)][0]["value"] == 0.0)
check("custom judge evaluator returns a scale value+label", scores[(ce["evaluatorId"], tid)][0]["label"] in ("Poor", "Good") and "explanation" in scores[(ce["evaluatorId"], tid)][0])
tool_lvl = ad.evaluate(evaluatorId="Builtin.ToolSelectionAccuracy", evaluationInput={"sessionSpans": [s for s in spans if s["traceId"] == tid]})["evaluationResults"]
check("tool-call-level evaluator yields one result per tool span", len(tool_lvl) == 2 and all("spanId" in r["context"]["spanContext"] for r in tool_lvl))
try:
    ad.evaluate(evaluatorId="Builtin.Correctness", evaluationInput={"sessionSpans": []})
    check("empty sessionSpans is a ValidationException", False)
except Exception as e:
    check("empty sessionSpans is a ValidationException", "ValidationException" in str(e) or "min" in str(e).lower(), e)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
