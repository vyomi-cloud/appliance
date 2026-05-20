from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.gcp.pubsub.basic",
    "service",
    "1.0.0",
    "gcp",
    {
        "protocol": "gcp-like",
        "actions": ["Topics.list", "Topics.insert", "Subscriptions.list", "Subscriptions.insert", "Topics.publish", "Subscriptions.pull"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
    },
)
