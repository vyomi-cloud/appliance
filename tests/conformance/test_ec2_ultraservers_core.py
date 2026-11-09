"""EC2 Capacity Blocks (core/ec2_ultraservers_core): bookings that REALLY reserve capacity. A block creates a real EC2 Capacity
Reservation; RunInstances (EC2 Query, the engine Nano runs and the offline appliance's core path uses) consumes it, is refused
when it is full / not started / expired, and terminating frees it. Pool accounting is checked against the host-sized pool.
UltraServers / accelerator types are Not in scope and must say so.

Run: PYTHONPATH=. python3 tests/conformance/test_ec2_ultraservers_core.py
"""
import json
import os
import re
import time
import types

os.environ["VYOMI_CAPACITY_POOL_MB"] = "8192"

from core import ec2_ops_core  # noqa: F401  (installs the RunInstances reservation wrapper)
from core import ec2_ultraservers_core as cb
from core import vpc_core as vpc

s = types.SimpleNamespace()


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def blk(op, body=None, now=None):
    r = cb.dispatch(s, "POST", "/" + op, json.dumps(body or {}).encode(), now=now)
    return r["status"], json.loads(r["body"])


def ec2(p, status=200):
    r = vpc.dispatch(s, p)
    if r.status != status:
        raise AssertionError((p.get("Action"), r.status, r.body))
    return r.body


def xid(body, tag):
    m = re.search(f"<{tag}>(.*?)</{tag}>", body)
    return m.group(1) if m else None


def launch(cr, n=1, itype="t3.small", expect=200):
    return ec2({"Action": "RunInstances", "ImageId": IMG, "InstanceType": itype, "MinCount": str(n), "MaxCount": str(n),
                "CapacityReservationSpecification.CapacityReservationTarget.CapacityReservationId": cr}, expect)


IMG = None


def main():
    global IMG
    # --- not in scope: accelerator types / UltraServers
    st, v = blk("DescribeCapacityBlockOfferings", {"InstanceType": "p5.48xlarge", "InstanceCount": 1, "CapacityDurationDays": 1})
    _check("p5 -> UnsupportedOperation, says Not in scope", st == 400 and v["__type"] == "UnsupportedOperation" and "not in scope" in v["message"])
    _check("UltraServer type rejected", blk("DescribeCapacityBlockOfferings", {"InstanceType": "u-p6e-gb200x72", "InstanceCount": 1, "CapacityDurationDays": 7})[0] == 400)
    _check("DescribeUltraServers is not an operation", blk("DescribeUltraServers")[0] == 404)
    # --- validation
    _check("missing type", blk("DescribeCapacityBlockOfferings", {})[0] == 400)
    _check("bad duration", blk("DescribeCapacityBlockOfferings", {"InstanceType": "t3.small", "CapacityDurationDays": 15})[0] == 400)
    _check("bad count", blk("DescribeCapacityBlockOfferings", {"InstanceType": "t3.small", "InstanceCount": 0, "CapacityDurationDays": 1})[0] == 400)
    _check("past range", blk("DescribeCapacityBlockOfferings", {"InstanceType": "t3.small", "CapacityDurationDays": 1, "StartDateRange": 1000})[0] == 400)
    img = ec2({"Action": "DescribeImages"})
    IMG = xid(img, "imageId")

    # --- an immediate block of 2 x t3.small (2 GiB each)
    st, v = blk("DescribeCapacityBlockOfferings", {"InstanceType": "t3.small", "InstanceCount": 2, "CapacityDurationDays": 1})
    _check("offerings", st == 200 and len(v["capacityBlockOfferings"]) == 3, str(v))
    off = v["capacityBlockOfferings"][0]
    st, b = blk("PurchaseCapacityBlock", {"CapacityBlockOfferingId": off["capacityBlockOfferingId"]})
    cbk = b["capacityBlock"]
    _check("purchase -> active, reserves 4096 MB", st == 200 and cbk["state"] == "active" and cbk["reservedMemoryMb"] == 4096, str(cbk))
    _check("double purchase rejected", blk("PurchaseCapacityBlock", {"CapacityBlockOfferingId": off["capacityBlockOfferingId"]})[0] == 400)
    cr = cbk["capacityReservationId"]
    d = ec2({"Action": "DescribeCapacityReservations", "CapacityReservationId.1": cr})
    _check("a REAL EC2 capacity reservation exists", "<state>active</state>" in d and "<totalInstanceCount>2</totalInstanceCount>" in d and "<availableInstanceCount>2</availableInstanceCount>" in d)

    # --- RunInstances really consumes it
    i1 = xid(launch(cr), "instanceId")
    _check("launch consumes (1 left)", "<availableInstanceCount>1</availableInstanceCount>" in ec2({"Action": "DescribeCapacityReservations", "CapacityReservationId.1": cr}))
    _check("status shows 1 used of 2", blk("DescribeCapacityBlockStatus")[1]["capacityBlockStatuses"][0]["totalUsedCapacity"] == 1)
    _check("wrong type refused", "InvalidParameterValue" in launch(cr, itype="t3.micro", expect=400))
    i2 = xid(launch(cr), "instanceId")
    _check("full reservation refuses a launch", "InsufficientInstanceCapacity" in launch(cr, expect=400))
    ec2({"Action": "TerminateInstances", "InstanceId.1": i1})
    _check("terminate frees capacity", "<availableInstanceCount>1</availableInstanceCount>" in ec2({"Action": "DescribeCapacityReservations", "CapacityReservationId.1": cr}))
    launch(cr)

    # --- pool accounting (pool 8192 MB, 4096 booked now)
    st, v = blk("DescribeCapacityBlockOfferings", {"InstanceType": "t3.small", "InstanceCount": 2, "CapacityDurationDays": 1})
    _check("second 4096 MB fits the pool", st == 200)
    blk("PurchaseCapacityBlock", {"CapacityBlockOfferingId": v["capacityBlockOfferings"][0]["capacityBlockOfferingId"]})
    st, v = blk("DescribeCapacityBlockOfferings", {"InstanceType": "t3.small", "InstanceCount": 2, "CapacityDurationDays": 1,
                                                    "EndDateRange": time.time() + 86400 + 3600})
    _check("pool full over that window -> InsufficientCapacity", st == 400 and v["__type"] == "InsufficientCapacity", str(v))
    _check("request bigger than the whole pool", blk("DescribeCapacityBlockOfferings", {"InstanceType": "t3.small", "InstanceCount": 64, "CapacityDurationDays": 1})[1]["__type"] == "InsufficientCapacity")

    # --- scheduled block: not usable until it starts; release works
    st, v = blk("DescribeCapacityBlockOfferings", {"InstanceType": "t3.micro", "InstanceCount": 1, "CapacityDurationDays": 1,
                                                    "StartDateRange": time.time() + 5 * 86400, "EndDateRange": time.time() + 9 * 86400})
    st, b3 = blk("PurchaseCapacityBlock", {"CapacityBlockOfferingId": v["capacityBlockOfferings"][0]["capacityBlockOfferingId"]})
    c3 = b3["capacityBlock"]
    _check("future block scheduled", c3["state"] == "scheduled")
    _check("launch into scheduled reservation refused", "CapacityReservationIncorrectState" in launch(c3["capacityReservationId"], itype="t3.micro", expect=400))
    _check("cannot extend a scheduled block", blk("ExtendCapacityBlock", {"CapacityBlockId": c3["capacityBlockId"], "CapacityBlockExtensionDurationDays": 7})[0] == 400)
    st, rel = blk("VyomiCancelCapacityBlock", {"CapacityBlockId": c3["capacityBlockId"]})
    _check("release scheduled", st == 200 and rel["capacityBlock"]["state"] == "cancelled")

    # --- the block starts later (clock moves): scheduled -> active through settle
    m = vpc._model(s)
    m["capacity_blocks"]["blocks"][c3["capacityBlockId"]]["state"] = "ok"      # un-release for the clock test
    m["capacity_reservations"][c3["capacityReservationId"]]["state"] = "scheduled"
    t_mid = m["capacity_blocks"]["blocks"][c3["capacityBlockId"]]["start"] + 60
    _check("scheduled -> active at start", blk("DescribeCapacityBlocks", {"CapacityBlockIds": [c3["capacityBlockId"]]}, now=t_mid)[1]["capacityBlocks"][0]["state"] == "active")
    _check("extend an active block", blk("ExtendCapacityBlock", {"CapacityBlockId": c3["capacityBlockId"], "CapacityBlockExtensionDurationDays": 7}, now=t_mid)[0] == 200)
    t_end = m["capacity_blocks"]["blocks"][c3["capacityBlockId"]]["end"] + 60
    _check("expires on schedule", blk("DescribeCapacityBlocks", {"CapacityBlockIds": [c3["capacityBlockId"]]}, now=t_end)[1]["capacityBlocks"][0]["state"] == "expired")
    _check("reservation expired with it", m["capacity_reservations"][c3["capacityReservationId"]]["state"] == "expired")

    # --- offline appliance hook (same rules over Docker-backed instance counts)
    ok = cb.admit_launch(m, cr, "t3.small", "", 1, used=1)
    _check("admit_launch allows within capacity", ok == cr)
    for used, count, code in ((2, 1, "InsufficientInstanceCapacity"), (0, 3, "InsufficientInstanceCapacity")):
        try:
            cb.admit_launch(m, cr, "t3.small", "", count, used=used)
            raise AssertionError("expected refusal")
        except cb._Err as e:
            _check(f"admit_launch refuses used={used} count={count}", e.code == code)
    try:
        cb.admit_launch(m, c3["capacityReservationId"], "t3.micro", "", 1, used=0)
        raise AssertionError("expected refusal")
    except cb._Err as e:
        _check("admit_launch refuses an expired block", e.code == "CapacityReservationIncorrectState")

    ov = blk("VyomiOverview")[1]
    _check("overview has pool + not-in-scope text", ov["poolMb"] == 8192 and "not in scope" in ov["notInScope"] and ov["blocksByState"]["active"] >= 2)
    print("PASS")


if __name__ == "__main__":
    main()
