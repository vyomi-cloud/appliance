from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.eventbridge.basic",
    "service",
    "1.0.0",
    "aws",
    {
        "protocol": "aws-like",
        "actions": [
            "PutEvents",
            "PutRule",
            "DeleteRule",
            "ListRules",
            "PutTargets",
            "RemoveTargets",
            "CreateEventBus",
            "DeleteEventBus",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "dataPlane": "NATS (cloudlearn-nats:4222) — PutEvents publishes to aws.eventbridge.<bus>.<source> subjects",
    },
)
