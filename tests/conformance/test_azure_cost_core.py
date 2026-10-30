"""Unit tests for core/azure_cost_core.py (run: python3 tests/conformance/test_azure_cost_core.py)."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_cost_core as cost  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)   # day 30 of a 31-day month → mtd fraction 30/31

# ── seed real inventory through the ARM core, so cost queries read the SAME state ──
arm = AzureArm()
SUB = arm.state and None or None  # noqa (placeholder to keep lints quiet about unused import style)
P = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg1/providers"
arm.handle("PUT", f"{P}/Microsoft.Compute/virtualMachines/vm1", {}, {"location": "eastus", "properties": {"hardwareProfile": {"vmSize": "Standard_D2s_v5"}}})
arm.handle("PUT", f"{P}/Microsoft.Storage/storageAccounts/uicstorage", {}, {"location": "eastus"})
SUB = "00000000-0000-0000-0000-cloudlearn01"
ST = arm.state

rows = cost._collect_resource_rows(ST, SUB)
check("real inventory feeds cost rows (vm + storage)", sorted(r["full_type"] for r in rows) ==
      ["microsoft.compute/virtualmachines", "microsoft.storage/storageaccounts"], rows)
vm_row = next(r for r in rows if r["full_type"] == "microsoft.compute/virtualmachines")
check("VM priced by its real vmSize (Standard_D2s_v5 = $0.096/hr)", vm_row["monthly_usd"] == round(0.096 * 730, 2), vm_row)

# ── Microsoft.CostManagement/query ──────────────────────────────────────────────
r = cost.dispatch_costmanagement(ST, "GET", SUB, None, ["query"], {}, {})
check("query requires POST", r["status"] == 405)
r = cost.dispatch_costmanagement(ST, "POST", SUB, None, ["query"], {"dataset": {}}, {}, )
total_row = r["body"]["properties"]["rows"][0]
check("ungrouped query totals both resources, MTD-scaled", r["status"] == 200 and total_row[1] == "USD" and total_row[0] > 0, r["body"])

r = cost.run_cost_query(ST, SUB, None, {"dataset": {"grouping": [{"name": "ServiceName"}]}}, NOW)
cols, vals = r["properties"]["columns"], r["properties"]["rows"]
check("grouped query groups by ServiceName with 2 real services", cols[1]["name"] == "ServiceName" and len(vals) == 2, r["properties"])
check("grouped rows sum to the ungrouped total", round(sum(v[0] for v in vals), 4) ==
      round(cost.run_cost_query(ST, SUB, None, {"dataset": {}}, NOW)["properties"]["rows"][0][0], 4))

filtered = cost.run_cost_query(ST, SUB, None, {"dataset": {"filter": {"dimensions": {"name": "ServiceName", "operator": "In", "values": ["Storage"]}}}}, NOW)
check("filter narrows the query to one service", len(filtered["properties"]["rows"]) == 1 and filtered["properties"]["rows"][0][0] > 0, filtered)

# ── Microsoft.Consumption/budgets ───────────────────────────────────────────────
r = cost.dispatch_consumption(ST, "PUT", SUB, None, ["budgets", "monthly-budget"], {"properties": {"amount": 1, "notifications": {
    "Actual_GreaterThan_80": {"enabled": True, "threshold": 80, "thresholdType": "Actual"}}}}, {})
check("create budget → 201 with currentSpend/forecastSpend", r["status"] == 201 and "currentSpend" in r["body"]["properties"]
      and "forecastSpend" in r["body"]["properties"], r["body"])
check("budget amount $1 is exceeded by real inventory spend → over 80%",
      r["body"]["properties"]["currentSpend"]["amount"] / r["body"]["properties"]["amount"] * 100 > 80, r["body"])
check("update (PUT again) → 200", cost.dispatch_consumption(ST, "PUT", SUB, None, ["budgets", "monthly-budget"], {"properties": {"amount": 2}}, {})["status"] == 200)
check("list budgets", len(cost.dispatch_consumption(ST, "GET", SUB, None, ["budgets"], {}, {})["body"]["value"]) == 1)
check("get missing budget → 404", cost.dispatch_consumption(ST, "GET", SUB, None, ["budgets", "none"], {}, {})["status"] == 404)
check("PATCH missing budget → 404", cost.dispatch_consumption(ST, "PATCH", SUB, None, ["budgets", "none"], {"properties": {}}, {})["status"] == 404)
check("create requires amount", cost.dispatch_consumption(ST, "PUT", SUB, None, ["budgets", "bad"], {"properties": {}}, {})["status"] == 400)
check("unsupported Consumption type → 404", cost.dispatch_consumption(ST, "GET", SUB, None, ["bogus"], {}, {})["status"] == 404)

# ── Microsoft.CostManagement/alerts (derived from the over-budget budget above) ─
r = cost.dispatch_costmanagement(ST, "GET", SUB, None, ["alerts"], {}, {}, )
alerts = r["body"]["value"]
check("an alert is derived for the over-threshold budget", len(alerts) == 1 and alerts[0]["properties"]["status"] == "Active", alerts)
alert_name = alerts[0]["name"]
r = cost.dispatch_costmanagement(ST, "POST", SUB, None, ["alerts", alert_name, "dismiss"], {}, {})
check("dismiss action → Dismissed", r["status"] == 200 and r["body"]["properties"]["status"] == "Dismissed")
after = cost.dispatch_costmanagement(ST, "GET", SUB, None, ["alerts"], {}, {})["body"]["value"]
check("dismissal persists across list calls", after[0]["properties"]["status"] == "Dismissed", after)
r = cost.dispatch_costmanagement(ST, "POST", SUB, None, ["alerts", alert_name, "reactivate"], {}, {})
check("reactivate action → Active", r["body"]["properties"]["status"] == "Active")

cost.dispatch_consumption(ST, "DELETE", SUB, None, ["budgets", "monthly-budget"], {}, {})
check("deleting the budget removes its alert", cost.dispatch_costmanagement(ST, "GET", SUB, None, ["alerts"], {}, {})["body"]["value"] == [])

# ── Microsoft.CostManagement/exports ────────────────────────────────────────────
r = cost.dispatch_costmanagement(ST, "PUT", SUB, None, ["exports", "weekly-export"], {"properties": {"format": "Csv"}}, {})
check("create export → 201 with defaults filled in", r["status"] == 201 and r["body"]["properties"]["definition"]["type"] == "ActualCost", r["body"])
r = cost.dispatch_costmanagement(ST, "POST", SUB, None, ["exports", "weekly-export", "run"], {}, {})
check("run export → run history", r["status"] == 200 and r["body"]["properties"]["runHistory"]["value"][0]["status"] == "Completed", r["body"])
r = cost.dispatch_costmanagement(ST, "GET", SUB, None, ["exports", "weekly-export"], {}, {})
check("export remembers its last run cost", r["body"]["properties"]["lastRunCost"]["amount"] >= 0, r["body"])
check("delete export → 200, then 204", cost.dispatch_costmanagement(ST, "DELETE", SUB, None, ["exports", "weekly-export"], {}, {})["status"] == 200
      and cost.dispatch_costmanagement(ST, "DELETE", SUB, None, ["exports", "weekly-export"], {}, {})["status"] == 204)

# ── through the Nano ARM wire end to end ────────────────────────────────────────
CM = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/providers/Microsoft.CostManagement"
CO = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/providers/Microsoft.Consumption"
r = arm.handle("PUT", f"{CO}/budgets/nano-budget", {}, {"properties": {"amount": 500}})
check("Nano ARM: budget create", r["status"] == 201, r)
r = arm.handle("POST", f"{CM}/query", {}, {"dataset": {}})
check("Nano ARM: cost query", r["status"] == 200 and "rows" in r["body"]["properties"], r)
r = arm.handle("GET", f"{CO}/budgets", {}, None)
check("Nano ARM: list budgets", r["status"] == 200 and len(r["body"]["value"]) == 1, r)
r = arm.handle("DELETE", f"{CO}/budgets/nano-budget", {}, None)
check("Nano ARM: delete budget", r["status"] == 200, r)

print(f"{PASS} passed, {FAIL} failed")
assert FAIL == 0

if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
