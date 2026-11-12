"""Build realistic AWS topologies THROUGH the real vpc_core EC2 Query API (dispatch), so the
translator is tested against the state the console / boto3 actually produce."""
from __future__ import annotations

import re

from core import vpc_core


class Store:
    pass


class Aws:
    def __init__(self):
        self.store = Store()

    @property
    def m(self) -> dict:
        return vpc_core._model(self.store)

    def call(self, action: str, **params) -> str:
        r = vpc_core.dispatch(self.store, {"Action": action, **{k: str(v) for k, v in params.items()}})
        assert r.status == 200, f"{action} {params}: {r.body}"
        return r.body

    @staticmethod
    def _id(body: str, tag: str) -> str:
        return re.search(rf"<{tag}>([^<]+)</{tag}>", body).group(1)

    def vpc(self, cidr):
        return self._id(self.call("CreateVpc", CidrBlock=cidr), "vpcId")

    def subnet(self, vpc, cidr, az="us-east-1a"):
        return self._id(self.call("CreateSubnet", VpcId=vpc, CidrBlock=cidr, AvailabilityZone=az), "subnetId")

    def igw(self, vpc):
        g = self._id(self.call("CreateInternetGateway"), "internetGatewayId")
        self.call("AttachInternetGateway", InternetGatewayId=g, VpcId=vpc)
        return g

    def rtb(self, vpc, subnet=None):
        r = self._id(self.call("CreateRouteTable", VpcId=vpc), "routeTableId")
        if subnet:
            self.call("AssociateRouteTable", RouteTableId=r, SubnetId=subnet)
        return r

    def route(self, rtb, dest, **target):
        self.call("CreateRoute", RouteTableId=rtb, DestinationCidrBlock=dest, **target)

    def sg(self, vpc, name):
        return self._id(self.call("CreateSecurityGroup", VpcId=vpc, GroupName=name, GroupDescription=name), "groupId")

    def allow_in(self, sg, proto, lo, hi, cidr=None, src_sg=None):
        p = {"GroupId": sg, "IpPermissions.1.IpProtocol": proto}
        if lo is not None:
            p["IpPermissions.1.FromPort"], p["IpPermissions.1.ToPort"] = lo, hi
        if cidr:
            p["IpPermissions.1.IpRanges.1.CidrIp"] = cidr
        if src_sg:
            p["IpPermissions.1.Groups.1.GroupId"] = src_sg
        self.call("AuthorizeSecurityGroupIngress", **p)

    def nacl(self, vpc, subnet):
        n = self._id(self.call("CreateNetworkAcl", VpcId=vpc), "networkAclId")
        self.call("AssociateNetworkAcl", NetworkAclId=n, SubnetId=subnet)
        return n

    def nacl_entry(self, nacl, num, egress, action, proto="-1", cidr="0.0.0.0/0", lo=None, hi=None):
        p = {"NetworkAclId": nacl, "RuleNumber": num, "Egress": str(egress).lower(), "RuleAction": action,
             "Protocol": proto, "CidrBlock": cidr}
        if lo is not None:
            p["PortRange.From"], p["PortRange.To"] = lo, hi if hi is not None else lo
        self.call("CreateNetworkAclEntry", **p)

    def instance(self, subnet, sgs, ip):
        p = {"SubnetId": subnet, "MinCount": 1, "MaxCount": 1, "InstanceType": "t3.micro", "PrivateIpAddress": ip}
        for i, g in enumerate(sgs, 1):
            p[f"SecurityGroupId.{i}"] = g
        return self._id(self.call("RunInstances", **p), "instanceId")

    def eip(self, iid):
        alloc = self._id(self.call("AllocateAddress", Domain="vpc"), "allocationId")
        self.call("AssociateAddress", AllocationId=alloc, InstanceId=iid)
        return self.m["instances"][iid]["public_ip"]

    def nat(self, subnet):
        return self._id(self.call("CreateNatGateway", SubnetId=subnet), "natGatewayId")

    def pcx(self, a, b):
        p = self._id(self.call("CreateVpcPeeringConnection", VpcId=a, PeerVpcId=b), "vpcPeeringConnectionId")
        self.call("AcceptVpcPeeringConnection", VpcPeeringConnectionId=p)
        return p


def classic_two_tier(vpc_cidr="10.213.0.0/16", pub_cidr="10.213.1.0/24", priv_cidr="10.213.2.0/24"):
    """Public subnet (own route table 0/0 → igw) + private subnet (main route table: local only).
    web SG: ingress tcp/22 from the VPC; app SG: ingress tcp/22 from the VPC.
    a, c in public; b in private."""
    a = Aws()
    ctx = {"aws": a}
    ctx["vpc"] = vpc = a.vpc(vpc_cidr)
    ctx["pub"] = pub = a.subnet(vpc, pub_cidr)
    ctx["priv"] = priv = a.subnet(vpc, priv_cidr, "us-east-1b")
    ctx["igw"] = a.igw(vpc)
    ctx["pub_rt"] = a.rtb(vpc, pub)
    a.route(ctx["pub_rt"], "0.0.0.0/0", GatewayId=ctx["igw"])
    ctx["main_rt"] = a.m["subnets"][priv]["route_table"]
    ctx["web"] = a.sg(vpc, "web")
    a.allow_in(ctx["web"], "tcp", 22, 22, cidr=vpc_cidr)
    ctx["app"] = a.sg(vpc, "app")
    a.allow_in(ctx["app"], "tcp", 22, 22, cidr=vpc_cidr)
    ctx["a"] = a.instance(pub, [ctx["web"]], pub_cidr.rsplit(".", 1)[0] + ".10")
    ctx["c"] = a.instance(pub, [ctx["web"]], pub_cidr.rsplit(".", 1)[0] + ".11")
    ctx["b"] = a.instance(priv, [ctx["app"]], priv_cidr.rsplit(".", 1)[0] + ".10")
    return ctx
