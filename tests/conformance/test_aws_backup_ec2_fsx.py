"""AWS Backup recovery points for EC2 instances (real AMIs), FSx for OpenZFS volumes (file trees), and honest refusals for EFS / Aurora.
Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_aws_backup_ec2_fsx.py"""
import base64
import json
import re

from core.aws_wire_router import AwsWireRouter

r = AwsWireRouter()
r._sched_last = 1e18
ROLE = "arn:aws:iam::123456789012:role/backup"


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def H(svc, extra=None):
    return dict({"authorization": f"AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"}, **(extra or {}))


def ec2(**p):
    o = r.handle("POST", "/", {}, H("ec2", {"content-type": "application/x-www-form-urlencoded"}), "&".join(f"{k}={v}" for k, v in p.items()).encode())
    return o["status"], o["body"].decode()


def bk(m, path, body=None):
    o = r.handle(m, path, {}, H("backup", {"content-type": "application/json"}), json.dumps(body).encode() if body is not None else b"")
    return o["status"], (json.loads(o["body"]) if o["body"] else {})


def fsx(op, body):
    o = r.handle("POST", "/", {}, H("fsx", {"x-amz-target": f"AWSSimbaAPIService_v20180301.{op}", "content-type": "application/x-amz-json-1.1"}), json.dumps(body).encode())
    return o["status"], (json.loads(o["body"]) if o["body"] else {})


def main():
    s, b = ec2(Action="CreateVpc", CidrBlock="10.7.0.0/16")
    vpc = re.search(r"<vpcId>([^<]+)", b).group(1)
    s, b = ec2(Action="CreateSubnet", VpcId=vpc, CidrBlock="10.7.1.0/24")
    subnet = re.search(r"<subnetId>([^<]+)", b).group(1)
    base_ami = re.search(r"<imageId>([^<]+)", ec2(Action="DescribeImages")[1]).group(1)
    s, b = ec2(Action="RunInstances", ImageId=base_ami, InstanceType="t3.micro", MinCount="1", MaxCount="1", SubnetId=subnet)
    iid = re.search(r"<instanceId>([^<]+)", b).group(1)
    _check("instance running", s == 200 and iid.startswith("i-"))
    s, d = bk("PUT", "/backup-vaults/v1", {})
    iarn = f"arn:aws:ec2:us-east-1:123456789012:instance/{iid}"
    s, d = bk("PUT", "/backup-jobs", {"BackupVaultName": "v1", "ResourceArn": iarn, "IamRoleArn": ROLE})
    jid = d["BackupJobId"]
    s, d = bk("GET", f"/backup-jobs/{jid}")
    _check("EC2 backup job completed", d["State"] == "COMPLETED" and d["ResourceType"] == "EC2")
    rp = d["RecoveryPointArn"]
    ami = rp.rsplit("/", 1)[1]
    _check("recovery point is a real AMI", ami.startswith("ami-") and ami in ec2(Action="DescribeImages")[1])
    s, d = bk("PUT", "/backup-jobs", {"BackupVaultName": "v1", "ResourceArn": "arn:aws:ec2:us-east-1:123456789012:instance/i-0ghost", "IamRoleArn": ROLE})
    _check("missing instance fails the job", bk("GET", f"/backup-jobs/{d['BackupJobId']}")[1]["State"] == "FAILED")
    s, d = bk("PUT", "/restore-jobs", {"RecoveryPointArn": rp, "IamRoleArn": ROLE, "Metadata": {"SubnetId": subnet, "InstanceType": "t3.small"}})
    s, d = bk("GET", f"/restore-jobs/{d['RestoreJobId']}")
    _check("EC2 restore launches an instance from the AMI", d["Status"] == "COMPLETED" and ":instance/i-" in d["CreatedResourceArn"] and d["CreatedResourceArn"].rsplit("/", 1)[1] != iid)

    # EFS / Aurora honest refusals
    for arn, needle in (("arn:aws:elasticfilesystem:us-east-1:123456789012:file-system/fs-1", "EFS"), ("arn:aws:rds:us-east-1:123456789012:cluster:aurora1", "Aurora")):
        s, d = bk("PUT", "/backup-jobs", {"BackupVaultName": "v1", "ResourceArn": arn, "IamRoleArn": ROLE})
        j = bk("GET", f"/backup-jobs/{d['BackupJobId']}")[1]
        _check(f"{needle} refused honestly", j["State"] == "FAILED" and needle in j["StatusMessage"])

    # FSx OpenZFS volume
    s, d = fsx("CreateFileSystem", {"FileSystemType": "OPENZFS", "StorageCapacity": 64, "SubnetIds": [subnet],
                                    "OpenZFSConfiguration": {"DeploymentType": "SINGLE_AZ_1", "ThroughputCapacity": 64}})
    assert s == 200, d
    fsid = d["FileSystem"]["FileSystemId"]
    root = d["FileSystem"]["OpenZFSConfiguration"]["RootVolumeId"]
    s, d = fsx("CreateVolume", {"VolumeType": "OPENZFS", "Name": "data", "OpenZFSConfiguration": {"ParentVolumeId": root}})
    vol = d["Volume"]["VolumeId"]
    s, d2 = fsx("CreateVolume", {"VolumeType": "OPENZFS", "Name": "restored", "OpenZFSConfiguration": {"ParentVolumeId": root}})
    vol2 = d2["Volume"]["VolumeId"]
    st = r.s3.account["fsx"]["vol"]
    st[vol]["_files"]["a.txt"] = {"b": base64.b64encode(b"alpha").decode(), "mtime": "x", "size": 5}
    varn = d["Volume"]["ResourceARN"]
    s, d = bk("PUT", "/backup-jobs", {"BackupVaultName": "v1", "ResourceArn": varn, "IamRoleArn": ROLE})
    j = bk("GET", f"/backup-jobs/{d['BackupJobId']}")[1]
    _check("FSx backup job completed", j["State"] == "COMPLETED" and j["ResourceType"] == "FSx" and j["BackupSizeInBytes"] == 5)
    fr = j["RecoveryPointArn"]
    s, d = bk("PUT", "/restore-jobs", {"RecoveryPointArn": fr, "IamRoleArn": ROLE, "Metadata": {}})
    _check("FSx restore needs a target volume", s == 400)
    s, d = bk("PUT", "/restore-jobs", {"RecoveryPointArn": fr, "IamRoleArn": ROLE, "Metadata": {"TargetVolumeId": vol2}})
    _check("FSx restore copies the files", bk("GET", f"/restore-jobs/{d['RestoreJobId']}")[1]["Status"] == "COMPLETED" and "a.txt" in st[vol2]["_files"])
    s, d = bk("DELETE", f"/backup-vaults/v1/recovery-points/{fr}")
    _check("FSx recovery point delete", s in (200, 204))
    print("BACKUP EC2/FSX OK")


if __name__ == "__main__":
    main()
