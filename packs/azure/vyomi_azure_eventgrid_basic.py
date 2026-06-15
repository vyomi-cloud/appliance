from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.eventgrid.basic",
    "service",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm+rest",
        "resourceType": "Microsoft.EventGrid/topics",
        "actions": [
            "Topics_CreateOrUpdate",
            "Topics_Get",
            "Topics_Delete",
            "Topics_List",
            "EventSubscriptions_CreateOrUpdate",
            "Events_Publish",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "apiVersion": "2023-12-15-preview",
        "dataPlane": "NATS (cloudlearn-nats:4222) — events publish to azure.eventgrid.<topic> subjects",
        "dataPlaneRoutes": ["/azure-data/eventgrid/{topic}/events"],
    },
)
