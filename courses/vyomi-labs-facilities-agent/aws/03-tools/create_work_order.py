import os
import re

import boto3

ASSET_ID = re.compile(r"^[A-Z]{1,4}-[0-9]{1,4}$")


def _invalid(req):
    if not isinstance(req.get("request_id"), str) or len(req["request_id"]) < 6:
        return "request_id is required"
    if not isinstance(req.get("asset_id"), str) or not ASSET_ID.match(req["asset_id"]):
        return "asset_id must look like B-12"
    if not isinstance(req.get("summary"), str) or not 3 <= len(req["summary"]) <= 200:
        return "summary must be 3 to 200 characters"
    if req.get("priority", "P3") not in ("P1", "P2", "P3", "P4"):
        return "priority must be P1 to P4"


def handler(event, context):
    req = event["request"] if "request" in event else event
    problem = _invalid(req)
    if problem:
        return {"error": "invalid_input", "detail": problem}
    ddb = boto3.client("dynamodb")
    wo_id = "WO-" + req["request_id"][-6:].upper()
    # Idempotency: the work-order id is derived from the request id, and the write is conditional. Approving twice, a retried
    # Lambda or a replayed event finds the row already there and returns it instead of creating a second work order.
    replayed = False
    try:
        ddb.put_item(TableName=os.environ["WORK_ORDERS_TABLE"], Item={
            "work_order_id": {"S": wo_id}, "asset_id": {"S": req["asset_id"]}, "title": {"S": req["summary"]},
            "priority": {"S": req.get("priority", "P3")}, "status": {"S": "OPEN"}, "requester": {"S": req.get("requester", "")}},
            ConditionExpression="attribute_not_exists(work_order_id)")
    except ddb.exceptions.ConditionalCheckFailedException:
        replayed = True
    ddb.update_item(TableName=os.environ["LEDGER_TABLE"], Key={"request_id": {"S": req["request_id"]}},
                    UpdateExpression="SET #s = :s, work_order_id = :w", ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": {"S": "EXECUTED"}, ":w": {"S": wo_id}})
    return {"work_order_id": wo_id, "replayed": replayed}
