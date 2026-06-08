from __future__ import annotations

from .._shared import build_pack

PACK = build_pack(
    "cloudlearn.azure.servicebus.basic",
    "service",
    "1.0.0",
    "azure",
    {
        "protocol": "azure-arm+rest",
        "resourceType": "Microsoft.ServiceBus/namespaces",
        "actions": [
            "Namespaces_CreateOrUpdate",
            "Namespaces_Get",
            "Namespaces_Delete",
            "Namespaces_List",
            "Queues_CreateOrUpdate",
            "Queues_Send",
            "Queues_Receive",
            "Topics_CreateOrUpdate",
            "Subscriptions_CreateOrUpdate",
        ],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
        "apiVersion": "2022-10-01-preview",
        "dataPlane": "in-process broker under /azure-data/servicebus/{namespace}/{entity}/messages",
        "notes": "REST-only: AMQP protocol is not supported in the CloudLearn simulator. Use HTTP REST endpoints for all send/receive operations.",
    },
)
