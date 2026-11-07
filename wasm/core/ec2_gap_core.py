# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""EC2 wire-gap operations merged into vpc_core._OPS (v4 wire sweep): the everyday calls boto3 / aws-cli /
Terraform make that the docs generator listed as "not served" — instance / volume / snapshot / image / ENI
attributes, AMI registration + lifecycle flags, IAM-instance-profile associations, ENI private-IP assignment,
EC2 Fleet + Spot Fleet (they really launch instances through the same launch path as RunInstances), launch
template version deletion, EC2 Instance Connect endpoints, event windows, route replacement, VPC endpoint /
peering modification and the account-level EBS/AMI switches.

Every operation reads and writes the SAME shared EC2/VPC model (`vpc_core._model`) the console and
RunInstances use, so it persists on both substrates. No fastapi / boto3 imports — loads under Pyodide.

Honest limits: no real hypervisor, so *ModifyInstanceCpuOptions-style hardware knobs are recorded, not enforced;
fleets launch a bounded number of instances immediately (no capacity pools, no price-driven interruptions);
snapshot "tiers" / fast-snapshot-restore are state flags only."""
from __future__ import annotations

import re
import uuid


def _V():
    from core import vpc_core
    return vpc_core


def _err(code, msg, status=400):
    return _V().VpcError(code, msg, status)


def _x(v):
    return _V()._xml_escape(str(v))


def _ok(action):
    return _V()._envelope(action, "<return>true</return>")


def _bool(v, default=False):
    return default if v is None else str(v).lower() == "true"


def _idx(p, prefix):
    out = {}
    for k, v in p.items():
        mm = re.match(rf"{re.escape(prefix)}\.(\d+)$", k)
        if mm:
            out[int(mm.group(1))] = v
    return [out[i] for i in sorted(out)]


def _gap(m):
    g = m.setdefault("gap", {})
    for k in ("iam_assoc", "fleets", "spot_fleets", "eic_endpoints", "event_windows", "eni_perms", "vol_mods",
              "snap_attrs", "img_flags", "fast_restore", "snap_tier", "addr_attr", "locked_snaps"):
        g.setdefault(k, {})
    g.setdefault("account", {"snapshot_bpa": "unblocked", "image_bpa": "unblocked", "imds_defaults": {},
                             "event_notif": {"InstanceTagAttribute": {"IncludeAllTagsOfInstance": False, "InstanceTagKeys": []}},
                             "spot_datafeed": None})
    return g


def _find_vol(m, vid):
    return _V()._find_volume(m, vid)


def _find_inst(m, iid):
    return _V()._find_instance(m, iid)


def _find_snap(m, sid):
    s = m["snapshots"].get(str(sid))
    if s is None:
        raise _err("InvalidSnapshot.NotFound", f"The snapshot '{sid}' does not exist.")
    return s


def _find_img(m, iid):
    _V()._seed_amis(m)
    i = m["images"].get(str(iid))
    if i is None:
        raise _err("InvalidAMIID.NotFound", f"The image id '[{iid}]' does not exist")
    return i


def _val(p, name):
    """Query-protocol AttributeValue wrapper: Name.Value."""
    return p.get(f"{name}.Value")


# ───────────────────────── instance attributes ─────────────────────────
_INST_ATTRS = {   # API attribute -> (response element, model key, kind)
    "instanceType": ("instanceType", "instance_type", "val"),
    "disableApiTermination": ("disableApiTermination", "termination_protection", "bool"),
    "disableApiStop": ("disableApiStop", "stop_protection", "bool"),
    "instanceInitiatedShutdownBehavior": ("instanceInitiatedShutdownBehavior", "shutdown_behavior", "val"),
    "sourceDestCheck": ("sourceDestCheck", "source_dest_check", "bool"),
    "ebsOptimized": ("ebsOptimized", "ebs_optimized", "bool"),
    "rootDeviceName": ("rootDeviceName", "root_device_name", "val"),
    "kernel": ("kernel", "kernel_id", "val"),
    "ramdisk": ("ramdisk", "ramdisk_id", "val"),
    "userData": ("userData", "user_data", "val"),
    "enaSupport": ("enaSupport", "ena_support", "bool"),
}


def _describe_instance_attribute(store, p):
    m = _V()._model(store)
    inst = _find_inst(m, p.get("InstanceId"))
    attr = str(p.get("Attribute") or "")
    body = f"<instanceId>{_x(inst['id'])}</instanceId>"
    if attr == "groupSet":
        body += "<groupSet>" + "".join(f"<item><groupId>{_x(g)}</groupId></item>" for g in inst.get("sg_ids", [])) + "</groupSet>"
    elif attr == "blockDeviceMapping":
        body += "<blockDeviceMapping>" + "".join(
            f"<item><deviceName>{_x(b['device_name'])}</deviceName><ebs><volumeId>{_x(b['volume_id'])}</volumeId>"
            f"<status>attached</status><deleteOnTermination>{str(b.get('delete_on_termination', True)).lower()}</deleteOnTermination></ebs></item>"
            for b in inst.get("block_devices", [])) + "</blockDeviceMapping>"
    elif attr == "productCodes":
        body += "<productCodes/>"
    elif attr in _INST_ATTRS:
        el, key, kind = _INST_ATTRS[attr]
        v = inst.get(key, True if key == "source_dest_check" else ("stop" if key == "shutdown_behavior" else False if kind == "bool" else ""))
        body += f"<{el}><value>{str(v).lower() if kind == 'bool' else _x(v)}</value></{el}>"
    else:
        raise _err("InvalidParameterValue", f"Value ({attr}) for parameter attribute is invalid.")
    return _V()._envelope("DescribeInstanceAttribute", body)


def _reset_instance_attribute(store, p):
    m = _V()._model(store)
    inst = _find_inst(m, p.get("InstanceId"))
    attr = str(p.get("Attribute") or "")
    if attr == "sourceDestCheck":
        inst["source_dest_check"] = True
    elif attr in ("kernel", "ramdisk"):
        inst.pop("kernel_id" if attr == "kernel" else "ramdisk_id", None)
    else:
        raise _err("InvalidParameterValue", f"Value ({attr}) for parameter attribute is invalid; only sourceDestCheck, kernel and ramdisk can be reset.")
    return _ok("ResetInstanceAttribute")


def _modify_metadata_options(store, p):
    m = _V()._model(store)
    inst = _find_inst(m, p.get("InstanceId"))
    if p.get("HttpTokens"):
        if p["HttpTokens"] not in ("optional", "required"):
            raise _err("InvalidParameterValue", "Value for parameter HttpTokens is invalid; expected optional | required.")
        inst["metadata_tokens"] = p["HttpTokens"]
    if p.get("HttpEndpoint"):
        inst["metadata_endpoint"] = p["HttpEndpoint"]
    for k, key in (("HttpPutResponseHopLimit", "metadata_hops"), ("HttpProtocolIpv6", "metadata_ipv6"), ("InstanceMetadataTags", "metadata_tags")):
        if p.get(k):
            inst[key] = p[k]
    return _V()._envelope("ModifyInstanceMetadataOptions",
                          f"<instanceId>{_x(inst['id'])}</instanceId><instanceMetadataOptions><state>applied</state>"
                          f"<httpTokens>{_x(inst.get('metadata_tokens', 'required'))}</httpTokens>"
                          f"<httpPutResponseHopLimit>{_x(inst.get('metadata_hops', 2))}</httpPutResponseHopLimit>"
                          f"<httpEndpoint>{_x(inst.get('metadata_endpoint', 'enabled'))}</httpEndpoint>"
                          f"<httpProtocolIpv6>{_x(inst.get('metadata_ipv6', 'disabled'))}</httpProtocolIpv6>"
                          f"<instanceMetadataTags>{_x(inst.get('metadata_tags', 'disabled'))}</instanceMetadataTags></instanceMetadataOptions>")


def _modify_credit_spec(store, p):
    m = _V()._model(store)
    ok, bad = [], []
    for k in sorted(k for k in p if re.match(r"InstanceCreditSpecification\.\d+\.InstanceId$", k)):
        n = k.split(".")[1]
        iid = p[k]
        cpu = p.get(f"InstanceCreditSpecification.{n}.CpuCredits", "standard")
        inst = m["instances"].get(iid)
        if inst is None:
            bad.append(f"<item><instanceId>{_x(iid)}</instanceId><errorCode>InvalidInstanceID.NotFound</errorCode><errorMessage>no such instance</errorMessage></item>")
        else:
            inst["credit_spec"] = cpu
            ok.append(f"<item><instanceId>{_x(iid)}</instanceId></item>")
    return _V()._envelope("ModifyInstanceCreditSpecification",
                          f"<successfulInstanceCreditSpecificationSet>{''.join(ok)}</successfulInstanceCreditSpecificationSet>"
                          f"<unsuccessfulInstanceCreditSpecificationSet>{''.join(bad)}</unsuccessfulInstanceCreditSpecificationSet>")


def _describe_credit_specs(store, p):
    m = _V()._model(store)
    ids = _idx(p, "InstanceId")
    rows = [i for i in m["instances"].values() if (not ids or i["id"] in ids) and str(i["instance_type"]).startswith("t")]
    return _V()._envelope("DescribeInstanceCreditSpecifications", "<instanceCreditSpecificationSet>" + "".join(
        f"<item><instanceId>{_x(i['id'])}</instanceId><cpuCredits>{_x(i.get('credit_spec', 'unlimited' if str(i['instance_type']).startswith(('t3', 't4')) else 'standard'))}</cpuCredits></item>"
        for i in rows) + "</instanceCreditSpecificationSet>")


def _modify_placement(store, p):
    m = _V()._model(store)
    inst = _find_inst(m, p.get("InstanceId"))
    if inst["state"] != "stopped":
        raise _err("IncorrectInstanceState", f"The instance '{inst['id']}' is not in the 'stopped' state.")
    if p.get("Tenancy"):
        inst["tenancy"] = p["Tenancy"]
    if "GroupName" in p:
        inst["placement_group"] = p["GroupName"]
    if p.get("HostId"):
        inst["host_id"] = p["HostId"]
    return _ok("ModifyInstancePlacement")


def _modify_maintenance_options(store, p):
    m = _V()._model(store)
    inst = _find_inst(m, p.get("InstanceId"))
    inst["auto_recovery"] = p.get("AutoRecovery", inst.get("auto_recovery", "default"))
    return _V()._envelope("ModifyInstanceMaintenanceOptions",
                          f"<instanceId>{_x(inst['id'])}</instanceId><autoRecovery>{_x(inst['auto_recovery'])}</autoRecovery>")


def _record_only(action):
    """Hardware / network-performance knobs: validated against a real instance and recorded on it."""
    def op(store, p):
        m = _V()._model(store)
        inst = _find_inst(m, p.get("InstanceId"))
        inst.setdefault("options", {})[action] = {k: v for k, v in p.items() if k not in ("Action", "InstanceId", "Version")}
        return _ok(action)
    return op


def _report_instance_status(store, p):
    m = _V()._model(store)
    for iid in _idx(p, "InstanceId"):
        _find_inst(m, iid).setdefault("status_reports", []).append({"status": p.get("Status", "ok"), "reason": _idx(p, "ReasonCode")})
    return _ok("ReportInstanceStatus")


def _instance_type_offerings(store, p):
    V = _V()
    loc_type = str(p.get("LocationType") or "region")
    flt = {}
    for k, v in p.items():
        mm = re.match(r"Filter\.(\d+)\.Name$", k)
        if mm:
            flt[v] = [p[kk] for kk in sorted(p) if kk.startswith(f"Filter.{mm.group(1)}.Value.")]
    items = []
    for t in sorted(V._INSTANCE_TYPES):
        if "instance-type" in flt and not any(re.fullmatch(s.replace(".", r"\.").replace("*", ".*"), t) for s in flt["instance-type"]):
            continue
        if loc_type == "region":
            items.append((t, "us-east-1"))
        else:
            for az in V._AZS:
                if "location" not in flt or az in flt["location"]:
                    items.append((t, az))
    return V._envelope("DescribeInstanceTypeOfferings", "<instanceTypeOfferingSet>" + "".join(
        f"<item><instanceType>{_x(t)}</instanceType><locationType>{'region' if loc_type == 'region' else 'availability-zone'}</locationType><location>{_x(loc)}</location></item>"
        for t, loc in items) + "</instanceTypeOfferingSet>")


def _get_launch_template_data(store, p):
    m = _V()._model(store)
    inst = _find_inst(m, p.get("InstanceId"))
    d = (f"<imageId>{_x(inst['image_id'])}</imageId><instanceType>{_x(inst['instance_type'])}</instanceType>"
         + (f"<keyName>{_x(inst['key_name'])}</keyName>" if inst.get("key_name") else "")
         + f"<ebsOptimized>{str(inst.get('ebs_optimized', True)).lower()}</ebsOptimized>"
         + f"<monitoring><enabled>{str(bool(inst.get('monitoring'))).lower()}</enabled></monitoring>"
         + "<securityGroupIdSet>" + "".join(f"<item>{_x(g)}</item>" for g in inst.get("sg_ids", [])) + "</securityGroupIdSet>"
         + f"<placement><availabilityZone>{_x(inst['az'])}</availabilityZone><tenancy>{_x(inst.get('tenancy', 'default'))}</tenancy></placement>"
         + "<tagSpecificationSet>" + ("<item><resourceType>instance</resourceType>" + _V()._tags_xml(inst.get("tags", {})) + "</item>" if inst.get("tags") else "") + "</tagSpecificationSet>")
    return _V()._envelope("GetLaunchTemplateData", f"<launchTemplateData>{d}</launchTemplateData>")


def _delete_lt_versions(store, p):
    m = _V()._model(store)
    lt = _find_lt(m, p)
    ok, bad = [], []
    for v in _idx(p, "LaunchTemplateVersion"):
        try:
            n = int(v)
        except ValueError:
            n = -1
        key = n if n in lt["versions"] else str(n) if str(n) in lt["versions"] else None
        if key is None or n == int(lt["default_version"]):
            bad.append(f"<item><launchTemplateId>{_x(lt['id'])}</launchTemplateId><launchTemplateName>{_x(lt['name'])}</launchTemplateName><versionNumber>{_x(v)}</versionNumber>"
                       f"<responseError><code>{'launchTemplateVersionDoesNotExist' if key is None else 'unexpectedError'}</code><message>"
                       f"{'version does not exist' if key is None else 'the default version cannot be deleted'}</message></responseError></item>")
        else:
            lt["versions"].pop(key)
            ok.append(f"<item><launchTemplateId>{_x(lt['id'])}</launchTemplateId><launchTemplateName>{_x(lt['name'])}</launchTemplateName><versionNumber>{n}</versionNumber></item>")
    return _V()._envelope("DeleteLaunchTemplateVersions",
                          f"<successfullyDeletedLaunchTemplateVersionSet>{''.join(ok)}</successfullyDeletedLaunchTemplateVersionSet>"
                          f"<unsuccessfullyDeletedLaunchTemplateVersionSet>{''.join(bad)}</unsuccessfullyDeletedLaunchTemplateVersionSet>")


def _find_lt(m, p):
    lt_id, name = p.get("LaunchTemplateId"), p.get("LaunchTemplateName")
    lt = next((t for k, t in m["launch_templates"].items() if (lt_id and k == lt_id) or (name and t["name"] == name)), None)
    if lt is None:
        raise _err("InvalidLaunchTemplateId.NotFound", "At least one of the launch templates specified in the request does not exist.")
    return lt


def _imds_defaults(store, p):
    m = _V()._model(store)
    g = _gap(m)["account"]["imds_defaults"]
    g.update({k: v for k, v in p.items() if k in ("HttpTokens", "HttpPutResponseHopLimit", "HttpEndpoint", "InstanceMetadataTags")})
    return _ok("ModifyInstanceMetadataDefaults")


def _get_imds_defaults(store, p):
    g = _gap(_V()._model(store))["account"]["imds_defaults"]
    return _V()._envelope("GetInstanceMetadataDefaults", "<accountLevel>" + "".join(
        f"<{k[0].lower() + k[1:]}>{_x(v)}</{k[0].lower() + k[1:]}>" for k, v in g.items()) + "</accountLevel>")


def _event_notif(action):
    def op(store, p):
        a = _gap(_V()._model(store))["account"]["event_notif"]["InstanceTagAttribute"]
        if action == "Register":
            a["IncludeAllTagsOfInstance"] = _bool(p.get("InstanceTagAttribute.IncludeAllTagsOfInstance"))
            a["InstanceTagKeys"] = _idx(p, "InstanceTagAttribute.InstanceTagKey")
        elif action == "Deregister":
            if _bool(p.get("InstanceTagAttribute.IncludeAllTagsOfInstance")):
                a["IncludeAllTagsOfInstance"] = False
            a["InstanceTagKeys"] = [k for k in a["InstanceTagKeys"] if k not in _idx(p, "InstanceTagAttribute.InstanceTagKey")]
        inner = (f"<instanceTagAttribute><includeAllTagsOfInstance>{str(a['IncludeAllTagsOfInstance']).lower()}</includeAllTagsOfInstance>"
                 f"<instanceTagKeySet>{''.join(f'<item>{_x(k)}</item>' for k in a['InstanceTagKeys'])}</instanceTagKeySet></instanceTagAttribute>")
        return _V()._envelope(f"{action}InstanceEventNotificationAttributes" if action != "Describe" else "DescribeInstanceEventNotificationAttributes", inner)
    return op


# ───────────────────────── volumes ─────────────────────────
def _describe_volume_attribute(store, p):
    m = _V()._model(store)
    vol = _find_vol(m, p.get("VolumeId"))
    attr = str(p.get("Attribute") or "")
    body = f"<volumeId>{_x(vol['id'])}</volumeId>"
    if attr == "autoEnableIO":
        body += f"<autoEnableIO><value>{str(vol.get('auto_enable_io', False)).lower()}</value></autoEnableIO>"
    elif attr == "productCodes":
        body += "<productCodes/>"
    else:
        raise _err("InvalidParameterValue", f"Value ({attr}) for parameter attribute is invalid.")
    return _V()._envelope("DescribeVolumeAttribute", body)


def _modify_volume_attribute(store, p):
    m = _V()._model(store)
    vol = _find_vol(m, p.get("VolumeId"))
    v = _val(p, "AutoEnableIO")
    if v is not None:
        vol["auto_enable_io"] = _bool(v)
    return _ok("ModifyVolumeAttribute")


def _describe_volume_status(store, p):
    m = _V()._model(store)
    ids = _idx(p, "VolumeId")
    rows = [v for v in m["volumes"].values() if not ids or v["id"] in ids]
    if ids and len(rows) != len(set(ids)):
        raise _err("InvalidVolume.NotFound", "One or more volumes do not exist.")
    return _V()._envelope("DescribeVolumeStatus", "<volumeStatusSet>" + "".join(
        f"<item><volumeId>{_x(v['id'])}</volumeId><availabilityZone>{_x(v['az'])}</availabilityZone>"
        f"<volumeStatus><status>{'impaired' if v.get('io_disabled') else 'ok'}</status><details><item><name>io-enabled</name><status>{'impaired' if v.get('io_disabled') else 'passed'}</status></item>"
        f"<item><name>io-performance</name><status>not-applicable</status></item></details></volumeStatus>"
        f"<eventsSet/><actionsSet/></item>" for v in rows) + "</volumeStatusSet>")


def _enable_volume_io(store, p):
    vol = _find_vol(_V()._model(store), p.get("VolumeId"))
    vol["io_disabled"] = False
    return _ok("EnableVolumeIO")


def _modify_volume_wrap(orig):
    def op(store, p):
        m = _V()._model(store)
        vol = _find_vol(m, p.get("VolumeId"))
        before = {"size": vol["size"], "type": vol["type"], "iops": vol.get("iops"), "throughput": vol.get("throughput")}
        r = orig(store, p)
        _gap(m)["vol_mods"].setdefault(vol["id"], []).append({
            "volume_id": vol["id"], "state": "completed", "progress": 100, "start": _V()._now(), "end": _V()._now(),
            "orig_size": before["size"], "orig_type": before["type"], "orig_iops": before["iops"], "orig_throughput": before["throughput"],
            "target_size": vol["size"], "target_type": vol["type"], "target_iops": vol.get("iops"), "target_throughput": vol.get("throughput")})
        return r
    return op


def _describe_volumes_modifications(store, p):
    m = _V()._model(store)
    ids = _idx(p, "VolumeId")
    out = []
    for vid, mods in _gap(m)["vol_mods"].items():
        if ids and vid not in ids:
            continue
        x = mods[-1]
        out.append(f"<item><volumeId>{_x(vid)}</volumeId><modificationState>{x['state']}</modificationState>"
                   f"<targetSize>{x['target_size']}</targetSize><targetIops>{x['target_iops'] or ''}</targetIops>"
                   f"<targetVolumeType>{_x(x['target_type'])}</targetVolumeType><targetThroughput>{x['target_throughput'] or ''}</targetThroughput>"
                   f"<originalSize>{x['orig_size']}</originalSize><originalIops>{x['orig_iops'] or ''}</originalIops>"
                   f"<originalVolumeType>{_x(x['orig_type'])}</originalVolumeType><progress>{x['progress']}</progress>"
                   f"<startTime>{_x(x['start'])}</startTime><endTime>{_x(x['end'])}</endTime></item>")
    return _V()._envelope("DescribeVolumesModifications", f"<volumeModificationSet>{''.join(out)}</volumeModificationSet>")


# ───────────────────────── snapshots ─────────────────────────
def _snap_perm(m, sid):
    return _gap(m)["snap_attrs"].setdefault(sid, {"users": [], "groups": []})


def _describe_snapshot_attribute(store, p):
    m = _V()._model(store)
    s = _find_snap(m, p.get("SnapshotId"))
    attr = str(p.get("Attribute") or "")
    body = f"<snapshotId>{_x(s['id'])}</snapshotId>"
    if attr == "createVolumePermission":
        a = _snap_perm(m, s["id"])
        body += "<createVolumePermission>" + "".join(f"<item><userId>{_x(u)}</userId></item>" for u in a["users"]) + \
                "".join(f"<item><group>{_x(g)}</group></item>" for g in a["groups"]) + "</createVolumePermission>"
    elif attr == "productCodes":
        body += "<productCodes/>"
    else:
        raise _err("InvalidParameterValue", f"Value ({attr}) for parameter attribute is invalid.")
    return _V()._envelope("DescribeSnapshotAttribute", body)


def _modify_snapshot_attribute(store, p):
    m = _V()._model(store)
    s = _find_snap(m, p.get("SnapshotId"))
    a = _snap_perm(m, s["id"])
    for u in _idx(p, "UserId"):
        if str(p.get("OperationType") or "add") == "remove":
            a["users"] = [x for x in a["users"] if x != u]
        elif u not in a["users"]:
            a["users"].append(u)
    for g in _idx(p, "UserGroup"):
        if str(p.get("OperationType") or "add") == "remove":
            a["groups"] = [x for x in a["groups"] if x != g]
        elif g not in a["groups"]:
            a["groups"].append(g)
    for k, v in p.items():
        mm = re.match(r"CreateVolumePermission\.(Add|Remove)\.\d+\.(UserId|Group)$", k)
        if mm:
            lst = a["users" if mm.group(2) == "UserId" else "groups"]
            if mm.group(1) == "Add" and v not in lst:
                lst.append(v)
            if mm.group(1) == "Remove" and v in lst:
                lst.remove(v)
    s["public"] = "all" in a["groups"]
    return _ok("ModifySnapshotAttribute")


def _reset_snapshot_attribute(store, p):
    m = _V()._model(store)
    s = _find_snap(m, p.get("SnapshotId"))
    _gap(m)["snap_attrs"][s["id"]] = {"users": [], "groups": []}
    s["public"] = False
    return _ok("ResetSnapshotAttribute")


def _create_snapshots(store, p):
    m = _V()._model(store)
    inst = _find_inst(m, p.get("InstanceSpecification.InstanceId"))
    excl_root = _bool(p.get("InstanceSpecification.ExcludeBootVolume"))
    excl_vols = _idx(p, "InstanceSpecification.ExcludeDataVolumeId")
    tags = _V()._parse_tag_specifications(p).get("snapshot", {})
    out = []
    for bd in inst.get("block_devices", []):
        if bd["volume_id"] in excl_vols or (excl_root and bd["device_name"] == inst.get("root_device_name")):
            continue
        vol = _find_vol(m, bd["volume_id"])
        sid = _V()._rid("snap")
        m["snapshots"][sid] = {"id": sid, "volume_id": vol["id"], "volume_size": vol["size"], "description": str(p.get("Description") or ""),
                               "state": "completed", "progress": "100%", "started": _V()._now(), "encrypted": vol.get("encrypted", False),
                               "kms_key_id": vol.get("kms_key_id", ""), "owner_id": _V().OWNER_ID, "tags": dict(tags)}
        vol["snapshot_id"] = sid
        out.append(f"<item><snapshotId>{_x(sid)}</snapshotId><volumeId>{_x(vol['id'])}</volumeId><state>completed</state>"
                   f"<volumeSize>{vol['size']}</volumeSize><startTime>{_x(m['snapshots'][sid]['started'])}</startTime>"
                   f"<ownerId>{_V().OWNER_ID}</ownerId><description>{_x(m['snapshots'][sid]['description'])}</description>"
                   f"<sourceVolume>{_x(vol['id'])}</sourceVolume>{_V()._tags_xml(tags)}</item>")
    if not out:
        raise _err("InvalidParameterValue", "No volumes matched the instance specification.")
    return _V()._envelope("CreateSnapshots", f"<snapshotSet>{''.join(out)}</snapshotSet>")


def _lock_snapshot(store, p):
    m = _V()._model(store)
    s = _find_snap(m, p.get("SnapshotId"))
    mode = str(p.get("LockMode") or "")
    if mode not in ("governance", "compliance"):
        raise _err("InvalidParameterValue", "LockMode must be governance or compliance.")
    s_lock = _gap(m)["locked_snaps"][s["id"]] = {"mode": mode, "duration": p.get("LockDuration"), "cool_off": p.get("CoolOffPeriod"), "since": _V()._now()}
    return _V()._envelope("LockSnapshot", f"<snapshotId>{_x(s['id'])}</snapshotId><lockState>{mode}</lockState><lockDuration>{_x(s_lock['duration'] or '')}</lockDuration>"
                                           f"<lockCreatedOn>{_x(s_lock['since'])}</lockCreatedOn>")


def _unlock_snapshot(store, p):
    m = _V()._model(store)
    s = _find_snap(m, p.get("SnapshotId"))
    lock = _gap(m)["locked_snaps"].get(s["id"])
    if lock is None:
        raise _err("InvalidParameterValue", f"Snapshot {s['id']} is not locked.")
    if lock["mode"] == "compliance":
        raise _err("OperationNotPermitted", "A snapshot locked in compliance mode cannot be unlocked.")
    _gap(m)["locked_snaps"].pop(s["id"])
    return _V()._envelope("UnlockSnapshot", f"<snapshotId>{_x(s['id'])}</snapshotId>")


def _describe_locked_snapshots(store, p):
    m = _V()._model(store)
    return _V()._envelope("DescribeLockedSnapshots", "<snapshotSet>" + "".join(
        f"<item><ownerId>{_V().OWNER_ID}</ownerId><snapshotId>{_x(sid)}</snapshotId><lockState>{l['mode']}</lockState>"
        f"<lockCreatedOn>{_x(l['since'])}</lockCreatedOn></item>" for sid, l in _gap(m)["locked_snaps"].items()) + "</snapshotSet>")


def _delete_snapshot_guard(orig):
    def op(store, p):
        m = _V()._model(store)
        sid = str(p.get("SnapshotId") or "")
        if sid in _gap(m)["locked_snaps"]:
            raise _err("OperationNotPermitted", f"The snapshot {sid} is locked and cannot be deleted.")
        return orig(store, p)
    return op


def _fast_restore(action):
    def op(store, p):
        m = _V()._model(store)
        fr = _gap(m)["fast_restore"]
        azs = _idx(p, "AvailabilityZone")
        succ, fail = [], []
        for sid in _idx(p, "SourceSnapshotId"):
            if sid not in m["snapshots"]:
                fail.append(f"<item><snapshotId>{_x(sid)}</snapshotId><fastSnapshotRestoreStateErrors/></item>")
                continue
            for az in azs:
                key = (sid, az)
                if action == "Enable":
                    fr[f"{sid}|{az}"] = {"snapshot": sid, "az": az, "state": "enabled", "since": _V()._now()}
                else:
                    fr.pop(f"{sid}|{az}", None)
                succ.append(f"<item><snapshotId>{_x(sid)}</snapshotId><availabilityZone>{_x(az)}</availabilityZone>"
                            f"<state>{'enabled' if action == 'Enable' else 'disabled'}</state><ownerId>{_V().OWNER_ID}</ownerId></item>")
        return _V()._envelope(f"{action}FastSnapshotRestores",
                              f"<successful>{''.join(succ)}</successful><unsuccessful>{''.join(fail)}</unsuccessful>")
    return op


def _describe_fast_restores(store, p):
    m = _V()._model(store)
    return _V()._envelope("DescribeFastSnapshotRestores", "<fastSnapshotRestoreSet>" + "".join(
        f"<item><snapshotId>{_x(f['snapshot'])}</snapshotId><availabilityZone>{_x(f['az'])}</availabilityZone><state>enabled</state>"
        f"<ownerId>{_V().OWNER_ID}</ownerId><enablingTime>{_x(f['since'])}</enablingTime></item>" for f in _gap(m)["fast_restore"].values()) + "</fastSnapshotRestoreSet>")


def _snapshot_tier(action):
    def op(store, p):
        m = _V()._model(store)
        s = _find_snap(m, p.get("SnapshotId"))
        t = _gap(m)["snap_tier"]
        if action == "Modify":
            tier = str(p.get("StorageTier") or "archive")
            t[s["id"]] = tier
            return _V()._envelope("ModifySnapshotTier", f"<snapshotId>{_x(s['id'])}</snapshotId><tieringStartTime>{_x(_V()._now())}</tieringStartTime>")
        t[s["id"]] = "standard"
        return _V()._envelope("RestoreSnapshotTier", f"<snapshotId>{_x(s['id'])}</snapshotId><restoreStartTime>{_x(_V()._now())}</restoreStartTime>"
                                                     f"<restoreDuration>{_x(p.get('TemporaryRestoreDays') or '')}</restoreDuration><isPermanentRestore>{str(_bool(p.get('PermanentRestore'))).lower()}</isPermanentRestore>")
    return op


def _describe_snapshot_tier_status(store, p):
    m = _V()._model(store)
    return _V()._envelope("DescribeSnapshotTierStatus", "<snapshotTierStatusSet>" + "".join(
        f"<item><snapshotId>{_x(sid)}</snapshotId><volumeId>{_x(m['snapshots'][sid]['volume_id'])}</volumeId><status>completed</status>"
        f"<ownerId>{_V().OWNER_ID}</ownerId><storageTier>{_x(tier)}</storageTier></item>"
        for sid, tier in _gap(m)["snap_tier"].items() if sid in m["snapshots"]) + "</snapshotTierStatusSet>")


def _bpa(kind):
    key = "snapshot_bpa" if kind == "Snapshot" else "image_bpa"
    tag = "state" if kind == "Snapshot" else "imageBlockPublicAccessState"

    def get(store, p):
        return _V()._envelope(f"Get{kind}BlockPublicAccessState", f"<{tag}>{_gap(_V()._model(store))['account'][key]}</{tag}>")

    def enable(store, p):
        a = _gap(_V()._model(store))["account"]
        a[key] = str(p.get("State") or "block-all-sharing") if kind == "Snapshot" else "block-new-sharing"
        return _V()._envelope(f"Enable{kind}BlockPublicAccess", f"<{'state' if kind == 'Snapshot' else 'imageBlockPublicAccessState'}>{a[key]}</{'state' if kind == 'Snapshot' else 'imageBlockPublicAccessState'}>")

    def disable(store, p):
        a = _gap(_V()._model(store))["account"]
        a[key] = "unblocked"
        return _V()._envelope(f"Disable{kind}BlockPublicAccess", f"<{'state' if kind == 'Snapshot' else 'imageBlockPublicAccessState'}>unblocked</{'state' if kind == 'Snapshot' else 'imageBlockPublicAccessState'}>")
    return get, enable, disable


# ───────────────────────── images ─────────────────────────
def _register_image(store, p):
    m = _V()._model(store)
    _V()._seed_amis(m)
    name = str(p.get("Name") or "")
    if not name:
        raise _err("MissingParameter", "The request must contain the parameter Name")
    if any(i["name"] == name and i["owner_id"] == _V().OWNER_ID for i in m["images"].values()):
        raise _err("InvalidAMIName.Duplicate", f"AMI name {name} is already in use by AMI.")
    bds = []
    for k in sorted(k for k in p if re.match(r"BlockDeviceMapping\.\d+\.DeviceName$", k)):
        n = k.split(".")[1]
        sid = p.get(f"BlockDeviceMapping.{n}.Ebs.SnapshotId")
        if sid:
            _find_snap(m, sid)
        bds.append({"device_name": p[k], "snapshot_id": sid or "",
                    "size": int(p.get(f"BlockDeviceMapping.{n}.Ebs.VolumeSize") or (m["snapshots"][sid]["volume_size"] if sid else 8)),
                    "volume_type": p.get(f"BlockDeviceMapping.{n}.Ebs.VolumeType", "gp3"), "delete_on_termination": _bool(p.get(f"BlockDeviceMapping.{n}.Ebs.DeleteOnTermination"), True)})
    image_id = "ami-" + uuid.uuid4().hex[:17]
    m["images"][image_id] = {
        "id": image_id, "name": name, "description": str(p.get("Description") or ""), "owner_id": _V().OWNER_ID, "public": False, "state": "available",
        "architecture": str(p.get("Architecture") or "x86_64"), "platform": "", "root_device_type": "ebs",
        "root_device_name": str(p.get("RootDeviceName") or "/dev/xvda"), "virtualization_type": str(p.get("VirtualizationType") or "hvm"),
        "creation_date": _V()._now(), "source": "RegisterImage", "tags": {}, "launch_permissions": [], "block_devices": bds}
    return _V()._envelope("RegisterImage", f"<imageId>{_x(image_id)}</imageId>")


def _describe_image_attribute(store, p):
    m = _V()._model(store)
    img = _find_img(m, p.get("ImageId"))
    attr = str(p.get("Attribute") or "")
    body = f"<imageId>{_x(img['id'])}</imageId>"
    if attr == "launchPermission":
        body += "<launchPermission>" + "".join(f"<item><userId>{_x(u)}</userId></item>" for u in img.get("launch_permissions", [])) + \
                ("<item><group>all</group></item>" if img.get("public") else "") + "</launchPermission>"
    elif attr == "description":
        body += f"<description><value>{_x(img.get('description', ''))}</value></description>"
    elif attr == "blockDeviceMapping":
        body += "<blockDeviceMapping>" + "".join(
            f"<item><deviceName>{_x(b['device_name'])}</deviceName><ebs><snapshotId>{_x(b.get('snapshot_id', ''))}</snapshotId><volumeSize>{b.get('size', 8)}</volumeSize>"
            f"<volumeType>{_x(b.get('volume_type', 'gp3'))}</volumeType><deleteOnTermination>{str(b.get('delete_on_termination', True)).lower()}</deleteOnTermination></ebs></item>"
            for b in img.get("block_devices", [])) + "</blockDeviceMapping>"
    elif attr in ("productCodes", "kernel", "ramdisk", "sriovNetSupport", "bootMode", "tpmSupport", "uefiData", "lastLaunchedTime", "imdsSupport"):
        body += f"<{attr}/>" if attr == "productCodes" else f"<{attr}><value>{_x(img.get(attr, ''))}</value></{attr}>"
    else:
        raise _err("InvalidParameterValue", f"Value ({attr}) for parameter attribute is invalid.")
    return _V()._envelope("DescribeImageAttribute", body)


def _reset_image_attribute(store, p):
    img = _find_img(_V()._model(store), p.get("ImageId"))
    if str(p.get("Attribute")) != "launchPermission":
        raise _err("InvalidParameterValue", "Only the launchPermission attribute can be reset.")
    img["launch_permissions"] = []
    img["public"] = False
    return _ok("ResetImageAttribute")


def _image_flag(action, flag, value):
    def op(store, p):
        m = _V()._model(store)
        img = _find_img(m, p.get("ImageId"))
        if flag == "state":
            if value == "disabled" and img["owner_id"] != _V().OWNER_ID:
                raise _err("AuthFailure", "You do not own this image.", 403)
            img["state"] = value
        elif flag == "deprecate":
            if value:
                at = str(p.get("DeprecateAt") or _V()._now())
                img["deprecation_time"] = at
            else:
                img.pop("deprecation_time", None)
        elif flag == "dereg_protection":
            img["dereg_protection"] = value
        return _V()._envelope(action, "<return>true</return>" if flag != "dereg_protection" or not value else "<return>enabled-without-cooldown</return>")
    return op


def _dereg_guard(orig):
    def op(store, p):
        img = _V()._model(store)["images"].get(str(p.get("ImageId") or ""))
        if img is not None and img.get("dereg_protection"):
            raise _err("OperationNotPermitted", f"The image {img['id']} has deregistration protection enabled.")
        return orig(store, p)
    return op


# ───────────────────────── network interfaces / IPs ─────────────────────────
def _find_eni(m, eid):
    e = m["enis"].get(str(eid))
    if e is None:
        raise _err("InvalidNetworkInterfaceID.NotFound", f"The networkInterface ID '{eid}' does not exist")
    return e


def _assign_private_ips(store, p):
    V = _V()
    m = V._model(store)
    e = _find_eni(m, p.get("NetworkInterfaceId"))
    secondary = e.setdefault("secondary_ips", [])
    given = _idx(p, "PrivateIpAddress")
    n = int(p.get("SecondaryPrivateIpAddressCount") or 0)
    new = []
    for ip in given:
        if ip == e["private_ip"] or ip in secondary:
            raise _err("InvalidParameterValue", f"The specified address is already assigned: {ip}")
        new.append(V._allocate_private_ip(m, e["subnet_id"], ip))
    for _ in range(n if not given else 0):
        new.append(V._allocate_private_ip(m, e["subnet_id"], ""))
    secondary.extend(new)
    return V._envelope("AssignPrivateIpAddresses", f"<networkInterfaceId>{_x(e['id'])}</networkInterfaceId>"
                                                     f"<assignedPrivateIpAddressesSet>{''.join(f'<item><privateIpAddress>{_x(i)}</privateIpAddress></item>' for i in new)}</assignedPrivateIpAddressesSet>")


def _unassign_private_ips(store, p):
    e = _find_eni(_V()._model(store), p.get("NetworkInterfaceId"))
    for ip in _idx(p, "PrivateIpAddress"):
        if ip not in e.get("secondary_ips", []):
            raise _err("InvalidParameterValue", f"The specified address is not assigned to the interface: {ip}")
        e["secondary_ips"].remove(ip)
    return _ok("UnassignPrivateIpAddresses")


def _assign_ipv6(store, p):
    import ipaddress
    m = _V()._model(store)
    e = _find_eni(m, p.get("NetworkInterfaceId"))
    given = _idx(p, "Ipv6Addresses")
    n = int(p.get("Ipv6AddressCount") or 0)
    cur = e.setdefault("ipv6", [])
    new = list(given)
    base = int(ipaddress.IPv6Address("2600:1f18:1:0::")) + (len(m["enis"]) << 16)
    for i in range(n if not given else 0):
        new.append(str(ipaddress.IPv6Address(base + len(cur) + i + 1)))
    cur.extend(x for x in new if x not in cur)
    return _V()._envelope("AssignIpv6Addresses", f"<networkInterfaceId>{_x(e['id'])}</networkInterfaceId>"
                                                  f"<assignedIpv6Addresses>{''.join(f'<item>{_x(i)}</item>' for i in new)}</assignedIpv6Addresses>")


def _unassign_ipv6(store, p):
    e = _find_eni(_V()._model(store), p.get("NetworkInterfaceId"))
    gone = _idx(p, "Ipv6Addresses")
    e["ipv6"] = [i for i in e.get("ipv6", []) if i not in gone]
    return _V()._envelope("UnassignIpv6Addresses", f"<networkInterfaceId>{_x(e['id'])}</networkInterfaceId>"
                                                    f"<unassignedIpv6Addresses>{''.join(f'<item>{_x(i)}</item>' for i in gone)}</unassignedIpv6Addresses>")


def _describe_eni_attribute(store, p):
    m = _V()._model(store)
    e = _find_eni(m, p.get("NetworkInterfaceId"))
    attr = str(p.get("Attribute") or "")
    body = f"<networkInterfaceId>{_x(e['id'])}</networkInterfaceId>"
    if attr == "description":
        body += f"<description><value>{_x(e.get('description', ''))}</value></description>"
    elif attr == "groupSet":
        body += "<groupSet>" + "".join(f"<item><groupId>{_x(g)}</groupId></item>" for g in e.get("sg_ids", [])) + "</groupSet>"
    elif attr == "sourceDestCheck":
        body += f"<sourceDestCheck><value>{str(e.get('source_dest_check', True)).lower()}</value></sourceDestCheck>"
    elif attr == "attachment":
        a = e.get("attachment")
        if a:
            body += (f"<attachment><attachmentId>{_x(a.get('id', ''))}</attachmentId><instanceId>{_x(a.get('instance_id', ''))}</instanceId>"
                     f"<deviceIndex>{_x(a.get('device_index', 0))}</deviceIndex><status>attached</status></attachment>")
    else:
        raise _err("InvalidParameterValue", f"Value ({attr}) for parameter attribute is invalid.")
    return _V()._envelope("DescribeNetworkInterfaceAttribute", body)


def _reset_eni_attribute(store, p):
    e = _find_eni(_V()._model(store), p.get("NetworkInterfaceId"))
    if str(p.get("SourceDestCheck") or "") not in ("", "true"):
        raise _err("InvalidParameterValue", "SourceDestCheck can only be reset to true.")
    e["source_dest_check"] = True
    return _ok("ResetNetworkInterfaceAttribute")


def _create_eni_permission(store, p):
    m = _V()._model(store)
    e = _find_eni(m, p.get("NetworkInterfaceId"))
    pid = "eni-perm-" + uuid.uuid4().hex[:17]
    _gap(m)["eni_perms"][pid] = {"id": pid, "eni": e["id"], "account": p.get("AwsAccountId", ""), "service": p.get("AwsService", ""),
                                 "permission": p.get("Permission", "INSTANCE-ATTACH")}
    x = _gap(m)["eni_perms"][pid]
    return _V()._envelope("CreateNetworkInterfacePermission", _perm_xml(x, "interfacePermission"))


def _perm_xml(x, tag="item"):
    return (f"<{tag}><networkInterfacePermissionId>{_x(x['id'])}</networkInterfacePermissionId><networkInterfaceId>{_x(x['eni'])}</networkInterfaceId>"
            f"<awsAccountId>{_x(x['account'])}</awsAccountId><awsService>{_x(x['service'])}</awsService><permission>{_x(x['permission'])}</permission>"
            f"<permissionState><state>GRANTED</state></permissionState></{tag}>")


def _describe_eni_permissions(store, p):
    m = _V()._model(store)
    ids = _idx(p, "NetworkInterfacePermissionId")
    return _V()._envelope("DescribeNetworkInterfacePermissions", "<networkInterfacePermissions>" + "".join(
        _perm_xml(x) for x in _gap(m)["eni_perms"].values() if not ids or x["id"] in ids) + "</networkInterfacePermissions>")


def _delete_eni_permission(store, p):
    m = _V()._model(store)
    pid = str(p.get("NetworkInterfacePermissionId"))
    if pid not in _gap(m)["eni_perms"]:
        raise _err("InvalidPermissionID.NotFound", f"The permission '{pid}' does not exist.")
    _gap(m)["eni_perms"].pop(pid)
    return _V()._envelope("DeleteNetworkInterfacePermission", "<return>true</return>")


# ───────────────────────── IAM instance profile associations ─────────────────────────
def _iam_assoc_xml(a):
    return (f"<item><associationId>{_x(a['id'])}</associationId><instanceId>{_x(a['instance'])}</instanceId>"
            f"<iamInstanceProfile><arn>{_x(a['arn'])}</arn><id>{_x(a['profile_id'])}</id></iamInstanceProfile><state>{a['state']}</state></item>")


def _profile_arn(p):
    arn = p.get("IamInstanceProfile.Arn") or ""
    name = p.get("IamInstanceProfile.Name") or ""
    if not arn and not name:
        raise _err("MissingParameter", "The request must contain the parameter IamInstanceProfile")
    if not arn:
        arn = f"arn:aws:iam::{_V().OWNER_ID}:instance-profile/{name}"
    return arn


def _associate_iam_profile(store, p):
    m = _V()._model(store)
    inst = _find_inst(m, p.get("InstanceId"))
    a = _gap(m)["iam_assoc"]
    if any(x["instance"] == inst["id"] and x["state"] == "associated" for x in a.values()):
        raise _err("IncorrectState", f"There is an existing association for instance {inst['id']}")
    arn = _profile_arn(p)
    aid = "iip-assoc-" + uuid.uuid4().hex[:17]
    a[aid] = {"id": aid, "instance": inst["id"], "arn": arn, "profile_id": "AIPA" + uuid.uuid4().hex[:17].upper(), "state": "associated"}
    inst["iam_instance_profile"] = arn
    return _V()._envelope("AssociateIamInstanceProfile", "<iamInstanceProfileAssociation>" + _iam_assoc_xml(a[aid])[6:-7] + "</iamInstanceProfileAssociation>")


def _describe_iam_profile_assocs(store, p):
    m = _V()._model(store)
    ids = _idx(p, "AssociationId")
    flt = {}
    for k, v in p.items():
        mm = re.match(r"Filter\.(\d+)\.Name$", k)
        if mm:
            flt[v] = [p[kk] for kk in sorted(p) if kk.startswith(f"Filter.{mm.group(1)}.Value.")]
    rows = [a for a in _gap(m)["iam_assoc"].values() if a["state"] == "associated" and (not ids or a["id"] in ids)
            and ("instance-id" not in flt or a["instance"] in flt["instance-id"])]
    return _V()._envelope("DescribeIamInstanceProfileAssociations", "<iamInstanceProfileAssociationSet>" + "".join(_iam_assoc_xml(a) for a in rows) + "</iamInstanceProfileAssociationSet>")


def _disassociate_iam_profile(store, p):
    m = _V()._model(store)
    a = _gap(m)["iam_assoc"].get(str(p.get("AssociationId")))
    if a is None or a["state"] != "associated":
        raise _err("InvalidAssociationID.NotFound", f"An association with ID '{p.get('AssociationId')}' does not exist.")
    a["state"] = "disassociated"
    inst = m["instances"].get(a["instance"])
    if inst:
        inst["iam_instance_profile"] = ""
    return _V()._envelope("DisassociateIamInstanceProfile", "<iamInstanceProfileAssociation>" + _iam_assoc_xml({**a, "state": "disassociating"})[6:-7] + "</iamInstanceProfileAssociation>")


def _replace_iam_profile(store, p):
    m = _V()._model(store)
    a = _gap(m)["iam_assoc"].get(str(p.get("AssociationId")))
    if a is None or a["state"] != "associated":
        raise _err("InvalidAssociationID.NotFound", f"An association with ID '{p.get('AssociationId')}' does not exist.")
    a["arn"] = _profile_arn(p)
    a["profile_id"] = "AIPA" + uuid.uuid4().hex[:17].upper()
    if a["instance"] in m["instances"]:
        m["instances"][a["instance"]]["iam_instance_profile"] = a["arn"]
    return _V()._envelope("ReplaceIamInstanceProfileAssociation", "<iamInstanceProfileAssociation>" + _iam_assoc_xml(a)[6:-7] + "</iamInstanceProfileAssociation>")


# ───────────────────────── routes / VPC ─────────────────────────
def _replace_route(store, p):
    m = _V()._model(store)
    rt = m["route_tables"].get(str(p.get("RouteTableId")))
    if rt is None:
        raise _err("InvalidRouteTableID.NotFound", f"Route table {p.get('RouteTableId')} not found.")
    dest = str(p.get("DestinationCidrBlock") or p.get("DestinationIpv6CidrBlock") or p.get("DestinationPrefixListId") or "")
    route = next((r for r in rt["routes"] if r["dest"] == dest), None)
    if route is None:
        raise _err("InvalidParameterValue", f"no route with destination-cidr-block {dest} in route table {rt['id']}")
    target = str(p.get("GatewayId") or p.get("NatGatewayId") or p.get("VpcPeeringConnectionId") or p.get("TransitGatewayId")
                 or p.get("NetworkInterfaceId") or p.get("InstanceId") or p.get("EgressOnlyInternetGatewayId") or "")
    if not target:
        raise _err("MissingParameter", "The request must contain exactly one of gatewayId, natGatewayId, networkInterfaceId, vpcPeeringConnectionId or instanceId")
    if target.startswith("i-"):
        _find_inst(m, target)
    elif target.startswith("eni-"):
        _find_eni(m, target)
    route["target"] = target
    return _ok("ReplaceRoute")


def _reject_peering(store, p):
    m = _V()._model(store)
    pc = m["peering_connections"].get(str(p.get("VpcPeeringConnectionId")))
    if pc is None:
        raise _err("InvalidVpcPeeringConnectionID.NotFound", f"The vpcPeeringConnection ID '{p.get('VpcPeeringConnectionId')}' does not exist.")
    if pc.get("status", pc.get("state")) not in ("pending-acceptance", "pending_acceptance"):
        raise _err("InvalidStateTransition", f"Peering connection {pc.get('id')} is not in the pending-acceptance state.")
    for k in ("status", "state"):
        if k in pc:
            pc[k] = "rejected"
    pc.setdefault("status", "rejected")
    return _ok("RejectVpcPeeringConnection")


def _modify_peering_options(store, p):
    m = _V()._model(store)
    pc = m["peering_connections"].get(str(p.get("VpcPeeringConnectionId")))
    if pc is None:
        raise _err("InvalidVpcPeeringConnectionID.NotFound", f"The vpcPeeringConnection ID '{p.get('VpcPeeringConnectionId')}' does not exist.")
    out = {}
    for side, tag in (("Accepter", "accepterPeeringConnectionOptions"), ("Requester", "requesterPeeringConnectionOptions")):
        vals = {k.split(".", 2)[2]: _bool(v) for k, v in p.items() if k.startswith(f"{side}PeeringConnectionOptions.")}
        pc.setdefault("options", {}).setdefault(side, {}).update(vals)
        o = pc["options"][side]
        out[side] = (f"<{tag}><allowDnsResolutionFromRemoteVpc>{str(o.get('AllowDnsResolutionFromRemoteVpc', False)).lower()}</allowDnsResolutionFromRemoteVpc>"
                     f"<allowEgressFromLocalClassicLinkToRemoteVpc>false</allowEgressFromLocalClassicLinkToRemoteVpc>"
                     f"<allowEgressFromLocalVpcToRemoteClassicLink>false</allowEgressFromLocalVpcToRemoteClassicLink></{tag}>")
    return _V()._envelope("ModifyVpcPeeringConnectionOptions", out["Requester"] + out["Accepter"])


def _modify_vpc_endpoint(store, p):
    m = _V()._model(store)
    ep = m["vpc_endpoints"].get(str(p.get("VpcEndpointId")))
    if ep is None:
        raise _err("InvalidVpcEndpointId.NotFound", f"The Vpc Endpoint Id '{p.get('VpcEndpointId')}' does not exist")
    for add_k, key in (("AddRouteTableId", "route_table_ids"), ("AddSubnetId", "subnet_ids"), ("AddSecurityGroupId", "security_group_ids")):
        for v in _idx(p, add_k):
            ep.setdefault(key, [])
            if v not in ep[key]:
                ep[key].append(v)
    for rm_k, key in (("RemoveRouteTableId", "route_table_ids"), ("RemoveSubnetId", "subnet_ids"), ("RemoveSecurityGroupId", "security_group_ids")):
        gone = _idx(p, rm_k)
        if gone:
            ep[key] = [x for x in ep.get(key, []) if x not in gone]
    if p.get("PolicyDocument"):
        ep["policy_document"] = p["PolicyDocument"]
    if p.get("PrivateDnsEnabled") is not None:
        ep["private_dns_enabled"] = _bool(p["PrivateDnsEnabled"])
    return _ok("ModifyVpcEndpoint")


def _describe_endpoint_services(store, p):
    m = _V()._model(store)
    names = [f"com.amazonaws.us-east-1.{s}" for s in ("s3", "dynamodb", "ec2", "sqs", "sns", "kms", "secretsmanager", "ssm", "lambda", "logs", "monitoring", "sts", "ecr.api", "ecr.dkr", "ecs", "events", "kinesis-streams", "states", "rds")]
    custom = [c for c in (m.get("vpc_endpoint_services") or {}).values()]
    wanted = _idx(p, "ServiceName")
    rows = [n for n in names if not wanted or n in wanted]
    sset = "".join(
        f"<item><serviceName>{_x(n)}</serviceName><serviceType><item><serviceType>{'Gateway' if n.endswith(('.s3', '.dynamodb')) else 'Interface'}</serviceType></item></serviceType>"
        f"<availabilityZoneSet>{''.join(f'<item>{a}</item>' for a in _V()._AZS)}</availabilityZoneSet><owner>amazon</owner>"
        f"<baseEndpointDnsNameSet><item>{_x(n.split('.', 3)[-1])}.{_x(n.split('.')[2])}.vpce.amazonaws.com</item></baseEndpointDnsNameSet>"
        f"<privateDnsName>{_x(n.split('.', 3)[-1])}.{_x(n.split('.')[2])}.amazonaws.com</privateDnsName><vpcEndpointPolicySupported>true</vpcEndpointPolicySupported>"
        f"<acceptanceRequired>false</acceptanceRequired><managesVpcEndpoints>false</managesVpcEndpoints></item>" for n in rows)
    names_xml = "".join(f"<item>{_x(n)}</item>" for n in rows)
    return _V()._envelope("DescribeVpcEndpointServices", f"<serviceNameSet>{names_xml}</serviceNameSet><serviceDetailSet>{sset}</serviceDetailSet>")


def _modify_vpc_tenancy(store, p):
    m = _V()._model(store)
    vpc = m["vpcs"].get(str(p.get("VpcId")))
    if vpc is None:
        raise _err("InvalidVpcID.NotFound", f"The vpc ID '{p.get('VpcId')}' does not exist")
    if str(p.get("InstanceTenancy")) != "default":
        raise _err("InvalidParameterValue", "InstanceTenancy can only be changed to default.")
    vpc["tenancy"] = "default"
    vpc["instance_tenancy"] = "default"
    return _ok("ModifyVpcTenancy")


def _create_default_vpc(store, p):
    m = _V()._model(store)
    if any(v.get("default") for v in m["vpcs"].values()):
        raise _err("DefaultVpcAlreadyExists", "A Default VPC already exists for this account in this region.")
    vpc_id, _, _ = _V()._ensure_default_network(m)
    return _V()._envelope("CreateDefaultVpc", "<vpc>" + _V()._vpc_xml(m["vpcs"][vpc_id]).replace("<item>", "").replace("</item>", "") + "</vpc>") \
        if hasattr(_V(), "_vpc_xml") else _V()._envelope("CreateDefaultVpc", f"<vpc><vpcId>{_x(vpc_id)}</vpcId><isDefault>true</isDefault></vpc>")


def _create_default_subnet(store, p):
    V = _V()
    m = V._model(store)
    az = str(p.get("AvailabilityZone") or "")
    if az not in V._AZS:
        raise _err("InvalidParameterValue", f"Invalid availability zone: [{az}]")
    vpc_id, _, _ = V._ensure_default_network(m)
    sn = next((s for s in m["subnets"].values() if s["vpc_id"] == vpc_id and s.get("az") == az), None)
    if sn is None:
        raise _err("InvalidParameterValue", f"No default subnet could be created in {az}.")
    raise _err("DefaultSubnetAlreadyExistsInAvailabilityZone", f"A Default Subnet already exists in Availability Zone {az}.")


# ───────────────────────── EC2 Fleet / Spot Fleet ─────────────────────────
def _lt_spec_data(m, p, prefix):
    """Resolve `<prefix>.LaunchTemplateId|Name|Version` to the flattened launch parameters stored on the template."""
    lt_id = p.get(f"{prefix}.LaunchTemplateId")
    name = p.get(f"{prefix}.LaunchTemplateName")
    if not lt_id and not name:
        return {}
    lt = _find_lt(m, {"LaunchTemplateId": lt_id, "LaunchTemplateName": name})
    ver = str(p.get(f"{prefix}.Version") or "$Default")
    n = lt["default_version"] if ver == "$Default" else lt["latest_version"] if ver == "$Latest" else int(ver)
    v = lt["versions"].get(n) or lt["versions"].get(str(n))
    if v is None:
        raise _err("InvalidLaunchTemplateId.VersionNotFound", f"Could not find launch template version {ver}.")
    return dict(v["data"])


def _launch_capacity(m, base, overrides_list, n, tags):
    V = _V()
    out = []
    for i in range(n):
        ov = overrides_list[i % len(overrides_list)] if overrides_list else {}
        prm = {**base, **ov}
        inst = V._launch_one(m, prm, {"instance": dict(tags)} if tags else {}, i)
        if tags:
            inst.setdefault("tags", {}).update(tags)
        out.append(inst)
    return out


def _create_fleet(store, p):
    V = _V()
    m = V._model(store)
    g = _gap(m)
    ftype = str(p.get("Type") or "maintain")
    target = int(p.get("TargetCapacitySpecification.TotalTargetCapacity") or 0)
    if target < 0 or not any(k.startswith("LaunchTemplateConfigs.") for k in p):
        raise _err("MissingParameter", "The request must contain the parameter LaunchTemplateConfigs")
    spot_n = int(p.get("TargetCapacitySpecification.SpotTargetCapacity") or 0)
    default_type = str(p.get("TargetCapacitySpecification.DefaultTargetCapacityType") or "on-demand")
    tags = V._parse_tag_specifications(p).get("instance", {})
    fleet_id = "fleet-" + uuid.uuid4().hex[:8] + "-" + uuid.uuid4().hex[:4]
    launched, errors = [], []
    insts = []
    cfgs = sorted({int(re.match(r"LaunchTemplateConfigs\.(\d+)\.", k).group(1)) for k in p if re.match(r"LaunchTemplateConfigs\.\d+\.", k)})
    for c in cfgs:
        base = _lt_spec_data(m, p, f"LaunchTemplateConfigs.{c}.LaunchTemplateSpecification")
        ovs = []
        for o in sorted({int(re.match(rf"LaunchTemplateConfigs\.{c}\.Overrides\.(\d+)\.", k).group(1)) for k in p if re.match(rf"LaunchTemplateConfigs\.{c}\.Overrides\.\d+\.", k)}):
            pre = f"LaunchTemplateConfigs.{c}.Overrides.{o}."
            ov = {}
            for src, dst in (("InstanceType", "InstanceType"), ("SubnetId", "SubnetId"), ("ImageId", "ImageId"), ("AvailabilityZone", "Placement.AvailabilityZone")):
                if p.get(pre + src):
                    ov[dst] = p[pre + src]
            ovs.append(ov)
        n = target if len(cfgs) == 1 else max(1, target // len(cfgs))
        if n > 50:
            raise _err("InvalidParameterValue", "TargetCapacity above 50 is not supported by the simulator.")
        try:
            made = _launch_capacity(m, base, ovs, n, tags)
        except _V().VpcError as e:
            errors.append(f"<item><lifecycle>{'spot' if default_type == 'spot' else 'on-demand'}</lifecycle><errorCode>{_x(e.code)}</errorCode><errorMessage>{_x(e.message)}</errorMessage></item>")
            continue
        for ins in made:
            if default_type == "spot":
                ins["lifecycle"] = "spot"
            ins["fleet_id"] = fleet_id
        insts.extend(made)
    g["fleets"][fleet_id] = {"id": fleet_id, "type": ftype, "target": target, "state": "active" if ftype == "maintain" else "fulfilled",
                             "created": V._now(), "instances": [i["id"] for i in insts], "default_type": default_type,
                             "terminate": _bool(p.get("TerminateInstancesWithExpiration")), "tags": V._parse_tag_specifications(p).get("fleet", {}),
                             "spot_target": spot_n}
    inst_xml = ""
    if ftype == "instant":
        by = {}
        for i in insts:
            by.setdefault(i["instance_type"], []).append(i["id"])
        inst_xml = "<fleetInstanceSet>" + "".join(
            f"<item><lifecycle>{'spot' if default_type == 'spot' else 'on-demand'}</lifecycle><instanceIds>{''.join(f'<item>{x}</item>' for x in ids)}</instanceIds><instanceType>{_x(t)}</instanceType></item>"
            for t, ids in by.items()) + "</fleetInstanceSet>"
    return V._envelope("CreateFleet", f"<fleetId>{fleet_id}</fleetId><errorSet>{''.join(errors)}</errorSet>{inst_xml or '<fleetInstanceSet/>'}")


def _fleet_xml(f, m):
    live = [i for i in f["instances"] if m["instances"].get(i, {}).get("state") in ("pending", "running")]
    return (f"<item><fleetId>{f['id']}</fleetId><fleetState>{f['state']}</fleetState><createTime>{_x(f['created'])}</createTime>"
            f"<type>{f['type']}</type><targetCapacitySpecification><totalTargetCapacity>{f['target']}</totalTargetCapacity>"
            f"<defaultTargetCapacityType>{f['default_type']}</defaultTargetCapacityType></targetCapacitySpecification>"
            f"<fulfilledCapacity>{len(live)}.0</fulfilledCapacity><fulfilledOnDemandCapacity>{len(live) if f['default_type'] != 'spot' else 0}.0</fulfilledOnDemandCapacity>"
            f"<terminateInstancesWithExpiration>{str(f['terminate']).lower()}</terminateInstancesWithExpiration>{_V()._tags_xml(f.get('tags', {}))}</item>")


def _describe_fleets(store, p):
    m = _V()._model(store)
    ids = _idx(p, "FleetId")
    rows = [f for f in _gap(m)["fleets"].values() if not ids or f["id"] in ids]
    return _V()._envelope("DescribeFleets", f"<fleetSet>{''.join(_fleet_xml(f, m) for f in rows)}</fleetSet>")


def _describe_fleet_instances(store, p):
    m = _V()._model(store)
    f = _gap(m)["fleets"].get(str(p.get("FleetId")))
    if f is None:
        raise _err("InvalidFleetId.NotFound", f"The fleet id '{p.get('FleetId')}' does not exist")
    return _V()._envelope("DescribeFleetInstances", "<activeInstanceSet>" + "".join(
        f"<item><instanceId>{_x(i)}</instanceId><instanceType>{_x(m['instances'][i]['instance_type'])}</instanceType><instanceHealth>healthy</instanceHealth></item>"
        for i in f["instances"] if m["instances"].get(i, {}).get("state") in ("pending", "running")) + f"</activeInstanceSet><fleetId>{f['id']}</fleetId>")


def _modify_fleet(store, p):
    m = _V()._model(store)
    f = _gap(m)["fleets"].get(str(p.get("FleetId")))
    if f is None:
        raise _err("InvalidFleetId.NotFound", f"The fleet id '{p.get('FleetId')}' does not exist")
    if p.get("TargetCapacitySpecification.TotalTargetCapacity"):
        f["target"] = int(p["TargetCapacitySpecification.TotalTargetCapacity"])
    return _ok("ModifyFleet")


def _delete_fleets(store, p):
    m = _V()._model(store)
    term = _bool(p.get("TerminateInstances"))
    ok, bad = [], []
    for fid in _idx(p, "FleetId"):
        f = _gap(m)["fleets"].get(fid)
        if f is None:
            bad.append(f"<item><fleetId>{_x(fid)}</fleetId><error><code>fleetIdDoesNotExist</code><message>The fleet id does not exist</message></error></item>")
            continue
        f["state"] = "deleted_terminating" if term else "deleted_running"
        if term:
            for iid in f["instances"]:
                i = m["instances"].get(iid)
                if i and i["state"] not in ("terminated", "shutting-down"):
                    _V()._instance_state_change(store, {"InstanceId.1": iid}, "terminate", "terminated")
            f["state"] = "deleted_terminating"
        ok.append(f"<item><fleetId>{fid}</fleetId><currentFleetState>{f['state']}</currentFleetState><previousFleetState>active</previousFleetState></item>")
    return _V()._envelope("DeleteFleets", f"<successfulFleetDeletionSet>{''.join(ok)}</successfulFleetDeletionSet><unsuccessfulFleetDeletionSet>{''.join(bad)}</unsuccessfulFleetDeletionSet>")


def _request_spot_fleet(store, p):
    V = _V()
    m = V._model(store)
    cfg = "SpotFleetRequestConfig."
    target = int(p.get(cfg + "TargetCapacity") or 0)
    if not target:
        raise _err("MissingParameter", "The request must contain the parameter SpotFleetRequestConfig.TargetCapacity")
    if target > 50:
        raise _err("InvalidParameterValue", "TargetCapacity above 50 is not supported by the simulator.")
    sid = "sfr-" + str(uuid.uuid4())
    insts = []
    cfgs = sorted({int(re.match(rf"{re.escape(cfg)}LaunchTemplateConfigs\.(\d+)\.", k).group(1)) for k in p if re.match(rf"{re.escape(cfg)}LaunchTemplateConfigs\.\d+\.", k)})
    if cfgs:
        base = _lt_spec_data(m, p, f"{cfg}LaunchTemplateConfigs.{cfgs[0]}.LaunchTemplateSpecification")
        ovs = []
        for o in sorted({int(re.match(rf"{re.escape(cfg)}LaunchTemplateConfigs\.{cfgs[0]}\.Overrides\.(\d+)\.", k).group(1)) for k in p if re.match(rf"{re.escape(cfg)}LaunchTemplateConfigs\.{cfgs[0]}\.Overrides\.\d+\.", k)}):
            pre = f"{cfg}LaunchTemplateConfigs.{cfgs[0]}.Overrides.{o}."
            ovs.append({d: p[pre + s] for s, d in (("InstanceType", "InstanceType"), ("SubnetId", "SubnetId")) if p.get(pre + s)})
        insts = _launch_capacity(m, base, ovs, target, {})
    else:
        lsp = sorted({int(re.match(rf"{re.escape(cfg)}LaunchSpecifications\.(\d+)\.", k).group(1)) for k in p if re.match(rf"{re.escape(cfg)}LaunchSpecifications\.\d+\.", k)})
        if not lsp:
            raise _err("MissingParameter", "The request must contain LaunchTemplateConfigs or LaunchSpecifications")
        ovs = [{d: p[f"{cfg}LaunchSpecifications.{n}.{s}"] for s, d in (("ImageId", "ImageId"), ("InstanceType", "InstanceType"), ("SubnetId", "SubnetId"), ("KeyName", "KeyName")) if p.get(f"{cfg}LaunchSpecifications.{n}.{s}")} for n in lsp]
        insts = _launch_capacity(m, {}, ovs, target, {})
    for i in insts:
        i["lifecycle"] = "spot"
        i["spot_fleet_id"] = sid
    _gap(m)["spot_fleets"][sid] = {"id": sid, "target": target, "state": "active", "created": V._now(), "instances": [i["id"] for i in insts],
                                   "type": str(p.get(cfg + "Type") or "maintain"), "role": str(p.get(cfg + "IamFleetRole") or ""),
                                   "alloc": str(p.get(cfg + "AllocationStrategy") or "lowestPrice")}
    return V._envelope("RequestSpotFleet", f"<spotFleetRequestId>{sid}</spotFleetRequestId>")


def _describe_spot_fleet_requests(store, p):
    m = _V()._model(store)
    ids = _idx(p, "SpotFleetRequestId")
    rows = [f for f in _gap(m)["spot_fleets"].values() if not ids or f["id"] in ids]
    return _V()._envelope("DescribeSpotFleetRequests", "<spotFleetRequestConfigSet>" + "".join(
        f"<item><spotFleetRequestId>{f['id']}</spotFleetRequestId><spotFleetRequestState>{f['state']}</spotFleetRequestState><createTime>{_x(f['created'])}</createTime>"
        f"<spotFleetRequestConfig><targetCapacity>{f['target']}</targetCapacity><iamFleetRole>{_x(f['role'])}</iamFleetRole><allocationStrategy>{_x(f['alloc'])}</allocationStrategy>"
        f"<type>{f['type']}</type><fulfilledCapacity>{sum(1 for i in f['instances'] if m['instances'].get(i, {}).get('state') in ('pending', 'running'))}.0</fulfilledCapacity></spotFleetRequestConfig></item>"
        for f in rows) + "</spotFleetRequestConfigSet>")


def _describe_spot_fleet_instances(store, p):
    m = _V()._model(store)
    f = _gap(m)["spot_fleets"].get(str(p.get("SpotFleetRequestId")))
    if f is None:
        raise _err("InvalidSpotFleetRequestId.NotFound", f"The spot fleet request ID '{p.get('SpotFleetRequestId')}' does not exist")
    return _V()._envelope("DescribeSpotFleetInstances", f"<spotFleetRequestId>{f['id']}</spotFleetRequestId><activeInstanceSet>" + "".join(
        f"<item><instanceId>{_x(i)}</instanceId><instanceType>{_x(m['instances'][i]['instance_type'])}</instanceType><spotInstanceRequestId>sir-{i[2:10]}</spotInstanceRequestId><instanceHealth>healthy</instanceHealth></item>"
        for i in f["instances"] if m["instances"].get(i, {}).get("state") in ("pending", "running")) + "</activeInstanceSet>")


def _modify_spot_fleet(store, p):
    m = _V()._model(store)
    f = _gap(m)["spot_fleets"].get(str(p.get("SpotFleetRequestId")))
    if f is None:
        raise _err("InvalidSpotFleetRequestId.NotFound", f"The spot fleet request ID '{p.get('SpotFleetRequestId')}' does not exist")
    if p.get("TargetCapacity"):
        f["target"] = int(p["TargetCapacity"])
    return _ok("ModifySpotFleetRequest")


def _cancel_spot_fleets(store, p):
    m = _V()._model(store)
    term = _bool(p.get("TerminateInstances"))
    ok, bad = [], []
    for sid in _idx(p, "SpotFleetRequestId"):
        f = _gap(m)["spot_fleets"].get(sid)
        if f is None:
            bad.append(f"<item><spotFleetRequestId>{_x(sid)}</spotFleetRequestId><error><code>spotFleetRequestIdNotFound</code><message>not found</message></error></item>")
            continue
        f["state"] = "cancelled_terminating" if term else "cancelled_running"
        if term:
            for iid in f["instances"]:
                i = m["instances"].get(iid)
                if i and i["state"] not in ("terminated", "shutting-down"):
                    _V()._instance_state_change(store, {"InstanceId.1": iid}, "terminate", "terminated")
        ok.append(f"<item><spotFleetRequestId>{sid}</spotFleetRequestId><currentSpotFleetRequestState>{f['state']}</currentSpotFleetRequestState>"
                  f"<previousSpotFleetRequestState>active</previousSpotFleetRequestState></item>")
    return _V()._envelope("CancelSpotFleetRequests", f"<successfulFleetRequestSet>{''.join(ok)}</successfulFleetRequestSet><unsuccessfulFleetRequestSet>{''.join(bad)}</unsuccessfulFleetRequestSet>")


def _spot_fleet_history(store, p):
    m = _V()._model(store)
    f = _gap(m)["spot_fleets"].get(str(p.get("SpotFleetRequestId")))
    if f is None:
        raise _err("InvalidSpotFleetRequestId.NotFound", f"The spot fleet request ID '{p.get('SpotFleetRequestId')}' does not exist")
    return _V()._envelope("DescribeSpotFleetRequestHistory",
                          f"<spotFleetRequestId>{f['id']}</spotFleetRequestId><startTime>{_x(p.get('StartTime') or f['created'])}</startTime><lastEvaluatedTime>{_x(_V()._now())}</lastEvaluatedTime>"
                          f"<historyRecordSet><item><eventType>fleetRequestChange</eventType><timestamp>{_x(f['created'])}</timestamp><eventInformation><eventSubType>submitted</eventSubType></eventInformation></item></historyRecordSet>")


def _fleet_history(store, p):
    m = _V()._model(store)
    f = _gap(m)["fleets"].get(str(p.get("FleetId")))
    if f is None:
        raise _err("InvalidFleetId.NotFound", f"The fleet id '{p.get('FleetId')}' does not exist")
    return _V()._envelope("DescribeFleetHistory", f"<fleetId>{f['id']}</fleetId><startTime>{_x(p.get('StartTime') or f['created'])}</startTime><lastEvaluatedTime>{_x(_V()._now())}</lastEvaluatedTime>"
                                                    f"<historyRecordSet><item><eventType>fleet-change</eventType><timestamp>{_x(f['created'])}</timestamp><eventInformation><eventSubType>submitted</eventSubType></eventInformation></item></historyRecordSet>")


def _spot_datafeed(action):
    def op(store, p):
        a = _gap(_V()._model(store))["account"]
        if action == "Create":
            if not p.get("Bucket"):
                raise _err("MissingParameter", "The request must contain the parameter Bucket")
            a["spot_datafeed"] = {"bucket": p["Bucket"], "prefix": p.get("Prefix", "")}
        elif action == "Delete":
            if a["spot_datafeed"] is None:
                raise _err("InvalidSpotDatafeed.NotFound", "No Spot datafeed subscription exists.")
            a["spot_datafeed"] = None
            return _ok("DeleteSpotDatafeedSubscription")
        d = a["spot_datafeed"]
        if d is None:
            if action == "Describe":
                raise _err("InvalidSpotDatafeed.NotFound", "No Spot datafeed subscription exists.")
        tag = "spotDatafeedSubscription"
        return _V()._envelope(f"{action}SpotDatafeedSubscription", f"<{tag}><ownerId>{_V().OWNER_ID}</ownerId><bucket>{_x(d['bucket'])}</bucket><prefix>{_x(d['prefix'])}</prefix><state>Active</state></{tag}>")
    return op


# ───────────────────────── Instance Connect endpoints, event windows, addresses ─────────────────────────
def _eic_xml(e):
    return (f"<item><ownerId>{_V().OWNER_ID}</ownerId><instanceConnectEndpointId>{e['id']}</instanceConnectEndpointId>"
            f"<instanceConnectEndpointArn>arn:aws:ec2:us-east-1:{_V().OWNER_ID}:instance-connect-endpoint/{e['id']}</instanceConnectEndpointArn>"
            f"<state>create-complete</state><stateMessage/><dnsName>{e['id']}.{uuid.uuid5(uuid.NAMESPACE_DNS, e['id']).hex[:8]}.ec2-instance-connect-endpoint.us-east-1.amazonaws.com</dnsName>"
            f"<networkInterfaceIdSet>{''.join(f'<item>{x}</item>' for x in e['enis'])}</networkInterfaceIdSet><vpcId>{_x(e['vpc'])}</vpcId>"
            f"<availabilityZone>{_x(e['az'])}</availabilityZone><createdAt>{_x(e['created'])}</createdAt><subnetId>{_x(e['subnet'])}</subnetId>"
            f"<preserveClientIp>{str(e['preserve']).lower()}</preserveClientIp><securityGroupIdSet>{''.join(f'<item>{_x(s)}</item>' for s in e['sgs'])}</securityGroupIdSet>"
            f"{_V()._tags_xml(e['tags'])}</item>")


def _create_eic_endpoint(store, p):
    V = _V()
    m = V._model(store)
    sn = m["subnets"].get(str(p.get("SubnetId")))
    if sn is None:
        raise _err("InvalidSubnetID.NotFound", f"The subnet ID '{p.get('SubnetId')}' does not exist")
    sgs = _idx(p, "SecurityGroupId") or [V._vpc_default_sg(m, sn["vpc_id"], "")]
    eid = "eice-" + uuid.uuid4().hex[:17]
    eni_id = V._rid("eni")
    m["enis"][eni_id] = {"id": eni_id, "subnet_id": sn["id"] if "id" in sn else p["SubnetId"], "vpc_id": sn["vpc_id"], "az": sn.get("az", V._AZS[0]),
                         "description": f"EICE {eid}", "status": "in-use", "private_ip": V._allocate_private_ip(m, str(p["SubnetId"]), ""),
                         "public_ip": "", "sg_ids": sgs, "attachment": None, "source_dest_check": True, "tags": {}, "requester_managed": True}
    e = {"id": eid, "vpc": sn["vpc_id"], "subnet": str(p["SubnetId"]), "az": sn.get("az", V._AZS[0]), "sgs": sgs, "enis": [eni_id],
         "preserve": _bool(p.get("PreserveClientIp")), "created": V._now(), "tags": V._parse_tag_specifications(p).get("instance-connect-endpoint", {})}
    _gap(m)["eic_endpoints"][eid] = e
    return V._envelope("CreateInstanceConnectEndpoint", "<instanceConnectEndpoint>" + _eic_xml(e)[6:-7] + "</instanceConnectEndpoint>")


def _describe_eic_endpoints(store, p):
    m = _V()._model(store)
    ids = _idx(p, "InstanceConnectEndpointId")
    return _V()._envelope("DescribeInstanceConnectEndpoints", "<instanceConnectEndpointSet>" + "".join(
        _eic_xml(e) for e in _gap(m)["eic_endpoints"].values() if not ids or e["id"] in ids) + "</instanceConnectEndpointSet>")


def _delete_eic_endpoint(store, p):
    m = _V()._model(store)
    e = _gap(m)["eic_endpoints"].pop(str(p.get("InstanceConnectEndpointId")), None)
    if e is None:
        raise _err("InvalidInstanceConnectEndpointId.NotFound", f"The instance connect endpoint '{p.get('InstanceConnectEndpointId')}' does not exist.")
    for n in e["enis"]:
        m["enis"].pop(n, None)
    return _V()._envelope("DeleteInstanceConnectEndpoint", "<instanceConnectEndpoint>" + _eic_xml(e)[6:-7].replace("create-complete", "delete-complete") + "</instanceConnectEndpoint>")


def _modify_eic_endpoint(store, p):
    m = _V()._model(store)
    e = _gap(m)["eic_endpoints"].get(str(p.get("InstanceConnectEndpointId")))
    if e is None:
        raise _err("InvalidInstanceConnectEndpointId.NotFound", f"The instance connect endpoint '{p.get('InstanceConnectEndpointId')}' does not exist.")
    if _idx(p, "SecurityGroupId"):
        e["sgs"] = _idx(p, "SecurityGroupId")
    if p.get("PreserveClientIp") is not None:
        e["preserve"] = _bool(p["PreserveClientIp"])
    return _V()._envelope("ModifyInstanceConnectEndpoint", "<return>true</return>")


def _ew_xml(w):
    return (f"<item><instanceEventWindowId>{w['id']}</instanceEventWindowId><timeRangeSet/>"
            f"<name>{_x(w['name'])}</name><cronExpression>{_x(w['cron'])}</cronExpression><associationTarget><instanceIdSet>{''.join(f'<item>{i}</item>' for i in w['instances'])}</instanceIdSet>"
            f"<tagSet/><dedicatedHostIdSet/></associationTarget><state>active</state>{_V()._tags_xml(w['tags'])}</item>")


def _create_event_window(store, p):
    m = _V()._model(store)
    wid = "iew-" + uuid.uuid4().hex[:17]
    _gap(m)["event_windows"][wid] = {"id": wid, "name": str(p.get("Name") or ""), "cron": str(p.get("CronExpression") or ""), "ranges": [],
                                     "instances": [], "tags": _V()._parse_tag_specifications(p).get("instance-event-window", {})}
    return _V()._envelope("CreateInstanceEventWindow", "<instanceEventWindow>" + _ew_xml(_gap(m)["event_windows"][wid])[6:-7] + "</instanceEventWindow>")


def _ew(m, p):
    w = _gap(m)["event_windows"].get(str(p.get("InstanceEventWindowId")))
    if w is None:
        raise _err("InvalidInstanceEventWindowId.NotFound", f"The event window '{p.get('InstanceEventWindowId')}' does not exist.")
    return w


def _describe_event_windows(store, p):
    m = _V()._model(store)
    ids = _idx(p, "InstanceEventWindowId")
    return _V()._envelope("DescribeInstanceEventWindows", "<instanceEventWindowSet>" + "".join(
        _ew_xml(w) for w in _gap(m)["event_windows"].values() if not ids or w["id"] in ids) + "</instanceEventWindowSet>")


def _modify_event_window(store, p):
    m = _V()._model(store)
    w = _ew(m, p)
    if p.get("Name"):
        w["name"] = p["Name"]
    if p.get("CronExpression"):
        w["cron"] = p["CronExpression"]
    return _V()._envelope("ModifyInstanceEventWindow", "<instanceEventWindow>" + _ew_xml(w)[6:-7] + "</instanceEventWindow>")


def _delete_event_window(store, p):
    m = _V()._model(store)
    w = _ew(m, p)
    _gap(m)["event_windows"].pop(w["id"])
    return _V()._envelope("DeleteInstanceEventWindow", f"<instanceEventWindowState><instanceEventWindowId>{w['id']}</instanceEventWindowId><state>deleted</state></instanceEventWindowState>")


def _assoc_event_window(store, p):
    m = _V()._model(store)
    w = _ew(m, p)
    for i in _idx(p, "AssociationTarget.InstanceId"):
        _find_inst(m, i)
        if i not in w["instances"]:
            w["instances"].append(i)
    return _V()._envelope("AssociateInstanceEventWindow", "<instanceEventWindow>" + _ew_xml(w)[6:-7] + "</instanceEventWindow>")


def _disassoc_event_window(store, p):
    m = _V()._model(store)
    w = _ew(m, p)
    gone = _idx(p, "AssociationTarget.InstanceId")
    w["instances"] = [i for i in w["instances"] if i not in gone]
    return _V()._envelope("DisassociateInstanceEventWindow", "<instanceEventWindow>" + _ew_xml(w)[6:-7] + "</instanceEventWindow>")


def _describe_addresses_attribute(store, p):
    m = _V()._model(store)
    ids = _idx(p, "AllocationId")
    rows = [a for a in m["addresses"].values() if not ids or a.get("allocation_id") in ids or a.get("id") in ids]
    return _V()._envelope("DescribeAddressesAttribute", "<addressSet>" + "".join(
        f"<item><publicIp>{_x(a.get('public_ip', ''))}</publicIp><allocationId>{_x(a.get('allocation_id', a.get('id', '')))}</allocationId>"
        f"<ptrRecord>{_x(_gap(m)['addr_attr'].get(a.get('allocation_id', a.get('id', '')), ''))}</ptrRecord></item>" for a in rows) + "</addressSet>")


def _modify_address_attribute(store, p):
    m = _V()._model(store)
    aid = str(p.get("AllocationId"))
    a = next((a for a in m["addresses"].values() if aid in (a.get("allocation_id"), a.get("id"))), None)
    if a is None:
        raise _err("InvalidAllocationID.NotFound", f"The allocation ID '{aid}' does not exist")
    _gap(m)["addr_attr"][aid] = str(p.get("DomainName") or "")
    return _V()._envelope("ModifyAddressAttribute", f"<address><allocationId>{_x(aid)}</allocationId><publicIp>{_x(a.get('public_ip', ''))}</publicIp><ptrRecord>{_x(p.get('DomainName') or '')}</ptrRecord></address>")


def _reset_address_attribute(store, p):
    m = _V()._model(store)
    aid = str(p.get("AllocationId"))
    _gap(m)["addr_attr"].pop(aid, None)
    return _V()._envelope("ResetAddressAttribute", f"<address><allocationId>{_x(aid)}</allocationId></address>")


def _describe_moving_addresses(store, p):
    return _V()._envelope("DescribeMovingAddresses", "<movingAddressStatusSet/>")


# ───────────────────────── install ─────────────────────────
_OPS = {
    "DescribeInstanceAttribute": _describe_instance_attribute, "ResetInstanceAttribute": _reset_instance_attribute,
    "ModifyInstanceMetadataOptions": _modify_metadata_options, "ModifyInstanceCreditSpecification": _modify_credit_spec,
    "DescribeInstanceCreditSpecifications": _describe_credit_specs, "ModifyInstancePlacement": _modify_placement,
    "ModifyInstanceMaintenanceOptions": _modify_maintenance_options,
    "ModifyInstanceCpuOptions": _record_only("ModifyInstanceCpuOptions"),
    "ModifyInstanceNetworkPerformanceOptions": _record_only("ModifyInstanceNetworkPerformanceOptions"),
    "ModifyInstanceCapacityReservationAttributes": _record_only("ModifyInstanceCapacityReservationAttributes"),
    "ReportInstanceStatus": _report_instance_status, "DescribeInstanceTypeOfferings": _instance_type_offerings,
    "GetLaunchTemplateData": _get_launch_template_data, "DeleteLaunchTemplateVersions": _delete_lt_versions,
    "ModifyInstanceMetadataDefaults": _imds_defaults, "GetInstanceMetadataDefaults": _get_imds_defaults,
    "RegisterInstanceEventNotificationAttributes": _event_notif("Register"),
    "DeregisterInstanceEventNotificationAttributes": _event_notif("Deregister"),
    "DescribeInstanceEventNotificationAttributes": _event_notif("Describe"),
    "DescribeVolumeAttribute": _describe_volume_attribute, "ModifyVolumeAttribute": _modify_volume_attribute,
    "DescribeVolumeStatus": _describe_volume_status, "EnableVolumeIO": _enable_volume_io,
    "DescribeVolumesModifications": _describe_volumes_modifications,
    "DescribeSnapshotAttribute": _describe_snapshot_attribute, "ModifySnapshotAttribute": _modify_snapshot_attribute,
    "ResetSnapshotAttribute": _reset_snapshot_attribute, "CreateSnapshots": _create_snapshots,
    "LockSnapshot": _lock_snapshot, "UnlockSnapshot": _unlock_snapshot, "DescribeLockedSnapshots": _describe_locked_snapshots,
    "EnableFastSnapshotRestores": _fast_restore("Enable"), "DisableFastSnapshotRestores": _fast_restore("Disable"),
    "DescribeFastSnapshotRestores": _describe_fast_restores,
    "ModifySnapshotTier": _snapshot_tier("Modify"), "RestoreSnapshotTier": _snapshot_tier("Restore"),
    "DescribeSnapshotTierStatus": _describe_snapshot_tier_status,
    "RegisterImage": _register_image, "DescribeImageAttribute": _describe_image_attribute, "ResetImageAttribute": _reset_image_attribute,
    "EnableImage": _image_flag("EnableImage", "state", "available"), "DisableImage": _image_flag("DisableImage", "state", "disabled"),
    "EnableImageDeprecation": _image_flag("EnableImageDeprecation", "deprecate", True),
    "DisableImageDeprecation": _image_flag("DisableImageDeprecation", "deprecate", False),
    "EnableImageDeregistrationProtection": _image_flag("EnableImageDeregistrationProtection", "dereg_protection", True),
    "DisableImageDeregistrationProtection": _image_flag("DisableImageDeregistrationProtection", "dereg_protection", False),
    "AssignPrivateIpAddresses": _assign_private_ips, "UnassignPrivateIpAddresses": _unassign_private_ips,
    "AssignIpv6Addresses": _assign_ipv6, "UnassignIpv6Addresses": _unassign_ipv6,
    "DescribeNetworkInterfaceAttribute": _describe_eni_attribute, "ResetNetworkInterfaceAttribute": _reset_eni_attribute,
    "CreateNetworkInterfacePermission": _create_eni_permission, "DescribeNetworkInterfacePermissions": _describe_eni_permissions,
    "DeleteNetworkInterfacePermission": _delete_eni_permission,
    "AssociateIamInstanceProfile": _associate_iam_profile, "DescribeIamInstanceProfileAssociations": _describe_iam_profile_assocs,
    "DisassociateIamInstanceProfile": _disassociate_iam_profile, "ReplaceIamInstanceProfileAssociation": _replace_iam_profile,
    "ReplaceRoute": _replace_route, "RejectVpcPeeringConnection": _reject_peering,
    "ModifyVpcPeeringConnectionOptions": _modify_peering_options, "ModifyVpcEndpoint": _modify_vpc_endpoint,
    "DescribeVpcEndpointServices": _describe_endpoint_services, "ModifyVpcTenancy": _modify_vpc_tenancy,
    "CreateDefaultVpc": _create_default_vpc, "CreateDefaultSubnet": _create_default_subnet,
    "CreateFleet": _create_fleet, "DescribeFleets": _describe_fleets, "DescribeFleetInstances": _describe_fleet_instances,
    "ModifyFleet": _modify_fleet, "DeleteFleets": _delete_fleets, "DescribeFleetHistory": _fleet_history,
    "RequestSpotFleet": _request_spot_fleet, "DescribeSpotFleetRequests": _describe_spot_fleet_requests,
    "DescribeSpotFleetInstances": _describe_spot_fleet_instances, "ModifySpotFleetRequest": _modify_spot_fleet,
    "CancelSpotFleetRequests": _cancel_spot_fleets, "DescribeSpotFleetRequestHistory": _spot_fleet_history,
    "CreateSpotDatafeedSubscription": _spot_datafeed("Create"), "DescribeSpotDatafeedSubscription": _spot_datafeed("Describe"),
    "DeleteSpotDatafeedSubscription": _spot_datafeed("Delete"),
    "CreateInstanceConnectEndpoint": _create_eic_endpoint, "DescribeInstanceConnectEndpoints": _describe_eic_endpoints,
    "DeleteInstanceConnectEndpoint": _delete_eic_endpoint, "ModifyInstanceConnectEndpoint": _modify_eic_endpoint,
    "CreateInstanceEventWindow": _create_event_window, "DescribeInstanceEventWindows": _describe_event_windows,
    "ModifyInstanceEventWindow": _modify_event_window, "DeleteInstanceEventWindow": _delete_event_window,
    "AssociateInstanceEventWindow": _assoc_event_window, "DisassociateInstanceEventWindow": _disassoc_event_window,
    "DescribeAddressesAttribute": _describe_addresses_attribute, "ModifyAddressAttribute": _modify_address_attribute,
    "ResetAddressAttribute": _reset_address_attribute, "DescribeMovingAddresses": _describe_moving_addresses,
}
for _kind in ("Snapshot", "Image"):
    _g, _e, _d = _bpa(_kind)
    _OPS[f"Get{_kind}BlockPublicAccessState"] = _g
    _OPS[f"Enable{_kind}BlockPublicAccess"] = _e
    _OPS[f"Disable{_kind}BlockPublicAccess"] = _d


def install(ops):
    ops.update(_OPS)
    ops["ModifyVolume"] = _modify_volume_wrap(ops["ModifyVolume"])
    ops["DeleteSnapshot"] = _delete_snapshot_guard(ops["DeleteSnapshot"])
    ops["DeregisterImage"] = _dereg_guard(ops["DeregisterImage"])
