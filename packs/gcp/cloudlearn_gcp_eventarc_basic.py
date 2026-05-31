from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.gcp.eventarc.basic",
    "service",
    "1.0.0",
    "gcp",
    {
        "protocol": "gcp-like",
        "actions": [
            "projects.locations.triggers.create",
            "projects.locations.triggers.get",
            "projects.locations.triggers.delete",
            "projects.locations.triggers.list",
            "projects.locations.channels.create",
            "projects.locations.channels.publish",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "dataPlane": "NATS (cloudlearn-nats:4222) — trigger.fire and channels:publish push to gcp.eventarc.<trigger> subjects",
    },
)
