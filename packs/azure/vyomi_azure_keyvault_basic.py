from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.keyvault.basic",
    "service",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm+rest",
        "resourceType": "Microsoft.KeyVault/vaults",
        "actions": [
            "Vaults_CreateOrUpdate",
            "Vaults_Get",
            "Vaults_Delete",
            "Vaults_List",
            "Keys_Encrypt",
            "Keys_Decrypt",
            "Secrets_Get",
            "Secrets_Put",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "apiVersion": "2023-07-01",
        "dataPlane": "HashiCorp Vault (cloudlearn-vault:8200) — transit for keys, KV v2 for secrets",
        "dataPlaneRoutes": [
            "/azure-data/keyvault/{vault}/keys/{key}/encrypt",
            "/azure-data/keyvault/{vault}/keys/{key}/decrypt",
            "/azure-data/keyvault/{vault}/secrets/{secret}",
        ],
    },
)
