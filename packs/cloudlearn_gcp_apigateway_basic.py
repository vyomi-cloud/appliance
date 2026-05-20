from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.gcp.apigateway.basic",
    "service",
    "1.0.0",
    "gcp",
    {
        "protocol": "gcp-like",
        "actions": ["Apis.list", "Apis.create", "Apis.get", "Apis.delete", "Apis.deploy", "Apis.stages"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
    },
)
