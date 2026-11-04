"""AWS Network Firewall is IN the netsim path: a route to a firewall endpoint (vpce-) makes AnalyzeReachability run
the firewall policy on the packet, then forward via the firewall subnet's route table. Also SimulateTraffic.
Run: PYTHONPATH=. python3 tests/conformance/test_netfw_path_inspection.py
"""
import json
import re
from urllib.parse import quote

from core.aws_wire_router import AwsWireRouter


def _auth(svc):
    return f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond, extra=""):
    if not cond:
        raise AssertionError(f"{name} {extra}")
    print(f"  ok  {name}")


def main():
    r = AwsWireRouter()

    def ec2(action, **p):
        form = "&".join(f"{k}={quote(str(v))}" for k, v in {"Action": action, **p}.items())
        return r.handle("POST", "/", {}, {"authorization": _auth("ec2"), "content-type": "application/x-www-form-urlencoded"}, form.encode())["body"].decode()

    def nfw(op, body):
        out = r.handle("POST", "/", {}, {"authorization": _auth("network-firewall"), "content-type": "application/x-amz-json-1.0",
                                         "x-amz-target": f"NetworkFirewall_20201112.{op}"}, json.dumps(body).encode())
        return out["status"], json.loads(out["body"])

    x = lambda tag, s: re.search(rf"<{tag}>([\w-]+)</{tag}>", s).group(1)
    vpc = x("vpcId", ec2("CreateVpc", CidrBlock="10.40.0.0/16"))
    mk = lambda c: x("subnetId", ec2("CreateSubnet", VpcId=vpc, CidrBlock=c, AvailabilityZone="us-east-1a"))
    sub_fw, sub_a, sub_b = mk("10.40.0.0/24"), mk("10.40.1.0/24"), mk("10.40.2.0/24")
    sg = x("groupId", ec2("CreateSecurityGroup", GroupName="all", GroupDescription="d", VpcId=vpc))
    ec2("AuthorizeSecurityGroupIngress", GroupId=sg, **{"IpPermissions.1.IpProtocol": "-1", "IpPermissions.1.IpRanges.1.CidrIp": "0.0.0.0/0"})
    run = lambda s: x("instanceId", ec2("RunInstances", MinCount=1, MaxCount=1, SubnetId=s, **{"SecurityGroupId.1": sg}))
    ia, ib = run(sub_a), run(sub_b)

    st, rg = nfw("CreateRuleGroup", {"RuleGroupName": "no-ssh", "Type": "STATELESS", "Capacity": 10, "RuleGroup": {"RulesSource": {"StatelessRulesAndCustomActions": {
        "StatelessRules": [{"Priority": 1, "RuleDefinition": {"MatchAttributes": {"Protocols": [6], "DestinationPorts": [{"FromPort": 22, "ToPort": 22}]}, "Actions": ["aws:drop"]}}]}}}})
    _check("rule group created", st == 200, rg)
    arn = rg["RuleGroupResponse"]["RuleGroupArn"]
    st, pol = nfw("CreateFirewallPolicy", {"FirewallPolicyName": "pol", "FirewallPolicy": {"StatelessDefaultActions": ["aws:pass"], "StatelessFragmentDefaultActions": ["aws:pass"],
                                                                                          "StatelessRuleGroupReferences": [{"ResourceArn": arn, "Priority": 10}]}})
    parn = pol["FirewallPolicyResponse"]["FirewallPolicyArn"]
    st, fw = nfw("CreateFirewall", {"FirewallName": "fw1", "FirewallPolicyArn": parn, "VpcId": vpc, "SubnetMappings": [{"SubnetId": sub_fw}]})
    _check("firewall created", st == 200, fw)
    vpce = fw["FirewallStatus"]["SyncStates"]["us-east-1a"]["Attachment"]["EndpointId"]

    rtb = x("routeTableId", ec2("CreateRouteTable", VpcId=vpc))
    ec2("AssociateRouteTable", RouteTableId=rtb, SubnetId=sub_a)
    ec2("CreateRoute", RouteTableId=rtb, DestinationCidrBlock="10.40.2.0/24", GatewayId=vpce)

    def reach(port):
        o = ec2("AnalyzeReachability", **{"Source.InstanceId": ia, "Destination.InstanceId": ib, "DestinationPort": port})
        return x("reachable", o) == "true", o

    ok, o = reach(80)
    _check("port 80 passes the firewall and is forwarded via the firewall subnet", ok, o)
    ok, o = reach(22)
    _check("port 22 is dropped by the stateless rule group", not ok and "NETWORK_FIREWALL_DROP" in o and "no-ssh" in o, o)
    # SimulateTraffic verb
    st, sim = nfw("SimulateTraffic", {"FirewallName": "fw1", "Packet": {"Protocol": "tcp", "SourceIp": "10.40.1.5", "DestinationIp": "10.40.2.5", "DestinationPort": 22}})
    _check("SimulateTraffic DROP / stateless", sim["Action"] == "DROP" and sim["Stage"] == "stateless", sim)
    st, sim = nfw("SimulateTraffic", {"FirewallName": "fw1", "Packet": {"Protocol": "udp", "SourceIp": "10.40.1.5", "DestinationIp": "10.40.2.5", "DestinationPort": 53}})
    _check("SimulateTraffic PASS", sim["Action"] == "PASS", sim)
    st, bad = nfw("SimulateTraffic", {"FirewallName": "nope", "Packet": {"Protocol": "tcp", "SourceIp": "1.1.1.1", "DestinationIp": "2.2.2.2"}})
    _check("unknown firewall -> error", st >= 400, bad)
    print("network firewall path inspection: all checks passed")


if __name__ == "__main__":
    main()
