"""boto3 (official SDK, endpoint changed only) against engine operations no SDK
test called: IAM UpdateAccessKey and EC2 DeleteNetworkAcl."""
import os
import sys
import uuid

import boto3

EP = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000")
KW = dict(endpoint_url=EP, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
failed = False
sfx = uuid.uuid4().hex[:8]


def check(name, fn):
    global failed
    try:
        ok = fn()
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {str(e)[:200]}")
        ok = False
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    failed = failed or not ok


def raises(fn, code):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        return code in str(e)
    return False


def main():
    iam, ec2 = boto3.client("iam", **KW), boto3.client("ec2", **KW)
    u = f"conf5-user-{sfx}"
    iam.create_user(UserName=u)
    kid = iam.create_access_key(UserName=u)["AccessKey"]["AccessKeyId"]
    iam.update_access_key(UserName=u, AccessKeyId=kid, Status="Inactive")
    check("iam UpdateAccessKey: ListAccessKeys shows Inactive", lambda: next(
        k["Status"] for k in iam.list_access_keys(UserName=u)["AccessKeyMetadata"] if k["AccessKeyId"] == kid) == "Inactive")
    iam.update_access_key(UserName=u, AccessKeyId=kid, Status="Active")
    check("iam UpdateAccessKey: back to Active", lambda: next(
        k["Status"] for k in iam.list_access_keys(UserName=u)["AccessKeyMetadata"] if k["AccessKeyId"] == kid) == "Active")
    iam.delete_access_key(UserName=u, AccessKeyId=kid)
    iam.delete_user(UserName=u)

    vpc = ec2.create_vpc(CidrBlock="10.78.0.0/16")["Vpc"]["VpcId"]
    acl = ec2.create_network_acl(VpcId=vpc)["NetworkAcl"]["NetworkAclId"]
    check("ec2 CreateNetworkAcl is listed", lambda: acl in [a["NetworkAclId"] for a in ec2.describe_network_acls()["NetworkAcls"]])
    ec2.delete_network_acl(NetworkAclId=acl)
    check("ec2 DeleteNetworkAcl removes it", lambda: acl not in [a["NetworkAclId"] for a in ec2.describe_network_acls()["NetworkAcls"]])
    ec2.delete_vpc(VpcId=vpc)
    sys.exit(1 if failed else 0)


main()
