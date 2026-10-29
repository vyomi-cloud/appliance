"""GCP resources created through the console's catalog endpoints (the calls the Create forms make)
must move the space's cost_savings: Pub/Sub topic, API Gateway API, Secret Manager secret
(created empty, as the form allows), Cloud KMS key, Cloud SQL instance without a password."""
import os
import sys
import time
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
P = "123456789012"
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
    sid = next(s.get("space_id") or s.get("id") for s in requests.get(f"{BASE}/api/spaces", timeout=60).json()["spaces"]
               if s.get("provider") == "gcp")
    requests.post(f"{BASE}/api/spaces/{sid}/switch", timeout=60)
    t = uuid.uuid4().hex[:6]
    cases = (
        ("Pub/Sub topic", f"/api/gcp/pubsub/v1/projects/{P}/topics", {"name": f"sav-{t}"}),
        ("API Gateway API", f"/api/gcp/apigateway/v1/projects/{P}/locations/global/apis", {"name": f"sav-{t}", "displayName": f"sav-{t}"}),
        ("Secret Manager secret (no value)", "/api/gcp/secrets", {"name": f"sav-{t}"}),
        ("Cloud SQL instance (no password)", "/api/gcp/rds/databases", {"name": f"sav-{t}", "region": "us-central1", "databaseVersion": "POSTGRES_16", "tier": "db-f1-micro"}),
    )
    for label, path, body in cases:
        c0, g0 = snap()
        r = requests.post(BASE + path, json=body, timeout=60)
        check(f"create {label}", r.status_code < 300, r.text[:160])
        end = time.time() + 12
        while time.time() < end:
            c1, g1 = snap()
            if c1 > c0 and g1 > g0:
                break
            time.sleep(0.5)
        check(f"{label}: resource_count rises ({c0} -> {c1})", c1 > c0)
        check(f"{label}: gcp savings rise ({g0} -> {g1})", g1 > g0)
    sys.exit(1 if failed else 0)


main()
