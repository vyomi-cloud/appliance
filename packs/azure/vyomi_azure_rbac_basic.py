from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.rbac.basic",
    "service",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm",
        "resourceType": "Microsoft.Authorization/roleAssignments",
        "actions": [
            "RoleAssignments_Create",
            "RoleAssignments_Get",
            "RoleAssignments_Delete",
            "RoleAssignments_List",
            "RoleDefinitions_List",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": False,
        "apiVersion": "2022-04-01",
        "dataPlane": "Cedar policy engine (compiles RBAC assignments → Cedar permit rules; evaluated via /api/iam/evaluate)",
    },
)
