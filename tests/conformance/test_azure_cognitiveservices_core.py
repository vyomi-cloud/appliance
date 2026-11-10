"""Unit tests for core/azure_cognitiveservices_core.py (run: python3 tests/conformance/test_azure_cognitiveservices_core.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_cognitiveservices_core as cs  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def cp(st, method, chain, body=None, rg="rg1"):
    return cs.dispatch(st, method, "sub1", rg, chain, [], body or {})


OAI = {"kind": "OpenAI", "location": "eastus", "sku": {"name": "S0"}, "properties": {"customSubDomainName": "oai-one"}}
st = {}
r = cp(st, "PUT", ["accounts", "oai-one"], OAI)
p = r["body"]["properties"]
check("create → 201 + LRO, endpoint, Succeeded", r["status"] == 201 and r["lro"] and p["endpoint"] == "https://oai-one.openai.azure.com/"
      and p["provisioningState"] == "Succeeded" and r["body"]["sku"] == {"name": "S0", "tier": "Standard"}, r["body"])
check("kind required", cp(st, "PUT", ["accounts", "x1"], {"location": "eastus"})["status"] == 400)
check("unknown kind", cp(st, "PUT", ["accounts", "x1"], {"kind": "Nope", "location": "eastus"})["body"]["error"]["code"] == "InvalidParameter")
check("sku not valid for kind", cp(st, "PUT", ["accounts", "x1"], {"kind": "OpenAI", "location": "eastus", "sku": {"name": "F0"}})["body"]["error"]["code"] == "InvalidSku")
check("missing location", cp(st, "PUT", ["accounts", "x1"], {"kind": "OpenAI", "sku": {"name": "S0"}})["status"] == 400)
check("subdomain conflict", cp(st, "PUT", ["accounts", "oai-two"], dict(OAI), rg="rg2")["status"] == 409)
check("kind is immutable", cp(st, "PUT", ["accounts", "oai-one"], dict(OAI, kind="TextAnalytics"))["status"] == 409)
r = cp(st, "PATCH", ["accounts", "oai-one"], {"tags": {"a": "b"}, "properties": {"publicNetworkAccess": "Disabled"}})
check("PATCH updates tags + network access", r["body"]["tags"] == {"a": "b"} and r["body"]["properties"]["publicNetworkAccess"] == "Disabled", r["body"])
k = cp(st, "POST", ["accounts", "oai-one", "listKeys"])["body"]
k2 = cp(st, "POST", ["accounts", "oai-one", "regenerateKey"], {"keyName": "Key1"})["body"]
check("regenerateKey rotates only the named key", k2["key1"] != k["key1"] and k2["key2"] == k["key2"])
check("regenerateKey validates keyName", cp(st, "POST", ["accounts", "oai-one", "regenerateKey"], {"keyName": "Key3"})["status"] == 400)

D = {"sku": {"name": "Standard", "capacity": 10}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-08-06"}}}
r = cp(st, "PUT", ["accounts", "oai-one", "deployments", "chat"], D)
check("deployment create", r["status"] == 201 and r["body"]["properties"]["model"]["name"] == "gpt-4o" and r["body"]["sku"]["capacity"] == 10, r["body"])
bad = dict(D, properties={"model": {"format": "OpenAI", "name": "nope", "version": "1"}})
check("unknown model", cp(st, "PUT", ["accounts", "oai-one", "deployments", "b"], bad)["body"]["error"]["code"] == "DeploymentModelNotSupported")
check("over quota", cp(st, "PUT", ["accounts", "oai-one", "deployments", "b"], dict(D, sku={"name": "Standard", "capacity": 10 ** 6}))["body"]["error"]["code"] == "InsufficientQuota")
used = [u for u in cp(st, "GET", ["accounts", "oai-one", "usages"])["body"]["value"] if u["name"]["value"].endswith("gpt-4o")][0]["currentValue"]
check("usages reflect deployed capacity", used == 10, used)
check("deployments only on OpenAI/AIServices", cp(st, "PUT", ["accounts", "ta", "deployments", "d"], D)["status"] == 404)
ta = cp(st, "PUT", ["accounts", "ta"], {"kind": "TextAnalytics", "location": "eastus", "sku": {"name": "S"}})
check("TextAnalytics gets the regional endpoint", ta["body"]["properties"]["endpoint"] == "https://eastus.api.cognitive.microsoft.com/")
check("deployment on TextAnalytics rejected", cp(st, "PUT", ["accounts", "ta", "deployments", "d"], D)["status"] == 400)
check("commitment plan", cp(st, "PUT", ["accounts", "ta", "commitmentPlans", "p1"], {"properties": {"autoRenew": True}})["body"]["properties"]["autoRenew"] is True)
check("list in RG / subscription", len(cp(st, "GET", ["accounts"])["body"]["value"]) == 2 and len(cp(st, "GET", ["accounts"], rg=None)["body"]["value"]) == 2)
check("checkDomainAvailability taken / free",
      cp(st, "POST", ["checkDomainAvailability"], {"subdomainName": "oai-one"}, rg=None)["body"]["isSubdomainAvailable"] is False
      and cp(st, "POST", ["checkDomainAvailability"], {"subdomainName": "fresh-one"}, rg=None)["body"]["isSubdomainAvailable"] is True)
check("location models", len(cp(st, "GET", ["locations", "eastus", "models"], rg=None)["body"]["value"]) > 10)

r = cp(st, "DELETE", ["accounts", "oai-one"])
check("delete → soft-deleted", r["status"] == 200 and cp(st, "GET", ["accounts", "oai-one"])["status"] == 404
      and cp(st, "GET", ["locations", "eastus", "resourceGroups", "rg1", "deletedAccounts", "oai-one"], rg=None)["status"] == 200)
check("re-create blocked until restore", cp(st, "PUT", ["accounts", "oai-one"], OAI)["status"] == 409)
r = cp(st, "PUT", ["accounts", "oai-one"], dict(OAI, properties={"customSubDomainName": "oai-one", "restore": True}))
check("restore brings the deployments back", r["status"] == 201 and cp(st, "GET", ["accounts", "oai-one", "deployments", "chat"])["status"] == 200)
cp(st, "DELETE", ["accounts", "oai-one"])
check("purge", cp(st, "DELETE", ["locations", "eastus", "resourceGroups", "rg1", "deletedAccounts", "oai-one"], rg=None)["status"] == 200
      and cp(st, "GET", ["deletedAccounts"], rg=None)["body"]["value"] == [])
check("delete of a missing account → 204", cp(st, "DELETE", ["accounts", "ghost"])["status"] == 204)

# through the Nano ARM dispatcher (same engine, same state map)
arm = AzureArm()
base = "/subscriptions/00000000-0000-0000-0000-cloudlearn01/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/viaarm"
resp = arm.handle("PUT", base, {"api-version": cs.API_VERSION}, {"kind": "OpenAI", "location": "eastus", "sku": {"name": "S0"}})
check("ARM dispatcher delegates to the engine", resp["status"] in (200, 201) and resp["body"]["kind"] == "OpenAI", resp)

print(f"{PASS} passed, {FAIL} failed")


def test_all_checks_pass():
    assert FAIL == 0


if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
