"""Enterprise additions to the GCP course (Mesh edition): approval expiry, tool contract failure lab, cost limit, key rotation, tamper-evident
audit chain and the Ship it capstone (Infrastructure Manager). Every block is verified by `python -m vyomilabs.labrun gcp ...`."""

MESH = ["mesh"]


def extend(LAB, b):
    LAB[5] += [
     b("Approval expiry: nobody answers, the request expires", "A request that waits forever is a risk. Each Firestore ledger document gets `expires_at`; a sweeper marks PENDING documents past their deadline EXPIRED inside a transaction that re-reads the status, so a request approved a moment earlier is never overwritten. The block proves an unanswered request expires, an approved one is untouched and an expired one cannot be approved afterwards.",
       "expiry.py", '''
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
''', run="python expiry.py", expect="approval expiry verified", kind="harden", edition=MESH,
       nano_note="Firestore transactions are not verified on the Nano GCP core."),
    ]
    LAB[7] += [
     b("Failure lab: a poisoned tool call is refused", "The model builds the arguments of every tool call, so a manipulated prompt means hostile arguments. The contract is checked before any Firestore call: asset ids must match `^[A-Z]{1,3}-[0-9]{1,4}$`, priorities come from a closed set, free text is length-limited and stripped of control characters. The block fires the inputs a prompt injection would produce (a query-injection id, a path traversal, an oversized summary, control characters, an unknown priority) and asserts each is refused with a reason while valid input passes.",
       "tool_contract.py", '''
import re

ASSET = re.compile(r"^[A-Z]{1,3}-[0-9]{1,4}$")
PRIORITIES = {"P1", "P2", "P3", "P4"}


def validate(call):
    errs = []
    if not ASSET.match(str(call.get("asset_id", ""))):
        errs.append("asset_id must look like B-12")
    if call.get("priority", "P3") not in PRIORITIES:
        errs.append("priority must be one of P1..P4")
    s = str(call.get("summary", ""))
    if not 3 <= len(s) <= 300 or any(ord(c) < 32 for c in s):
        errs.append("summary must be 3-300 printable characters")
    return errs


good = {"asset_id": "B-12", "priority": "P2", "summary": "Boiler pressure above limit"}
assert validate(good) == []
poisoned = {
    "document path injection": {**good, "asset_id": "B-12/../approval-ledger/x"},
    "path traversal": {**good, "asset_id": "../../secrets"},
    "oversized summary": {**good, "summary": "x" * 5000},
    "control characters": {**good, "summary": "ok\\x00\\x1b[31m"},
    "unknown priority": {**good, "priority": "P0; drop"},
}
for name, call in poisoned.items():
    errs = validate(call)
    assert errs, name + " must be refused"
    print("refused:", name, "->", errs[0])
print("tool contract verified: 5 of 5 poisoned calls refused")
''', run="python tool_contract.py", expect="tool contract verified: 5 of 5 poisoned calls refused", kind="failure", edition=MESH,
       nano_note="Pure Python: kept Mesh-only until the Nano matrix verifies it."),
    ]
    LAB[8] += [
     b("Cost and budget limit per layer", "A budget object counts notional model tokens per layer and refuses the call that would cross the limit, so a runaway loop stops itself before the bill. The block drives the real Gemini-compatible model from chapter 10 until the budget trips, then asserts the crossing call was refused and spend never exceeded the limit.",
       "cost_meter.py", '''
from vymodels import chat

PRICE_PER_1K = 0.0006      # notional price per 1,000 tokens: put the real rate card here


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, layer, limit_usd):
        self.layer, self.limit, self.spent, self.calls = layer, limit_usd, 0.0, 0

    def charge(self, text_in, text_out):
        cost = (len(text_in) + len(text_out)) / 4 / 1000 * PRICE_PER_1K
        if self.spent + cost > self.limit:
            raise BudgetExceeded(f"{self.layer}: {self.spent + cost:.6f} would exceed the {self.limit:.6f} limit")
        self.spent += cost
        self.calls += 1


budget = Budget("agents", limit_usd=0.0004)
refused = None
for _ in range(200):
    q = "Summarise the boiler shutdown procedure in one sentence. " * 3
    try:
        budget.charge(q, chat(q))
    except BudgetExceeded as e:
        refused = str(e)
        break
assert refused, "the budget must trip before 200 calls"
assert budget.spent <= budget.limit
print("calls allowed:", budget.calls, "| spent:", round(budget.spent, 6), "| limit:", budget.limit)
print("refused:", refused)
print("cost limit verified")
''', run="python cost_meter.py", expect="cost limit verified", kind="harden", edition=MESH,
       nano_note="Replays against the in-browser model on Nano once the Nano matrix verifies it."),
    ]
    LAB[13] += [
     b("Key rotation without re-encrypting data", "Rotation adds a new key VERSION and makes it primary; earlier versions still decrypt what they sealed, so nothing already wrapped breaks. The block wraps a data key, creates a new version, promotes it, asserts the primary changed, decrypts the OLD ciphertext (Cloud KMS picks the version from the ciphertext) and wraps again under the new primary.",
       "key_rotation.py", '''
from google.cloud import kms

import gcp

client = gcp.rest(kms.KeyManagementServiceClient)
KEY = f"{gcp.PARENT}/keyRings/facilities/cryptoKeys/ledger-key"
CTX = b"collection=approval-ledger"
dek = b"0123456789abcdef0123456789abcdef"

before = client.get_crypto_key(request={"name": KEY}).primary.name
old = client.encrypt(request={"name": KEY, "plaintext": dek, "additional_authenticated_data": CTX}).ciphertext

new_version = client.create_crypto_key_version(request={"parent": KEY, "crypto_key_version": {}}).name
client.update_crypto_key_primary_version(request={"name": KEY, "crypto_key_version_id": new_version.rsplit("/", 1)[-1]})
after = client.get_crypto_key(request={"name": KEY}).primary.name
assert after != before and after == new_version, "the new version must be primary"
print("primary:", before.rsplit("/", 1)[-1], "->", after.rsplit("/", 1)[-1])

assert client.decrypt(request={"name": KEY, "ciphertext": old, "additional_authenticated_data": CTX}).plaintext == dek
print("ciphertext from the old version still decrypts")
fresh = client.encrypt(request={"name": KEY, "plaintext": dek, "additional_authenticated_data": CTX}).ciphertext
assert fresh != old
print("key rotation verified")
''', run="python key_rotation.py", expect="key rotation verified", kind="harden", edition=MESH,
       nano_note="KMS key versions are not verified on the Nano GCP core."),
     b("Tamper-evident audit trail", "Cloud Audit Logs record the control plane; they cannot prove nobody edited your own approval records. Chain them: each audit document stores the SHA-256 of the previous one plus its own content, so changing, deleting or re-ordering any entry breaks every hash after it. The block writes five events to Firestore, verifies the chain, edits one entry the way an attacker with database access would and asserts the verifier names exactly that entry.",
       "audit_chain.py", '''
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
''', run="python audit_chain.py", expect="audit chain verified", kind="harden", edition=MESH,
       nano_note="Firestore on Nano is not yet verified for this block."),
     b("Ship it: deploy the stack with Infrastructure Manager", "The capstone. Infrastructure Manager runs Terraform for you: you hand it a configuration and a service account, it creates a deployment, a revision and the resources. Here the configuration describes the course's bucket and Pub/Sub topic. The block creates the deployment through the real `config.googleapis.com` REST API, waits for the long-running operation, asserts the revision applied and lists its resources. On real Google Cloud you point `gcsSource` or `gitSource` at the same files, and replace simulator-only values (project id, bucket names must be globally unique) first.",
       "ship_it.py", '''
import json
import time

import gcp

TF = """
resource "google_storage_bucket" "docs" {
  name     = "facilities-ship-docs"
  location = "US"
}
resource "google_pubsub_topic" "approvals" {
  name = "facilities-ship-approvals"
}
"""
s = gcp.authed_session()
base = f"{gcp.ENDPOINT}/v1/{gcp.PARENT}/deployments"
dep = f"{gcp.PARENT}/deployments/facilities-ship"
s.delete(f"{gcp.ENDPOINT}/v1/{dep}")
time.sleep(1)
r = s.post(base + "?deploymentId=facilities-ship", json={
    "terraformBlueprint": {"vyomiFiles": {"main.tf": TF}},
    "serviceAccount": f"projects/{gcp.PROJECT}/serviceAccounts/infra-manager@{gcp.PROJECT}.iam.gserviceaccount.com"})
assert r.status_code == 200, r.text[:300]
op = r.json()
for _ in range(60):
    if op.get("done"):
        break
    time.sleep(0.5)
    op = s.get(f"{gcp.ENDPOINT}/v1/{op['name']}").json()
assert op.get("done") and not op.get("error"), op
d = s.get(f"{gcp.ENDPOINT}/v1/{dep}").json()
print("deployment state:", d.get("state"))
assert d.get("state") == "ACTIVE", d
rev = d["latestRevision"]
res = s.get(f"{gcp.ENDPOINT}/v1/{rev}/resources").json().get("resources", [])
types = sorted(x["terraformInfo"]["type"] for x in res)
print("resources applied:", types)
assert types == ["google_pubsub_topic", "google_storage_bucket"]
print("ship it verified: Infrastructure Manager applied", len(res), "resources; review them, then point gcsSource at the same files on real Google Cloud")
''', run="python ship_it.py", expect="ship it verified", kind="ship", edition=MESH,
       nano_note="Infrastructure Manager is not in the Nano GCP core."),
    ]
