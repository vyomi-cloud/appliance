"""A GCP API Gateway API created through the console route must be counted in the space's
cost_savings (resource_count + gcp by_provider $) and drop out again when deleted."""
import os
import sys
import time
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
try:   # the GCP space's project ID
    PROJECT = requests.get(f"{BASE}/api/gcp/catalog", timeout=60).json()["project"]
except Exception:   # appliance not up yet (collection)
    PROJECT = "vyomi-project"
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def switch_to_gcp():
    d = requests.get(f"{BASE}/api/spaces", timeout=60).json()
    sid = next((s.get("space_id") for s in d.get("spaces", []) if s.get("provider") == "gcp"), None)
    if sid:
        requests.post(f"{BASE}/api/spaces/{sid}/switch", timeout=60)
    return d.get("active_space_id")


def snap(settle=None):
    end = time.time() + 12
    while True:
        d = requests.get(f"{BASE}/api/spaces", timeout=60).json()
        cs = (d.get("active_space") or {}).get("cost_savings") or {}
        cur = cs.get("resource_count", 0), cs.get("by_provider", {}).get("gcp", 0)
        if settle is None or settle(*cur) or time.time() > end:
            return cur
        time.sleep(1)


def main():
    prev = switch_to_gcp()
    api = f"apigw-sav-{uuid.uuid4().hex[:6]}"
    root = f"{BASE}/api/gcp/apigateway/v1/projects/{PROJECT}/locations/global/apis"
    c0, g0 = snap()
    r = requests.post(root, json={"name": api}, timeout=60)
    check("create API", r.status_code < 300, r.text[:120])
    c1, g1 = snap(lambda c, g: c > c0 and g > g0)
    check(f"API raises resource_count ({c0} -> {c1})", c1 > c0)
    check(f"API raises gcp savings ({g0} -> {g1})", g1 > g0)
    r = requests.delete(f"{root}/{api}", timeout=60)
    check("delete API", r.status_code < 300, r.text[:120])
    c2, _ = snap(lambda c, g: c < c1)
    check(f"delete drops resource_count ({c1} -> {c2})", c2 < c1)
    if prev:
        requests.post(f"{BASE}/api/spaces/{prev}/switch", timeout=60)
    sys.exit(1 if failed else 0)


main()
