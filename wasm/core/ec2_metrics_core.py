# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""EC2 instance and EBS volume CloudWatch metrics from REAL measured counters — substrate-independent.

The instance runtime (offline: the Docker container behind the instance; Nano: no measurable runtime) hands this module the
cumulative kernel counters it can read from inside the instance — /proc/net/dev, the cgroup cpu.stat and io.stat — as one text
blob (`SECTION_*` markers below). This module parses them, turns two successive readings into per-interval deltas and publishes
them into CloudWatch (namespace AWS/EC2 for the instance, AWS/EBS for its root volume) with the real metric names and units:

  AWS/EC2  CPUUtilization (Percent = CPU time used / (wall time x vCPUs)), NetworkIn / NetworkOut (Bytes),
           NetworkPacketsIn / NetworkPacketsOut (Count), EBSReadBytes / EBSWriteBytes (Bytes), EBSReadOps / EBSWriteOps (Count)
  AWS/EBS  VolumeReadBytes / VolumeWriteBytes (Bytes), VolumeReadOps / VolumeWriteOps (Count), VolumeConsumedReadWriteOps (Count)

Nothing is synthesised: the first reading only establishes the baseline, an unreadable counter publishes nothing, and an
instance with no measurable runtime (Nano, stopped, model-only) simply has no datapoints (the console draws "No data").

Honest limits: counters are the container's, which stand in for the instance's NIC and root disk (the root volume receives the
instance's whole block I/O); burst/credit metrics (CPUCreditUsage/Balance, BurstBalance), VolumeIdleTime / VolumeQueueLength /
VolumeTotalReadTime, per-volume attribution when several volumes are attached, and detailed vs basic-monitoring billing are not
produced. Pure Python, Pyodide-loadable.
"""
from __future__ import annotations

SECTION_CPU = "---CPU"
SECTION_IO = "---IO"

# The one command a runtime runs inside the instance to collect everything this module needs.
READ_COUNTERS_CMD = ["sh", "-c", f"cat /proc/net/dev; echo {SECTION_CPU}; cat /sys/fs/cgroup/cpu.stat; echo {SECTION_IO}; cat /sys/fs/cgroup/io.stat"]


def _cw():
    try:
        from core import cloudwatch_core as m
    except ImportError:                      # Pyodide flat layout
        import cloudwatch_core as m          # type: ignore
    return m


def parse_counters(text: str) -> dict | None:
    """Parse the READ_COUNTERS_CMD output. Returns cumulative counters, or None when nothing usable was read."""
    sect = "net"
    c = {"rx_bytes": 0, "rx_packets": 0, "tx_bytes": 0, "tx_packets": 0, "cpu_usec": None, "rbytes": 0, "wbytes": 0, "rios": 0, "wios": 0}
    seen_net = seen_io = False
    for line in (text or "").splitlines():
        line = line.strip()
        if line == SECTION_CPU:
            sect = "cpu"
            continue
        if line == SECTION_IO:
            sect = "io"
            continue
        if sect == "net" and ":" in line:
            name, _, rest = line.partition(":")
            f = rest.split()
            if name.strip().startswith("eth") and len(f) >= 10:
                c["rx_bytes"] += int(f[0]); c["rx_packets"] += int(f[1]); c["tx_bytes"] += int(f[8]); c["tx_packets"] += int(f[9])
                seen_net = True
        elif sect == "cpu" and line.startswith("usage_usec"):
            c["cpu_usec"] = int(line.split()[1])
        elif sect == "io" and line:
            for kv in line.split()[1:]:
                k, _, v = kv.partition("=")
                if k in c and v.isdigit():
                    c[k] += int(v)
                    seen_io = True
    if c["cpu_usec"] is None and not seen_net and not seen_io:
        return None
    return c


def publish(cw_store, instance_id: str, counters: dict, prev: dict, now: float, vcpus: int = 1, volume_id: str | None = None) -> list[str]:
    """Publish the delta since `prev` (mutated to hold this reading). Returns the metric names published ([] on the baseline reading)."""
    last = prev.get("counters")
    last_ts = prev.get("ts")
    prev["counters"], prev["ts"] = dict(counters), now
    if not last or last_ts is None or now <= last_ts:
        return []
    cw = _cw()
    dt = now - last_ts
    d = lambda k: max(0, (counters.get(k) or 0) - (last.get(k) or 0))      # counter reset (container restart) clamps to 0
    inst = [{"Name": "InstanceId", "Value": instance_id}]
    out = []

    def put(ns, name, dims, val, unit):
        cw.ingest_internal_metric(cw_store, ns, name, dims, val, unit=unit, ts=now)
        out.append(name)

    if counters.get("cpu_usec") is not None and last.get("cpu_usec") is not None:
        used = max(0, counters["cpu_usec"] - last["cpu_usec"])
        put("AWS/EC2", "CPUUtilization", inst, round(min(100.0, 100.0 * used / (dt * 1e6 * max(1, vcpus))), 4), "Percent")
    put("AWS/EC2", "NetworkIn", inst, d("rx_bytes"), "Bytes")
    put("AWS/EC2", "NetworkOut", inst, d("tx_bytes"), "Bytes")
    put("AWS/EC2", "NetworkPacketsIn", inst, d("rx_packets"), "Count")
    put("AWS/EC2", "NetworkPacketsOut", inst, d("tx_packets"), "Count")
    put("AWS/EC2", "EBSReadBytes", inst, d("rbytes"), "Bytes")
    put("AWS/EC2", "EBSWriteBytes", inst, d("wbytes"), "Bytes")
    put("AWS/EC2", "EBSReadOps", inst, d("rios"), "Count")
    put("AWS/EC2", "EBSWriteOps", inst, d("wios"), "Count")
    if volume_id:
        vol = [{"Name": "VolumeId", "Value": volume_id}]
        put("AWS/EBS", "VolumeReadBytes", vol, d("rbytes"), "Bytes")
        put("AWS/EBS", "VolumeWriteBytes", vol, d("wbytes"), "Bytes")
        put("AWS/EBS", "VolumeReadOps", vol, d("rios"), "Count")
        put("AWS/EBS", "VolumeWriteOps", vol, d("wios"), "Count")
        put("AWS/EBS", "VolumeConsumedReadWriteOps", vol, d("rios") + d("wios"), "Count")
    return out
