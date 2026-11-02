"""ARM role assignments + built-in roles feed checkAccess (core == Nano): python3 tests/conformance/test_azure_rbac_arm_checkaccess.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core.azure_arm_core import AzureArm  # noqa: E402

fails = 0


def check(name, ok, d=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {str(d)[:300]}"))
    fails += 0 if ok else 1


arm = AzureArm()
S = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
AU = S + "/providers/Microsoft.Authorization"
V = {"api-version": "2022-04-01"}
READER, CONTRIB, BLOBC = "acdd72a7-3385-48ef-bd42-f606fba81ae7", "b24988ac-6180-42a0-ab88-20f7382dd24c", "ba92f5b4-2d11-453d-a403-e96b0029c9fe"
r = arm.handle("GET", AU + "/roleDefinitions", V)
names = [x["properties"]["roleName"] for x in r["body"]["value"]]
check("built-in roleDefinitions list has Owner/Contributor/Reader + data-plane roles", {"Owner", "Contributor", "Reader", "Storage Blob Data Contributor", "Key Vault Secrets User"} <= set(names), names)
check("GET built-in role by GUID", arm.handle("GET", f"{AU}/roleDefinitions/{READER}", V)["body"]["properties"]["roleName"] == "Reader")


def can(principal, action, scope=S):
    r = arm.handle("POST", AU + "/checkAccess", {"api-version": "2018-09-01-preview"},
                   {"subject": {"principalId": principal}, "actions": [{"id": action}], "resource": {"id": scope}})
    return r["body"]["value"][0]


check("no assignment -> NotAllowed", can("p1", "Microsoft.Compute/virtualMachines/read")["accessDecision"] == "NotAllowed")
r = arm.handle("PUT", f"{AU}/roleAssignments/aaaa0001-0000-0000-0000-000000000001", V,
               {"properties": {"roleDefinitionId": f"{AU}/roleDefinitions/{READER}", "principalId": "p1"}})
check("ARM PUT roleAssignment (Reader) accepted", r["status"] in (200, 201), r)
check("Reader: read Allowed", can("p1", "Microsoft.Compute/virtualMachines/read")["accessDecision"] == "Allowed")
check("Reader: write NotAllowed", can("p1", "Microsoft.Compute/virtualMachines/write")["accessDecision"] == "NotAllowed")
arm.handle("PUT", f"{AU}/roleAssignments/aaaa0001-0000-0000-0000-000000000002", V,
           {"properties": {"roleDefinitionId": f"{AU}/roleDefinitions/{CONTRIB}", "principalId": "p2"}})
check("Contributor: write Allowed, role assignment write NotAllowed",
      can("p2", "Microsoft.Compute/virtualMachines/write")["accessDecision"] == "Allowed" and can("p2", "Microsoft.Authorization/roleAssignments/write")["accessDecision"] == "NotAllowed")
arm.handle("PUT", f"{AU}/roleAssignments/aaaa0001-0000-0000-0000-000000000003", V,
           {"properties": {"roleDefinitionId": f"{AU}/roleDefinitions/{BLOBC}", "principalId": "p3"}})
d = can("p3", "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write")
check("Storage Blob Data Contributor: data action Allowed (isDataAction)", d["accessDecision"] == "Allowed" and d["isDataAction"], d)
check("scope inheritance: sub-scope assignment covers a resource", can("p1", "Microsoft.Compute/virtualMachines/read", S + "/resourceGroups/g/providers/Microsoft.Compute/virtualMachines/vm")["accessDecision"] == "Allowed")
rg = S + "/resourceGroups/rgx"
arm.handle("PUT", S + "/resourcegroups/rgx", {"api-version": "2021-04-01"}, {"location": "eastus"})
arm.handle("PUT", f"{AU}/roleDefinitions/cccc0001-0000-0000-0000-000000000009", V,
           {"properties": {"roleName": "VM Starter", "type": "CustomRole", "permissions": [{"actions": ["Microsoft.Compute/virtualMachines/start/action"]}], "assignableScopes": ["/"]}})
arm.handle("PUT", f"{rg}/providers/Microsoft.Authorization/roleAssignments/aaaa0001-0000-0000-0000-000000000004", V,
           {"properties": {"roleDefinitionId": f"{AU}/roleDefinitions/cccc0001-0000-0000-0000-000000000009", "principalId": "p4"}})
check("custom role at RG scope: Allowed inside the RG, not outside",
      can("p4", "Microsoft.Compute/virtualMachines/start/action", rg + "/providers/Microsoft.Compute/virtualMachines/v")["accessDecision"] == "Allowed"
      and can("p4", "Microsoft.Compute/virtualMachines/start/action", S)["accessDecision"] == "NotAllowed")
arm.handle("DELETE", f"{AU}/roleAssignments/aaaa0001-0000-0000-0000-000000000001", V)
check("deleting the assignment revokes access", can("p1", "Microsoft.Compute/virtualMachines/read")["accessDecision"] == "NotAllowed")
sys.exit(1 if fails else 0)
