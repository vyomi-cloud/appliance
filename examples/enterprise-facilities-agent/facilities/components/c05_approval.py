"""C5: write actions behind a human approval: Step Functions callback (waitForTaskToken via Lambda), SNS inbox, DynamoDB ledger."""
import json, time
from ..runtime import NAMES, Blocked, aws_json

ASL = {"Comment": "Human approval before any write", "StartAt": "RequestApproval", "States": {
    "RequestApproval": {"Type": "Task", "Resource": "arn:aws:states:::lambda:invoke.waitForTaskToken",
                        "Parameters": {"FunctionName": "facilities-request-approval", "Payload": {"TaskToken.$": "$$.Task.Token", "request_id.$": "$.request_id", "summary.$": "$.summary", "requester.$": "$.requester"}},
                        "ResultPath": "$.approval", "TimeoutSeconds": 86400, "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "Rejected"}], "Next": "CreateWorkOrder"},
    "CreateWorkOrder": {"Type": "Task", "Resource": "arn:aws:states:::lambda:invoke",
                        "Parameters": {"FunctionName": "facilities-create-work-order", "Payload": {"request.$": "$"}}, "ResultSelector": {"work_order.$": "$.Payload"}, "ResultPath": "$.result", "End": True},
    "Rejected": {"Type": "Fail", "Error": "ApprovalRejected", "Cause": "Approver rejected the request"}}}


def setup(ctx):
    sf = ctx.client("stepfunctions")

    def sm():
        try:
            arn = sf.create_state_machine(name=NAMES["sm"], definition=json.dumps(ASL), roleArn=NAMES["role"], type="STANDARD")["stateMachineArn"]
        except sf.exceptions.StateMachineAlreadyExists:
            arn = f"arn:aws:states:{ctx.region}:000000000000:stateMachine:{NAMES['sm']}"
        ctx.state["sm_arn"] = arn
        return arn
    ctx.step("stepfunctions: CreateStateMachine work-order-approval (waitForTaskToken)", sm)


def _inbox(ctx, request_id):
    sqs = ctx.client("sqs")
    for _ in range(20):
        for m in sqs.receive_message(QueueUrl=ctx.state["inbox_url"], MaxNumberOfMessages=10, WaitTimeSeconds=1).get("Messages", []):
            body = json.loads(m["Body"])
            msg = json.loads(body["Message"]) if "Message" in body else body
            if msg.get("request_id") == request_id:
                return msg
    return None


def _wait(ctx, arn, want):
    sf = ctx.client("stepfunctions")
    for _ in range(40):
        d = sf.describe_execution(executionArn=arn)
        if d["status"] != "RUNNING":
            return d
        time.sleep(0.5)
    return d


def run(ctx):
    sf = ctx.client("stepfunctions")
    res = ctx.state.get("result", {})
    ap = res.get("approval")
    if not ap:
        ctx.step("agent produced an approval request", lambda: (_ for _ in ()).throw(AssertionError("the agent run did not submit a work order request")))
        return

    def pending():
        d = sf.describe_execution(executionArn=ap["execution_arn"])
        assert d["status"] == "RUNNING", f"execution {d['status']}: {d.get('cause') or d.get('error')}"
        row = aws_json(ctx.client("dynamodb").get_item(TableName=NAMES["ledger"], Key={"request_id": {"S": ap["request_id"]}})["Item"])
        assert row["status"] == "PENDING"
        return f"execution RUNNING, ledger {row['status']}"
    ctx.step("agent write is parked: execution RUNNING + ledger PENDING (no work order yet)", pending)

    def no_wo_yet():
        items = ctx.client("dynamodb").scan(TableName=NAMES["work_orders"])["Items"]
        assert not [i for i in items if aws_json(i)["requester"] == ctx.state.get("user")], "work order exists before approval"
        return "no work order exists before approval"
    ctx.step("no write happens before approval", no_wo_yet)
    box = {}

    def inbox():
        m = _inbox(ctx, ap["request_id"])
        assert m and m.get("task_token"), "no approval message reached the approver inbox queue"
        box["msg"] = m
        return "approval message delivered to the approver inbox (SNS -> SQS)"
    ctx.step("sns -> sqs: approver inbox receives the approval request", inbox)
    msg = box.get("msg")
    if not msg:   # delivery failure is already reported above; read the token from the ledger so the approval path is still exercised
        row = aws_json(ctx.client("dynamodb").get_item(TableName=NAMES["ledger"], Key={"request_id": {"S": ap["request_id"]}})["Item"])
        msg = {"task_token": row["task_token"]}

    def approve():
        sf.send_task_success(taskToken=msg["task_token"], output=json.dumps({"approved_by": "duty.manager@example.com"}))
        d = _wait(ctx, ap["execution_arn"], "SUCCEEDED")
        assert d["status"] == "SUCCEEDED", f"{d['status']}: {d.get('cause') or d.get('error')}"
        out = json.loads(d["output"])
        wo = out["result"]["work_order"]["work_order_id"]
        ctx.state["work_order_id"] = wo
        row = aws_json(ctx.client("dynamodb").get_item(TableName=NAMES["ledger"], Key={"request_id": {"S": ap["request_id"]}})["Item"])
        assert row["status"] == "EXECUTED" and row["work_order_id"] == wo, row
        wrow = aws_json(ctx.client("dynamodb").get_item(TableName=NAMES["work_orders"], Key={"work_order_id": {"S": wo}})["Item"])
        assert wrow["asset_id"] == "B-12" and wrow["status"] == "OPEN"
        return f"SendTaskSuccess -> execution SUCCEEDED -> {wo} created, ledger EXECUTED"
    ctx.step("approver approves: SendTaskSuccess -> work order created", approve)

    def reject():
        rid = "req-reject01"
        ex = sf.start_execution(stateMachineArn=ctx.state["sm_arn"], name=rid, input=json.dumps(
            {"request_id": rid, "asset_id": "EL-3", "summary": "Replace elevator 3 (should be rejected)", "priority": "P3", "requester": "test"}))["executionArn"]
        for _ in range(20):
            row = ctx.client("dynamodb").get_item(TableName=NAMES["ledger"], Key={"request_id": {"S": rid}}).get("Item")
            if row:
                break
            time.sleep(0.3)
        tok = aws_json(row)["task_token"]
        sf.send_task_failure(taskToken=tok, error="Rejected", cause="Not approved by the duty manager")
        d = _wait(ctx, ex, "FAILED")
        assert d["status"] == "FAILED", d["status"]
        items = [aws_json(i) for i in ctx.client("dynamodb").scan(TableName=NAMES["work_orders"])["Items"]]
        assert not [i for i in items if i["asset_id"] == "EL-3" and i["requester"] == "test"], "work order created despite rejection"
        return "SendTaskFailure -> execution FAILED, no work order written"
    ctx.step("approver rejects: SendTaskFailure -> nothing is written", reject)
    ctx.step("stepfunctions: GetExecutionHistory shows the callback task", lambda: "events: " + ",".join(
        e["type"] for e in sf.get_execution_history(executionArn=ap["execution_arn"])["events"][:8]))
