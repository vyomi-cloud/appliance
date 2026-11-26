import hashlib
import json
import time
from azdata import table

audit = table("approvalaudit")
for e in list(audit.list_entities()):
    audit.delete_entity(e["PartitionKey"], e["RowKey"])


def digest(prev, body):
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True)).encode()).hexdigest()


def append(seq, event):
    prev = "0" * 64 if seq == 0 else audit.get_entity("a", f"{seq - 1:06d}")["hash"]
    body = {"seq": seq, "ts": int(time.time()), **event}
    audit.upsert_entity({"PartitionKey": "a", "RowKey": f"{seq:06d}", "body": json.dumps(body, sort_keys=True), "prev": prev, "hash": digest(prev, body)})


def verify():
    prev = "0" * 64
    for row in sorted(audit.list_entities(), key=lambda r: r["RowKey"]):
        if row["prev"] != prev or digest(prev, json.loads(row["body"])) != row["hash"]:
            return row["RowKey"]
        prev = row["hash"]
    return None


for i, ev in enumerate([{"event": "requested", "by": "maria"}, {"event": "approved", "by": "duty.manager"}, {"event": "executed", "wo": "WO-17"},
                        {"event": "requested", "by": "sam"}, {"event": "rejected", "by": "duty.manager"}]):
    append(i, ev)
assert verify() is None
print("chain of 5 verified")
row = audit.get_entity("a", "000001")
body = json.loads(row["body"]); body["by"] = "mallory"
audit.update_entity({"PartitionKey": "a", "RowKey": "000001", "body": json.dumps(body, sort_keys=True)}, mode="merge")
assert verify() == "000001", "the edit must be detected at the edited entry"
print("tampering detected at entry", verify())
print("audit chain verified")
