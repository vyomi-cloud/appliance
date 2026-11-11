"""Console RDS SQL routes (/api/console/rds/*), capabilities/profile/host routes and the
cost-budget lifecycle (/api/runtime/budgets*), tenants list/active."""
import os
import sys
import uuid

import requests

BASE = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
failed = False


def check(name, ok, extra=""):
    global failed
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' ' + str(extra)[:200]}")
    failed = failed or not ok


def call(method, path, **kw):
    return requests.request(method, BASE + path, timeout=60, **kw)


def main():
    # --- RDS console
    r = call("GET", "/api/console/rds/databases")
    dbs = r.json().get("databases", []) if r.ok else []
    check("rds databases listed with endpoint+status", bool(dbs) and all(d.get("endpoint") and d.get("status") for d in dbs), r.text)
    if dbs:
        r = call("GET", f"/api/console/rds/databases/{dbs[0]['db_instance_identifier']}/schema")
        check("rds schema returns tables list", r.ok and isinstance(r.json().get("tables"), list), r.text)
    r = call("POST", "/api/console/rds/execute", json={"sql": "select 1 as x"})
    j = r.json() if r.ok else {}
    check("rds execute select", j.get("ok") and j.get("columns") == ["x"] and j.get("rows") == [[1]], r.text)
    check("rds execute without sql -> 400", call("POST", "/api/console/rds/execute", json={}).status_code == 400)
    # --- capabilities / profile / host
    r = call("GET", "/api/console/capabilities")
    j = r.json() if r.ok else {}
    check("capabilities lists aws lens + widgets", "aws" in j.get("cloud_lenses", []) and "sql-console" in j.get("widgets", {}), r.text)
    r = call("GET", "/api/runtime/profile")
    check("profile has allowed_clouds", r.ok and "aws" in r.json().get("allowed_clouds", []), r.text)
    r = call("GET", "/api/host/cpu")
    check("host cpu has cpu_count", r.ok and r.json().get("cpu_count", 0) >= 1, r.text)
    # --- tenants
    r = call("GET", "/api/tenants")
    j = r.json() if r.ok else {}
    check("tenants lists active tenant", any(t["tenant_id"] == j.get("active_tenant_id") for t in j.get("tenants", [])), r.text)
    r = call("GET", "/api/tenants/active")
    check("active tenant has id", r.ok and r.json().get("tenant_id") == j.get("active_tenant_id"), r.text)
    # --- budgets
    name = "b-" + uuid.uuid4().hex[:6]
    r = call("POST", "/api/runtime/budgets", json={"name": name, "amount_usd": 42, "alert_thresholds": [90, 50, 50]})
    b = r.json().get("budget", {}) if r.ok else {}
    bid = b.get("budget_id", "")
    check("create budget", bid.startswith("budget-") and b.get("amount_usd") == 42.0 and b.get("alert_thresholds") == [50, 90], r.text)
    r = call("GET", "/api/runtime/budgets")
    row = next((x for x in r.json().get("budgets", []) if x["budget_id"] == bid), {}) if r.ok else {}
    check("list budgets shows spend + utilization", row.get("name") == name and "utilization_pct" in row, row)
    r = call("GET", f"/api/runtime/budgets/{bid}/status")
    check("budget status", r.ok and r.json().get("budget_id") == bid and r.json().get("thresholds_breached") == [], r.text)
    r = call("DELETE", f"/api/runtime/budgets/{bid}")
    check("delete budget", r.ok and r.json().get("deleted") is True, r.text)
    check("deleted budget status -> 404", call("GET", f"/api/runtime/budgets/{bid}/status").status_code == 404)
    check("delete missing budget -> 404", call("DELETE", f"/api/runtime/budgets/{bid}").status_code == 404)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
