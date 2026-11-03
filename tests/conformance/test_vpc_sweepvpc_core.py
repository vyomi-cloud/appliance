"""VPC sweep (VPN / route propagation / ...) — real behaviour, host + Nano share core code.
Run: PYTHONPATH=. python3 tests/conformance/test_vpc_sweepvpc_core.py"""
import re
import types

from core import vpc_core as vpc


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


class Env:
    def __init__(self):
        self.s = types.SimpleNamespace()

    def call(self, p, ok=True):
        r = vpc.dispatch(self.s, p)
        if ok and r.status != 200:
            raise AssertionError((p.get("Action"), r.body))
        if not ok and r.status == 200:
            raise AssertionError(("expected failure", p.get("Action"), r.body))
        return r.body

    def id(self, body, tag):
        return re.search(f"<{tag}>(.*?)</{tag}>", body).group(1)


def vpn():
    e = Env(); c = e.call
    vpc_id = e.id(c({"Action": "CreateVpc", "CidrBlock": "10.70.0.0/16"}), "vpcId")
    sub = e.id(c({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.70.1.0/24"}), "subnetId")
    rtb = e.id(c({"Action": "CreateRouteTable", "VpcId": vpc_id}), "routeTableId")
    c({"Action": "AssociateRouteTable", "RouteTableId": rtb, "SubnetId": sub})
    cgw = e.id(c({"Action": "CreateCustomerGateway", "IpAddress": "203.0.113.12", "BgpAsn": "65000", "Type": "ipsec.1"}), "customerGatewayId")
    c({"Action": "CreateCustomerGateway", "IpAddress": "nope"}, ok=False)
    _check("customer gateway listed", cgw in c({"Action": "DescribeCustomerGateways"}))
    _check("bad Amazon ASN rejected", "InvalidParameterValue" in c({"Action": "CreateVpnGateway", "AmazonSideAsn": "100"}, ok=False))
    vgw = e.id(c({"Action": "CreateVpnGateway", "Type": "ipsec.1"}), "vpnGatewayId")
    c({"Action": "AttachVpnGateway", "VpnGatewayId": vgw, "VpcId": vpc_id})
    _check("VGW attachment shown", f"<vpcId>{vpc_id}</vpcId><state>attached</state>" in c({"Action": "DescribeVpnGateways", "VpnGatewayId.1": vgw}))
    _check("VPC with attached VGW cannot be deleted", "DependencyViolation" in c({"Action": "DeleteVpc", "VpcId": vpc_id}, ok=False))
    _check("both VGW and TGW rejected", "InvalidParameterCombination" in c({"Action": "CreateVpnConnection", "CustomerGatewayId": cgw, "VpnGatewayId": vgw, "TransitGatewayId": "tgw-1"}, ok=False))
    body = c({"Action": "CreateVpnConnection", "CustomerGatewayId": cgw, "VpnGatewayId": vgw, "Type": "ipsec.1",
              "Options.StaticRoutesOnly": "true", "Options.TunnelOptions.1.PreSharedKey": "my-secret.key1".replace("-", "_"),
              "Options.TunnelOptions.1.Phase1LifetimeSeconds": "14400"})
    vid = e.id(body, "vpnConnectionId")
    _check("two tunnels with the supplied PSK / lifetime", body.count("<outsideIpAddress>") >= 2 and "my_secret.key1" in body and "<phase1LifetimeSeconds>14400</phase1LifetimeSeconds>" in body)
    _check("tunnel status honest (DOWN, no IPsec peer)", "<status>DOWN</status>" in body)
    c({"Action": "CreateVpnConnection", "CustomerGatewayId": cgw, "VpnGatewayId": vgw, "Options.TunnelOptions.1.Phase1LifetimeSeconds": "10"}, ok=False)
    _check("CGW in use cannot be deleted", "IncorrectState" in c({"Action": "DeleteCustomerGateway", "CustomerGatewayId": cgw}, ok=False))
    c({"Action": "CreateVpnConnectionRoute", "VpnConnectionId": vid, "DestinationCidrBlock": "192.168.50.0/24"})
    c({"Action": "CreateVpnConnectionRoute", "VpnConnectionId": vid, "DestinationCidrBlock": "192.168.50.0/24"}, ok=False)
    c({"Action": "CreateVpnConnectionRoute", "VpnConnectionId": vid, "DestinationCidrBlock": "bad"}, ok=False)
    # propagation
    _check("no propagated route before enabling", "EnableVgwRoutePropagation" not in c({"Action": "DescribeRouteTables", "RouteTableId.1": rtb}))
    c({"Action": "EnableVgwRoutePropagation", "GatewayId": vgw, "RouteTableId": rtb})
    rt = c({"Action": "DescribeRouteTables", "RouteTableId.1": rtb})
    _check("propagated route in Routes tab (origin EnableVgwRoutePropagation)", "192.168.50.0/24" in rt and f"<gatewayId>{vgw}</gatewayId><state>active</state><origin>EnableVgwRoutePropagation</origin>" in rt)
    _check("propagatingVgwSet lists the VGW", f"<propagatingVgwSet><item><gatewayId>{vgw}</gatewayId>" in rt)
    c({"Action": "EnableVgwRoutePropagation", "GatewayId": vgw, "RouteTableId": rtb}, ok=False)
    c({"Action": "CreateVpnConnectionRoute", "VpnConnectionId": vid, "DestinationCidrBlock": "172.20.0.0/16"})
    _check("later VPN route follows into the table", "172.20.0.0/16" in c({"Action": "DescribeRouteTables", "RouteTableId.1": rtb}))
    # netsim honours it
    i = e.id(c({"Action": "RunInstances", "MinCount": "1", "MaxCount": "1", "SubnetId": sub}), "instanceId")
    nip = e.id(c({"Action": "CreateNetworkInsightsPath", "Source": i, "DestinationIp": "192.168.50.9", "Protocol": "tcp", "DestinationPort": "443"}), "networkInsightsPathId")
    an = c({"Action": "StartNetworkInsightsAnalysis", "NetworkInsightsPathId": nip})
    _check("netsim: traffic to propagated prefix reaches the VPN (path found)", "<networkPathFound>true</networkPathFound>" in an)
    nip2 = e.id(c({"Action": "CreateNetworkInsightsPath", "Source": i, "DestinationIp": "192.168.99.9", "Protocol": "tcp", "DestinationPort": "443"}), "networkInsightsPathId")
    _check("netsim: no route to non-propagated prefix", "<networkPathFound>false</networkPathFound>" in c({"Action": "StartNetworkInsightsAnalysis", "NetworkInsightsPathId": nip2}))
    c({"Action": "DisableVgwRoutePropagation", "GatewayId": vgw, "RouteTableId": rtb})
    _check("disable removes propagated routes", "192.168.50.0/24" not in c({"Action": "DescribeRouteTables", "RouteTableId.1": rtb}))
    c({"Action": "DeleteVpnConnectionRoute", "VpnConnectionId": vid, "DestinationCidrBlock": "172.20.0.0/16"})
    c({"Action": "ModifyVpnTunnelOptions", "VpnConnectionId": vid, "VpnTunnelOutsideIpAddress": e.id(body, "outsideIpAddress"), "TunnelOptions.DPDTimeoutSeconds": "60"})
    c({"Action": "ModifyVpnTunnelOptions", "VpnConnectionId": vid, "VpnTunnelOutsideIpAddress": "1.1.1.1", "TunnelOptions.DPDTimeoutSeconds": "60"}, ok=False)
    c({"Action": "DeleteVpnGateway", "VpnGatewayId": vgw}, ok=False)
    c({"Action": "DeleteVpnConnection", "VpnConnectionId": vid})
    _check("deleted VPN gone", vid not in c({"Action": "DescribeVpnConnections"}))
    c({"Action": "DetachVpnGateway", "VpnGatewayId": vgw, "VpcId": vpc_id})
    c({"Action": "DeleteVpnGateway", "VpnGatewayId": vgw})
    c({"Action": "DeleteCustomerGateway", "CustomerGatewayId": cgw})


def client_vpn():
    e = Env(); c = e.call
    vpc_id = e.id(c({"Action": "CreateVpc", "CidrBlock": "10.71.0.0/16"}), "vpcId")
    s1 = e.id(c({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.71.1.0/24", "AvailabilityZone": "us-east-1a"}), "subnetId")
    s2 = e.id(c({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.71.2.0/24", "AvailabilityZone": "us-east-1a"}), "subnetId")
    s3 = e.id(c({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.71.3.0/24", "AvailabilityZone": "us-east-1b"}), "subnetId")
    base = {"Action": "CreateClientVpnEndpoint", "ClientCidrBlock": "10.99.0.0/16", "ServerCertificateArn": "arn:aws:acm:us-east-1:123456789012:certificate/x",
            "Authentication.1.Type": "certificate-authentication", "Authentication.1.MutualAuthentication.ClientRootCertificateChainArn": "arn:aws:acm:us-east-1:123456789012:certificate/c"}
    c({**base, "ClientCidrBlock": "10.99.0.0/28"}, ok=False)
    c({k: v for k, v in base.items() if not k.startswith("Authentication")}, ok=False)
    eid = e.id(c(base), "clientVpnEndpointId")
    _check("new endpoint is pending-associate", "<code>pending-associate</code>" in c({"Action": "DescribeClientVpnEndpoints", "ClientVpnEndpointId.1": eid}))
    c({"Action": "AssociateClientVpnTargetNetwork", "ClientVpnEndpointId": eid, "SubnetId": s1})
    _check("association makes the endpoint available", "<code>available</code>" in c({"Action": "DescribeClientVpnEndpoints", "ClientVpnEndpointId.1": eid}))
    _check("second subnet in the same AZ rejected", "Duplicate" in c({"Action": "AssociateClientVpnTargetNetwork", "ClientVpnEndpointId": eid, "SubnetId": s2}, ok=False))
    c({"Action": "AssociateClientVpnTargetNetwork", "ClientVpnEndpointId": eid, "SubnetId": s3})
    _check("VPC-CIDR route auto-created", "<destinationCidr>10.71.0.0/16</destinationCidr>" in c({"Action": "DescribeClientVpnRoutes", "ClientVpnEndpointId": eid}))
    c({"Action": "AuthorizeClientVpnIngress", "ClientVpnEndpointId": eid, "TargetNetworkCidr": "10.71.0.0/16", "AuthorizeAllGroups": "true"})
    c({"Action": "AuthorizeClientVpnIngress", "ClientVpnEndpointId": eid, "TargetNetworkCidr": "10.71.0.0/16", "AuthorizeAllGroups": "true"}, ok=False)
    c({"Action": "AuthorizeClientVpnIngress", "ClientVpnEndpointId": eid, "TargetNetworkCidr": "10.0.0.0/8"}, ok=False)
    _check("rule listed", "<accessAll>true</accessAll>" in c({"Action": "DescribeClientVpnAuthorizationRules", "ClientVpnEndpointId": eid}))
    c({"Action": "CreateClientVpnRoute", "ClientVpnEndpointId": eid, "DestinationCidrBlock": "0.0.0.0/0", "TargetVpcSubnetId": s1})
    c({"Action": "CreateClientVpnRoute", "ClientVpnEndpointId": eid, "DestinationCidrBlock": "1.0.0.0/8", "TargetVpcSubnetId": "subnet-nope"}, ok=False)
    c({"Action": "DeleteClientVpnEndpoint", "ClientVpnEndpointId": eid}, ok=False)
    _check("connections list honest (empty)", "<connections></connections>" in c({"Action": "DescribeClientVpnConnections", "ClientVpnEndpointId": eid}))
    for a in __import__("re").findall(r"<associationId>(.*?)</associationId>", c({"Action": "DescribeClientVpnTargetNetworks", "ClientVpnEndpointId": eid})):
        c({"Action": "DisassociateClientVpnTargetNetwork", "ClientVpnEndpointId": eid, "AssociationId": a})
    c({"Action": "DeleteClientVpnEndpoint", "ClientVpnEndpointId": eid})
    tg = e.id(c({"Action": "CreateTransitGateway"}), "transitGatewayId")
    vc = e.id(c({"Action": "CreateVpnConcentrator", "TransitGatewayId": tg, "Type": "ipsec.1"}), "vpnConcentratorId")
    c({"Action": "CreateVpnConcentrator", "TransitGatewayId": "tgw-nope"}, ok=False)
    _check("concentrator listed + deleted", vc in c({"Action": "DescribeVpnConcentrators"}) and (c({"Action": "DeleteVpnConcentrator", "VpnConcentratorId": vc}) and vc not in c({"Action": "DescribeVpnConcentrators"})))


def cidrs_and_edge():
    e = Env(); c = e.call
    vpc_id = e.id(c({"Action": "CreateVpc", "CidrBlock": "10.72.0.0/16"}), "vpcId")
    other = e.id(c({"Action": "CreateVpc", "CidrBlock": "10.73.0.0/16"}), "vpcId")
    c({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.99.1.0/24"}, ok=False)
    _check("subnet outside every VPC CIDR rejected", True)
    for bad in ("10.72.5.0/24", "8.8.0.0/16", "10.80.0.0/8", "10.80.0.0/29"):
        c({"Action": "AssociateVpcCidrBlock", "VpcId": vpc_id, "CidrBlock": bad}, ok=False)
    _check("overlap / public range / size rejected", True)
    body = c({"Action": "AssociateVpcCidrBlock", "VpcId": vpc_id, "CidrBlock": "10.80.0.0/16"})
    aid = e.id(body, "associationId")
    d = c({"Action": "DescribeVpcs", "VpcId.1": vpc_id})
    _check("secondary CIDR in cidrBlockAssociationSet", "<cidrBlock>10.80.0.0/16</cidrBlock>" in d and d.count("<cidrBlockState>") == 2)
    sn = e.id(c({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.80.1.0/24"}), "subnetId")
    _check("subnet can use the secondary CIDR", sn.startswith("subnet-"))
    _check("local route for the secondary CIDR", "<destinationCidrBlock>10.80.0.0/16</destinationCidrBlock><gatewayId>local</gatewayId>" in c({"Action": "DescribeRouteTables"}))
    _check("disassociate blocked while a subnet lives there", "OperationNotPermitted" in c({"Action": "DisassociateVpcCidrBlock", "AssociationId": aid}, ok=False))
    c({"Action": "DeleteSubnet", "SubnetId": sn})
    c({"Action": "DisassociateVpcCidrBlock", "AssociationId": aid})
    _check("disassociated CIDR gone", "10.80.0.0/16" not in c({"Action": "DescribeVpcs", "VpcId.1": vpc_id}))
    _check("primary CIDR cannot be disassociated", "OperationNotPermitted" in c({"Action": "DisassociateVpcCidrBlock", "AssociationId": "vpc-cidr-assoc-primary-" + vpc_id[4:]}, ok=False))
    v6 = c({"Action": "AssociateVpcCidrBlock", "VpcId": vpc_id, "AmazonProvidedIpv6CidrBlock": "true"})
    _check("Amazon-provided IPv6 /56", "/56</ipv6CidrBlock>" in v6)
    # edge associations
    igw = e.id(c({"Action": "CreateInternetGateway"}), "internetGatewayId")
    rtb = e.id(c({"Action": "CreateRouteTable", "VpcId": vpc_id}), "routeTableId")
    c({"Action": "AssociateRouteTable", "RouteTableId": rtb, "GatewayId": igw}, ok=False)
    c({"Action": "AttachInternetGateway", "InternetGatewayId": igw, "VpcId": vpc_id})
    ea = e.id(c({"Action": "AssociateRouteTable", "RouteTableId": rtb, "GatewayId": igw}), "associationId")
    rt = c({"Action": "DescribeRouteTables", "RouteTableId.1": rtb})
    _check("edge association listed with gatewayId", f"<gatewayId>{igw}</gatewayId><main>false</main>" in rt)
    rtb2 = e.id(c({"Action": "CreateRouteTable", "VpcId": vpc_id}), "routeTableId")
    c({"Action": "AssociateRouteTable", "RouteTableId": rtb2, "GatewayId": igw}, ok=False)
    c({"Action": "AssociateRouteTable", "RouteTableId": rtb2, "GatewayId": "eni-1"}, ok=False)
    c({"Action": "DisassociateRouteTable", "AssociationId": ea})
    _check("edge association removed", f"<gatewayId>{igw}</gatewayId><main>" not in c({"Action": "DescribeRouteTables", "RouteTableId.1": rtb}))


def traffic_mirroring():
    e = Env(); c = e.call
    vpc_id = e.id(c({"Action": "CreateVpc", "CidrBlock": "10.74.0.0/16"}), "vpcId")
    sub = e.id(c({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.74.1.0/24"}), "subnetId")
    a = e.id(c({"Action": "CreateNetworkInterface", "SubnetId": sub}), "networkInterfaceId")
    b = e.id(c({"Action": "CreateNetworkInterface", "SubnetId": sub}), "networkInterfaceId")
    c({"Action": "CreateTrafficMirrorTarget", "NetworkInterfaceId": "eni-nope"}, ok=False)
    c({"Action": "CreateTrafficMirrorTarget"}, ok=False)
    tgt = e.id(c({"Action": "CreateTrafficMirrorTarget", "NetworkInterfaceId": b, "Description": "ids"}), "trafficMirrorTargetId")
    flt = e.id(c({"Action": "CreateTrafficMirrorFilter", "Description": "web"}), "trafficMirrorFilterId")
    rule = {"Action": "CreateTrafficMirrorFilterRule", "TrafficMirrorFilterId": flt, "TrafficDirection": "ingress", "RuleNumber": "100", "RuleAction": "accept",
            "DestinationCidrBlock": "0.0.0.0/0", "SourceCidrBlock": "0.0.0.0/0", "Protocol": "6", "DestinationPortRange.FromPort": "443", "DestinationPortRange.ToPort": "443"}
    rid = e.id(c(rule), "trafficMirrorFilterRuleId")
    _check("duplicate rule number rejected", "Duplicate" in c(rule, ok=False))
    c({**rule, "RuleNumber": "101", "Protocol": "1"}, ok=False)
    c({**rule, "RuleNumber": "102", "RuleAction": "maybe"}, ok=False)
    _check("rule listed", rid in c({"Action": "DescribeTrafficMirrorFilterRules", "TrafficMirrorFilterId": flt}))
    c({"Action": "CreateTrafficMirrorSession", "NetworkInterfaceId": b, "TrafficMirrorTargetId": tgt, "TrafficMirrorFilterId": flt, "SessionNumber": "1"}, ok=False)
    _check("source == target ENI rejected", True)
    sid = e.id(c({"Action": "CreateTrafficMirrorSession", "NetworkInterfaceId": a, "TrafficMirrorTargetId": tgt, "TrafficMirrorFilterId": flt, "SessionNumber": "1", "PacketLength": "128"}), "trafficMirrorSessionId")
    _check("duplicate session number per ENI rejected", "Duplicate" in c({"Action": "CreateTrafficMirrorSession", "NetworkInterfaceId": a, "TrafficMirrorTargetId": tgt, "TrafficMirrorFilterId": flt, "SessionNumber": "1"}, ok=False))
    _check("target + filter in use cannot be deleted", "InUse" in c({"Action": "DeleteTrafficMirrorTarget", "TrafficMirrorTargetId": tgt}, ok=False) and "InUse" in c({"Action": "DeleteTrafficMirrorFilter", "TrafficMirrorFilterId": flt}, ok=False))
    m = e.s._vpc_model; sess = m["tm_sessions"][sid]
    from core import vpc_extras_core as x
    _check("filter evaluator: tcp/443 ingress accepted", x.mirror_decision(m, sess, "ingress", 6, "1.2.3.4", "10.74.1.4", 5555, 443) == "accept")
    _check("filter evaluator: tcp/80 not mirrored", x.mirror_decision(m, sess, "ingress", 6, "1.2.3.4", "10.74.1.4", 5555, 80) is None)
    c({"Action": "DeleteTrafficMirrorSession", "TrafficMirrorSessionId": sid})
    c({"Action": "DeleteTrafficMirrorFilterRule", "TrafficMirrorFilterRuleId": rid})
    c({"Action": "DeleteTrafficMirrorFilter", "TrafficMirrorFilterId": flt})
    c({"Action": "DeleteTrafficMirrorTarget", "TrafficMirrorTargetId": tgt})


def tgw_extras():
    e = Env(); c = e.call
    va = e.id(c({"Action": "CreateVpc", "CidrBlock": "10.75.0.0/16"}), "vpcId")
    sa = e.id(c({"Action": "CreateSubnet", "VpcId": va, "CidrBlock": "10.75.1.0/24"}), "subnetId")
    tg = e.id(c({"Action": "CreateTransitGateway", "Options.MulticastSupport": "enable"}), "transitGatewayId")
    plain = e.id(c({"Action": "CreateTransitGateway"}), "transitGatewayId")
    att = e.id(c({"Action": "CreateTransitGatewayVpcAttachment", "TransitGatewayId": tg, "VpcId": va, "SubnetIds.1": sa}), "transitGatewayAttachmentId")
    c({"Action": "CreateTransitGatewayPolicyTable", "TransitGatewayId": "tgw-nope"}, ok=False)
    pt = e.id(c({"Action": "CreateTransitGatewayPolicyTable", "TransitGatewayId": tg}), "transitGatewayPolicyTableId")
    c({"Action": "AssociateTransitGatewayPolicyTable", "TransitGatewayPolicyTableId": pt, "TransitGatewayAttachmentId": att})
    _check("policy table association listed", att in c({"Action": "GetTransitGatewayPolicyTableAssociations", "TransitGatewayPolicyTableId": pt}))
    c({"Action": "DeleteTransitGatewayPolicyTable", "TransitGatewayPolicyTableId": pt}, ok=False)
    c({"Action": "DisassociateTransitGatewayPolicyTable", "TransitGatewayPolicyTableId": pt, "TransitGatewayAttachmentId": att})
    c({"Action": "DeleteTransitGatewayPolicyTable", "TransitGatewayPolicyTableId": pt})
    _check("multicast needs MulticastSupport on the TGW", "InvalidTransitGatewayState" in c({"Action": "CreateTransitGatewayMulticastDomain", "TransitGatewayId": plain}, ok=False))
    md = e.id(c({"Action": "CreateTransitGatewayMulticastDomain", "TransitGatewayId": tg, "Options.StaticSourcesSupport": "enable"}), "transitGatewayMulticastDomainId")
    c({"Action": "AssociateTransitGatewayMulticastDomain", "TransitGatewayMulticastDomainId": md, "TransitGatewayAttachmentId": att, "SubnetIds.1": "subnet-nope"}, ok=False)
    c({"Action": "AssociateTransitGatewayMulticastDomain", "TransitGatewayMulticastDomainId": md, "TransitGatewayAttachmentId": att, "SubnetIds.1": sa})
    eni = e.id(c({"Action": "CreateNetworkInterface", "SubnetId": sa}), "networkInterfaceId")
    c({"Action": "RegisterTransitGatewayMulticastGroupMembers", "TransitGatewayMulticastDomainId": md, "GroupIpAddress": "10.0.0.1", "NetworkInterfaceIds.1": eni}, ok=False)
    c({"Action": "RegisterTransitGatewayMulticastGroupMembers", "TransitGatewayMulticastDomainId": md, "GroupIpAddress": "224.0.0.50", "NetworkInterfaceIds.1": eni})
    _check("registered member found by group search", eni in c({"Action": "SearchTransitGatewayMulticastGroups", "TransitGatewayMulticastDomainId": md}))
    c({"Action": "DeleteTransitGatewayMulticastDomain", "TransitGatewayMulticastDomainId": md}, ok=False)
    c({"Action": "DisassociateTransitGatewayMulticastDomain", "TransitGatewayMulticastDomainId": md, "TransitGatewayAttachmentId": att, "SubnetIds.1": sa})
    c({"Action": "DeleteTransitGatewayMulticastDomain", "TransitGatewayMulticastDomainId": md})
    mp = e.id(c({"Action": "CreateTransitGatewayMeteringPolicy", "TransitGatewayId": tg, "MiddleboxAttachmentId.1": att}), "transitGatewayMeteringPolicyId")
    c({"Action": "CreateTransitGatewayMeteringPolicyEntry", "TransitGatewayMeteringPolicyId": mp, "PolicyRuleNumber": "10", "PolicyRule.Protocol": "6"})
    c({"Action": "CreateTransitGatewayMeteringPolicyEntry", "TransitGatewayMeteringPolicyId": mp, "PolicyRuleNumber": "10"}, ok=False)
    _check("metering entry listed", "<policyRuleNumber>10</policyRuleNumber>" in c({"Action": "GetTransitGatewayMeteringPolicyEntries", "TransitGatewayMeteringPolicyId": mp}))
    c({"Action": "DeleteTransitGatewayMeteringPolicy", "TransitGatewayMeteringPolicyId": mp})


def main():
    tgw_extras()
    traffic_mirroring()
    cidrs_and_edge()
    vpn()
    client_vpn()
    print("\nVPC sweep: ALL GREEN")


if __name__ == "__main__":
    main()
