from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.apim.basic",
    "service",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm",
        "resourceType": "Microsoft.ApiManagement/service",
        "actions": [
            "ApiManagementService_CreateOrUpdate",
            "ApiManagementService_Get",
            "ApiManagementService_Delete",
            "ApiManagementService_List",
            "Api_CreateOrUpdate",
            "Product_CreateOrUpdate",
            "Subscription_CreateOrUpdate",
            "Policy_CreateOrUpdate",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "apiVersion": "2023-05-01-preview",
        "dataPlane": "metadata-only (policy XML stored; not enforced)",
    },
)
