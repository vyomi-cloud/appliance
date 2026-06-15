from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.functionapp.basic",
    "service",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm",
        "resourceType": "Microsoft.Web/sites",
        "actions": [
            "WebApps_CreateOrUpdate",
            "WebApps_Get",
            "WebApps_Delete",
            "WebApps_List",
            "WebApps_Start",
            "WebApps_Stop",
            "WebApps_Restart",
            "WebApps_ListFunctions",
            "WebApps_CreateOrUpdateSlot",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "apiVersion": "2023-12-01",
        "dataPlane": "metadata only (function exec not yet wired; see post-MVP roadmap)",
    },
)
