# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""S3 buckets (+ versioning, public access block, encryption, policy) and CloudWatch log groups."""
from __future__ import annotations

import json

from core.tf_export import hcl
from core.tf_export.core import Ctx, exporter, tags_of


def _try(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception:  # noqa: BLE001 - config absent on this bucket
        return None


@exporter(30, "s3")
def export_s3(ctx: Ctx) -> None:
    s3 = ctx.c["s3"]
    for b in s3.list_buckets().get("Buckets", []):
        name = b["Name"]
        t = _try(s3.get_bucket_tagging, Bucket=name)
        tags = tags_of((t or {}).get("TagSet"))
        addr = ctx.add("aws_s3_bucket", name, name, {"bucket": name, "tags": tags or None}, file="storage.tf")
        bucket_ref = hcl.Ref(f"{addr}.id")
        short = addr.split(".", 1)[1]
        v = _try(s3.get_bucket_versioning, Bucket=name) or {}
        if v.get("Status") in ("Enabled", "Suspended"):
            ctx.add("aws_s3_bucket_versioning", name, short, {"bucket": bucket_ref},
                    [("versioning_configuration", {"status": v["Status"]})], file="storage.tf")
        pab = (_try(s3.get_public_access_block, Bucket=name) or {}).get("PublicAccessBlockConfiguration")
        if pab:
            ctx.add("aws_s3_bucket_public_access_block", name, short, {"bucket": bucket_ref, **{
                k: bool(pab.get(c)) for k, c in (("block_public_acls", "BlockPublicAcls"), ("block_public_policy", "BlockPublicPolicy"),
                                                 ("ignore_public_acls", "IgnorePublicAcls"),
                                                 ("restrict_public_buckets", "RestrictPublicBuckets"))}}, file="storage.tf")
        enc = (_try(s3.get_bucket_encryption, Bucket=name) or {}).get("ServerSideEncryptionConfiguration")
        if enc and enc.get("Rules"):
            d = enc["Rules"][0].get("ApplyServerSideEncryptionByDefault", {})
            ctx.add("aws_s3_bucket_server_side_encryption_configuration", name, short, {"bucket": bucket_ref},
                    [("rule", {}, [("apply_server_side_encryption_by_default",
                                    {"sse_algorithm": d.get("SSEAlgorithm"), "kms_master_key_id": d.get("KMSMasterKeyID")})])],
                    file="storage.tf")
        pol = _try(s3.get_bucket_policy, Bucket=name)
        if pol and pol.get("Policy"):
            ctx.add("aws_s3_bucket_policy", name, short, {"bucket": bucket_ref, "policy": hcl.jsonencode(json.loads(pol["Policy"]))},
                    file="storage.tf")


@exporter(31, "log-groups")
def export_log_groups(ctx: Ctx) -> None:
    logs = ctx.c["logs"]
    for g in logs.describe_log_groups().get("logGroups", []):
        name = g["logGroupName"]
        tags = (_try(logs.list_tags_for_resource, resourceArn=g.get("arn", "").removesuffix(":*")) or {}).get("tags") or \
               (_try(logs.list_tags_log_group, logGroupName=name) or {}).get("tags") or {}
        ctx.add("aws_cloudwatch_log_group", name, name.strip("/").replace("/", "_"),
                {"name": name, "retention_in_days": g.get("retentionInDays"), "tags": tags or None}, file="observability.tf")
