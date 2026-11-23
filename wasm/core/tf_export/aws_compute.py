# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""EC2 instances (+ key pairs, instance profiles, non-root EBS volumes and their attachments)."""
from __future__ import annotations

import base64

from core.tf_export import hcl
from core.tf_export.aws_network import _name_hint
from core.tf_export.core import Ctx, attempt, exporter, paged, tags_of


@exporter(22, "instance-profiles")
def export_instance_profiles(ctx: Ctx) -> None:
    iam = ctx.c["iam"]
    profiles = []
    marker = None
    while True:
        r = iam.list_instance_profiles(**({"Marker": marker} if marker else {}))
        profiles += r.get("InstanceProfiles", [])
        if not r.get("IsTruncated"):
            break
        marker = r.get("Marker")
    for p in sorted(profiles, key=lambda p: p["InstanceProfileName"]):
        roles = p.get("Roles") or []
        attrs = {"name": p["InstanceProfileName"], "path": None if p.get("Path", "/") == "/" else p["Path"],
                 "role": ctx.ref("aws_iam_role", roles[0]["Arn"], "name") if roles else None}
        ctx.add("aws_iam_instance_profile", p["Arn"], p["InstanceProfileName"], attrs, file="iam.tf")
        ctx.alias("aws_iam_instance_profile", p["InstanceProfileName"], ctx.addr[("aws_iam_instance_profile", p["Arn"])])


@exporter(25, "ec2-instances")
def export_instances(ctx: Ctx) -> None:
    ec2 = ctx.c["ec2"]
    kp = attempt(ec2.describe_key_pairs, IncludePublicKey=True) or ec2.describe_key_pairs()
    for k in sorted(kp.get("KeyPairs", []), key=lambda k: k["KeyName"]):
        name = k["KeyName"]
        pub = k.get("PublicKey")
        pub = pub if pub else ctx.variable(f"public_key_{name.replace('-', '_')}", "", f"OpenSSH public key for key pair {name} (the simulator keeps only the fingerprint)", sensitive=False)
        ctx.add("aws_key_pair", name, name, {"key_name": name, "public_key": pub, "tags": tags_of(k.get("Tags")) or None}, file="compute.tf")
    seen: dict[str, dict] = {}  # the simulator can list one instance under two reservations; an instance is exported once
    for page in ec2.get_paginator("describe_instances").paginate():
        for res in page.get("Reservations", []):
            for i in res.get("Instances", []):
                if (i.get("State") or {}).get("Name") not in ("terminated", "shutting-down"):
                    seen.setdefault(i["InstanceId"], i)
    instances = list(seen.values())
    instances.sort(key=lambda i: (tags_of(i.get("Tags")).get("Name", ""), i["InstanceId"]))
    root_vols: set[str] = set()
    for i in instances:
        ctx.reserve("aws_instance", i["InstanceId"], _name_hint(tags_of(i.get("Tags")), i["InstanceId"], f"instance_{i['InstanceType']}"))
    for i in instances:
        iid, tags = i["InstanceId"], tags_of(i.get("Tags"))
        attrs: dict = {"ami": i.get("ImageId"), "instance_type": i.get("InstanceType"),
                       "subnet_id": ctx.ref("aws_subnet", i["SubnetId"]) if i.get("SubnetId") else None,
                       "vpc_security_group_ids": [ctx.ref("aws_security_group", g["GroupId"]) for g in i.get("SecurityGroups", [])] or None,
                       "key_name": ctx.ref("aws_key_pair", i["KeyName"], "key_name") if i.get("KeyName") else None,
                       "monitoring": True if (i.get("Monitoring") or {}).get("State") == "enabled" else None,
                       "ebs_optimized": True if i.get("EbsOptimized") else None}
        prof = (i.get("IamInstanceProfile") or {}).get("Arn")
        if prof:
            attrs["iam_instance_profile"] = ctx.ref("aws_iam_instance_profile", prof, "name") if (("aws_iam_instance_profile", prof) in ctx.addr) \
                else prof.rsplit("/", 1)[-1]
        ud = ((attempt(ec2.describe_instance_attribute, InstanceId=iid, Attribute="userData") or {}).get("UserData") or {}).get("Value")
        blocks: list = []
        name_hint = ctx.addr[("aws_instance", iid)].split(".", 1)[1]
        if ud:
            path = f"ec2/{name_hint}-user-data.sh"
            ctx.files_bin[path] = base64.b64decode(ud)
            attrs["user_data"] = hcl.Ref(f'file("{path}")')
        md = i.get("MetadataOptions") or {}
        if md.get("HttpTokens") == "required" or md.get("HttpEndpoint") == "disabled" or md.get("HttpPutResponseHopLimit") not in (None, 1):
            blocks.append(("metadata_options", {"http_endpoint": md.get("HttpEndpoint"), "http_tokens": md.get("HttpTokens"),
                                                "http_put_response_hop_limit": md.get("HttpPutResponseHopLimit")}))
        root = i.get("RootDeviceName")
        for m in i.get("BlockDeviceMappings", []):
            if m.get("DeviceName") == root and m.get("Ebs"):
                root_vols.add(m["Ebs"]["VolumeId"])
        attrs["tags"] = tags or None
        # root volume details are read after the loop (describe_volumes) and merged in
        i["_root_vol"] = next((m["Ebs"]["VolumeId"] for m in i.get("BlockDeviceMappings", []) if m.get("DeviceName") == root and m.get("Ebs")), None)
        i["_attrs"], i["_blocks"] = attrs, blocks
    vols = {}
    for page in ec2.get_paginator("describe_volumes").paginate():
        for v in page.get("Volumes", []):
            vols[v["VolumeId"]] = v
    for i in instances:
        rv = vols.get(i.get("_root_vol") or "")
        if rv:
            rb = {"volume_size": rv.get("Size"), "volume_type": rv.get("VolumeType"), "encrypted": True if rv.get("Encrypted") else None,
                  "delete_on_termination": next((m["Ebs"].get("DeleteOnTermination") for m in i["BlockDeviceMappings"]
                                                 if m.get("Ebs", {}).get("VolumeId") == rv["VolumeId"]), None)}
            i["_blocks"].insert(0, ("root_block_device", rb))
        ctx.add("aws_instance", i["InstanceId"], "", i["_attrs"], i["_blocks"], file="compute.tf")
    live = {i["InstanceId"] for i in instances}
    for vid in sorted(vols):
        v = vols[vid]
        if vid in root_vols:
            continue
        attrs = {"availability_zone": v.get("AvailabilityZone"), "size": v.get("Size"), "type": v.get("VolumeType") if v.get("VolumeType") != "gp2" else None,
                 "encrypted": True if v.get("Encrypted") else None,
                 "kms_key_id": ctx.ref("aws_kms_key", v["KmsKeyId"], "arn") if v.get("KmsKeyId") else None,
                 "iops": v.get("Iops") if v.get("VolumeType") in ("io1", "io2") or (v.get("VolumeType") == "gp3" and v.get("Iops") not in (None, 3000)) else None,
                 "throughput": v.get("Throughput") if v.get("VolumeType") == "gp3" and v.get("Throughput") not in (None, 125) else None,
                 "snapshot_id": v.get("SnapshotId") or None, "tags": tags_of(v.get("Tags")) or None}
        vaddr = ctx.add("aws_ebs_volume", vid, _name_hint(tags_of(v.get("Tags")), vid, f"volume_{v.get('Size')}gb"), attrs, file="compute.tf")
        for a in sorted(v.get("Attachments", []), key=lambda a: a["InstanceId"]):
            if a["InstanceId"] in live:
                ctx.add("aws_volume_attachment", f"{vid}/{a['InstanceId']}", vaddr.split(".", 1)[1] + "_" + a["Device"].rsplit("/", 1)[-1],
                        {"device_name": a["Device"], "volume_id": hcl.Ref(f"{vaddr}.id"), "instance_id": ctx.ref("aws_instance", a["InstanceId"])}, file="compute.tf")
