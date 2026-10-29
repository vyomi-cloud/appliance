"""GCP Secret Manager secrets and Cloud KMS keys created through the console's own CRUD routes
(/api/gcp/secrets, /api/gcp/kms/keys) must list with a Created time and the real latest version,
and must move the space's cost_savings (resource_count + gcp by_provider $)."""
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
    return cs.get("resource_count", 0), cs.get("by_provider", {}).get("gcp", 0)


def main():
    tag = uuid.uuid4().hex[:6]
    c0, g0 = snap()
    name = f"vsec-{tag}"
    r = requests.post(f"{BASE}/api/gcp/secrets", json={"name": name, "secret_value": "s3cret-one"}, timeout=60)
    check("create secret", r.status_code < 300, r.text[:120])
    rows = requests.get(f"{BASE}/api/gcp/secrets", timeout=60).json()["items"]
    row = next((x for x in rows if x["name"] == name), {})
    created = str(row.get("created") or "")
    check(f"secret Created filled ({created})", created not in ("", "-", "—", "None", "null"))
    check("secret latest_version is 1", str(row.get("latest_version")) == "1", row)
    got = requests.get(f"{BASE}/api/gcp/secrets/{name}", timeout=60).json()
    check("secret value is the one submitted (secret_value honoured)", got.get("value") == "s3cret-one", got)
    c1, g1 = snap()
    check(f"secret raises resource_count ({c0} -> {c1})", c1 > c0)
    check(f"secret raises gcp savings ({g0} -> {g1})", g1 > g0)

    key = f"vkey-{tag}"
    r = requests.post(f"{BASE}/api/gcp/kms/keys", json={"name": key}, timeout=60)
    check("create KMS key", r.status_code < 300, r.text[:120])
    c2, g2 = snap()
    check(f"key raises resource_count ({c1} -> {c2})", c2 > c1)
    check(f"key raises gcp savings ({g1} -> {g2})", g2 > g1)

    requests.delete(f"{BASE}/api/gcp/secrets/{name}", timeout=60)
    requests.delete(f"{BASE}/api/gcp/kms/keys/{key}", timeout=60)
    sys.exit(1 if failed else 0)


main()
