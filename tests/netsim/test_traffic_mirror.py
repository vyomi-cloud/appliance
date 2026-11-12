"""AWS Traffic Mirroring on netsim (no Docker): sessions + filters from the real EC2 API claim flows from per-window nft counter
deltas; captures land in CloudWatch Logs. Also: the persistent collector reports each flow ONCE (deltas), never re-emitting
cumulative counters. Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/netsim/test_traffic_mirror.py"""
import json
import re
import time
from urllib.parse import quote

from core import logs_core as lc
from core import vpc_core
from core.aws_wire_router import AwsWireRouter
from core.netsim import from_aws, wiring
from core.netsim.flowlogs import FlowLogCollector

NOW = int(time.time())


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def main():
    r = AwsWireRouter()
    A = "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0"

    def ec2(action, **p):
        form = "&".join(f"{k}={quote(str(v))}" for k, v in {"Action": action, **p}.items())
        o = r.handle("POST", "/", {}, {"authorization": A, "content-type": "application/x-www-form-urlencoded"}, form.encode())
        return o["status"], o["body"].decode()
    x = lambda tag, s: re.search(rf"<{tag}>([\w.-]+)</{tag}>", s).group(1)
    vpc = x("vpcId", ec2("CreateVpc", CidrBlock="10.60.0.0/16")[1])
    sub = x("subnetId", ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.60.1.0/24", AvailabilityZone="us-east-1a")[1])
    src = ec2("CreateNetworkInterface", SubnetId=sub)[1]
    tgt = ec2("CreateNetworkInterface", SubnetId=sub)[1]
    oth = ec2("CreateNetworkInterface", SubnetId=sub)[1]
    e_src, e_tgt, e_oth = (x("networkInterfaceId", s) for s in (src, tgt, oth))
    ip_src, ip_oth = x("privateIpAddress", src), x("privateIpAddress", oth)
    t = x("trafficMirrorTargetId", ec2("CreateTrafficMirrorTarget", NetworkInterfaceId=e_tgt)[1])
    f = x("trafficMirrorFilterId", ec2("CreateTrafficMirrorFilter")[1])
    ec2("CreateTrafficMirrorFilterRule", TrafficMirrorFilterId=f, TrafficDirection="egress", RuleNumber=10, RuleAction="accept", Protocol=6,
        **{"DestinationPortRange.FromPort": 80, "DestinationPortRange.ToPort": 80}, DestinationCidrBlock="0.0.0.0/0", SourceCidrBlock="0.0.0.0/0")
    ec2("CreateTrafficMirrorFilterRule", TrafficMirrorFilterId=f, TrafficDirection="ingress", RuleNumber=10, RuleAction="reject", Protocol=6,
        DestinationCidrBlock="0.0.0.0/0", SourceCidrBlock="0.0.0.0/0")
    s1 = x("trafficMirrorSessionId", ec2("CreateTrafficMirrorSession", NetworkInterfaceId=e_src, TrafficMirrorTargetId=t, TrafficMirrorFilterId=f, SessionNumber=1, PacketLength=100)[1])
    m = vpc_core._model(r.vpc)
    topo = from_aws.from_aws(m)
    _check("explicit ENIs are in the topology", topo.iface_by_ip(ip_src) is not None and topo.iface_by_ip(ip_src).id == e_src)
    logs = lc.LogsStore()
    # window 1: one TCP/80 flow (mirrored, egress at the source ENI), one TCP/22 flow (no accept rule -> not mirrored), one reverse (ingress rejected)
    acc = [{"src": ip_src, "dst": ip_oth, "proto": 6, "sport": 40000, "dport": 80, "packets": 10, "bytes": 5000},
           {"src": ip_src, "dst": ip_oth, "proto": 6, "sport": 40001, "dport": 22, "packets": 3, "bytes": 300},
           {"src": ip_oth, "dst": ip_src, "proto": 6, "sport": 5000, "dport": 6000, "packets": 4, "bytes": 400}]
    col = FlowLogCollector(topo)
    col.keep_history = False
    out = wiring.deliver_flows(acc, [], topo, aws_model=m, logs_store=logs, collector=col, now=NOW)
    _check("one session captured", list(out["mirror"]) == [s1] and out["mirror"][s1] == 1)
    msgs = [json.loads(e["message"]) for s_ in logs.log_groups["/vyomi/traffic-mirror/" + s1]["streams"].values() for e in s_["events"]]
    c = msgs[0]
    _check("capture shape", c["dstport"] == 80 and c["direction"] == "egress" and c["sourceEni"] == e_src and c["targetId"] == t and c["packets"] == 10)
    _check("PacketLength truncates bytes", c["bytes"] == 1000)
    # window 2: counters grew by 5 packets -> only the DELTA is captured
    acc2 = [dict(acc[0], packets=15, bytes=7500)] + acc[1:]
    out = wiring.deliver_flows(acc2, [], topo, aws_model=m, logs_store=logs, collector=col, now=NOW + 60)
    msgs = [json.loads(e["message"]) for s_ in logs.log_groups["/vyomi/traffic-mirror/" + s1]["streams"].values() for e in s_["events"]]
    _check("second window reports the delta only", len(msgs) == 2 and msgs[1]["packets"] == 5)
    out = wiring.deliver_flows(acc2, [], topo, aws_model=m, logs_store=logs, collector=col, now=NOW + 120)
    _check("unchanged counters capture nothing", out["mirror"] == {})
    # session ordering: a lower-numbered session claiming the packet wins
    t2 = x("trafficMirrorTargetId", ec2("CreateTrafficMirrorTarget", NetworkInterfaceId=e_oth)[1])
    s0 = x("trafficMirrorSessionId", ec2("CreateTrafficMirrorSession", NetworkInterfaceId=e_src, TrafficMirrorTargetId=t2, TrafficMirrorFilterId=f, SessionNumber=0 + 2)[1])
    caps = __import__("core.netsim.mirror", fromlist=["x"]).mirror_captures(m, topo, [dict(acc[0], action="ACCEPT")], NOW)
    _check("lowest session number claims the packet", len(caps) == 1 and caps[0]["sessionId"] == s1)
    # GCP-style persistent collector: windows hold only the latest delta when keep_history is False
    col2 = FlowLogCollector(topo)
    col2.keep_history = False
    col2.ingest(acc, [], now=NOW)
    col2.ingest(acc2, [], now=NOW + 60)
    _check("persistent collector keeps one window", len(col2.windows) == 1 and sum(r_["packets"] for _, _, rows in col2.windows for r_ in rows) == 5)
    print("MIRROR OK")


if __name__ == "__main__":
    main()
