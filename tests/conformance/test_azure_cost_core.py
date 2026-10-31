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

# ── Microsoft.BillingBenefits/savingsPlanOrders ─────────────────────────────────
r = cost.dispatch_billingbenefits(ST, "PUT", SUB, ["savingsPlanOrders", "sp1"],
                                   {"properties": {"commitment": {"amount": 0.0001, "currency": "USD", "grain": "Hourly"}}}, {})
check("create savings plan → 201 with utilization", r["status"] == 201 and "utilization" in r["body"]["properties"], r["body"])
check("tiny commitment vs real VM spend → ~100% utilized", r["body"]["properties"]["utilization"] == 100.0, r["body"])
check("defaults filled in (term/scope/renew/expiry)", r["body"]["properties"]["term"] == "P1Y"
      and r["body"]["properties"]["appliedScopeType"] == "Shared" and r["body"]["properties"]["renew"] is False
      and r["body"]["properties"]["expiryDateTime"], r["body"])
r = cost.dispatch_billingbenefits(ST, "PUT", SUB, ["savingsPlanOrders", "sp2"],
                                   {"properties": {"commitment": {"amount": 1000000, "currency": "USD", "grain": "Hourly"}}}, {})
check("huge commitment vs real VM spend → ~0% utilized", r["body"]["properties"]["utilization"] == 0.0, r["body"])
check("list savings plans", len(cost.dispatch_billingbenefits(ST, "GET", SUB, ["savingsPlanOrders"], {}, {})["body"]["value"]) == 2)
check("get missing savings plan → 404", cost.dispatch_billingbenefits(ST, "GET", SUB, ["savingsPlanOrders", "none"], {}, {})["status"] == 404)
check("create requires commitment.amount", cost.dispatch_billingbenefits(ST, "PUT", SUB, ["savingsPlanOrders", "bad"], {"properties": {}}, {})["status"] == 400)
check("unsupported BillingBenefits type → 404", cost.dispatch_billingbenefits(ST, "GET", SUB, ["bogus"], {}, {})["status"] == 404)
check("delete savings plan → 200, then 204", cost.dispatch_billingbenefits(ST, "DELETE", SUB, ["savingsPlanOrders", "sp2"], {}, {})["status"] == 200
      and cost.dispatch_billingbenefits(ST, "DELETE", SUB, ["savingsPlanOrders", "sp2"], {}, {})["status"] == 204)

# ── Hybrid Benefit (licenseType discount on VM cost) ────────────────────────────
arm.handle("PUT", f"{P}/Microsoft.Compute/virtualMachines/vm-win", {}, {"location": "eastus",
    "properties": {"hardwareProfile": {"vmSize": "Standard_D2s_v5"}, "licenseType": "Windows_Server"}})
win_row = next(r for r in cost._collect_resource_rows(ST, SUB) if r["name"] == "vm-win")
check("Hybrid Benefit discounts the VM's monthly cost", win_row["hybrid_benefit"] is True
      and win_row["monthly_usd"] == round(vm_row["monthly_usd"] * 0.8, 2), win_row)

# ── Microsoft.Capacity/reservationOrders ────────────────────────────────────────
r = cost.dispatch_capacity(ST, "PUT", SUB, ["reservationOrders", "res1"],
                            {"properties": {"skuName": "Standard_D2s_v5", "quantity": 0.0001}}, {})
check("create reservation → 201 with utilization", r["status"] == 201 and "utilization" in r["body"]["properties"], r["body"])
check("tiny reservation vs real VM spend of the same sku → ~100% utilized", r["body"]["properties"]["utilization"] == 100.0, r["body"])
check("defaults filled in (term/scope/renew/expiry)", r["body"]["properties"]["term"] == "P1Y"
      and r["body"]["properties"]["appliedScopeType"] == "Shared" and r["body"]["properties"]["renew"] is False
      and r["body"]["properties"]["expiryDateTime"], r["body"])
r = cost.dispatch_capacity(ST, "PUT", SUB, ["reservationOrders", "res2"],
                            {"properties": {"skuName": "Standard_D2s_v5", "quantity": 1000000}}, {})
check("huge reservation vs real VM spend of the same sku → ~0% utilized", r["body"]["properties"]["utilization"] == 0.0, r["body"])
r = cost.dispatch_capacity(ST, "PUT", SUB, ["reservationOrders", "res-other-sku"],
                            {"properties": {"skuName": "Standard_B2s", "quantity": 1}}, {})
check("reservation for a sku with no matching VMs → 0% utilized", r["body"]["properties"]["utilization"] == 0.0, r["body"])
check("list reservations", len(cost.dispatch_capacity(ST, "GET", SUB, ["reservationOrders"], {}, {})["body"]["value"]) == 3)
check("get missing reservation → 404", cost.dispatch_capacity(ST, "GET", SUB, ["reservationOrders", "none"], {}, {})["status"] == 404)
check("create requires skuName/quantity", cost.dispatch_capacity(ST, "PUT", SUB, ["reservationOrders", "bad"], {"properties": {}}, {})["status"] == 400)
check("unsupported Capacity type → 404", cost.dispatch_capacity(ST, "GET", SUB, ["bogus"], {}, {})["status"] == 404)
check("delete reservation → 200, then 204", cost.dispatch_capacity(ST, "DELETE", SUB, ["reservationOrders", "res2"], {}, {})["status"] == 200
      and cost.dispatch_capacity(ST, "DELETE", SUB, ["reservationOrders", "res2"], {}, {})["status"] == 204)

# ── Microsoft.CostManagement/costAllocationRules (enforced in a grouped query) ──
P2 = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg2/providers"
arm.handle("PUT", f"{P2}/Microsoft.Storage/storageAccounts/uicstorage2", {}, {"location": "eastus"})
before = {row[1]: row[0] for row in cost.run_cost_query(ST, SUB, None, {"dataset": {"grouping": [{"name": "ResourceGroupName"}]}}, NOW)["properties"]["rows"]}
check("before any rule, rg1 carries its own real cost", before.get("rg1", 0) > 0, before)
r = cost.dispatch_allocationrules(ST, "PUT", SUB, ["alloc1"], {"properties": {"details": {
    "sourceResources": [{"name": "rg1"}], "targetResources": [{"name": "rg2", "allocation": 100}]}}}, {})
check("create allocation rule → 201 with defaults", r["status"] == 201 and r["body"]["properties"]["status"] == "Active"
      and r["body"]["properties"]["details"]["allocationType"] == "Fixed", r["body"])
after = {row[1]: row[0] for row in cost.run_cost_query(ST, SUB, None, {"dataset": {"grouping": [{"name": "ResourceGroupName"}]}}, NOW)["properties"]["rows"]}
check("rule moves rg1's cost onto rg2", "rg1" not in after and after.get("rg2", 0) == round(before["rg1"] + before.get("rg2", 0), 6), after)
check("a scoped query (single RG) is unaffected by allocation rules", any(row[1] == "rg1" for row in
      cost.run_cost_query(ST, SUB, "rg1", {"dataset": {"grouping": [{"name": "ResourceGroupName"}]}}, NOW)["properties"]["rows"]))
check("list allocation rules", len(cost.dispatch_allocationrules(ST, "GET", SUB, [], {}, {})["body"]["value"]) == 1)
check("get missing allocation rule → 404", cost.dispatch_allocationrules(ST, "GET", SUB, ["none"], {}, {})["status"] == 404)
check("create requires source/target resources", cost.dispatch_allocationrules(ST, "PUT", SUB, ["bad"], {"properties": {"details": {}}}, {})["status"] == 400)
check("delete allocation rule → 200, then 204", cost.dispatch_allocationrules(ST, "DELETE", SUB, ["alloc1"], {}, {})["status"] == 200
      and cost.dispatch_allocationrules(ST, "DELETE", SUB, ["alloc1"], {}, {})["status"] == 204)

# ── through the Nano ARM wire end to end ────────────────────────────────────────
CM = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/providers/Microsoft.CostManagement"
CO = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/providers/Microsoft.Consumption"
BB = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/providers/Microsoft.BillingBenefits"
CAP = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/providers/Microsoft.Capacity"
r = arm.handle("PUT", f"{CO}/budgets/nano-budget", {}, {"properties": {"amount": 500}})
check("Nano ARM: budget create", r["status"] == 201, r)
r = arm.handle("POST", f"{CM}/query", {}, {"dataset": {}})
check("Nano ARM: cost query", r["status"] == 200 and "rows" in r["body"]["properties"], r)
r = arm.handle("GET", f"{CO}/budgets", {}, None)
check("Nano ARM: list budgets", r["status"] == 200 and len(r["body"]["value"]) == 1, r)
r = arm.handle("DELETE", f"{CO}/budgets/nano-budget", {}, None)
check("Nano ARM: delete budget", r["status"] == 200, r)
r = arm.handle("PUT", f"{BB}/savingsPlanOrders/nano-sp", {}, {"properties": {"commitment": {"amount": 1, "currency": "USD", "grain": "Hourly"}}})
check("Nano ARM: savings plan create", r["status"] == 201, r)
r = arm.handle("GET", f"{BB}/savingsPlanOrders", {}, None)
check("Nano ARM: list savings plans", r["status"] == 200 and any(v["name"] == "nano-sp" for v in r["body"]["value"]), r)
r = arm.handle("PUT", f"{CAP}/reservationOrders/nano-res", {}, {"properties": {"skuName": "Standard_D2s_v5", "quantity": 1}})
check("Nano ARM: reservation create", r["status"] == 201, r)
r = arm.handle("GET", f"{CAP}/reservationOrders", {}, None)
check("Nano ARM: list reservations", r["status"] == 200 and any(v["name"] == "nano-res" for v in r["body"]["value"]), r)
r = arm.handle("PUT", f"{CM}/costAllocationRules/nano-alloc", {}, {"properties": {"details": {
    "sourceResources": [{"name": "rg1"}], "targetResources": [{"name": "rg2", "allocation": 100}]}}})
check("Nano ARM: allocation rule create", r["status"] == 201, r)
r = arm.handle("GET", f"{CM}/costAllocationRules", {}, None)
check("Nano ARM: list allocation rules", r["status"] == 200 and any(v["name"] == "nano-alloc" for v in r["body"]["value"]), r)

print(f"{PASS} passed, {FAIL} failed")
assert FAIL == 0

if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
