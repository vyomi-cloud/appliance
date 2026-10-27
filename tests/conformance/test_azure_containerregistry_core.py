"""Unit tests for core/azure_containerregistry_core.py (run: python3 tests/conformance/test_azure_containerregistry_core.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_containerregistry_core as acr  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def cp(st, method, chain, body=None, rg="rg1"):
    return acr.dispatch(st, method, "sub1", rg, chain, [], body or {})


R = ["registries", "acrone1"]
st = {}
r = cp(st, "PUT", R, {"location": "eastus", "sku": {"name": "Basic"}})
p = r["body"]["properties"]
check("create → 201 + LRO, loginServer, defaults", r["status"] == 201 and r["lro"] and p["loginServer"] == "acrone1.azurecr.io"
      and p["adminUserEnabled"] is False and r["body"]["sku"] == {"name": "Basic", "tier": "Basic"}, r["body"])
check("name rules (alphanumeric 5-50)", cp(st, "PUT", ["registries", "ab-cd"], {"location": "eastus", "sku": {"name": "Basic"}})["body"]["error"]["code"] == "InvalidParameter")
check("name conflict across groups", cp(st, "PUT", R, {"location": "eastus", "sku": {"name": "Basic"}}, rg="rg2")["status"] == 409)
check("missing location", cp(st, "PUT", ["registries", "acrtwo22"], {"sku": {"name": "Basic"}})["status"] == 400)
check("missing sku", cp(st, "PUT", ["registries", "acrtwo22"], {"location": "eastus"})["status"] == 400)
check("bad sku", cp(st, "PUT", ["registries", "acrtwo22"], {"location": "eastus", "sku": {"name": "Gold"}})["body"]["error"]["code"] == "InvalidSku")
check("credentials refused while admin disabled", cp(st, "POST", R + ["listCredentials"])["status"] == 400)
r = cp(st, "PATCH", R, {"tags": {"a": "b"}, "properties": {"adminUserEnabled": True}})
check("PATCH updates tags + admin", r["body"]["tags"] == {"a": "b"} and r["body"]["properties"]["adminUserEnabled"] is True, r["body"])
c1 = cp(st, "POST", R + ["listCredentials"])["body"]
check("credentials: username + 2 passwords, stable", c1["username"] == "acrone1" and len(c1["passwords"]) == 2
      and cp(st, "POST", R + ["listCredentials"])["body"] == c1)
c2 = cp(st, "POST", R + ["regenerateCredential"], {"name": "password2"})["body"]
check("regenerate rotates only the named password", c2["passwords"][0] == c1["passwords"][0] and c2["passwords"][1] != c1["passwords"][1])
check("regenerate rejects a bad name", cp(st, "POST", R + ["regenerateCredential"], {"name": "x"})["status"] == 400)
check("list by group / subscription", len(cp(st, "GET", ["registries"])["body"]["value"]) == 1 and cp(st, "GET", ["registries"], rg="rg2")["body"]["value"] == [])
check("checkNameAvailability: taken / invalid / free",
      cp(st, "POST", ["checkNameAvailability"], {"name": "acrone1"}, rg=None)["body"]["reason"] == "AlreadyExists"
      and cp(st, "POST", ["checkNameAvailability"], {"name": "a-b"}, rg=None)["body"]["reason"] == "Invalid"
      and cp(st, "POST", ["checkNameAvailability"], {"name": "freename1"}, rg=None)["body"]["nameAvailable"] is True)
check("usages report Size / Webhooks", {u["name"] for u in cp(st, "GET", R + ["listUsages"])["body"]["value"]} >= {"Size", "Webhooks"})

W = R + ["webhooks", "hook11"]
w = cp(st, "PUT", W, {"location": "eastus", "properties": {"serviceUri": "https://e.com/h", "actions": ["push"]}})
check("webhook create → 201", w["status"] == 201 and w["body"]["properties"]["status"] == "enabled", w["body"])
check("webhook needs serviceUri + valid actions", cp(st, "PUT", R + ["webhooks", "hook22"], {"properties": {"actions": ["push"]}})["status"] == 400
      and cp(st, "PUT", R + ["webhooks", "hook22"], {"properties": {"serviceUri": "https://e.com", "actions": ["bogus"]}})["status"] == 400)
check("webhook ping + events", cp(st, "POST", W + ["ping"])["status"] == 200 and len(cp(st, "POST", W + ["listEvents"])["body"]["value"]) == 1)
check("Basic allows 2 webhooks", cp(st, "PUT", R + ["webhooks", "hook33"], {"properties": {"serviceUri": "https://e.com", "actions": ["push"]}})["status"] == 201
      and cp(st, "PUT", R + ["webhooks", "hook44"], {"properties": {"serviceUri": "https://e.com", "actions": ["push"]}})["status"] == 409)
check("webhook delete + list", cp(st, "DELETE", W)["status"] == 200 and len(cp(st, "GET", R + ["webhooks"])["body"]["value"]) == 1)

check("replication needs Premium", cp(st, "PUT", R + ["replications", "westus"], {"location": "westus"})["body"]["error"]["code"] == "InvalidSku")
cp(st, "PATCH", R, {"sku": {"name": "Premium"}})
check("replication create on Premium", cp(st, "PUT", R + ["replications", "westus"], {"location": "westus"})["status"] == 201)
check("cannot downgrade with replications", cp(st, "PATCH", R, {"sku": {"name": "Basic"}})["status"] == 409)
check("home region cannot be a replica", cp(st, "PUT", R + ["replications", "eastus"], {"location": "eastus"})["status"] == 409)

sm = cp(st, "PUT", R + ["scopeMaps", "mymap"], {"properties": {"actions": ["repositories/*/content/read"]}})
check("scope map create", sm["status"] == 201, sm["body"])
check("system scope maps listed", any(m["name"] == "_repositories_pull" for m in cp(st, "GET", R + ["scopeMaps"])["body"]["value"]))
tk = cp(st, "PUT", R + ["tokens", "tok1"], {"properties": {"scopeMapId": sm["body"]["id"]}})
check("token create bound to scope map", tk["status"] == 201 and tk["body"]["properties"]["status"] == "enabled", tk["body"])
check("scope map in use cannot be deleted", cp(st, "DELETE", R + ["scopeMaps", "mymap"])["status"] == 409)
g = cp(st, "POST", R + ["generateCredentials"], {"tokenId": tk["body"]["id"]})
check("generateCredentials returns a token password", g["status"] == 200 and g["body"]["passwords"][0]["value"], g["body"])

d = cp(st, "DELETE", R)
check("delete → LRO, then not found", d["status"] == 200 and d["lro"] and cp(st, "GET", R)["body"]["error"]["code"] == "ResourceNotFound")
check("delete of a missing registry → 204", cp(st, "DELETE", R)["status"] == 204)
check("unknown type", cp(st, "GET", ["bogus"])["status"] == 404)

print(f"{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
