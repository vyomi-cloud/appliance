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

    # DeleteVpc, as on real EC2: refused while dependencies exist, gone once they are cleared
    v2 = xid(call({"Action": "CreateVpc", "CidrBlock": "10.8.0.0/16"}), "vpcId")
    sn = xid(call({"Action": "CreateSubnet", "VpcId": v2, "CidrBlock": "10.8.1.0/24"}), "subnetId")
    gw = xid(call({"Action": "CreateInternetGateway"}), "internetGatewayId")
    call({"Action": "AttachInternetGateway", "InternetGatewayId": gw, "VpcId": v2})
    _check("DeleteVpc with a subnet + gateway → DependencyViolation", vpc.dispatch(s, {"Action": "DeleteVpc", "VpcId": v2}).status == 400 and "DependencyViolation" in vpc.dispatch(s, {"Action": "DeleteVpc", "VpcId": v2}).body)
    _check("DeleteInternetGateway while attached → DependencyViolation", "DependencyViolation" in vpc.dispatch(s, {"Action": "DeleteInternetGateway", "InternetGatewayId": gw}).body)
    call({"Action": "DeleteSubnet", "SubnetId": sn})
    call({"Action": "DetachInternetGateway", "InternetGatewayId": gw, "VpcId": v2})
    call({"Action": "DeleteInternetGateway", "InternetGatewayId": gw})
    call({"Action": "DeleteVpc", "VpcId": v2})
    m = s._vpc_model
    _check("DeleteVpc removes the VPC and its main route table", v2 not in m["vpcs"] and not any(r["vpc_id"] == v2 for r in m["route_tables"].values()))
    _check("DeleteVpc on an unknown id → InvalidVpcID.NotFound", "InvalidVpcID.NotFound" in vpc.dispatch(s, {"Action": "DeleteVpc", "VpcId": v2}).body)
    v3 = xid(call({"Action": "CreateVpc", "CidrBlock": "10.7.0.0/16"}), "vpcId")
    call({"Action": "CreateSubnet", "VpcId": v3, "CidrBlock": "10.7.1.0/24"})
    _check("console cascade removes the VPC and its subnets", vpc.delete_vpc_cascade(s, v3) and v3 not in m["vpcs"] and not any(x["vpc_id"] == v3 for x in m["subnets"].values()))

    # DescribeSecurityGroups: what was given at creation, and the default group every VPC has
    v4 = xid(call({"Action": "CreateVpc", "CidrBlock": "10.6.0.0/16"}), "vpcId")
    g4 = xid(call({"Action": "CreateSecurityGroup", "VpcId": v4, "GroupName": "web", "GroupDescription": "web <tier>"}), "groupId")
    body = call({"Action": "DescribeSecurityGroups", "GroupId.1": g4})
    _check("DescribeSecurityGroups returns the Description + name", "<groupDescription>web &lt;tier&gt;</groupDescription>" in body and "<groupName>web</groupName>" in body)
    body = call({"Action": "DescribeSecurityGroups", "Filter.1.Name": "vpc-id", "Filter.1.Value.1": v4, "Filter.2.Name": "group-name", "Filter.2.Value.1": "default"})
    _check("every VPC has a default group", "<groupDescription>default VPC security group</groupDescription>" in body)
    _check("unknown group → InvalidGroup.NotFound", "InvalidGroup.NotFound" in vpc.dispatch(s, {"Action": "DescribeSecurityGroups", "GroupId.1": "sg-nope"}).body)

    print("\nVPC network-simulation conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
