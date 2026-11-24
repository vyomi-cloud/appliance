import functions
import gcp

db = gcp.firestore_client()
rid = "req-ch7test01"
db.collection("approval-ledger").document(rid).set({"request_id": rid, "asset_id": "B-12", "summary": "Chapter 7 write-tool check", "priority": "P2",
                                                   "requester": "lab", "status": "PENDING"})

refused = functions.call("facilities-create-work-order", {"request_id": rid})
print("before approval:", refused["ok"], "-", refused["error"][:40])

stranger = functions.call("facilities-approval-decision", {"request_id": rid, "decision": "APPROVE", "approver": "mallory@evil.test"})
print("stranger approves:", stranger["ok"])

approved = functions.call("facilities-approval-decision", {"request_id": rid, "decision": "APPROVE", "approver": "duty.manager@example.com"})
print("approver decides:", approved["status"])

first = functions.call("facilities-create-work-order", {"request_id": rid})
second = functions.call("facilities-create-work-order", {"request_id": rid})
print("work order:", first["work_order_id"], "| second call idempotent:", second.get("idempotent"))
print("ledger:", db.collection("approval-ledger").document(rid).get().to_dict()["status"])

db.collection("work-orders").document(first["work_order_id"]).delete()
db.collection("approval-ledger").document(rid).delete()
