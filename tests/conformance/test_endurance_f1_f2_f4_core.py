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


if __name__ == "__main__":
    _f1(); _f4(); _f6_f7(); _f8(); _f11(); _f9_f10_f12()
    print("Endurance F1/F4/F6-F12 regressions: ALL GREEN")
