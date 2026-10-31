"""Upgrade path through the REAL server: build VPC state with the OLD handlers
(VYOMI_VPC_ENGINE=legacy), switch to the one engine (core/vpc_core), and prove nothing is lost:
Describe* returns the same IDs and fields, create/modify keep working on the adopted objects, an
EC2 instance referencing the legacy subnet/SG keeps working, and adoption is idempotent.

    PYTHONPATH=. python3 -m pytest -q tests/netsim/test_legacy_vpc_upgrade.py
"""
from __future__ import annotations

import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

_D = Path(tempfile.mkdtemp(prefix="vyomi-vpc-upgrade-"))
os.environ.setdefault("CLOUDLEARN_STATE_FILE", str(_D / "state.sqlite3"))
os.environ.setdefault("CLOUDLEARN_LEGACY_STATE_FILE", str(_D / "state.pkl"))
os.environ.setdefault("VYOMI_NO_TELEMETRY", "1")
os.environ["CLOUDLEARN_TIER_ENFORCE"] = "0"
os.environ.setdefault("CLOUDLEARN_MINIO_URL", "http://127.0.0.1:1")
os.environ.pop("VYOMI_NETSIM_ENFORCE", None)

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

C = TestClient(server.app)
H = {"Authorization": "AWS4-HMAC-SHA256 Credential=AKIAVYOMIDUMMY/20261030/us-east-1/ec2/aws4_request, "
                      "SignedHeaders=host;x-amz-date, Signature=" + "0" * 64,
     "content-type": "application/x-www-form-urlencoded"}


def ec2(action, **p):
    r = C.post("/", data={"Action": action, "Version": "2016-11-15", **{k: str(v) for k, v in p.items()}}, headers=H)
    assert r.status_code == 200, (action, r.text[:500])
    return r.text


def xid(body, tag):
    return re.search(f"<{tag}>([^<]+)</{tag}>", body).group(1)


def items(body, set_tag):
    root = ET.fromstring(re.sub(r'\sxmlns="[^"]+"', "", body, count=1))
    s = root.find(set_tag)
    return [] if s is None else list(s)


def txt(el, path):
    x = el.find(path)
    return (x.text or "") if x is not None else ""


def tags(el):
    return {txt(t, "key"): txt(t, "value") for t in el.findall("tagSet/item")}


def snapshot():
    """The fields an upgrade must not change, per resource id."""
    out = {}
    for v in items(ec2("DescribeVpcs"), "vpcSet"):
        out[txt(v, "vpcId")] = ("vpc", txt(v, "cidrBlock"), tuple(sorted(tags(v).items())))
    for s in items(ec2("DescribeSubnets"), "subnetSet"):
        out[txt(s, "subnetId")] = ("subnet", txt(s, "vpcId"), txt(s, "cidrBlock"), txt(s, "availabilityZone"),
                                   tuple(sorted(tags(s).items())))
    for g in items(ec2("DescribeSecurityGroups"), "securityGroupInfo"):
        rules = tuple(sorted((txt(p, "ipProtocol"), txt(p, "fromPort"), txt(p, "toPort"),
                              tuple(sorted(txt(r, "cidrIp") for r in p.findall("ipRanges/item"))),
                              tuple(sorted(txt(r, "groupId") for r in p.findall("groups/item"))))
                             for p in g.findall("ipPermissions/item")))
        # the pre-v4 handler emitted <description>; EC2 (and vpc_core) emit <groupDescription>
        out[txt(g, "groupId")] = ("sg", txt(g, "vpcId"), txt(g, "groupName"),
                                  txt(g, "groupDescription") or txt(g, "description"), rules)
    for rt in items(ec2("DescribeRouteTables"), "routeTableSet"):
        routes = tuple(sorted((txt(r, "destinationCidrBlock"), txt(r, "gatewayId") or txt(r, "natGatewayId"))
                              for r in rt.findall("routeSet/item")))
        assoc = tuple(sorted(txt(a, "subnetId") for a in rt.findall("associationSet/item") if txt(a, "subnetId")))
        main = any(txt(a, "main") == "true" for a in rt.findall("associationSet/item"))
        out[txt(rt, "routeTableId")] = ("rtb", txt(rt, "vpcId"), routes, assoc, main)
    for ig in items(ec2("DescribeInternetGateways"), "internetGatewaySet"):
        att = tuple(sorted(txt(a, "vpcId") for a in ig.findall("attachmentSet/item")))
        out[txt(ig, "internetGatewayId")] = ("igw", att, tuple(sorted(tags(ig).items())))
    return out


def test_upgrade_preserves_every_legacy_vpc_object():
    os.environ["VYOMI_VPC_ENGINE"] = "legacy"
    try:
        vpc = xid(ec2("CreateVpc", CidrBlock="10.61.0.0/16", **{"TagSpecification.1.ResourceType": "vpc",
                                                                "TagSpecification.1.Tag.1.Key": "Name",
                                                                "TagSpecification.1.Tag.1.Value": "legacy-prod"}), "vpcId")
        pub = xid(ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.61.1.0/24", AvailabilityZone="us-east-1a"), "subnetId")
        priv = xid(ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.61.2.0/24", AvailabilityZone="us-east-1b",
                       **{"TagSpecification.1.ResourceType": "subnet", "TagSpecification.1.Tag.1.Key": "tier",
                          "TagSpecification.1.Tag.1.Value": "db"}), "subnetId")
        web = xid(ec2("CreateSecurityGroup", VpcId=vpc, GroupName="web", GroupDescription="web tier"), "groupId")
        ec2("AuthorizeSecurityGroupIngress", GroupId=web, **{"IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "22",
                                                             "IpPermissions.1.ToPort": "22", "IpPermissions.1.IpRanges.1.CidrIp": "10.61.0.0/16"})
        igw = xid(ec2("CreateInternetGateway"), "internetGatewayId")
        ec2("AttachInternetGateway", InternetGatewayId=igw, VpcId=vpc)
        rt = xid(ec2("CreateRouteTable", VpcId=vpc), "routeTableId")
        ec2("CreateRoute", RouteTableId=rt, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw)
        ec2("AssociateRouteTable", RouteTableId=rt, SubnetId=pub)
        req = server.EC2InstanceRequest(name="legacy-i", instance_type="t3.micro", ami="ami-amzn2023", runtime="python",
                                        key_pair="", subnet_id=pub, vpc_id=vpc, security_group_ids=[web], az="us-east-1a",
                                        storage_gb=8, command="", user_data="")
        inst = server.api_ec2_create_instance(req, auto_start=False, host_os_hint="linux")
        assert server._Ec2CoreSpaceStore()._vpc_model is None or vpc not in (server._Ec2CoreSpaceStore()._vpc_model or {}).get("vpcs", {})
        before = snapshot()
    finally:
        os.environ.pop("VYOMI_VPC_ENGINE", None)          # upgrade: the one engine is the default

    after = snapshot()
    legacy_ids = {vpc, pub, priv, web, igw, rt}
    assert legacy_ids <= set(before) and legacy_ids <= set(after), (legacy_ids - set(after))
    for rid in before:
        if rid in legacy_ids or before[rid][0] in ("rtb", "sg"):       # main table / default SG ids too
            assert after.get(rid) == before[rid], (rid, before[rid], after.get(rid))
    m = server._Ec2CoreSpaceStore()._vpc_model
    assert m.get("_adopted_legacy") and vpc in m["vpcs"]

    # create / modify keep working on adopted objects (served by vpc_core now)
    acl = xid(ec2("CreateNetworkAcl", VpcId=vpc), "networkAclId")
    sub3 = xid(ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.61.3.0/24"), "subnetId")
    ec2("AssociateNetworkAcl", NetworkAclId=acl, SubnetId=sub3)
    ec2("AuthorizeSecurityGroupIngress", GroupId=web, **{"IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "443",
                                                         "IpPermissions.1.ToPort": "443", "IpPermissions.1.IpRanges.1.CidrIp": "0.0.0.0/0"})
    nat = xid(ec2("CreateNatGateway", SubnetId=pub), "natGatewayId")
    main_rt = next(r for r, v in after.items() if v[0] == "rtb" and v[1] == vpc and v[4])
    ec2("CreateRoute", RouteTableId=main_rt, DestinationCidrBlock="0.0.0.0/0", NatGatewayId=nat)
    assert "<fromPort>443</fromPort>" in ec2("DescribeSecurityGroups", **{"GroupId.1": web})
    assert f"<natGatewayId>{nat}</natGatewayId>" in ec2("DescribeRouteTables", **{"RouteTableId.1": main_rt})

    # the instance launched against the legacy subnet/SG keeps working
    body = ec2("DescribeInstances", **{"InstanceId.1": inst["instance_id"]})
    assert pub in body and web in body
    from core.netsim import wiring
    t = wiring.netsim_topology()
    iface = next(i for i in t.interfaces.values() if i.instance == inst["instance_id"])
    assert iface.subnet == pub and iface.rulesets == [web] and iface.ip.startswith("10.61.1.")
    r = ec2("AnalyzeReachability", **{"Source.Ip": iface.ip, "Source.SecurityGroupId.1": web,
                                      "Destination.Ip": "10.61.2.30", "Destination.SecurityGroupId.1": web, "DestinationPort": "22"})
    assert "<reachable>true</reachable>" in r, r

    # idempotent: more accesses / a forced re-run add nothing
    n_rt, n_sg, n_nacl = len(m["route_tables"]), len(m["sgs"]), len(m["nacls"])
    for _ in range(3):
        server._Ec2CoreSpaceStore()._vpc_model
        snapshot()
    from core import vpc_core
    owner = server._Ec2CoreSpaceStore()._slot_owner()
    legacy = owner.get("vpc") or {k: server.vpc_state.get(k, {}) for k in ("vpcs", "subnets", "security_groups",
                                                                            "route_tables", "internet_gateways")}
    _, counts = vpc_core.adopt_legacy(m, legacy)
    assert sum(counts.values()) == 0
    assert (len(m["route_tables"]), len(m["sgs"]), len(m["nacls"])) == (n_rt, n_sg, n_nacl)
    # a VPC deleted after the upgrade stays deleted (the marker stops re-adoption)
    tmp = xid(ec2("CreateVpc", CidrBlock="10.62.0.0/16"), "vpcId")
    ec2("DeleteVpc", VpcId=tmp)
    server._Ec2CoreSpaceStore()._vpc_model
    assert tmp not in m["vpcs"]
