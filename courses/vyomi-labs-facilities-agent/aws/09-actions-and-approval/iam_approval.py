import json
import time

import boto3
from botocore.exceptions import ClientError

import iamkit
from iamkit import allow

sns, sqs, sf = boto3.client("sns"), boto3.client("sqs"), boto3.client("stepfunctions")
topic = sns.create_topic(Name="gate-topic")["TopicArn"]
qurl = sqs.create_queue(QueueName="gate-inbox")["QueueUrl"]
qarn = sqs.get_queue_attributes(QueueUrl=qurl, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=qarn)
ASL = {"StartAt": "Ask", "States": {
    "Ask": {"Type": "Task", "Resource": "arn:aws:states:::sns:publish.waitForTaskToken", "TimeoutSeconds": 120,
            "Parameters": {"TopicArn": topic, "Message": {"request_id.$": "$.request_id", "token.$": "$$.Task.Token"}},
            "Catch": [{"ErrorEquals": ["States.Timeout"], "Next": "Expired"}, {"ErrorEquals": ["States.ALL"], "Next": "Rejected"}], "Next": "Approved"},
    "Approved": {"Type": "Succeed"}, "Expired": {"Type": "Fail", "Error": "ApprovalExpired"}, "Rejected": {"Type": "Fail", "Error": "ApprovalRejected"}}}
sm = sf.create_state_machine(name="approval-gate", definition=json.dumps(ASL), roleArn="arn:aws:iam::123456789012:role/facilities-role")["stateMachineArn"]

iamkit.enforce("enforce")
agent = iamkit.principal("facilities-agent", [allow("states:StartExecution", sm), allow(["states:DescribeExecution"], "*")])
manager = iamkit.principal("duty-manager", [allow(["states:SendTaskSuccess", "states:SendTaskFailure"], "*"), allow(["sqs:ReceiveMessage", "sqs:DeleteMessage"], qarn)])

# The agent asks for approval.
ex = iamkit.client("stepfunctions", agent).start_execution(stateMachineArn=sm, name="gate-1", input=json.dumps({"request_id": "gate-1"}))["executionArn"]
msg = None
for _ in range(20):
    got = iamkit.client("sqs", manager).receive_message(QueueUrl=qurl, WaitTimeSeconds=1).get("Messages")
    if got:
        msg = json.loads(json.loads(got[0]["Body"])["Message"])
        break
assert msg and msg["request_id"] == "gate-1", "the approver must find the request in the inbox"

# 1. The agent cannot approve its own request.
since = iamkit.last_audit_id()
try:
    iamkit.client("stepfunctions", agent).send_task_success(taskToken=msg["token"], output="{}")
    raise AssertionError("self-approval must be refused")
except ClientError as e:
    assert e.response["Error"]["Code"] in ("AccessDenied", "AccessDeniedException"), e
print("agent tried to approve its own request: refused")
assert sf.describe_execution(executionArn=ex)["status"] == "RUNNING", "a refused approval must leave the request waiting"

# 2. The duty manager approves; the audit log names who.
iamkit.client("stepfunctions", manager).send_task_success(taskToken=msg["token"], output=json.dumps({"decision": "approved"}))
for _ in range(20):
    if sf.describe_execution(executionArn=ex)["status"] != "RUNNING":
        break
    time.sleep(0.25)
assert sf.describe_execution(executionArn=ex)["status"] == "SUCCEEDED"
decided = [r for r in iamkit.audit(manager, since) if r["action"] == "states:SendTaskSuccess"]
assert decided and decided[0]["decision"] == "allow", "the audit log must show who sent the approval"
refusals = [r for r in iamkit.audit(agent, since) if r["action"] == "states:SendTaskSuccess" and r["decision"] == "deny"]
assert refusals, "the audit log must also show the refused self-approval"
approver, requester = decided[0]["principal"], refusals[0]["principal"]
assert approver != requester, "separation of duties: approver and requester must differ"
print("approved by", approver, "| requested by", requester)
print("approver identity verified from the audit log")
