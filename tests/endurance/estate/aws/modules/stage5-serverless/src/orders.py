import json, os


def handler(event, context):
    return {"statusCode": 200, "headers": {"content-type": "application/json"},
            "body": json.dumps({"service": "orders", "table": os.environ.get("TABLE_NAME"), "path": event.get("path")})}
