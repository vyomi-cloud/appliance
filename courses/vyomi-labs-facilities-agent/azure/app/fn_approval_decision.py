import json
import os
import time
import azure.functions as func

APPROVERS = ("@example.com",)


def _table(name):
    from azure.data.tables import TableClient
    return TableClient.from_connection_string(os.environ["TABLE_CONNECTION_STRING"], name)


def main(req: func.HttpRequest) -> func.HttpResponse:
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
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
