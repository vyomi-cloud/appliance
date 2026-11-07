"""Read-only runtime/cloudsim routes the console dashboards call: cloudsim current + summary,
runtime disk-health, service-metrics, host-distribution, scaffolding/supported."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)[:300]}")
    failed = failed or not ok


def get(path):
    r = requests.get(BASE + path, timeout=60)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, None


for path in ("/api/cloudsim/current", "/api/cloudsim/summary", "/api/runtime/disk-health",
             "/api/runtime/service-metrics", "/api/runtime/host-distribution",
             "/api/scaffolding/supported"):
    s, b = get(path)
    locked = s == 403 and isinstance(b, dict) and b.get("detail", {}).get("code") == "tier_feature_locked"
    check(f"GET {path} -> 200 JSON, or the tier-locked message", (s == 200 and isinstance(b, (dict, list))) or locked, (s, b))

sys.exit(1 if failed else 0)
