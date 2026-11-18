"""Approval decision function (component 5). The approver reads a request from the Pub/Sub inbox and sends the decision here; the function checks the
request is still PENDING and the approver is authorised, then records the decision in the Firestore ledger. It does not create the work order."""
import os, time
APPROVERS = ("@example.com",)


def handler(request):
    from google.cloud import firestore
    b = request.get_json(silent=True) or {}
    rid, decision, approver = b.get("request_id"), (b.get("decision") or "").upper(), b.get("approver", "")
    ref = firestore.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"]).collection(os.environ.get("LEDGER_COLLECTION", "approval-ledger")).document(rid)
    snap = ref.get()
    if not snap.exists:
        return {"ok": False, "error": "unknown request"}
    row = snap.to_dict()
    if row.get("status") != "PENDING":
        return {"ok": False, "error": f"request is {row.get('status')}, not PENDING"}
    if decision not in ("APPROVE", "REJECT") or not approver.endswith(APPROVERS):
        return {"ok": False, "error": "decision must be APPROVE or REJECT from an authorised approver"}
    status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    ref.update({"status": status, "approver": approver, "decided_at": int(time.time())})
    return {"ok": True, "request_id": rid, "status": status, "approver": approver}
