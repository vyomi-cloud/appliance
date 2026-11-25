import threading

import approval
import functions
import gcp

rid = open("request_id.txt").read().strip()
body, ack_id = approval.pull_request(rid)
print("inbox delivered:", body["summary"][:50])

refused = functions.call("facilities-create-work-order", {"request_id": rid})
print("create before approval refused:", not refused["ok"])
stranger = functions.call("facilities-approval-decision", {"request_id": rid, "decision": "APPROVE", "approver": "mallory@evil.test"})
print("stranger refused:", not stranger["ok"], "| ledger still", approval.ledger_row(rid)["status"])

seen = {}
waiter = threading.Thread(target=lambda: seen.update(approval.wait_for_decision(rid)))
waiter.start()
decision = functions.call("facilities-approval-decision", {"request_id": rid, "decision": "APPROVE", "approver": "duty.manager@example.com"})
waiter.join(timeout=30)
print("approver decided:", decision["status"], "| waiting caller saw:", seen.get("status"))
approval.ack(ack_id)

created = functions.call("facilities-create-work-order", {"request_id": rid})
again = functions.call("facilities-create-work-order", {"request_id": rid})
row = approval.ledger_row(rid)
order = gcp.firestore_client().collection("work-orders").document(created["work_order_id"]).get().to_dict()
print("work order:", created["work_order_id"], order["status"], "| ledger:", row["status"], "by", row["approver"], "| idempotent:", again["idempotent"])
assert row["status"] == "EXECUTED" and order["asset_id"] == "B-12"
