import json

import boto3

ASL = {"Comment": "Human approval before any write", "StartAt": "RequestApproval", "States": {
    "RequestApproval": {"Type": "Task", "Resource": "arn:aws:states:::lambda:invoke.waitForTaskToken",
                        "Parameters": {"FunctionName": "facilities-request-approval",
                                       "Payload": {"TaskToken.$": "$$.Task.Token", "request_id.$": "$.request_id",
                                                   "summary.$": "$.summary", "requester.$": "$.requester"}},
                        "ResultPath": "$.approval", "TimeoutSeconds": 86400,
                        "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "Rejected"}], "Next": "CreateWorkOrder"},
    "CreateWorkOrder": {"Type": "Task", "Resource": "arn:aws:states:::lambda:invoke",
                        "Parameters": {"FunctionName": "facilities-create-work-order", "Payload": {"request.$": "$"}},
                        "ResultSelector": {"work_order.$": "$.Payload"}, "ResultPath": "$.result", "End": True},
    "Rejected": {"Type": "Fail", "Error": "ApprovalRejected", "Cause": "Approver rejected the request"}}}

sf = boto3.client("stepfunctions")
arn = sf.create_state_machine(name="work-order-approval", definition=json.dumps(ASL),
                              roleArn="arn:aws:iam::123456789012:role/facilities-role", type="STANDARD")["stateMachineArn"]
print("state machine", arn)
