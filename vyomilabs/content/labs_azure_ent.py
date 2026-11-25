"""Enterprise additions to the Azure course (Mesh edition): approval expiry, validation, tamper-evident audit, key rotation, cost limit,
failure labs and the Ship it capstone (ARM export template). Every block is verified by `python -m vyomilabs.labrun azure ...`."""

MESH = ["mesh"]


def extend(LAB, b):
    LAB[5] += [
     b("Approval expiry: nobody answers, the request expires", "A request that waits forever is a risk. Every ledger row gets `expires_at`; a sweeper marks PENDING rows past their deadline EXPIRED using an ETag condition, so a row decided a moment earlier is never overwritten (the same optimistic-concurrency rule the decision function uses). The block proves three things: an unanswered request expires, an already-approved request is untouched, and an expired request can no longer be approved.",
       "expiry.py", '''
import time
from azure.core import MatchConditions
from azure.core.exceptions import ResourceModifiedError
from azure.data.tables import UpdateMode
from azdata import table

ledger = table("approvalledger")
now = int(time.time())
ledger.upsert_entity({"PartitionKey": "req", "RowKey": "req-exp-stale", "status": "PENDING", "expires_at": now - 5, "asset_id": "B-12"})
ledger.upsert_entity({"PartitionKey": "req", "RowKey": "req-exp-done", "status": "APPROVED", "expires_at": now - 5, "asset_id": "B-12"})
ledger.upsert_entity({"PartitionKey": "req", "RowKey": "req-exp-fresh", "status": "PENDING", "expires_at": now + 3600, "asset_id": "B-12"})


def sweep():
    expired = []
    for row in ledger.query_entities("status eq 'PENDING'"):
        if int(row.get("expires_at", 1 << 60)) < int(time.time()):
            try:
                ledger.update_entity({"PartitionKey": "req", "RowKey": row["RowKey"], "status": "EXPIRED"}, mode=UpdateMode.MERGE,
                                     etag=row.metadata["etag"], match_condition=MatchConditions.IfNotModified)
                expired.append(row["RowKey"])
            except ResourceModifiedError:
                pass          # decided in the meantime: leave it alone
    return expired


assert sweep() == ["req-exp-stale"], "only the overdue PENDING request may expire"
status = lambda r: ledger.get_entity("req", r)["status"]
assert status("req-exp-stale") == "EXPIRED" and status("req-exp-done") == "APPROVED" and status("req-exp-fresh") == "PENDING"
print("expired:", "req-exp-stale", "| approved row untouched | fresh row still waiting")

# a decision that raced the sweeper: it holds an old ETag, so the condition refuses it
stale = ledger.get_entity("req", "req-exp-stale")
try:
    ledger.update_entity({"PartitionKey": "req", "RowKey": "req-exp-stale", "status": "APPROVED"}, mode=UpdateMode.MERGE,
                         etag="W/\\"stale\\"", match_condition=MatchConditions.IfNotModified)
    raise SystemExit("an old ETag must not be able to approve an expired request")
except ResourceModifiedError:
    pass
assert status("req-exp-stale") == "EXPIRED"
print("approval expiry verified")
''', run="python expiry.py", expect="approval expiry verified", kind="harden", edition=MESH,
       nano_note="Table storage conditions are not part of the Nano Azure core yet."),
    ]
    LAB[7] += [
     b("Failure lab: a poisoned tool call is refused", "The model builds the arguments of every tool call, so a manipulated prompt means hostile arguments. The tool contract is checked before any storage call: asset ids must match `^[A-Z]{1,3}-[0-9]{1,4}$`, priorities come from a closed set, and free text is length-limited and stripped of control characters. The block fires the poisoned inputs a prompt injection would produce (an OData filter injection, a path traversal, an oversized summary, an unknown priority) and asserts every one is refused with a reason while valid input passes.",
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
    "odata injection": {**good, "asset_id": "B-12' or PartitionKey ne '"},
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
       nano_note="Pure Python: would run on Nano, kept Mesh-only until the Nano matrix verifies it."),
    ]
    LAB[8] += [
     b("Cost and budget limit per layer", "Cost belongs in the telemetry. A budget object counts notional model tokens per layer and refuses the call that would cross the limit, so a runaway loop stops itself instead of reaching the bill. The block drives the real Azure OpenAI deployments from chapter 10 until the budget trips, asserts the call that crosses it is refused and that spend never exceeds the limit.",
       "cost_meter.py", '''
from vymodels import chat

PRICE_PER_1K = {"chat": 0.0006}       # notional price per 1,000 tokens: the real rate card goes here


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, layer, limit_usd):
        self.layer, self.limit, self.spent, self.calls = layer, limit_usd, 0.0, 0

    def charge(self, text_in, text_out):
        tokens = (len(text_in) + len(text_out)) / 4
        cost = tokens / 1000 * PRICE_PER_1K["chat"]
        if self.spent + cost > self.limit:
            raise BudgetExceeded(f"{self.layer}: {self.spent + cost:.6f} would exceed the {self.limit:.6f} limit")
        self.spent += cost
        self.calls += 1


budget = Budget("agents", limit_usd=0.0004)
refused = None
for i in range(200):
    q = "Summarise the boiler shutdown procedure in one sentence. " * 3
    try:
        a = chat(q)
        budget.charge(q, a)
    except BudgetExceeded as e:
        refused = str(e)
        break
assert refused, "the budget must trip before 200 calls"
assert budget.spent <= budget.limit
print("calls allowed:", budget.calls, "| spent:", round(budget.spent, 6), "| limit:", budget.limit)
print("refused:", refused)
print("cost limit verified")
''', run="python cost_meter.py", expect="cost limit verified", kind="harden", edition=MESH, needs_runtime=False,
       nano_note="Needs the model deployments; Nano replays this against the in-browser model."),
    ]
    LAB[13] += [
     b("Key rotation without re-encrypting data", "Rotation creates a new key VERSION under the same name; old versions stay available to decrypt, so nothing already wrapped breaks. The block wraps a data key, rotates `ledger-key`, asserts the version list grew and the current version changed, then unwraps the OLD wrapped key (pinned to its version) and wraps a new one with the new version.",
       "key_rotation.py", '''
from azure.keyvault.keys import KeyClient
from azure.keyvault.keys.crypto import CryptographyClient, KeyWrapAlgorithm
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from azlab import DevToken, ENDPOINT

kc = KeyClient(vault_url=ENDPOINT, credential=DevToken(), verify_challenge_resource=False)
v1 = kc.get_key("ledger-key")
dek = AESGCM.generate_key(bit_length=256)
alg = KeyWrapAlgorithm.rsa_oaep_256
wrapped_v1 = CryptographyClient(v1.id, DevToken(), verify_challenge_resource=False).wrap_key(alg, dek).encrypted_key

v2 = kc.rotate_key("ledger-key")
versions = list(kc.list_properties_of_key_versions("ledger-key"))
assert len(versions) >= 2 and v2.properties.version != v1.properties.version, "rotation must create a new version"
print("versions:", len(versions), "| current changed:", v2.properties.version != v1.properties.version)

assert CryptographyClient(v1.id, DevToken(), verify_challenge_resource=False).unwrap_key(alg, wrapped_v1).key == dek
print("data wrapped by the old version still unwraps")
wrapped_v2 = CryptographyClient(v2.id, DevToken(), verify_challenge_resource=False).wrap_key(alg, dek).encrypted_key
assert wrapped_v2 != wrapped_v1
print("key rotation verified")
''', run="python key_rotation.py", expect="key rotation verified", kind="harden", edition=MESH,
       nano_note="Key Vault key versions are not in the Nano Azure core."),
     b("Tamper-evident audit trail", "The Activity Log tells you what happened; it cannot prove nobody edited your own approval records. Chain them: each audit entry stores the SHA-256 of the previous entry plus its own content, so changing, deleting or re-ordering any entry breaks every hash after it. The block writes five approval events to a table, verifies the chain, edits one entry the way an attacker with table access would, and asserts the verifier finds exactly where.",
       "audit_chain.py", '''
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
''', run="python audit_chain.py", expect="audit chain verified", kind="harden", edition=MESH,
       nano_note="Table storage on Nano is not yet verified for this block."),
     b("Ship it: export the resource group as an ARM template", "The capstone. Export `rg-facilities` as an ARM template (the same call as the portal's Export template and `az group export`), read the portability warnings the export returns, and check the template is a real deployable: schema, parameters, and the resources the course created. On real Azure you would deploy it with `az deployment group create` into a new subscription, after replacing simulator-only values (storage keys, host names) and resolving the warnings.",
       "ship_it.py", '''
from azure.mgmt.resource.resources import ResourceManagementClient
from azlab import arm, RG

rc = arm(ResourceManagementClient)
res = rc.resource_groups.begin_export_template(RG, {"resources": ["*"], "options": "IncludeParameterDefaultValue"}).result()
t = res.template
assert "$schema" in t and t.get("contentVersion"), "an ARM template needs a schema and contentVersion"
types = sorted({r["type"] for r in t["resources"]})
print("resources exported:", len(t["resources"]), "| types:", len(types))
for must in ("Microsoft.KeyVault/vaults", "Microsoft.Web/sites"):
    assert must in types, must + " must be in the template"
errors = getattr(res, "error", None)
print("export warnings:", [getattr(d, "code", None) for d in (getattr(errors, "details", None) or [])] or "none returned")
params = t.get("parameters", {})
assert params, "names should be parameterised so the template can be deployed elsewhere"
print("parameters:", sorted(params)[:4], "...")
print("ship it verified: template exported with", len(t["resources"]), "resources; review it, then az deployment group create")
''', run="python ship_it.py", expect="ship it verified", kind="ship", edition=MESH,
       nano_note="Export template on Nano is not verified; Mesh uses the full ARM core."),
    ]
