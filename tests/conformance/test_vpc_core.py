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
    r = vpc.analyze_reachability(s, src, {"ip": "8.8.8.8"}, 443, "tcp")
    _check("IGW route but no public IPv4 → blocked (an IGW only serves public addresses)",
           not r["reachable"] and r["code"] == "NO_PUBLIC_IP")
    web_i = xid(call({"Action": "RunInstances", "MinCount": "1", "MaxCount": "1", "SubnetId": web_sn,
                      "PrivateIpAddress": "10.0.1.10", "SecurityGroupId.1": web_sg,
                      "NetworkInterface.1.AssociatePublicIpAddress": "true"}), "instanceId")
    _check("instance with a public IPv4 → external reachable via the IGW",
           vpc.analyze_reachability(s, {"instance_id": web_i}, {"ip": "8.8.8.8"}, 443, "tcp")["reachable"])

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


def run_resources(store=None):
    """Full resource-lifecycle CRUD: route tables (+ associations), internet
    gateways, NAT gateways, network ACLs (+ entries), tags, and the simpler
    VPC-adjacent resources (egress-only IGW, DHCP options, managed prefix
    lists, peering connections, route servers)."""
    s = store or types.SimpleNamespace()

    def call(p):
        r = vpc.dispatch(s, p)
        if r.status != 200:
            raise AssertionError((p.get("Action"), r.body))
        return r.body

    def xid(body, tag):
        return re.search(f"<{tag}>(.*?)</{tag}>", body).group(1)

    vpc_id = xid(call({"Action": "CreateVpc", "CidrBlock": "10.9.0.0/16",
                        "TagSpecification.1.ResourceType": "vpc",
                        "TagSpecification.1.Tag.1.Key": "Name", "TagSpecification.1.Tag.1.Value": "crud-vpc"}), "vpcId")
    _check("VPC tag renders in DescribeVpcs", "crud-vpc" in call({"Action": "DescribeVpcs"}))

    subnet_id = xid(call({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.9.1.0/24"}), "subnetId")

    rt_id = xid(call({"Action": "CreateRouteTable", "VpcId": vpc_id}), "routeTableId")
    assoc_id = xid(call({"Action": "AssociateRouteTable", "RouteTableId": rt_id, "SubnetId": subnet_id}), "associationId")
    _check("explicit route table association shows the subnet", subnet_id in call({"Action": "DescribeRouteTables"}))
    call({"Action": "DisassociateRouteTable", "AssociationId": assoc_id})
    _check("disassociate falls back to the main route table",
           s._vpc_model["subnets"][subnet_id]["route_table"] != rt_id)
    try:
        call({"Action": "DeleteRouteTable", "RouteTableId": rt_id})
        deleted_ok = True
    except AssertionError:
        deleted_ok = False
    _check("unassociated non-main route table deletes", deleted_ok)

    igw_id = xid(call({"Action": "CreateInternetGateway"}), "internetGatewayId")
    call({"Action": "AttachInternetGateway", "InternetGatewayId": igw_id, "VpcId": vpc_id})
    _check("DescribeInternetGateways shows the attachment", vpc_id in call({"Action": "DescribeInternetGateways"}))
    call({"Action": "DetachInternetGateway", "InternetGatewayId": igw_id, "VpcId": vpc_id})
    call({"Action": "DeleteInternetGateway", "InternetGatewayId": igw_id})
    _check("IGW gone after delete", igw_id not in s._vpc_model["igws"])

    natgw_id = xid(call({"Action": "CreateNatGateway", "SubnetId": subnet_id}), "natGatewayId")
    _check("NAT gateway gets a public IP", s._vpc_model["nat_gateways"][natgw_id]["public_ip"])
    _check("DescribeNatGateways shows it", natgw_id in call({"Action": "DescribeNatGateways"}))
    call({"Action": "DeleteNatGateway", "NatGatewayId": natgw_id})

    acl_id = xid(call({"Action": "CreateNetworkAcl", "VpcId": vpc_id}), "networkAclId")
    call({"Action": "CreateNetworkAclEntry", "NetworkAclId": acl_id, "RuleNumber": "50",
          "Protocol": "tcp", "RuleAction": "allow", "Egress": "false", "CidrBlock": "10.0.0.0/8",
          "PortRange.From": "22", "PortRange.To": "22"})
    _check("DescribeNetworkAcls shows the custom entry", acl_id in call({"Action": "DescribeNetworkAcls"}))
    call({"Action": "DeleteNetworkAclEntry", "NetworkAclId": acl_id, "RuleNumber": "50", "Egress": "false"})
    _check("entry removed", not s._vpc_model["nacls"][acl_id]["entries"])
    call({"Action": "AssociateNetworkAcl", "NetworkAclId": acl_id, "SubnetId": subnet_id})
    _check("default NACL for a fresh VPC allows all (no entries needed)",
           any(n.get("default") for n in s._vpc_model["nacls"].values()))

    eigw_id = xid(call({"Action": "CreateEgressOnlyInternetGateway", "VpcId": vpc_id}), "egressOnlyInternetGatewayId")
    _check("egress-only IGW round-trips", eigw_id in call({"Action": "DescribeEgressOnlyInternetGateways"}))
    call({"Action": "DeleteEgressOnlyInternetGateway", "EgressOnlyInternetGatewayId": eigw_id})

    dopt_id = xid(call({"Action": "CreateDhcpOptions", "DhcpConfiguration.1.Key": "domain-name",
                        "DhcpConfiguration.1.Value.1": "uic.example.internal"}), "dhcpOptionsId")
    _check("DHCP options round-trip", "uic.example.internal" in call({"Action": "DescribeDhcpOptions"}))
    call({"Action": "AssociateDhcpOptions", "VpcId": vpc_id, "DhcpOptionsId": dopt_id})
    _check("VPC picks up the new DHCP options set", s._vpc_model["vpcs"][vpc_id]["dhcp_options_id"] == dopt_id)

    pl_id = xid(call({"Action": "CreateManagedPrefixList", "PrefixListName": "uic-prefix-list",
                      "MaxEntries": "5", "Entry.1.Cidr": "10.0.0.0/8"}), "prefixListId")
    _check("managed prefix list round-trips", "uic-prefix-list" in call({"Action": "DescribeManagedPrefixLists"}))
    call({"Action": "DeleteManagedPrefixList", "PrefixListId": pl_id})

    peer_vpc_id = xid(call({"Action": "CreateVpc", "CidrBlock": "10.10.0.0/16"}), "vpcId")
    pcx_id = xid(call({"Action": "CreateVpcPeeringConnection", "VpcId": vpc_id, "PeerVpcId": peer_vpc_id}), "vpcPeeringConnectionId")
    call({"Action": "AcceptVpcPeeringConnection", "VpcPeeringConnectionId": pcx_id})
    _check("peering connection becomes active", s._vpc_model["peering_connections"][pcx_id]["status"] == "active")
    call({"Action": "DeleteVpcPeeringConnection", "VpcPeeringConnectionId": pcx_id})

    rs_id = xid(call({"Action": "CreateRouteServer", "AmazonSideAsn": "65001"}), "routeServerId")
    _check("route server round-trips", rs_id in call({"Action": "DescribeRouteServers"}))
    call({"Action": "DeleteRouteServer", "RouteServerId": rs_id})

    fl_resp = call({"Action": "CreateFlowLogs", "ResourceType": "VPC", "ResourceId.1": vpc_id,
                    "TrafficType": "ALL", "LogDestinationType": "cloud-watch-logs", "LogGroupName": "/vpc/flowlogs"})
    fl_id = re.search(r"<flowLogIdSet><item>(.*?)</item>", fl_resp).group(1)
    _check("CreateFlowLogs returns no unsuccessful entries", "<unsuccessful></unsuccessful>" in fl_resp)
    _check("flow log round-trips with its resource and destination", vpc_id in call({"Action": "DescribeFlowLogs"}) and "/vpc/flowlogs" in call({"Action": "DescribeFlowLogs"}))
    bad_fl = call({"Action": "CreateFlowLogs", "ResourceType": "VPC", "ResourceId.1": "vpc-doesnotexist"})
    _check("flow log for an unknown resource is reported unsuccessful", "InvalidParameterValue" in bad_fl and "<flowLogIdSet></flowLogIdSet>" in bad_fl)
    call({"Action": "DeleteFlowLogs", "FlowLogId.1": fl_id})
    _check("flow log gone after delete", fl_id not in call({"Action": "DescribeFlowLogs"}))

    call({"Action": "DeleteSubnet", "SubnetId": subnet_id})
    call({"Action": "DeleteVpc", "VpcId": vpc_id})
    _check("VPC deletes once dependencies are gone", vpc_id not in s._vpc_model["vpcs"])

    print("\nVPC resource-lifecycle conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
    run_resources()
