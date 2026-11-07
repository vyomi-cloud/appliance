"""Real Azure SDKs against the ARM core served over real HTTP:
  * azure-mgmt-monitor   subscription_diagnostic_settings  (Activity log "Export Activity Logs")
  * azure-mgmt-security  automations                       (Defender for Cloud Workflow automation) + pricings
  * azure-mgmt-resourcegraph                               (Event Grid Topics "Open query")
Run: PYTHONPATH=. python tests/conformance/test_azure_sdk_defender_automation_export.py
(needs azure-mgmt-monitor, azure-mgmt-security, azure-mgmt-resourcegraph, azure-mgmt-loganalytics, azure-mgmt-resource)"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qsl

from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB

ARM = AzureArm()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _do(self):
        u = urlsplit(self.path)
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        body = json.loads(raw) if raw else None
        r = ARM.handle(self.command, u.path, dict(parse_qsl(u.query)), body)
        out = json.dumps(r["body"]).encode() if r.get("body") is not None else b""
        self.send_response(r["status"])
        for k, v in (r.get("headers") or {}).items():
            self.send_header(k, v)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
    do_GET = do_PUT = do_POST = do_DELETE = do_PATCH = _do


def _check(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


def run():
    from azure.core.pipeline.policies import SansIOHTTPPolicy
    from azure.mgmt.resource.resources import ResourceManagementClient
    from azure.mgmt.loganalytics import LogAnalyticsManagementClient
    from azure.mgmt.monitor import MonitorManagementClient
    from azure.mgmt.monitor.models import SubscriptionDiagnosticSettingsResource, SubscriptionLogSettings
    from azure.mgmt.security import SecurityCenter
    from azure.mgmt.security.models import (Automation, AutomationScope, AutomationSource, AutomationRuleSet, AutomationTriggeringRule,
                                            AutomationActionWorkspace, AutomationActionLogicApp, Pricing)
    from azure.mgmt.resourcegraph import ResourceGraphClient
    from azure.mgmt.resourcegraph.models import QueryRequest

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    cred = object()
    kw = dict(base_url=url, authentication_policy=SansIOHTTPPolicy())
    rg = "sdk-auto"
    ResourceManagementClient(cred, SUB, **kw).resource_groups.create_or_update(rg, {"location": "eastus"})
    la = LogAnalyticsManagementClient(cred, SUB, **kw)
    ws = la.workspaces.begin_create_or_update(rg, "sdk-auto-law", {"location": "eastus"}).result()

    # ── Activity log export (subscription diagnostic settings) ──
    mon = MonitorManagementClient(cred, SUB, **kw)
    ds = mon.subscription_diagnostic_settings.create_or_update(
        "sdk-export", SubscriptionDiagnosticSettingsResource(workspace_id=ws.id, logs=[SubscriptionLogSettings(category="Administrative", enabled=True)]))
    _check("SDK subscription_diagnostic_settings.create_or_update", ds.name == "sdk-export" and ds.workspace_id.lower() == ws.id.lower())
    _check("SDK subscription_diagnostic_settings.list", [d.name for d in list(mon.subscription_diagnostic_settings.list())] == ["sdk-export"])
    _check("SDK get", mon.subscription_diagnostic_settings.get("sdk-export").logs[0].category == "Administrative")
    ResourceManagementClient(cred, SUB, **kw).resource_groups.create_or_update("sdk-auto-2", {"location": "eastus"})
    q = ARM.handle("POST", f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.OperationalInsights/workspaces/sdk-auto-law/api/query",
                   {"api-version": "2022-10-01"}, {"query": "AzureDiagnostics | where Category == 'Administrative' | project OperationName"})
    rows = (q["body"].get("tables") or [{}])[0].get("rows") or []
    _check("exported Activity log rows landed in the workspace", any("resourceGroups/write" in str(r[0]) for r in rows), rows)
    mon.subscription_diagnostic_settings.delete("sdk-export")
    _check("SDK delete", list(mon.subscription_diagnostic_settings.list()) == [])

    # ── Workflow automation (azure-mgmt-security) ──
    sec = SecurityCenter(cred, SUB, **kw)
    scope = [AutomationScope(description="sub", scope_path=f"/subscriptions/{SUB}")]
    src = [AutomationSource(event_source="Alerts", rule_sets=[AutomationRuleSet(rules=[AutomationTriggeringRule(
        property_j_path="Severity", property_type="String", expected_value="Low", operator="GreaterThanOrEqualTo")])])]
    a = sec.automations.create_or_update(rg, "sdk-wf", Automation(location="eastus", scopes=scope, sources=src, is_enabled=True,
                                                                  actions=[AutomationActionWorkspace(workspace_resource_id=ws.id)]))
    _check("SDK automations.create_or_update", a.name == "sdk-wf" and a.actions[0].action_type == "Workspace" and a.is_enabled is True)
    sec.automations.create_or_update(rg, "sdk-logic", Automation(location="eastus", scopes=scope, sources=src, is_enabled=True,
                                     actions=[AutomationActionLogicApp(logic_app_resource_id=f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.Logic/workflows/w", uri="https://example.invalid/t")]))
    _check("SDK automations.list_by_resource_group", sorted(x.name for x in sec.automations.list_by_resource_group(rg)) == ["sdk-logic", "sdk-wf"])
    _check("SDK automations.get", sec.automations.get(rg, "sdk-wf").sources[0].event_source == "Alerts")
    try:
        sec.automations.create_or_update(rg, "bad", Automation(location="eastus", scopes=scope, sources=src, actions=[]))
        _check("empty actions rejected", False)
    except Exception as e:
        _check("empty actions rejected (400 from the SDK)", "400" in str(e) or "InvalidRequest" in str(e) or "action" in str(e).lower(), str(e)[:120])

    st = f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.Storage/storageAccounts/sdkautosa"
    ARM.handle("PUT", st, {"api-version": "2023-01-01"}, {"location": "eastus", "properties": {"allowBlobPublicAccess": False}})
    sec.pricings.update(f"/subscriptions/{SUB}", "StorageAccounts", Pricing(pricing_tier="Standard"))
    ARM.handle("PATCH", st, {"api-version": "2023-01-01"}, {"properties": {"allowBlobPublicAccess": True}})
    alerts = list(sec.alerts.list())
    _check("a Defender alert was raised", len(alerts) == 1)
    runs = ARM.handle("GET", f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.Security/automations/sdk-wf/vyomiRuns", {"api-version": "2023-12-01-preview"})["body"]["value"]
    _check("workspace automation ran and succeeded", len(runs) == 1 and runs[0]["status"] == "Succeeded", runs)
    runs = ARM.handle("GET", f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.Security/automations/sdk-logic/vyomiRuns", {"api-version": "2023-12-01-preview"})["body"]["value"]
    _check("Logic App automation is recorded Failed (no Logic Apps runtime)", len(runs) == 1 and runs[0]["status"] == "Failed")
    q = ARM.handle("POST", f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.OperationalInsights/workspaces/sdk-auto-law/api/query",
                   {"api-version": "2022-10-01"}, {"query": "SecurityAlert | count"})
    _check("alert row in the workspace", (q["body"].get("tables") or [{}])[0].get("rows") == [[1]], q)
    sec.automations.delete(rg, "sdk-wf")
    _check("SDK automations.delete", [x.name for x in sec.automations.list_by_resource_group(rg)] == ["sdk-logic"])

    # ── Resource Graph (Event Grid topics) ──
    ARM.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.EventGrid/topics/sdk-topic", {"api-version": "2022-06-15"}, {"location": "eastus"})
    rg_client = ResourceGraphClient(cred, **kw)
    r = rg_client.resources(QueryRequest(subscriptions=[SUB], query="Resources | where type =~ 'microsoft.eventgrid/topics' | project name"))
    data = r.data
    names = [row[0] for row in data["rows"]] if isinstance(data, dict) and "rows" in data else [row["name"] for row in data]
    _check("SDK ResourceGraph query returns the Event Grid topic", names == ["sdk-topic"], data)
    print("PASS")


if __name__ == "__main__":
    run()
