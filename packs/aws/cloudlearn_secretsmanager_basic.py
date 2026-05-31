from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.secretsmanager.basic",
    "service",
    "1.0.0",
    "aws",
    {
        "protocol": "aws-like",
        "actions": [
            "CreateSecret",
            "GetSecretValue",
            "PutSecretValue",
            "UpdateSecret",
            "DeleteSecret",
            "ListSecrets",
            "ListSecretVersionIds",
            "RotateSecret",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "dataPlane": "HashiCorp Vault (cloudlearn-vault:8200) — KV v2 backed; X-Amz-Target dispatch via vault_routes._aws_secrets_dispatch",
    },
)
