import gcp

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

db = gcp.firestore_client()
for collection, rows, key in (("assets", ASSETS, "asset_id"), ("work-orders", WORK_ORDERS, "work_order_id")):
    for row in rows:
        db.collection(collection).document(row[key]).set(row)
    print("seeded", collection, len(rows))
