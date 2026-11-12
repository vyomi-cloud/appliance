"""Workbooks renderer (core/azure_workbooks_core.py): Microsoft.Insights/workbooks CRUD stays the real resource; POST .../workbooks/{n}/render
executes serializedData -- parameters, text, KQL query items (against the Log Analytics KQL subset incl. AzureActivity), groups,
conditionalVisibility -- and reports unsupported item kinds honestly. Run: PYTHONPATH=. python tests/conformance/test_azure_workbooks_core.py"""
import json

from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB

AzureArm.STRICT_SUBSCRIPTION = False
a = AzureArm()
RG = f"/subscriptions/{SUB}/resourceGroups/wb-rg"
req = lambda m, p, b=None, v="2022-04-01", q=None: a.handle(m, p, {"api-version": v, **(q or {})}, b)


def ok(n, c, extra=""):
    if not c:
        raise AssertionError(f"{n} {extra}")
    print("  ok ", n)


req("PUT", RG, {"location": "eastus"}, "2021-04-01")
WS = f"{RG}/providers/Microsoft.OperationalInsights/workspaces/wb-law"
ok("workspace", req("PUT", WS, {"location": "eastus"}, "2022-10-01")["status"] in (200, 201))
rows = [{"Computer": "web1", "Level": "Error", "Count": 5, "Msg": "a"}, {"Computer": "web2", "Level": "Warning", "Count": 2, "Msg": "b"},
        {"Computer": "web1", "Level": "Error", "Count": 7, "Msg": "c"}, {"Computer": "db1", "Level": "Info", "Count": 1, "Msg": "d"}]
ok("ingest rows", req("POST", WS + "/api/logs", rows, "2022-10-01", {"logType": "AppEvents"})["status"] in (200, 202))

doc = {"version": "Notebook/1.0", "items": [
    {"type": 1, "name": "intro", "content": {"json": "## Errors on {Level}"}},
    {"type": 9, "name": "params", "content": {"parameters": [{"name": "Level", "type": 1, "value": "Error"}, {"name": "TimeRange", "type": 4, "value": {"durationMs": 86400000}}]}},
    {"type": 3, "name": "byComputer", "content": {"version": "KqlItem/1.0", "queryType": 0, "visualization": "barchart", "size": 1, "crossComponentResources": [WS],
                                                     "query": "AppEvents_CL | where Level_s == '{Level}' | summarize total = sum(Count_d) by Computer_s | order by total desc"}},
    {"type": 12, "name": "grp", "content": {"title": "Details", "items": [
        {"type": 3, "name": "raw", "content": {"queryType": 0, "crossComponentResources": [WS], "query": "AppEvents_CL | where {TimeRange} | where Level_s == '{Level}' | project Computer_s, Msg_s | take 10"}}]}},
    {"type": 3, "name": "bad", "content": {"queryType": 0, "crossComponentResources": [WS], "query": "AppEvents_CL | join kind=inner (X) on Computer_s"}},
    {"type": 3, "name": "arg", "content": {"queryType": 1, "query": "resources | take 1"}},
    {"type": 3, "name": "missing", "content": {"queryType": 0, "crossComponentResources": [WS], "query": "AppEvents_CL | where Level_s == '{Nope}'"}},
    {"type": 10, "name": "metrics", "content": {"chartId": "x"}},
    {"type": 1, "name": "warnOnly", "conditionalVisibility": {"parameterName": "Level", "comparison": "isEqualTo", "value": "Warning"}, "content": {"json": "warn"}},
]}
W = f"{RG}/providers/Microsoft.Insights/workbooks/11111111-1111-1111-1111-111111111111"
ok("create workbook (real CRUD)", req("PUT", W, {"location": "eastus", "kind": "shared", "properties": {"displayName": "Ops", "category": "workbook", "serializedData": json.dumps(doc),
                                                                                                           "sourceId": WS}})["status"] in (200, 201))
ok("get workbook", req("GET", W)["body"]["properties"]["displayName"] == "Ops")
ok("render of unknown workbook -> 404", req("POST", W + "x/render", {})["status"] == 404)

r = req("POST", W + "/render", {})
ok("render 200", r["status"] == 200, r)
b = r["body"]
byid = {x["name"]: x for x in b["items"]}
ok("text with parameter substituted", byid["intro"]["markdown"] == "## Errors on Error")
ok("parameters resolved", b["parameters"]["Level"] == "Error")
q = byid["byComputer"]
ok("KQL query item returns a table", q["status"] == "ok" and q["visualization"] == "barchart" and q["columns"][0]["name"] == "Computer_s" and q["rows"] == [["web1", 12]], q)
g = byid["grp"]["items"][0]
ok("group nests a query; {TimeRange} expands to a TimeGenerated filter", g["status"] == "ok" and "ago(86400000ms)" in g["query"] and sorted(r[1] for r in g["rows"]) == ["a", "c"], g)
ok("unsupported KQL is a per-item error, not a failed render", byid["bad"]["status"] == "error" and "join" in byid["bad"]["error"].lower(), byid["bad"])
ok("Resource Graph query reported unsupported", byid["arg"]["status"] == "unsupported")
ok("unresolved parameter reported", byid["missing"]["status"] == "error" and "Nope" in byid["missing"]["error"])
ok("metrics item reported unsupported", byid["metrics"]["status"] == "unsupported")
ok("conditionalVisibility hides the item", byid["warnOnly"]["type"] == "hidden")
ok("summary counts", b["summary"] == {"queries": 5, "ok": 2, "errors": 2, "unsupported": 2}, b["summary"])

r = req("POST", W + "/render", {"parameters": {"Level": "Warning"}})
by2 = {x["name"]: x for x in r["body"]["items"]}
ok("request parameter override re-runs the queries", by2["byComputer"]["rows"] == [["web2", 2]] and by2["warnOnly"]["type"] == "text")

# AzureActivity (the real Activity log feed) is queryable from a workbook
doc2 = {"version": "Notebook/1.0", "items": [{"type": 3, "name": "act", "content": {"queryType": 0, "crossComponentResources": [WS], "query": "AzureActivity | take 5"}}]}
W2 = f"{RG}/providers/Microsoft.Insights/workbooks/22222222-2222-2222-2222-222222222222"
req("PUT", W2, {"location": "eastus", "kind": "shared", "properties": {"displayName": "Act", "category": "workbook", "serializedData": json.dumps(doc2)}})
r = req("POST", W2 + "/render", {})
ok("AzureActivity table reachable; workspace falls back to the only one", r["body"]["items"][0]["status"] == "ok" and r["body"]["items"][0]["rowCount"] >= 1, r["body"]["items"][0])
req("PUT", W2, {"location": "eastus", "kind": "shared", "properties": {"displayName": "Act", "category": "workbook", "serializedData": "not json"}})
ok("invalid serializedData -> 400", req("POST", W2 + "/render", {})["status"] == 400)
print("PASS")
