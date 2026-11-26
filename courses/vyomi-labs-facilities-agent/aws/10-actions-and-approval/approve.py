import json
import time

import boto3

sf, ddb, sqs = boto3.client("stepfunctions"), boto3.client("dynamodb"), boto3.client("sqs")
qurl = sqs.get_queue_url(QueueName="approver-inbox-queue")["QueueUrl"]

msg = None
for _ in range(20):
    for m in sqs.receive_message(QueueUrl=qurl, MaxNumberOfMessages=10, WaitTimeSeconds=1).get("Messages", []):
        body = json.loads(m["Body"])
        cand = json.loads(body["Message"]) if "Message" in body else body
        if "B-12" in (cand.get("summary") or ""):
            msg = cand
    if msg:
        break
print("approval request in the inbox:", msg["request_id"], "-", msg["summary"][:60])

sm = next(s for s in sf.list_state_machines()["stateMachines"] if s["name"] == "work-order-approval")["stateMachineArn"]
ex = next(e for e in sf.list_executions(stateMachineArn=sm)["executions"] if e["name"] == msg["request_id"])["executionArn"]
sf.send_task_success(taskToken=msg["task_token"], output=json.dumps({"decision": "approved"}))   # who approved is not typed into the output: the Enforce step records the real caller
for _ in range(40):
    d = sf.describe_execution(executionArn=ex)
    if d["status"] != "RUNNING":
        break
    time.sleep(0.5)
wo = json.loads(d["output"])["result"]["work_order"]["work_order_id"]
print("execution", d["status"], "->", wo)
print("ledger:", ddb.get_item(TableName="approval-ledger", Key={"request_id": {"S": msg["request_id"]}})["Item"]["status"]["S"])
print("work order:", ddb.get_item(TableName="facilities-work-orders", Key={"work_order_id": {"S": wo}})["Item"]["status"]["S"])
