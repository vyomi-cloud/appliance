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
executed = [r for r in rows if r["status"] == "EXECUTED"]
print("ledger statuses:", sorted({r["status"] for r in rows}), "| executed:", [r.get("work_order_id") for r in executed])
if not executed or "StartExecution" not in names:
    raise SystemExit("missing prerequisite: chapter 5 must have run 'Let the agent ask for a work order' and 'Approve the request' first "
                     "(CloudTrail has StartExecution: %s, ledger has an EXECUTED request: %s)" % ("StartExecution" in names, bool(executed)))
assert "SendTaskSuccess" in names, "the approval itself (SendTaskSuccess) must be in the trail, not only the start"
# Every executed request must trace back to a ledger decision AND a work order that exists.
wos = {i["work_order_id"]["S"] for i in ddb.scan(TableName="facilities-work-orders")["Items"]}
assert all(r["work_order_id"] in wos for r in executed), "an EXECUTED request points at a work order that does not exist"
print("approval is fully audited:", True)
