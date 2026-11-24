import json, os, time
import boto3


def handler(event, context):
    token = event["TaskToken"]
    req = {k: v for k, v in event.items() if k != "TaskToken"}
    boto3.client("dynamodb").put_item(TableName=os.environ["LEDGER_TABLE"], Item={
        "request_id": {"S": req["request_id"]}, "status": {"S": "PENDING"}, "task_token": {"S": token},
        "requester": {"S": req.get("requester", "")}, "summary": {"S": req.get("summary", "")}, "ts": {"N": str(int(time.time()))}})
    boto3.client("sns").publish(TopicArn=os.environ["INBOX_TOPIC_ARN"], Subject="Approval needed: " + req.get("summary", "")[:80],
                                Message=json.dumps({"request_id": req["request_id"], "summary": req.get("summary"), "task_token": token}))
    return {"queued": True}
