from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.iam.basic",
    "service",
    "1.0.0",
    "agnostic",
    {
        "protocol": "aws-like",
        "actions": ["CreateUser", "CreateRole", "CreatePolicy", "AttachPolicy"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": False,
        "regionAware": False,
    },
)
