import approval
import functions
import gcp

rid = approval.request_approval("EL-3", "Replace elevator 3 (this one will be rejected)", "P3", "test")
body, ack_id = approval.pull_request(rid)
decision = functions.call("facilities-approval-decision", {"request_id": rid, "decision": "REJECT", "approver": "duty.manager@example.com"})
approval.ack(ack_id)
refused = functions.call("facilities-create-work-order", {"request_id": rid})
orders = [d.to_dict() for d in gcp.firestore_client().collection("work-orders").stream()]
leaked = [w for w in orders if w["asset_id"] == "EL-3" and w.get("requester") == "test"]
print("decision:", decision["status"], "| create refused:", not refused["ok"], "| work orders written:", len(leaked))
assert decision["status"] == "REJECTED" and not leaked
