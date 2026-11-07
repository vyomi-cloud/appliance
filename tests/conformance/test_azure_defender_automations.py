"""Defender for Cloud > Workflow automation (Microsoft.Security/automations): CRUD with the real validation, and a real trigger -
a Security alert that matches an enabled automation's rules is delivered to its Workspace action (a row in the Log Analytics
workspace, queryable with KQL); Logic App / Event Hub actions are recorded as Failed (no such runtime); non-matching alerts,
disabled automations and other scopes do not fire.
Run: PYTHONPATH=. python tests/conformance/test_azure_defender_automations.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB

RG = "auto-rg"
SEC = f"/subscriptions/{SUB}/providers/Microsoft.Security"
AUT = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Security/automations"
V = {"api-version": "2023-12-01-preview"}
arm = AzureArm()
req = lambda m, p, b=None, q=None: arm.handle(m, p, q or V, b)


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


req("PUT", f"/subscriptions/{SUB}/resourcegroups/{RG}", {"location": "eastus"}, {"api-version": "2021-04-01"})
WS = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.OperationalInsights/workspaces/auto-law"
ok("workspace", req("PUT", WS, {"location": "eastus", "properties": {}}, {"api-version": "2022-10-01"})["status"] in (200, 201))
SCOPE = [{"description": "sub", "scopePath": f"/subscriptions/{SUB}"}]
rule = lambda j, op, v, t="String": {"propertyJPath": j, "propertyType": t, "expectedValue": v, "operator": op}


def body(actions, rules=None, enabled=True, scopes=SCOPE):
    return {"location": "eastus", "properties": {"description": "d", "isEnabled": enabled, "scopes": scopes,
            "sources": [{"eventSource": "Alerts", "ruleSets": [{"rules": rules}] if rules else []}], "actions": actions}}


WSACT = [{"actionType": "Workspace", "workspaceResourceId": WS}]
# ── validation ──
ok("no location -> 400", req("PUT", f"{AUT}/a0", {"properties": body(WSACT)["properties"]})["status"] == 400)
ok("unknown actionType -> 400", req("PUT", f"{AUT}/a0", body([{"actionType": "Email"}]))["status"] == 400)
ok("LogicApp needs uri -> 400", req("PUT", f"{AUT}/a0", body([{"actionType": "LogicApp", "logicAppResourceId": "/x"}]))["status"] == 400)
ok("unknown eventSource -> 400", req("PUT", f"{AUT}/a0", {"location": "eastus", "properties": {**body(WSACT)["properties"], "sources": [{"eventSource": "Nope"}]}})["status"] == 400)
ok("bad operator -> 400", req("PUT", f"{AUT}/a0", body(WSACT, [rule("Severity", "Like", "High")]))["status"] == 400)
ok("scope in another subscription -> 400", req("PUT", f"{AUT}/a0", body(WSACT, scopes=[{"scopePath": "/subscriptions/other"}]))["status"] == 400)
ok("missing workspace -> 404", req("PUT", f"{AUT}/a0", body([{"actionType": "Workspace", "workspaceResourceId": WS + "x"}]))["status"] == 404)
ok("validate action", req("POST", f"{AUT}/a0/validate", body(WSACT))["body"]["isValid"] is True)

# ── CRUD ──
r = req("PUT", f"{AUT}/hi-sev", body(WSACT, [rule("Severity", "GreaterThanOrEqualTo", "Medium")]))
ok("create -> 201", r["status"] == 201 and r["body"]["name"] == "hi-sev" and r["body"]["type"] == "Microsoft.Security/automations", r)
ok("get", req("GET", f"{AUT}/hi-sev")["status"] == 200)
ok("list by rg + sub", len(req("GET", AUT)["body"]["value"]) == 1 and len(req("GET", f"{SEC}/automations")["body"]["value"]) == 1)
ok("update -> 200", req("PUT", f"{AUT}/hi-sev", body(WSACT, [rule("Severity", "GreaterThanOrEqualTo", "Medium")]))["status"] == 200)
req("PUT", f"{AUT}/never", body(WSACT, [rule("AlertType", "Equals", "SOMETHING_ELSE")]))
req("PUT", f"{AUT}/off", body(WSACT, enabled=False))
req("PUT", f"{AUT}/other-rg", body(WSACT, scopes=[{"scopePath": f"/subscriptions/{SUB}/resourceGroups/elsewhere"}]))
req("PUT", f"{AUT}/logic", body([{"actionType": "LogicApp", "logicAppResourceId": f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Logic/workflows/w", "uri": "https://x"}],
                              [rule("AlertType", "StartsWith", "VYOMI_STORAGE")]))

# ── a real alert fires them ──
runs = lambda n: req("GET", f"{AUT}/{n}/vyomiRuns")["body"]["value"]
ok("quiet subscription: nothing ran", runs("hi-sev") == [])
st = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Storage/storageAccounts/autosa"
req("PUT", st, {"location": "eastus", "properties": {"allowBlobPublicAccess": False}}, {"api-version": "2023-01-01"})
req("PUT", SEC + "/pricings/StorageAccounts", {"properties": {"pricingTier": "Standard"}}, {"api-version": "2024-01-01"})
req("PATCH", st, {"properties": {"allowBlobPublicAccess": True}}, {"api-version": "2023-01-01"})
al = req("GET", SEC + "/alerts", None, {"api-version": "2022-01-01"})["body"]["value"]
ok("storage alert raised", len(al) == 1, al)
sev = al[0]["properties"]["severity"]
r = runs("hi-sev")
ok("matching automation ran once, Succeeded", len(r) == 1 and r[0]["status"] == "Succeeded" and r[0]["actionType"] == "Workspace", (r, sev))
req("GET", SEC + "/alerts", None, {"api-version": "2022-01-01"})
ok("idempotent: reading alerts again does not re-fire", len(runs("hi-sev")) == 1)
ok("non-matching rule did not fire", runs("never") == [])
ok("disabled automation did not fire", runs("off") == [])
ok("other scope did not fire", runs("other-rg") == [])
lg = runs("logic")
ok("Logic App action fired but is honestly Failed", len(lg) == 1 and lg[0]["status"] == "Failed" and "Logic Apps" in lg[0]["error"], lg)
q = arm.handle("POST", WS + "/api/query", {"api-version": "2022-10-01"}, {"query": "SecurityAlert | project AlertType, Status, CompromisedEntity"})
rows = (q["body"].get("tables") or [{}])[0].get("rows") or []
ok("Log Analytics workspace received the alert (KQL)", q["status"] == 200 and len(rows) == 1 and rows[0][0] == "VYOMI_STORAGE_PUBLIC_ACCESS_ENABLED", q)
ok("delete", req("DELETE", f"{AUT}/hi-sev")["status"] == 204 and req("GET", f"{AUT}/hi-sev")["status"] == 404)
print("PASS")
