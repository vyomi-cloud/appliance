from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.vnet.basic",
    "service",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm",
        "resourceType": "Microsoft.Network/virtualNetworks",
        "actions": [
            "VirtualNetworks_CreateOrUpdate",
            "VirtualNetworks_Get",
            "VirtualNetworks_Delete",
            "VirtualNetworks_List",
            "Subnets_CreateOrUpdate",
            "VirtualNetworkPeerings_CreateOrUpdate",
            "NetworkSecurityGroups_CreateOrUpdate",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "apiVersion": "2023-11-01",
        "dataPlane": "topology metadata only (no real packet flow)",
    },
)
