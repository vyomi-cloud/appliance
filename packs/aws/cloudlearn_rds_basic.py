from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.rds.basic",
    "service",
    "1.0.0",
    "aws",
    {
        "protocol": "aws-like",
        "actions": [
            "CreateDBInstance",
            "DescribeDBInstances",
            "ModifyDBInstance",
            "DeleteDBInstance",
            "CreateDBSnapshot",
            "RestoreDBInstanceFromDBSnapshot",
            "CreateDBSubnetGroup",
            "CreateDBParameterGroup",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "dataPlane": "metadata-only (Postgres engine reuse for real connections is post-MVP — see [[mvp-backend-stack-shipped]])",
    },
)
