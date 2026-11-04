# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""netsim traffic mirroring — AWS Traffic Mirroring sessions applied to the real per-flow counters the enforcer reads.

Input: the VPC model (`tm_sessions` / `tm_filters` / `tm_targets`, created through the real EC2 API in core/vpc_extras_core) and the
per-window DELTA rows from `FlowLogCollector.ingest` (accepted flows only: a packet the security group dropped never reaches the
ENI's mirror, same as AWS). For every source ENI (an OUR-ENI end of the flow) the session with the lowest SessionNumber whose
filter ACCEPTS the packet claims it (rule evaluation = vpc_extras_core.mirror_decision: lowest rule number first, reject rules
exclude, no match = not mirrored); the claimed flow is recorded as a mirror capture {session, target, vni, direction, flow, packets,
bytes (truncated to PacketLength)}.

Honest limit: a capture is a FLOW SUMMARY, not a VXLAN-encapsulated copy of packets — the target ENI / NLB receives no packets (no
Suricata / Zeek on the target sees anything). The captures are written to CloudWatch Logs group
`/vyomi/traffic-mirror/<session-id>` (stream = source ENI) so they can be read with `aws logs`.
Pure Python (Pyodide-loadable).
"""
from __future__ import annotations

import json

LOG_GROUP_PREFIX = "/vyomi/traffic-mirror/"


def _decision(m, session, direction, proto, src, dst, sport, dport):
    try:
        from core import vpc_extras_core as x
    except ImportError:                                   # pragma: no cover - flat layout
        import vpc_extras_core as x                       # type: ignore
    return x.mirror_decision(m, session, direction, proto, src, dst, sport, dport)


def mirror_captures(m: dict, topo, rows: list, now: int) -> list:
    sessions = list((m.get("tm_sessions") or {}).values())
    if not sessions or not rows:
        return []
    by_eni: dict = {}
    for s in sorted(sessions, key=lambda s: s["number"]):
        by_eni.setdefault(s["eni"], []).append(s)
    targets = m.get("tm_targets") or {}
    out = []
    for r in rows:
        if r.get("action", "ACCEPT") != "ACCEPT":
            continue
        for direction, own, other in (("egress", r["src"], r["dst"]), ("ingress", r["dst"], r["src"])):
            iface = topo.iface_by_ip(own)
            if iface is None or iface.ip != own or iface.id not in by_eni:
                continue
            for s in by_eni[iface.id]:
                if _decision(m, s, direction, r["proto"], r["src"], r["dst"], r["sport"], r["dport"]) != "accept":
                    continue
                t = targets.get(s["target"]) or {}
                nbytes = r["bytes"]
                if s.get("packet_length"):
                    nbytes = min(nbytes, s["packet_length"] * r["packets"])
                out.append({"sessionId": s["id"], "targetId": s["target"], "targetType": t.get("type"), "filterId": s["filter"], "sourceEni": iface.id,
                            "direction": direction, "vni": s["vni"], "packetLength": s.get("packet_length") or 0,
                            "srcaddr": r["src"], "dstaddr": r["dst"], "srcport": r["sport"], "dstport": r["dport"], "protocol": r["proto"],
                            "packets": r["packets"], "bytes": nbytes, "timestamp": now})
                break          # one session claims a packet at a given ENI (lowest session number wins)
    return out


def deliver(m: dict, captures: list, logs_store) -> dict:
    """Write captures to CloudWatch Logs (group created on first use). Returns {session-id: n}."""
    res: dict = {}
    if not captures or logs_store is None:
        return res
    try:
        from core import logs_core as lc
    except ImportError:                                   # pragma: no cover
        import logs_core as lc                            # type: ignore
    by: dict = {}
    for c in captures:
        by.setdefault((c["sessionId"], c["sourceEni"]), []).append(c)
    for (sid, eni), cs in by.items():
        grp = LOG_GROUP_PREFIX + sid
        if grp not in logs_store.log_groups:
            lc.dispatch(logs_store, "Logs_20140328.CreateLogGroup", {"logGroupName": grp})
        lc.dispatch(logs_store, "Logs_20140328.CreateLogStream", {"logGroupName": grp, "logStreamName": eni})
        r = lc.dispatch(logs_store, "Logs_20140328.PutLogEvents", {"logGroupName": grp, "logStreamName": eni,
                        "logEvents": [{"timestamp": int(c["timestamp"]) * 1000, "message": json.dumps(c, sort_keys=True)} for c in cs]})
        if r.status == 200:
            res[sid] = res.get(sid, 0) + len(cs)
    return res
