"""Auto Scaling core — the minimal EC2 Auto Scaling group + scaling-policy backend that
makes a CloudWatch alarm's "Auto Scaling action" real (aws.cloudwatch.alarms.actions.compute).

Speaks the native Auto Scaling **Query protocol** (form-encoded `Action=...`, XML
responses, `2011-01-01` API version) so an unmodified boto3 `autoscaling` client manages
groups and policies. NO fastapi / boto3 / socket imports → loads under Pyodide.

Scope: CreateAutoScalingGroup / DescribeAutoScalingGroups / UpdateAutoScalingGroup /
DeleteAutoScalingGroup / SetDesiredCapacity / PutScalingPolicy / DescribePolicies /
DeletePolicy — enough to create a group, attach a scaling policy, and have a CloudWatch
alarm action really execute it. Executing a policy (or any desired-capacity change) really
launches/terminates EC2 instances through vpc_core's own instance model (the SAME path
RunInstances/TerminateInstances goes through), so a scaled group's instances show up
identically in the EC2 console. No launch configurations, lifecycle hooks, warm pools,
mixed-instance policies or scheduled actions — those slot in behind the same model.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from xml.sax.saxutils import escape as _xml_escape

NS = "http://autoscaling.amazonaws.com/doc/2011-01-01/"
DEFAULT_ACCOUNT_ID = "123456789012"
REGION = "us-east-1"
_ADJUSTMENT_TYPES = {"ChangeInCapacity", "ExactCapacity", "PercentChangeInCapacity"}


@dataclass
class AsgResponse:
    status: int = 200
    body: str = ""
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class AsgError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


@dataclass
class AutoScalingStore:
    account_id: str = DEFAULT_ACCOUNT_ID
    region: str = REGION
    groups: dict = field(default_factory=dict)      # name -> group record
    policies: dict = field(default_factory=dict)    # (group, policy) -> policy record
    vpc_store: object = None   # the shared EC2/VPC model — set by the wire router

    def persist(self) -> None:  # overridden by durable substrates
        pass


def _now() -> float:
    return time.time()


def _req_id() -> str:
    return str(uuid.uuid4())


def _group_arn(store, name, group_id) -> str:
    return f"arn:aws:autoscaling:{store.region}:{store.account_id}:autoScalingGroup:{group_id}:autoScalingGroupName/{name}"


def _policy_arn(store, group, policy_id, policy_name) -> str:
    return (f"arn:aws:autoscaling:{store.region}:{store.account_id}:scalingPolicy:{policy_id}:"
            f"autoScalingGroupName/{group}:policyName/{policy_name}")


def _members(params: dict, prefix: str) -> list:
    """Collect an AWS Query-protocol list parameter: `{prefix}.member.{i}` (scalar) or
    `{prefix}.member.{i}.{field}` (structured)."""
    out: list = []
    i = 1
    while True:
        scalar_key = f"{prefix}.member.{i}"
        if scalar_key in params:
            out.append(params[scalar_key])
            i += 1
            continue
        struct_prefix = scalar_key + "."
        sub = {k[len(struct_prefix):]: v for k, v in params.items() if k.startswith(struct_prefix)}
        if not sub:
            break
        out.append(sub)
        i += 1
    return out


def _el(tag: str, value) -> str:
    return f"<{tag}>{_xml_escape(str(value))}</{tag}>"


def _success(action: str, result_inner: str, status: int = 200) -> AsgResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<{action}Response xmlns="{NS}">'
           + (f'<{action}Result>{result_inner}</{action}Result>' if result_inner else "")
           + f'<ResponseMetadata><RequestId>{_req_id()}</RequestId></ResponseMetadata>'
           f'</{action}Response>')
    return AsgResponse(status=status, body=xml)


def _error(code: str, message: str, status: int = 400) -> AsgResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<ErrorResponse xmlns="{NS}">'
           f'<Error><Type>Sender</Type><Code>{_xml_escape(code)}</Code>'
           f'<Message>{_xml_escape(message)}</Message></Error>'
           f'<RequestId>{_req_id()}</RequestId></ErrorResponse>')
    return AsgResponse(status=status, body=xml)


def _req(params, key):
    v = params.get(key)
    if v is None or v == "":
        raise AsgError("ValidationError", f"{key} is required.")
    return v


def _instance_xml(iid: str) -> str:
    return (f"<member><InstanceId>{_xml_escape(iid)}</InstanceId>"
            f"<LifecycleState>InService</LifecycleState><HealthStatus>Healthy</HealthStatus>"
            f"<ProtectedFromScaleIn>false</ProtectedFromScaleIn></member>")


def _group_xml(store, g: dict) -> str:
    azs = "".join(_el("member", az) for az in g["azs"])
    insts = "".join(_instance_xml(i) for i in g["instance_ids"])
    return (
        "<member>"
        f"{_el('AutoScalingGroupName', g['name'])}{_el('AutoScalingGroupARN', g['arn'])}"
        f"{_el('MinSize', g['min'])}{_el('MaxSize', g['max'])}{_el('DesiredCapacity', g['desired'])}"
        f"{_el('DefaultCooldown', 300)}{_el('HealthCheckType', 'EC2')}{_el('HealthCheckGracePeriod', 300)}"
        f"{_el('CreatedTime', g['created'])}"
        f"<AvailabilityZones>{azs}</AvailabilityZones>"
        f"<Instances>{insts}</Instances>"
        "</member>"
    )


def _policy_xml(store, p: dict) -> str:
    return (
        "<member>"
        f"{_el('AutoScalingGroupName', p['group'])}{_el('PolicyName', p['name'])}{_el('PolicyARN', p['arn'])}"
        f"{_el('PolicyType', 'SimpleScaling')}{_el('AdjustmentType', p['adjustment_type'])}"
        f"{_el('ScalingAdjustment', p['scaling_adjustment'])}{_el('Cooldown', p.get('cooldown', 300))}"
        "</member>"
    )


def _op_create_group(store: AutoScalingStore, params: dict) -> AsgResponse:
    name = str(_req(params, "AutoScalingGroupName"))
    if name in store.groups:
        raise AsgError("AlreadyExists", f"AutoScalingGroup name {name} already exists")
    min_size = int(_req(params, "MinSize"))
    max_size = int(_req(params, "MaxSize"))
    if min_size < 0 or max_size < min_size:
        raise AsgError("ValidationError", "MinSize/MaxSize are invalid.")
    desired = int(params.get("DesiredCapacity") or min_size)
    if not (min_size <= desired <= max_size):
        raise AsgError("ValidationError", "DesiredCapacity must be between MinSize and MaxSize.")
    azs = _members(params, "AvailabilityZones") or ["us-east-1a"]
    group_id = uuid.uuid4().hex
    g = {
        "name": name, "id": group_id, "arn": _group_arn(store, name, group_id),
        "min": min_size, "max": max_size, "desired": 0, "azs": azs,
        "launch_template": {k[len("LaunchTemplate."):]: v for k, v in params.items() if k.startswith("LaunchTemplate.")},
        "image_id": params.get("ImageId"), "instance_type": params.get("InstanceType"),
        "instance_ids": [], "created": _iso(_now()),
    }
    store.groups[name] = g
    _reconcile(store, g, desired)
    store.persist()
    return _success("CreateAutoScalingGroup", "")


def _op_describe_groups(store: AutoScalingStore, params: dict) -> AsgResponse:
    names = _members(params, "AutoScalingGroupNames")
    groups = [g for g in store.groups.values() if not names or g["name"] in names]
    inner = f"<AutoScalingGroups>{''.join(_group_xml(store, g) for g in groups)}</AutoScalingGroups>"
    return _success("DescribeAutoScalingGroups", inner)


def _group_of(store, params):
    name = str(_req(params, "AutoScalingGroupName"))
    g = store.groups.get(name)
    if g is None:
        raise AsgError("ValidationError", f"AutoScalingGroup name not found - {name}")
    return g


def _op_update_group(store: AutoScalingStore, params: dict) -> AsgResponse:
    g = _group_of(store, params)
    if "MinSize" in params:
        g["min"] = int(params["MinSize"])
    if "MaxSize" in params:
        g["max"] = int(params["MaxSize"])
    desired = int(params["DesiredCapacity"]) if "DesiredCapacity" in params else g["desired"]
    desired = max(g["min"], min(g["max"], desired))
    _reconcile(store, g, desired)
    store.persist()
    return _success("UpdateAutoScalingGroup", "")


def _op_set_desired_capacity(store: AutoScalingStore, params: dict) -> AsgResponse:
    g = _group_of(store, params)
    desired = int(_req(params, "DesiredCapacity"))
    if not (g["min"] <= desired <= g["max"]):
        raise AsgError("ValidationError", "DesiredCapacity must be between MinSize and MaxSize.")
    _reconcile(store, g, desired)
    store.persist()
    return _success("SetDesiredCapacity", "")


def _op_delete_group(store: AutoScalingStore, params: dict) -> AsgResponse:
    name = str(_req(params, "AutoScalingGroupName"))
    g = store.groups.get(name)
    if g is None:
        raise AsgError("ValidationError", f"AutoScalingGroup name not found - {name}")
    force = str(params.get("ForceDelete", "")).lower() == "true"
    if g["instance_ids"] and not force:
        raise AsgError("ResourceInUse", "You cannot delete an AutoScalingGroup with instances unless you set ForceDelete.")
    if force:
        _reconcile(store, g, 0)
    store.groups.pop(name, None)
    store.policies = {k: v for k, v in store.policies.items() if v["group"] != name}
    store.persist()
    return _success("DeleteAutoScalingGroup", "")


def _op_put_scaling_policy(store: AutoScalingStore, params: dict) -> AsgResponse:
    g = _group_of(store, params)
    policy_name = str(_req(params, "PolicyName"))
    adj_type = str(params.get("AdjustmentType") or "ChangeInCapacity")
    if adj_type not in _ADJUSTMENT_TYPES:
        raise AsgError("ValidationError", f"AdjustmentType must be one of {sorted(_ADJUSTMENT_TYPES)}.")
    adjustment = int(_req(params, "ScalingAdjustment"))
    policy_id = uuid.uuid4().hex
    key = (g["name"], policy_name)
    p = {"group": g["name"], "name": policy_name, "id": policy_id,
         "arn": _policy_arn(store, g["name"], policy_id, policy_name),
         "adjustment_type": adj_type, "scaling_adjustment": adjustment,
         "cooldown": int(params.get("Cooldown") or 300)}
    store.policies[key] = p
    store.persist()
    return _success("PutScalingPolicy", f"{_el('PolicyARN', p['arn'])}")


def _op_describe_policies(store: AutoScalingStore, params: dict) -> AsgResponse:
    gname = params.get("AutoScalingGroupName")
    names = set(_members(params, "PolicyNames"))
    pols = [p for p in store.policies.values() if (not gname or p["group"] == gname) and (not names or p["name"] in names)]
    inner = f"<ScalingPolicies>{''.join(_policy_xml(store, p) for p in pols)}</ScalingPolicies>"
    return _success("DescribePolicies", inner)


def _op_delete_policy(store: AutoScalingStore, params: dict) -> AsgResponse:
    gname = str(_req(params, "AutoScalingGroupName"))
    policy_name = str(_req(params, "PolicyName"))
    store.policies.pop((gname, policy_name), None)
    store.persist()
    return _success("DeletePolicy", "")


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


def _reconcile(store: AutoScalingStore, g: dict, new_desired: int) -> None:
    """Make the group's real EC2 instance count match `new_desired`, through the same
    instance lifecycle RunInstances/TerminateInstances use (vpc_core.py) — a scaled group's
    instances are indistinguishable from any other EC2 instance in the console."""
    from core import vpc_core as _vpc_mod
    g["desired"] = new_desired
    if store.vpc_store is None:
        return
    current = len(g["instance_ids"])
    if new_desired > current:
        for _ in range(new_desired - current):
            az = g["azs"][len(g["instance_ids"]) % len(g["azs"])] if g["azs"] else None
            iid = _vpc_mod.launch_for_autoscaling(
                store.vpc_store, az=az, instance_type=g.get("instance_type"), image_id=g.get("image_id"),
                tags={"Name": f"{g['name']}-instance", "aws:autoscaling:groupName": g["name"]})
            g["instance_ids"].append(iid)
    elif new_desired < current:
        for _ in range(current - new_desired):
            iid = g["instance_ids"].pop()
            _vpc_mod.terminate_for_autoscaling(store.vpc_store, iid)


def execute_policy_arn(store: AutoScalingStore, policy_arn: str) -> bool:
    """Called by cloudwatch_core when a CloudWatch alarm fires an Auto Scaling action ARN
    (arn:...:autoscaling:...:scalingPolicy:...) — see aws.cloudwatch.alarms.actions.compute.
    Really adjusts the group's desired capacity (clamped to MinSize/MaxSize) and reconciles
    real EC2 instances to match, exactly as AWS's Auto Scaling service does under an alarm."""
    p = next((p for p in store.policies.values() if p["arn"] == policy_arn), None)
    if p is None:
        return False
    g = store.groups.get(p["group"])
    if g is None:
        return False
    current = g["desired"]
    if p["adjustment_type"] == "ExactCapacity":
        new_desired = p["scaling_adjustment"]
    elif p["adjustment_type"] == "PercentChangeInCapacity":
        new_desired = current + round(current * p["scaling_adjustment"] / 100)
    else:  # ChangeInCapacity
        new_desired = current + p["scaling_adjustment"]
    new_desired = max(g["min"], min(g["max"], new_desired))
    _reconcile(store, g, new_desired)
    store.persist()
    return True


_OPS = {
    "CreateAutoScalingGroup": _op_create_group,
    "DescribeAutoScalingGroups": _op_describe_groups,
    "UpdateAutoScalingGroup": _op_update_group,
    "SetDesiredCapacity": _op_set_desired_capacity,
    "DeleteAutoScalingGroup": _op_delete_group,
    "PutScalingPolicy": _op_put_scaling_policy,
    "DescribePolicies": _op_describe_policies,
    "DeletePolicy": _op_delete_policy,
}
OPERATIONS = sorted(_OPS)


def dispatch(store: AutoScalingStore, params: dict | None = None) -> AsgResponse:
    """Native Auto Scaling Query-protocol router. `params` is the parsed form body
    ({"Action": "CreateAutoScalingGroup", "AutoScalingGroupName": "my-asg", ...})."""
    params = params if isinstance(params, dict) else {}
    action = str(params.get("Action", "")).strip()
    op = _OPS.get(action)
    if op is None:
        return _error("InvalidAction", f"The action {action} is not implemented.", 400)
    try:
        return op(store, params)
    except AsgError as e:
        return _error(e.code, e.message, e.status)
