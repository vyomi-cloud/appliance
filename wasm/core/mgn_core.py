# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS Application Migration Service (service `mgn`, SigV4 signing name `mgn`, rest-json `POST /<Operation>`) — substrate-independent.

Source servers, replication configuration templates, per-server replication + launch configuration, and the real
test / cutover lifecycle state machine (NOT_READY -> READY_FOR_TEST -> TEST_IN_PROGRESS -> READY_FOR_CUTOVER ->
CUTTING_OVER -> CUTOVER -> DISCONNECTED / archived) with jobs. State lives in the shared EC2 model bag (`m["mgn"]`), so offline +
Nano persist it with the VPC store.

REAL: validation (subnets / security groups / instance types / enums against the EC2 model), the lifecycle transition rules and
ConflictException / ValidationException errors, and cutover: StartTest / StartCutover launch a REAL EC2 instance (vpc_core._launch_one)
into the configured subnet from an AMI registered out of the server's (synthetic) replicated disks, with right-sizing, STARTED/STOPPED
launch disposition, copied tags and AWS tags; TerminateTargetInstances really terminates them.

HONEST LIMITS: replication is records only — no agent runs on a source machine and no disk data is copied (a source server is registered with
the Vyomi-only RegisterSourceServer action, the stand-in for installing the replication agent). dataReplicationState advances on elapsed
time (INITIATING -> INITIAL_SYNC -> CONTINUOUS), not on transferred bytes; the launched instance boots the synthetic image, not the source OS.
Post-launch actions, wave/application grouping, and conversion server behaviour are not modelled.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone

SYNC_AFTER = 2.0          # seconds from registration to INITIAL_SYNC
CONTINUOUS_AFTER = 6.0    # seconds from registration to CONTINUOUS (ready for test)
_LIFECYCLE_SETTABLE = {"READY_FOR_TEST", "READY_FOR_CUTOVER", "CUTOVER"}
_DISPOSITION = {"STOPPED", "STARTED"}
_RIGHTSIZING = {"NONE", "BASIC", "IN_AWS"}
_THROTTLE_MAX = 10000
_DATA_PLANE = {"PUBLIC_IP", "PRIVATE_IP"}
_DISK_TYPES = {"AUTO", "GP2", "GP3", "ST1"}
_EBS_ENC = {"DEFAULT", "CUSTOM", "NONE"}
_BOOT = {"LEGACY_BIOS", "UEFI", "USE_SOURCE"}
_SIZES = [(1, 1, "t3.micro"), (2, 2, "t3.small"), (2, 4, "t3.medium"), (2, 8, "t3.large"), (4, 16, "m5.xlarge"),
          (8, 32, "m5.2xlarge"), (16, 64, "m5.4xlarge")]


class _Err(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def _V():
    from core import vpc_core
    return vpc_core


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _bag(store) -> dict:
    m = _V()._model(store)
    b = m.setdefault("mgn", {})
    for k in ("servers", "templates", "jobs"):
        b.setdefault(k, {})
    b.setdefault("initialized", False)
    return b


def _resp(status, obj=None, code=None):
    hdrs = {"content-type": "application/json"}
    if code:
        hdrs["x-amzn-errortype"] = code
    return {"status": status, "headers": hdrs, "body": json.dumps(obj if obj is not None else {}).encode()}


def _arn(kind, rid):
    return f"arn:aws:mgn:us-east-1:123456789012:{kind}/{rid}"


def _need(data, *keys):
    for k in keys:
        if data.get(k) in (None, "", []):
            raise _Err("ValidationException", f"{k} is required.")


def _enum(v, allowed, name):
    if v not in allowed:
        raise _Err("ValidationException", f"{name} must be one of {sorted(allowed)}.")
    return v


def _check_subnet(m, sid, name="subnet"):
    if sid and sid not in m["subnets"]:
        raise _Err("ValidationException", f"The {name} '{sid}' does not exist.")


def _check_sgs(m, ids):
    for g in ids or []:
        if g not in m["sgs"]:
            raise _Err("ValidationException", f"The security group '{g}' does not exist.")


def _check_type(t):
    if not re.fullmatch(r"[a-z][a-z0-9]*\d[a-z0-9-]*\.[a-z0-9]+", t or ""):
        raise _Err("ValidationException", f"'{t}' is not a valid EC2 instance type.")


# ── replication templates ────────────────────────────────────────────────────
_TPL_DEFAULTS = {"associateDefaultSecurityGroup": True, "bandwidthThrottling": 0, "createPublicIP": False,
                 "dataPlaneRouting": "PRIVATE_IP", "defaultLargeStagingDiskType": "GP3", "ebsEncryption": "DEFAULT",
                 "replicationServerInstanceType": "t3.small", "useDedicatedReplicationServer": False,
                 "useFipsEndpoint": False, "stagingAreaTags": {}, "replicationServersSecurityGroupsIDs": []}


def _apply_repl(m, target: dict, data: dict):
    for k in ("associateDefaultSecurityGroup", "createPublicIP", "useDedicatedReplicationServer", "useFipsEndpoint"):
        if k in data:
            if not isinstance(data[k], bool):
                raise _Err("ValidationException", f"{k} must be a boolean.")
            target[k] = data[k]
    if "bandwidthThrottling" in data:
        b = data["bandwidthThrottling"]
        if not isinstance(b, int) or not 0 <= b <= _THROTTLE_MAX:
            raise _Err("ValidationException", f"bandwidthThrottling must be 0-{_THROTTLE_MAX} Mbps.")
        target["bandwidthThrottling"] = b
    if "dataPlaneRouting" in data:
        target["dataPlaneRouting"] = _enum(data["dataPlaneRouting"], _DATA_PLANE, "dataPlaneRouting")
    if "defaultLargeStagingDiskType" in data:
        target["defaultLargeStagingDiskType"] = _enum(data["defaultLargeStagingDiskType"], _DISK_TYPES, "defaultLargeStagingDiskType")
    if "ebsEncryption" in data:
        target["ebsEncryption"] = _enum(data["ebsEncryption"], _EBS_ENC, "ebsEncryption")
    if target.get("ebsEncryption") == "CUSTOM" and not (data.get("ebsEncryptionKeyArn") or target.get("ebsEncryptionKeyArn")):
        raise _Err("ValidationException", "ebsEncryptionKeyArn is required when ebsEncryption is CUSTOM.")
    if data.get("ebsEncryptionKeyArn"):
        target["ebsEncryptionKeyArn"] = data["ebsEncryptionKeyArn"]
    if "replicationServerInstanceType" in data:
        _check_type(data["replicationServerInstanceType"])
        target["replicationServerInstanceType"] = data["replicationServerInstanceType"]
    if "stagingAreaSubnetId" in data:
        _check_subnet(m, data["stagingAreaSubnetId"], "staging area subnet")
        target["stagingAreaSubnetId"] = data["stagingAreaSubnetId"]
    if "replicationServersSecurityGroupsIDs" in data:
        _check_sgs(m, data["replicationServersSecurityGroupsIDs"])
        target["replicationServersSecurityGroupsIDs"] = list(data["replicationServersSecurityGroupsIDs"])
    if "stagingAreaTags" in data:
        target["stagingAreaTags"] = dict(data["stagingAreaTags"] or {})


def _op_create_template(store, m, b, data):
    _need(data, "stagingAreaSubnetId")
    t = dict(_TPL_DEFAULTS)
    t["stagingAreaSubnetId"] = ""
    _apply_repl(m, t, data)
    tid = "rct-" + uuid.uuid4().hex[:17]
    t.update({"replicationConfigurationTemplateID": tid, "arn": _arn("replication-configuration-template", tid), "tags": dict(data.get("tags") or {})})
    b["templates"][tid] = t
    return _resp(201, t)


def _tpl(b, tid):
    t = b["templates"].get(tid)
    if t is None:
        raise _Err("ResourceNotFoundException", f"Replication configuration template {tid} not found.", 404)
    return t


def _op_describe_templates(store, m, b, data):
    ids = data.get("replicationConfigurationTemplateIDs")
    items = [t for tid, t in sorted(b["templates"].items()) if not ids or tid in ids]
    return _resp(200, {"items": items})


def _op_update_template(store, m, b, data):
    _need(data, "replicationConfigurationTemplateID")
    t = _tpl(b, data["replicationConfigurationTemplateID"])
    _apply_repl(m, t, data)
    return _resp(200, t)


def _op_delete_template(store, m, b, data):
    _need(data, "replicationConfigurationTemplateID")
    _tpl(b, data["replicationConfigurationTemplateID"])
    del b["templates"][data["replicationConfigurationTemplateID"]]
    return _resp(204)


# ── source servers ───────────────────────────────────────────────────────────
def _op_register(store, m, b, data):
    """Vyomi-only: stand-in for installing the replication agent on a source machine."""
    _need(data, "hostname")
    disks = data.get("disks") or [{"deviceName": "/dev/sda", "bytes": 8 * 1024 ** 3}]
    for d in disks:
        if not isinstance(d.get("bytes"), int) or d["bytes"] < 1024 ** 3:
            raise _Err("ValidationException", "every disk needs 'bytes' >= 1 GiB.")
    tid = data.get("replicationConfigurationTemplateID")
    base = _tpl(b, tid) if tid else (next(iter(b["templates"].values()), None))
    if base is None:
        raise _Err("ValidationException", "No replication configuration template exists; create one first (CreateReplicationConfigurationTemplate).")
    if any(s["sourceProperties"]["identificationHints"]["hostname"] == data["hostname"] and not s["isArchived"] for s in b["servers"].values()):
        raise _Err("ConflictException", f"A source server with hostname {data['hostname']} is already registered.", 409)
    sid = "s-" + uuid.uuid4().hex[:17]
    os_name = str(data.get("os") or "Linux")
    cpus = int(data.get("cpus") or 2)
    ram = int(data.get("ramBytes") or 4 * 1024 ** 3)
    repl = {k: base.get(k) for k in _TPL_DEFAULTS}
    repl["stagingAreaSubnetId"] = base["stagingAreaSubnetId"]
    b["servers"][sid] = {
        "sourceServerID": sid, "arn": _arn("source-server", sid), "isArchived": False, "tags": dict(data.get("tags") or {}),
        "registered_at": time.time(),
        "sourceProperties": {"lastUpdatedDateTime": _now(), "recommendedInstanceType": _recommend(cpus, ram),
                             "identificationHints": {"hostname": data["hostname"], "fqdn": data.get("fqdn") or data["hostname"]},
                             "networkInterfaces": [{"ips": list(data.get("ips") or ["10.0.0.10"]), "isPrimary": True, "macAddress": "00:00:5e:00:53:01"}],
                             "disks": [{"deviceName": d.get("deviceName") or f"/dev/sd{chr(97 + i)}", "bytes": d["bytes"]} for i, d in enumerate(disks)],
                             "cpus": [{"cores": cpus, "modelName": "Vyomi synthetic CPU"}], "ramBytes": ram,
                             "os": {"fullString": os_name}},
        "replication": repl,
        "launch": {"name": data["hostname"], "launchDisposition": "STOPPED", "targetInstanceTypeRightSizingMethod": "BASIC",
                   "copyPrivateIp": False, "copyTags": True, "enableMapAutoTagging": False, "bootMode": "USE_SOURCE",
                   "licensing": {"osByol": False}, "targetInstanceType": "", "targetSubnetId": "", "securityGroupIDs": []},
        "lifeCycle": {"state": "NOT_READY", "addedToServiceDateTime": _now()},
        "dataReplicationInfo": {"dataReplicationState": "INITIATING", "lagDuration": "PT0S", "replicatedDisks": [], "lastSnapshotDateTime": ""},
        "launchedInstance": None, "launched_test_instance": None,
    }
    b["initialized"] = True
    return _resp(201, _view(b["servers"][sid]))


def _recommend(cpus, ram):
    gib = ram / 1024 ** 3
    for c, g, t in _SIZES:
        if cpus <= c and gib <= g:
            return t
    return _SIZES[-1][2]


def _advance(srv):
    """Records-only replication: the state follows elapsed time since registration (no bytes move)."""
    if srv["isArchived"] or srv["lifeCycle"]["state"] in ("DISCONNECTED",):
        return
    el = time.time() - srv["registered_at"]
    info = srv["dataReplicationInfo"]
    if el >= CONTINUOUS_AFTER and info["dataReplicationState"] != "CONTINUOUS":
        info["dataReplicationState"] = "CONTINUOUS"
        info["lastSnapshotDateTime"] = _now()
        info["replicatedDisks"] = [{"deviceName": d["deviceName"], "totalStorageBytes": d["bytes"], "replicatedStorageBytes": d["bytes"],
                                    "rescannedStorageBytes": 0, "backloggedStorageBytes": 0} for d in srv["sourceProperties"]["disks"]]
        if srv["lifeCycle"]["state"] == "NOT_READY":
            srv["lifeCycle"]["state"] = "READY_FOR_TEST"
            srv["lifeCycle"]["firstByteDateTime"] = _now()
    elif el >= SYNC_AFTER and info["dataReplicationState"] == "INITIATING":
        info["dataReplicationState"] = "INITIAL_SYNC"
        info["replicatedDisks"] = [{"deviceName": d["deviceName"], "totalStorageBytes": d["bytes"], "replicatedStorageBytes": d["bytes"] // 2,
                                    "rescannedStorageBytes": 0, "backloggedStorageBytes": 0} for d in srv["sourceProperties"]["disks"]]


def _view(srv):
    _advance(srv)
    out = {k: v for k, v in srv.items() if k not in ("registered_at", "replication", "launch", "launched_test_instance")}
    out["launchedInstance"] = srv["launchedInstance"]
    return out


def _server(b, sid):
    s = b["servers"].get(sid)
    if s is None:
        raise _Err("ResourceNotFoundException", f"Source server {sid} not found.", 404)
    _advance(s)
    return s


def _op_describe_servers(store, m, b, data):
    f = data.get("filters") or {}
    ids, states = f.get("sourceServerIDs"), f.get("lifeCycleStates")
    items = []
    for sid, s in sorted(b["servers"].items()):
        _advance(s)
        if ids and sid not in ids:
            continue
        if states and s["lifeCycle"]["state"] not in states:
            continue
        if "isArchived" in f and bool(f["isArchived"]) != s["isArchived"]:
            continue
        if "isArchived" not in f and s["isArchived"]:
            continue
        items.append(_view(s))
    return _resp(200, {"items": items})


def _op_get_repl(store, m, b, data):
    _need(data, "sourceServerID")
    s = _server(b, data["sourceServerID"])
    return _resp(200, {"sourceServerID": s["sourceServerID"], "name": s["launch"]["name"], **s["replication"]})


def _op_update_repl(store, m, b, data):
    _need(data, "sourceServerID")
    s = _server(b, data["sourceServerID"])
    if s["isArchived"]:
        raise _Err("ConflictException", "Source server is archived.", 409)
    _apply_repl(m, s["replication"], data)
    return _op_get_repl(store, m, b, data)


def _op_get_launch(store, m, b, data):
    _need(data, "sourceServerID")
    s = _server(b, data["sourceServerID"])
    return _resp(200, {"sourceServerID": s["sourceServerID"], **s["launch"]})


def _op_update_launch(store, m, b, data):
    _need(data, "sourceServerID")
    s = _server(b, data["sourceServerID"])
    L = s["launch"]
    if s["isArchived"]:
        raise _Err("ConflictException", "Source server is archived.", 409)
    if "launchDisposition" in data:
        L["launchDisposition"] = _enum(data["launchDisposition"], _DISPOSITION, "launchDisposition")
    if "targetInstanceTypeRightSizingMethod" in data:
        L["targetInstanceTypeRightSizingMethod"] = _enum(data["targetInstanceTypeRightSizingMethod"], _RIGHTSIZING, "targetInstanceTypeRightSizingMethod")
    if "bootMode" in data:
        L["bootMode"] = _enum(data["bootMode"], _BOOT, "bootMode")
    for k in ("copyPrivateIp", "copyTags", "enableMapAutoTagging"):
        if k in data:
            if not isinstance(data[k], bool):
                raise _Err("ValidationException", f"{k} must be a boolean.")
            L[k] = data[k]
    if data.get("name"):
        L["name"] = str(data["name"])[:255]
    if "targetInstanceType" in data:
        if data["targetInstanceType"]:
            _check_type(data["targetInstanceType"])
        L["targetInstanceType"] = data["targetInstanceType"]
    if "targetSubnetId" in data:
        _check_subnet(m, data["targetSubnetId"], "target subnet")
        L["targetSubnetId"] = data["targetSubnetId"]
    if "securityGroupIDs" in data:
        _check_sgs(m, data["securityGroupIDs"])
        L["securityGroupIDs"] = list(data["securityGroupIDs"])
    if "licensing" in data:
        L["licensing"] = {"osByol": bool((data["licensing"] or {}).get("osByol"))}
    if L["targetInstanceTypeRightSizingMethod"] == "NONE" and not L["targetInstanceType"] and False:
        pass
    return _op_get_launch(store, m, b, data)


# ── lifecycle + jobs ─────────────────────────────────────────────────────────
def _job(b, jtype, ids, tags):
    jid = "mgn-job-" + uuid.uuid4().hex[:17]
    j = {"jobID": jid, "arn": _arn("job", jid), "type": jtype, "initiatedBy": "START_TEST" if jtype == "LAUNCH" else "TERMINATE_RECOVERY_INSTANCES",
         "creationDateTime": _now(), "status": "STARTED", "participatingServers": [], "tags": dict(tags or {}), "logs": []}
    b["jobs"][jid] = j
    return j


def _log(j, event, **extra):
    j["logs"].append({"logDateTime": _now(), "event": event, "eventData": extra})


def _launch_instance(store, m, b, srv, purpose):
    V = _V()
    L = srv["launch"]
    sp = srv["sourceProperties"]
    method = L["targetInstanceTypeRightSizingMethod"]
    itype = L["targetInstanceType"] if (method == "NONE" and L["targetInstanceType"]) else sp["recommendedInstanceType"]
    if L["targetInstanceType"] and method != "BASIC":
        itype = L["targetInstanceType"]
    subnet = L["targetSubnetId"] or srv["replication"].get("stagingAreaSubnetId") or ""
    # AMI registered from the synthetic replicated disks (records-only replication; not the source OS)
    ami = "ami-" + uuid.uuid4().hex[:17]
    bds = [{"device_name": "/dev/xvda" if i == 0 else d["deviceName"], "snapshot_id": "snap-" + uuid.uuid4().hex[:12],
            "size": max(1, -(-d["bytes"] // 1024 ** 3)), "volume_type": "gp3", "delete_on_termination": True}
           for i, d in enumerate(sp["disks"])]
    windows = "windows" in sp["os"]["fullString"].lower()
    m["images"][ami] = {"id": ami, "name": f"mgn-replicated-{srv['sourceServerID']}-{purpose}", "description": "AWS Application Migration Service replicated disks (synthetic)",
                        "owner_id": V.OWNER_ID, "public": False, "state": "available", "architecture": "x86_64", "platform": "windows" if windows else "",
                        "root_device_type": "ebs", "root_device_name": "/dev/xvda", "virtualization_type": "hvm", "creation_date": _now(),
                        "source": srv["sourceServerID"], "tags": {}, "launch_permissions": [], "block_devices": bds}
    params = {"ImageId": ami, "InstanceType": itype}
    if subnet:
        params["SubnetId"] = subnet
    for i, g in enumerate(L["securityGroupIDs"], 1):
        params[f"SecurityGroupId.{i}"] = g
    if L["copyPrivateIp"] and sp["networkInterfaces"][0]["ips"]:
        params["PrivateIpAddress"] = sp["networkInterfaces"][0]["ips"][0]
    tags = {"AWSApplicationMigrationServiceManaged": "mgn.amazonaws.com", "AWSApplicationMigrationServiceSourceServerID": srv["sourceServerID"],
            "Name": L["name"]}
    if L["copyTags"]:
        tags.update(srv.get("tags") or {})
    try:
        inst = V._launch_one(m, params, {"instance": tags}, 0)
    except V.VpcError as e:
        m["images"].pop(ami, None)
        raise _Err("ValidationException", f"Launch failed: {e.code}: {e.message}")
    if L["launchDisposition"] == "STOPPED":
        inst["state"] = "stopped"
        inst["public_ip"], inst["public_dns"] = "", ""
    return inst["id"], ami, itype


def _start(store, m, b, data, mode):
    ids = data.get("sourceServerIDs")
    if not ids:
        raise _Err("ValidationException", "sourceServerIDs is required.")
    if len(ids) > 200:
        raise _Err("ValidationException", "At most 200 source servers per job.")
    ok_states = {"test": {"READY_FOR_TEST", "READY_FOR_CUTOVER"}, "cutover": {"READY_FOR_TEST", "READY_FOR_CUTOVER", "TEST_IN_PROGRESS"}}[mode]
    servers = []
    for sid in ids:
        s = _server(b, sid)
        st = s["lifeCycle"]["state"]
        if s["isArchived"]:
            raise _Err("ConflictException", f"Source server {sid} is archived.", 409)
        if st not in ok_states:
            raise _Err("ConflictException", f"Source server {sid} is in lifecycle state {st}; "
                       f"{'StartTest' if mode == 'test' else 'StartCutover'} needs one of {sorted(ok_states)} "
                       f"(data replication state {s['dataReplicationInfo']['dataReplicationState']}).", 409)
        servers.append(s)
    j = _job(b, "LAUNCH", ids, data.get("tags"))
    for s in servers:
        try:
            iid, ami, itype = _launch_instance(store, m, b, s, mode)
        except _Err as e:
            j["participatingServers"].append({"sourceServerID": s["sourceServerID"], "launchStatus": "FAILED"})
            _log(j, "LAUNCH_FAILED", sourceServerID=s["sourceServerID"], error=e.message)
            continue
        s["launchedInstance"] = {"ec2InstanceID": iid, "jobID": j["jobID"], "firstBoot": "WAITING", "imageID": ami, "instanceType": itype, "purpose": mode}
        s["lifeCycle"]["state"] = "TEST_IN_PROGRESS" if mode == "test" else "CUTTING_OVER"
        s["lifeCycle"]["lastTest" if mode == "test" else "lastCutover"] = {"initiated": {"apiCallDateTime": _now(), "jobID": j["jobID"]}}
        j["participatingServers"].append({"sourceServerID": s["sourceServerID"], "launchStatus": "LAUNCHED",
                                          "launchedEc2InstanceID": iid, "postLaunchActionsStatus": "NOT_STARTED"})
        _log(j, "LAUNCH_START", sourceServerID=s["sourceServerID"])
        _log(j, "LAUNCH_END", sourceServerID=s["sourceServerID"], ec2InstanceID=iid, conversionServerID="", instanceType=itype)
    failed = [p for p in j["participatingServers"] if p["launchStatus"] == "FAILED"]
    j["status"] = "COMPLETED"
    j["endDateTime"] = _now()
    return _resp(202, j)


def _op_start_test(store, m, b, data):
    return _start(store, m, b, data, "test")


def _op_start_cutover(store, m, b, data):
    return _start(store, m, b, data, "cutover")


def _op_change_lifecycle(store, m, b, data):
    _need(data, "sourceServerID")
    s = _server(b, data["sourceServerID"])
    new = ((data.get("lifeCycle") or {}).get("state"))
    _enum(new, _LIFECYCLE_SETTABLE, "lifeCycle.state")
    cur = s["lifeCycle"]["state"]
    allowed = {"READY_FOR_TEST": {"TEST_IN_PROGRESS", "READY_FOR_CUTOVER"}, "READY_FOR_CUTOVER": {"TEST_IN_PROGRESS", "READY_FOR_TEST"},
               "CUTOVER": {"CUTTING_OVER"}}
    # real MGN: move TEST_IN_PROGRESS -> READY_FOR_CUTOVER (test passed) or READY_FOR_TEST (redo); CUTTING_OVER -> CUTOVER
    if new == "READY_FOR_CUTOVER" and cur not in ("TEST_IN_PROGRESS", "READY_FOR_TEST"):
        raise _Err("ConflictException", f"Cannot move {cur} to READY_FOR_CUTOVER.", 409)
    if new == "READY_FOR_TEST" and cur not in ("TEST_IN_PROGRESS", "READY_FOR_CUTOVER"):
        raise _Err("ConflictException", f"Cannot move {cur} to READY_FOR_TEST.", 409)
    if new == "CUTOVER" and cur != "CUTTING_OVER":
        raise _Err("ConflictException", f"Cannot move {cur} to CUTOVER; start a cutover first.", 409)
    s["lifeCycle"]["state"] = new
    return _resp(200, _view(s))


def _op_finalize(store, m, b, data):
    _need(data, "sourceServerID")
    s = _server(b, data["sourceServerID"])
    if s["lifeCycle"]["state"] != "CUTTING_OVER":
        raise _Err("ConflictException", f"FinalizeCutover requires CUTTING_OVER; the server is {s['lifeCycle']['state']}.", 409)
    s["lifeCycle"]["state"] = "CUTOVER"
    s["lifeCycle"]["lastCutover"] = {**s["lifeCycle"].get("lastCutover", {}), "finalized": {"apiCallDateTime": _now()}}
    return _resp(200, _view(s))


def _op_terminate_targets(store, m, b, data):
    ids = data.get("sourceServerIDs")
    if not ids:
        raise _Err("ValidationException", "sourceServerIDs is required.")
    V = _V()
    j = _job(b, "TERMINATE", ids, data.get("tags"))
    for sid in ids:
        s = _server(b, sid)
        li = s["launchedInstance"]
        if not li:
            raise _Err("ConflictException", f"Source server {sid} has no launched target instance.", 409)
        if s["lifeCycle"]["state"] == "CUTOVER":
            raise _Err("ConflictException", f"Source server {sid} is cut over; its target instance is the migrated workload.", 409)
        inst = m["instances"].get(li["ec2InstanceID"])
        if inst and inst["state"] != "terminated":
            V._instance_state_change(store, {"InstanceId.1": li["ec2InstanceID"], "Force": "true"}, "terminate", "terminated")
        m["images"].pop(li.get("imageID"), None)
        s["launchedInstance"] = None
        if s["lifeCycle"]["state"] in ("TEST_IN_PROGRESS", "CUTTING_OVER"):
            s["lifeCycle"]["state"] = "READY_FOR_TEST"
        j["participatingServers"].append({"sourceServerID": sid, "launchStatus": "TERMINATED", "launchedEc2InstanceID": li["ec2InstanceID"]})
        _log(j, "CLEANUP_END", sourceServerID=sid, ec2InstanceID=li["ec2InstanceID"])
    j["status"] = "COMPLETED"
    j["endDateTime"] = _now()
    return _resp(202, j)


def _op_archive(store, m, b, data):
    _need(data, "sourceServerID")
    s = _server(b, data["sourceServerID"])
    if s["lifeCycle"]["state"] not in ("CUTOVER", "DISCONNECTED"):
        raise _Err("ConflictException", f"MarkAsArchived requires CUTOVER or DISCONNECTED; the server is {s['lifeCycle']['state']}.", 409)
    s["isArchived"] = True
    return _resp(200, _view(s))


def _op_disconnect(store, m, b, data):
    _need(data, "sourceServerID")
    s = _server(b, data["sourceServerID"])
    if s["isArchived"]:
        raise _Err("ConflictException", "Source server is archived.", 409)
    if s["lifeCycle"]["state"] in ("TEST_IN_PROGRESS", "CUTTING_OVER"):
        raise _Err("ConflictException", "Finish or terminate the in-flight test/cutover before disconnecting.", 409)
    s["lifeCycle"]["state"] = "DISCONNECTED"
    s["dataReplicationInfo"]["dataReplicationState"] = "DISCONNECTED"
    return _resp(200, _view(s))


def _op_delete_server(store, m, b, data):
    _need(data, "sourceServerID")
    s = _server(b, data["sourceServerID"])
    if not s["isArchived"]:
        raise _Err("ConflictException", "Archive the source server (MarkAsArchived) before deleting it.", 409)
    del b["servers"][data["sourceServerID"]]
    return _resp(204)


def _op_describe_jobs(store, m, b, data):
    f = data.get("filters") or {}
    items = [j for _, j in sorted(b["jobs"].items(), reverse=True) if not f.get("jobIDs") or j["jobID"] in f["jobIDs"]]
    return _resp(200, {"items": [{k: v for k, v in j.items() if k != "logs"} for j in items]})


def _op_job_logs(store, m, b, data):
    _need(data, "jobID")
    j = b["jobs"].get(data["jobID"])
    if j is None:
        raise _Err("ResourceNotFoundException", f"Job {data['jobID']} not found.", 404)
    return _resp(200, {"items": j["logs"]})


def _op_init(store, m, b, data):
    b["initialized"] = True
    return _resp(204)


_OPS = {
    "InitializeService": _op_init,
    "CreateReplicationConfigurationTemplate": _op_create_template,
    "DescribeReplicationConfigurationTemplates": _op_describe_templates,
    "UpdateReplicationConfigurationTemplate": _op_update_template,
    "DeleteReplicationConfigurationTemplate": _op_delete_template,
    "RegisterSourceServer": _op_register,   # Vyomi-only stand-in for the replication agent install
    "DescribeSourceServers": _op_describe_servers,
    "GetReplicationConfiguration": _op_get_repl, "UpdateReplicationConfiguration": _op_update_repl,
    "GetLaunchConfiguration": _op_get_launch, "UpdateLaunchConfiguration": _op_update_launch,
    "StartTest": _op_start_test, "StartCutover": _op_start_cutover,
    "ChangeServerLifeCycleState": _op_change_lifecycle, "FinalizeCutover": _op_finalize,
    "TerminateTargetInstances": _op_terminate_targets, "MarkAsArchived": _op_archive,
    "DisconnectFromService": _op_disconnect, "DeleteSourceServer": _op_delete_server,
    "DescribeJobs": _op_describe_jobs, "DescribeJobLogItems": _op_job_logs,
}


def dispatch(store, method, path, query, headers, body):
    op = path.split("?")[0].strip("/")
    fn = _OPS.get(op)
    if fn is None or method != "POST":
        return _resp(404, {"message": f"Unknown MGN operation {method} {path}", "__type": "UnknownOperationException"}, "UnknownOperationException")
    try:
        data = json.loads(body) if body else {}
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        return _resp(400, {"message": "Invalid JSON body.", "__type": "ValidationException"}, "ValidationException")
    try:
        m = _V()._model(store)
        b = _bag(store)
        return fn(store, m, b, data)
    except _Err as e:
        return _resp(e.status, {"message": e.message, "Message": e.message, "code": e.code, "__type": e.code}, e.code)
