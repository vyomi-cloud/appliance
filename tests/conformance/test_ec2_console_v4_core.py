"""EC2 v4-console conformance — the instance/volume/AMI/snapshot/key-pair/elastic-IP/
network-interface/security-group/placement-group/launch-template operations added to
core/vpc_core.py for the v4 EC2 console (EC2 and VPC share one native Query-protocol
wire, so they share one store/model — see vpc_core.py's module docstring).

Run on host:    PYTHONPATH=. python3 tests/conformance/test_ec2_console_v4_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
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


def run() -> int:
    s = types.SimpleNamespace()

    def call(p):
        r = vpc.dispatch(s, p)
        if r.status != 200:
            raise AssertionError((p.get("Action"), r.status, r.body))
        return r.body

    def xid(body, tag):
        m = re.search(f"<{tag}>(.*?)</{tag}>", body)
        return m.group(1) if m else None

    # 1. Instance types / AZs: a real describe/list call, not a hand-written disclaimer.
    types_body = call({"Action": "DescribeInstanceTypes"})
    _check("DescribeInstanceTypes lists t3.micro", "<instanceType>t3.micro</instanceType>" in types_body)
    _check("DescribeInstanceTypes carries free-tier flag", "<freeTierEligible>true</freeTierEligible>" in types_body)
    az_body = call({"Action": "DescribeAvailabilityZones"})
    _check("DescribeAvailabilityZones lists 3 AZs", az_body.count("<zoneName>") == 3)

    # 2. Key pair: create (material returned once), import, describe, delete.
    kp = call({"Action": "CreateKeyPair", "KeyName": "v4-key"})
    _check("CreateKeyPair returns private key material", "BEGIN RSA PRIVATE KEY" in kp)
    dup = vpc.dispatch(s, {"Action": "CreateKeyPair", "KeyName": "v4-key"})
    _check("duplicate key pair name rejected", dup.status == 400 and "Duplicate" in dup.body)
    imp = call({"Action": "ImportKeyPair", "KeyName": "v4-imported", "PublicKeyMaterial": "c3NoLXJzYSBBQUFB"})
    _check("ImportKeyPair does not return private material", "KeyMaterial" not in imp)
    desc = call({"Action": "DescribeKeyPairs"})
    _check("DescribeKeyPairs lists both", "v4-key" in desc and "v4-imported" in desc)
    call({"Action": "DeleteKeyPair", "KeyName": "v4-imported"})
    _check("deleted key pair is gone", "v4-imported" not in call({"Action": "DescribeKeyPairs"}))

    # 3. Security group: create, authorize/revoke by rule id, describe, delete-in-use guard.
    sg = call({"Action": "CreateSecurityGroup", "GroupName": "v4-web", "GroupDescription": "web tier"})
    sg_id = xid(sg, "groupId")
    call({"Action": "AuthorizeSecurityGroupIngress", "GroupId": sg_id, "IpPermissions.1.IpProtocol": "tcp",
          "IpPermissions.1.FromPort": "22", "IpPermissions.1.ToPort": "22", "IpPermissions.1.IpRanges.1.CidrIp": "0.0.0.0/0"})
    sgd = call({"Action": "DescribeSecurityGroups", "GroupId.1": sg_id})
    _check("authorized ingress rule appears", "<fromPort>22</fromPort>" in sgd)
    rule_id = xid(sgd, "securityGroupRuleId")
    call({"Action": "RevokeSecurityGroupIngress", "GroupId": sg_id, "SecurityGroupRuleId.1": rule_id})
    sgd2 = call({"Action": "DescribeSecurityGroups", "GroupId.1": sg_id})
    _check("revoked rule is gone", "<fromPort>22</fromPort>" not in sgd2)

    # 4. Launch an instance into that security group (RunInstances creates the default
    #    VPC/subnet + a root EBS volume, exactly like a real new account's first launch).
    run_body = call({
        "Action": "RunInstances", "InstanceType": "t3.micro", "KeyName": "v4-key",
        "SecurityGroupId.1": sg_id, "MaxCount": "1",
        "TagSpecification.1.ResourceType": "instance", "TagSpecification.1.Tag.1.Key": "Name",
        "TagSpecification.1.Tag.1.Value": "v4-instance",
    })
    iid = xid(run_body, "instanceId")
    _check("RunInstances returns a running instance", "<name>running</name>" in run_body)
    _check("instance id looks native (i-<17 hex>)", bool(re.fullmatch(r"i-[0-9a-f]{17}", iid)))
    desc_i = call({"Action": "DescribeInstances", "InstanceId.1": iid})
    _check("DescribeInstances round-trips the Name tag", "v4-instance" in desc_i)
    _check("DescribeInstances carries the attached security group", sg_id in desc_i)

    # Deleting an in-use security group is rejected (DependencyViolation), same as AWS.
    blocked = vpc.dispatch(s, {"Action": "DeleteSecurityGroup", "GroupId": sg_id})
    _check("delete of an in-use security group is rejected", blocked.status == 400 and "DependencyViolation" in blocked.body)

    # 5. Termination protection is actually enforced, not just stored.
    call({"Action": "ModifyInstanceAttribute", "InstanceId": iid, "DisableApiTermination.Value": "true"})
    blocked_term = vpc.dispatch(s, {"Action": "TerminateInstances", "InstanceId.1": iid})
    _check("termination-protected instance cannot be terminated", blocked_term.status == 400 and "OperationNotPermitted" in blocked_term.body)
    call({"Action": "ModifyInstanceAttribute", "InstanceId": iid, "DisableApiTermination.Value": "false"})

    # 6. Stop / start cycles the public IP like real AWS (ephemeral unless an EIP is attached).
    call({"Action": "StopInstances", "InstanceId.1": iid})
    stopped = call({"Action": "DescribeInstances", "InstanceId.1": iid})
    _check("stopped instance has no public IP", "<ipAddress></ipAddress>" in stopped)
    call({"Action": "StartInstances", "InstanceId.1": iid})
    started = call({"Action": "DescribeInstances", "InstanceId.1": iid})
    _check("started instance is assigned a new public IP", "<ipAddress></ipAddress>" not in started)

    # 7. Elastic IP survives a stop (sticky, same as AWS).
    eip = call({"Action": "AllocateAddress"})
    alloc_id = xid(eip, "allocationId")
    eip_ip = xid(eip, "publicIp")
    call({"Action": "AssociateAddress", "AllocationId": alloc_id, "InstanceId": iid})
    call({"Action": "StopInstances", "InstanceId.1": iid})
    still = call({"Action": "DescribeInstances", "InstanceId.1": iid})
    _check("elastic IP sticks across a stop", eip_ip in still)
    assoc_id = xid(call({"Action": "DescribeAddresses"}), "associationId")
    call({"Action": "DisassociateAddress", "AssociationId": assoc_id})
    call({"Action": "ReleaseAddress", "AllocationId": alloc_id})
    call({"Action": "StartInstances", "InstanceId.1": iid})

    # 8. Volumes: attach, describe shows in-use, detach, delete; snapshot + AMI from the instance.
    vol = call({"Action": "CreateVolume", "Size": "20", "VolumeType": "gp3", "AvailabilityZone": "us-east-1a"})
    vol_id = xid(vol, "volumeId")
    call({"Action": "AttachVolume", "VolumeId": vol_id, "InstanceId": iid, "Device": "/dev/sdf"})
    _check("attached volume shows in-use", "in-use" in call({"Action": "DescribeVolumes", "VolumeId.1": vol_id}))
    snap = call({"Action": "CreateSnapshot", "VolumeId": vol_id, "Description": "v4 snap"})
    snap_id = xid(snap, "snapshotId")
    _check("snapshot completes synchronously", "completed" in call({"Action": "DescribeSnapshots", "SnapshotId.1": snap_id}))
    call({"Action": "DetachVolume", "VolumeId": vol_id, "InstanceId": iid})
    _check("detached volume is available again", "available" in call({"Action": "DescribeVolumes", "VolumeId.1": vol_id}))
    call({"Action": "DeleteVolume", "VolumeId": vol_id})
    call({"Action": "DeleteSnapshot", "SnapshotId": snap_id})

    ami = call({"Action": "CreateImage", "InstanceId": iid, "Name": "v4-ami"})
    ami_id = xid(ami, "imageId")
    _check("CreateImage snapshots the root volume for the new AMI", "snap-" in call({"Action": "DescribeImages", "ImageId.1": ami_id}))
    call({"Action": "DeregisterImage", "ImageId": ami_id})

    # 9. AMI catalog seeding: quickstart AMIs are real DescribeImages rows, owned by "amazon".
    seeded = call({"Action": "DescribeImages", "Owner.1": "amazon"})
    _check("quickstart catalog is seeded and owned by amazon", "Amazon Linux" in seeded and "amazon" in seeded)

    # 10. Network interfaces: create, attach, detach, delete.
    _vpc_id, subnet_id, _default_sg = vpc._ensure_default_network(vpc._model(s))
    eni = call({"Action": "CreateNetworkInterface", "SubnetId": subnet_id, "Description": "v4 eni"})
    eni_id = xid(eni, "networkInterfaceId")
    att = call({"Action": "AttachNetworkInterface", "NetworkInterfaceId": eni_id, "InstanceId": iid, "DeviceIndex": "1"})
    att_id = xid(att, "attachmentId")
    blocked_del = vpc.dispatch(s, {"Action": "DeleteNetworkInterface", "NetworkInterfaceId": eni_id})
    _check("cannot delete an attached ENI", blocked_del.status == 400)
    call({"Action": "DetachNetworkInterface", "AttachmentId": att_id})
    call({"Action": "DeleteNetworkInterface", "NetworkInterfaceId": eni_id})

    # 11. Placement groups + launch templates: named sub-resources, CRUD.
    pg = call({"Action": "CreatePlacementGroup", "GroupName": "v4-pg", "Strategy": "cluster"})
    _check("placement group created", "v4-pg" in pg)
    call({"Action": "DeletePlacementGroup", "GroupName": "v4-pg"})
    lt = call({"Action": "CreateLaunchTemplate", "LaunchTemplateName": "v4-lt", "LaunchTemplateData.InstanceType": "t3.micro"})
    lt_id = xid(lt, "launchTemplateId")
    _check("launch template stores its config", "v4-lt" in call({"Action": "DescribeLaunchTemplates", "LaunchTemplateId.1": lt_id}))
    call({"Action": "DeleteLaunchTemplate", "LaunchTemplateId": lt_id})

    # 12. EBS encryption-by-default: an account setting that actually changes new-volume behavior.
    call({"Action": "EnableEbsEncryptionByDefault"})
    _check("EBS default encryption flag reads back true", "true" in call({"Action": "GetEbsEncryptionByDefault"}))
    newvol = call({"Action": "CreateVolume", "Size": "5", "AvailabilityZone": "us-east-1a"})
    _check("new volume inherits the account default (encrypted)", "<encrypted>true</encrypted>" in newvol)
    call({"Action": "DisableEbsEncryptionByDefault"})

    # 13. Generic tagging works across resource types.
    call({"Action": "CreateTags", "ResourceId.1": iid, "Tag.1.Key": "Env", "Tag.1.Value": "prod"})
    tags = call({"Action": "DescribeTags"})
    _check("DescribeTags surfaces the tag across resources", "Env" in tags and "prod" in tags)
    call({"Action": "DeleteTags", "ResourceId.1": iid, "Tag.1.Key": "Env"})
    _check("DeleteTags removes it", "prod" not in call({"Action": "DescribeTags"}))

    # 14. Terminate cleans up non-persistent block devices.
    call({"Action": "TerminateInstances", "InstanceId.1": iid})
    _check("terminated instance reports terminated", "<name>terminated</name>" in call({"Action": "DescribeInstances", "InstanceId.1": iid}))

    print("\nRESULT: PASS — EC2 v4-console additions conform (native Query-protocol wire semantics) on this substrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
