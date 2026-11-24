from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError
from azure.data.tables import UpdateMode
from approval import request_approval, pull_request, ledger_row, work_orders
from azdata import call_function, table, FUNCTION_APP

request_approval("req-demo0002", "EL-3", "Replace elevator 3 (this one is rejected)", "P3", "maria")
pull_request("req-demo0002")
d = call_function(FUNCTION_APP, "approval-decision", {"request_id": "req-demo0002", "decision": "REJECT", "approver": "duty.manager@example.com"})
refused = call_function(FUNCTION_APP, "create-work-order", {"request_id": "req-demo0002"})
print("decision:", d["status"], "| create-work-order:", refused["error"][:40])
print("work orders written for the rejected request:", len([w for w in work_orders() if w.get("requester") == "maria" and w["asset_id"] == "EL-3"]))

ledger = table("approvalledger")
stale = ledger.get_entity("req", "req-demo0001").metadata["etag"]
ledger.update_entity({"PartitionKey": "req", "RowKey": "req-demo0001", "note": "touched"}, mode=UpdateMode.MERGE)
try:
    ledger.update_entity({"PartitionKey": "req", "RowKey": "req-demo0001", "status": "REJECTED"}, mode=UpdateMode.MERGE, etag=stale, match_condition=MatchConditions.IfNotModified)
except HttpResponseError as e:
    print("decision with a stale ETag refused:", e.status_code)
