import os
import time

from google.cloud import firestore

AUTHORISED = ("@example.com",)


def handler(request):
    body = request.get_json(silent=True) or {}
    rid, decision, approver = body.get("request_id"), (body.get("decision") or "").upper(), body.get("approver", "")
    db = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])
    ref = db.collection(os.environ.get("LEDGER_COLLECTION", "approval-ledger")).document(rid)
    snap = ref.get()
    if not snap.exists:
        return {"ok": False, "error": "unknown request"}
    row = snap.to_dict()
    if row.get("status") != "PENDING":
        return {"ok": False, "error": f"request is {row.get('status')}, not PENDING"}
    if decision not in ("APPROVE", "REJECT") or not approver.endswith(AUTHORISED):
        return {"ok": False, "error": "decision must be APPROVE or REJECT from an authorised approver"}
    status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    ref.update({"status": status, "approver": approver, "decided_at": int(time.time())})
    return {"ok": True, "request_id": rid, "status": status, "approver": approver}
