"""VPC wave-5b gap-sweep conformance: PrivateLink gateway endpoints (real route +
netsim enforcement), VPC Block Public Access (real egress/ingress enforcement +
exclusions), DHCP option sets (effective DNS resolution, enforced not stored),
NAT gateway CloudWatch monitoring (real activity-derived metrics), Network Access
Analyzer (scope/analysis/findings reusing the reachability evaluator), and AWS
Verified Access (CRUD + the real policy-test evaluator). Host + Pyodide.
"""
import re
import types

try:
    from core import vpc_core as vpc
    from core import cloudwatch_core as cw
except ImportError:  # pragma: no cover - Pyodide flat layout
    import vpc_core as vpc  # type: ignore
    import cloudwatch_core as cw  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or types.SimpleNamespace()
    s.cw_store = cw.CloudWatchStore()

    def call(p):
        r = vpc.dispatch(s, p)
        if r.status != 200:
            raise AssertionError((p.get("Action"), r.body))
        return r.body

    def xid(body, tag):
        return re.search(f"<{tag}>(.*?)</{tag}>", body).group(1)

    # ── PrivateLink: Gateway VPC endpoint (S3) ──────────────────────────────
    vpc_id = xid(call({"Action": "CreateVpc", "CidrBlock": "10.40.0.0/16"}), "vpcId")
    subnet_id = xid(call({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.40.1.0/24"}), "subnetId")
    rt_id = s._vpc_model["subnets"][subnet_id]["route_table"]
    vpce_id = xid(call({"Action": "CreateVpcEndpoint", "VpcId": vpc_id, "ServiceName": "com.amazonaws.us-east-1.s3",
                        "VpcEndpointType": "Gateway", "RouteTableId.1": rt_id}), "vpcEndpointId")
    routes = s._vpc_model["route_tables"][rt_id]["routes"]
    _check("gateway endpoint adds a real route to the chosen table", any(r["target"] == vpce_id for r in routes))
    v = vpc.reach(s, {"ip": "10.40.1.10", "security_group_ids": []}, {"ip": "52.216.1.1"}, 443, "tcp")
    _check("S3 prefix-list IP reachable via the gateway endpoint", v.reachable and v.path == "via-gateway-endpoint")
    call({"Action": "DeleteVpcEndpoints", "VpcEndpointId.1": vpce_id})
    _check("endpoint route removed after delete", not any(r["target"] == vpce_id for r in s._vpc_model["route_tables"][rt_id]["routes"]))
    v2 = vpc.reach(s, {"ip": "10.40.1.10", "security_group_ids": []}, {"ip": "52.216.1.1"}, 443, "tcp")
    _check("S3 prefix-list IP unreachable once the endpoint is gone", not v2.reachable)

    # ── PrivateLink: Interface endpoint + endpoint service connection flow ──
    svc_id = xid(call({"Action": "CreateVpcEndpointServiceConfiguration",
                       "NetworkLoadBalancerArn.1": "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/x/1",
                       "AcceptanceRequired": "true"}), "serviceId")
    service_name = re.search(r"<serviceName>(.*?)</serviceName>", call({"Action": "DescribeVpcEndpointServiceConfigurations"})).group(1)
    iface_ep = xid(call({"Action": "CreateVpcEndpoint", "VpcId": vpc_id, "ServiceName": service_name,
                        "VpcEndpointType": "Interface", "SubnetId.1": subnet_id}), "vpcEndpointId")
    _check("interface endpoint gets a real ENI", len(s._vpc_model["vpc_endpoints"][iface_ep]["eni_ids"]) == 1)
    _check("interface endpoint to an acceptance-required service starts pendingAcceptance",
           s._vpc_model["vpc_endpoints"][iface_ep]["state"] == "pendingAcceptance")
    call({"Action": "AcceptVpcEndpointConnections", "ServiceId": svc_id, "VpcEndpointId.1": iface_ep})
    _check("accepted connection flips the endpoint to available", s._vpc_model["vpc_endpoints"][iface_ep]["state"] == "available")

    # ── VPC Block Public Access ─────────────────────────────────────────────
    igw_id = xid(call({"Action": "CreateInternetGateway"}), "internetGatewayId")
    call({"Action": "AttachInternetGateway", "InternetGatewayId": igw_id, "VpcId": vpc_id})
    call({"Action": "CreateRoute", "RouteTableId": rt_id, "DestinationCidrBlock": "0.0.0.0/0", "GatewayId": igw_id})
    from core.netsim import from_aws as fa, evaluate as ev, model as nm
    topo = fa.from_aws(s._vpc_model)
    topo.add(nm.Interface(id="eni-bpa-test", subnet=subnet_id, ip="10.40.1.20", public_ip="203.0.113.50", groups=[], rulesets=[]))
    before = ev.reach(topo, "eni-bpa-test", "8.8.8.8", "tcp", 443)
    _check("egress works before Block Public Access", before.reachable)
    call({"Action": "ModifyVpcBlockPublicAccessOptions", "InternetGatewayBlockMode": "block-bidirectional"})
    topo2 = fa.from_aws(s._vpc_model)
    topo2.add(nm.Interface(id="eni-bpa-test", subnet=subnet_id, ip="10.40.1.20", public_ip="203.0.113.50", groups=[], rulesets=[]))
    blocked = ev.reach(topo2, "eni-bpa-test", "8.8.8.8", "tcp", 443)
    _check("block-bidirectional really blocks egress", not blocked.reachable and blocked.code == "BLOCKED_PUBLIC_ACCESS")
    call({"Action": "CreateVpcBlockPublicAccessExclusion", "SubnetId": subnet_id, "InternetGatewayExclusionMode": "allow-bidirectional"})
    topo3 = fa.from_aws(s._vpc_model)
    topo3.add(nm.Interface(id="eni-bpa-test", subnet=subnet_id, ip="10.40.1.20", public_ip="203.0.113.50", groups=[], rulesets=[]))
    excluded = ev.reach(topo3, "eni-bpa-test", "8.8.8.8", "tcp", 443)
    _check("an exclusion restores egress for that subnet", excluded.reachable)
    call({"Action": "ModifyVpcBlockPublicAccessOptions", "InternetGatewayBlockMode": "off"})

    # ── DHCP option sets: effective DNS resolution is enforced, not stored ──
    dns0 = call({"Action": "DescribeVpcDnsResolution", "VpcId": vpc_id})
    _check("default VPC resolves via AmazonProvidedDNS at the reserved address",
           "<amazonProvidedDns>true</amazonProvidedDns>" in dns0 and "<item>10.40.0.2</item>" in dns0)
    dopt_id = xid(call({"Action": "CreateDhcpOptions", "DhcpConfiguration.1.Key": "domain-name-servers",
                       "DhcpConfiguration.1.Value.1": "8.8.8.8"}), "dhcpOptionsId")
    call({"Action": "AssociateDhcpOptions", "VpcId": vpc_id, "DhcpOptionsId": dopt_id})
    dns1 = call({"Action": "DescribeVpcDnsResolution", "VpcId": vpc_id})
    _check("associating a custom DHCP option set changes the effective resolver",
           "<amazonProvidedDns>false</amazonProvidedDns>" in dns1 and "<item>8.8.8.8</item>" in dns1)
    call({"Action": "ModifyVpcAttribute", "VpcId": vpc_id, "EnableDnsSupport.Value": "false"})
    dns2 = call({"Action": "DescribeVpcDnsResolution", "VpcId": vpc_id})
    _check("disabling DNS support really removes every resolver", "<dnsServerSet></dnsServerSet>" in dns2)
    call({"Action": "ModifyVpcAttribute", "VpcId": vpc_id, "EnableDnsSupport.Value": "true"})

    # ── NAT gateway CloudWatch monitoring: real activity, not synthetic ─────
    nat_subnet = xid(call({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.40.2.0/24"}), "subnetId")
    nat_id = xid(call({"Action": "CreateNatGateway", "SubnetId": nat_subnet}), "natGatewayId")
    priv_rt = xid(call({"Action": "CreateRouteTable", "VpcId": vpc_id}), "routeTableId")
    priv_subnet = xid(call({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.40.3.0/24"}), "subnetId")
    call({"Action": "AssociateRouteTable", "RouteTableId": priv_rt, "SubnetId": priv_subnet})
    call({"Action": "CreateRoute", "RouteTableId": priv_rt, "DestinationCidrBlock": "0.0.0.0/0", "NatGatewayId": nat_id})
    key = next(iter(s.cw_store.metrics), None)
    _check("no NAT metrics before any reachability check through it", key is None or "NatGatewayId" not in key or nat_id not in key)
    vv = vpc.reach(s, {"ip": "10.40.3.10", "security_group_ids": []}, {"ip": "8.8.8.8"}, 443, "tcp")
    _check("reachability through the NAT gateway succeeds", vv.reachable and vv.path == "internet-via-nat")
    metric_keys = [k for k in s.cw_store.metrics if "AWS/NATGateway" in k and nat_id in k]
    _check("a real AWS/NATGateway metric point was pushed for this check", len(metric_keys) > 0)

    # ── Network Access Analyzer ─────────────────────────────────────────────
    scope_id = xid(call({"Action": "CreateNetworkInsightsAccessScope"}), "networkInsightsAccessScopeId")
    analysis_body = call({"Action": "StartNetworkInsightsAccessScopeAnalysis", "NetworkInsightsAccessScopeId": scope_id})
    analysis_id = xid(analysis_body, "networkInsightsAccessScopeAnalysisId")
    findings_body = call({"Action": "DescribeNetworkInsightsAccessScopeAnalysisFindings", "NetworkInsightsAccessScopeAnalysisId": analysis_id})
    _check("access scope analysis completes", "<analysisStatus>succeeded</analysisStatus>" in findings_body)
    call({"Action": "DeleteNetworkInsightsAccessScope", "NetworkInsightsAccessScopeId": scope_id})
    _check("access scope gone after delete", scope_id not in call({"Action": "DescribeNetworkInsightsAccessScopes"}))

    # ── AWS Verified Access ──────────────────────────────────────────────────
    vai_id = xid(call({"Action": "CreateVerifiedAccessInstance", "Description": "uic-test"}), "verifiedAccessInstanceId")
    vagr_id = xid(call({"Action": "CreateVerifiedAccessGroup", "VerifiedAccessInstanceId": vai_id,
                        "PolicyDocument": 'permit(context.device.trust == "high");'}), "verifiedAccessGroupId")
    vae_id = xid(call({"Action": "CreateVerifiedAccessEndpoint", "VerifiedAccessGroupId": vagr_id,
                       "ApplicationDomain": "app.internal"}), "verifiedAccessEndpointId")
    allow = call({"Action": "VerifyAccessEndpointPolicy", "VerifiedAccessEndpointId": vae_id, "Context": '{"device":{"trust":"high"}}'})
    _check("policy tester allows matching context", "<policyAllowed>true</policyAllowed>" in allow)
    deny = call({"Action": "VerifyAccessEndpointPolicy", "VerifiedAccessEndpointId": vae_id, "Context": '{"device":{"trust":"low"}}'})
    _check("policy tester denies non-matching context", "<policyAllowed>false</policyAllowed>" in deny)
    call({"Action": "DeleteVerifiedAccessEndpoint", "VerifiedAccessEndpointId": vae_id})
    call({"Action": "DeleteVerifiedAccessGroup", "VerifiedAccessGroupId": vagr_id})
    call({"Action": "DeleteVerifiedAccessInstance", "VerifiedAccessInstanceId": vai_id})
    _check("Verified Access instance gone after delete", vai_id not in call({"Action": "DescribeVerifiedAccessInstances"}))

    print("\nVPC gap-sweep (wave 5b) conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
