"""Write tool, behind the approval: creates the work order only when the ledger says APPROVED, then closes the ledger entry (EXECUTED)."""
import json, os
import azure.functions as func
from tools import _table


def main(req: func.HttpRequest) -> func.HttpResponse:
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceNotFoundError
    from azure.data.tables import UpdateMode
    b = req.get_json() if req.get_body() else {}
    rid = b.get("request_id", "")
    ledger = _table(os.environ.get("LEDGER_TABLE", "approvalledger"))
    out = lambda d: func.HttpResponse(json.dumps(d), mimetype="application/json")
    try:
        row = ledger.get_entity("req", rid)
    except ResourceNotFoundError:
        return out({"ok": False, "error": "refused: unknown request"})
    if row.get("status") == "EXECUTED":
        return out({"ok": True, "work_order_id": row["work_order_id"], "idempotent": True})
    if row.get("status") != "APPROVED":
        return out({"ok": False, "error": f"refused: ledger status is {row.get('status')}, a work order needs APPROVED"})
    wo_id = "WO-" + rid[-6:].upper()
    _table(os.environ.get("WORK_ORDERS_TABLE", "workorders")).upsert_entity({
        "PartitionKey": "wo", "RowKey": wo_id, "work_order_id": wo_id, "asset_id": row["asset_id"], "title": row["summary"], "priority": row.get("priority", "P3"),
        "status": "OPEN", "requester": row.get("requester", "")})
    ledger.update_entity({"PartitionKey": "req", "RowKey": rid, "status": "EXECUTED", "work_order_id": wo_id}, mode=UpdateMode.MERGE,
                         etag=row.metadata["etag"], match_condition=MatchConditions.IfNotModified)
    return out({"ok": True, "work_order_id": wo_id})
