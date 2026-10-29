"""ELBv2 engine conformance — host (CPython) and Pyodide.

Drives core/elbv2_core.py on the native Query wire (Action=...): load balancer,
target group, listener and rule lifecycle, target health, tags, the errors real
SDKs branch on, and the console REST view built on the same engine.
"""
import re

try:
    from core import elbv2_core as elb
except ImportError:  # pragma: no cover - Pyodide flat layout
    import elbv2_core as elb  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def run(store=None):
    s = store or elb.Elbv2Store()

    def call(**p):
        return elb.dispatch(s, p)

    def ok(**p):
        r = call(**p)
        if r.status != 200:
            raise AssertionError((p.get("Action"), r.body))
        return r.body

    def code(**p):
        r = call(**p)
        return r.status, re.search(r"<Code>(.*?)</Code>", r.body).group(1)

    def one(tag, body):
        return re.search(f"<{tag}>(.*?)</{tag}>", body).group(1)

    subs = {"Subnets.member.1": "subnet-a", "Subnets.member.2": "subnet-b"}
    body = ok(Action="CreateLoadBalancer", Name="lb1", **subs)
    arn = one("LoadBalancerArn", body)
    _check("create returns provisioning", "<Code>provisioning</Code>" in body)
    _check("ARN is real-shaped", ":loadbalancer/app/lb1/" in arn)
    _check("describe shows it active", "<Code>active</Code>" in ok(Action="DescribeLoadBalancers", **{"Names.member.1": "lb1"}))
    _check("same settings is idempotent", ok(Action="CreateLoadBalancer", Name="lb1", **subs).count(arn) == 1)
    _check("different settings -> duplicate", code(Action="CreateLoadBalancer", Name="lb1", Scheme="internal", **subs)[1] == "DuplicateLoadBalancerName")
    _check("one subnet for an ALB is rejected", code(Action="CreateLoadBalancer", Name="lb2", **{"Subnets.member.1": "subnet-a"})[1] == "ValidationError")
    _check("bad name is rejected", code(Action="CreateLoadBalancer", Name="-bad-", **subs)[1] == "ValidationError")
    _check("missing LB", code(Action="DescribeLoadBalancers", **{"Names.member.1": "nope"})[1] == "LoadBalancerNotFound")

    tg_body = ok(Action="CreateTargetGroup", Name="tg1", Protocol="HTTP", Port="80", VpcId="vpc-1")
    tg = one("TargetGroupArn", tg_body)
    _check("target group defaults", "<HealthCheckPath>/</HealthCheckPath>" in tg_body and "<HttpCode>200</HttpCode>" in tg_body)
    _check("instance target ids are validated", code(Action="RegisterTargets", TargetGroupArn=tg, **{"Targets.member.1.Id": "web-1"})[1] == "InvalidTarget")
    ok(Action="RegisterTargets", TargetGroupArn=tg, **{"Targets.member.1.Id": "i-0123456789abcdef0"})
    _check("target unused before a listener", "<State>unused</State>" in ok(Action="DescribeTargetHealth", TargetGroupArn=tg))

    lsn = ok(Action="CreateListener", LoadBalancerArn=arn, Protocol="HTTP", Port="80",
             **{"DefaultActions.member.1.Type": "forward", "DefaultActions.member.1.TargetGroupArn": tg})
    ls = one("ListenerArn", lsn)
    _check("target healthy once attached", "<State>healthy</State>" in ok(Action="DescribeTargetHealth", TargetGroupArn=tg))
    _check("duplicate port", code(Action="CreateListener", LoadBalancerArn=arn, Protocol="HTTP", Port="80",
                                  **{"DefaultActions.member.1.Type": "forward", "DefaultActions.member.1.TargetGroupArn": tg})[1] == "DuplicateListener")
    _check("target group in use", code(Action="DeleteTargetGroup", TargetGroupArn=tg)[1] == "ResourceInUse")

    rule = ok(Action="CreateRule", ListenerArn=ls, Priority="10",
              **{"Conditions.member.1.Field": "path-pattern", "Conditions.member.1.Values.member.1": "/a/*",
                 "Actions.member.1.Type": "forward", "Actions.member.1.TargetGroupArn": tg})
    ra = one("RuleArn", rule)
    _check("priority collision", code(Action="CreateRule", ListenerArn=ls, Priority="10",
                                      **{"Conditions.member.1.Field": "path-pattern", "Conditions.member.1.Values.member.1": "/b",
                                         "Actions.member.1.Type": "forward", "Actions.member.1.TargetGroupArn": tg})[1] == "PriorityInUse")
    rules = ok(Action="DescribeRules", ListenerArn=ls)
    _check("default rule sorts last", rules.rfind("<IsDefault>true</IsDefault>") > rules.rfind("<IsDefault>false</IsDefault>"))
    ok(Action="SetRulePriorities", **{"RulePriorities.member.1.RuleArn": ra, "RulePriorities.member.1.Priority": "20"})
    ok(Action="DeleteRule", RuleArn=ra)

    ok(Action="AddTags", **{"ResourceArns.member.1": arn, "Tags.member.1.Key": "k", "Tags.member.1.Value": "v"})
    _check("tags read back", "<Key>k</Key><Value>v</Value>" in ok(Action="DescribeTags", **{"ResourceArns.member.1": arn}))

    row = elb.console_create(s, {"name": "ui"})
    _check("console create fills every field", all(v not in (None, "") for k, v in row.items() if k != "tags"))
    elb.console_child_create(s, "target-groups", {"name": "ui-tg"})
    elb.console_child_create(s, "listeners", {"load_balancer": "ui", "port": 8080})
    _check("console child lists", len(elb.console_children(s, "target-groups")["items"]) == 2
           and len(elb.console_children(s, "listeners")["items"]) == 2)
    elb.console_delete(s, "ui")

    ok(Action="ModifyLoadBalancerAttributes", LoadBalancerArn=arn, **{"Attributes.member.1.Key": "deletion_protection.enabled", "Attributes.member.1.Value": "true"})
    _check("deletion protection", code(Action="DeleteLoadBalancer", LoadBalancerArn=arn)[1] == "OperationNotPermitted")
    ok(Action="ModifyLoadBalancerAttributes", LoadBalancerArn=arn, **{"Attributes.member.1.Key": "deletion_protection.enabled", "Attributes.member.1.Value": "false"})
    ok(Action="DeleteLoadBalancer", LoadBalancerArn=arn)
    _check("listeners removed with the LB", code(Action="DescribeListeners", **{"ListenerArns.member.1": ls})[1] == "ListenerNotFound")
    ok(Action="DeleteTargetGroup", TargetGroupArn=tg)
    return s


def test_elbv2_core():
    run()


if __name__ == "__main__":
    run()
    print("elbv2 core: ok")
