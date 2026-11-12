"""EC2/VPC addressing + routing semantics the netsim engine relies on, and the native VPC
Reachability Analyzer (Network Insights) answered by core/netsim — host + Pyodide.

  * private IPv4 comes from the SUBNET CIDR; .0-.3 and the broadcast address are reserved;
    PrivateIpAddress honoured, in-use / out-of-range / reserved rejected
  * public IPv4 only per MapPublicIpOnLaunch / AssociatePublicIpAddress / EIP
  * ModifySubnetAttribute(MapPublicIpOnLaunch), SourceDestCheck on instances + ENIs
  * custom route tables carry the `local` route; CreateRoute InstanceId / NetworkInterfaceId targets
  * CreateNetworkInsightsPath → StartNetworkInsightsAnalysis → networkPathFound + explanations

    PYTHONPATH=. python3 tests/conformance/test_vpc_netsim_core.py
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

    def call(p, status=200):
        r = vpc.dispatch(s, p)
        if r.status != status:
            raise AssertionError((p.get("Action"), r.status, r.body))
        return r.body

    def xid(body, tag):
        return re.search(f"<{tag}>(.*?)</{tag}>", body).group(1)

    vpc_id = xid(call({"Action": "CreateVpc", "CidrBlock": "10.40.0.0/16"}), "vpcId")
    pub = xid(call({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.40.1.0/28"}), "subnetId")
    priv = xid(call({"Action": "CreateSubnet", "VpcId": vpc_id, "CidrBlock": "10.40.2.0/24"}), "subnetId")

    # addressing
    run_i = lambda **kw: call({"Action": "RunInstances", "MinCount": "1", "MaxCount": "1", **kw})
    a = xid(run_i(SubnetId=pub), "instanceId")
    _check("first instance gets .4 (AWS reserves .0-.3)", xid(call({"Action": "DescribeInstances", "InstanceId.1": a}), "privateIpAddress") == "10.40.1.4")
    b_body = run_i(SubnetId=priv, PrivateIpAddress="10.40.2.50")
    b = xid(b_body, "instanceId")
    _check("PrivateIpAddress honoured", "<privateIpAddress>10.40.2.50</privateIpAddress>" in b_body)
    _check("address in use rejected", "InvalidIPAddress.InUse" in call({"Action": "RunInstances", "SubnetId": priv, "PrivateIpAddress": "10.40.2.50"}, 400))
    _check("reserved .1 rejected", "reserved" in call({"Action": "RunInstances", "SubnetId": priv, "PrivateIpAddress": "10.40.2.1"}, 400))
    _check("outside subnet rejected", "InvalidParameterValue" in call({"Action": "RunInstances", "SubnetId": priv, "PrivateIpAddress": "10.40.9.9"}, 400))
    for _ in range(10):                      # /28 → 16 - 5 reserved = 11 usable; a used one
        run_i(SubnetId=pub)
    _check("exhausted subnet → InsufficientFreeAddressesInSubnet",
           "InsufficientFreeAddressesInSubnet" in call({"Action": "RunInstances", "SubnetId": pub}, 400))

    # public IPv4 rules
    _check("custom subnet: no public IPv4 by default", "<ipAddress></ipAddress>" in b_body)
    call({"Action": "ModifySubnetAttribute", "SubnetId": priv, "MapPublicIpOnLaunch.Value": "true"})
    _check("ModifySubnetAttribute → mapPublicIpOnLaunch true",
           "<mapPublicIpOnLaunch>true</mapPublicIpOnLaunch>" in call({"Action": "DescribeSubnets"}))
    c_body = run_i(SubnetId=priv)
    _check("MapPublicIpOnLaunch subnet → public IPv4", "<ipAddress></ipAddress>" not in c_body)
    d_body = run_i(SubnetId=priv, **{"NetworkInterface.1.AssociatePublicIpAddress": "false"})
    _check("AssociatePublicIpAddress=false overrides the subnet", "<ipAddress></ipAddress>" in d_body)
    d = xid(d_body, "instanceId")
    call({"Action": "StopInstances", "InstanceId.1": d})
    call({"Action": "StartInstances", "InstanceId.1": d})
    _check("no-public instance stays private across stop/start",
           "<ipAddress></ipAddress>" in call({"Action": "DescribeInstances", "InstanceId.1": d}))
    default_body = call({"Action": "RunInstances", "MinCount": "1", "MaxCount": "1"})
    _check("default VPC launch still gets a public IPv4", "<ipAddress></ipAddress>" not in default_body)

    # source/dest check
    call({"Action": "ModifyInstanceAttribute", "InstanceId": a, "SourceDestCheck.Value": "false"})
    _check("instance SourceDestCheck=false", "<sourceDestCheck>false</sourceDestCheck>" in call({"Action": "DescribeInstances", "InstanceId.1": a}))
    eni = xid(call({"Action": "CreateNetworkInterface", "SubnetId": priv}), "networkInterfaceId")
    call({"Action": "ModifyNetworkInterfaceAttribute", "NetworkInterfaceId": eni, "SourceDestCheck.Value": "false"})
    _check("ENI SourceDestCheck=false", "<sourceDestCheck>false</sourceDestCheck>" in call({"Action": "DescribeNetworkInterfaces"}))
    _check("ENI address allocated in its subnet",
           re.search(r"<networkInterfaceId>" + eni + r"</networkInterfaceId>.*?<privateIpAddress>10\.40\.2\.", call({"Action": "DescribeNetworkInterfaces"}), re.S))

    # route tables
    rt = xid(call({"Action": "CreateRouteTable", "VpcId": vpc_id}), "routeTableId")
    rtx = call({"Action": "DescribeRouteTables", "RouteTableId.1": rt})
    _check("custom route table has the local route", "<destinationCidrBlock>10.40.0.0/16</destinationCidrBlock><gatewayId>local</gatewayId>" in rtx)
    call({"Action": "CreateRoute", "RouteTableId": rt, "DestinationCidrBlock": "0.0.0.0/0", "InstanceId": a})
    call({"Action": "CreateRoute", "RouteTableId": rt, "DestinationCidrBlock": "192.168.0.0/16", "NetworkInterfaceId": eni})
    rtx = call({"Action": "DescribeRouteTables", "RouteTableId.1": rt})
    _check("CreateRoute InstanceId target rendered as instanceId", f"<instanceId>{a}</instanceId>" in rtx)
    _check("CreateRoute NetworkInterfaceId target rendered", f"<networkInterfaceId>{eni}</networkInterfaceId>" in rtx)
    _check("duplicate destination → RouteAlreadyExists",
           "RouteAlreadyExists" in call({"Action": "CreateRoute", "RouteTableId": rt, "DestinationCidrBlock": "0.0.0.0/0", "InstanceId": a}, 400))
    _check("route without a target → MissingParameter",
           "MissingParameter" in call({"Action": "CreateRoute", "RouteTableId": rt, "DestinationCidrBlock": "10.9.0.0/16"}, 400))

    # Reachability Analyzer (native Network Insights API) — answered by core/netsim
    sg = xid(call({"Action": "CreateSecurityGroup", "VpcId": vpc_id, "GroupName": "db", "GroupDescription": "db"}), "groupId")
    call({"Action": "ModifyInstanceAttribute", "InstanceId": b, "GroupId.1": sg})
    nip = xid(call({"Action": "CreateNetworkInsightsPath", "Source": a, "Destination": b, "Protocol": "tcp",
                    "DestinationPort": "5432"}), "networkInsightsPathId")
    _check("path listed", nip in call({"Action": "DescribeNetworkInsightsPaths"}))
    an = call({"Action": "StartNetworkInsightsAnalysis", "NetworkInsightsPathId": nip})
    _check("analysis: SG blocks → networkPathFound false", "<networkPathFound>false</networkPathFound>" in an)
    _check("explanation code ENI_SG_RULES_MISMATCH naming the SG",
           "<explanationCode>ENI_SG_RULES_MISMATCH</explanationCode>" in an and sg in an)
    call({"Action": "AuthorizeSecurityGroupIngress", "GroupId": sg, "IpPermissions.1.IpProtocol": "tcp",
          "IpPermissions.1.FromPort": "5432", "IpPermissions.1.ToPort": "5432",
          "IpPermissions.1.IpRanges.1.CidrIp": "10.40.0.0/16"})
    an2 = call({"Action": "StartNetworkInsightsAnalysis", "NetworkInsightsPathId": nip})
    _check("after authorize → networkPathFound true + forward path components",
           "<networkPathFound>true</networkPathFound>" in an2 and "<sequenceNumber>1</sequenceNumber>" in an2)
    _check("analyses listed by path", call({"Action": "DescribeNetworkInsightsAnalyses", "NetworkInsightsPathId": nip}).count("<networkInsightsAnalysisId>") == 2)
    _check("path with analyses cannot be deleted",
           "DependencyViolation" in call({"Action": "DeleteNetworkInsightsPath", "NetworkInsightsPathId": nip}, 400))
    for aid in re.findall(r"<networkInsightsAnalysisId>(.*?)</", call({"Action": "DescribeNetworkInsightsAnalyses"})):
        call({"Action": "DeleteNetworkInsightsAnalysis", "NetworkInsightsAnalysisId": aid})
    call({"Action": "DeleteNetworkInsightsPath", "NetworkInsightsPathId": nip})
    _check("path deleted", nip not in call({"Action": "DescribeNetworkInsightsPaths"}))

    # internet: IGW destination
    igw = xid(call({"Action": "CreateInternetGateway"}), "internetGatewayId")
    call({"Action": "AttachInternetGateway", "InternetGatewayId": igw, "VpcId": vpc_id})
    nip2 = xid(call({"Action": "CreateNetworkInsightsPath", "Source": b, "Destination": igw, "Protocol": "tcp",
                     "DestinationPort": "443"}), "networkInsightsPathId")
    _check("private subnet → IGW without a route: NO_ROUTE_TO_DESTINATION",
           "<explanationCode>NO_ROUTE_TO_DESTINATION</explanationCode>" in call({"Action": "StartNetworkInsightsAnalysis", "NetworkInsightsPathId": nip2}))
    print("\nVPC netsim semantics + Reachability Analyzer conformance: ALL GREEN")
    return s


if __name__ == "__main__":
    run()
    print("RESULT: PASS")
