"""Azure RBAC checkAccess conformance (v2.6.0) — the AWS-SimulatePrincipalPolicy /
GCP-testIamPermissions peer. Role assignments + definitions → an access decision
with wildcard, scope-inheritance, notActions, and explicit-deny semantics.
"""
import json

try:
    from core.iam_store import InMemoryIamStore
    from core import azure_iam_core as az
except ImportError:  # pragma: no cover - Pyodide flat layout
    from iam_store import InMemoryIamStore  # type: ignore
    import azure_iam_core as az  # type: ignore

AUTH = "/providers/Microsoft.Authorization"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or InMemoryIamStore()

    def call(m, p, b=None):
        return az.dispatch(s, m, p, {}, {}, json.dumps(b or {}).encode())

    def check(pid, action, scope):
        r = json.loads(call("POST", f"{AUTH}/checkAccess",
                            {"principalId": pid, "action": action, "scope": scope}).body)
        return r["value"][0]["accessDecision"]

    call("PUT", f"{AUTH}/roleAssignments/ra1",
         {"properties": {"principalId": "alice", "roleName": "Reader", "scope": "/subscriptions/S1"}})
    call("PUT", f"{AUTH}/roleAssignments/ra2",
         {"properties": {"principalId": "bob", "roleName": "Contributor",
                         "scope": "/subscriptions/S1/resourceGroups/RG1"}})

    _check("Reader */read allowed (scope-inherited)",
           check("alice", "Microsoft.Storage/storageAccounts/read", "/subscriptions/S1/resourceGroups/RG1/x") == "Allowed")
    _check("Reader write denied",
           check("alice", "Microsoft.Storage/storageAccounts/write", "/subscriptions/S1/resourceGroups/RG1") == "NotAllowed")
    _check("Contributor write allowed in its RG",
           check("bob", "Microsoft.Storage/storageAccounts/write", "/subscriptions/S1/resourceGroups/RG1/x") == "Allowed")
    _check("Contributor Authorization/*/Delete blocked by notActions",
           check("bob", "Microsoft.Authorization/roleAssignments/Delete", "/subscriptions/S1/resourceGroups/RG1") == "NotAllowed")
    _check("scope isolation — no access to sibling RG2",
           check("bob", "Microsoft.Storage/storageAccounts/write", "/subscriptions/S1/resourceGroups/RG2") == "NotAllowed")

    call("PUT", f"{AUTH}/roleDefinitions/custom1",
         {"properties": {"roleName": "BlobOnly", "permissions": [{"actions": ["Microsoft.Storage/*"], "notActions": []}]}})
    call("PUT", f"{AUTH}/roleAssignments/ra3",
         {"properties": {"principalId": "carol", "roleName": "BlobOnly", "scope": "/subscriptions/S1"}})
    _check("custom role allows", check("carol", "Microsoft.Storage/blob/write", "/subscriptions/S1") == "Allowed")
    call("PUT", f"{AUTH}/roleAssignments/deny1",
         {"properties": {"principalId": "carol", "kind": "deny",
                         "denyActions": ["Microsoft.Storage/blob/write"], "scope": "/subscriptions/S1"}})
    _check("explicit deny wins", check("carol", "Microsoft.Storage/blob/write", "/subscriptions/S1") == "NotAllowed")

    # Entra ID | Properties' "Access management for Azure resources" toggle
    # (azure.entra.security_defaults): Yes really grants "User Access Administrator" at
    # the tenant root ("/"), which checkAccess then honours at ANY subscription scope —
    # the same elevateAccess semantics the real console's radio button triggers.
    _check("dave has no Azure-management access before elevation",
           check("dave", "Microsoft.Authorization/roleAssignments/write", "/subscriptions/S2") == "NotAllowed")
    call("PUT", f"{AUTH}/roleAssignments/elevate-dave",
         {"properties": {"principalId": "dave", "roleName": "User Access Administrator", "scope": "/"}})
    _check("User Access Administrator at '/' grants role-assignment write on any subscription",
           check("dave", "Microsoft.Authorization/roleAssignments/write", "/subscriptions/S2") == "Allowed")
    _check("elevation also covers a resource group under that subscription",
           check("dave", "Microsoft.Authorization/roleAssignments/write", "/subscriptions/S2/resourceGroups/RG9") == "Allowed")
    call("DELETE", f"{AUTH}/roleAssignments/elevate-dave")
    _check("turning the toggle back off revokes the access",
           check("dave", "Microsoft.Authorization/roleAssignments/write", "/subscriptions/S2") == "NotAllowed")

    # Roles and administrators (Entra ID "Roles and administrators" blade): list built-in +
    # custom role definitions with assignment counts, and custom-role create/delete.
    defs = json.loads(call("GET", f"{AUTH}/roleDefinitions").body)["value"]
    names = {d["properties"]["roleName"]: d for d in defs}
    _check("built-in directory roles are listed", "Global Administrator" in names and "User Administrator" in names)
    _check("Owner assignment count reflects live assignments", names["Reader"]["assignmentCount"] == 1)
    _check("custom role (BlobOnly) created via PUT is listed as CustomRole",
           names["BlobOnly"]["properties"]["type"] == "CustomRole" and names["BlobOnly"]["assignmentCount"] == 1)
    _check("built-in role cannot be deleted",
           json.loads(call("DELETE", f"{AUTH}/roleDefinitions/Owner").body)["error"]["code"] == "RoleDefinitionIsBuiltIn")
    _check("custom role can be deleted", call("DELETE", f"{AUTH}/roleDefinitions/BlobOnly").status == 200)
    _check("deleted custom role no longer listed",
           "BlobOnly" not in {d["properties"]["roleName"] for d in json.loads(call("GET", f"{AUTH}/roleDefinitions").body)["value"]})
    assignments = json.loads(call("GET", f"{AUTH}/roleAssignments").body)["value"]
    _check("role assignments are listed", any(a["name"] == "ra1" for a in assignments))

    print("\nAzure RBAC checkAccess conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
