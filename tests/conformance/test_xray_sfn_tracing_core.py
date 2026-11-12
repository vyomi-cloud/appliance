"""X-Ray core + Step Functions active tracing: tracing-enabled machines produce REAL traces readable through the X-Ray
API (BatchGetTraces / GetTraceSummaries / GetServiceGraph); PutTraceSegments stores app segments.

Run: PYTHONPATH=. ../s3_simulator/.venv/bin/python tests/conformance/test_xray_sfn_tracing_core.py
"""
import json
import time

from core import stepfunctions_core as sf, xray_core as xr

ROLE = "arn:aws:iam::000000000000:role/sfn"
OK = {"StartAt": "A", "States": {"A": {"Type": "Pass", "Next": "B"}, "B": {"Type": "Succeed"}}}
BAD = {"StartAt": "A", "States": {"A": {"Type": "Pass", "Next": "F"}, "F": {"Type": "Fail", "Error": "Boom", "Cause": "x"}}}


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def call(st, op, **b):
    r = sf.dispatch(st, "AWSStepFunctions." + op, b)
    return r.body


def x(st, path, **b):
    r = xr.dispatch(st, "POST", path, {}, {}, json.dumps(b).encode())
    return r["status"], json.loads(r["body"])


def main():
    st = sf.StepFunctionsStore()
    t0 = time.time() - 5
    traced = call(st, "CreateStateMachine", name="traced", definition=json.dumps(OK), roleArn=ROLE, tracingConfiguration={"enabled": True})["stateMachineArn"]
    plain = call(st, "CreateStateMachine", name="plain", definition=json.dumps(OK), roleArn=ROLE)["stateMachineArn"]
    bad = call(st, "CreateStateMachine", name="bad", definition=json.dumps(BAD), roleArn=ROLE, tracingConfiguration={"enabled": True})["stateMachineArn"]
    e1 = call(st, "StartExecution", stateMachineArn=traced, name="e1")["executionArn"]
    call(st, "StartExecution", stateMachineArn=plain, name="e2")
    call(st, "StartExecution", stateMachineArn=bad, name="e3")
    _check("only tracing-enabled machines produce traces", len(st.xray_traces) == 2, len(st.xray_traces))
    d = call(st, "DescribeExecution", executionArn=e1)
    tid = d["traceHeader"].split("Root=")[1].split(";")[0]
    _check("DescribeExecution exposes the trace header", tid in st.xray_traces)

    s, b = x(st, "/Traces", TraceIds=[tid, "1-00000000-000000000000000000000000"])
    _check("BatchGetTraces returns it, reports the unknown one", s == 200 and len(b["Traces"]) == 1 and b["UnprocessedTraceIds"] == ["1-00000000-000000000000000000000000"])
    doc = json.loads(b["Traces"][0]["Segments"][0]["Document"])
    _check("segment is the state machine with one subsegment per state", doc["name"] == "traced" and doc["origin"] == "AWS::StepFunctions::StateMachine"
           and [s["name"] for s in doc["subsegments"]] == ["A", "B"], doc)

    s, b = x(st, "/TraceSummaries", StartTime=t0, EndTime=time.time() + 5)
    _check("summaries list both traces", len(b["TraceSummaries"]) == 2)
    s, b = x(st, "/TraceSummaries", StartTime=t0, EndTime=time.time() + 5, FilterExpression="fault")
    _check("filter 'fault' finds only the failed execution", len(b["TraceSummaries"]) == 1 and b["TraceSummaries"][0]["HasFault"])
    s, b = x(st, "/TraceSummaries", StartTime=t0, EndTime=time.time() + 5, FilterExpression='service("traced")')
    _check("filter service(name)", len(b["TraceSummaries"]) == 1 and not b["TraceSummaries"][0]["HasFault"])
    s, b = x(st, "/ServiceGraph", StartTime=t0, EndTime=time.time() + 5)
    _check("service graph has both state machines", {n["Name"] for n in b["Services"]} == {"traced", "bad"})

    # caller-supplied trace header is honoured
    root = "1-65a1b2c3-0123456789abcdef01234567"
    e4 = call(st, "StartExecution", stateMachineArn=traced, name="e4", traceHeader=f"Root={root};Sampled=1")["executionArn"]
    _check("caller Root trace id is used", root in st.xray_traces and root in call(st, "DescribeExecution", executionArn=e4)["traceHeader"])

    # PutTraceSegments: an app's own segments
    tid2 = xr.new_trace_id()
    seg = {"trace_id": tid2, "id": "70de5b6f19ff9a0a", "name": "my-app", "start_time": time.time() - 1, "end_time": time.time()}
    s, b = x(st, "/TraceSegments", TraceSegmentDocuments=[json.dumps(seg), json.dumps({"id": "bad", "name": "n"})])
    _check("PutTraceSegments stores valid, reports invalid", s == 200 and len(b["UnprocessedTraceSegments"]) == 1 and tid2 in st.xray_traces)
    s, b = x(st, "/Traces", TraceIds=[tid2])
    _check("app trace readable", b["Traces"][0]["Segments"][0]["Id"] == "70de5b6f19ff9a0a")


if __name__ == "__main__":
    main()
    print("RESULT: PASS")
