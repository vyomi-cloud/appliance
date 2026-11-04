"""Unit tests for core/stepfunctions_core.py (run: python3 tests/conformance/test_stepfunctions_core.py)."""
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import stepfunctions_core as sf  # noqa: E402
from core import lambda_core  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def call(st, op, **body):
    r = sf.dispatch(st, "AWSStepFunctions." + op, body)
    return r.status, r.body


ROLE = "arn:aws:iam::000000000000:role/sfn"
DEF = {"StartAt": "Hello", "States": {
    "Hello": {"Type": "Pass", "Result": {"greeting": "hi"}, "ResultPath": "$.out", "Next": "Check"},
    "Check": {"Type": "Choice", "Choices": [{"Variable": "$.n", "NumericGreaterThan": 5, "Next": "Big"}], "Default": "Small"},
    "Big": {"Type": "Succeed"},
    "Small": {"Type": "Fail", "Error": "TooSmall", "Cause": "n<=5"}}}


def main():
    st = sf.StepFunctionsStore()
    s, b = call(st, "CreateStateMachine", name="m1", definition=json.dumps(DEF), roleArn=ROLE)
    check("CreateStateMachine", s == 200 and b["stateMachineArn"].endswith(":stateMachine:m1"), b)
    arn = b["stateMachineArn"]
    s, b = call(st, "CreateStateMachine", name="m1", definition="{}", roleArn=ROLE)
    check("duplicate/invalid definition rejected", s == 400 and b["__type"] == "InvalidDefinition", b)
    s, b = call(st, "CreateStateMachine", name="m1", definition=json.dumps({**DEF, "Comment": "x"}), roleArn=ROLE)
    check("StateMachineAlreadyExists", b.get("__type") == "StateMachineAlreadyExists", b)
    s, b = call(st, "DescribeStateMachine", stateMachineArn=arn)
    check("DescribeStateMachine", b["status"] == "ACTIVE" and b["type"] == "STANDARD", b)
    s, b = call(st, "StartExecution", stateMachineArn=arn, name="e1", input='{"n": 9}')
    ex = b["executionArn"]
    s, b = call(st, "DescribeExecution", executionArn=ex)
    check("execution SUCCEEDED via Choice", b["status"] == "SUCCEEDED" and json.loads(b["output"])["out"]["greeting"] == "hi", b)
    s, b = call(st, "StartExecution", stateMachineArn=arn, name="e2", input='{"n": 1}')
    s, b = call(st, "DescribeExecution", executionArn=b["executionArn"])
    check("Fail state -> FAILED with error/cause", b["status"] == "FAILED" and b["error"] == "TooSmall" and b["cause"] == "n<=5", b)
    s, b = call(st, "GetExecutionHistory", executionArn=ex)
    types_ = [e["type"] for e in b["events"]]
    check("history has Started/StateEntered/Succeeded", types_[0] == "ExecutionStarted" and types_[-1] == "ExecutionSucceeded"
          and "ChoiceStateEntered" in types_, types_)
    s, b = call(st, "ListExecutions", stateMachineArn=arn, statusFilter="FAILED")
    check("ListExecutions statusFilter", len(b["executions"]) == 1)
    s, b = call(st, "StartExecution", stateMachineArn=arn, name="e1", input='{"n": 2}')
    check("ExecutionAlreadyExists", b.get("__type") == "ExecutionAlreadyExists", b)

    # Lambda task, Parameters, Retry/Catch, Map, Parallel, intrinsics
    lam = types.SimpleNamespace()
    lambda_core.dispatch(lam, "POST", "/2015-03-31/functions", {}, {}, json.dumps({
        "FunctionName": "dbl", "Runtime": "python3.12", "Role": ROLE, "Handler": "index.handler",
        "Code": {"Source": "def handler(e, c):\n    return {'v': e['v'] * 2}\n"}}).encode())
    lambda_core.dispatch(lam, "POST", "/2015-03-31/functions", {}, {}, json.dumps({
        "FunctionName": "boom", "Runtime": "python3.12", "Role": ROLE, "Handler": "index.handler",
        "Code": {"Source": "def handler(e, c):\n    raise ValueError('bad')\n"}}).encode())
    sf.set_lambda_store(lam)
    d2 = {"StartAt": "M", "States": {
        "M": {"Type": "Map", "ItemsPath": "$.items", "ItemProcessor": {"StartAt": "D", "States": {
            "D": {"Type": "Task", "Resource": "arn:aws:lambda:us-east-1:000000000000:function:dbl", "End": True}}},
            "ResultPath": "$.doubled", "Next": "P"},
        "P": {"Type": "Parallel", "Branches": [
            {"StartAt": "A", "States": {"A": {"Type": "Pass", "Result": 1, "End": True}}},
            {"StartAt": "B", "States": {"B": {"Type": "Pass", "Parameters": {"n.$": "States.ArrayLength($.items)"}, "End": True}}}],
            "ResultPath": "$.par", "Next": "T"},
        "T": {"Type": "Task", "Resource": "arn:aws:states:::lambda:invoke", "Parameters": {"FunctionName": "boom", "Payload.$": "$"},
              "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.err", "Next": "Done"}], "End": True},
        "Done": {"Type": "Pass", "End": True}}}
    s, b = call(st, "CreateStateMachine", name="m2", definition=json.dumps(d2), roleArn=ROLE, type="EXPRESS")
    s, b = call(st, "StartSyncExecution", stateMachineArn=b["stateMachineArn"], input=json.dumps({"items": [{"v": 1}, {"v": 2}]}))
    out = json.loads(b.get("output", "{}"))
    check("Map+Lambda, Parallel, intrinsic, Catch", b["status"] == "SUCCEEDED" and out["doubled"] == [{"v": 2}, {"v": 4}]
          and out["par"] == [1, {"n": 2}] and out["err"]["Error"] == "ValueError", b)

    # activity / callback
    s, b = call(st, "CreateActivity", name="act")
    act = b["activityArn"]
    d3 = {"StartAt": "W", "States": {"W": {"Type": "Task", "Resource": act, "End": True}}}
    s, b = call(st, "CreateStateMachine", name="m3", definition=json.dumps(d3), roleArn=ROLE)
    s, b = call(st, "StartExecution", stateMachineArn=b["stateMachineArn"], name="w1", input='{"a":1}')
    e3 = b["executionArn"]
    check("activity task leaves execution RUNNING", call(st, "DescribeExecution", executionArn=e3)[1]["status"] == "RUNNING")
    s, b = call(st, "GetActivityTask", activityArn=act)
    check("GetActivityTask returns token+input", json.loads(b["input"]) == {"a": 1} and b["taskToken"], b)
    call(st, "SendTaskSuccess", taskToken=b["taskToken"], output='{"done":true}')
    s, b = call(st, "DescribeExecution", executionArn=e3)
    check("SendTaskSuccess completes the execution", b["status"] == "SUCCEEDED" and json.loads(b["output"]) == {"done": True}, b)
    s, b = call(st, "StartExecution", stateMachineArn=arn.replace("m1", "m3"), name="w2")
    s, b2 = call(st, "StopExecution", executionArn=b["executionArn"], error="X", cause="y")
    check("StopExecution -> ABORTED", call(st, "DescribeExecution", executionArn=b["executionArn"])[1]["status"] == "ABORTED")

    # versions / aliases / tags / validate / test state
    s, b = call(st, "PublishStateMachineVersion", stateMachineArn=arn)
    ver = b["stateMachineVersionArn"]
    s, b = call(st, "CreateStateMachineAlias", name="prod", routingConfiguration=[{"stateMachineVersionArn": ver, "weight": 100}])
    check("alias created", s == 200 and b["stateMachineAliasArn"].endswith(":m1:prod"), b)
    check("StartExecution through alias", call(st, "StartExecution", stateMachineArn=b["stateMachineAliasArn"], input='{"n":9}')[0] == 200)
    call(st, "TagResource", resourceArn=arn, tags=[{"key": "env", "value": "dev"}])
    check("tags round trip", call(st, "ListTagsForResource", resourceArn=arn)[1]["tags"] == [{"key": "env", "value": "dev"}])
    check("Validate FAIL on bad def", call(st, "ValidateStateMachineDefinition", definition='{"StartAt":"x","States":{}}')[1]["result"] == "FAIL")
    check("Validate OK", call(st, "ValidateStateMachineDefinition", definition=json.dumps(DEF))[1]["result"] == "OK")
    s, b = call(st, "TestState", definition=json.dumps({"Type": "Pass", "Result": {"x": 1}, "End": True}), roleArn=ROLE, input="{}")
    check("TestState Pass", b["status"] == "SUCCEEDED" and json.loads(b["output"]) == {"x": 1}, b)
    check("DeleteStateMachine", call(st, "DeleteStateMachine", stateMachineArn=arn)[0] == 200
          and call(st, "DescribeStateMachine", stateMachineArn=arn)[1]["__type"] == "StateMachineDoesNotExist")
    # loggingConfiguration is ENFORCED: executions write history events to the CloudWatch Logs group
    from core import logs_core
    lg = logs_core.LogsStore()
    st2 = sf.StepFunctionsStore()
    st2.logs_store = lg
    G = "arn:aws:logs:us-east-1:000000000000:log-group:/aws/vendedlogs/states/m2:*"

    def run_with(level, data, name):
        cfg = {"level": level, "includeExecutionData": data, "destinations": [{"cloudWatchLogsLogGroup": {"logGroupArn": G}}]}
        call(st2, "CreateStateMachine", name=name, definition=json.dumps(DEF), roleArn=ROLE, loggingConfiguration=cfg)
        call(st2, "StartExecution", stateMachineArn=sf._sm_arn(name), input='{"n":1,"secret":"s3"}')

    def msgs():
        g = lg.log_groups.get("/aws/vendedlogs/states/m2")
        return [json.loads(e["message"]) for st_ in (g["streams"].values() if g else []) for e in st_["events"]]
    run_with("OFF", False, "m2")
    check("level OFF writes no logs", msgs() == [])
    call(st2, "DeleteStateMachine", stateMachineArn=sf._sm_arn("m2"))
    run_with("ALL", False, "m2")
    m = msgs()
    types_ = {x["type"] for x in m}
    check("level ALL logs every history event", {"ExecutionStarted", "ExecutionFailed"} <= types_ and len(m) > 2, types_)
    check("includeExecutionData=false strips payloads", "s3" not in json.dumps(m) and all(x["execution_arn"] for x in m))
    call(st2, "DeleteStateMachine", stateMachineArn=sf._sm_arn("m2"))
    lg.log_groups.clear()
    run_with("ERROR", True, "m2")
    m = msgs()
    check("level ERROR logs only failure events", m and all(x["type"].endswith("Failed") for x in m), [x["type"] for x in m])
    check("includeExecutionData=true keeps the cause", "n<=5" in json.dumps(m))
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
