"""CloudSim routes: /api/cloudsim/current, /summary and /reconcile answer with the documented
shape (or the tier-lock body on the Free tier, never a 5xx)."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)}")
    failed = failed or not ok


def locked(r):
    try:
        return r.status_code in (402, 403) and (r.json().get("detail") or {}).get("code") == "tier_feature_locked"
    except ValueError:
        return False


for path in ("/api/cloudsim/current", "/api/cloudsim/summary"):
    if path.endswith("current"):
        r = requests.get(BASE + "/api/cloudsim/current", timeout=60)
    else:
        r = requests.get(BASE + "/api/cloudsim/summary", timeout=60)
    ok = (r.status_code == 200 and isinstance(r.json(), dict)) or locked(r)
    check(f"GET {path} returns an object or the tier-lock body", ok, f"{r.status_code} {r.text[:120]}")
    check(f"GET {path} is not a 5xx", r.status_code < 500, r.status_code)

r = requests.post(BASE + "/api/cloudsim/reconcile", timeout=60)
body = r.json() if r.status_code == 200 else {}
check("POST /api/cloudsim/reconcile completes", r.status_code == 200 and "summary" in body, r.text[:120])
check("reconcile reports last_reconcile_at", bool(body.get("last_reconcile_at")), body)
check("reconcile summary lists spaces", (body.get("summary") or {}).get("spaces", 0) >= 1, body)

sys.exit(1 if failed else 0)
