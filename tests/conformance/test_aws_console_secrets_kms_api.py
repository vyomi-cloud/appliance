"""AWS Secrets Manager / KMS console data-plane routes (/api/console/secrets/*, /api/console/kms/*):
create, describe, read/write value, delete; key create/describe, encrypt/decrypt round trip, data key."""
import base64
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def J(r):
    try:
        return r.json()
    except Exception:
        return {}


def main():
    tag = uuid.uuid4().hex[:6]
    name = f"cm-sec-{tag}"
    s = BASE + "/api/console/secrets"
    r = requests.post(s, json={"name": name, "secret_string": "v1", "description": "d"}, timeout=60)
    check("secret create", r.status_code == 200, r.text[:200])
    r = requests.get(f"{s}/{name}", timeout=60)
    check("secret describe", r.status_code == 200 and name in r.text, r.text[:200])
    r = requests.get(f"{s}/{name}/value", timeout=60)
    check("secret value v1", r.status_code == 200 and "v1" in r.text, r.text[:200])
    r = requests.post(f"{s}/{name}/value", json={"secret_string": "v2"}, timeout=60)
    check("secret put value", r.status_code == 200, r.text[:200])
    r = requests.get(f"{s}/{name}/value", timeout=60)
    check("secret value v2 after put", r.status_code == 200 and "v2" in r.text, r.text[:200])
    r = requests.delete(f"{s}/{name}", timeout=60)
    check("secret delete", r.status_code == 200, r.text[:200])
    r = requests.get(f"{s}/{name}/value", timeout=60)
    check("deleted secret value is refused", r.status_code >= 400, r.status_code)
    r = requests.post(s, json={}, timeout=60)
    check("secret create without name is 400", r.status_code == 400, r.status_code)

    k = BASE + "/api/console/kms"
    r = requests.post(f"{k}/keys", json={"description": f"cm-key-{tag}"}, timeout=60)
    check("kms create key", r.status_code == 200, r.text[:200])
    kj = J(r)
    kid = kj.get("key_id") or kj.get("KeyId") or (kj.get("key") or {}).get("key_id") or kj.get("id") or ""
    check("kms key id returned", bool(kid), kj)
    r = requests.get(f"{k}/keys", timeout=60)
    check("kms list contains key", r.status_code == 200 and kid in r.text, r.text[:200])
    r = requests.get(f"{k}/keys/{kid}", timeout=60)
    check("kms describe key", r.status_code == 200 and kid in r.text, r.text[:200])
    pt = base64.b64encode(b"hello vyomi").decode()
    r = requests.post(f"{k}/encrypt", json={"key_id": kid, "plaintext": pt}, timeout=60)
    ej = J(r)
    check("kms encrypt", r.status_code == 200 and ej, r.text[:200])
    blob = ej.get("ciphertext_blob") or ej.get("CiphertextBlob") or ""
    check("kms ciphertext returned", bool(blob), ej)
    r = requests.post(f"{k}/decrypt", json={"ciphertext_blob": blob}, timeout=60)
    check("kms decrypt round trip", r.status_code == 200 and (pt in r.text or "hello vyomi" in r.text), r.text[:200])
    r = requests.post(f"{k}/data-key", json={"key_id": kid, "key_spec": "AES_256"}, timeout=60)
    check("kms data key", r.status_code == 200 and len(r.text) > 40, r.text[:200])
    check("kms encrypt without key_id is 400", requests.post(f"{k}/encrypt", json={}, timeout=60).status_code == 400)
    check("kms decrypt without blob is 400", requests.post(f"{k}/decrypt", json={}, timeout=60).status_code == 400)
    check("kms data-key without key_id is 400", requests.post(f"{k}/data-key", json={}, timeout=60).status_code == 400)
    sys.exit(1 if failed else 0)


main()
