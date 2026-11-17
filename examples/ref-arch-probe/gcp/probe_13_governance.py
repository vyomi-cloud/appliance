"""C13 Governance: Cloud KMS envelope protection of an approval record (google-cloud-kms, REST) with AAD enforcement, and Cloud Audit Logs entries for the run (logging read)."""
from _common import *
import base64, json, time

s = Step()
P = PROJECT
parent = f"projects/{P}/locations/{LOC}"


def key():
    from google.cloud import kms
    c = rest_client(kms.KeyManagementServiceClient)
    ring = c.create_key_ring(request={"parent": parent, "key_ring_id": f"fac-{TAG}", "key_ring": {}})
    k = c.create_crypto_key(request={"parent": ring.name, "crypto_key_id": "ledger", "crypto_key": {
        "purpose": kms.CryptoKey.CryptoKeyPurpose.ENCRYPT_DECRYPT, "rotation_period": {"seconds": 7776000}, "next_rotation_time": {"seconds": int(time.time()) + 7776000}}})
    s.c, s.key = c, k.name
    return k.name


def envelope():
    from google.api_core import exceptions as gex
    c = s.c
    aad = b"table=ledger"
    pt = json.dumps({"work_order": "WO-1", "approved_by": "duty.manager@example.com"}).encode()
    # envelope: a data key encrypts the record locally, KMS wraps the data key
    from cryptography.fernet import Fernet
    dek = Fernet.generate_key()
    blob = Fernet(dek).encrypt(pt)
    wrapped = c.encrypt(request={"name": s.key, "plaintext": dek, "additional_authenticated_data": aad}).ciphertext
    assert b"duty.manager" not in blob and dek not in wrapped
    back = c.decrypt(request={"name": s.key, "ciphertext": wrapped, "additional_authenticated_data": aad}).plaintext
    assert json.loads(Fernet(back).decrypt(blob))["work_order"] == "WO-1"
    try:
        c.decrypt(request={"name": s.key, "ciphertext": wrapped, "additional_authenticated_data": b"table=other"})
    except gex.GoogleAPICallError:
        return "DEK wrapped/unwrapped via KMS; wrong AAD refused"
    raise AssertionError("decrypt succeeded with the wrong additional_authenticated_data")


def audit():
    call("PUT", f"/v1/projects/{P}/topics/audit-{TAG}", {})
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    names = set()
    for _ in range(10):
        r = call("POST", "/v2/entries:list", {"resourceNames": [f"projects/{P}"], "filter": f'logName="projects/{P}/logs/cloudaudit.googleapis.com%2Factivity"', "pageSize": 200})
        names = {e.get("protoPayload", {}).get("methodName") for e in r.get("entries", [])}
        if any("CreateCryptoKey" in (n or "") for n in names):
            break
        time.sleep(0.5)
    assert any("CreateCryptoKey" in (n or "") for n in names), f"audit methods seen: {sorted(x for x in names if x)}"
    return "admin-activity audit: " + ", ".join(sorted(n.rsplit('.', 1)[-1] for n in names if n))[:160]


def audit_pubsub():
    r = call("POST", "/v2/entries:list", {"resourceNames": [f"projects/{P}"], "filter": f'logName="projects/{P}/logs/cloudaudit.googleapis.com%2Factivity"', "pageSize": 200})
    names = {e.get("protoPayload", {}).get("methodName") for e in r.get("entries", [])}
    want = {"google.pubsub.v1.Publisher.CreateTopic"}
    assert want <= names, f"Pub/Sub CreateTopic missing from audit log; methods seen: {sorted(x for x in names if x)}"
    return "Pub/Sub CreateTopic audited"


def audit_encrypt():
    r = call("POST", "/v2/entries:list", {"resourceNames": [f"projects/{P}"], "filter": f'logName="projects/{P}/logs/cloudaudit.googleapis.com%2Fdata_access"', "pageSize": 200})
    names = {e.get("protoPayload", {}).get("methodName") for e in r.get("entries", [])}
    if not any("Encrypt" in (n or "") for n in names):
        raise Blocked(f"NOT VERIFIED: no KMS Encrypt/Decrypt in the data_access log. Real GCP makes these opt-in (auditConfig) and this probe did not enable one; the simulator documents it generates Data Access logs only via the IAM audit-config path. no KMS Encrypt/Decrypt in data_access audit log ; methods seen: {sorted(x for x in names if x)}")
    return "data-access audit has Encrypt"


s("KMS: key ring + ENCRYPT_DECRYPT key with rotation", key)
if hasattr(s, "key"):
    s("KMS envelope: wrap data key with AAD, wrong AAD refused", envelope)
s("Cloud Audit Logs: admin-activity entries for the run (CreateCryptoKey ...)", audit)
s("Cloud Audit Logs: Pub/Sub CreateTopic is audited", audit_pubsub)
s("Cloud Audit Logs: KMS Encrypt/Decrypt in data_access log (needs audit config)", audit_encrypt)
s.finish()
