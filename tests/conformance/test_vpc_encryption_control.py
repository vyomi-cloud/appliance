"""VPC Encryption Controls (AWS-09 leftover): per-VPC control, monitor/enforce, exclusions, audit of ENIs + load balancers, enforcement.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_vpc_encryption_control.py
"""
import re
from urllib.parse import urlencode

from core.aws_wire_router import AwsWireRouter

EC2 = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0"
ELB = "AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/elasticloadbalancing/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def q(r, action, params=None, auth=EC2, version="2016-11-15"):
    body = urlencode({"Action": action, "Version": version, **(params or {})}).encode()
    out = r.handle("POST", "/", {}, {"authorization": auth, "content-type": "application/x-www-form-urlencoded"}, body)
    return out["status"], out["body"].decode()


def first(x, tag):
    return re.search(rf"<{tag}>([^<]+)</{tag}>", x).group(1)


def main():
    r = AwsWireRouter()
    s, x = q(r, "CreateVpc", {"CidrBlock": "10.9.0.0/16"})
    vpc = first(x, "vpcId")
    s, x = q(r, "CreateSubnet", {"VpcId": vpc, "CidrBlock": "10.9.1.0/24"})
    sub = first(x, "subnetId")
    img = first(q(r, "DescribeImages", {"Owner.1": "amazon"})[1], "imageId")
    s, x = q(r, "RunInstances", {"ImageId": img, "InstanceType": "m5.large", "SubnetId": sub, "MinCount": "1", "MaxCount": "1"})
    _check("fixture m5.large instance", s == 200)

    _check("create on a missing VPC 400", q(r, "CreateVpcEncryptionControl", {"VpcId": "vpc-nope"})[0] == 400)
    s, x = q(r, "CreateVpcEncryptionControl", {"VpcId": vpc, "NatGatewayExclusion": "enable"})
    cid = first(x, "vpcEncryptionControlId")
    _check("create in monitor mode", s == 200 and "<mode>monitor</mode>" in x and cid.startswith("vpcec-"))
    _check("one control per VPC", q(r, "CreateVpcEncryptionControl", {"VpcId": vpc})[0] == 400)
    s, x = q(r, "DescribeVpcEncryptionControls", {"VpcEncryptionControlId.1": cid})
    _check("describe", cid in x and "<state>available</state>" in x)
    s, x = q(r, "GetVpcResourcesBlockingEncryptionEnforcement", {"VpcId": vpc})
    _check("an m5 (non-encrypting) instance ENI blocks enforcement", s == 200 and "<type>instance-network-interface</type>" in x and "m5.large" in x)
    s, x = q(r, "ModifyVpcEncryptionControl", {"VpcEncryptionControlId": cid, "Mode": "enforce"})
    _check("enforce refused while blocking resources exist", s == 400 and "OperationNotPermitted" in x)
    _check("bad mode 400", q(r, "ModifyVpcEncryptionControl", {"VpcEncryptionControlId": cid, "Mode": "nope"})[0] == 400)

    # remediate: terminate the m5, launch an m6i
    iid = first(q(r, "DescribeInstances", {})[1], "instanceId")
    q(r, "TerminateInstances", {"InstanceId.1": iid})
    s, x = q(r, "RunInstances", {"ImageId": img, "InstanceType": "m6g.large", "SubnetId": sub, "MinCount": "1", "MaxCount": "1"})
    _check("a Graviton2 instance launches in monitor mode", s == 200)
    s, x = q(r, "GetVpcResourcesBlockingEncryptionEnforcement", {"VpcId": vpc})
    _check("no blocking resources after remediation", "<type>instance-network-interface</type>" not in x)
    s, x = q(r, "ModifyVpcEncryptionControl", {"VpcEncryptionControlId": cid, "Mode": "enforce", "NatGatewayExclusion": "disable"})
    _check("enforce accepted", s == 200 and "<mode>enforce</mode>" in x)
    s, x = q(r, "RunInstances", {"ImageId": img, "InstanceType": "t3.micro", "SubnetId": sub, "MinCount": "1", "MaxCount": "1"})
    _check("enforce rejects an instance type that cannot encrypt", s == 400 and "OperationNotPermitted" in x)
    s, x = q(r, "RunInstances", {"ImageId": img, "InstanceType": "c6g.large", "SubnetId": sub, "MinCount": "1", "MaxCount": "1"})
    _check("enforce allows an encrypting family", s == 200)

    # load balancer audit (plaintext listener)
    s, x = q(r, "CreateSubnet", {"VpcId": vpc, "CidrBlock": "10.9.2.0/24", "AvailabilityZone": "us-east-1b"})
    sub2 = first(x, "subnetId")
    s, x = q(r, "CreateLoadBalancer", {"Name": "web-lb", "Subnets.member.1": sub, "Subnets.member.2": sub2, "Type": "application"}, auth=ELB, version="2015-12-01")
    lb_arn = first(x, "LoadBalancerArn")
    s, x = q(r, "CreateTargetGroup", {"Name": "tg1", "Protocol": "HTTP", "Port": "80", "VpcId": vpc}, auth=ELB, version="2015-12-01")
    tg = first(x, "TargetGroupArn")
    q(r, "CreateListener", {"LoadBalancerArn": lb_arn, "Protocol": "HTTP", "Port": "80", "DefaultActions.member.1.Type": "forward", "DefaultActions.member.1.TargetGroupArn": tg}, auth=ELB, version="2015-12-01")
    s, x = q(r, "GetVpcResourcesBlockingEncryptionEnforcement", {"VpcId": vpc})
    _check("a load balancer with a plaintext listener is reported", "<type>load-balancer</type>" in x and "HTTP" in x)
    s, x = q(r, "VyomiDescribeVpcEncryptionAudit", {"VpcId": vpc})
    _check("full audit lists encrypted ENIs with reasons", "<encrypted>true</encrypted>" in x and "supports in-transit encryption" in x)
    _check("modify unknown id 400", q(r, "ModifyVpcEncryptionControl", {"VpcEncryptionControlId": "vpcec-x", "Mode": "monitor"})[0] == 400)
    s, x = q(r, "DeleteVpcEncryptionControl", {"VpcEncryptionControlId": cid})
    _check("delete", s == 200 and "<state>deleted</state>" in x)
    s, x = q(r, "RunInstances", {"ImageId": img, "InstanceType": "t3.micro", "SubnetId": sub, "MinCount": "1", "MaxCount": "1"})
    _check("deleting the control lifts enforcement", s == 200)
    print("vpc encryption control conformance OK")


if __name__ == "__main__":
    main()
