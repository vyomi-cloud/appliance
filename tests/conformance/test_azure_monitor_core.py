"""Unit tests for core/azure_monitor_core.py (run: python3 tests/conformance/test_azure_monitor_core.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_monitor_core as mo  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0
VM = "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1"
AG = "/subscriptions/sub1/resourceGroups/rg1/providers/microsoft.insights/actionGroups/ops"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def cp(st, method, chain, body=None, rg="rg1"):
    return mo.dispatch(st, method, "sub1", rg, chain, [], body or {}, {})


def alert(**over):
    p = {"severity": 3, "enabled": True, "scopes": [VM], "evaluationFrequency": "PT1M", "windowSize": "PT5M",
         "criteria": {"odata.type": mo.CRITERIA_TYPES[0], "allOf": [
             {"name": "c1", "metricName": "Percentage CPU", "operator": "GreaterThan", "timeAggregation": "Average", "threshold": 80}]},
         "actions": [{"actionGroupId": AG}]}
    p.update(over)
    return {"location": "global", "properties": p}


st = {}
r = cp(st, "PUT", ["actionGroups", "ops"], {"location": "Global", "properties": {"groupShortName": "ops", "enabled": True,
      "emailReceivers": [{"name": "a", "emailAddress": "a@example.com"}]}})
check("create action group → 201, receiver Enabled", r["status"] == 201 and r["body"]["properties"]["emailReceivers"][0]["status"] == "Enabled"
      and r["body"]["type"] == "Microsoft.Insights/actionGroups", r["body"])
check("short name over 12 chars → 400", cp(st, "PUT", ["actionGroups", "x"], {"properties": {"groupShortName": "x" * 13, "enabled": True}})["status"] == 400)
check("duplicate receiver names → 400", cp(st, "PUT", ["actionGroups", "x"], {"properties": {"groupShortName": "x", "enabled": True,
      "emailReceivers": [{"name": "a", "emailAddress": "a@b.co"}], "smsReceivers": [{"name": "A", "countryCode": "1", "phoneNumber": "5551234"}]}})["status"] == 400)
check("bad webhook url → 400", cp(st, "PUT", ["actionGroups", "x"], {"properties": {"groupShortName": "x", "enabled": True,
      "webhookReceivers": [{"name": "w", "serviceUri": "nope"}]}})["status"] == 400)
check("PATCH disables the group", cp(st, "PATCH", ["actionGroups", "ops"], {"properties": {"enabled": False}})["body"]["properties"]["enabled"] is False)
check("enable already-enabled receiver → 409", cp(st, "POST", ["actionGroups", "ops", "subscribe"], {"receiverName": "a"})["status"] == 409)
check("enable unknown receiver → 404", cp(st, "POST", ["actionGroups", "ops", "subscribe"], {"receiverName": "zz"})["status"] == 404)
r = cp(st, "POST", ["actionGroups", "ops", "createNotifications"], {"alertType": "servicehealth"})
check("test notifications → 202 + Location", r["status"] == 202 and "notificationStatus" in r["headers"]["Location"], r)
nid = r["headers"]["Location"].split("/notificationStatus/")[1].split("?")[0]
r = cp(st, "GET", ["notificationStatus", nid], rg=None)
check("notification status Completed with details", r["body"]["state"] == "Completed" and r["body"]["actionDetails"], r)

r = cp(st, "PUT", ["metricAlerts", "cpu"], alert())
check("create metric alert → 200 (the spec documents only 200)", r["status"] == 200 and r["body"]["properties"]["autoMitigate"] is True and "lastUpdatedTime" in r["body"]["properties"], r["body"])
check("update → 200", cp(st, "PUT", ["metricAlerts", "cpu"], alert(severity=1))["status"] == 200)
check("string numbers from the console are coerced", cp(st, "PUT", ["metricAlerts", "ui"], alert(severity="2", enabled="true",
      criteria={"allOf": [{"name": "c", "metricName": "m", "operator": "GreaterThan", "timeAggregation": "Average", "threshold": "75"}]}))["body"]["properties"]["criteria"]["allOf"][0]["threshold"] == 75)
check("severity 5 → 400", cp(st, "PUT", ["metricAlerts", "b1"], alert(severity=5))["status"] == 400)
check("window shorter than frequency → 400", cp(st, "PUT", ["metricAlerts", "b2"], alert(evaluationFrequency="PT15M", windowSize="PT5M"))["status"] == 400)
check("empty scopes → 400", cp(st, "PUT", ["metricAlerts", "b3"], alert(scopes=[]))["status"] == 400)
check("bad operator → 400", cp(st, "PUT", ["metricAlerts", "b4"], alert(criteria={"odata.type": mo.CRITERIA_TYPES[0], "allOf": [
      {"name": "c", "metricName": "m", "operator": "Bigger", "timeAggregation": "Average", "threshold": 1}]}))["status"] == 400)
check("bad action group id → 400", cp(st, "PUT", ["metricAlerts", "b5"], alert(actions=[{"actionGroupId": "ops"}]))["status"] == 400)
check("name with '/' → 400", cp(st, "PUT", ["metricAlerts", "a:b"], alert())["status"] == 400)
check("PATCH keeps criteria", len(cp(st, "PATCH", ["metricAlerts", "cpu"], {"properties": {"description": "d"}})["body"]["properties"]["criteria"]["allOf"]) == 1)
check("get missing → 404 ResourceNotFound", cp(st, "GET", ["metricAlerts", "none"])["body"]["error"]["code"] == "ResourceNotFound")
check("list by rg and sub", len(cp(st, "GET", ["metricAlerts"])["body"]["value"]) == 2 and len(cp(st, "GET", ["metricAlerts"], rg=None)["body"]["value"]) == 2)
check("other rg lists nothing", cp(st, "GET", ["metricAlerts"], rg="other")["body"]["value"] == [])

r = cp(st, "PUT", ["activityLogAlerts", "dep"], {"location": "Global", "properties": {"scopes": ["/subscriptions/sub1"],
      "condition": {"allOf": [{"field": "category", "equals": "Administrative"}, {"field": "status", "equals": "Failed"}]},
      "actions": {"actionGroups": [{"actionGroupId": AG}]}}})
check("create activity log alert → 201, enabled default", r["status"] == 201 and r["body"]["properties"]["enabled"] is True, r["body"])
check("activity alert needs a category condition", cp(st, "PUT", ["activityLogAlerts", "x"], {"properties": {"scopes": ["/subscriptions/sub1"],
      "condition": {"allOf": [{"field": "status", "equals": "Failed"}]}}})["status"] == 400)

prof = {"name": "default", "capacity": {"minimum": "1", "maximum": "5", "default": "2"}, "rules": []}
r = cp(st, "PUT", ["autoscaleSettings", "web"], {"location": "eastus", "properties": {"profiles": [prof], "targetResourceUri": VM}})
check("create autoscale → 201, enabled, name", r["status"] == 201 and r["body"]["properties"]["name"] == "web", r["body"])
check("capacity min>max → 400", cp(st, "PUT", ["autoscaleSettings", "y"], {"properties": {"profiles": [dict(prof, capacity={"minimum": "6", "maximum": "5", "default": "5"})]}})["status"] == 400)

r = cp(st, "PUT", ["workbooks", "wb1"], {"location": "eastus", "properties": {"displayName": "CPU overview", "category": "workbook", "serializedData": "{}"}})
check("create workbook → 201", r["status"] == 201 and r["body"]["properties"]["displayName"] == "CPU overview", r["body"])
check("workbook missing displayName → 400", cp(st, "PUT", ["workbooks", "wb2"], {"properties": {"category": "workbook", "serializedData": "{}"}})["status"] == 400)
check("list workbooks", len(cp(st, "GET", ["workbooks"])["body"]["value"]) == 1)

dcr = {"location": "eastus", "properties": {"dataSources": {}, "destinations": {"logAnalytics": [{"name": "dest1", "workspaceResourceId": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.OperationalInsights/workspaces/ws1"}]},
       "dataFlows": [{"streams": ["Microsoft-Perf"], "destinations": ["dest1"]}]}}
r = cp(st, "PUT", ["dataCollectionRules", "dcr1"], dcr)
check("create data collection rule → 201", r["status"] == 201 and r["body"]["properties"]["destinations"]["logAnalytics"][0]["name"] == "dest1", r["body"])
check("DCR missing dataFlows → 400", cp(st, "PUT", ["dataCollectionRules", "dcr2"], {"properties": {"destinations": dcr["properties"]["destinations"]}})["status"] == 400)

dce = {"location": "eastus", "properties": {}}
r = cp(st, "PUT", ["dataCollectionEndpoints", "dce1"], dce)
check("create DCE → 201 with generated ingestion endpoints", r["status"] == 201
      and r["body"]["properties"]["logsIngestion"]["endpoint"] and r["body"]["properties"]["networkAcls"]["publicNetworkAccess"] == "Enabled", r["body"])
immutable1 = r["body"]["properties"]["immutableId"]
r = cp(st, "PATCH", ["dataCollectionEndpoints", "dce1"], {"properties": {"description": "prod"}})
check("update DCE keeps the same immutableId/endpoints", r["body"]["properties"]["immutableId"] == immutable1 and r["body"]["properties"]["description"] == "prod")

pls = {"location": "global", "properties": {"accessModeSettings": {"queryAccessMode": "PrivateOnly", "ingestionAccessMode": "Open"}}}
r = cp(st, "PUT", ["privateLinkScopes", "pls1"], pls)
check("create private link scope → 201, access modes honored", r["status"] == 201
      and r["body"]["properties"]["accessModeSettings"]["queryAccessMode"] == "PrivateOnly"
      and r["body"]["properties"]["accessModeSettings"]["ingestionAccessMode"] == "Open", r["body"])
check("bad access mode → 400", cp(st, "PUT", ["privateLinkScopes", "pls2"],
      {"properties": {"accessModeSettings": {"queryAccessMode": "Nope"}}})["status"] == 400)

# scoped resources (Azure Monitor Resources tab) — a real child resource, validated against
# the shared ARM store rather than a stored-but-inert config.
WS1 = "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.OperationalInsights/workspaces/ws1"
st[WS1.lower()] = {"id": WS1, "name": "ws1", "type": "Microsoft.OperationalInsights/workspaces",
                    "_type": "microsoft.operationalinsights/workspaces"}
r = cp(st, "PUT", ["privateLinkScopes", "pls1", "scopedResources", "ws1res"], {"properties": {"linkedResourceId": WS1}})
check("create scoped resource → 201, linked to a real workspace", r["status"] == 201
      and r["body"]["properties"]["linkedResourceId"] == WS1
      and r["body"]["type"] == "Microsoft.Insights/privateLinkScopes/scopedResources", r["body"])
check("scoped resource needs a linkedResourceId → 400",
      cp(st, "PUT", ["privateLinkScopes", "pls1", "scopedResources", "bad"], {"properties": {}})["status"] == 400)
check("scoped resource to an unknown resource → 400", cp(st, "PUT", ["privateLinkScopes", "pls1", "scopedResources", "bad2"],
      {"properties": {"linkedResourceId": WS1 + "nope"}})["status"] == 400)
check("list scoped resources", [x["name"] for x in cp(st, "GET", ["privateLinkScopes", "pls1", "scopedResources"])["body"]["value"]] == ["ws1res"])
check("get scoped resource", cp(st, "GET", ["privateLinkScopes", "pls1", "scopedResources", "ws1res"])["body"]["properties"]["linkedResourceId"] == WS1)
check("get missing scoped resource → 404", cp(st, "GET", ["privateLinkScopes", "pls1", "scopedResources", "none"])["status"] == 404)
r = cp(st, "DELETE", ["privateLinkScopes", "pls1", "scopedResources", "ws1res"])
check("delete scoped resource → 200 then 204", r["status"] == 200
      and cp(st, "DELETE", ["privateLinkScopes", "pls1", "scopedResources", "ws1res"])["status"] == 204)
cp(st, "PUT", ["privateLinkScopes", "pls1", "scopedResources", "ws1res"], {"properties": {"linkedResourceId": WS1}})
check("deleting the scope cascades to its scoped resources", cp(st, "DELETE", ["privateLinkScopes", "pls1"])["status"] == 200
      and cp(st, "GET", ["privateLinkScopes", "pls1", "scopedResources", "ws1res"])["status"] == 404)

# diagnostic settings (ARM extension resource, scoped to any resource's own id) exercised
# directly against the module functions — AzureArm._diagnostic_settings covers the wiring.
VM2 = "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm2"
check("diagnostic marker finds the re-entrant providers token",
      mo.find_diagnostic_marker(["virtualMachines", "vm2", "providers", "Microsoft.Insights", "diagnosticSettings", "d1"]) == 2)
check("no marker on a plain chain", mo.find_diagnostic_marker(["actionGroups", "ops"]) is None)
r = mo.upsert_diagnostic_setting(st, VM2, "toLA", {"properties": {
    "workspaceId": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.OperationalInsights/workspaces/ws1",
    "logs": [{"categoryGroup": "allLogs", "enabled": True}]}})
check("diagnostic setting create → 201", r["status"] == 201 and r["body"]["properties"]["logs"][0]["enabled"] is True, r["body"])
r = mo.upsert_diagnostic_setting(st, VM2, "nodest", {"properties": {"logs": [{"category": "x", "enabled": True}]}})
check("diagnostic setting needs a destination → 400", r["status"] == 400)
r = mo.upsert_diagnostic_setting(st, VM2, "noneenabled", {"properties": {
    "storageAccountId": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/sa1",
    "logs": [{"category": "x", "enabled": False}]}})
check("diagnostic setting needs an enabled category → 400", r["status"] == 400)
check("list diagnostic settings scoped to VM2", [x["name"] for x in mo.list_diagnostic_settings(st, VM2)["body"]["value"]] == ["toLA"])
check("get missing diagnostic setting → 404", mo.get_diagnostic_setting(st, VM2, "none")["status"] == 404)
r = mo.remove_diagnostic_setting(st, VM2, "toLA")
check("delete diagnostic setting → 200 then 204", r["status"] == 200 and mo.remove_diagnostic_setting(st, VM2, "toLA")["status"] == 204)

check("delete → 200 then 204", cp(st, "DELETE", ["metricAlerts", "cpu"])["status"] == 200 and cp(st, "DELETE", ["metricAlerts", "cpu"])["status"] == 204)

arm = AzureArm()
r = arm.handle("PUT", "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Insights/metricAlerts/viaarm", {"api-version": "2018-03-01"}, alert())
check("ARM dispatcher routes Microsoft.Insights to the engine", r["status"] == 200, r)
r = arm.handle("GET", "/subscriptions/sub1/providers/Microsoft.Insights/metricAlerts", {"api-version": "2018-03-01"})
check("ARM dispatcher lists at subscription scope", r["status"] == 200 and len(r["body"]["value"]) == 1, r)

# Metrics data plane (Microsoft.Insights/metricDefinitions, metrics) — resource-scoped, chain
# re-enters "providers" like diagnostic settings. Exactly one real metric, derived from the
# resource's own real Activity log rows (never synthetic/random data).
mvm = "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/mvm1"
r = arm.handle("PUT", mvm, {"api-version": "2023-09-01"}, {"location": "eastus", "properties": {}})
check("metrics test VM created", r["status"] == 200, r)
r = arm.handle("GET", mvm + "/providers/Microsoft.Insights/metricDefinitions", {"api-version": "2018-01-01"})
check("metric definitions lists the one real metric", r["status"] == 200
      and r["body"]["value"][0]["name"]["value"] == "ActivityOperations", r["body"])
r = arm.handle("GET", mvm + "/providers/Microsoft.Insights/metrics", {"api-version": "2018-01-01", "interval": "PT1H"})
check("metrics data has one real operation (the VM create) somewhere in its series", r["status"] == 200
      and sum(p["total"] for p in r["body"]["value"][0]["timeseries"][0]["data"]) == 1, r["body"])
r = arm.handle("GET", mvm + "/providers/Microsoft.Insights/metrics", {"api-version": "2018-01-01", "metricnames": "NotReal"})
check("unknown metric name → 400", r["status"] == 400, r["body"])
r = arm.handle("GET", "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/nope/providers/Microsoft.Insights/metrics",
               {"api-version": "2018-01-01"})
check("metrics for an unknown resource → 404", r["status"] == 404, r["body"])

# Data collection rule associations (Microsoft.Insights/dataCollectionRuleAssociations) — the
# real extension resource behind "Observability agents (preview)", validated against an
# actually-existing Data Collection Rule.
mdcr = "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Insights/dataCollectionRules/mdcr1"
arm.handle("PUT", mdcr, {"api-version": "2023-03-11"}, dcr)
r = arm.handle("PUT", mvm + "/providers/Microsoft.Insights/dataCollectionRuleAssociations/assoc1",
               {"api-version": "2023-03-11"}, {"properties": {"dataCollectionRuleId": mdcr}})
check("DCR association create → 201, linked to a real rule", r["status"] == 201
      and r["body"]["properties"]["dataCollectionRuleId"] == mdcr, r["body"])
r = arm.handle("PUT", mvm + "/providers/Microsoft.Insights/dataCollectionRuleAssociations/assoc2",
               {"api-version": "2023-03-11"}, {"properties": {"dataCollectionRuleId": mdcr + "nope"}})
check("DCR association to an unknown rule → 400", r["status"] == 400, r["body"])
r = arm.handle("GET", mvm + "/providers/Microsoft.Insights/dataCollectionRuleAssociations", {"api-version": "2023-03-11"})
check("list DCR associations", [a["name"] for a in r["body"]["value"]] == ["assoc1"], r["body"])
r = arm.handle("DELETE", mvm + "/providers/Microsoft.Insights/dataCollectionRuleAssociations/assoc1", {"api-version": "2023-03-11"})
check("delete DCR association → 200 then 204", r["status"] == 200
      and arm.handle("DELETE", mvm + "/providers/Microsoft.Insights/dataCollectionRuleAssociations/assoc1", {"api-version": "2023-03-11"})["status"] == 204)

# Health models (Microsoft.Insights/healthModels) — generic-catalog CRUD, a named collection of
# member resource ids (format-validated like metric alert scopes, same _scopes helper).
r = arm.handle("PUT", "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Insights/healthModels/hm1",
               {"api-version": "2023-04-01-preview"}, {"location": "global", "properties": {"displayName": "Prod", "resources": [mvm]}})
check("health model create → 201", r["status"] == 201 and r["body"]["properties"]["resources"] == [mvm], r["body"])
check("health model missing displayName → 400", arm.handle("PUT",
      "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Insights/healthModels/hm2",
      {"api-version": "2023-04-01-preview"}, {"properties": {"resources": [mvm]}})["status"] == 400)

# Azure Monitor pipelines (Microsoft.Insights/pipelineGroups) — config real, nothing delivered.
r = arm.handle("PUT", "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Insights/pipelineGroups/pg1",
               {"api-version": "2023-10-01-preview"}, {"location": "eastus", "properties": {"platform": "Linux", "collectorEndpoints": ["https://x"]}})
check("pipeline group create → 201", r["status"] == 201 and r["body"]["properties"]["platform"] == "Linux", r["body"])
check("pipeline group bad platform → 400", arm.handle("PUT",
      "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Insights/pipelineGroups/pg2",
      {"api-version": "2023-10-01-preview"}, {"properties": {"platform": "Solaris"}})["status"] == 400)

print(f"\n{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
