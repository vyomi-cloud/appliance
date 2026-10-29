"""AWS Secrets Manager / KMS / IAM created through the console's own routes (Vault-backed
secrets + keys, in-memory IAM) move the space's cost_savings (resource_count + AWS $ for the
billable ones), and the secrets grid returns real Created / Encryption key values."""
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


def snap():
    d = requests.get(f"{BASE}/api/spaces", timeout=60).json()
    cs = (d.get("active_space") or {}).get("cost_savings") or {}
    return cs.get("resource_count", 0), cs.get("by_provider", {}).get("aws", 0)


def main():
    tag = uuid.uuid4().hex[:6]
    for label, path, body, billable in (
        ("Secrets Manager secret", "/api/aws/secrets", {"name": f"sav-{tag}", "value": "x"}, True),
        ("KMS key", "/api/aws/kms/keys", {"name": f"sav-{tag}", "description": "probe"}, True),
        ("IAM user", "/api/iam/users", {"user_name": f"sav-{tag}"}, False),
        ("IAM role", "/api/iam/roles", {"role_name": f"sav-{tag}"}, False),
    ):
        c0, d0 = snap()
        r = requests.post(BASE + path, json=body, timeout=60)
        check(f"create {label}", r.status_code < 300, r.text[:120])
        c1, d1 = snap()
        check(f"{label}: resource_count rises ({c0} -> {c1})", c1 > c0)
        if billable:
            check(f"{label}: aws savings rise ({d0} -> {d1})", d1 > d0)

    items = requests.get(f"{BASE}/api/aws/secrets", timeout=60).json().get("items", [])
    row = next((i for i in items if i["name"] == f"sav-{tag}"), {})
    check("secret row has Created", bool(row.get("created")), row)
    check("secret row has Encryption key", bool(row.get("kms_key_id")), row)
    requests.delete(f"{BASE}/api/aws/secrets/sav-{tag}", timeout=60)
    sys.exit(1 if failed else 0)


main()
