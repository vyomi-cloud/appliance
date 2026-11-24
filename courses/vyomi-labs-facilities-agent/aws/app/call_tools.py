import json
import boto3

lam = boto3.client("lambda")
r = lam.invoke(FunctionName="facilities-asset-status", Payload=json.dumps({"asset_id": "B-12"}).encode())
out = json.loads(r["Payload"].read())
print("found:", out["found"], "| status:", out["asset"]["status"], "| open work orders:", len([w for w in out["work_orders"] if w["status"] == "OPEN"]))
