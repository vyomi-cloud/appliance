"""Unit tests for core/azure_applicationinsights_core.py (run: python3 tests/conformance/test_azure_applicationinsights_core.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_applicationinsights_core as ai  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def call(st, method, chain, body=None, rg="rg1"):
    return ai.dispatch(st, method, "sub1", rg, chain, [], body or {})


C = {"location": "eastus", "kind": "web", "tags": {"env": "dev"}, "properties": {"Application_Type": "web", "RetentionInDays": 30}}
st = {}
r = call(st, "PUT", ["components", "appi1"], C)
p = r["body"]["properties"]
check("create → 200, instrumentation key + connection string issued, not an LRO",
      r["status"] == 200 and not r["lro"] and "InstrumentationKey=" + p["InstrumentationKey"] in p["ConnectionString"]
      and p["RetentionInDays"] == 30 and p["provisioningState"] == "Succeeded", r["body"])
check("PUT again → 200, key stable", call(st, "PUT", ["components", "appi1"], C)["body"]["properties"]["InstrumentationKey"] == p["InstrumentationKey"])
check("missing Application_Type → 400", call(st, "PUT", ["components", "x"], {"location": "eastus", "kind": "web"})["status"] == 400)
check("bad retention → 400", call(st, "PUT", ["components", "x"], {**C, "properties": {"Application_Type": "web", "RetentionInDays": 31}})["status"] == 400)
check("PATCH tags", call(st, "PATCH", ["components", "appi1"], {"tags": {"a": "b"}})["body"]["tags"] == {"a": "b"})
check("list by rg / other rg / sub", len(call(st, "GET", ["components"])["body"]["value"]) == 1
      and call(st, "GET", ["components"], rg="other")["body"]["value"] == []
      and len(call(st, "GET", ["components"], rg=None)["body"]["value"]) == 1)
r = call(st, "POST", ["components", "appi1", "ApiKeys"], {"name": "k1", "linkedReadProperties": ["/x/api"], "linkedWriteProperties": ["/x/annotations"]})
kid = r["body"]["id"].rsplit("/", 1)[-1]
check("API key create returns the secret once", r["status"] == 200 and r["body"]["apiKey"] and r["body"]["name"] == "k1", r["body"])
check("API key list hides secret", "apiKey" not in call(st, "GET", ["components", "appi1", "ApiKeys"])["body"]["value"][0])
check("API key duplicate → 409", call(st, "POST", ["components", "appi1", "ApiKeys"], {"name": "k1"})["status"] == 409)
check("API key delete", call(st, "DELETE", ["components", "appi1", "ApiKeys", kid])["status"] == 200
      and call(st, "GET", ["components", "appi1", "ApiKeys", kid])["status"] == 404)
f = call(st, "PUT", ["components", "appi1", "currentbillingfeatures"], {"DataVolumeCap": {"Cap": 5.0}})["body"]
check("billing features / daily cap update", f["DataVolumeCap"]["Cap"] == 5.0 and f["CurrentBillingFeatures"] == ["Basic"], f)
W = {"location": "eastus", "tags": {"hidden-link:" + ai._canon("sub1", "rg1", ["components"], ["appi1"]): "Resource"},
     "properties": {"Name": "ping1", "Kind": "ping", "Frequency": 300, "Timeout": 30, "Locations": [{"Id": "us-fl-mia-edge"}]}}
check("web test create", call(st, "PUT", ["webtests", "wt1"], W)["status"] == 200)
check("web test bad frequency → 400", call(st, "PUT", ["webtests", "wt2"], {**W, "properties": {**W["properties"], "Frequency": 42}})["status"] == 400)
check("list web tests by component", [w["name"] for w in call(st, "GET", ["components", "appi1", "webtests"])["body"]["value"]] == ["wt1"])
check("purge → 202 with operationId", call(st, "POST", ["components", "appi1", "purge"], {"table": "Heartbeat", "filters": [{"column": "x", "operator": "==", "value": "1"}]})["status"] == 202)
check("get missing → 404", call(st, "GET", ["components", "nope"])["status"] == 404)
check("delete component cascades its web tests", call(st, "DELETE", ["components", "appi1"])["status"] == 200
      and call(st, "GET", ["webtests", "wt1"])["status"] == 404)
check("delete missing → 204", call(st, "DELETE", ["components", "appi1"])["status"] == 204)

arm = AzureArm()
base = "/subscriptions/s/resourceGroups/rg1/providers/Microsoft.Insights/components/a1"
r = arm.handle("PUT", base, {"api-version": "2020-02-02"}, C)
check("AzureArm (Nano) serves Microsoft.Insights synchronously with public state",
      r["status"] == 200 and "Azure-AsyncOperation" not in r["headers"] and any("components" in k for k in arm.state), r)
check("AzureArm GET after PUT", arm.handle("GET", base, {"api-version": "2020-02-02"})["status"] == 200)
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
