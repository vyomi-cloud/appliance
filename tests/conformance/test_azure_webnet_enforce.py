"""App Service access restrictions enforced on requests reaching the site (evaluate_access).
Run: PYTHONPATH=. python tests/conformance/test_azure_webnet_enforce.py"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
    from core import azure_webnet_core as wn
except ImportError:  # pragma: no cover
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB  # type: ignore
    import azure_webnet_core as wn  # type: ignore


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def run():
    a = AzureArm()
    Q = {"api-version": "2023-12-01"}
    RG = f"/subscriptions/{SUB}/resourceGroups/w-rg"
    W = RG + "/providers/Microsoft.Web"
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    a.handle("PUT", f"{W}/serverfarms/p1", Q, {"location": "eastus", "sku": {"name": "B1", "tier": "Basic"}, "properties": {}})
    site = a.handle("PUT", f"{W}/sites/app1", Q, {"location": "eastus", "kind": "app", "properties": {"serverFarmId": f"{W}/serverfarms/p1"}})
    ev = lambda h, scm=False: wn.evaluate_access(a.state, a.handle("GET", f"{W}/sites/app1", Q)["body"], h, scm)
    _check("no rules -> allowed", ev({}) is None)
    a.handle("PUT", f"{W}/sites/app1/config/web", Q, {"properties": {"ipSecurityRestrictions": [
        {"name": "office", "action": "Allow", "priority": 100, "ipAddress": "203.0.113.0/24"},
        {"name": "bad", "action": "Deny", "priority": 50, "ipAddress": "203.0.113.66/32"},
        {"name": "fd", "action": "Allow", "priority": 200, "ipAddress": "AzureFrontDoor.Backend", "tag": "ServiceTag", "headers": {"x-azure-fdid": ["12345678-1234-1234-1234-123456789abc"]}}]}})
    _check("allowed office ip", ev({"x-vyomi-source-ip": "203.0.113.9"}) is None)
    d = ev({"x-vyomi-source-ip": "203.0.113.66"})
    _check("higher-priority Deny wins", d and d[0] == 403 and "bad" in d[2])
    _check("other ip denied by implicit Deny all", ev({"x-vyomi-source-ip": "198.51.100.5"})[0] == 403)
    _check("undeclared caller denied", ev({})[0] == 403)
    _check("front door with right id allowed", ev({"x-vyomi-source-service-tag": "AzureFrontDoor.Backend", "x-azure-fdid": "12345678-1234-1234-1234-123456789abc"}) is None)
    _check("front door with wrong id denied", ev({"x-vyomi-source-service-tag": "AzureFrontDoor.Backend", "x-azure-fdid": "00000000-0000-0000-0000-000000000000"})[0] == 403)
    _check("SCM site has its own (empty) restrictions", ev({"x-vyomi-source-ip": "198.51.100.5"}, scm=True) is None)
    print("webnet enforcement: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
