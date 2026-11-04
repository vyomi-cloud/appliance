try:
    import core.azure_arm_core as _lax_arm; _lax_arm.AzureArm.STRICT_SUBSCRIPTION = False  # engine test: ad-hoc subscription ids
except ImportError:
    pass
"""Storage account extras: real key rotation + expiry policy, route-specific endpoints, resource instances/custom domain round-trip."""
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
    av = {"api-version": "2023-01-01"}
    a.handle("PUT", f"/subscriptions/{S}/resourceGroups/r", {"api-version": "2021-04-01"}, {"location": "eastus"})
    p = f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.Storage/storageAccounts/saext"
    a.handle("PUT", p, av, {"location": "eastus", "kind": "StorageV2", "sku": {"name": "Standard_LRS"}})
    k1 = a.handle("POST", p + "/listKeys", av)["body"]["keys"]
    _check("two distinct random keys", k1[0]["value"] != k1[1]["value"] and len(k1[0]["value"]) > 60)
    _check("listKeys is stable", a.handle("POST", p + "/listKeys", av)["body"]["keys"][0]["value"] == k1[0]["value"])
    k2 = a.handle("POST", p + "/regenerateKey", av, {"keyName": "key1"})["body"]["keys"]
    _check("regenerate rotates key1 only", k2[0]["value"] != k1[0]["value"] and k2[1]["value"] == k1[1]["value"])
    _check("listKeys returns the rotated key", a.handle("POST", p + "/listKeys", av)["body"]["keys"][0]["value"] == k2[0]["value"])
    _check("bad keyName 400", a.handle("POST", p + "/regenerateKey", av, {"keyName": "key3"})["status"] == 400)
    _check("keyCreationTime on account", "key1" in a.handle("GET", p, av)["body"]["properties"]["keyCreationTime"])
    r = a.handle("PATCH", p, av, {"properties": {"keyPolicy": {"keyExpirationPeriodInDays": 30}}})
    _check("keyPolicy stored", r["body"]["properties"]["keyPolicy"]["keyExpirationPeriodInDays"] == 30)
    _check("per-key expiry reported", "keyExpirationTime" in a.handle("POST", p + "/listKeys", av)["body"]["keys"][0])
    r = a.handle("PATCH", p, av, {"properties": {"routingPreference": {"routingChoice": "MicrosoftRouting", "publishInternetEndpoints": True}}})
    _check("internet endpoint published", "internetEndpoints" in r["body"]["properties"]["primaryEndpoints"] and "microsoftEndpoints" not in r["body"]["properties"]["primaryEndpoints"])
    r = a.handle("PATCH", p, av, {"properties": {"routingPreference": {"publishInternetEndpoints": False}}})
    _check("endpoint unpublished", "internetEndpoints" not in r["body"]["properties"].get("primaryEndpoints", {}))
    r = a.handle("PATCH", p, av, {"properties": {"networkAcls": {"resourceAccessRules": [{"tenantId": "t", "resourceId": "/subscriptions/x"}]}, "customDomain": {"name": "cdn.example.com", "useSubDomainName": False}}})
    pr = r["body"]["properties"]
    _check("resource instances + custom domain round-trip", pr["networkAcls"]["resourceAccessRules"][0]["resourceId"] == "/subscriptions/x" and pr["customDomain"]["name"] == "cdn.example.com")
    print("PASS test_azure_storage_ext_core")


if __name__ == "__main__":
    run()
