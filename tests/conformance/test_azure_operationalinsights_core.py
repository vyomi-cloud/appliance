"""Unit tests for core/azure_operationalinsights_core.py (run: python3 tests/conformance/test_azure_operationalinsights_core.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_operationalinsights_core as oi  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def cp(st, method, chain, body=None, rg="rg1", query=None):
    return oi.dispatch(st, method, "sub1", rg, chain, [], body or {}, query or {})


def mk(st, name="law-one", **props):
    return cp(st, "PUT", ["workspaces", name], {"location": "eastus", "properties": props})


st = {}
r = mk(st, retentionInDays=60)
check("create returns 201 + LRO flag", r["status"] == 201 and r["lro"])
p = r["body"]["properties"]
check("defaults: PerGB2018, customerId, Succeeded", p["sku"]["name"] == "PerGB2018" and p["customerId"] and p["provisioningState"] == "Succeeded")
check("retention honoured", p["retentionInDays"] == 60)
check("update of existing returns 200", mk(st)["status"] == 200)
check("invalid name → 400", mk(st, "x")["status"] == 400)
check("duplicate name in another RG → 409", cp(st, "PUT", ["workspaces", "law-one"], {"location": "eastus"}, rg="rg2")["status"] == 409)
check("Free tier pins retention to 7", mk(st, "law-free", sku={"name": "Free"})["body"]["properties"]["retentionInDays"] == 7)
check("retention out of range → 400", mk(st, "law-bad", retentionInDays=5000)["status"] == 400)
check("PATCH missing → 404", cp(st, "PATCH", ["workspaces", "nope"], {"tags": {}})["status"] == 404)
check("PATCH keeps sku, changes retention", cp(st, "PATCH", ["workspaces", "law-one"], {"properties": {"retentionInDays": 90}})["body"]["properties"]["sku"]["name"] == "PerGB2018")
check("list in RG and subscription", len(cp(st, "GET", ["workspaces"])["body"]["value"]) == 2 and len(cp(st, "GET", ["workspaces"], rg=None)["body"]["value"]) == 2)

k1 = cp(st, "POST", ["workspaces", "law-one", "sharedKeys"])["body"]
k2 = cp(st, "POST", ["workspaces", "law-one", "regenerateSharedKey"], {"name": "primary"})["body"]
check("regenerate changes only the requested key", k2["primarySharedKey"] != k1["primarySharedKey"] and k2["secondarySharedKey"] == k1["secondarySharedKey"])
check("usages lists DataAnalyzed", cp(st, "GET", ["workspaces", "law-one", "usages"])["body"]["value"][0]["name"]["value"] == "DataAnalyzed")
check("LogManagement cannot be disabled", cp(st, "POST", ["workspaces", "law-one", "intelligencePacks", "LogManagement", "Disable"])["status"] == 400)

S = ["workspaces", "law-one", "savedSearches", "s1"]
check("saved search without query → 400", cp(st, "PUT", S, {"properties": {"category": "c", "displayName": "d"}})["status"] == 400)
check("saved search create", cp(st, "PUT", S, {"properties": {"category": "c", "displayName": "d", "query": "Heartbeat"}})["status"] == 200)
check("saved search list/delete", len(cp(st, "GET", S[:3])["body"]["value"]) == 1 and cp(st, "DELETE", S)["status"] == 200 and cp(st, "GET", S)["status"] == 404)

T = ["workspaces", "law-one", "tables", "Orders_CL"]
cols = [{"name": "TimeGenerated", "type": "dateTime"}, {"name": "Id", "type": "string"}]
check("built-in tables present", any(t["name"] == "Heartbeat" for t in cp(st, "GET", T[:3])["body"]["value"]))
check("custom table needs TimeGenerated", cp(st, "PUT", T, {"properties": {"schema": {"columns": [{"name": "Id", "type": "string"}]}}})["status"] == 400)
check("custom table create", cp(st, "PUT", T, {"properties": {"retentionInDays": 30, "totalRetentionInDays": 90, "schema": {"columns": cols}}})["body"]["properties"]["archiveRetentionInDays"] == 60)
check("total retention below interactive → 400", cp(st, "PATCH", T, {"properties": {"retentionInDays": 100, "totalRetentionInDays": 50}})["status"] == 400)
check("built-in table delete → 400", cp(st, "DELETE", ["workspaces", "law-one", "tables", "Heartbeat"])["status"] == 400)
check("custom table delete", cp(st, "DELETE", T)["status"] == 200)

D = ["workspaces", "law-one", "dataSources", "w1"]
check("data source kind required", cp(st, "PUT", D, {"properties": {}})["status"] == 400)
cp(st, "PUT", D, {"kind": "WindowsEvent", "properties": {"eventLogName": "System"}})
check("data sources need a kind filter", cp(st, "GET", D[:3])["status"] == 400)
check("data sources filter by kind", len(cp(st, "GET", D[:3], query={"$filter": "kind eq 'WindowsEvent'"})["body"]["value"]) == 1
      and len(cp(st, "GET", D[:3], query={"$filter": "kind eq 'LinuxSyslog'"})["body"]["value"]) == 0)

check("delete returns 200 + LRO, then 204", cp(st, "DELETE", ["workspaces", "law-one"])["lro"] and cp(st, "DELETE", ["workspaces", "law-one"])["status"] == 204)

arm = AzureArm()
resp = arm.handle("PUT", "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.OperationalInsights/workspaces/law-arm",
                  {"api-version": "2022-10-01"}, {"location": "eastus", "properties": {}})
check("ARM dispatcher routes Microsoft.OperationalInsights (201 + async header)",
      resp["status"] == 201 and "Azure-AsyncOperation" in resp["headers"], str(resp)[:200])
resp = arm.handle("GET", "/subscriptions/sub1/providers/Microsoft.OperationalInsights/workspaces", {"api-version": "2022-10-01"})
check("ARM subscription list sees the workspace", any(w["name"] == "law-arm" for w in resp["body"]["value"]), str(resp)[:200])

print(f"{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
