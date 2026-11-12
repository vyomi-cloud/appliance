"""S3 Files (bucket-backed file systems) + FSx for OpenZFS S3 access points (AWS-02) via AwsWireRouter.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_s3files_core.py
"""
import base64
import json
import re

from core.aws_wire_router import AwsWireRouter

A = lambda svc: f"AWS4-HMAC-SHA256 Credential=T/20261030/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"
ROLE = "arn:aws:iam::123456789012:role/s3files"


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


r = AwsWireRouter()


def sf(method, path, payload=None, query=None):
    o = r.handle(method, path, query or {}, {"authorization": A("s3files"), "content-type": "application/json"}, json.dumps(payload).encode() if payload is not None else b"")
    return o["status"], (json.loads(o["body"]) if o["body"] else {})


def fsx(op, payload=None):
    o = r.handle("POST", "/", {}, {"authorization": A("fsx"), "x-amz-target": f"AmazonFSx.{op}", "content-type": "application/x-amz-json-1.1"}, json.dumps(payload or {}).encode())
    return o["status"], (json.loads(o["body"]) if o["body"] else {})


def s3(method, path, query=None, body=b""):
    o = r.handle(method, path, query or {}, {"authorization": A("s3")}, body)
    return o["status"], o["body"]


def ec2(action, **params):
    body = "&".join([f"Action={action}", "Version=2016-11-15"] + [f"{k}={v}" for k, v in params.items()])
    o = r.handle("POST", "/", {}, {"authorization": A("ec2"), "content-type": "application/x-www-form-urlencoded"}, body.encode())
    return o["body"].decode()


def main():
    s3("PUT", "/lake")
    _check("bucket must exist", sf("POST", "/file-systems", {"bucket": "arn:aws:s3:::nope", "roleArn": ROLE})[0] == 404)
    _check("bucket must be an ARN", sf("POST", "/file-systems", {"bucket": "lake", "roleArn": ROLE})[0] == 400)
    _check("role must be an IAM role ARN", sf("POST", "/file-systems", {"bucket": "arn:aws:s3:::lake", "roleArn": "x"})[0] == 400)
    s, f = sf("POST", "/file-systems", {"bucket": "arn:aws:s3:::lake", "prefix": "share", "roleArn": ROLE, "tags": [{"key": "Name", "value": "team"}]})
    fid = f["fileSystemId"]
    _check("create file system", s == 201 and fid.startswith("fs-") and f["prefix"] == "share/" and f["name"] == "team" and f["status"] == "available")
    _check("one file system per bucket+prefix", sf("POST", "/file-systems", {"bucket": "arn:aws:s3:::lake", "prefix": "share/", "roleArn": ROLE})[0] == 409)
    _check("list + get", [x["fileSystemId"] for x in sf("GET", "/file-systems")[1]["fileSystems"]] == [fid] and sf("GET", f"/file-systems/{fid}")[0] == 200)
    _check("get missing 404", sf("GET", "/file-systems/fs-0000000000000000a")[0] == 404)

    # files are the bucket's objects
    _check("write file", sf("PUT", f"/file-systems/{fid}/file", {"content": "hello"}, {"path": "/docs/a.txt"})[0] == 200)
    _check("file is an S3 object", s3("GET", "/lake/share/docs/a.txt") == (200, b"hello"))
    s3("PUT", "/lake/share/docs/b.bin", body=b"\x00\x01")
    s, d = sf("GET", f"/file-systems/{fid}/files", query={"path": "/docs"})
    _check("list directory (S3-written file appears)", [(e["name"], e["type"]) for e in d["entries"]] == [("a.txt", "file"), ("b.bin", "file")])
    _check("root lists the docs directory", sf("GET", f"/file-systems/{fid}/files", query={"path": "/"})[1]["entries"] == [{"name": "docs", "type": "directory"}])
    s, g = sf("GET", f"/file-systems/{fid}/file", query={"path": "/docs/a.txt"})
    _check("read file", base64.b64decode(g["contentBase64"]) == b"hello")
    _check("mkdir", sf("POST", f"/file-systems/{fid}/directories", {"path": "/empty"})[0] == 201
           and {"name": "empty", "type": "directory"} in sf("GET", f"/file-systems/{fid}/files", query={"path": "/"})[1]["entries"])
    _check("path traversal rejected", sf("GET", f"/file-systems/{fid}/files", query={"path": "/../x"})[0] == 400)
    _check("delete file", sf("DELETE", f"/file-systems/{fid}/file", query={"path": "/docs/a.txt"})[0] == 204 and s3("GET", "/lake/share/docs/a.txt")[0] == 404)

    # mount targets / access points need real EC2 resources
    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", ec2("CreateVpc", CidrBlock="10.7.0.0/16")).group(1)
    sub = re.search(r"<subnetId>(subnet-\w+)</subnetId>", ec2("CreateSubnet", VpcId=vpc, CidrBlock="10.7.1.0/24", AvailabilityZone="us-east-1a")).group(1)
    sg = re.search(r"<groupId>(sg-\w+)</groupId>", ec2("CreateSecurityGroup", GroupName="nfs", GroupDescription="nfs", VpcId=vpc)).group(1)
    _check("mount target needs a real subnet", sf("POST", f"/file-systems/{fid}/mount-targets", {"subnetId": "subnet-nope"})[0] == 404)
    _check("mount target checks security groups", sf("POST", f"/file-systems/{fid}/mount-targets", {"subnetId": sub, "securityGroups": ["sg-nope"]})[0] == 400)
    s, t = sf("POST", f"/file-systems/{fid}/mount-targets", {"subnetId": sub, "securityGroups": [sg]})
    _check("create mount target", s == 201 and t["ipAddress"].startswith("10.7.1.") and t["availabilityZoneName"] == "us-east-1a")
    _check("one mount target per AZ", sf("POST", f"/file-systems/{fid}/mount-targets", {"subnetId": sub})[0] == 409)
    s, ap = sf("POST", f"/file-systems/{fid}/access-points", {"name": "etl", "posixUser": {"uid": 1000, "gid": 1000}, "rootDirectory": {"path": "/docs", "creationPermissions": {"ownerUid": 1000, "ownerGid": 1000, "permissions": "0755"}}})
    _check("create access point", s == 201 and ap["accessPointId"].startswith("fsap-"))
    _check("bad POSIX user 400", sf("POST", f"/file-systems/{fid}/access-points", {"posixUser": {"uid": "x", "gid": 1}})[0] == 400)
    _check("bad permissions 400", sf("POST", f"/file-systems/{fid}/access-points", {"rootDirectory": {"path": "/", "creationPermissions": {"permissions": "9"}}})[0] == 400)
    _check("delete blocked by mount target", sf("DELETE", f"/file-systems/{fid}")[0] == 409)
    pol = json.dumps({"Version": "2012-10-17", "Statement": []})
    _check("policy round-trip", sf("PUT", f"/file-systems/{fid}/policy", {"policy": pol})[0] == 200 and sf("GET", f"/file-systems/{fid}/policy")[1]["policy"] == pol
           and sf("DELETE", f"/file-systems/{fid}/policy")[0] == 204 and sf("GET", f"/file-systems/{fid}/policy")[0] == 404)
    _check("sync rules validated", sf("PUT", f"/file-systems/{fid}/synchronization-configuration", {"expirationDataRules": [{"daysAfterLastAccess": 0}]})[0] == 400
           and sf("PUT", f"/file-systems/{fid}/synchronization-configuration", {"importDataRules": [{"prefix": "", "trigger": "ON_FILE_ACCESS", "sizeLessThan": 1024}], "expirationDataRules": [{"daysAfterLastAccess": 30}]})[0] == 200
           and sf("GET", f"/file-systems/{fid}/synchronization-configuration")[1]["expirationDataRules"] == [{"daysAfterLastAccess": 30}])
    _check("delete mount target + access point", sf("DELETE", f"/mount-targets/{t['mountTargetId']}")[0] == 204 and sf("DELETE", f"/access-points/{ap['accessPointId']}")[0] == 204)
    _check("delete file system", sf("DELETE", f"/file-systems/{fid}")[0] == 204 and sf("GET", "/file-systems")[1]["fileSystems"] == [])

    # FSx for OpenZFS + S3 access point
    cfg = {"FileSystemType": "OPENZFS", "StorageCapacity": 64, "SubnetIds": [sub], "OpenZFSConfiguration": {"DeploymentType": "SINGLE_AZ_2", "ThroughputCapacity": 160}}
    _check("capacity validated", fsx("CreateFileSystem", {**cfg, "StorageCapacity": 10})[0] == 400)
    _check("subnet validated", fsx("CreateFileSystem", {**cfg, "SubnetIds": ["subnet-nope"]})[0] == 400)
    s, o = fsx("CreateFileSystem", cfg)
    fs = o["FileSystem"]
    root = fs["OpenZFSConfiguration"]["RootVolumeId"]
    _check("create FSx file system + root volume", s == 200 and fs["FileSystemId"].startswith("fs-") and root.startswith("fsvol-") and fs["VpcId"] == vpc)
    s, o = fsx("CreateVolume", {"VolumeType": "OPENZFS", "Name": "data", "OpenZFSConfiguration": {"ParentVolumeId": root}})
    vol = o["Volume"]["VolumeId"]
    _check("create child volume", s == 200 and o["Volume"]["OpenZFSConfiguration"]["VolumePath"] == "/data")
    _check("duplicate volume name 400", fsx("CreateVolume", {"VolumeType": "OPENZFS", "Name": "data", "OpenZFSConfiguration": {"ParentVolumeId": root}})[0] == 400)
    ident = {"Type": "POSIX", "PosixUser": {"Uid": 1001, "Gid": 1001}}
    att = {"Name": "ap-data", "Type": "OPENZFS", "OpenZFSConfiguration": {"VolumeId": vol, "FileSystemIdentity": ident}, "S3AccessPoint": {"VpcConfiguration": {"VpcId": vpc}}}
    _check("identity validated", fsx("CreateAndAttachS3AccessPoint", {**att, "OpenZFSConfiguration": {"VolumeId": vol, "FileSystemIdentity": {"Type": "WINDOWS"}}})[0] == 400)
    _check("volume must exist", fsx("CreateAndAttachS3AccessPoint", {**att, "OpenZFSConfiguration": {"VolumeId": "fsvol-nope", "FileSystemIdentity": ident}})[0] == 400)
    s, o = fsx("CreateAndAttachS3AccessPoint", att)
    a = o["S3AccessPointAttachment"]
    alias = a["S3AccessPoint"]["Alias"]
    _check("attach S3 access point", s == 200 and a["Lifecycle"] == "AVAILABLE" and alias.endswith("-ext-s3alias") and a["S3AccessPoint"]["ResourceARN"].endswith("accesspoint/ap-data"))
    _check("duplicate attachment name 400", fsx("CreateAndAttachS3AccessPoint", att)[0] == 400)
    _check("describe attachments", [x["Name"] for x in fsx("DescribeS3AccessPointAttachments", {"Filters": [{"Name": "volume-id", "Values": [vol]}]})[1]["S3AccessPointAttachments"]] == ["ap-data"])
    fsx("VyomiPutVolumeFile", {"VolumeId": vol, "Path": "/reports/q1.csv", "Content": "a,b\n1,2\n"})
    st, body = s3("GET", f"/{alias}", {"list-type": "2", "prefix": "reports/", "delimiter": "/"})
    _check("S3 list through the alias sees the volume file", st == 200 and b"reports/q1.csv" in body)
    _check("S3 get through the alias", s3("GET", f"/{alias}/reports/q1.csv") == (200, b"a,b\n1,2\n"))
    _check("S3 put through the alias lands in the volume", s3("PUT", f"/{alias}/reports/q2.csv", body=b"x")[0] == 200
           and sorted(f["Path"] for f in fsx("VyomiListVolumeFiles", {"VolumeId": vol})[1]["Files"]) == ["/reports/q1.csv", "/reports/q2.csv"])
    _check("S3 delete through the alias", s3("DELETE", f"/{alias}/reports/q2.csv")[0] == 204 and s3("GET", f"/{alias}/reports/q2.csv")[0] == 404)
    _check("delete volume blocked by attachment", fsx("DeleteVolume", {"VolumeId": vol})[0] == 400)
    _check("detach", fsx("DetachAndDeleteS3AccessPoint", {"Name": "ap-data"})[0] == 200 and fsx("DescribeS3AccessPointAttachments")[1]["S3AccessPointAttachments"] == [])
    _check("alias is gone after detach", s3("GET", f"/{alias}/reports/q1.csv")[0] == 404)
    _check("delete file system blocked by child volume", fsx("DeleteFileSystem", {"FileSystemId": fs["FileSystemId"]})[0] == 400)
    _check("delete volume then file system", fsx("DeleteVolume", {"VolumeId": vol})[0] == 200 and fsx("DeleteFileSystem", {"FileSystemId": fs["FileSystemId"]})[0] == 200
           and fsx("DescribeFileSystems")[1]["FileSystems"] == [])
    print("S3 Files + FSx access points core: all green")


if __name__ == "__main__":
    main()
