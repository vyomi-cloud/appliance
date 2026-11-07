"""EC2 wire gaps closed by core/ec2_gap_core.py — driven by REAL boto3 clients whose transport is the Nano/offline
AwsWireRouter (tests/conformance/_wire_boto.py). Each op reads/writes the shared EC2 model, so the assertions
cross-check state through *other* operations (not just the call's own response)."""
import os
import sys

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(__file__))
from _wire_boto import make_clients  # noqa: E402


@pytest.fixture()
def ec2():
    _, client = make_clients()
    return client("ec2")


def _launch(ec2, **kw):
    return ec2.run_instances(MaxCount=1, MinCount=1, InstanceType="t3.micro", **kw)["Instances"][0]


def _img(ec2):
    return ec2.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]


def test_instance_attributes(ec2):
    i = _launch(ec2, ImageId=_img(ec2))
    iid = i["InstanceId"]
    ec2.modify_instance_attribute(InstanceId=iid, DisableApiTermination={"Value": True})
    assert ec2.describe_instance_attribute(InstanceId=iid, Attribute="disableApiTermination")["DisableApiTermination"]["Value"] is True
    assert ec2.describe_instance_attribute(InstanceId=iid, Attribute="instanceType")["InstanceType"]["Value"] == "t3.micro"
    ec2.modify_instance_attribute(InstanceId=iid, SourceDestCheck={"Value": False})
    ec2.reset_instance_attribute(InstanceId=iid, Attribute="sourceDestCheck")
    assert ec2.describe_instance_attribute(InstanceId=iid, Attribute="sourceDestCheck")["SourceDestCheck"]["Value"] is True
    md = ec2.modify_instance_metadata_options(InstanceId=iid, HttpTokens="optional", HttpPutResponseHopLimit=3)
    assert md["InstanceMetadataOptions"]["HttpTokens"] == "optional"
    assert ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]["MetadataOptions"]["HttpTokens"] == "optional"
    cs = ec2.modify_instance_credit_specification(InstanceCreditSpecifications=[{"InstanceId": iid, "CpuCredits": "unlimited"}])
    assert cs["SuccessfulInstanceCreditSpecifications"][0]["InstanceId"] == iid
    assert ec2.describe_instance_credit_specifications(InstanceIds=[iid])["InstanceCreditSpecifications"][0]["CpuCredits"] == "unlimited"
    off = ec2.describe_instance_type_offerings(Filters=[{"Name": "instance-type", "Values": ["t3.*"]}])["InstanceTypeOfferings"]
    assert off and all(o["InstanceType"].startswith("t3.") for o in off)
    lt = ec2.get_launch_template_data(InstanceId=iid)["LaunchTemplateData"]
    assert lt["InstanceType"] == "t3.micro" and lt["ImageId"] == i["ImageId"]
    ec2.modify_instance_metadata_defaults(HttpTokens="required")
    assert ec2.get_instance_metadata_defaults()["AccountLevel"]["HttpTokens"] == "required"
    ec2.register_instance_event_notification_attributes(InstanceTagAttribute={"IncludeAllTagsOfInstance": True})
    assert ec2.describe_instance_event_notification_attributes()["InstanceTagAttribute"]["IncludeAllTagsOfInstance"] is True
    with pytest.raises(ClientError) as e:
        ec2.describe_instance_attribute(InstanceId="i-0000000000000000a", Attribute="instanceType")
    assert e.value.response["Error"]["Code"] == "InvalidInstanceID.NotFound"


def test_volume_snapshot_image_lifecycle(ec2):
    i = _launch(ec2, ImageId=_img(ec2))
    iid = i["InstanceId"]
    vol = ec2.create_volume(AvailabilityZone="us-east-1a", Size=10, VolumeType="gp3")["VolumeId"]
    ec2.attach_volume(VolumeId=vol, InstanceId=iid, Device="/dev/sdf")
    ec2.modify_volume(VolumeId=vol, Size=20)
    mods = ec2.describe_volumes_modifications(VolumeIds=[vol])["VolumesModifications"]
    assert mods[0]["OriginalSize"] == 10 and mods[0]["TargetSize"] == 20
    ec2.modify_volume_attribute(VolumeId=vol, AutoEnableIO={"Value": True})
    assert ec2.describe_volume_attribute(VolumeId=vol, Attribute="autoEnableIO")["AutoEnableIO"]["Value"] is True
    assert ec2.describe_volume_status(VolumeIds=[vol])["VolumeStatuses"][0]["VolumeStatus"]["Status"] == "ok"
    ec2.enable_volume_io(VolumeId=vol)

    snap = ec2.create_snapshot(VolumeId=vol)["SnapshotId"]
    ec2.modify_snapshot_attribute(SnapshotId=snap, Attribute="createVolumePermission", OperationType="add", UserIds=["111122223333"])
    perm = ec2.describe_snapshot_attribute(SnapshotId=snap, Attribute="createVolumePermission")["CreateVolumePermissions"]
    assert perm == [{"UserId": "111122223333"}]
    ec2.reset_snapshot_attribute(SnapshotId=snap, Attribute="createVolumePermission")
    assert ec2.describe_snapshot_attribute(SnapshotId=snap, Attribute="createVolumePermission")["CreateVolumePermissions"] == []
    multi = ec2.create_snapshots(InstanceSpecification={"InstanceId": iid})["Snapshots"]
    assert len(multi) >= 2   # root + the attached data volume
    assert {s["SnapshotId"] for s in multi} <= {s["SnapshotId"] for s in ec2.describe_snapshots(OwnerIds=["self"])["Snapshots"]}

    ec2.lock_snapshot(SnapshotId=snap, LockMode="compliance", CoolOffPeriod=1, LockDuration=1)
    assert snap in [s["SnapshotId"] for s in ec2.describe_locked_snapshots()["Snapshots"]]
    with pytest.raises(ClientError) as e:
        ec2.delete_snapshot(SnapshotId=snap)
    assert e.value.response["Error"]["Code"] == "OperationNotPermitted"
    with pytest.raises(ClientError):
        ec2.unlock_snapshot(SnapshotId=snap)
    ec2.enable_fast_snapshot_restores(AvailabilityZones=["us-east-1a"], SourceSnapshotIds=[multi[0]["SnapshotId"]])
    assert ec2.describe_fast_snapshot_restores()["FastSnapshotRestores"][0]["State"] == "enabled"
    assert ec2.enable_snapshot_block_public_access(State="block-all-sharing")["State"] == "block-all-sharing"
    assert ec2.get_snapshot_block_public_access_state()["State"] == "block-all-sharing"

    # RegisterImage from a snapshot -> usable AMI -> launchable, attribute + lifecycle flags
    ami = ec2.register_image(Name="gap-ami", RootDeviceName="/dev/xvda", VirtualizationType="hvm",
                             BlockDeviceMappings=[{"DeviceName": "/dev/xvda", "Ebs": {"SnapshotId": multi[0]["SnapshotId"]}}])["ImageId"]
    assert ec2.describe_images(ImageIds=[ami])["Images"][0]["Name"] == "gap-ami"
    ec2.modify_image_attribute(ImageId=ami, LaunchPermission={"Add": [{"UserId": "444455556666"}]})
    assert ec2.describe_image_attribute(ImageId=ami, Attribute="launchPermission")["LaunchPermissions"] == [{"UserId": "444455556666"}]
    ec2.reset_image_attribute(ImageId=ami, Attribute="launchPermission")
    assert ec2.describe_image_attribute(ImageId=ami, Attribute="launchPermission")["LaunchPermissions"] == []
    ec2.enable_image_deregistration_protection(ImageId=ami)
    with pytest.raises(ClientError) as e:
        ec2.deregister_image(ImageId=ami)
    assert e.value.response["Error"]["Code"] == "OperationNotPermitted"
    ec2.disable_image_deregistration_protection(ImageId=ami)
    ec2.disable_image(ImageId=ami)
    assert ec2.describe_images(ImageIds=[ami])["Images"][0]["State"] == "disabled"
    ec2.enable_image(ImageId=ami)
    ec2.deregister_image(ImageId=ami)
    with pytest.raises(ClientError) as e:
        ec2.register_image(Name="gap-ami2", BlockDeviceMappings=[{"DeviceName": "/dev/xvda", "Ebs": {"SnapshotId": "snap-nope"}}])
    assert e.value.response["Error"]["Code"] == "InvalidSnapshot.NotFound"


def test_eni_iam_profile_routes_and_endpoints(ec2):
    vpc = ec2.create_vpc(CidrBlock="10.7.0.0/16")["Vpc"]["VpcId"]
    sn = ec2.create_subnet(VpcId=vpc, CidrBlock="10.7.1.0/24")["Subnet"]["SubnetId"]
    eni = ec2.create_network_interface(SubnetId=sn)["NetworkInterface"]["NetworkInterfaceId"]
    a = ec2.assign_private_ip_addresses(NetworkInterfaceId=eni, SecondaryPrivateIpAddressCount=2)["AssignedPrivateIpAddresses"]
    assert len(a) == 2
    ec2.unassign_private_ip_addresses(NetworkInterfaceId=eni, PrivateIpAddresses=[a[0]["PrivateIpAddress"]])
    assert len(ec2.assign_ipv6_addresses(NetworkInterfaceId=eni, Ipv6AddressCount=1)["AssignedIpv6Addresses"]) == 1
    assert ec2.describe_network_interface_attribute(NetworkInterfaceId=eni, Attribute="sourceDestCheck")["SourceDestCheck"]["Value"] is True
    ec2.reset_network_interface_attribute(NetworkInterfaceId=eni, SourceDestCheck="true")
    perm = ec2.create_network_interface_permission(NetworkInterfaceId=eni, AwsAccountId="999988887777", Permission="INSTANCE-ATTACH")["InterfacePermission"]
    assert ec2.describe_network_interface_permissions()["NetworkInterfacePermissions"][0]["NetworkInterfacePermissionId"] == perm["NetworkInterfacePermissionId"]
    ec2.delete_network_interface_permission(NetworkInterfacePermissionId=perm["NetworkInterfacePermissionId"])
    assert ec2.describe_network_interface_permissions()["NetworkInterfacePermissions"] == []

    i = _launch(ec2, ImageId=_img(ec2), SubnetId=sn)
    iid = i["InstanceId"]
    assoc = ec2.associate_iam_instance_profile(InstanceId=iid, IamInstanceProfile={"Name": "web-profile"})["IamInstanceProfileAssociation"]
    assert assoc["State"] == "associated"
    got = ec2.describe_iam_instance_profile_associations(Filters=[{"Name": "instance-id", "Values": [iid]}])["IamInstanceProfileAssociations"]
    assert got[0]["IamInstanceProfile"]["Arn"].endswith("instance-profile/web-profile")
    assert ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]["IamInstanceProfile"]["Arn"].endswith("web-profile")
    ec2.replace_iam_instance_profile_association(AssociationId=assoc["AssociationId"], IamInstanceProfile={"Name": "other"})
    ec2.disassociate_iam_instance_profile(AssociationId=assoc["AssociationId"])
    assert ec2.describe_iam_instance_profile_associations(Filters=[{"Name": "instance-id", "Values": [iid]}])["IamInstanceProfileAssociations"] == []

    rt = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    igw = ec2.create_internet_gateway()["InternetGateway"]["InternetGatewayId"]
    ec2.attach_internet_gateway(InternetGatewayId=igw, VpcId=vpc)
    ec2.create_route(RouteTableId=rt, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw)
    nat_eni = ec2.create_network_interface(SubnetId=sn)["NetworkInterface"]["NetworkInterfaceId"]
    ec2.replace_route(RouteTableId=rt, DestinationCidrBlock="0.0.0.0/0", NetworkInterfaceId=nat_eni)
    routes = {r["DestinationCidrBlock"]: r for r in ec2.describe_route_tables(RouteTableIds=[rt])["RouteTables"][0]["Routes"] if "DestinationCidrBlock" in r}
    assert routes["0.0.0.0/0"]["NetworkInterfaceId"] == nat_eni
    with pytest.raises(ClientError):
        ec2.replace_route(RouteTableId=rt, DestinationCidrBlock="9.9.9.0/24", GatewayId=igw)

    ep = ec2.create_vpc_endpoint(VpcId=vpc, ServiceName="com.amazonaws.us-east-1.s3", RouteTableIds=[rt])["VpcEndpoint"]["VpcEndpointId"]
    rt2 = ec2.create_route_table(VpcId=vpc)["RouteTable"]["RouteTableId"]
    ec2.modify_vpc_endpoint(VpcEndpointId=ep, AddRouteTableIds=[rt2])
    assert set(ec2.describe_vpc_endpoints(VpcEndpointIds=[ep])["VpcEndpoints"][0]["RouteTableIds"]) == {rt, rt2}
    names = ec2.describe_vpc_endpoint_services()["ServiceNames"]
    assert "com.amazonaws.us-east-1.s3" in names


def test_fleets_launch_real_instances(ec2):
    lt = ec2.create_launch_template(LaunchTemplateName="gap-lt", LaunchTemplateData={"ImageId": _img(ec2), "InstanceType": "t3.small"})["LaunchTemplate"]
    v2 = ec2.create_launch_template_version(LaunchTemplateName="gap-lt", SourceVersion="1", LaunchTemplateData={"InstanceType": "t3.medium"})
    assert v2["LaunchTemplateVersion"]["VersionNumber"] == 2
    ec2.delete_launch_template_versions(LaunchTemplateName="gap-lt", Versions=["2"])
    assert [v["VersionNumber"] for v in ec2.describe_launch_template_versions(LaunchTemplateName="gap-lt")["LaunchTemplateVersions"]] == [1]
    r = ec2.delete_launch_template_versions(LaunchTemplateName="gap-lt", Versions=["1"])   # default version can't be deleted
    assert r["UnsuccessfullyDeletedLaunchTemplateVersions"]

    fl = ec2.create_fleet(Type="instant", LaunchTemplateConfigs=[{"LaunchTemplateSpecification": {"LaunchTemplateId": lt["LaunchTemplateId"], "Version": "$Default"}}],
                          TargetCapacitySpecification={"TotalTargetCapacity": 2, "DefaultTargetCapacityType": "on-demand"})
    ids = [x for g in fl["Instances"] for x in g["InstanceIds"]]
    assert len(ids) == 2
    live = ec2.describe_instances(InstanceIds=ids)["Reservations"]
    assert sum(len(r["Instances"]) for r in live) == 2 and live[0]["Instances"][0]["InstanceType"] == "t3.small"
    assert ec2.describe_fleets(FleetIds=[fl["FleetId"]])["Fleets"][0]["FulfilledCapacity"] == 2.0
    assert len(ec2.describe_fleet_instances(FleetId=fl["FleetId"])["ActiveInstances"]) == 2
    d = ec2.delete_fleets(FleetIds=[fl["FleetId"]], TerminateInstances=True)
    assert d["SuccessfulFleetDeletions"][0]["CurrentFleetState"] == "deleted_terminating"
    states = {i["State"]["Name"] for r in ec2.describe_instances(InstanceIds=ids)["Reservations"] for i in r["Instances"]}
    assert states <= {"shutting-down", "terminated"}

    sf = ec2.request_spot_fleet(SpotFleetRequestConfig={"IamFleetRole": "arn:aws:iam::123456789012:role/f", "TargetCapacity": 1, "AllocationStrategy": "lowestPrice",
                                "LaunchSpecifications": [{"ImageId": _img(ec2), "InstanceType": "t3.micro"}]})["SpotFleetRequestId"]
    inst = ec2.describe_spot_fleet_instances(SpotFleetRequestId=sf)["ActiveInstances"]
    assert len(inst) == 1
    assert ec2.describe_spot_fleet_requests(SpotFleetRequestIds=[sf])["SpotFleetRequestConfigs"][0]["SpotFleetRequestState"] == "active"
    ec2.cancel_spot_fleet_requests(SpotFleetRequestIds=[sf], TerminateInstances=True)
    assert ec2.describe_spot_fleet_requests(SpotFleetRequestIds=[sf])["SpotFleetRequestConfigs"][0]["SpotFleetRequestState"] == "cancelled_terminating"
    ec2.create_spot_datafeed_subscription(Bucket="spot-feed")
    assert ec2.describe_spot_datafeed_subscription()["SpotDatafeedSubscription"]["Bucket"] == "spot-feed"
    ec2.delete_spot_datafeed_subscription()


def test_instance_connect_endpoint_event_windows_addresses(ec2):
    vpc = ec2.create_vpc(CidrBlock="10.8.0.0/16")["Vpc"]["VpcId"]
    sn = ec2.create_subnet(VpcId=vpc, CidrBlock="10.8.1.0/24")["Subnet"]["SubnetId"]
    e = ec2.create_instance_connect_endpoint(SubnetId=sn)["InstanceConnectEndpoint"]
    got = ec2.describe_instance_connect_endpoints(InstanceConnectEndpointIds=[e["InstanceConnectEndpointId"]])["InstanceConnectEndpoints"][0]
    assert got["VpcId"] == vpc and got["NetworkInterfaceIds"]
    assert got["NetworkInterfaceIds"][0] in [n["NetworkInterfaceId"] for n in ec2.describe_network_interfaces()["NetworkInterfaces"]]
    ec2.delete_instance_connect_endpoint(InstanceConnectEndpointId=e["InstanceConnectEndpointId"])
    assert ec2.describe_instance_connect_endpoints()["InstanceConnectEndpoints"] == []

    iid = _launch(ec2, ImageId=_img(ec2))["InstanceId"]
    w = ec2.create_instance_event_window(Name="maint", CronExpression="* 21-23 * * 2,3")["InstanceEventWindow"]["InstanceEventWindowId"]
    ec2.associate_instance_event_window(InstanceEventWindowId=w, AssociationTarget={"InstanceIds": [iid]})
    assert ec2.describe_instance_event_windows()["InstanceEventWindows"][0]["AssociationTarget"]["InstanceIds"] == [iid]
    ec2.delete_instance_event_window(InstanceEventWindowId=w)

    alloc = ec2.allocate_address(Domain="vpc")["AllocationId"]
    ec2.modify_address_attribute(AllocationId=alloc, DomainName="host.example.com")
    assert ec2.describe_addresses_attribute(AllocationIds=[alloc])["Addresses"][0]["PtrRecord"] == "host.example.com"
    ec2.reset_address_attribute(AllocationId=alloc, Attribute="domain-name")
