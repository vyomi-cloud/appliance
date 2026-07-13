"""VPC network-simulation conformance (v2.8.0, PARITY P4 #15) — host + Pyodide.

Builds a VPC topology (subnets, security groups, route table, internet gateway,
network ACL) and exercises the reachability analyzer across the allow path and each
blocking layer: destination-SG ingress, wrong port, no route, and a stateless NACL
deny. Proves the analyzer evaluates real network semantics, not a catalog stub.
"""
import re
import types

try:
    from core import vpc_core as vpc
except ImportError:  # pragma: no cover - Pyodide flat layout
    import vpc_core as vpc  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or types.SimpleNamespace()

    def call(p):
        r = vpc.dispatch(s, p)
        if r.status != 200:
            raise AssertionError((p.get("Action"), r.body))
        return r.body

    def xid(body, tag):
        return re.search(f"<{tag}>(.*?)</{tag}>", body).group(1)

    vpc_id = xid(call({"Action": "CreateVpc", "CidrBlock": "10.0.0.0/16"}), "vpcId")
    web_sn = xid(call({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.0.1.0/24"}), "subnetId")
    call({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.0.2.0/24"})
    web_sg = xid(call({"Action": "CreateSecurityGroup", "VpcId": vpc_id, "GroupName": "web"}), "groupId")
    db_sg = xid(call({"Action": "CreateSecurityGroup", "VpcId": vpc_id, "GroupName": "db"}), "groupId")

    src = {"ip": "10.0.1.10", "security_group_ids": [web_sg]}
    dst = {"ip": "10.0.2.20", "security_group_ids": [db_sg]}

    r = vpc.analyze_reachability(s, src, dst, 5432, "tcp")
    _check("default: web→db:5432 blocked (dest SG ingress deny)",
           not r["reachable"] and "ingress" in r["reason"])

    call({"Action": "AuthorizeSecurityGroupIngress", "GroupId": db_sg,
          "IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "5432",
          "IpPermissions.1.ToPort": "5432", "IpPermissions.1.Groups.1.GroupId": web_sg})
    r = vpc.analyze_reachability(s, src, dst, 5432, "tcp")
    _check("after authorize 5432 from web SG → reachable", r["reachable"])

    _check("wrong port 3306 still blocked",
           not vpc.analyze_reachability(s, src, dst, 3306, "tcp")["reachable"])

    r = vpc.analyze_reachability(s, src, {"ip": "8.8.8.8"}, 443, "tcp")
    _check("no route to external IP → blocked", not r["reachable"] and "route" in r["reason"])

    igw = xid(call({"Action": "CreateInternetGateway"}), "internetGatewayId")
    call({"Action": "AttachInternetGateway", "InternetGatewayId": igw, "VpcId": vpc_id})
    rt_id = s._vpc_model["subnets"][web_sn]["route_table"]
    call({"Action": "CreateRoute", "RouteTableId": rt_id,
          "DestinationCidrBlock": "0.0.0.0/0", "GatewayId": igw})
    _check("after IGW + 0.0.0.0/0 route → external reachable",
           vpc.analyze_reachability(s, src, {"ip": "8.8.8.8"}, 443, "tcp")["reachable"])

    # NACL deny layer: attach a NACL to the web subnet that denies egress on 5432
    acl = xid(call({"Action": "CreateNetworkAcl", "VpcId": vpc_id}), "networkAclId")
    call({"Action": "CreateNetworkAclEntry", "NetworkAclId": acl, "RuleNumber": "100",
          "Protocol": "tcp", "RuleAction": "deny", "Egress": "true",
          "CidrBlock": "0.0.0.0/0", "PortRange.From": "5432", "PortRange.To": "5432"})
    call({"Action": "CreateNetworkAclEntry", "NetworkAclId": acl, "RuleNumber": "200",
          "Protocol": "-1", "RuleAction": "allow", "Egress": "true"})
    call({"Action": "AssociateNetworkAcl", "NetworkAclId": acl, "SubnetId": web_sn})
    r = vpc.analyze_reachability(s, src, dst, 5432, "tcp")
    _check("NACL egress deny on 5432 → blocked (stateless layer)",
           not r["reachable"] and "NACL" in r["reason"])

    body = call({"Action": "AnalyzeReachability", "Source.Ip": "10.0.1.10",
                 "Destination.Ip": "10.0.2.20", "Destination.SecurityGroupId.1": db_sg,
                 "DestinationPort": "5432", "Protocol": "tcp"})
    _check("AnalyzeReachability over EC2 Query wire → <reachable> emitted", "<reachable>" in body)

    print("\nVPC network-simulation conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
