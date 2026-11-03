"""EC2 ops (AWS-03/AWS-04): scheduled events, zones + Local Zone opt-in, Spot, Reserved Instances,
Capacity Reservations, Dedicated Hosts, Recycle Bin (EC2 Query + native rbin REST).

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_ec2_ops_core.py
"""
import json
import re
import time
import types

from core import ec2_ops_core as ops
from core import vpc_core as vpc


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


s = types.SimpleNamespace()


def call(p, status=200):
    r = vpc.dispatch(s, p)
    if r.status != status:
        raise AssertionError((p.get("Action"), r.status, r.body))
    return r.body


def xid(body, tag):
    m = re.search(f"<{tag}>(.*?)</{tag}>", body)
    return m.group(1) if m else None


def rbin(method, path, body=None, query=None):
    r = ops.rbin_dispatch(s, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r["status"], (json.loads(r["body"]) if r["body"] else {})


def main():
    # ── zones ──
    z = call({"Action": "DescribeAvailabilityZones"})
    _check("3 standard zones by default", z.count("<zoneName>") == 3 and "us-east-1-bos-1a" not in z)
    za = call({"Action": "DescribeAvailabilityZones", "AllAvailabilityZones": "true"})
    _check("all-zones lists local + wavelength", "us-east-1-bos-1a" in za and "wavelength-zone" in za and "not-opted-in" in za)
    call({"Action": "ModifyAvailabilityZoneGroup", "GroupName": "us-east-1-bos-1", "OptInStatus": "opted-in"})
    _check("opted-in local zone shows by default", "us-east-1-bos-1a" in call({"Action": "DescribeAvailabilityZones"}))
    _check("bad group 400", "InvalidParameterValue" in call({"Action": "ModifyAvailabilityZoneGroup", "GroupName": "nope", "OptInStatus": "opted-in"}, 400))

    # ── instance + scheduled events ──
    iid = xid(call({"Action": "RunInstances", "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1"}), "instanceId")
    st = call({"Action": "DescribeInstanceStatus", "InstanceId.1": iid})
    _check("no events initially", "<eventsSet/>" in st)
    soon = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3 * 86400))
    ev = xid(call({"Action": "VyomiScheduleInstanceEvent", "InstanceId": iid, "Code": "instance-stop", "NotBefore": soon, "Description": "host retirement"}), "instanceEventId")
    st = call({"Action": "DescribeInstanceStatus", "InstanceId.1": iid})
    _check("event listed", ev in st and "instance-stop" in st)
    _check("bad NotBefore (past) rejected", "InvalidParameterValue" in call({"Action": "ModifyInstanceEventStartTime", "InstanceId": iid, "InstanceEventId": ev, "NotBefore": "2001-01-01T00:00:00Z"}, 400))
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 4 * 86400))
    call({"Action": "ModifyInstanceEventStartTime", "InstanceId": iid, "InstanceEventId": ev, "NotBefore": later})
    m = vpc._model(s)
    m["instances"][iid]["events"][0]["not_before"] = time.time() - 5   # time travel: event is due
    st = call({"Action": "DescribeInstanceStatus", "InstanceId.1": iid, "IncludeAllInstances": "true"})
    _check("due instance-stop event completes and stops the instance", "[Completed]" in st and m["instances"][iid]["state"] == "stopped")

    # ── spot ──
    img = xid(call({"Action": "DescribeImages", "Owner.1": "amazon"}), "imageId")
    low = call({"Action": "RequestSpotInstances", "SpotPrice": "0.0001", "LaunchSpecification.ImageId": img, "LaunchSpecification.InstanceType": "t3.micro"})
    sir_low = xid(low, "spotInstanceRequestId")
    _check("too-low bid stays open (price-too-low)", "<state>open</state>" in low and "price-too-low" in low)
    hi = call({"Action": "RequestSpotInstances", "SpotPrice": "1.0", "Type": "persistent", "LaunchSpecification.ImageId": img, "LaunchSpecification.InstanceType": "t3.micro"})
    sir = xid(hi, "spotInstanceRequestId")
    _check("fulfilled bid launches a real spot instance", "<state>active</state>" in hi and xid(hi, "instanceId"))
    spot_inst = xid(hi, "instanceId")
    d = call({"Action": "DescribeInstances", "InstanceId.1": spot_inst})
    _check("instance shows spot lifecycle", "<instanceLifecycle>spot</instanceLifecycle>" in d and sir in d)
    call({"Action": "TerminateInstances", "InstanceId.1": spot_inst})
    dd = call({"Action": "DescribeSpotInstanceRequests", "SpotInstanceRequestId.1": sir})
    _check("persistent request relaunches after termination", "<state>active</state>" in dd and spot_inst not in dd)
    c = call({"Action": "CancelSpotInstanceRequests", "SpotInstanceRequestId.1": sir_low})
    _check("cancel", "<state>cancelled</state>" in c)
    _check("unknown request 400", "NotFound" in call({"Action": "DescribeSpotInstanceRequests", "SpotInstanceRequestId.1": "sir-nope"}, 400))
    h = call({"Action": "DescribeSpotPriceHistory", "InstanceType.1": "t3.micro", "AvailabilityZone": "us-east-1a"})
    _check("price history is hourly + deterministic", h.count("<spotPrice>") >= 24 and re.findall(r"<spotPrice>(.*?)</spotPrice>", h) == re.findall(r"<spotPrice>(.*?)</spotPrice>", call({"Action": "DescribeSpotPriceHistory", "InstanceType.1": "t3.micro", "AvailabilityZone": "us-east-1a"})))
    _check("RunInstances MarketType=spot with too-low MaxPrice rejected", "SpotMaxPriceTooLow" in call({"Action": "RunInstances", "ImageId": img, "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1", "InstanceMarketOptions.MarketType": "spot", "InstanceMarketOptions.SpotOptions.MaxPrice": "0.00001"}, 400))
    sp = xid(call({"Action": "RunInstances", "ImageId": img, "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1", "InstanceMarketOptions.MarketType": "spot"}), "instanceId")
    _check("RunInstances spot creates a fulfilled request", sp in call({"Action": "DescribeSpotInstanceRequests"}))

    # ── reserved instances ──
    offs = call({"Action": "DescribeReservedInstancesOfferings", "InstanceType": "m5.large", "OfferingClass": "standard"})
    oid = xid(offs, "reservedInstancesOfferingId")
    _check("offerings listed (3 payment x 2 terms)", offs.count("<reservedInstancesOfferingId>") == 6)
    _check("bad offering 400", "InvalidReservedInstancesOfferingId" in call({"Action": "PurchaseReservedInstancesOffering", "ReservedInstancesOfferingId": "nope", "InstanceCount": "1"}, 400))
    ri = xid(call({"Action": "PurchaseReservedInstancesOffering", "ReservedInstancesOfferingId": oid, "InstanceCount": "2"}), "reservedInstancesId")
    dr = call({"Action": "DescribeReservedInstances"})
    _check("purchased RI active", ri in dr and "<state>active</state>" in dr and "<instanceCount>2</instanceCount>" in dr)

    # ── capacity reservations ──
    cr = xid(call({"Action": "CreateCapacityReservation", "InstanceType": "t3.micro", "InstancePlatform": "Linux/UNIX", "AvailabilityZone": "us-east-1b", "InstanceCount": "1", "InstanceMatchCriteria": "targeted"}), "capacityReservationId")
    _check("avail = total", "<availableInstanceCount>1</availableInstanceCount>" in call({"Action": "DescribeCapacityReservations", "CapacityReservationId.1": cr}))
    i1 = xid(call({"Action": "RunInstances", "ImageId": img, "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1", "CapacityReservationSpecification.CapacityReservationTarget.CapacityReservationId": cr}), "instanceId")
    _check("launch consumes reservation", "<availableInstanceCount>0</availableInstanceCount>" in call({"Action": "DescribeCapacityReservations", "CapacityReservationId.1": cr}))
    _check("second launch -> InsufficientInstanceCapacity", "InsufficientInstanceCapacity" in call({"Action": "RunInstances", "ImageId": img, "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1", "CapacityReservationSpecification.CapacityReservationTarget.CapacityReservationId": cr}, 400))
    call({"Action": "TerminateInstances", "InstanceId.1": i1})
    _check("terminate frees capacity", "<availableInstanceCount>1</availableInstanceCount>" in call({"Action": "DescribeCapacityReservations", "CapacityReservationId.1": cr}))
    i1b = xid(call({"Action": "RunInstances", "ImageId": img, "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1", "CapacityReservationSpecification.CapacityReservationTarget.CapacityReservationId": cr}), "instanceId")
    _check("modify below used rejected", "InvalidParameterValue" in call({"Action": "ModifyCapacityReservation", "CapacityReservationId": cr, "InstanceCount": "0"}, 400))
    call({"Action": "TerminateInstances", "InstanceId.1": i1b})
    call({"Action": "CancelCapacityReservation", "CapacityReservationId": cr})
    _check("cancelled reservation can't be targeted", "CapacityReservationIncorrectState" in call({"Action": "RunInstances", "ImageId": img, "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1", "CapacityReservationSpecification.CapacityReservationTarget.CapacityReservationId": cr}, 400))
    _check("bad platform 400", "InvalidParameterValue" in call({"Action": "CreateCapacityReservation", "InstanceType": "t3.micro", "InstancePlatform": "Plan9", "AvailabilityZone": "us-east-1a", "InstanceCount": "1"}, 400))

    # ── dedicated hosts ──
    hid = xid(call({"Action": "AllocateHosts", "AvailabilityZone": "us-east-1a", "InstanceType": "m5.large", "Quantity": "1"}), "item")
    _check("host available w/ capacity", "<availableCapacity>48</availableCapacity>" in call({"Action": "DescribeHosts", "HostId.1": hid}))
    _check("wrong instance type rejected", "InvalidParameterCombination" in call({"Action": "RunInstances", "ImageId": img, "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1", "Placement.HostId": hid, "Placement.Tenancy": "host"}, 400))
    hi_ = xid(call({"Action": "RunInstances", "ImageId": img, "InstanceType": "m5.large", "MinCount": "1", "MaxCount": "1", "Placement.HostId": hid, "Placement.Tenancy": "host"}), "instanceId")
    dh = call({"Action": "DescribeHosts", "HostId.1": hid})
    _check("instance on host + capacity decremented", hi_ in dh and "<availableCapacity>47</availableCapacity>" in dh)
    rel = call({"Action": "ReleaseHosts", "HostId.1": hid})
    _check("release with instances fails (HostNotEmpty)", "HostNotEmpty" in rel)
    call({"Action": "TerminateInstances", "InstanceId.1": hi_})
    # terminated instances still hold host? (they must not)
    m = vpc._model(s)
    m["instances"][hi_]["state"] = "terminated"
    _check("release succeeds when empty", f"<successful><item>{hid}</item>" in call({"Action": "ReleaseHosts", "HostId.1": hid}))

    # ── recycle bin ──
    _check("create rule validation", rbin("POST", "/rules", {"ResourceType": "EBS_SNAPSHOT", "RetentionPeriod": {"RetentionPeriodValue": 0, "RetentionPeriodUnit": "DAYS"}})[0] == 400)
    stt, rule = rbin("POST", "/rules", {"ResourceType": "EBS_SNAPSHOT", "RetentionPeriod": {"RetentionPeriodValue": 7, "RetentionPeriodUnit": "DAYS"}, "Description": "keep snaps"})
    _check("rule created", stt in (200, 201) and rule["Status"] == "available")
    rid = rule["Identifier"]
    vol = xid(call({"Action": "CreateVolume", "AvailabilityZone": "us-east-1a", "Size": "8"}), "volumeId")
    snap = xid(call({"Action": "CreateSnapshot", "VolumeId": vol}), "snapshotId")
    call({"Action": "DeleteSnapshot", "SnapshotId": snap})
    _check("deleted snapshot gone from DescribeSnapshots", snap not in call({"Action": "DescribeSnapshots"}))
    _check("deleted snapshot in the bin", snap in call({"Action": "ListSnapshotsInRecycleBin"}))
    rs = call({"Action": "RestoreSnapshotFromRecycleBin", "SnapshotId": snap})
    _check("restore brings it back", snap in call({"Action": "DescribeSnapshots"}) and snap not in call({"Action": "ListSnapshotsInRecycleBin"}))
    call({"Action": "DeleteSnapshot", "SnapshotId": snap})
    vpc._model(s)["rbin_items"][snap]["expires_at"] = time.time() - 1
    _check("retention expiry purges permanently", snap not in call({"Action": "ListSnapshotsInRecycleBin"}) and "InvalidSnapshot.NotFound" in call({"Action": "RestoreSnapshotFromRecycleBin", "SnapshotId": snap}, 400))
    # tag-level rule + AMI
    stt, ar = rbin("POST", "/rules", {"ResourceType": "EC2_IMAGE", "RetentionPeriod": {"RetentionPeriodValue": 3, "RetentionPeriodUnit": "DAYS"}, "ResourceTags": [{"ResourceTagKey": "keep", "ResourceTagValue": "yes"}]})
    i2 = xid(call({"Action": "RunInstances", "ImageId": img, "InstanceType": "t3.micro", "MinCount": "1", "MaxCount": "1"}), "instanceId")
    a1 = xid(call({"Action": "CreateImage", "InstanceId": i2, "Name": "untagged"}), "imageId")
    a2 = xid(call({"Action": "CreateImage", "InstanceId": i2, "Name": "tagged", "TagSpecification.1.ResourceType": "image", "TagSpecification.1.Tag.1.Key": "keep", "TagSpecification.1.Tag.1.Value": "yes"}), "imageId")
    call({"Action": "DeregisterImage", "ImageId": a1})
    call({"Action": "DeregisterImage", "ImageId": a2})
    lb = call({"Action": "ListImagesInRecycleBin"})
    _check("only the tag-matching image is retained", a2 in lb and a1 not in lb)
    call({"Action": "RestoreImageFromRecycleBin", "ImageId": a2})
    _check("image restored", a2 in call({"Action": "DescribeImages", "Owner.1": "self"}))
    # lock
    _check("update", rbin("PATCH", f"/rules/{rid}", {"Description": "x"})[0] == 200)
    stt, lk = rbin("PATCH", f"/rules/{rid}/lock", {"LockConfiguration": {"UnlockDelay": {"UnlockDelayValue": 7, "UnlockDelayUnit": "DAYS"}}})
    _check("locked", lk["LockState"] == "locked")
    _check("locked rule can't be deleted (409)", rbin("DELETE", f"/rules/{rid}")[0] == 409)
    _check("locked rule can't be updated (409)", rbin("PATCH", f"/rules/{rid}", {"Description": "y"})[0] == 409)
    stt, ul = rbin("PATCH", f"/rules/{rid}/unlock")
    _check("pending_unlock w/ end time", ul["LockState"] == "pending_unlock" and ul["LockEndTime"])
    _check("still can't delete while pending", rbin("DELETE", f"/rules/{rid}")[0] == 409)
    vpc._model(s)["rbin_rules"][rid]["lock_end"] = time.time() - 1
    _check("after the delay the rule unlocks and deletes", rbin("DELETE", f"/rules/{rid}")[0] == 204)
    _check("list rules by type", [r["Identifier"] for r in rbin("POST", "/list-rules", {"ResourceType": "EC2_IMAGE"})[1]["Rules"]] == [ar["Identifier"]])
    # ── IAM instance profiles (Create IAM profile) ──
    from core import iam_core
    from core.iam_store import IamStore
    ist = IamStore()
    d = lambda a, **k: iam_core.dispatch(ist, {"Action": a, **k})
    d("CreateRole", RoleName="web", AssumeRolePolicyDocument='{"Version":"2012-10-17","Statement":[]}')
    _check("create profile", "<InstanceProfileName>web-p</InstanceProfileName>" in d("CreateInstanceProfile", InstanceProfileName="web-p").body)
    _check("duplicate 409", d("CreateInstanceProfile", InstanceProfileName="web-p").status == 409)
    _check("add role", d("AddRoleToInstanceProfile", InstanceProfileName="web-p", RoleName="web").status == 200)
    _check("one role per profile", d("AddRoleToInstanceProfile", InstanceProfileName="web-p", RoleName="web").status == 409)
    _check("profile lists its role", "<RoleName>web</RoleName>" in d("GetInstanceProfile", InstanceProfileName="web-p").body)
    _check("role in a profile can't be deleted", d("DeleteRole", RoleName="web").status == 409)
    _check("non-empty profile can't be deleted", d("DeleteInstanceProfile", InstanceProfileName="web-p").status == 409)
    d("RemoveRoleFromInstanceProfile", InstanceProfileName="web-p", RoleName="web")
    _check("empty profile deletes", d("DeleteInstanceProfile", InstanceProfileName="web-p").status == 200)
    print("PASS")


main()
