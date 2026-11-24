import os
import boto3


def handler(event, context):
    ddb = boto3.client("dynamodb")
    asset = ddb.get_item(TableName=os.environ["ASSETS_TABLE"], Key={"asset_id": {"S": event["asset_id"]}}).get("Item")
    if not asset:
        return {"found": False}
    wos = ddb.scan(TableName=os.environ["WORK_ORDERS_TABLE"], FilterExpression="asset_id = :a",
                   ExpressionAttributeValues={":a": {"S": event["asset_id"]}}).get("Items", [])
    return {"found": True, "asset": {k: list(v.values())[0] for k, v in asset.items()},
            "work_orders": [{k: list(v.values())[0] for k, v in w.items()} for w in wos]}
