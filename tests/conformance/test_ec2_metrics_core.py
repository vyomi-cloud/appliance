"""EC2 instance / EBS volume CloudWatch metrics from real counters (AWS-05): parse -> delta -> AWS/EC2 + AWS/EBS series.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_ec2_metrics_core.py
Add LIVE_CONTAINER=<docker container> to also read the counters from a real running container.
"""
import os
import subprocess

from core import cloudwatch_core as cw
from core import ec2_metrics_core as em


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def blob(rx=0, rxp=0, tx=0, txp=0, cpu=0, rb=0, wb=0, ri=0, wi=0):
    return (f"Inter-|   Receive\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
            f"    lo:  99 9 0 0 0 0 0 0  99 9 0 0 0 0 0 0\n  eth0: {rx} {rxp} 0 0 0 0 0 0 {tx} {txp} 0 0 0 0 0 0\ndocker0: 5 5 0 0 0 0 0 0 5 5 0 0 0 0 0 0\n"
            f"{em.SECTION_CPU}\nusage_usec {cpu}\nuser_usec 1\n{em.SECTION_IO}\n254:0 rbytes={rb} wbytes={wb} rios={ri} wios={wi} dbytes=0 dios=0\n254:16 rbytes=10 wbytes=0 rios=1 wios=0 dbytes=0 dios=0\n")


def points(store, ns, name, dims):
    s = cw._series(store, ns, name, dims, create=False)
    return [] if not s else [p[1] for p in s["points"]]


def main():
    c0 = em.parse_counters(blob(rx=1000, rxp=10, tx=500, txp=5, cpu=1_000_000, rb=4096, wb=0, ri=2, wi=0))
    _check("parse sums eth*, ignores lo/docker0", c0["rx_bytes"] == 1000 and c0["tx_packets"] == 5)
    _check("parse sums cgroup io across devices", c0["rbytes"] == 4106 and c0["rios"] == 3)
    _check("garbage -> None", em.parse_counters("nope") is None and em.parse_counters("") is None)

    store = cw.CloudWatchStore()
    prev = {}
    _check("baseline reading publishes nothing", em.publish(store, "i-1", c0, prev, 1000.0, vcpus=2, volume_id="vol-1") == [])
    c1 = em.parse_counters(blob(rx=3000, rxp=30, tx=900, txp=9, cpu=1_000_000 + 12_000_000, rb=4096 + 8192, wb=65536, ri=4, wi=16))
    names = em.publish(store, "i-1", c1, prev, 1060.0, vcpus=2, volume_id="vol-1")
    _check("publishes instance + volume metrics", "CPUUtilization" in names and "VolumeWriteBytes" in names and len(names) == 14)
    I = [{"Name": "InstanceId", "Value": "i-1"}]
    V = [{"Name": "VolumeId", "Value": "vol-1"}]
    _check("CPU% = used / (wall x vCPUs)", points(store, "AWS/EC2", "CPUUtilization", I) == [10.0])
    _check("NetworkIn/Out are interval deltas", points(store, "AWS/EC2", "NetworkIn", I) == [2000] and points(store, "AWS/EC2", "NetworkOut", I) == [400])
    _check("packets + EBS ops", points(store, "AWS/EC2", "NetworkPacketsIn", I) == [20] and points(store, "AWS/EC2", "EBSWriteOps", I) == [16])
    _check("volume metrics", points(store, "AWS/EBS", "VolumeWriteBytes", V) == [65536] and points(store, "AWS/EBS", "VolumeConsumedReadWriteOps", V) == [18])
    # counter reset (container restart) clamps instead of going negative
    c2 = em.parse_counters(blob(rx=100, rxp=1, tx=100, txp=1, cpu=500, rb=0, wb=0, ri=0, wi=0))
    em.publish(store, "i-1", c2, prev, 1120.0, vcpus=2, volume_id="vol-1")
    _check("counter reset clamps to 0", points(store, "AWS/EC2", "NetworkIn", I)[-1] == 0)
    _check("same-timestamp reading is skipped", em.publish(store, "i-1", c2, prev, 1120.0) == [])
    live = os.environ.get("LIVE_CONTAINER")
    if live:
        out = subprocess.run(["docker", "exec", live] + em.READ_COUNTERS_CMD, capture_output=True, text=True, timeout=30).stdout
        lc = em.parse_counters(out)
        _check("live container counters parse", lc is not None and lc["cpu_usec"] and lc["cpu_usec"] > 0)
        lp = {}
        em.publish(store, "i-live", lc, lp, 1.0, vcpus=1)
        out2 = subprocess.run(["docker", "exec", live] + em.READ_COUNTERS_CMD, capture_output=True, text=True, timeout=30).stdout
        names = em.publish(store, "i-live", em.parse_counters(out2), lp, 61.0, vcpus=1, volume_id="vol-live")
        _check("live container publishes real series", "CPUUtilization" in names)
    print("EC2 metrics core: all green")


if __name__ == "__main__":
    main()
