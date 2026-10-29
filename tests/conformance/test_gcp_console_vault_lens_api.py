"""GCP Secret Manager and Cloud KMS lens routes (/api/console/gcp-secrets/*, /api/console/gcp-kms/*):
create, list, describe, versioned value, encrypt/decrypt round trip, data key, delete."""
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


def call(method, path, **kw):
    return requests.request(method, BASE + path, timeout=60, **kw)


def main():
    tag = uuid.uuid4().hex[:6]
    name = f"lens-sec-{tag}"
    sp = "/api/console/gcp-secrets/secrets"
    r = call("POST", sp, json={"name": name, "secret_string": "one", "description": "d"})
    check("create secret", r.status_code < 300, r.text[:150])
    r = call("GET", sp)
    names = [str(s.get("name") or s.get("Name")) for s in (r.json().get("secrets") or r.json().get("items") or [])] if r.ok else []
    check("secret listed", any(name in n for n in names), r.text[:200])
    r = call("GET", f"{sp}/{name}")
    check("describe secret", r.ok and name in r.text, r.text[:150])
    r = call("POST", f"{sp}/{name}/value", json={"secret_string": "two"})
    check("add secret version", r.status_code < 300, r.text[:150])
    r = call("GET", f"{sp}/{name}/value")
    check("value is newest version", r.ok and "two" in r.text, r.text[:150])
    r = call("DELETE", f"{sp}/{name}")
    check("delete secret", r.status_code < 300, r.text[:150])
    r = call("GET", f"{sp}/{name}")
    check("deleted secret no longer describes", r.status_code >= 400, r.text[:150])

    kp = "/api/console/gcp-kms/keys"
    r = call("POST", kp, json={"description": f"lens-{tag}"})
    check("create KMS key", r.status_code < 300, r.text[:150])
    body = r.json() if r.ok else {}
    kid = body.get("key_id") or body.get("KeyId") or (body.get("key") or {}).get("key_id") or ""
    check("key has an id", bool(kid), body)
    r = call("GET", kp)
    check("key listed", r.ok and kid and kid in r.text, r.text[:200])
    r = call("GET", f"{kp}/{kid}")
    check("describe key", r.ok and kid in r.text, r.text[:150])
    r = call("POST", "/api/console/gcp-kms/encrypt", json={"key_id": kid, "plaintext": "aGVsbG8="})
    check("encrypt", r.ok, r.text[:150])
    blob = r.json().get("ciphertext_blob", "") if r.ok else ""
    r = call("POST", "/api/console/gcp-kms/decrypt", json={"ciphertext_blob": blob, "key_id": kid})
    check("decrypt round trip", r.ok and "aGVsbG8=" in r.text, r.text[:150])
    r = call("POST", "/api/console/gcp-kms/data-key", json={"key_id": kid})
    check("data key", r.ok, r.text[:150])
    r = call("POST", "/api/console/gcp-kms/encrypt", json={"plaintext": "x"})
    check("encrypt without key_id is 400", r.status_code == 400, r.status_code)
    sys.exit(1 if failed else 0)


main()
