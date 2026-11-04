"""Flow-log delivery (no Docker): synthetic nft counters -> AWS CloudWatch Logs + S3 and Azure NSG blob.
Run: PYTHONPATH=. python3 tests/netsim/test_flow_delivery.py"""
import gzip
import json
import re
from urllib.parse import quote

from core import logs_core as lc
from core import object_store as obs
from core import s3_object_core as s3
from core.aws_wire_router import AwsWireRouter
from core.netsim import from_aws, wiring


import time
NOW = int(time.time())


def main():
    r = AwsWireRouter()
    A = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0"

    def ec2(action, **p):
        form = "&".join(f"{k}={quote(str(v))}" for k, v in {"Action": action, **p}.items())
        return r.handle("POST", "/", {}, {"authorization": A, "content-type": "application/x-www-form-urlencoded"}, form.encode())["body"].decode()
    x = lambda tag, s: re.search(rf"<{tag}>([\w-]+)</{tag}>", s).group(1)
    vpc = x("vpcId", ec2("CreateVpc", CidrBlock="10.50.0.0/16"))
    sub = x("subnetId", ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.50.1.0/24", AvailabilityZone="us-east-1a"))
    sg = x("groupId", ec2("CreateSecurityGroup", GroupName="g", GroupDescription="d", VpcId=vpc))
    ia = x("instanceId", ec2("RunInstances", MinCount=1, MaxCount=1, SubnetId=sub, **{"SecurityGroupId.1": sg}))
    ib = x("instanceId", ec2("RunInstances", MinCount=1, MaxCount=1, SubnetId=sub, **{"SecurityGroupId.1": sg}))
    st = r.vpc
    m = wiring_model = st._vpc_model if hasattr(st, "_vpc_model") else None
    from core import vpc_core
    m = vpc_core._model(st)
    ipa, ipb = m["instances"][ia]["private_ip"], m["instances"][ib]["private_ip"]

    logs = lc.LogsStore()
    lc.dispatch(logs, "Logs_20140328.CreateLogGroup", {"logGroupName": "/vpc/flow"})
    s3store = obs.InMemoryObjectStore()
    s3store.create_bucket("flowbkt")
    ec2("CreateFlowLogs", **{"ResourceId.1": vpc, "ResourceType": "VPC", "TrafficType": "ALL", "LogDestinationType": "cloud-watch-logs", "LogGroupName": "/vpc/flow"})
    ec2("CreateFlowLogs", **{"ResourceId.1": sub, "ResourceType": "Subnet", "TrafficType": "REJECT", "LogDestinationType": "s3", "LogDestination": "arn:aws:s3:::flowbkt/pre",
                              "LogFormat": "${srcaddr} ${dstaddr} ${dstport} ${action}"})
    topo = from_aws.from_aws(m)
    from core.netsim.model import Interface
    for iid, ip in ((ia, ipa), (ib, ipb)):
        topo.add(Interface(id=from_aws.primary_eni(iid), instance=iid, subnet=sub, ip=ip))
    acc = [{"src": ipa, "dst": ipb, "proto": 6, "sport": 40000, "dport": 80, "packets": 5, "bytes": 400}]
    rej = [{"src": ipa, "dst": ipb, "proto": 6, "sport": 40001, "dport": 22, "packets": 2, "bytes": 120}]
    out = wiring.deliver_flows(acc, rej, topo, aws_model=m, logs_store=logs, s3_store=s3store, now=NOW)
    assert len(out["aws"]) == 2, out
    streams = logs.log_groups["/vpc/flow"]["streams"]
    msgs = [e["message"] for s_ in streams.values() for e in s_["events"]]
    assert any(f"{ipa} {ipb} 40000 80 6 5 400" in mm and "ACCEPT OK" in mm for mm in msgs), msgs
    assert any("REJECT OK" in mm for mm in msgs) and len(msgs) == 4      # 2 flows x 2 ENIs
    print("  ok  VPC flow log -> CloudWatch Logs (ACCEPT + REJECT, one record per ENI)")
    keys = [k for k in s3store.bucket_objects("flowbkt")]
    assert len(keys) == 1 and keys[0].startswith("pre/AWSLogs/") and keys[0].endswith(".log.gz"), keys
    ent = s3store.bucket_objects("flowbkt")[keys[0]]; raw = ent["data"] if isinstance(ent, dict) else ent.data
    body = gzip.decompress(raw).decode().splitlines()
    assert body[0] == "srcaddr dstaddr dstport action" and all(l.endswith("REJECT") for l in body[1:]) and len(body) == 3, body
    print("  ok  subnet REJECT-only flow log -> S3 gz with custom format")
    cfg = [c for c in m["flow_logs"].values() if c["log_destination_type"] == "cloud-watch-logs"][0]
    assert cfg["deliver_logs_status"] == "SUCCESS"
    lc.dispatch(logs, "Logs_20140328.DeleteLogGroup", {"logGroupName": "/vpc/flow"})
    wiring.deliver_flows(acc, rej, topo, aws_model=m, logs_store=logs, s3_store=s3store, now=NOW + 60)
    assert cfg["deliver_logs_status"] == "FAILED"
    print("  ok  missing log group -> deliverLogsStatus FAILED")
    print("flow delivery: all checks passed")


if __name__ == "__main__":
    main()
