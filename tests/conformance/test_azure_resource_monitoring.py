"""Resource-group scoped metrics + per-resource alert scoping (core/azure_monitor_core.py via AzureArm).
Run: PYTHONPATH=. python tests/conformance/test_azure_resource_monitoring.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0
SUB = "00000000-0000-0000-0000-cloudlearn01"
RG = "monrg"
KV = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.KeyVault/vaults/monkv"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail) if detail and not ok else ''}")


arm = AzureArm()
h = lambda m, p, q=None, b=None: arm.handle(m, f"/subscriptions/{SUB}{p}", q or {}, b)
h("PUT", f"/resourceGroups/{RG}", {"api-version": "2021-04-01"}, {"location": "eastus"})
h("PUT", f"/resourceGroups/{RG}/providers/Microsoft.KeyVault/vaults/monkv", {"api-version": "2023-07-01"},
  {"location": "eastus", "properties": {"tenantId": "x", "sku": {"family": "A", "name": "standard"}}})
AV = {"api-version": "2018-01-01"}

r = h("GET", f"/resourceGroups/{RG}/providers/Microsoft.Insights/metricDefinitions", AV)
check("RG metric definitions list ActivityOperations", r["status"] == 200 and r["body"]["value"][0]["name"]["value"] == "ActivityOperations", r["body"])
r = h("GET", f"/resourceGroups/{RG}/providers/Microsoft.Insights/metrics", {**AV, "metricnames": "ActivityOperations", "interval": "PT1H"})
tot = sum(p.get("total", 0) for p in r["body"]["value"][0]["timeseries"][0]["data"]) if r["status"] == 200 else -1
check("RG metric counts every operation under the group (vault create is >= 1)", tot >= 1, r["body"])
r = h("GET", f"/resourceGroups/{RG}/providers/Microsoft.Insights/metrics", {**AV, "metricnames": "Percentage CPU"})
check("unknown metric name -> 400", r["status"] == 400, r)
r = h("GET", "/resourceGroups/nosuchrg/providers/Microsoft.Insights/metrics", AV)
check("missing resource group -> 404", r["status"] == 404, r)
r = h("POST", f"/resourceGroups/{RG}/providers/Microsoft.Insights/metrics", AV)
check("non-GET -> 405", r["status"] == 405, r)
r = h("GET", f"/resourceGroups/{RG}/providers/Microsoft.KeyVault/vaults/monkv/providers/Microsoft.Insights/metrics", {**AV, "metricnames": "ActivityOperations"})
check("resource scope still counts its own operations", r["status"] == 200 and sum(p.get("total", 0) for p in r["body"]["value"][0]["timeseries"][0]["data"]) >= 1, r["body"])

alert = {"location": "global", "properties": {"severity": 2, "enabled": True, "scopes": [KV], "evaluationFrequency": "PT5M", "windowSize": "PT15M",
         "criteria": {"odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria", "allOf": [
             {"criterionType": "StaticThresholdCriterion", "name": "m1", "metricName": "ActivityOperations", "timeAggregation": "Total", "operator": "GreaterThan", "threshold": 0}]}}}
r = h("PUT", f"/resourceGroups/{RG}/providers/Microsoft.Insights/metricAlerts/kvbusy", {"api-version": "2018-03-01"}, alert)
check("alert rule scoped to the vault is created", r["status"] == 200 and r["body"]["properties"]["scopes"] == [KV], r["body"])
bad = {**alert, "properties": {**alert["properties"], "windowSize": "PT1M", "evaluationFrequency": "PT5M"}}
r = h("PUT", f"/resourceGroups/{RG}/providers/Microsoft.Insights/metricAlerts/kvbad", {"api-version": "2018-03-01"}, bad)
check("window shorter than frequency -> 400", r["status"] == 400, r)

print(f"\n{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
