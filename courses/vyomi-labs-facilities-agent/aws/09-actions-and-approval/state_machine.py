import io
import json
import zipfile

import boto3

ROLE = "arn:aws:iam::123456789012:role/facilities-role"
EXPIRE_SOURCE = """
import os
import boto3


def handler(event, context):
    # A request nobody answered in time becomes EXPIRED. The condition means an already-decided request is never overwritten.
    ddb = boto3.client("dynamodb")
    try:
        ddb.update_item(TableName=os.environ["LEDGER_TABLE"], Key={"request_id": {"S": event["request_id"]}},
                        UpdateExpression="SET #s = :e", ConditionExpression="#s = :p", ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={":e": {"S": "EXPIRED"}, ":p": {"S": "PENDING"}})
        return {"expired": True}
    except ddb.exceptions.ConditionalCheckFailedException:
        return {"expired": False}
"""


def build_asl(timeout_seconds=4 * 3600):
    """The approval workflow. Low-risk (P4) requests are approved by policy; every other request needs a human, who has `timeout_seconds` to answer before the request EXPIRES instead of waiting forever."""
    return {"Comment": "Risk-based approval before any write", "StartAt": "RiskGate", "States": {
        # Risk levels: informational P4 requests on non-safety work are approved by policy; everything else waits for a human.
        "RiskGate": {"Type": "Choice", "Choices": [{"Variable": "$.priority", "StringEquals": "P4", "Next": "AutoApprove"}], "Default": "RequestApproval"},
        "AutoApprove": {"Type": "Pass", "Result": {"decision": "auto-approved", "policy": "P4-low-risk"}, "ResultPath": "$.approval", "Next": "CreateWorkOrder"},
        "RequestApproval": {"Type": "Task", "Resource": "arn:aws:states:::lambda:invoke.waitForTaskToken",
                            "Parameters": {"FunctionName": "facilities-request-approval",
                                           "Payload": {"TaskToken.$": "$$.Task.Token", "request_id.$": "$.request_id",
                                                       "summary.$": "$.summary", "requester.$": "$.requester"}},
                            "ResultPath": "$.approval", "TimeoutSeconds": timeout_seconds,
                            "Catch": [{"ErrorEquals": ["States.Timeout"], "ResultPath": "$.error", "Next": "ExpireRequest"},
                                      {"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "Rejected"}], "Next": "CreateWorkOrder"},
        "CreateWorkOrder": {"Type": "Task", "Resource": "arn:aws:states:::lambda:invoke",
                            "Parameters": {"FunctionName": "facilities-create-work-order", "Payload": {"request.$": "$"}},
                            "ResultSelector": {"work_order.$": "$.Payload"}, "ResultPath": "$.result", "End": True},
        "ExpireRequest": {"Type": "Task", "Resource": "arn:aws:states:::lambda:invoke",
                          "Parameters": {"FunctionName": "facilities-expire-request", "Payload": {"request_id.$": "$.request_id"}},
                          "ResultPath": "$.expiry", "Next": "Expired"},
        "Expired": {"Type": "Fail", "Error": "ApprovalExpired", "Cause": "Nobody answered before the deadline"},
        "Rejected": {"Type": "Fail", "Error": "ApprovalRejected", "Cause": "Approver rejected the request"}}}


def deploy_expire_function():
    lam = boto3.client("lambda")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("expire_request.py", EXPIRE_SOURCE)
    env = lam.get_function_configuration(FunctionName="facilities-request-approval")["Environment"]["Variables"]
    try:
        lam.create_function(FunctionName="facilities-expire-request", Runtime="python3.12", Role=ROLE, Handler="expire_request.handler",
                            Code={"ZipFile": buf.getvalue()}, Timeout=30, Environment={"Variables": env})
    except lam.exceptions.ResourceConflictException:
        pass


if __name__ == "__main__":
    deploy_expire_function()
    sf = boto3.client("stepfunctions")
    arn = sf.create_state_machine(name="work-order-approval", definition=json.dumps(build_asl()), roleArn=ROLE, type="STANDARD")["stateMachineArn"]
    print("state machine", arn)
