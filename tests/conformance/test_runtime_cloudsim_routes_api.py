"""Cover /api/runtime/profile and /api/cloudsim/{current,summary,reconcile}: they answer with the
documented shapes (cost_simulation is Pro-tier: Free must say so with a 403, never a 5xx)."""
import os
import sys

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def main():
    r = requests.get(f"{BASE}/api/runtime/profile", timeout=30)
    j = r.json() if r.status_code == 200 else {}
    check("runtime/profile 200", r.status_code == 200)
    check("runtime/profile allowed_clouds covers aws,gcp,azure",
          {"aws", "gcp", "azure"} <= set(j.get("allowed_clouds") or []))
    check("runtime/profile has restricted flag", isinstance(j.get("restricted"), bool))

    for p in ("current", "summary"):
        r = requests.get(f"{BASE}/api/cloudsim/{p}", timeout=30)
        ok = r.status_code == 200
        if r.status_code == 403:
            d = r.json().get("detail") or {}
            ok = d.get("code") == "tier_feature_locked" and d.get("feature") == "cost_simulation"
        check(f"cloudsim/{p} is 200 or a tier_feature_locked 403 (got {r.status_code})", ok)

    r = requests.post(f"{BASE}/api/cloudsim/reconcile", timeout=30)
    j = r.json() if r.status_code == 200 else {}
    check("cloudsim/reconcile 200", r.status_code == 200)
    s = j.get("summary") or {}
    check("reconcile summary has spaces/active_space_id/max_spaces",
          all(k in s for k in ("spaces", "active_space_id", "max_spaces")) and s["spaces"] >= 1)
    check("reconcile has last_reconcile_at", bool(j.get("last_reconcile_at")))
    sys.exit(1 if failed else 0)


main()
