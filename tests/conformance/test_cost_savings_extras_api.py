"""Secrets Manager / KMS / Secret Manager / Cloud KMS created through the console's generic
create backend move the space's cost_savings (resource_count + that cloud's by_provider $)."""
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
    return cs.get("resource_count", 0), cs.get("by_provider", {})


def main():
    tag = uuid.uuid4().hex[:6]
    for label, provider, path, body in (
        ("AWS Secrets Manager secret", "aws", "/api/aws/extras/secretsmanager/secrets", {"name": f"sav-{tag}"}),
        ("AWS KMS key", "aws", "/api/aws/extras/kms/keys", {"name": f"sav-{tag}", "description": "savings probe"}),
        ("GCP Secret Manager secret", "gcp", "/api/gcp/extras/secretmanager/secrets", {"name": f"sav-{tag}"}),
        ("GCP Cloud KMS key", "gcp", "/api/gcp/extras/kms/keys", {"name": f"sav-{tag}"}),
    ):
        c0, p0 = snap()
        r = requests.post(BASE + path, json=body, timeout=60)
        check(f"create {label}", r.status_code < 300, r.text[:120])
        c1, p1 = snap()
        check(f"{label}: resource_count rises ({c0} -> {c1})", c1 > c0)
        check(f"{label}: {provider} savings rise ({p0.get(provider, 0)} -> {p1.get(provider, 0)})",
              p1.get(provider, 0) > p0.get(provider, 0))
    sys.exit(1 if failed else 0)


main()
