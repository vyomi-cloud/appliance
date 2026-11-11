"""Console-next AWS routes that had no test: messaging queues (send/peek/receive/purge/delete),
secrets (create/value/update/delete) and KMS keys (create/get/encrypt/decrypt/data-key)."""
import base64
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000") + "/api/console"
failed = False
sfx = uuid.uuid4().hex[:8]


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def req(m, p, **kw):
    return requests.request(m, BASE + p, timeout=60, **kw)


def locked(r):
    try:
        return r.status_code in (402, 403) and (r.json().get("detail") or {}).get("code") == "tier_feature_locked"
    except ValueError:
        return False


# --- messaging queues
q = "zz-conf-q-" + sfx
r = req("POST", "/messaging/queues", json={"name": q})
if locked(r):
    print("[PASS] messaging locked by tier (skipped)")
else:
    check("create queue", r.status_code == 200 and r.json().get("queue_name") == q and q in r.json().get("queue_url", ""), r.text[:200])
    r = req("POST", f"/messaging/queues/{q}/send", json={"body": "hello"})
    check("send returns message_id + md5", r.status_code == 200 and r.json().get("message_id") and len(r.json().get("md5_of_body", "")) == 32, r.text[:200])
    r = req("GET", f"/messaging/queues/{q}/peek")
    check("peek shows the message without consuming", r.status_code == 200 and r.json()["count"] == 1 and r.json()["messages"][0]["Body"] == "hello", r.text[:200])
    r = req("POST", f"/messaging/queues/{q}/receive", json={})
    m = r.json().get("messages", []) if r.status_code == 200 else []
    check("receive returns body + receipt handle", len(m) == 1 and m[0]["Body"] == "hello" and m[0].get("ReceiptHandle"), r.text[:200])
    req("POST", f"/messaging/queues/{q}/send", json={"body": "again"})
    r = req("POST", f"/messaging/queues/{q}/purge")
    check("purge is accepted", r.status_code == 200, r.text[:200])
    r = req("DELETE", f"/messaging/queues/{q}")
    check("delete queue", r.status_code == 200 and r.json().get("deleted") is True, r.text[:200])

# --- secrets
s = "zz-conf-secret-" + sfx
r = req("POST", "/secrets", json={"name": s, "secret_string": "v1"})
if locked(r):
    print("[PASS] secrets locked by tier (skipped)")
else:
    check("create secret returns Secrets Manager ARN", r.status_code == 200 and r.json().get("arn", "").startswith("arn:aws:secretsmanager:") and r.json()["arn"].split(":secret:")[1].startswith(s), r.text[:200])
    r = req("GET", f"/secrets/{s}/value")
    check("value is v1 with AWSCURRENT", r.status_code == 200 and r.json().get("secret_string") == "v1" and "AWSCURRENT" in r.json().get("stages", []), r.text[:200])
    v1 = r.json().get("version_id")
    r = req("POST", f"/secrets/{s}/value", json={"secret_string": "v2"})
    check("put new value makes a new version", r.status_code == 200 and r.json().get("version_id") not in (None, v1), r.text[:200])
    check("value reads back v2", req("GET", f"/secrets/{s}/value").json().get("secret_string") == "v2")
    check("secret detail is not a 5xx", req("GET", f"/secrets/{s}").status_code < 500)
    r = req("DELETE", f"/secrets/{s}")
    check("delete secret", r.status_code == 200 and r.json().get("deleted") is True, r.text[:200])

# --- KMS
r = req("POST", "/kms/keys", json={"description": "conf " + sfx})
if locked(r):
    print("[PASS] kms locked by tier (skipped)")
else:
    k = r.json() if r.status_code == 200 else {}
    kid = k.get("key_id", "")
    check("create key returns KMS ARN + Enabled", r.status_code == 200 and k.get("arn", "").endswith("key/" + kid) and k.get("state") == "Enabled", r.text[:200])
    g = req("GET", f"/kms/keys/{kid}").json()
    check("key detail has usage/spec/created", g.get("usage") == "ENCRYPT_DECRYPT" and g.get("spec") == "SYMMETRIC_DEFAULT" and g.get("created"), g)
    pt = base64.b64encode(b"hello kms").decode()
    r = req("POST", "/kms/encrypt", json={"key_id": kid, "plaintext": pt})
    ct = r.json().get("ciphertext_blob") if r.status_code == 200 else None
    check("encrypt returns ciphertext_blob", bool(ct) and ct != pt, r.text[:200])
    r = req("POST", "/kms/decrypt", json={"ciphertext_blob": ct})
    check("decrypt round-trips plaintext", r.status_code == 200 and r.json().get("plaintext") == pt, r.text[:200])
    r = req("POST", "/kms/data-key", json={"key_id": kid})
    check("data-key returns plaintext + ciphertext_blob", r.status_code == 200 and r.json().get("plaintext") and r.json().get("ciphertext_blob"), r.text[:200])

sys.exit(1 if failed else 0)
