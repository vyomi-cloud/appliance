from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.vpc.basic",
    "service",
    "1.0.0",
    "agnostic",
    {
        "protocol": "aws-like",
        "actions": ["CreateVpc", "CreateSubnet", "CreateSecurityGroup", "CreateRouteTable"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": False,
        "regionAware": True,
    },
)
