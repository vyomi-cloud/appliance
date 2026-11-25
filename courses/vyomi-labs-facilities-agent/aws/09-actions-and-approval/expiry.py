import json
import time

import boto3
from botocore.exceptions import ClientError

from state_machine import ROLE, build_asl

sf, ddb = boto3.client("stepfunctions"), boto3.client("dynamodb")
arn = sf.create_state_machine(name="work-order-approval-2s", definition=json.dumps(build_asl(2)), roleArn=ROLE, type="STANDARD")["stateMachineArn"]
rid = "req-expire01"
ex = sf.start_execution(stateMachineArn=arn, name=rid, input=json.dumps(
    {"request_id": rid, "asset_id": "EL-3", "summary": "Replace the elevator 3 door sensor", "priority": "P3", "requester": "expiry-test"}))["executionArn"]

row = None
for _ in range(40):
    row = ddb.get_item(TableName="approval-ledger", Key={"request_id": {"S": rid}}).get("Item")
    if row:
        break
    time.sleep(0.25)
assert row and row["status"]["S"] == "PENDING" and int(row["expires_at"]["N"]) > int(row["ts"]["N"]), "the ledger must hold a PENDING row with a deadline"
token = row["task_token"]["S"]
print("pending with a deadline: expires_at - ts =", int(row["expires_at"]["N"]) - int(row["ts"]["N"]), "seconds (the lambda default; this run uses 2s in the workflow)")

time.sleep(3)                                             # nobody answers
for _ in range(40):
    d = sf.describe_execution(executionArn=ex)
    if d["status"] != "RUNNING":
        break
    time.sleep(0.5)
assert d["status"] == "FAILED" and d.get("error") == "ApprovalExpired", "execution must end as ApprovalExpired, got %s/%s" % (d["status"], d.get("error"))
status = ddb.get_item(TableName="approval-ledger", Key={"request_id": {"S": rid}})["Item"]["status"]["S"]
assert status == "EXPIRED", "ledger must say EXPIRED, got " + status
print("nobody answered: execution", d["status"], "/", d["error"], "| ledger", status)

try:
    sf.send_task_success(taskToken=token, output=json.dumps({"decision": "approved"}))
    raise AssertionError("a late approval must be refused")
except ClientError as e:
    print("late approval refused:", e.response["Error"]["Code"])
mine = [i for i in ddb.scan(TableName="facilities-work-orders")["Items"] if i["requester"]["S"] == "expiry-test"]
assert not mine, "an expired request must never create a work order"
print("expiry verified: no work order, request closed")
