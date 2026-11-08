"""Cost budget routes (/api/runtime/budgets*, /api/runtime/budget/enable|disable):
create, list, status, delete, 404s, and the host-clamp gate toggle guard."""
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


def J(r):
    try:
        return r.json()
    except Exception:
        return {}


def main():
    b = BASE + "/api/runtime/budgets"
    name = f"cm-budget-{uuid.uuid4().hex[:6]}"
    r = requests.post(b, json={"name": name, "amount_usd": 250, "alert_thresholds": [80, 50, 50, 100]}, timeout=60)
    bud = J(r).get("budget", {})
    bid = bud.get("budget_id", "")
    check("budget create", r.status_code == 200 and bid.startswith("budget-"), r.text[:200])
    check("thresholds sorted and de-duplicated", bud.get("alert_thresholds") == [50, 80, 100], bud)
    check("budget keeps amount/period", bud.get("amount_usd") == 250 and bud.get("period") == "monthly", bud)
    r = requests.get(b, timeout=60)
    row = next((x for x in J(r).get("budgets", []) if x.get("budget_id") == bid), None)
    check("budget listed with spend and utilization",
          r.status_code == 200 and row is not None and "current_spend_usd" in row and "utilization_pct" in row, r.text[:300])
    r = requests.get(f"{b}/{bid}/status", timeout=60)
    st = J(r)
    check("budget status shape", r.status_code == 200 and st.get("name") == name and st.get("amount_usd") == 250
          and isinstance(st.get("thresholds_breached"), list) and isinstance(st.get("alerts_triggered"), list), r.text[:300])
    check("status breached thresholds match utilization",
          st.get("thresholds_breached") == [t for t in (50, 80, 100) if st.get("utilization_pct", 0) >= t], st)
    check("status of unknown budget is 404", requests.get(f"{b}/budget-nope/status", timeout=60).status_code == 404)
    check("delete unknown budget is 404", requests.delete(f"{b}/budget-nope", timeout=60).status_code == 404)
    r = requests.delete(f"{b}/{bid}", timeout=60)
    check("budget delete", r.status_code == 200 and J(r).get("deleted") is True, r.text[:200])
    check("deleted budget gone from list",
          all(x.get("budget_id") != bid for x in J(requests.get(b, timeout=60)).get("budgets", [])))
    check("status after delete is 404", requests.get(f"{b}/{bid}/status", timeout=60).status_code == 404)

    # Gate toggle: admin-only and refused in appliance mode. Never leave the gate bypassed.
    r = requests.post(BASE + "/api/runtime/budget/disable", timeout=60)
    check("budget/disable is guarded or toggles", r.status_code in (200, 401, 403), r.text[:200])
    r2 = requests.post(BASE + "/api/runtime/budget/enable", timeout=60)
    check("budget/enable is guarded or restores", r2.status_code in (200, 401, 403), r2.text[:200])
    if r.status_code == 200:
        check("enable reports gate not bypassed", J(r2).get("bypassed") is False, r2.text[:200])
    sys.exit(1 if failed else 0)


main()
