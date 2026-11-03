"""Deployment stacks: template provisioning, cascade delete / detach, deny settings enforcement."""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as S  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    a.handle("PUT", f"/subscriptions/{S}/resourceGroups/r", {"api-version": "2021-04-01"}, {"location": "eastus"})
    tpl = lambda n: {"$schema": "x", "contentVersion": "1.0.0.0", "resources": [{"type": "Microsoft.Storage/storageAccounts", "apiVersion": "2023-01-01", "name": n,
                     "location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2", "properties": {}}]}
    sp = lambda n: f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.Storage/storageAccounts/{n}"
    stp = lambda n: f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.Resources/deploymentStacks/{n}"
    st = {"api-version": "2024-03-01"}
    a.handle("PUT", stp("s1"), st, {"properties": {"template": tpl("stkone"), "denySettings": {"mode": "denyDelete"}}})
    _check("stack provisions its template", a.handle("GET", sp("stkone"), {"api-version": "2023-01-01"})["status"] == 200)
    _check("denyDelete blocks direct delete of a managed resource", a.handle("DELETE", sp("stkone"), {"api-version": "2023-01-01"})["status"] == 403)
    _check("denyDelete still allows writes", a.handle("PATCH", sp("stkone"), {"api-version": "2023-01-01"}, {"tags": {"a": "b"}})["status"] < 300)
    a.handle("PUT", stp("s2"), st, {"properties": {"template": tpl("stktwo"), "denySettings": {"mode": "denyWriteAndDelete"}}})
    _check("denyWriteAndDelete blocks writes", a.handle("PATCH", sp("stktwo"), {"api-version": "2023-01-01"}, {"tags": {"a": "b"}})["status"] == 403)
    _check("delete stack with detach keeps resources", a.handle("DELETE", stp("s1"), {**st, "unmanageAction.Resources": "detach"})["status"] == 200
           and a.handle("GET", sp("stkone"), {"api-version": "2023-01-01"})["status"] == 200)
    _check("detached resource is deletable again", a.handle("DELETE", sp("stkone"), {"api-version": "2023-01-01"})["status"] < 300)
    a.handle("DELETE", stp("s2"), st)
    _check("delete stack cascades managed resources", a.handle("GET", sp("stktwo"), {"api-version": "2023-01-01"})["status"] == 404)
    print("PASS test_azure_deploymentstacks_core")


if __name__ == "__main__":
    run()
