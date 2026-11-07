"""Real alert evaluation + action delivery (core/azure_alerts_core.py), end to end through AzureArm.
Run: PYTHONPATH=. python3 tests/conformance/test_azure_alerts_core.py
Proves: metric alerts fire from the real metric store, activity-log alerts fire from real Activity-log rows, log-search
(scheduledQueryRules) alerts fire from the real KQL engine over ingested rows, action-group webhooks are REALLY POSTed
to a live local HTTP server, processing rules suppress/add groups, state changes + history + summary, Prometheus rule groups."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import core.azure_arm_core as _a  # noqa: E402
_a.AzureArm.STRICT_SUBSCRIPTION = False
from core.azure_arm_core import AzureArm  # noqa: E402
from core import azure_alerts_core as al  # noqa: E402

PASS = FAIL = 0
SUB = "00000000-0000-0000-0000-cloudlearn01"


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail)[:300] if detail and not ok else ''}")


HITS = []


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        HITS.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"))
        self.send_response(200); self.end_headers()

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_port}/hook"

arm = AzureArm()
P = f"/subscriptions/{SUB}"
RG = f"{P}/resourceGroups/rg1"


def call(m, path, body=None, q=None, v="2023-01-01"):
    return arm.handle(m, path, dict({"api-version": v}, **(q or {})), body)


check("rg", call("PUT", RG, {"location": "eastus"}, v="2021-04-01")["status"] in (200, 201))
ag = call("PUT", f"{RG}/providers/Microsoft.Insights/actionGroups/ops", {"location": "Global", "properties": {
    "groupShortName": "ops", "enabled": True,
    "webhookReceivers": [{"name": "hook", "serviceUri": URL, "useCommonAlertSchema": True}],
    "emailReceivers": [{"name": "mail", "emailAddress": "a@example.com"}]}})
AG = ag["body"]["id"]
check("action group created", ag["status"] in (200, 201), ag)
stg = f"{RG}/providers/Microsoft.Storage/storageAccounts/stalerts1"
call("PUT", stg, {"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2", "properties": {}}, v="2023-01-01")

# ── metric alert on the real ActivityOperations metric of the storage account ──
ma = {"location": "global", "properties": {"severity": 2, "enabled": True, "scopes": [stg], "evaluationFrequency": "PT1M", "windowSize": "PT5M",
      "criteria": {"odata.type": "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria", "allOf": [
          {"name": "c1", "metricName": "ActivityOperations", "operator": "GreaterThan", "timeAggregation": "Total", "threshold": 0}]},
      "actions": [{"actionGroupId": AG}]}}
r = call("PUT", f"{RG}/providers/Microsoft.Insights/metricAlerts/ops-high", ma, v="2018-03-01")
check("metric alert rule created", r["status"] == 200, r)
# the storage write above created Activity-log rows -> metric > 0 -> must fire when alerts are read
r = call("GET", f"{P}/providers/Microsoft.AlertsManagement/alerts", v="2019-03-01")
vals = r["body"]["value"]
check("alerts list returns a REAL fired metric alert", r["status"] == 200 and len(vals) == 1 and vals[0]["properties"]["essentials"]["monitorCondition"] == "Fired"
      and vals[0]["properties"]["essentials"]["signalType"] == "Metric" and vals[0]["properties"]["essentials"]["severity"] == "Sev2", r)
a1 = vals[0]
check("alert targets the storage account", a1["properties"]["essentials"]["targetResource"].lower() == stg.lower()
      and a1["properties"]["essentials"]["targetResourceType"] == "Microsoft.Storage/storageAccounts", a1)
check("action group webhook REALLY received an HTTP POST (common alert schema)", len(HITS) == 1 and HITS[0]["schemaId"] == "azureMonitorCommonAlertSchema"
      and HITS[0]["data"]["essentials"]["monitorCondition"] == "Fired" and HITS[0]["data"]["essentials"]["alertRule"] == "ops-high", HITS)
h = call("GET", f"{P}/providers/Microsoft.AlertsManagement/alerts/{a1['name']}/history", v="2019-03-01")["body"]["value"]
txt = " | ".join(x["properties"]["description"] for x in h)
check("history records webhook delivered + email honestly NOT sent", "webhook ops/hook: delivered" in txt and "nothing was sent" in txt, txt)
r2 = call("GET", f"{P}/providers/Microsoft.AlertsManagement/alerts", v="2019-03-01")
check("re-reading does not duplicate the open alert / re-notify", len(r2["body"]["value"]) == 1 and len(HITS) == 1)

# change state
cs = call("POST", f"{P}/providers/Microsoft.AlertsManagement/alerts/{a1['name']}/changestate", q={"newState": "Acknowledged"}, v="2019-03-01")
check("changestate -> Acknowledged", cs["status"] == 200 and cs["body"]["properties"]["essentials"]["alertState"] == "Acknowledged", cs)
check("changestate bad value -> 400", call("POST", f"{P}/providers/Microsoft.AlertsManagement/alerts/{a1['name']}/changestate", q={"newState": "x"}, v="2019-03-01")["status"] == 400)
s = call("GET", f"{P}/providers/Microsoft.AlertsManagement/alertsSummary", q={"groupby": "severity,alertState"}, v="2019-03-01")["body"]["properties"]
check("alertsSummary groups by severity then state", s["total"] == 1 and s["values"][0]["name"] == "Sev2" and s["values"][0]["values"][0]["name"] == "Acknowledged", s)
f = call("GET", f"{P}/providers/Microsoft.AlertsManagement/alerts", q={"severity": "Sev0"}, v="2019-03-01")["body"]["value"]
check("severity filter excludes", f == [])

# ── resolve: a metric that is NOT breached resolves the open alert (auto-mitigate) + resolved webhook ──
ma["properties"]["criteria"]["allOf"][0]["threshold"] = 10_000
call("PUT", f"{RG}/providers/Microsoft.Insights/metricAlerts/ops-high", ma, v="2018-03-01")
ev = call("POST", f"{P}/providers/Microsoft.AlertsManagement/evaluate", {}, v="2019-03-01")["body"]
al1 = call("GET", f"{P}/providers/Microsoft.AlertsManagement/alerts/{a1['name']}", v="2019-03-01")["body"]["properties"]["essentials"]
check("condition cleared -> alert auto-resolved", ev["resolved"] == 1 and al1["monitorCondition"] == "Resolved" and al1.get("monitorConditionResolvedDateTime"), (ev, al1))
check("resolved notification POSTed", HITS[-1]["data"]["essentials"]["monitorCondition"] == "Resolved", HITS[-1])

# ── processing rules ──
pr = {"location": "global", "properties": {"scopes": [RG], "conditions": [{"field": "Severity", "operator": "Equals", "values": ["Sev2"]}],
                                           "actions": [{"actionType": "RemoveAllActionGroups"}], "enabled": True}}
check("processing rule invalid actionType -> 400", call("PUT", f"{RG}/providers/Microsoft.AlertsManagement/actionRules/bad",
      {"properties": dict(pr["properties"], actions=[{"actionType": "Nope"}])}, v="2021-08-08")["status"] == 400)
check("processing rule created", call("PUT", f"{RG}/providers/Microsoft.AlertsManagement/actionRules/mute", pr, v="2021-08-08")["status"] == 201)
check("processing rule listed", len(call("GET", f"{RG}/providers/Microsoft.AlertsManagement/actionRules", v="2021-08-08")["body"]["value"]) == 1)
ma["properties"]["criteria"]["allOf"][0]["threshold"] = 0
call("PUT", f"{RG}/providers/Microsoft.Insights/metricAlerts/ops-high", ma, v="2018-03-01")
n_before = len(HITS)
call("POST", f"{P}/providers/Microsoft.AlertsManagement/evaluate", {}, v="2019-03-01")
fired = [x for x in call("GET", f"{P}/providers/Microsoft.AlertsManagement/alerts", q={"monitorCondition": "Fired"}, v="2019-03-01")["body"]["value"]]
check("alert raised again but notifications SUPPRESSED by the processing rule", len(fired) == 1 and fired[0]["properties"]["essentials"]["actionStatus"]["isSuppressed"] is True
      and len(HITS) == n_before, (fired, len(HITS), n_before))
call("DELETE", f"{RG}/providers/Microsoft.AlertsManagement/actionRules/mute", v="2021-08-08")

# ── activity log alert: fires for a NEW write after the rule exists ──
la = {"location": "Global", "properties": {"enabled": True, "scopes": [P], "condition": {"allOf": [
    {"field": "category", "equals": "Administrative"}, {"field": "operationName", "equals": "Microsoft.Network/virtualNetworks/write"}]},
    "actions": {"actionGroups": [{"actionGroupId": AG}]}}}
check("activity log alert created", call("PUT", f"{RG}/providers/Microsoft.Insights/activityLogAlerts/vnet-write", la, v="2020-10-01")["status"] in (200, 201))
n0 = len(HITS)
call("PUT", f"{RG}/providers/Microsoft.Network/virtualNetworks/vn1", {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}}}, v="2023-11-01")
act = [x for x in call("GET", f"{P}/providers/Microsoft.AlertsManagement/alerts", q={"monitorService": "Activity Log - Administrative"}, v="2019-03-01")["body"]["value"]]
check("activity-log alert fired for the vnet write only", len(act) == 1 and act[0]["properties"]["essentials"]["targetResourceName"] == "vn1"
      and act[0]["properties"]["essentials"]["signalType"] == "Activity Log", act)
check("...and invoked the webhook", len(HITS) == n0 + 1, (len(HITS), n0))

# ── log search alert (scheduledQueryRules) over REAL ingested rows via the real KQL engine ──
ws = f"{RG}/providers/Microsoft.OperationalInsights/workspaces/law1"
call("PUT", ws, {"location": "eastus", "properties": {}}, v="2022-10-01")
ing = arm.handle("POST", ws + "/api/logs", {"api-version": "2022-10-01", "logType": "App"},
                 [{"level": "Error", "ms": 900}, {"level": "Error", "ms": 700}, {"level": "Info", "ms": 5}])
check("ingest rows into workspace", ing["status"] == 200, ing)
sq = {"location": "eastus", "properties": {"displayName": "errors", "severity": 1, "enabled": True, "scopes": [ws], "evaluationFrequency": "PT5M",
      "windowSize": "PT15M", "criteria": {"allOf": [{"query": "App_CL | where level_s == 'Error'", "timeAggregation": "Count", "operator": "GreaterThan", "threshold": 1}]},
      "actions": {"actionGroups": [AG]}}}
bad = json.loads(json.dumps(sq)); bad["properties"]["scopes"] = [stg]
check("scheduledQueryRule scope must be a workspace -> 400", call("PUT", f"{RG}/providers/Microsoft.Insights/scheduledQueryRules/q0", bad, v="2023-03-15-preview")["status"] == 400)
check("scheduledQueryRule created", call("PUT", f"{RG}/providers/Microsoft.Insights/scheduledQueryRules/q1", sq, v="2023-03-15-preview")["status"] in (200, 201))
n0 = len(HITS)
logs = [x for x in call("GET", f"{P}/providers/Microsoft.AlertsManagement/alerts", q={"monitorService": "Log Alerts V2"}, v="2019-03-01")["body"]["value"]]
check("log alert fired from the KQL result (2 error rows > 1)", len(logs) == 1 and "query result Count = 2" in logs[0]["properties"]["context"]["result"], logs)
check("...and invoked the webhook", len(HITS) == n0 + 1)

# KQL engine proves richer operators through the ARM query path
q = arm.handle("POST", ws + "/api/query", {"api-version": "2017-10-01"},
               {"query": "App_CL | summarize n=count(), avgms=avg(ms_d) by level_s | order by n desc"})
rows = q["body"]["tables"][0]["rows"]
check("KQL summarize count/avg by + order over ingested rows", rows == [["Error", 2, 800.0], ["Info", 1, 5.0]], q["body"])
q = arm.handle("POST", ws + "/api/query", {"api-version": "2017-10-01"}, {"query": "AzureActivity | where Category == 'Alert' | count"})
check("fired alerts are in the Activity log (category Alert) and queryable via KQL", q["status"] == 200 and q["body"]["tables"][0]["rows"][0][0] >= 3, q["body"])

# ── DCR associations by rule ──
dcr = f"{RG}/providers/Microsoft.Insights/dataCollectionRules/dcr1"
call("PUT", dcr, {"location": "eastus", "properties": {"destinations": {"logAnalytics": [{"name": "d1", "workspaceResourceId": ws}]},
    "dataFlows": [{"streams": ["Microsoft-Event"], "destinations": ["d1"]}], "dataSources": {}}}, v="2023-03-11")
vm = f"{RG}/providers/Microsoft.Compute/virtualMachines/vm1"
call("PUT", vm, {"location": "eastus", "properties": {}}, v="2023-09-01")
call("PUT", f"{vm}/providers/Microsoft.Insights/dataCollectionRuleAssociations/a1", {"properties": {"dataCollectionRuleId": dcr}}, v="2023-03-11")
r = call("GET", f"{dcr}/associations", v="2023-03-11")
check("DCR -> associated resources (Resources tab)", r["status"] == 200 and len(r["body"]["value"]) == 1 and r["body"]["value"][0]["id"].lower().startswith(vm.lower()), r)

# ── Prometheus rule groups ──
prg = {"location": "eastus", "properties": {"scopes": ["/subscriptions/x/resourceGroups/rg1/providers/Microsoft.Monitor/accounts/m1"], "interval": "PT1M",
       "rules": [{"alert": "HighErr", "expression": "rate(http_errors_total[5m]) > 1", "for": "PT5M", "severity": 2, "actions": [{"actionGroupId": AG}]}]}}
check("prometheus rule group created", call("PUT", f"{RG}/providers/Microsoft.AlertsManagement/prometheusRuleGroups/pg1", prg, v="2023-03-01")["status"] == 201)
badp = json.loads(json.dumps(prg)); badp["properties"]["rules"][0]["expression"] = "rate(x[5m] > 1"
check("prometheus rule with unbalanced expression -> 400", call("PUT", f"{RG}/providers/Microsoft.AlertsManagement/prometheusRuleGroups/pg2", badp, v="2023-03-01")["status"] == 400)
check("unknown alert id -> 404", call("GET", f"{P}/providers/Microsoft.AlertsManagement/alerts/nope", v="2019-03-01")["status"] == 404)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
