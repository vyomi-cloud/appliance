"""Unit tests for core/azure_msi_core.py (run: python3 tests/conformance/test_azure_msi_core.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_msi_core as msi  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if ok else 0), FAIL + (0 if ok else 1)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + str(detail) if detail and not ok else ''}")


def cp(st, method, chain, body=None, query=None, rg="rg1"):
    return msi.dispatch(st, method, "sub1", rg, chain, [], body or {}, query or {})


st = {}
r = cp(st, "PUT", ["userAssignedIdentities", "id-one"], {"location": "eastus", "tags": {"a": "b"}})
p = r["body"]["properties"]
check("create identity → 201 with tenant/principal/client ids", r["status"] == 201 and p["clientId"] and p["principalId"] and p["tenantId"]
      and r["body"]["type"] == "Microsoft.ManagedIdentity/userAssignedIdentities" and r["body"]["systemData"]["createdAt"], r["body"])
r2 = cp(st, "PUT", ["userAssignedIdentities", "id-one"], {"location": "eastus", "tags": {"c": "d"}})
check("update identity → 200, ids stable, tags replaced", r2["status"] == 200 and r2["body"]["properties"]["clientId"] == p["clientId"]
      and r2["body"]["tags"] == {"c": "d"}, r2["body"])
check("location is required", cp(st, "PUT", ["userAssignedIdentities", "id-two"], {})["body"]["error"]["code"] == "LocationRequired")
check("location cannot change", cp(st, "PUT", ["userAssignedIdentities", "id-one"], {"location": "westus"})["body"]["error"]["code"] == "InvalidResourceLocation")
check("bad name → 400", cp(st, "PUT", ["userAssignedIdentities", "a!"], {"location": "eastus"})["status"] == 400)
check("get missing → 404 ResourceNotFound", cp(st, "GET", ["userAssignedIdentities", "none"])["body"]["error"]["code"] == "ResourceNotFound")
check("PATCH missing → 404", cp(st, "PATCH", ["userAssignedIdentities", "none"], {"tags": {}})["status"] == 404)
r = cp(st, "PATCH", ["userAssignedIdentities", "id-one"], {"tags": {"x": "y"}, "properties": {"isolationScope": "regional"}})
check("PATCH tags + isolationScope", r["status"] == 200 and r["body"]["tags"] == {"x": "y"} and r["body"]["properties"]["isolationScope"] == "Regional", r["body"])
cp(st, "PUT", ["userAssignedIdentities", "id-two"], {"location": "westus"})
cp(st, "PUT", ["userAssignedIdentities", "id-three"], {"location": "eastus"}, rg="rg2")
check("list by resource group", [x["name"] for x in cp(st, "GET", ["userAssignedIdentities"])["body"]["value"]] == ["id-one", "id-two"])
check("list by subscription", len(cp(st, "GET", ["userAssignedIdentities"], rg=None)["body"]["value"]) == 3)
r = cp(st, "GET", ["userAssignedIdentities"], query={"$top": "1", "api-version": "2023-01-31"})
check("paging nextLink", len(r["body"]["value"]) == 1 and "$skiptoken=1" in r["body"].get("nextLink", ""), r["body"])

fc = ["userAssignedIdentities", "id-one", "federatedIdentityCredentials"]
good = {"properties": {"issuer": "https://token.actions.githubusercontent.com", "subject": "repo:o/r:ref:refs/heads/main",
                       "audiences": ["api://AzureADTokenExchange"]}}
r = cp(st, "PUT", fc + ["github"], good)
check("create federated credential → 201", r["status"] == 201 and r["body"]["type"].endswith("/federatedIdentityCredentials")
      and r["body"]["properties"]["subject"].startswith("repo:"), r["body"])
check("update federated credential → 200", cp(st, "PUT", fc + ["github"], good)["status"] == 200)
check("duplicate issuer+subject → 409", cp(st, "PUT", fc + ["github2"], good)["status"] == 409)
check("issuer must be https", cp(st, "PUT", fc + ["bad"], {"properties": {"issuer": "http://x", "subject": "s", "audiences": ["a"]}})["status"] == 400)
check("exactly one audience", cp(st, "PUT", fc + ["bad"], {"properties": {"issuer": "https://x", "subject": "s", "audiences": ["a", "b"]}})["status"] == 400)
check("list / get credentials", len(cp(st, "GET", fc)["body"]["value"]) == 1 and cp(st, "GET", fc + ["github"])["status"] == 200)
check("credential on missing identity → 404", cp(st, "GET", ["userAssignedIdentities", "none", "federatedIdentityCredentials"])["status"] == 404)
check("delete credential → 200 then 204", cp(st, "DELETE", fc + ["github"])["status"] == 200 and cp(st, "DELETE", fc + ["github"])["status"] == 204)

# associated resources: any ARM record that references the identity
rid = "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-one"
for n in ("vm-b", "vm-a"):
    st[f"/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.compute/virtualmachines/{n}"] = {
        "id": f"/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/{n}", "name": n,
        "type": "Microsoft.Compute/virtualMachines", "identity": {"type": "UserAssigned", "userAssignedIdentities": {rid: {}}}}
ar = ["userAssignedIdentities", "id-one", "listAssociatedResources"]
r = cp(st, "POST", ar)
check("listAssociatedResources sorted by name", [x["name"] for x in r["body"]["value"]] == ["vm-a", "vm-b"], r["body"])
check("$filter contains(name,…)", len(cp(st, "POST", ar, query={"$filter": "contains(name,'-b')"})["body"]["value"]) == 1)
check("$orderby desc", cp(st, "POST", ar, query={"$orderby": "name desc"})["body"]["value"][0]["name"] == "vm-b")
check("bad $filter → 400", cp(st, "POST", ar, query={"$filter": "foo"})["status"] == 400)
check("associated GET not allowed", cp(st, "GET", ar)["status"] == 405)

check("delete identity → 200, then 204", cp(st, "DELETE", ["userAssignedIdentities", "id-one"])["status"] == 200
      and cp(st, "DELETE", ["userAssignedIdentities", "id-one"])["status"] == 204)

# through the Nano ARM front door
arm = AzureArm()
path = "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.ManagedIdentity/userAssignedIdentities/viaarm"
res = arm.handle("PUT", path, {"api-version": "2023-01-31"}, {"location": "eastus"}) if hasattr(arm, "handle") else None
check("ARM front door creates and lists", res is not None and res["status"] == 201
      and len(arm.handle("GET", path.rsplit("/", 1)[0], {"api-version": "2023-01-31"}, None)["body"]["value"]) == 1, res)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
