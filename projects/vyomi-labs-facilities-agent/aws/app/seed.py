import boto3

ddb = boto3.client("dynamodb")
ASSETS = [
    {"asset_id": "B-12", "name": "Boiler B-12", "site": "HQ-1", "type": "boiler", "status": "RUNNING", "pressure_psi": 34, "last_inspection": "2026-08-02"},
    {"asset_id": "AHU-7", "name": "Air handling unit 7", "site": "HQ-1", "type": "hvac", "status": "DEGRADED", "supply_temp_drift_c": 3.8, "last_inspection": "2026-09-12"},
    {"asset_id": "EL-3", "name": "Elevator 3", "site": "HQ-2", "type": "elevator", "status": "RUNNING", "last_inspection": "2026-10-01"},
]
WORK_ORDERS = [
    {"work_order_id": "WO-000101", "asset_id": "AHU-7", "title": "Replace AHU-7 filter", "priority": "P3", "status": "CLOSED", "requester": "seed"},
    {"work_order_id": "WO-000102", "asset_id": "B-12", "title": "Quarterly PRV inspection", "priority": "P2", "status": "OPEN", "requester": "seed"},
    {"work_order_id": "WO-000103", "asset_id": "EL-3", "title": "Door-zone sensor check", "priority": "P2", "status": "OPEN", "requester": "seed"},
]


def attr(v):
    return {"N": str(v)} if isinstance(v, (int, float)) else {"S": str(v)}


for table, rows in (("facilities-assets", ASSETS), ("facilities-work-orders", WORK_ORDERS)):
    for row in rows:
        ddb.put_item(TableName=table, Item={k: attr(v) for k, v in row.items()})
    print("seeded", table, len(rows))
