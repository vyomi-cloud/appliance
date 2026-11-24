import approval
import gcp
from agents import ask

question = "Boiler B-12 is at 34 psi. Please raise a work order for it."
result = ask(question, "maria.ops@example.com")
rid = approval.request_approval("B-12", "Work order for B-12: " + question[:80], "P1", "maria.ops@example.com")
open("request_id.txt", "w").write(rid)
print("agent route:", result["route"])
print("ledger:", approval.ledger_row(rid)["status"], "for", rid)
orders = [d.to_dict() for d in gcp.firestore_client().collection("work-orders").stream()]
assert not [w for w in orders if w.get("requester") == "maria.ops@example.com"], "a work order exists before approval"
print("no work order exists before approval")
