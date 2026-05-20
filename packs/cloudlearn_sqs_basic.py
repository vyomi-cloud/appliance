from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.sqs.basic",
    "service",
    "1.0.0",
    "agnostic",
    {
        "protocol": "aws-like",
        "actions": ["CreateQueue", "ListQueues", "GetQueueUrl", "GetQueueAttributes", "SetQueueAttributes", "SendMessage", "ReceiveMessage", "DeleteMessage", "ChangeMessageVisibility", "PurgeQueue", "TagQueue", "UntagQueue", "ListQueueTags"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
    },
)
