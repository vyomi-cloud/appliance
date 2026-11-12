"""Resource group tools: validateMoveResources / moveResources really re-parent resources.
Run: PYTHONPATH=. python tests/conformance/test_azure_rg_move_resources.py"""
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
AzureArm.STRICT_SUBSCRIPTION = False


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    R = {"api-version": "2021-04-01"}
    code = lambda r: (r["body"] or {}).get("error", {}).get("code") if isinstance(r["body"], dict) else None
    for g in ("src", "dst"):
        a.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/{g}", R, {"location": "eastus"})
    base = f"/subscriptions/{SUB}/resourceGroups/src/providers"
    SA = f"{base}/Microsoft.Storage/storageAccounts/moveacct"
    SA2 = f"{base}/Microsoft.Storage/storageAccounts/other"
    PIP = f"{base}/Microsoft.Network/publicIPAddresses/pip1"
    NIC = f"{base}/Microsoft.Network/networkInterfaces/nic1"
    a.handle("PUT", SA, {"api-version": "2023-01-01"}, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
    a.handle("PUT", SA2, {"api-version": "2023-01-01"}, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
    a.handle("PUT", PIP, {"api-version": "2023-05-01"}, {"location": "eastus", "properties": {}})
    n = a.handle("PUT", NIC, {"api-version": "2023-05-01"}, {"location": "eastus", "properties": {"ipConfigurations": [{"name": "ip1", "properties": {"publicIPAddress": {"id": PIP}}}]}})
    _check("nic with a public-ip reference created", n["status"] in (200, 201))
    mv = lambda p, b: a.handle("POST", f"/subscriptions/{SUB}/resourceGroups/src/{p}", R, b)
    tgt = f"/subscriptions/{SUB}/resourceGroups/dst"
    _check("same target rejected", code(mv("moveResources", {"resources": [SA], "targetResourceGroup": f"/subscriptions/{SUB}/resourceGroups/src"})) == "InvalidMoveRequest")
    _check("missing target group rejected", code(mv("moveResources", {"resources": [SA], "targetResourceGroup": f"/subscriptions/{SUB}/resourceGroups/nope"})) == "ResourceGroupNotFound")
    _check("unknown resource rejected", code(mv("moveResources", {"resources": [SA + "x"], "targetResourceGroup": tgt})) == "ResourceNotFound")
    _check("dependency left behind is rejected (nic -> pip)", code(mv("validateMoveResources", {"resources": [NIC], "targetResourceGroup": tgt})) == "MissingMoveDependentResources")
    _check("referenced resource cannot leave alone", code(mv("validateMoveResources", {"resources": [PIP], "targetResourceGroup": tgt})) == "MissingMoveDependentResources")
    _check("validate succeeds with 204", mv("validateMoveResources", {"resources": [SA], "targetResourceGroup": tgt})["status"] == 204)
    _check("validate does not move", a.handle("GET", SA, {"api-version": "2023-01-01"})["status"] == 200)
    # lock blocks
    a.handle("PUT", f"{SA2}/providers/Microsoft.Authorization/locks/l1", {"api-version": "2016-09-01"}, {"properties": {"level": "CanNotDelete"}})
    _check("locked resource cannot move", code(mv("moveResources", {"resources": [SA2], "targetResourceGroup": tgt})) == "ScopeLocked")
    r = mv("moveResources", {"resources": [NIC, PIP, SA], "targetResourceGroup": tgt})
    _check("move succeeds with 204", r["status"] == 204)
    NEW_SA = SA.replace("/resourceGroups/src/", "/resourceGroups/dst/")
    NEW_NIC = NIC.replace("/resourceGroups/src/", "/resourceGroups/dst/")
    _check("old id is gone", a.handle("GET", SA, {"api-version": "2023-01-01"})["status"] == 404)
    _check("resource reachable under the new group", a.handle("GET", NEW_SA, {"api-version": "2023-01-01"})["status"] == 200)
    got = a.handle("GET", NEW_NIC, {"api-version": "2023-05-01"})["body"]
    _check("embedded reference rewritten to the new group", got["properties"]["ipConfigurations"][0]["properties"]["publicIPAddress"]["id"].endswith("/resourceGroups/dst/providers/Microsoft.Network/publicIPAddresses/pip1"))
    ls = lambda g: {x["name"] for x in a.handle("GET", f"/subscriptions/{SUB}/resourceGroups/{g}/resources", R)["body"]["value"]}
    _check("group listings reflect the move", ls("dst") == {"moveacct", "nic1", "pip1"} and "moveacct" not in ls("src") and "other" in ls("src"))
    _check("name clash in target rejected", code(mv("moveResources", {"resources": [SA2], "targetResourceGroup": tgt})) in ("ScopeLocked", "ResourceMoveConflict"))
    print("PASS")


if __name__ == "__main__":
    run()
