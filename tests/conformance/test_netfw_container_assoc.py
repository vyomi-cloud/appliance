"""Network Firewall container associations (Vyomi-simulated verbs): firewall <-> EKS cluster, protected node networks,
SimulateContainerTraffic through the firewall policy. Run: PYTHONPATH=. python3 tests/conformance/test_netfw_container_assoc.py"""
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
    vpc = x("vpcId", ec2("CreateVpc", CidrBlock="10.50.0.0/16"))
    other = x("vpcId", ec2("CreateVpc", CidrBlock="10.60.0.0/16"))
    mk = lambda v, c, az: x("subnetId", ec2("CreateSubnet", VpcId=v, CidrBlock=c, AvailabilityZone=az))
    fw_sub, n1, n2 = mk(vpc, "10.50.0.0/24", "us-east-1a"), mk(vpc, "10.50.1.0/24", "us-east-1a"), mk(vpc, "10.50.2.0/24", "us-east-1b")
    o1, o2 = mk(other, "10.60.1.0/24", "us-east-1a"), mk(other, "10.60.2.0/24", "us-east-1b")

    def eks_create(name, subnets, vpc_id):
        # Nano has no k3s control plane (EKS create is refused there), so seed the account bag the way a real create would leave it.
        from core import aws_eks_core
        aws_eks_core._st(r.s3.account)["clusters"][aws_eks_core._ck("us-east-1", name)] = {"name": name, "status": "ACTIVE", "resourcesVpcConfig": {"vpcId": vpc_id, "subnetIds": subnets}}

    eks_create("prod", [n1, n2], vpc)
    eks_create("elsewhere", [o1, o2], other)

    st, rg = nfw("CreateRuleGroup", {"RuleGroupName": "no-ssh", "Type": "STATELESS", "Capacity": 10, "RuleGroup": {"RulesSource": {"StatelessRulesAndCustomActions": {
        "StatelessRules": [{"Priority": 1, "RuleDefinition": {"MatchAttributes": {"Protocols": [6], "DestinationPorts": [{"FromPort": 22, "ToPort": 22}]}, "Actions": ["aws:drop"]}}]}}}})
    st, pol = nfw("CreateFirewallPolicy", {"FirewallPolicyName": "pol", "FirewallPolicy": {"StatelessDefaultActions": ["aws:pass"], "StatelessFragmentDefaultActions": ["aws:pass"],
                                                                                          "StatelessRuleGroupReferences": [{"ResourceArn": rg["RuleGroupResponse"]["RuleGroupArn"], "Priority": 10}]}})
    st, fw = nfw("CreateFirewall", {"FirewallName": "fw1", "FirewallPolicyArn": pol["FirewallPolicyResponse"]["FirewallPolicyArn"], "VpcId": vpc, "SubnetMappings": [{"SubnetId": fw_sub}]})
    farn = fw["Firewall"]["FirewallArn"]

    st, o = nfw("CreateContainerAssociation", {"FirewallArn": farn, "ClusterName": "nope"})
    _check("unknown cluster refused", st == 400 and o["__type"] == "ResourceNotFoundException", o)
    st, o = nfw("CreateContainerAssociation", {"FirewallArn": farn, "ClusterName": "elsewhere"})
    _check("cluster in a VPC without a firewall endpoint refused", st == 400 and "endpoint" in o["message"], o)
    st, o = nfw("CreateContainerAssociation", {"FirewallArn": farn, "ClusterName": "prod", "ClusterType": "ECS"})
    _check("ECS refused honestly", st == 400 and "ECS" in o["message"], o)

    st, o = nfw("CreateContainerAssociation", {"FirewallArn": farn, "ClusterName": "prod", "Description": "prod nodes"})
    _check("EKS cluster in firewall VPC associated", st == 200, o)
    a = o["ContainerAssociation"]
    _check("protected node networks derived from the cluster subnets", sorted(a["ProtectedCidrs"]) == ["10.50.1.0/24", "10.50.2.0/24"], a)
    st, o = nfw("CreateContainerAssociation", {"FirewallArn": farn, "ClusterName": "prod"})
    _check("duplicate refused", st == 400, o)

    st, o = nfw("SimulateContainerTraffic", {"ContainerAssociationId": a["ContainerAssociationId"], "Packet": {"Protocol": "tcp", "SourceIp": "10.50.1.9", "DestinationIp": "10.9.9.9", "DestinationPort": 22}})
    _check("ssh from a node is dropped by the firewall policy", st == 200 and o["Action"] == "DROP", o)
    st, o = nfw("SimulateContainerTraffic", {"ContainerAssociationId": a["ContainerAssociationId"], "Packet": {"Protocol": "tcp", "SourceIp": "10.50.1.9", "DestinationIp": "10.9.9.9", "DestinationPort": 443}})
    _check("https from a node passes", st == 200 and o["Action"] == "PASS", o)
    st, o = nfw("SimulateContainerTraffic", {"ContainerAssociationId": a["ContainerAssociationId"], "Packet": {"Protocol": "tcp", "SourceIp": "192.168.0.1", "DestinationIp": "10.9.9.9", "DestinationPort": 443}})
    _check("source outside the protected networks refused", st == 400, o)

    st, o = nfw("ListContainerAssociations", {"FirewallArn": farn})
    _check("listed", st == 200 and len(o["ContainerAssociations"]) == 1, o)
    st, o = nfw("DeleteContainerAssociation", {"ContainerAssociationId": a["ContainerAssociationId"]})
    _check("deleted", st == 200, o)
    st, o = nfw("ListContainerAssociations", {})
    _check("list empty after delete", o["ContainerAssociations"] == [], o)
    print("PASS test_netfw_container_assoc")


if __name__ == "__main__":
    main()
