#!/usr/bin/env python3
"""AWS create-and-use regressions (sweep 2026-11-02): KMS, VPC, Lambda API shapes, via boto3.

  python3 sweep_aws.py http://localhost:9000      (needs boto3)
One [PASS]/[FAIL] line per check, exit 1 on any failure.
"""
import base64, io, json, sys, time, zipfile

import boto3
from botocore.exceptions import ClientError

E = (sys.argv[-1] if sys.argv[-1].startswith("http") else "http://localhost:9000").rstrip("/")
kw = dict(endpoint_url=E, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test")
fails = 0
tag = f"sw{int(time.time()) % 100000}"


def check(ok, name, why=""):
    global fails
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {why}"), flush=True)
    fails += 0 if ok else 1


def attempt(name, f):
    try:
        f()
    except Exception as e:
        check(False, name, f"{type(e).__name__}: {str(e)[:200]}")


def kms_checks():
    k = boto3.client("kms", **kw)
    kid = k.create_key(Description=f"{tag}")["KeyMetadata"]["KeyId"]
    try:
        dk = k.generate_data_key(KeyId=kid, KeySpec="AES_256")
        check(len(dk["Plaintext"]) == 32 and bool(dk["CiphertextBlob"]), "KMS generate_data_key via boto3 (32-byte plaintext + blob)")
        d = k.decrypt(CiphertextBlob=dk["CiphertextBlob"])
        check(d["Plaintext"] == dk["Plaintext"] and kid in d["KeyId"], "KMS decrypt of a data key WITHOUT KeyId returns the plaintext", repr(d.get("Plaintext"))[:60])
        e = k.encrypt(KeyId=kid, Plaintext=b"hello")["CiphertextBlob"]
        check(k.decrypt(CiphertextBlob=e)["Plaintext"] == b"hello", "KMS decrypt of encrypt() output without KeyId round-trips")
        try:
            k.decrypt(CiphertextBlob=b"not-a-real-ciphertext")
            check(False, "KMS decrypt of garbage ciphertext errors", "no error raised")
        except ClientError as ce:
            check(ce.response["Error"]["Code"] in ("InvalidCiphertextException", "NotFoundException"), "KMS decrypt of garbage ciphertext errors", str(ce)[:120])
    finally:
        try:
            k.schedule_key_deletion(KeyId=kid, PendingWindowInDays=7)
        except Exception:
            pass


def vpc_checks():
    ec2 = boto3.client("ec2", **kw)
    vpc = ec2.create_vpc(CidrBlock="10.77.0.0/16")["Vpc"]["VpcId"]
    sn = ec2.create_subnet(VpcId=vpc, CidrBlock="10.77.1.0/24")["Subnet"]["SubnetId"]
    sg = ec2.create_security_group(GroupName=f"{tag}-sg", Description="sweep", VpcId=vpc)["GroupId"]
    ec2.authorize_security_group_ingress(GroupId=sg, IpPermissions=[{"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}])
    try:
        ec2.delete_vpc(VpcId=vpc)
        check(False, "VPC delete refused while subnet/SG exist (DependencyViolation)", "delete_vpc succeeded")
    except ClientError as ce:
        check(ce.response["Error"]["Code"] == "DependencyViolation", "VPC delete refused while subnet/SG exist (DependencyViolation)", str(ce)[:160])
    try:
        ec2.delete_security_group(GroupId=sg)
        gone = not [g for g in ec2.describe_security_groups(Filters=[{"Name": "vpc-id", "Values": [vpc]}])["SecurityGroups"] if g["GroupId"] == sg]
        check(gone, "delete_security_group removes the group")
    except ClientError as ce:
        check(False, "delete_security_group removes the group", str(ce)[:160])
    ec2.delete_subnet(SubnetId=sn)
    try:
        ec2.delete_vpc(VpcId=vpc)
        left = [v for v in ec2.describe_vpcs()["Vpcs"] if v["VpcId"] == vpc]
        check(not left, "delete_vpc (after subnet/SG removed) succeeds and the VPC is gone")
    except ClientError as ce:
        check(False, "delete_vpc (after subnet/SG removed) succeeds and the VPC is gone", str(ce)[:160])


def main():
    attempt("vpc", vpc_checks)
    attempt("kms", kms_checks)
    sys.exit(1 if fails else 0)


main()
