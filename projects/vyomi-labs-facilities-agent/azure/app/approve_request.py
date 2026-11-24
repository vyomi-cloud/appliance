import threading
from approval import pull_request, wait_decision, ledger_row, work_orders
from azdata import call_function, FUNCTION_APP

msg = pull_request("req-demo0001")
print("inbox delivered:", msg["summary"][:50])

seen = {}
waiting = threading.Thread(target=wait_decision, args=("req-demo0001", seen))
waiting.start()
d = call_function(FUNCTION_APP, "approval-decision", {"request_id": "req-demo0001", "decision": "APPROVE", "approver": "duty.manager@example.com"})
waiting.join(timeout=30)
print("decision:", d["status"], "| the waiting caller saw:", seen["row"]["status"])

wo = call_function(FUNCTION_APP, "create-work-order", {"request_id": "req-demo0001"})
row = ledger_row("req-demo0001")
print("work order:", wo["work_order_id"], "| ledger:", row["status"], "approved by", row["approver"])
again = call_function(FUNCTION_APP, "create-work-order", {"request_id": "req-demo0001"})
print("second call idempotent:", again.get("idempotent"), "| work orders for B-12 from this request:", len([w for w in work_orders() if w["work_order_id"] == wo["work_order_id"]]))
