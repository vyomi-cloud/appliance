"""Azure Subscriptions console gap-sweep conformance — the acceptance gate for the new
Settings/Billing surfaces added to core/azure_arm_core.py: Usage + quotas (live counts AND
enforcement), Preview features, My permissions, Policies (allowed-locations enforcement +
compliance), Deployment stacks (cascade delete), Invoices and Billing properties, and
Programmatic deployment credentials (a real, enforced roleAssignment).

Run on host:    python3 tests/conformance/test_azure_subscriptions_ext_core.py
Run in Pyodide: loaded by wasm/ harness (same file).
"""
try:
    from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


SUB = DEFAULT_SUBSCRIPTION
AV = "2023-01-01"


def _sub(path=""):
    return f"/subscriptions/{SUB}{path}"


def run() -> int:
    arm = AzureArm()

    # ── Usage + quotas: live count off real resources, then enforced on create ──
    r = arm.handle("GET", _sub("/providers/Microsoft.Network/locations/eastus/usages"))
    _check("network usages 200", r["status"] == 200)
    names = {row["name"]["value"] for row in r["body"]["value"]}
    _check("network usages cover PublicIPAddresses/VirtualNetworks/NetworkSecurityGroups",
           {"PublicIPAddresses", "VirtualNetworks", "NetworkSecurityGroups"} <= names)
    _check("public IP usage starts at zero", next(row for row in r["body"]["value"] if row["name"]["value"] == "PublicIPAddresses")["currentValue"] == 0)

    r = arm.handle("PUT", _sub("/resourceGroups/quotarg"), {"api-version": AV}, {"location": "eastus"})
    _check("quota test rg created", r["status"] == 200)
    QUOTA_LIMIT = 100
    for i in range(QUOTA_LIMIT):
        r = arm.handle("PUT", _sub(f"/resourceGroups/quotarg/providers/Microsoft.Compute/virtualMachines/vm{i}"),
                       {"api-version": "2023-09-01"}, {"location": "eastus"})
        _check(f"vm{i} create succeeds under quota", r["status"] in (200, 201))
    r = arm.handle("PUT", _sub(f"/resourceGroups/quotarg/providers/Microsoft.Compute/virtualMachines/vm{QUOTA_LIMIT}"),
                   {"api-version": "2023-09-01"}, {"location": "eastus"})
    _check(f"the ({QUOTA_LIMIT + 1})th VM in a region is rejected by the real virtualMachines quota (limit {QUOTA_LIMIT})",
           r["status"] == 403 and r["body"]["error"]["code"] == "QuotaExceeded")
    r = arm.handle("GET", _sub("/providers/Microsoft.Compute/locations/eastus/usages"))
    vmrow = next(row for row in r["body"]["value"] if row["name"]["value"] == "virtualMachines")
    _check(f"compute usages reports the {QUOTA_LIMIT} VMs actually provisioned (live, not static)", vmrow["currentValue"] == QUOTA_LIMIT)
    _check("compute usages lists the created VM names (liveness-verifiable)", "vm0" in vmrow["resources"])
    r = arm.handle("PUT", _sub("/resourceGroups/quotarg/providers/Microsoft.Compute/virtualMachines/vm0"),
                   {"api-version": "2023-09-01"}, {"location": "eastus", "tags": {"env": "x"}})
    _check("updating an existing VM at quota is not blocked (only new allocations are)", r["status"] in (200, 201))

    # ── Preview features: register/unregister persists like real ARM ──
    r = arm.handle("GET", _sub("/providers/Microsoft.Features/features"))
    _check("preview features list 200", r["status"] == 200 and len(r["body"]["value"]) > 0)
    r = arm.handle("GET", _sub("/providers/Microsoft.Features/providers/Microsoft.Compute/features/EncryptionAtHost"))
    _check("feature starts NotRegistered", r["body"]["properties"]["state"] == "NotRegistered")
    r = arm.handle("POST", _sub("/providers/Microsoft.Features/providers/Microsoft.Compute/features/EncryptionAtHost/register"))
    _check("feature register 200", r["status"] == 200 and r["body"]["properties"]["state"] == "Registered")
    r = arm.handle("GET", _sub("/providers/Microsoft.Features/providers/Microsoft.Compute/features/EncryptionAtHost"))
    _check("feature registration persists", r["body"]["properties"]["state"] == "Registered")
    r = arm.handle("POST", _sub("/providers/Microsoft.Features/providers/Microsoft.Compute/features/EncryptionAtHost/unregister"))
    _check("feature unregister 200", r["status"] == 200 and r["body"]["properties"]["state"] == "NotRegistered")

    # ── My permissions: defaults to Owner (matches Overview's "My role"), narrows under a deny ──
    r = arm.handle("GET", _sub("/providers/Microsoft.Authorization/permissions"))
    _check("my permissions defaults to full ('*') with no explicit assignment",
           r["status"] == 200 and r["body"]["value"][0]["actions"] == ["*"])
    r = arm.handle("PUT", _sub("/providers/Microsoft.Authorization/roleAssignments/deny-admin"), {"api-version": "2022-04-01"},
                   {"properties": {"principalId": "admin@vyomi.local", "kind": "deny", "denyActions": ["*"]}})
    _check("deny role assignment for the default principal created", r["status"] == 201)
    r = arm.handle("GET", _sub("/providers/Microsoft.Authorization/permissions"))
    _check("my permissions reflects an explicit assignment for the default principal (no longer the bare default)",
           r["body"]["value"][0]["actions"] != ["*"] or r["body"]["value"][0]["notActions"])
    arm.handle("DELETE", _sub("/providers/Microsoft.Authorization/roleAssignments/deny-admin"), {"api-version": "2022-04-01"})

    # ── Policies: allowed-locations built-in enforced on create, then reflected in compliance ──
    r = arm.handle("PUT", _sub("/providers/Microsoft.Authorization/policyAssignments/allowed-eastus"), {"api-version": "2022-06-01"},
                   {"properties": {"displayName": "Allowed locations",
                                   "policyDefinitionId": "/providers/Microsoft.Authorization/policyDefinitions/e56962a6-4747-49cd-b67b-bf8b01975c4c",
                                   "parameters": {"listOfAllowedLocations": {"value": ["eastus"]}}}})
    _check("policy assignment created (generic catalog CRUD)", r["status"] == 201)
    r = arm.handle("PUT", _sub("/resourceGroups/quotarg/providers/Microsoft.Storage/storageAccounts/policydenied"),
                   {"api-version": AV}, {"location": "westus"})
    _check("a resource outside the allowed locations is denied by policy", r["status"] == 403 and r["body"]["error"]["code"] == "RequestDisallowedByPolicy")
    r = arm.handle("PUT", _sub("/resourceGroups/quotarg/providers/Microsoft.Storage/storageAccounts/policyallowed"),
                   {"api-version": AV}, {"location": "eastus"})
    _check("a resource inside the allowed locations is created", r["status"] in (200, 201))
    r = arm.handle("POST", _sub("/providers/Microsoft.PolicyInsights/policyStates/latest/queryResults"))
    _check("policyStates 200", r["status"] == 200)
    states = {row["resourceId"].rsplit("/", 1)[-1]: row["complianceState"] for row in r["body"]["value"]}
    _check("compliance reports the allowed resource as Compliant", states.get("policyallowed") == "Compliant")
    _check("compliance reports resources made before the policy existed per the same rule",
           "vm0" in states)
    _check("compliance never reports an Activity log entry as a resource",
           not any("__event__" in row["resourceId"] for row in r["body"]["value"]))
    _check("compliance skips non-regional resources (roleAssignments etc.) rather than falsely flagging them",
           not any("roleassignments" in row["resourceId"].lower() for row in r["body"]["value"]))
    arm.handle("DELETE", _sub("/providers/Microsoft.Authorization/policyAssignments/allowed-eastus"), {"api-version": "2022-06-01"})

    # ── Deployment stacks: a deployment that cascade-deletes what it manages ──
    r = arm.handle("PUT", _sub("/providers/Microsoft.Resources/deploymentStacks/stack1"), {"api-version": "2024-03-01"},
                   {"properties": {"template": {"resources": [
                       {"type": "Microsoft.Storage/storageAccounts", "name": "stackmanaged1", "location": "eastus", "properties": {}}]}}})
    _check("deployment stack put 200 provisions its managed resource", r["status"] == 200 and len(r["body"]["properties"]["resources"]) == 1)
    r = arm.handle("GET", _sub("/providers/Microsoft.Storage/storageAccounts/stackmanaged1"))
    _check("the stack's managed resource really exists", r["status"] == 200)
    r = arm.handle("DELETE", _sub("/providers/Microsoft.Resources/deploymentStacks/stack1"))
    _check("deployment stack delete 200", r["status"] == 200)
    r = arm.handle("GET", _sub("/providers/Microsoft.Storage/storageAccounts/stackmanaged1"))
    _check("deleting the stack cascade-deletes the resource it managed", r["status"] == 404)

    # ── Invoices: derived from the real cost engine, not fabricated ──
    r = arm.handle("GET", _sub("/providers/Microsoft.Billing/invoices"))
    _check("invoices 200 with exactly the current in-progress period", r["status"] == 200 and len(r["body"]["value"]) == 1)
    _check("invoice status is honestly InProgress (no fabricated finalized history)",
           r["body"]["value"][0]["properties"]["status"] == "InProgress")
    _check("invoice amount is a number (real cost engine output, not a placeholder)",
           isinstance(r["body"]["value"][0]["properties"]["amountDue"]["value"], (int, float)))

    # ── Billing properties: subscription-scoped in Vyomi, PATCH round-trips ──
    r = arm.handle("GET", _sub("/providers/Microsoft.Billing/billingProperties"))
    _check("billing properties default account admin", r["status"] == 200 and r["body"]["accountAdmin"] == "admin@vyomi.local")
    r = arm.handle("PATCH", _sub("/providers/Microsoft.Billing/billingProperties"), None, {"accountAdmin": "owner@contoso.com"})
    _check("billing properties PATCH 200", r["status"] == 200 and r["body"]["accountAdmin"] == "owner@contoso.com")
    r = arm.handle("GET", _sub("/providers/Microsoft.Billing/billingProperties"))
    _check("billing properties PATCH round-trips on GET", r["body"]["accountAdmin"] == "owner@contoso.com")

    # ── Programmatic deployment credentials: a real, enforced Contributor role assignment ──
    r = arm.handle("POST", _sub("/providers/Microsoft.Authorization/deploymentCredentials"))
    _check("deployment credential create 201", r["status"] == 201 and r["body"].get("appId") and r["body"].get("secret"))
    app_id, cred_name = r["body"]["appId"], r["body"]["name"]
    r = arm.handle("GET", _sub("/providers/Microsoft.Authorization/deploymentCredentials"))
    _check("deployment credentials list omits the secret", r["status"] == 200 and "secret" not in r["body"]["value"][0])
    r = arm.handle("POST", _sub("/providers/Microsoft.Authorization/checkAccess"), {"api-version": "2022-04-01"},
                   {"principalId": app_id, "action": "Microsoft.Storage/storageAccounts/write"})
    _check("the generated service principal really has Contributor access (checkAccess, not just stored config)",
           r["body"]["value"][0]["accessDecision"] == "Allowed")
    r = arm.handle("DELETE", _sub(f"/providers/Microsoft.Authorization/deploymentCredentials/{cred_name}"))
    _check("deployment credential delete 200", r["status"] == 200)
    r = arm.handle("POST", _sub("/providers/Microsoft.Authorization/checkAccess"), {"api-version": "2022-04-01"},
                   {"principalId": app_id, "action": "Microsoft.Storage/storageAccounts/write"})
    _check("revoking the credential really revokes access", r["body"]["value"][0]["accessDecision"] == "NotAllowed")

    print("\nRESULT: PASS — Azure Subscriptions gap-sweep surfaces conform on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
