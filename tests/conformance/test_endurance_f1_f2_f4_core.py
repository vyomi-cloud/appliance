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


if __name__ == "__main__":
    _f1(); _f4()
    print("Endurance F1/F4 regressions: ALL GREEN")
