from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.gcp.iam.basic",
    "service",
    "1.0.0",
    "gcp",
    {
        "protocol": "gcp-like",
        "actions": ["ListUsers", "ListGroups", "ListRoles", "ListPolicies", "AttachPolicy", "DetachPolicy"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": False,
    },
)
