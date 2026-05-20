from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.runtime.python",
    "runtime",
    "1.0.0",
    "agnostic",
    {
        "protocol": "aws-like",
        "actions": ["Deploy", "Invoke", "Restart"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": False,
        "regionAware": False,
    },
)
