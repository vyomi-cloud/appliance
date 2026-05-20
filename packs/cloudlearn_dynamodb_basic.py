from __future__ import annotations

from ._shared import build_pack

PACK = build_pack(
    "cloudlearn.dynamodb.basic",
    "service",
    "1.0.0",
    "agnostic",
    {
        "protocol": "aws-like",
        "actions": ["CreateTable", "ListTables", "DescribeTable", "PutItem", "GetItem", "UpdateItem", "DeleteItem", "Query", "Scan", "BatchGetItem", "BatchWriteItem"],
        "requestSchemas": True,
        "responseSchemas": True,
        "errors": True,
        "pagination": True,
        "regionAware": True,
    },
)
