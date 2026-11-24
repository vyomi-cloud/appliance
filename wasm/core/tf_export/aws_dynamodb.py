# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""DynamoDB tables: keys, GSIs / LSIs, billing mode, TTL, point-in-time recovery, streams, encryption, tags."""
from __future__ import annotations

from core.tf_export import hcl
from core.tf_export.core import Ctx, attempt, exporter, paged, tags_of


def _projection(idx: dict, out: dict) -> None:
    pr = idx.get("Projection") or {}
    out["projection_type"] = pr.get("ProjectionType") or "ALL"
    out["non_key_attributes"] = sorted(pr.get("NonKeyAttributes") or []) or None


def _keys(schema: list) -> tuple[str | None, str | None]:
    h = next((k["AttributeName"] for k in schema if k["KeyType"] == "HASH"), None)
    r = next((k["AttributeName"] for k in schema if k["KeyType"] == "RANGE"), None)
    return h, r


@exporter(41, "dynamodb")
def export_dynamodb(ctx: Ctx) -> None:
    ddb = ctx.c["dynamodb"]
    names: list[str] = []
    for page in ddb.get_paginator("list_tables").paginate():
        names += page.get("TableNames", [])
    for name in sorted(names):
        t = ddb.describe_table(TableName=name)["Table"]
        arn = t["TableArn"]
        on_demand = (t.get("BillingModeSummary") or {}).get("BillingMode") == "PAY_PER_REQUEST"
        h, r = _keys(t["KeySchema"])
        attrs: dict = {"name": name, "billing_mode": "PAY_PER_REQUEST" if on_demand else None, "hash_key": h, "range_key": r}
        if not on_demand:
            pt = t.get("ProvisionedThroughput") or {}
            attrs["read_capacity"], attrs["write_capacity"] = pt.get("ReadCapacityUnits", 5), pt.get("WriteCapacityUnits", 5)
        if t.get("DeletionProtectionEnabled"):
            attrs["deletion_protection_enabled"] = True
        tc = (t.get("TableClassSummary") or {}).get("TableClass")
        if tc and tc != "STANDARD":
            attrs["table_class"] = tc
        ss = t.get("StreamSpecification") or {}
        if ss.get("StreamEnabled"):
            attrs["stream_enabled"], attrs["stream_view_type"] = True, ss.get("StreamViewType")
        attrs["tags"] = tags_of(paged(ddb.list_tags_of_resource, "Tags", ResourceArn=arn)) or None
        blocks: list = [("attribute", {"name": a["AttributeName"], "type": a["AttributeType"]})
                        for a in sorted(t.get("AttributeDefinitions", []), key=lambda a: a["AttributeName"])]
        for g in sorted(t.get("GlobalSecondaryIndexes") or [], key=lambda g: g["IndexName"]):
            gh, gr = _keys(g["KeySchema"])
            b = {"name": g["IndexName"], "hash_key": gh, "range_key": gr}
            _projection(g, b)
            if not on_demand:
                gp = g.get("ProvisionedThroughput") or {}
                b["read_capacity"], b["write_capacity"] = gp.get("ReadCapacityUnits", 5), gp.get("WriteCapacityUnits", 5)
            blocks.append(("global_secondary_index", b))
        for lsi in sorted(t.get("LocalSecondaryIndexes") or [], key=lambda g: g["IndexName"]):
            _lh, lr = _keys(lsi["KeySchema"])
            b = {"name": lsi["IndexName"], "range_key": lr}
            _projection(lsi, b)
            blocks.append(("local_secondary_index", b))
        ttl = (attempt(ddb.describe_time_to_live, TableName=name) or {}).get("TimeToLiveDescription") or {}
        if ttl.get("TimeToLiveStatus") in ("ENABLED", "ENABLING") and ttl.get("AttributeName"):
            blocks.append(("ttl", {"attribute_name": ttl["AttributeName"], "enabled": True}))
        cb = (attempt(ddb.describe_continuous_backups, TableName=name) or {}).get("ContinuousBackupsDescription") or {}
        if (cb.get("PointInTimeRecoveryDescription") or {}).get("PointInTimeRecoveryStatus") == "ENABLED":
            blocks.append(("point_in_time_recovery", {"enabled": True}))
        sse = t.get("SSEDescription") or {}
        if sse.get("SSEType") == "KMS" and sse.get("Status") in ("ENABLED", "ENABLING", None):
            blocks.append(("server_side_encryption", {"enabled": True, "kms_key_arn": ctx.ref("aws_kms_key", sse.get("KMSMasterKeyArn", ""), "arn")}))
        addr = ctx.add("aws_dynamodb_table", arn, name, attrs, blocks, file="dynamodb.tf")
        ctx.alias("aws_dynamodb_table", name, addr)
