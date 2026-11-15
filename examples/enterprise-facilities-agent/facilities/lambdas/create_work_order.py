"""Write tool (runs only after approval): create the work order and close the ledger entry."""
import os, time
import boto3


def handler(event, context):
    req = event["request"] if "request" in event else event
    ddb = boto3.client("dynamodb")
    wo_id = "WO-" + req["request_id"][-6:].upper()
    ddb.put_item(TableName=os.environ["WORK_ORDERS_TABLE"], Item={
        "work_order_id": {"S": wo_id}, "asset_id": {"S": req["asset_id"]}, "title": {"S": req["summary"]},
        "priority": {"S": req.get("priority", "P3")}, "status": {"S": "OPEN"}, "requester": {"S": req.get("requester", "")}})
    ddb.update_item(TableName=os.environ["LEDGER_TABLE"], Key={"request_id": {"S": req["request_id"]}},
                    UpdateExpression="SET #s = :s, work_order_id = :w", ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": {"S": "EXECUTED"}, ":w": {"S": wo_id}})
    return {"work_order_id": wo_id}
