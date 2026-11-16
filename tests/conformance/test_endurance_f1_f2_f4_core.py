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


if __name__ == "__main__":
    _f1(); _f4(); _f6_f7()
    print("Endurance F1/F4/F6/F7 regressions: ALL GREEN")
