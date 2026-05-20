from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.cloudsim.basic",
    "service",
    "1.0.0",
    "agnostic",
    {
        "protocol": "aws-like",
        "actions": ["GetSummary", "Reconcile", "ListEvents"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": False,
        "regionAware": True,
    },
)
