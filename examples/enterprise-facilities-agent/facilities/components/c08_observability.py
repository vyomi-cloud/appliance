"""C8: AgentOps: spans from the agent run -> X-Ray trace, CloudWatch metrics and logs, then read them back."""
import json, time, uuid
from ..runtime import Blocked


def _trace_id(t):
    return "1-%08x-%s" % (int(t), uuid.uuid4().hex[:24])


def run(ctx):
    res = ctx.state.get("result", {})
    spans = res.get("spans", [])
    xr, cw, lg = ctx.client("xray"), ctx.client("cloudwatch"), ctx.client("logs")
    tid = _trace_id(spans[0]["start"] if spans else time.time())
    ctx.state["trace_id"] = tid

    def push():
        docs = []
        root = uuid.uuid4().hex[:16]
        docs.append(json.dumps({"trace_id": tid, "id": root, "name": "facilities-supervisor", "start_time": spans[0]["start"], "end_time": spans[-1]["end"],
                                "annotations": {"user": ctx.state.get("user", "anon")}}))
        for s in spans:
            docs.append(json.dumps({"trace_id": tid, "id": uuid.uuid4().hex[:16], "parent_id": root, "name": s["name"], "start_time": s["start"], "end_time": s["end"],
                                    "type": "subsegment", "annotations": {"kind": s["kind"]}}))
        r = xr.put_trace_segments(TraceSegmentDocuments=docs)
        assert not r.get("UnprocessedTraceSegments"), r["UnprocessedTraceSegments"]
        return f"{len(docs)} segments sent"
    ctx.step("xray: PutTraceSegments (one segment per agent / tool span)", push)

    def read():
        t = xr.batch_get_traces(TraceIds=[tid])["Traces"]
        assert t and t[0]["Segments"], "trace not found"
        n = len(t[0]["Segments"])
        names = {json.loads(s["Document"]).get("name") for s in t[0]["Segments"]}
        assert "agent:facilities" in names or n > 1, names
        return f"trace {tid} read back with {n} segments"
    ctx.step("xray: BatchGetTraces reads the agent trace back", read, lane="observability")

    def summaries():
        s = xr.get_trace_summaries(StartTime=time.time() - 3600, EndTime=time.time() + 60)["TraceSummaries"]
        assert any(x["Id"] == tid for x in s), f"{len(s)} summaries, ours missing"
        return "trace listed in GetTraceSummaries"
    ctx.step("xray: GetTraceSummaries lists it", summaries, lane="observability")

    def metrics():
        cw.put_metric_data(Namespace="FacilitiesAgent", MetricData=[
            {"MetricName": "ToolCalls", "Value": len(res.get("tools", [])), "Unit": "Count"},
            {"MetricName": "AgentLatencyMs", "Value": (spans[-1]["end"] - spans[0]["start"]) * 1000 if spans else 0, "Unit": "Milliseconds"}])
        got = cw.list_metrics(Namespace="FacilitiesAgent")["Metrics"]
        assert {m["MetricName"] for m in got} >= {"ToolCalls", "AgentLatencyMs"}, got
        return "custom metrics published and listed"
    ctx.step("cloudwatch: PutMetricData + ListMetrics (agent KPIs)", metrics)

    def logs():
        g = "/aws/agentcore/runtimes/facilities-supervisor"
        try:
            lg.create_log_group(logGroupName=g)
        except lg.exceptions.ResourceAlreadyExistsException:
            pass
        lg.create_log_stream(logGroupName=g, logStreamName="s1")
        lg.put_log_events(logGroupName=g, logStreamName="s1", logEvents=[
            {"timestamp": int(time.time() * 1000), "message": json.dumps({"trace_id": tid, "route": res.get("route"), "tools": [t["tool"] for t in res.get("tools", [])]})}])
        ev = lg.get_log_events(logGroupName=g, logStreamName="s1")["events"]
        assert ev and tid in ev[0]["message"]
        return "structured agent log written and read back, carries the trace id"
    ctx.step("cloudwatch logs: PutLogEvents + GetLogEvents (structured, trace-correlated)", logs)

    def evals():
        ev = ctx.client("bedrock-agentcore-control").list_evaluators()
        assert ev.get("evaluators") is not None
        return f"{len(ev['evaluators'])} evaluators"
    ctx.step("agentcore-control: ListEvaluators (AgentCore evaluations)", evals, lane="observability")
