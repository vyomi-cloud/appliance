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


def main():
    vpn()
    client_vpn()
    print("\nVPC sweep: ALL GREEN")


if __name__ == "__main__":
    main()
