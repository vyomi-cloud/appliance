from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.azcli.basic",
    "tooling",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm",
        "actions": ["vm", "storage", "sql", "servicebus", "cosmosdb", "functionapp",
                    "apim", "network", "eventgrid", "keyvault", "role"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "cli": "az",
        "sdk": "azure-cli",
    },
)
