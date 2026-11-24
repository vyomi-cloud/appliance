import time

import boto3

ct, ddb = boto3.client("cloudtrail"), boto3.client("dynamodb")
names = set()
for _ in range(10):
    ev = ct.lookup_events(LookupAttributes=[{"AttributeKey": "EventSource", "AttributeValue": "states.amazonaws.com"}], MaxResults=50)["Events"]
    names = {e["EventName"] for e in ev}
    if "StartExecution" in names:
        break
    time.sleep(0.5)
print("CloudTrail saw:", sorted(names))
rows = [{k: list(v.values())[0] for k, v in i.items()} for i in ddb.scan(TableName="approval-ledger")["Items"]]
print("ledger statuses:", sorted({r["status"] for r in rows}), "| executed:", [r.get("work_order_id") for r in rows if r["status"] == "EXECUTED"])
print("approval is fully audited:", "StartExecution" in names and any(r["status"] == "EXECUTED" for r in rows))
