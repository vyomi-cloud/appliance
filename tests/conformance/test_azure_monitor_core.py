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

check("delete → 200 then 204", cp(st, "DELETE", ["metricAlerts", "cpu"])["status"] == 200 and cp(st, "DELETE", ["metricAlerts", "cpu"])["status"] == 204)

arm = AzureArm()
r = arm.handle("PUT", "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Insights/metricAlerts/viaarm", {"api-version": "2018-03-01"}, alert())
check("ARM dispatcher routes Microsoft.Insights to the engine", r["status"] == 200, r)
r = arm.handle("GET", "/subscriptions/sub1/providers/Microsoft.Insights/metricAlerts", {"api-version": "2018-03-01"})
check("ARM dispatcher lists at subscription scope", r["status"] == 200 and len(r["body"]["value"]) == 1, r)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
