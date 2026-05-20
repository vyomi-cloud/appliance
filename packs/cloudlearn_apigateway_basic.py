from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.apigateway.basic",
    "service",
    "1.0.0",
    "agnostic",
    {
        "protocol": "aws-like",
        "actions": ["CreateRestApi", "CreateResource", "PutMethod", "PutIntegration", "CreateDeployment", "CreateStage"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": False,
        "regionAware": True,
    },
)
