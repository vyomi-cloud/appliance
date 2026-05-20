from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.gcp.functions.basic",
    "service",
    "1.0.0",
    "gcp",
    {
        "protocol": "gcp-like",
        "actions": ["Functions.list", "Functions.create", "Functions.get", "Functions.update", "Functions.delete", "Functions.invoke"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
    },
)
