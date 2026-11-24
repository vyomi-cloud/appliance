# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""KMS customer-managed keys (+ rotation, policy) and aliases. AWS-managed keys and keys pending deletion are not exported."""
from __future__ import annotations

import json

from core.tf_export import hcl
from core.tf_export.core import Ctx, attempt, exporter, tags_of


@exporter(15, "kms")
def export_kms(ctx: Ctx) -> None:
    kms = ctx.c["kms"]
    key_ids: list[str] = []
    for page in kms.get_paginator("list_keys").paginate():
        key_ids += [k["KeyId"] for k in page.get("Keys", [])]
    aliases: dict[str, list[str]] = {}
    for page in kms.get_paginator("list_aliases").paginate():
        for a in page.get("Aliases", []):
            if a.get("TargetKeyId") and not a["AliasName"].startswith("alias/aws/"):
                aliases.setdefault(a["TargetKeyId"], []).append(a["AliasName"])
    keys = {}
    for kid in sorted(key_ids):
        md = kms.describe_key(KeyId=kid)["KeyMetadata"]
        if md.get("KeyManager") == "AWS" or md.get("KeyState") in ("PendingDeletion", "PendingReplicaDeletion"):
            continue
        keys[kid] = md
        hint = (sorted(aliases.get(kid, [])) or [md.get("Description") or kid])[0].removeprefix("alias/")
        addr = ctx.reserve("aws_kms_key", md["Arn"], hint)
        ctx.alias("aws_kms_key", kid, addr)
    for kid, md in keys.items():
        attrs: dict = {"description": md.get("Description") or None,
                       "key_usage": md["KeyUsage"] if md.get("KeyUsage") not in (None, "ENCRYPT_DECRYPT") else None,
                       "customer_master_key_spec": md["KeySpec"] if md.get("KeySpec") not in (None, "SYMMETRIC_DEFAULT") else None,
                       "is_enabled": False if md.get("KeyState") == "Disabled" or md.get("Enabled") is False else None,
                       "multi_region": True if md.get("MultiRegion") else None}
        if md.get("KeySpec") in (None, "SYMMETRIC_DEFAULT") and md.get("Origin", "AWS_KMS") == "AWS_KMS":
            if (attempt(kms.get_key_rotation_status, KeyId=kid) or {}).get("KeyRotationEnabled"):
                attrs["enable_key_rotation"] = True
        pol = (attempt(kms.get_key_policy, KeyId=kid, PolicyName="default") or {}).get("Policy")
        if pol:
            attrs["policy"] = hcl.jsonencode(json.loads(pol))
        raw = (attempt(kms.list_resource_tags, KeyId=kid) or {}).get("Tags") or []
        attrs["tags"] = tags_of([{"Key": t["TagKey"], "Value": t["TagValue"]} for t in raw]) or None
        ctx.add("aws_kms_key", md["Arn"], "", attrs, file="kms.tf")  # address was reserved above
    for kid, names in aliases.items():
        if kid not in keys:
            continue
        for n in sorted(names):
            ctx.add("aws_kms_alias", n, n.removeprefix("alias/"), {"name": n, "target_key_id": ctx.ref("aws_kms_key", kid, "key_id")}, file="kms.tf")
