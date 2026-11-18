"""Approval decision function (component 5). The approver reads a request from the Service Bus approver inbox and sends the decision here; the function
checks the request is still PENDING and the approver is authorised, then records the decision in the Azure Table ledger with an ETag-conditional update
(optimistic concurrency: two approvers cannot both decide). It does not create the work order."""
import json, os, time
import azure.functions as func
from tools import _table
APPROVERS = ("@example.com",)


def main(req: func.HttpRequest) -> func.HttpResponse:
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceNotFoundError, ResourceModifiedError
    from azure.data.tables import UpdateMode
    b = req.get_json() if req.get_body() else {}
    rid, decision, approver = b.get("request_id"), (b.get("decision") or "").upper(), b.get("approver", "")
    ledger = _table(os.environ.get("LEDGER_TABLE", "approvalledger"))
    out = lambda d: func.HttpResponse(json.dumps(d), mimetype="application/json")
    try:
        row = ledger.get_entity("req", rid)
    except ResourceNotFoundError:
        return out({"ok": False, "error": "unknown request"})
    if row.get("status") != "PENDING":
        return out({"ok": False, "error": f"request is {row.get('status')}, not PENDING"})
    if decision not in ("APPROVE", "REJECT") or not approver.endswith(APPROVERS):
        return out({"ok": False, "error": "decision must be APPROVE or REJECT from an authorised approver"})
    status = "APPROVED" if decision == "APPROVE" else "REJECTED"
    try:
        ledger.update_entity({"PartitionKey": "req", "RowKey": rid, "status": status, "approver": approver, "decided_at": int(time.time())},
                             mode=UpdateMode.MERGE, etag=row.metadata["etag"], match_condition=MatchConditions.IfNotModified)
    except ResourceModifiedError:
        return out({"ok": False, "error": "request was decided concurrently"})
    return out({"ok": True, "request_id": rid, "status": status, "approver": approver})
