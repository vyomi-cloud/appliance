import time

from google.cloud import firestore

import gcp

db = gcp.firestore_client()
col = db.collection("approval-ledger")
now = int(time.time())
col.document("req-exp-stale").set({"status": "PENDING", "expires_at": now - 5})
col.document("req-exp-done").set({"status": "APPROVED", "expires_at": now - 5})
col.document("req-exp-fresh").set({"status": "PENDING", "expires_at": now + 3600})


@firestore.transactional
def expire(tx, ref):
    snap = ref.get(transaction=tx)
    if snap.get("status") == "PENDING" and snap.get("expires_at") < int(time.time()):
        tx.update(ref, {"status": "EXPIRED"})
        return True
    return False


@firestore.transactional
def decide(tx, ref, status):
    snap = ref.get(transaction=tx)
    if snap.get("status") != "PENDING":
        return False                  # only a PENDING request can be decided
    tx.update(ref, {"status": status})
    return True


expired = [d.id for d in col.where("status", "==", "PENDING").stream() if expire(db.transaction(), col.document(d.id))]
assert expired == ["req-exp-stale"], expired
status = lambda r: col.document(r).get().get("status")
assert status("req-exp-stale") == "EXPIRED" and status("req-exp-done") == "APPROVED" and status("req-exp-fresh") == "PENDING"
print("expired:", expired[0], "| approved document untouched | fresh one still waiting")
assert decide(db.transaction(), col.document("req-exp-stale"), "APPROVED") is False
assert status("req-exp-stale") == "EXPIRED"
for r in ("req-exp-stale", "req-exp-done", "req-exp-fresh"):
    col.document(r).delete()
print("approval expiry verified")
