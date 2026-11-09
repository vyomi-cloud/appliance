"""Dev Simplified EC2 Capacity Blocks + UltraServers (core/ec2_ultraservers_core): AWS validation rules and the clock-driven lifecycle.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_ec2_ultraservers_core.py
"""
import json
import time

from core.aws_wire_router import AwsWireRouter

AUTH = "AWS4-HMAC-SHA256 Credential=T/20261110/us-east-1/vyomi-ultraservers/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def call(r, op, body=None):
    o = r.handle("POST", "/" + op, {}, {"authorization": AUTH, "content-type": "application/json"}, json.dumps(body or {}).encode())
    return o["status"], json.loads(o["body"])


def main():
    r = AwsWireRouter()
    _check("missing type", call(r, "DescribeCapacityBlockOfferings", {})[0] == 400)
    _check("unknown type", call(r, "DescribeCapacityBlockOfferings", {"InstanceType": "m5.large"})[0] == 400)
    _check("bad duration (15 days)", call(r, "DescribeCapacityBlockOfferings", {"InstanceType": "p5.48xlarge", "InstanceCount": 1, "CapacityDurationDays": 15})[0] == 400)
    _check("count too large", call(r, "DescribeCapacityBlockOfferings", {"InstanceType": "p5.48xlarge", "InstanceCount": 65, "CapacityDurationDays": 1})[0] == 400)
    _check("range in the past", call(r, "DescribeCapacityBlockOfferings", {"InstanceType": "p5.48xlarge", "InstanceCount": 1, "CapacityDurationDays": 1, "StartDateRange": 1000})[0] == 400)

    s, v = call(r, "DescribeCapacityBlockOfferings", {"UltraServerType": "u-p6e-gb200x72", "UltraServerCount": 1, "CapacityDurationDays": 7})
    _check("ultraserver offerings", s == 200 and len(v["capacityBlockOfferings"]) == 3 and v["capacityBlockOfferings"][0]["source"] == "Dev Simplified")
    off = v["capacityBlockOfferings"][0]
    s, b = call(r, "PurchaseCapacityBlock", {"CapacityBlockOfferingId": off["capacityBlockOfferingId"]})
    cb = b["capacityBlock"]
    _check("purchase", s == 200 and cb["instanceCount"] == 18 and cb["acceleratorCount"] == 72 and cb["state"] in ("scheduled", "active"))
    _check("double purchase rejected", call(r, "PurchaseCapacityBlock", {"CapacityBlockOfferingId": off["capacityBlockOfferingId"]})[0] == 400)
    _check("unknown offering 404", call(r, "PurchaseCapacityBlock", {"CapacityBlockOfferingId": "cbo-nope"})[0] == 404)

    s, u = call(r, "DescribeUltraServers")
    _check("one ultraserver with 18 hosts", s == 200 and len(u["ultraServers"]) == 1 and u["ultraServers"][0]["hostCount"] == 18 and u["ultraServers"][0]["acceleratorCount"] == 72)

    # instance-type block is not an UltraServer
    s, v = call(r, "DescribeCapacityBlockOfferings", {"InstanceType": "p5.48xlarge", "InstanceCount": 2, "CapacityDurationDays": 14})
    s, b2 = call(r, "PurchaseCapacityBlock", {"CapacityBlockOfferingId": v["capacityBlockOfferings"][1]["capacityBlockOfferingId"]})
    _check("p5 block 16 GPUs", b2["capacityBlock"]["acceleratorCount"] == 16)
    _check("ultraservers list unchanged", len(call(r, "DescribeUltraServers")[1]["ultraServers"]) == 1)
    _check("filter by state", len(call(r, "DescribeCapacityBlocks", {"States": ["expired"]})[1]["capacityBlocks"]) == 0)
    _check("bad state", call(r, "DescribeCapacityBlocks", {"States": ["bogus"]})[0] == 400)

    # lifecycle with a controlled clock
    from core import ec2_ultraservers_core as c
    store = r.vpc
    t0 = time.time()
    bid = b2["capacityBlock"]["capacityBlockId"]
    far = t0 + 30 * 86400
    st = c.dispatch(store, "POST", "/DescribeCapacityBlocks", b"{}", now=far)
    states = {x["capacityBlockId"]: x["state"] for x in json.loads(st["body"])["capacityBlocks"]}
    _check("all expired after 30 days", set(states.values()) == {"expired"}, str(states))
    ex = c.dispatch(store, "POST", "/ExtendCapacityBlock", json.dumps({"CapacityBlockId": bid, "CapacityBlockExtensionDurationDays": 7}).encode(), now=far)
    _check("cannot extend expired", ex["status"] == 400)
    _check("cannot release expired", call_at(c, store, "VyomiCancelCapacityBlock", {"CapacityBlockId": bid}, far) == 400)
    mid = b2["capacityBlock"]
    start = time.mktime(time.strptime(mid["startDate"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    _check("extend active", call_at(c, store, "ExtendCapacityBlock", {"CapacityBlockId": bid, "CapacityBlockExtensionDurationDays": 7}, start + 3600) == 200)
    _check("extend invalid days", call_at(c, store, "ExtendCapacityBlock", {"CapacityBlockId": bid, "CapacityBlockExtensionDurationDays": 20}, start + 3600) == 400)
    # a fresh scheduled block can be released
    s, v = call(r, "DescribeCapacityBlockOfferings", {"InstanceType": "trn2.48xlarge", "InstanceCount": 1, "CapacityDurationDays": 1,
                                                       "StartDateRange": time.time() + 5 * 86400, "EndDateRange": time.time() + 9 * 86400})
    s, b3 = call(r, "PurchaseCapacityBlock", {"CapacityBlockOfferingId": v["capacityBlockOfferings"][0]["capacityBlockOfferingId"]})
    _check("future block scheduled", b3["capacityBlock"]["state"] == "scheduled")
    s, rel = call(r, "VyomiCancelCapacityBlock", {"CapacityBlockId": b3["capacityBlock"]["capacityBlockId"]})
    _check("release scheduled", s == 200 and rel["capacityBlock"]["state"] == "cancelled")
    _check("status op", call(r, "DescribeCapacityBlockStatus")[0] == 200)
    ov = call(r, "VyomiOverview")[1]
    _check("overview", ov["blocksByState"]["cancelled"] == 1 and len(ov["supportedTypes"]) >= 10 and ov["source"] == "Dev Simplified")
    print("PASS")


def call_at(c, store, op, body, now):
    return c.dispatch(store, "POST", "/" + op, json.dumps(body).encode(), now=now)["status"]


if __name__ == "__main__":
    main()
