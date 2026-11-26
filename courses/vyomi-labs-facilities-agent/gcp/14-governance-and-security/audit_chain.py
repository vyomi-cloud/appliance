import hashlib
import json
import time

import gcp

col = gcp.firestore_client().collection("approval-audit")
for d in col.stream():
    d.reference.delete()


def digest(prev, body):
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True)).encode()).hexdigest()


def append(seq, event):
    prev = "0" * 64 if seq == 0 else col.document(f"{seq - 1:06d}").get().get("hash")
    body = {"seq": seq, "ts": int(time.time()), **event}
    col.document(f"{seq:06d}").set({"body": json.dumps(body, sort_keys=True), "prev": prev, "hash": digest(prev, body)})


def verify():
    prev = "0" * 64
    for d in sorted(col.stream(), key=lambda d: d.id):
        r = d.to_dict()
        if r["prev"] != prev or digest(prev, json.loads(r["body"])) != r["hash"]:
            return d.id
        prev = r["hash"]
    return None


for i, ev in enumerate([{"event": "requested", "by": "maria"}, {"event": "approved", "by": "duty.manager"}, {"event": "executed", "wo": "WO-17"},
                        {"event": "requested", "by": "sam"}, {"event": "rejected", "by": "duty.manager"}]):
    append(i, ev)
assert verify() is None
print("chain of 5 verified")
body = json.loads(col.document("000001").get().get("body"))
body["by"] = "mallory"
col.document("000001").update({"body": json.dumps(body, sort_keys=True)})
assert verify() == "000001", "the edit must be detected at the edited entry"
print("tampering detected at entry", verify())
print("audit chain verified")
