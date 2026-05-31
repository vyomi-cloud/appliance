from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.kms.basic",
    "service",
    "1.0.0",
    "aws",
    {
        "protocol": "aws-like",
        "actions": [
            "CreateKey",
            "Encrypt",
            "Decrypt",
            "GenerateDataKey",
            "DescribeKey",
            "ListKeys",
            "CreateAlias",
            "DeleteAlias",
            "ScheduleKeyDeletion",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "dataPlane": "HashiCorp Vault (cloudlearn-vault:8200) — transit engine; X-Amz-Target=TrentService.* dispatch via vault_routes._aws_kms_dispatch",
    },
)
