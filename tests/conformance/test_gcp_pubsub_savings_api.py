"""GCP Pub/Sub topics and subscriptions (backed by the Pub/Sub emulator) must be counted in the
space's cost_savings (resource_count + gcp by_provider $) when created through the console routes
or the PUT calls the official client libraries / gcloud make, and drop out again when deleted."""
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
    """Savings recompute on the space tick after a write; poll until `settle(count, usd)` holds."""
    end = time.time() + 12
    while True:
        d = requests.get(f"{BASE}/api/spaces", timeout=60).json()
        cs = (d.get("active_space") or {}).get("cost_savings") or {}
        cur = cs.get("resource_count", 0), cs.get("by_provider", {}).get("gcp", 0)
        if settle is None or settle(*cur) or time.time() > end:
            return cur
        time.sleep(1)


def main():
    prev_space = switch_to_gcp()
    tag = uuid.uuid4().hex[:6]
    ps = f"{BASE}/api/gcp/pubsub/v1/projects/{PROJECT}"
    c0, g0 = snap()
    topic = f"ps-sav-{tag}"
    r = requests.post(f"{ps}/topics", json={"topicId": topic}, timeout=60)
    check("console create topic", r.status_code < 300, r.text[:120])
    c1, g1 = snap(lambda c, g: c > c0 and g > g0)
    check(f"topic raises resource_count ({c0} -> {c1})", c1 > c0)
    check(f"topic raises gcp savings ({g0} -> {g1})", g1 > g0)

    topic2 = f"ps-sav2-{tag}"
    r = requests.put(f"{ps}/topics/{topic2}", json={}, timeout=60)
    check("PUT create topic (client-library style)", r.status_code < 300, r.text[:120])
    c2, _ = snap(lambda c, g: c > c1)
    check(f"PUT topic raises resource_count ({c1} -> {c2})", c2 > c1)

    sub = f"ps-sub-{tag}"
    r = requests.put(f"{ps}/subscriptions/{sub}", json={"topic": f"projects/{PROJECT}/topics/{topic2}"}, timeout=60)
    check("PUT create subscription", r.status_code < 300, r.text[:120])
    c3, _ = snap(lambda c, g: c > c2)
    check(f"subscription raises resource_count ({c2} -> {c3})", c3 > c2)

    for path in (f"subscriptions/{sub}", f"topics/{topic2}", f"topics/{topic}"):
        r = requests.delete(f"{ps}/{path}", timeout=60)
        check(f"DELETE {path.split('/')[0]}", r.status_code < 300, f"{r.status_code} {r.text[:80]}")
    c4, _ = snap(lambda c, g: c <= c0)
    check(f"deleting them drops resource_count ({c3} -> {c4})", c4 <= c0, c0)
    if prev_space:
        requests.post(f"{BASE}/api/spaces/{prev_space}/switch", timeout=60)
    sys.exit(1 if failed else 0)


main()
