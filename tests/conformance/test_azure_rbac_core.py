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

    print("\nAzure RBAC checkAccess conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
