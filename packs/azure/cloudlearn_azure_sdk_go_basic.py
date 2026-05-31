from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.sdk.go.basic",
    "tooling",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm",
        "actions": ["armcompute", "armstorage", "armsql", "armservicebus", "armcosmos",
                    "armappservice", "armapimanagement", "armnetwork", "armeventgrid",
                    "armkeyvault", "armauthorization"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "language": "go",
        "sdk": "azure-sdk-for-go (github.com/Azure/azure-sdk-for-go/sdk/resourcemanager/*)",
    },
)
