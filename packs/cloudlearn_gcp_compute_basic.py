from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.gcp.compute.basic",
    "service",
    "1.0.0",
    "gcp",
    {
        "protocol": "gcp-like",
        "actions": ["Instances.list", "Instances.get", "Instances.insert", "Instances.delete", "Instances.start", "Instances.stop", "Instances.reset"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
    },
)
