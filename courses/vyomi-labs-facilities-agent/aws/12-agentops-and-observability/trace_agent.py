import json
import time
import uuid

import boto3

from ask_agent import ask

xr, cw, lg = boto3.client("xray"), boto3.client("cloudwatch"), boto3.client("logs")
res = ask("facilities-session-" + "f" * 20)
spans = res["spans"]
trace_id = "1-%08x-%s" % (int(spans[0]["start"]), uuid.uuid4().hex[:24])

root = uuid.uuid4().hex[:16]
docs = [json.dumps({"trace_id": trace_id, "id": root, "name": "facilities-supervisor", "start_time": spans[0]["start"],
                    "end_time": spans[-1]["end"], "annotations": {"user": "maria.ops@example.com"}})]
for s in spans:
    docs.append(json.dumps({"trace_id": trace_id, "id": uuid.uuid4().hex[:16], "parent_id": root, "name": s["name"], "start_time": s["start"],
                            "end_time": s["end"], "type": "subsegment", "annotations": {"kind": s["kind"]}}))
xr.put_trace_segments(TraceSegmentDocuments=docs)
print("sent", len(docs), "segments")

trace = xr.batch_get_traces(TraceIds=[trace_id])["Traces"][0]
names = {json.loads(sg["Document"]).get("name") for sg in trace["Segments"]}
print("read trace back with", len(trace["Segments"]), "segments; sub-agent spans:", sorted(n for n in names if n.startswith("agent:")))
listed = xr.get_trace_summaries(StartTime=time.time() - 3600, EndTime=time.time() + 60)["TraceSummaries"]
print("trace listed by GetTraceSummaries:", any(t["Id"] == trace_id for t in listed))

cw.put_metric_data(Namespace="FacilitiesAgent", MetricData=[
    {"MetricName": "ToolCalls", "Value": len(res["tools"]), "Unit": "Count"},
    {"MetricName": "AgentLatencyMs", "Value": (spans[-1]["end"] - spans[0]["start"]) * 1000, "Unit": "Milliseconds"}])
print("metrics:", sorted(m["MetricName"] for m in cw.list_metrics(Namespace="FacilitiesAgent")["Metrics"]))

group = "/aws/agentcore/runtimes/facilities-supervisor"
try:
    lg.create_log_group(logGroupName=group)
except lg.exceptions.ResourceAlreadyExistsException:
    pass
lg.create_log_stream(logGroupName=group, logStreamName="s1")
lg.put_log_events(logGroupName=group, logStreamName="s1", logEvents=[{"timestamp": int(time.time() * 1000), "message": json.dumps(
    {"trace_id": trace_id, "route": res["route"], "tools": [t["tool"] for t in res["tools"]]})}])
line = lg.get_log_events(logGroupName=group, logStreamName="s1")["events"][0]["message"]
print("structured log carries the trace id:", trace_id in line)
