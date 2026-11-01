"""Auto Scaling depth (wave 5b gap sweep, ec2.auto-scaling) — launch template resolution,
StepScaling/TargetTrackingScaling policies, scheduled actions (lazy cron evaluation),
lifecycle hooks (real Pending:Wait / Terminating:Wait holds) and instance refresh.

Run on host:    PYTHONPATH=. python3 tests/conformance/test_autoscaling_depth_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import re
import time
from datetime import datetime, timedelta, timezone

try:
    from core import autoscaling_core as asg
    from core import vpc_core as vpc
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # pragma: no cover - Pyodide flat layout
    import autoscaling_core as asg  # type: ignore
    import vpc_core as vpc  # type: ignore
    from aws_wire_router import AwsWireRouter  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _xid(body, tag):
    m = re.search(f"<{tag}>(.*?)</{tag}>", body)
    return m.group(1) if m else None


def run() -> int:
    r = AwsWireRouter()

    # ── launch template resolution ──────────────────────────────────────
    seed = vpc.dispatch(r.vpc, {"Action": "DescribeImages"}).body
    ami_id = re.search(r"<imageId>([^<]+)</imageId>", seed).group(1)
    lt = vpc.dispatch(r.vpc, {"Action": "CreateLaunchTemplate", "LaunchTemplateName": "web-lt",
                              "LaunchTemplateData.ImageId": ami_id, "LaunchTemplateData.InstanceType": "t3.small"})
    lt_id = _xid(lt.body, "launchTemplateId")
    create = asg.dispatch(r.asg, {"Action": "CreateAutoScalingGroup", "AutoScalingGroupName": "web-asg",
                                  "MinSize": "1", "MaxSize": "5", "DesiredCapacity": "2",
                                  "LaunchTemplate.LaunchTemplateId": lt_id, "LaunchTemplate.Version": "$Default"})
    _check("CreateAutoScalingGroup with a launch template succeeds", create.status == 200)
    g = asg.dispatch(r.asg, {"Action": "DescribeAutoScalingGroups", "AutoScalingGroupNames.member.1": "web-asg"}).body
    _check("group carries its launch template", f"<LaunchTemplateId>{lt_id}</LaunchTemplateId>" in g)
    live = vpc.dispatch(r.vpc, {"Action": "DescribeInstances"}).body
    _check("instances launched via the template really use its instance type", live.count("<instanceType>t3.small</instanceType>") == 2)

    # ── StepScaling ──────────────────────────────────────────────────────
    step = asg.dispatch(r.asg, {"Action": "PutScalingPolicy", "AutoScalingGroupName": "web-asg", "PolicyName": "step-out",
                               "PolicyType": "StepScaling", "AdjustmentType": "ChangeInCapacity",
                               "StepAdjustments.member.1.MetricIntervalLowerBound": "0", "StepAdjustments.member.1.ScalingAdjustment": "1",
                               "StepAdjustments.member.2.MetricIntervalLowerBound": "10", "StepAdjustments.member.2.ScalingAdjustment": "3"})
    step_arn = _xid(step.body, "PolicyARN")
    _check("StepScaling policy created", step_arn is not None)
    pols = asg.dispatch(r.asg, {"Action": "DescribePolicies", "AutoScalingGroupName": "web-asg"}).body
    _check("DescribePolicies lists the step adjustments", "<StepAdjustments>" in pols and "<ScalingAdjustment>3</ScalingAdjustment>" in pols)
    _check("executing a StepScaling policy applies its first (smallest-breach) step", asg.execute_policy_arn(r.asg, step_arn))
    g2 = asg.dispatch(r.asg, {"Action": "DescribeAutoScalingGroups", "AutoScalingGroupNames.member.1": "web-asg"}).body
    _check("desired capacity grew by the first step's adjustment (+1)", "<DesiredCapacity>3</DesiredCapacity>" in g2)

    # ── TargetTrackingScaling ────────────────────────────────────────────
    tt = asg.dispatch(r.asg, {"Action": "PutScalingPolicy", "AutoScalingGroupName": "web-asg", "PolicyName": "target-cpu",
                             "PolicyType": "TargetTrackingScaling",
                             "TargetTrackingConfiguration.TargetValue": "40"})
    tt_arn = _xid(tt.body, "PolicyARN")
    _check("executing a TargetTrackingScaling policy nudges capacity by one instance", asg.execute_policy_arn(r.asg, tt_arn))
    g3 = asg.dispatch(r.asg, {"Action": "DescribeAutoScalingGroups", "AutoScalingGroupNames.member.1": "web-asg"}).body
    _check("desired capacity is now 4", "<DesiredCapacity>4</DesiredCapacity>" in g3)

    # ── scheduled actions (lazy cron evaluation) ─────────────────────────
    due = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    asg.dispatch(r.asg, {"Action": "PutScheduledUpdateGroupAction", "AutoScalingGroupName": "web-asg",
                        "ScheduledActionName": "night-scale-down", "StartTime": due, "MinSize": "1", "MaxSize": "5", "DesiredCapacity": "1"})
    g4 = asg.dispatch(r.asg, {"Action": "DescribeAutoScalingGroups", "AutoScalingGroupNames.member.1": "web-asg"}).body
    _check("a due one-time scheduled action is really applied on the next read", "<DesiredCapacity>1</DesiredCapacity>" in g4)
    sched = asg.dispatch(r.asg, {"Action": "DescribeScheduledActions", "AutoScalingGroupName": "web-asg"}).body
    _check("scheduled action round-trips", "<ScheduledActionName>night-scale-down</ScheduledActionName>" in sched)
    bad = asg.dispatch(r.asg, {"Action": "PutScheduledUpdateGroupAction", "AutoScalingGroupName": "web-asg",
                               "ScheduledActionName": "bad-cron", "Recurrence": "not a cron"})
    _check("an invalid recurrence is rejected", bad.status == 400)

    # ── lifecycle hooks: launching + terminating really hold the transition ─
    asg.dispatch(r.asg, {"Action": "PutLifecycleHook", "AutoScalingGroupName": "web-asg", "LifecycleHookName": "launch-hook",
                        "LifecycleTransition": "autoscaling:EC2_INSTANCE_LAUNCHING"})
    asg.dispatch(r.asg, {"Action": "SetDesiredCapacity", "AutoScalingGroupName": "web-asg", "DesiredCapacity": "2"})
    g5 = asg.dispatch(r.asg, {"Action": "DescribeAutoScalingGroups", "AutoScalingGroupNames.member.1": "web-asg"}).body
    _check("new instance held at Pending:Wait by the launch hook", "<LifecycleState>Pending:Wait</LifecycleState>" in g5)
    pending_iid = re.search(r"<InstanceId>([^<]+)</InstanceId>\s*<LifecycleState>Pending:Wait", g5).group(1)
    live2 = vpc.dispatch(r.vpc, {"Action": "DescribeInstances", "InstanceId.1": pending_iid}).body
    _check("the pending instance is nonetheless a REAL running EC2 instance", "<instanceState><code>16</code>" not in live2 or "running" in live2)
    complete = asg.dispatch(r.asg, {"Action": "CompleteLifecycleAction", "AutoScalingGroupName": "web-asg",
                                    "LifecycleHookName": "launch-hook", "InstanceId": pending_iid, "LifecycleActionResult": "CONTINUE"})
    _check("CompleteLifecycleAction succeeds", complete.status == 200)
    g6 = asg.dispatch(r.asg, {"Action": "DescribeAutoScalingGroups", "AutoScalingGroupNames.member.1": "web-asg"}).body
    _check("instance now InService", "<LifecycleState>Pending:Wait</LifecycleState>" not in g6)

    asg.dispatch(r.asg, {"Action": "PutLifecycleHook", "AutoScalingGroupName": "web-asg", "LifecycleHookName": "term-hook",
                        "LifecycleTransition": "autoscaling:EC2_INSTANCE_TERMINATING"})
    asg.dispatch(r.asg, {"Action": "SetDesiredCapacity", "AutoScalingGroupName": "web-asg", "DesiredCapacity": "1"})
    g7 = asg.dispatch(r.asg, {"Action": "DescribeAutoScalingGroups", "AutoScalingGroupNames.member.1": "web-asg"}).body
    _check("the chosen instance is held at Terminating:Wait, not actually removed yet", "<LifecycleState>Terminating:Wait</LifecycleState>" in g7)
    _check("desired capacity change doesn't drop below 2 settled instances while the hook is pending", g7.count("<member><InstanceId>") == 2)
    term_iid = re.search(r"<InstanceId>([^<]+)</InstanceId>\s*<LifecycleState>Terminating:Wait", g7).group(1)
    asg.dispatch(r.asg, {"Action": "CompleteLifecycleAction", "AutoScalingGroupName": "web-asg",
                        "LifecycleHookName": "term-hook", "InstanceId": term_iid, "LifecycleActionResult": "CONTINUE"})
    g8 = asg.dispatch(r.asg, {"Action": "DescribeAutoScalingGroups", "AutoScalingGroupNames.member.1": "web-asg"}).body
    _check("instance actually terminated once the hook completed", g8.count("<member><InstanceId>") == 1)
    live3 = vpc.dispatch(r.vpc, {"Action": "DescribeInstances", "InstanceId.1": term_iid}).body
    _check("the EC2 instance itself is really terminated", "terminated" in live3)

    # ── instance refresh ─────────────────────────────────────────────────
    before = asg.dispatch(r.asg, {"Action": "DescribeAutoScalingGroups", "AutoScalingGroupNames.member.1": "web-asg"}).body
    before_iid = _xid(before, "InstanceId")
    refresh = asg.dispatch(r.asg, {"Action": "StartInstanceRefresh", "AutoScalingGroupName": "web-asg"})
    refresh_id = _xid(refresh.body, "InstanceRefreshId")
    _check("StartInstanceRefresh returns an id", refresh_id is not None)
    after = asg.dispatch(r.asg, {"Action": "DescribeAutoScalingGroups", "AutoScalingGroupNames.member.1": "web-asg"}).body
    after_iid = _xid(after, "InstanceId")
    _check("the instance was really replaced (new instance id)", after_iid != before_iid)
    refreshes = asg.dispatch(r.asg, {"Action": "DescribeInstanceRefreshes", "AutoScalingGroupName": "web-asg"}).body
    _check("the refresh is recorded as Successful", f"<InstanceRefreshId>{refresh_id}</InstanceRefreshId>" in refreshes and "<Status>Successful</Status>" in refreshes)
    cancel = asg.dispatch(r.asg, {"Action": "CancelInstanceRefresh", "AutoScalingGroupName": "web-asg"})
    _check("cancelling an already-finished refresh is correctly rejected", cancel.status == 400 and "ActiveInstanceRefreshNotFound" in cancel.body)

    print("RESULT: PASS — Auto Scaling depth (launch templates, step/target-tracking, scheduled actions, lifecycle hooks, instance refresh) conforms.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
