from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.s3.basic",
    "service",
    "1.0.0",
    "agnostic",
    {
        "protocol": "aws-like",
        "actions": ["CreateBucket", "PutObject", "GetObject", "DeleteObject", "ListObjects"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
    },
)
