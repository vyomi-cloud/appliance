from approval import request_approval, ledger_row, work_orders
from azdata import call_function, FUNCTION_APP

request_approval("req-demo0001", "B-12", "Work order for B-12: boiler pressure is 34 psi, above the 30 psi limit", "P1", "maria")
print("ledger status:", ledger_row("req-demo0001")["status"])
print("work orders requested by maria:", len([w for w in work_orders() if w.get("requester") == "maria"]))
premature = call_function(FUNCTION_APP, "create-work-order", {"request_id": "req-demo0001"})
print("create-work-order before approval:", premature["error"])
stranger = call_function(FUNCTION_APP, "approval-decision", {"request_id": "req-demo0001", "decision": "APPROVE", "approver": "mallory@evil.test"})
print("unauthorised approver:", stranger["error"], "| ledger still", ledger_row("req-demo0001")["status"])
