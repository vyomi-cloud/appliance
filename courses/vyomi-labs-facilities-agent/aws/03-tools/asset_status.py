import os
import re

import boto3

ASSET_ID = re.compile(r"^[A-Z]{1,4}-[0-9]{1,4}$")


def handler(event, context):
    # Never trust the caller: the agent's model produced this argument, so validate it like any untrusted input before it reaches a query.
    asset_id = event.get("asset_id") if isinstance(event, dict) else None
    if not isinstance(asset_id, str) or not ASSET_ID.match(asset_id):
        return {"error": "invalid_input", "detail": "asset_id must look like B-12"}
    ddb = boto3.client("dynamodb")
    asset = ddb.get_item(TableName=os.environ["ASSETS_TABLE"], Key={"asset_id": {"S": asset_id}}).get("Item")
    if not asset:
        return {"found": False}
    wos = ddb.scan(TableName=os.environ["WORK_ORDERS_TABLE"], FilterExpression="asset_id = :a",
                   ExpressionAttributeValues={":a": {"S": asset_id}}).get("Items", [])
    return {"found": True, "asset": {k: list(v.values())[0] for k, v in asset.items()},
            "work_orders": [{k: list(v.values())[0] for k, v in w.items()} for w in wos]}
