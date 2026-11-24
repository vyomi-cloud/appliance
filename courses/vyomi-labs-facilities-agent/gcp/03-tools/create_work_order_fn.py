import os

from google.cloud import firestore


def handler(request):
    body = request.get_json(silent=True) or {}
    db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])
    ref = db.collection(os.environ.get("LEDGER_COLLECTION", "approval-ledger")).document(body["request_id"])
    row = ref.get().to_dict() or {}
    if row.get("status") == "EXECUTED":
        return {"ok": True, "work_order_id": row["work_order_id"], "idempotent": True}
    if row.get("status") != "APPROVED":
        return {"ok": False, "error": f"refused: ledger status is {row.get('status')}, a work order needs APPROVED"}
    wo_id = "WO-" + body["request_id"][-6:].upper()
    db.collection(os.environ.get("WORK_ORDERS_COLLECTION", "work-orders")).document(wo_id).set({
        "work_order_id": wo_id, "asset_id": row["asset_id"], "title": row["summary"], "priority": row.get("priority", "P3"),
        "status": "OPEN", "requester": row.get("requester", "")})
    ref.update({"status": "EXECUTED", "work_order_id": wo_id})
    return {"ok": True, "work_order_id": wo_id}
