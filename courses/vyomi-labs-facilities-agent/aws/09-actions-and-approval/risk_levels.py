import json
import time

import boto3

sf, ddb = boto3.client("stepfunctions"), boto3.client("dynamodb")
sm = next(s for s in sf.list_state_machines()["stateMachines"] if s["name"] == "work-order-approval")["stateMachineArn"]


def start(rid, priority):
    return sf.start_execution(stateMachineArn=sm, name=rid, input=json.dumps(
        {"request_id": rid, "asset_id": "EL-3", "summary": "Risk level check " + priority, "priority": priority, "requester": "risk-test"}))["executionArn"]


def wait(ex, seconds=15):
    for _ in range(int(seconds / 0.5)):
        d = sf.describe_execution(executionArn=ex)
        if d["status"] != "RUNNING":
            return d
        time.sleep(0.5)
    return d


low = wait(start("req-risk-low1", "P4"))
assert low["status"] == "SUCCEEDED", "a P4 request must complete without a human, got " + low["status"]
out = json.loads(low["output"])
assert out["approval"]["decision"] == "auto-approved" and out["approval"]["policy"] == "P4-low-risk", out["approval"]
wo = out["result"]["work_order"]["work_order_id"]
assert ddb.get_item(TableName="facilities-work-orders", Key={"work_order_id": {"S": wo}}).get("Item"), "the auto-approved work order must exist"
print("P4: auto-approved by policy", out["approval"]["policy"], "->", wo)

high = start("req-risk-high1", "P2")
time.sleep(2)
assert sf.describe_execution(executionArn=high)["status"] == "RUNNING", "a P2 request must wait for a human"
mine = [i for i in ddb.scan(TableName="facilities-work-orders")["Items"] if i["requester"]["S"] == "risk-test" and i["priority"]["S"] == "P2"]
assert not mine, "a waiting P2 request must not have written anything"
print("P2: waiting for a human, nothing written")
print("risk levels verified")
