"""vyomi-endurance regressions found by running real Terraform providers against the simulator (tests/endurance/FINDINGS.md).

F1  EC2 DescribeVpcAttribute answers enableNetworkAddressUsageMetrics under its own tag (aws provider 5.x reads it for every VPC).
F2  SQS GetQueueAttributes reports SqsManagedSseEnabled=true by default (provider polls until it appears); verified end to end by the Terraform spike (SQS create 26 s -> instant).
F4  GCP compute network carries networkFirewallPolicyEnforcementOrder=AFTER_CLASSIC_FIREWALL (provider otherwise plans an update forever).
"""
import re
import types

try:
    from core import vpc_core as v
    from core import gcp_compute_core as gc
    from core import sqs_core as sq
except ImportError:  # pragma: no cover
    import vpc_core as v; import gcp_compute_core as gc; import sqs_core as sq  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def _f1():
    s = types.SimpleNamespace()
    call = lambda **p: v.dispatch(s, p)  # noqa: E731
    body = lambda r: r.body.decode() if isinstance(r.body, bytes) else r.body  # noqa: E731
    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", body(call(Action="CreateVpc", CidrBlock="10.9.0.0/16"))).group(1)
    for attr, want in (("enableNetworkAddressUsageMetrics", "false"), ("enableDnsSupport", "true"), ("enableDnsHostnames", "false")):
        out = body(call(Action="DescribeVpcAttribute", VpcId=vpc, Attribute=attr))
        _check(f"F1 {attr} default", re.search(rf"<{attr}><value>{want}</value></{attr}>", out) is not None)
    call(Action="ModifyVpcAttribute", VpcId=vpc, **{"EnableNetworkAddressUsageMetrics.Value": "true"})
    out = body(call(Action="DescribeVpcAttribute", VpcId=vpc, Attribute="enableNetworkAddressUsageMetrics"))
    _check("F1 modify then describe", "<value>true</value>" in out)
    r = call(Action="DescribeVpcAttribute", VpcId=vpc, Attribute="bogus")
    _check("F1 unknown attribute is an InvalidParameterValue error", "InvalidParameterValue" in body(r) and r.status >= 400)


def _f4():
    rec = {"id": "1", "project": "p", "name": "n", "creationTimestamp": "t", "_subnets": []}
    _check("F4 default enforcement order", gc._network_view(rec)["networkFirewallPolicyEnforcementOrder"] == "AFTER_CLASSIC_FIREWALL")
    rec["networkFirewallPolicyEnforcementOrder"] = "BEFORE_CLASSIC_FIREWALL"
    _check("F4 honours explicit value", gc._network_view(rec)["networkFirewallPolicyEnforcementOrder"] == "BEFORE_CLASSIC_FIREWALL")


def _f6_f7():
    s = types.SimpleNamespace()
    call = lambda **p: v.dispatch(s, p)  # noqa: E731
    body = lambda r: r.body.decode() if isinstance(r.body, bytes) else r.body  # noqa: E731
    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", body(call(Action="CreateVpc", CidrBlock="10.8.0.0/16"))).group(1)
    sub = re.search(r"<subnetId>(subnet-\w+)</subnetId>", body(call(Action="CreateSubnet", VpcId=vpc, CidrBlock="10.8.1.0/24"))).group(1)
    acl = re.search(r"<networkAclId>(acl-\w+)</networkAclId>", body(call(Action="CreateNetworkAcl", VpcId=vpc))).group(1)
    other = re.search(r"<networkAclId>(acl-\w+)</networkAclId>", body(call(Action="CreateNetworkAcl", VpcId=vpc))).group(1)
    call(Action="ReplaceNetworkAclAssociation", AssociationId=f"aclassoc-{sub}", NetworkAclId=acl)
    out = body(call(Action="DescribeNetworkAcls", **{"Filter.1.Name": "association.subnet-id", "Filter.1.Value.1": sub}))
    ids = re.findall(r"<networkAclId>(acl-\w+)</networkAclId>", out)
    _check("F6 association.subnet-id filter returns exactly the associated ACL", set(ids) == {acl})
    out = body(call(Action="DescribeNetworkAcls", **{"Filter.1.Name": "vpc-id", "Filter.1.Value.1": vpc}))
    _check("F6 vpc-id filter", acl in out and other in out)
    r = call(Action="DescribeNetworkAcls", **{"Filter.1.Name": "no-such-filter", "Filter.1.Value.1": "x"})
    _check("F6 unknown filter is an error", r.status >= 400)

    pl = re.search(r"<prefixListId>(pl-\w+)</prefixListId>", body(call(Action="CreateManagedPrefixList", PrefixListName="office",
                   AddressFamily="IPv4", MaxEntries="3", **{"Entry.1.Cidr": "203.0.113.0/24", "Entry.1.Description": "hq"}))).group(1)
    out = body(call(Action="GetManagedPrefixListEntries", PrefixListId=pl))
    _check("F7 GetManagedPrefixListEntries", "203.0.113.0/24" in out and "hq" in out)
    out = body(call(Action="ModifyManagedPrefixList", PrefixListId=pl, CurrentVersion="1", **{"AddEntry.1.Cidr": "198.51.100.0/24"}))
    _check("F7 modify bumps version", "<version>2</version>" in out)
    out = body(call(Action="GetManagedPrefixListEntries", PrefixListId=pl))
    _check("F7 entries after modify", "198.51.100.0/24" in out and "203.0.113.0/24" in out)
    r = call(Action="ModifyManagedPrefixList", PrefixListId=pl, CurrentVersion="1", **{"AddEntry.1.Cidr": "192.0.2.0/24"})
    _check("F7 stale CurrentVersion is rejected", r.status >= 400)
    out = body(call(Action="DescribeManagedPrefixLists", **{"Filter.1.Name": "prefix-list-name", "Filter.1.Value.1": "office"}))
    _check("F7 describe by name filter", pl in out)


def _f8():
    s = types.SimpleNamespace()
    call = lambda **p: v.dispatch(s, p)  # noqa: E731
    body = lambda r: r.body.decode() if isinstance(r.body, bytes) else r.body  # noqa: E731
    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", body(call(Action="CreateVpc", CidrBlock="10.7.0.0/16"))).group(1)
    sg = re.search(r"<groupId>(sg-\w+)</groupId>", body(call(Action="CreateSecurityGroup", VpcId=vpc, GroupName="g", GroupDescription="d"))).group(1)
    out = body(call(Action="AuthorizeSecurityGroupIngress", GroupId=sg, **{
        "IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "443", "IpPermissions.1.ToPort": "443",
        "IpPermissions.1.IpRanges.1.CidrIp": "0.0.0.0/0", "IpPermissions.1.IpRanges.1.Description": "https"}))
    ids = re.findall(r"<securityGroupRuleId>(sgr-\w+)</securityGroupRuleId>", out)
    _check("F8 authorize returns the created rule with an sgr id", len(ids) == 1 and "<cidrIpv4>0.0.0.0/0</cidrIpv4>" in out and "<fromPort>443</fromPort>" in out)
    d = body(call(Action="DescribeSecurityGroupRules", **{"SecurityGroupRuleId.1": ids[0]}))
    _check("F8 DescribeSecurityGroupRules by id", ids[0] in d and "<isEgress>false</isEgress>" in d and "<description>https</description>" in d)
    d = body(call(Action="DescribeSecurityGroupRules", **{"Filter.1.Name": "group-id", "Filter.1.Value.1": sg}))
    _check("F8 group-id filter includes the default egress rule too", d.count("<securityGroupRuleId>") == 2 and "<isEgress>true</isEgress>" in d)
    d0 = body(call(Action="AuthorizeSecurityGroupEgress", GroupId=sg, **{"IpPermissions.1.IpProtocol": "udp", "IpPermissions.1.FromPort": "53",
         "IpPermissions.1.ToPort": "53", "IpPermissions.1.IpRanges.1.CidrIp": "10.0.0.0/8"}))
    _check("F14 a rule without a description has NO <description> element (provider would see '' vs null forever)", "<description>" not in d0)
    call(Action="ModifySecurityGroupRules", GroupId=sg, **{"SecurityGroupRule.1.SecurityGroupRuleId": ids[0],
         "SecurityGroupRule.1.SecurityGroupRule.Description": "changed"})
    _check("F8 modify description", "<description>changed</description>" in body(call(Action="DescribeSecurityGroupRules", **{"SecurityGroupRuleId.1": ids[0]})))
    r = call(Action="AuthorizeSecurityGroupIngress", GroupId=sg, **{"IpPermissions.1.IpProtocol": "tcp", "IpPermissions.1.FromPort": "443",
         "IpPermissions.1.ToPort": "443", "IpPermissions.1.IpRanges.1.CidrIp": "0.0.0.0/0"})
    _check("F8 duplicate rule is rejected with InvalidPermission.Duplicate", r.status >= 400 and "InvalidPermission.Duplicate" in body(r))
    call(Action="RevokeSecurityGroupIngress", GroupId=sg, **{"SecurityGroupRuleId.1": ids[0]})
    _check("F8 revoke by rule id", ids[0] not in body(call(Action="DescribeSecurityGroupRules", **{"Filter.1.Name": "group-id", "Filter.1.Value.1": sg})))


def _f11():
    s = types.SimpleNamespace()
    call = lambda **p: v.dispatch(s, p)  # noqa: E731
    body = lambda r: r.body.decode() if isinstance(r.body, bytes) else r.body  # noqa: E731
    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", body(call(Action="CreateVpc", CidrBlock="10.6.0.0/16"))).group(1)
    sg = re.search(r"<groupId>(sg-\w+)</groupId>", body(call(Action="CreateSecurityGroup", VpcId=vpc, GroupName="g", GroupDescription="d"))).group(1)
    # the Terraform aws provider revokes the default egress rule with FromPort=0 ToPort=0 IpProtocol=-1
    call(Action="RevokeSecurityGroupEgress", GroupId=sg, **{"IpPermissions.1.FromPort": "0", "IpPermissions.1.ToPort": "0",
         "IpPermissions.1.IpProtocol": "-1", "IpPermissions.1.IpRanges.1.CidrIp": "0.0.0.0/0"})
    d = body(call(Action="DescribeSecurityGroupRules", **{"Filter.1.Name": "group-id", "Filter.1.Value.1": sg}))
    _check("F11 revoke of all-traffic rule ignores ports (FromPort=0/ToPort=0)", "<securityGroupRuleId>" not in d)
    r = call(Action="AuthorizeSecurityGroupEgress", GroupId=sg, **{"IpPermissions.1.IpProtocol": "-1", "IpPermissions.1.IpRanges.1.CidrIp": "0.0.0.0/0"})
    _check("F11 all-traffic egress can be re-created after the revoke", r.status == 200)


def _f9_f10_f12():
    s = types.SimpleNamespace()
    call = lambda **p: v.dispatch(s, p)  # noqa: E731
    body = lambda r: r.body.decode() if isinstance(r.body, bytes) else r.body  # noqa: E731
    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", body(call(Action="CreateVpc", CidrBlock="10.5.0.0/16"))).group(1)
    sub = re.search(r"<subnetId>(subnet-\w+)</subnetId>", body(call(Action="CreateSubnet", VpcId=vpc, CidrBlock="10.5.1.0/24"))).group(1)
    rt = re.search(r"<routeTableId>(rtb-\w+)</routeTableId>", body(call(Action="CreateRouteTable", VpcId=vpc))).group(1)
    aid = re.search(r"<associationId>([^<]+)</associationId>", body(call(Action="AssociateRouteTable", RouteTableId=rt, SubnetId=sub))).group(1)
    out = body(call(Action="DescribeRouteTables", **{"Filter.1.Name": "association.route-table-association-id", "Filter.1.Value.1": aid}))
    _check("F10 route table association is findable by association id and reports state associated",
           set(re.findall(r"<routeTableId>(rtb-\w+)</routeTableId>", out)) == {rt} and "<state>associated</state>" in out)
    out = body(call(Action="DescribeRouteTables", **{"Filter.1.Name": "vpc-id", "Filter.1.Value.1": vpc}))
    _check("F12 vpc-id filter on route tables (main + custom)", len(set(re.findall(r"<routeTableId>(rtb-\w+)</routeTableId>", out))) == 2)
    d1 = re.search(r"<dhcpOptionsId>(dopt-\w+)</dhcpOptionsId>", body(call(Action="CreateDhcpOptions", **{
        "DhcpConfiguration.1.Key": "domain-name", "DhcpConfiguration.1.Value.1": "a.internal"}))).group(1)
    call(Action="CreateDhcpOptions", **{"DhcpConfiguration.1.Key": "domain-name", "DhcpConfiguration.1.Value.1": "b.internal"})
    out = body(call(Action="DescribeDhcpOptions", **{"DhcpOptionsId.1": d1}))
    _check("F9 DescribeDhcpOptions honours DhcpOptionsId.N (exactly one)", len(set(re.findall(r"<dhcpOptionsId>(dopt-\w+)</dhcpOptionsId>", out))) == 1 and d1 in out)
    r = call(Action="DescribeDhcpOptions", **{"DhcpOptionsId.1": "dopt-doesnotexist"})
    _check("F9 unknown DhcpOptionsId is InvalidDhcpOptionsID.NotFound", r.status == 400 and "InvalidDhcpOptionsID.NotFound" in body(r))
    out = body(call(Action="DescribeSubnets", **{"Filter.1.Name": "vpc-id", "Filter.1.Value.1": vpc}))
    _check("F12 DescribeSubnets vpc-id filter", sub in out)
    out = body(call(Action="DescribeSubnets", **{"Filter.1.Name": "vpc-id", "Filter.1.Value.1": "vpc-0000000000000"}))
    _check("F12 DescribeSubnets filter with no match is empty, not everything", sub not in out)


def _f16():
    s = types.SimpleNamespace()
    call = lambda **p: v.dispatch(s, p)  # noqa: E731
    body = lambda r: r.body.decode() if isinstance(r.body, bytes) else r.body  # noqa: E731
    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", body(call(Action="CreateVpc", CidrBlock="10.4.0.0/16"))).group(1)
    sub = re.search(r"<subnetId>(subnet-\w+)</subnetId>", body(call(Action="CreateSubnet", VpcId=vpc, CidrBlock="10.4.1.0/24"))).group(1)
    rt = re.search(r"<routeTableId>(rtb-\w+)</routeTableId>", body(call(Action="CreateRouteTable", VpcId=vpc))).group(1)
    f = lambda aid: body(call(Action="DescribeRouteTables", **{"Filter.1.Name": "association.route-table-association-id", "Filter.1.Value.1": aid}))  # noqa: E731
    aid = re.search(r"<associationId>([^<]+)</associationId>", body(call(Action="AssociateRouteTable", RouteTableId=rt, SubnetId=sub))).group(1)
    _check("F16 explicit association exists", rt in f(aid))
    call(Action="DisassociateRouteTable", AssociationId=aid)
    _check("F16 after disassociate the association id is gone (implicit main-table fallback has no association record)",
           "<routeTableId>" not in f(aid))
    r = call(Action="DisassociateRouteTable", AssociationId=aid)
    _check("F16 disassociating again is InvalidAssociationID.NotFound", r.status == 400 and "InvalidAssociationID.NotFound" in body(r))


def _f18_f19():
    s = types.SimpleNamespace()
    call = lambda **p: v.dispatch(s, p)  # noqa: E731
    body = lambda r: r.body.decode() if isinstance(r.body, bytes) else r.body  # noqa: E731
    m = v._model(s)
    vpc = re.search(r"<vpcId>(vpc-\w+)</vpcId>", body(call(Action="CreateVpc", CidrBlock="10.3.0.0/16"))).group(1)
    sub = re.search(r"<subnetId>(subnet-\w+)</subnetId>", body(call(Action="CreateSubnet", VpcId=vpc, CidrBlock="10.3.1.0/24"))).group(1)
    vol = re.search(r"<volumeId>(vol-\w+)</volumeId>", body(call(Action="CreateVolume", Size="1", AvailabilityZone="us-east-1a"))).group(1)
    r = call(Action="AttachVolume", VolumeId=vol, InstanceId="i-0123456789ab", Device="/dev/sdf")
    _check("F18 before registration the engine does not know a runtime-launched instance", r.status == 400)
    ext = {"instance_id": "i-0123456789ab", "ami": "ami-ubuntu2204", "instance_type": "t3.micro", "state": "running", "subnet_id": sub,
           "security_group_ids": [], "private_ip": "10.3.1.5", "storage_gb": 8, "created": "2026-11-16T00:00:00.000Z", "name": "app"}
    v.register_external_instance(m, ext)
    v.register_external_instance(m, ext)   # idempotent
    r = call(Action="AttachVolume", VolumeId=vol, InstanceId="i-0123456789ab", Device="/dev/sdf")
    _check("F18 after shadow registration AttachVolume works", r.status == 200 and "<status>attached</status>" in body(r))
    out = body(call(Action="DescribeVolumes", **{"Filter.1.Name": "attachment.instance-id", "Filter.1.Value.1": "i-0123456789ab"}))
    _check("F19 DescribeVolumes filters on attachment.instance-id: the root volume (synthetic id) and the attached data volume",
           "vol-0123456789ab" in out and vol in out)
    out = body(call(Action="DescribeVolumes", **{"VolumeId.1": vol}))
    _check("F19 DescribeVolumes by id returns exactly that volume", out.count("<volumeId>" + vol + "</volumeId><size>") == 1 and "vol-0123456789ab</volumeId><size>" not in out)
    call(Action="CreateTags", **{"ResourceId.1": vol, "Tag.1.Key": "Env", "Tag.1.Value": "prod"})
    call(Action="CreateTags", **{"ResourceId.1": "i-0123456789ab", "Tag.1.Key": "Env", "Tag.1.Value": "dev"})
    out = body(call(Action="DescribeTags", **{"Filter.1.Name": "resource-id", "Filter.1.Value.1": vol}))
    _check("F20 DescribeTags honours the resource-id filter (provider reads one resource's tags)", vol in out and "i-0123456789ab" not in out)


def _f21():
    from core import dynamodb_core as d
    view = d._continuous_backups_view({"pitr_enabled": True, "pitr_earliest": "2026-11-16T00:00:00.000Z"})
    desc = view["PointInTimeRecoveryDescription"]
    _check("F21 PITR restorable timestamps are epoch numbers, not ISO strings",
           isinstance(desc["EarliestRestorableDateTime"], float) and isinstance(desc["LatestRestorableDateTime"], float))


if __name__ == "__main__":
    _f1(); _f4(); _f6_f7(); _f8(); _f11(); _f9_f10_f12(); _f16(); _f18_f19(); _f21()
    print("Endurance F1/F4/F6-F20 regressions: ALL GREEN")
