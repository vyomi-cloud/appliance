import json
import time

import boto3

sf, ddb = boto3.client("stepfunctions"), boto3.client("dynamodb")
sm = next(s for s in sf.list_state_machines()["stateMachines"] if s["name"] == "work-order-approval")["stateMachineArn"]
rid = "req-reject01"
ex = sf.start_execution(stateMachineArn=sm, name=rid, input=json.dumps(
    {"request_id": rid, "asset_id": "EL-3", "summary": "Replace elevator 3 (should be rejected)", "priority": "P3", "requester": "test"}))["executionArn"]
row = None
for _ in range(20):
    row = ddb.get_item(TableName="approval-ledger", Key={"request_id": {"S": rid}}).get("Item")
    if row:
        break
    time.sleep(0.3)
sf.send_task_failure(taskToken=row["task_token"]["S"], error="Rejected", cause="Not approved by the duty manager")
for _ in range(40):
    d = sf.describe_execution(executionArn=ex)
    if d["status"] != "RUNNING":
        break
    time.sleep(0.5)
print("execution", d["status"])
wos = [i for i in ddb.scan(TableName="facilities-work-orders")["Items"] if i["asset_id"]["S"] == "EL-3" and i["requester"]["S"] == "test"]
print("work orders written despite rejection:", len(wos))
