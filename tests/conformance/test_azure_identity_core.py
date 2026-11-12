"""User-assigned managed identities: real resource, attach validation, resolution across engines."""
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
    uid = f"/subscriptions/{S}/resourceGroups/r/providers/Microsoft.ManagedIdentity/userAssignedIdentities/mi1"
    r = a.handle("PUT", uid, {"api-version": "2023-01-31"}, {"location": "eastus"})
    pr = r["body"]["properties"]
    _check("identity created with principalId + clientId", r["status"] in (200, 201) and pr["principalId"] and pr["clientId"] and pr["principalId"] != pr["clientId"])
    _check("stable on re-read", a.handle("GET", uid, {"api-version": "2023-01-31"})["body"]["properties"]["principalId"] == pr["principalId"])
    cases = [("Microsoft.ContainerRegistry/registries/acr1", "2023-07-01", {"sku": {"name": "Standard"}}),
             ("Microsoft.DocumentDB/databaseAccounts/cos1", "2024-05-15", {}),
             ("Microsoft.Compute/virtualMachines/vm1", "2023-09-01", {}),
             ("Microsoft.Web/sites/web1", "2023-12-01", {"kind": "app"}),
             ("Microsoft.CognitiveServices/accounts/cog1", "2024-10-01", {"kind": "OpenAI", "sku": {"name": "S0"}})]
    for t, av, b in cases:
        ns, typ, name = t.split("/")
        p = f"/subscriptions/{S}/resourceGroups/r/providers/{ns}/{typ}/{name}"
        a.handle("PUT", p, {"api-version": av}, {"location": "eastus", **b})
        bad = a.handle("PATCH", p, {"api-version": av}, {"identity": {"type": "UserAssigned", "userAssignedIdentities": {uid + "nope": {}}}})
        _check(f"{typ}: unknown identity rejected", bad["status"] == 400)
        ok = a.handle("PATCH", p, {"api-version": av}, {"identity": {"type": "UserAssigned", "userAssignedIdentities": {uid: {}}}})
        got = a.handle("GET", p, {"api-version": av})["body"]["identity"]["userAssignedIdentities"]
        _check(f"{typ}: attach resolves principalId/clientId", ok["status"] < 300 and got[uid]["principalId"] == pr["principalId"] and got[uid]["clientId"] == pr["clientId"])
        a.handle("PATCH", p, {"api-version": av}, {"identity": {"type": "None", "userAssignedIdentities": {}}})
        gone = a.handle("GET", p, {"api-version": av})["body"].get("identity") or {}
        _check(f"{typ}: detach clears the attachment", not gone.get("userAssignedIdentities"))
    print("PASS test_azure_identity_core")


if __name__ == "__main__":
    run()
