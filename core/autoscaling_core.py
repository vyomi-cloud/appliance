"""Auto Scaling core — the EC2 Auto Scaling group + scaling-policy backend that makes a
CloudWatch alarm's "Auto Scaling action" real (aws.cloudwatch.alarms.actions.compute) and
backs the EC2 console's "Auto Scaling" section (ec2.auto-scaling).

Speaks the native Auto Scaling **Query protocol** (form-encoded `Action=...`, XML
responses, `2011-01-01` API version) so an unmodified boto3 `autoscaling` client manages
groups and policies. NO fastapi / boto3 / socket imports → loads under Pyodide.

Scope: CreateAutoScalingGroup / DescribeAutoScalingGroups / UpdateAutoScalingGroup /
DeleteAutoScalingGroup / SetDesiredCapacity / DescribeAutoScalingInstances —
group CRUD, reconciled against real EC2 instances through vpc_core's own instance model
(the SAME path RunInstances/TerminateInstances goes through — a launch template reference
resolves through vpc_core.resolve_launch_template), so a scaled group's instances show up
identically in the EC2 console.

PutScalingPolicy / DescribePolicies / DeletePolicy — SimpleScaling, StepScaling and
TargetTrackingScaling are all stored and describable; invoking one (an alarm action, or the
console's "scale now") really adjusts desired capacity. Vyomi's alarm → policy trigger
carries no breach magnitude, so StepScaling applies its first (smallest-breach) step and
TargetTrackingScaling nudges by one instance toward the configured target rather than
continuously tracking a live metric — see ec2.auto-scaling's limitations.

PutScheduledUpdateGroupAction / DescribeScheduledActions / DeleteScheduledAction — real
one-time (StartTime) and recurring (5-field Recurrence cron) schedules, evaluated lazily
(on every group read, like this simulator's CloudWatch alarms) rather than by a live
background clock.

PutLifecycleHook / DescribeLifecycleHooks / DeleteLifecycleHook / CompleteLifecycleAction /
RecordLifecycleActionHeartbeat — a group with a launch/terminate hook really holds new
instances at `Pending:Wait` / existing ones at `Terminating:Wait` until completed, instead
of transitioning them immediately.

StartInstanceRefresh / DescribeInstanceRefreshes / CancelInstanceRefresh — a real rolling
replacement of every instance (through the same launch/terminate path), executed eagerly
(Vyomi has no background scheduler to spread it over time, so there's no window to cancel
a refresh that's still `InProgress`).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape as _xml_escape

NS = "http://autoscaling.amazonaws.com/doc/2011-01-01/"
DEFAULT_ACCOUNT_ID = "123456789012"
REGION = "us-east-1"
_ADJUSTMENT_TYPES = {"ChangeInCapacity", "ExactCapacity", "PercentChangeInCapacity"}
_POLICY_TYPES = {"SimpleScaling", "StepScaling", "TargetTrackingScaling"}


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
    scheduled_actions: dict = field(default_factory=dict)   # (group, name) -> scheduled action record
    lifecycle_hooks: dict = field(default_factory=dict)     # (group, name) -> lifecycle hook record
    instance_refreshes: list = field(default_factory=list)  # most-recent-first per group
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


def _instance_xml(g: dict, iid: str) -> str:
    state = g.get("lifecycle", {}).get(iid, "InService")
    health = "Unhealthy" if state == "Terminating:Wait" else "Healthy"
    return (f"<member><InstanceId>{_xml_escape(iid)}</InstanceId>"
            f"<LifecycleState>{state}</LifecycleState><HealthStatus>{health}</HealthStatus>"
            f"<ProtectedFromScaleIn>false</ProtectedFromScaleIn></member>")


def _group_xml(store, g: dict) -> str:
    azs = "".join(_el("member", az) for az in g["azs"])
    insts = "".join(_instance_xml(g, i) for i in g["instance_ids"])
    subnets = ",".join(g.get("subnet_ids") or [])
    lt = g.get("launch_template_ref") or {}
    lt_xml = (f"<LaunchTemplate>{_el('LaunchTemplateId', lt['id'])}{_el('LaunchTemplateName', lt['name'])}"
              f"{_el('Version', lt.get('version', '$Default'))}</LaunchTemplate>") if lt else ""
    return (
        "<member>"
        f"{_el('AutoScalingGroupName', g['name'])}{_el('AutoScalingGroupARN', g['arn'])}"
        f"{_el('MinSize', g['min'])}{_el('MaxSize', g['max'])}{_el('DesiredCapacity', g['desired'])}"
        f"{_el('DefaultCooldown', 300)}{_el('HealthCheckType', g.get('health_check_type', 'EC2'))}"
        f"{_el('HealthCheckGracePeriod', g.get('health_check_grace_period', 300))}"
        f"{_el('DefaultInstanceWarmup', g.get('default_instance_warmup', 0))}"
        f"{_el('CreatedTime', g['created'])}"
        f"{lt_xml}"
        f"{_el('VPCZoneIdentifier', subnets) if subnets else ''}"
        f"<AvailabilityZones>{azs}</AvailabilityZones>"
        f"<Instances>{insts}</Instances>"
        "</member>"
    )


def _step_xml(steps: list) -> str:
    items = "".join(
        "<member>" +
        (f"{_el('MetricIntervalLowerBound', s['lower'])}" if s.get("lower") is not None else "") +
        (f"{_el('MetricIntervalUpperBound', s['upper'])}" if s.get("upper") is not None else "") +
        f"{_el('ScalingAdjustment', s['adjustment'])}</member>"
        for s in steps)
    return f"<StepAdjustments>{items}</StepAdjustments>"


def _policy_xml(store, p: dict) -> str:
    extra = ""
    if p["policy_type"] == "SimpleScaling":
        extra = f"{_el('AdjustmentType', p['adjustment_type'])}{_el('ScalingAdjustment', p['scaling_adjustment'])}"
    elif p["policy_type"] == "StepScaling":
        extra = f"{_el('AdjustmentType', p['adjustment_type'])}{_step_xml(p.get('step_adjustments', []))}"
    elif p["policy_type"] == "TargetTrackingScaling":
        ttc = p.get("target_tracking_configuration") or {}
        extra = (f"<TargetTrackingConfiguration>{_el('TargetValue', ttc.get('target_value', 50))}"
                 f"</TargetTrackingConfiguration>")
    return (
        "<member>"
        f"{_el('AutoScalingGroupName', p['group'])}{_el('PolicyName', p['name'])}{_el('PolicyARN', p['arn'])}"
        f"{_el('PolicyType', p['policy_type'])}{extra}{_el('Cooldown', p.get('cooldown', 300))}"
        f"{_el('EstimatedInstanceWarmup', p.get('estimated_instance_warmup', 300))}"
        "</member>"
    )


def _sched_arn(store, group, name) -> str:
    return f"arn:aws:autoscaling:{store.region}:{store.account_id}:scheduledUpdateGroupAction:{uuid.uuid4().hex}:autoScalingGroupName/{group}:scheduledActionName/{name}"


def _sched_xml(s: dict) -> str:
    return (
        "<member>"
        f"{_el('AutoScalingGroupName', s['group'])}{_el('ScheduledActionName', s['name'])}{_el('ScheduledActionARN', s['arn'])}"
        + (f"{_el('StartTime', s['start_time'])}" if s.get("start_time") else "")
        + (f"{_el('EndTime', s['end_time'])}" if s.get("end_time") else "")
        + (f"{_el('Recurrence', s['recurrence'])}" if s.get("recurrence") else "")
        + (f"{_el('MinSize', s['min_size'])}" if s.get("min_size") is not None else "")
        + (f"{_el('MaxSize', s['max_size'])}" if s.get("max_size") is not None else "")
        + (f"{_el('DesiredCapacity', s['desired_capacity'])}" if s.get("desired_capacity") is not None else "")
        + "</member>"
    )


def _hook_xml(h: dict) -> str:
    return (
        "<member>"
        f"{_el('AutoScalingGroupName', h['group'])}{_el('LifecycleHookName', h['name'])}"
        f"{_el('LifecycleTransition', h['transition'])}{_el('DefaultResult', h.get('default_result', 'ABANDON'))}"
        f"{_el('HeartbeatTimeout', h.get('heartbeat_timeout', 3600))}{_el('GlobalTimeout', h.get('global_timeout', 172800))}"
        "</member>"
    )


def _refresh_xml(r: dict) -> str:
    return (
        "<member>"
        f"{_el('InstanceRefreshId', r['id'])}{_el('AutoScalingGroupName', r['group'])}{_el('Status', r['status'])}"
        f"{_el('PercentageComplete', r['percentage_complete'])}{_el('InstancesToUpdate', r['instances_to_update'])}"
        f"{_el('StartTime', r['start_time'])}"
        + (f"{_el('EndTime', r['end_time'])}" if r.get("end_time") else "")
        + "</member>"
    )


def _resolve_launch_template_ref(store, params: dict) -> dict | None:
    lt_id = params.get("LaunchTemplate.LaunchTemplateId")
    lt_name = params.get("LaunchTemplate.LaunchTemplateName")
    version = params.get("LaunchTemplate.Version")
    if not (lt_id or lt_name) or store.vpc_store is None:
        return None
    from core import vpc_core as _vpc_mod
    data = _vpc_mod.resolve_launch_template(store.vpc_store, lt_id, lt_name, version)
    if data is None:
        raise AsgError("ValidationError", f"Launch template {lt_id or lt_name} version {version or '$Default'} not found.")
    return {"id": lt_id, "name": lt_name, "version": version or "$Default", "data": data}


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
    lt_ref = _resolve_launch_template_ref(store, params)
    lt_data = lt_ref["data"] if lt_ref else {}
    subnet_ids = str(params.get("VPCZoneIdentifier") or "").split(",") if params.get("VPCZoneIdentifier") else []
    subnet_ids = [s for s in subnet_ids if s]
    sg_ids = [v for k, v in lt_data.items() if k.startswith("SecurityGroupIds.")]
    group_id = uuid.uuid4().hex
    g = {
        "name": name, "id": group_id, "arn": _group_arn(store, name, group_id),
        "min": min_size, "max": max_size, "desired": 0, "azs": azs,
        "launch_template_ref": lt_ref,
        "image_id": params.get("ImageId") or lt_data.get("ImageId"),
        "instance_type": params.get("InstanceType") or lt_data.get("InstanceType"),
        "key_name": lt_data.get("KeyName"), "security_group_ids": sg_ids, "subnet_ids": subnet_ids,
        "health_check_type": str(params.get("HealthCheckType") or "EC2"),
        "health_check_grace_period": int(params.get("HealthCheckGracePeriod") or 300),
        "default_instance_warmup": int(params.get("DefaultInstanceWarmup") or 0),
        "instance_ids": [], "lifecycle": {}, "created": _iso(_now()),
    }
    store.groups[name] = g
    _reconcile(store, g, desired)
    store.persist()
    return _success("CreateAutoScalingGroup", "")


def _op_describe_groups(store: AutoScalingStore, params: dict) -> AsgResponse:
    _apply_due_scheduled_actions(store)
    names = _members(params, "AutoScalingGroupNames")
    groups = [g for g in store.groups.values() if not names or g["name"] in names]
    inner = f"<AutoScalingGroups>{''.join(_group_xml(store, g) for g in groups)}</AutoScalingGroups>"
    return _success("DescribeAutoScalingGroups", inner)


def _op_describe_instances(store: AutoScalingStore, params: dict) -> AsgResponse:
    _apply_due_scheduled_actions(store)
    ids = set(_members(params, "InstanceIds"))
    rows = []
    for g in store.groups.values():
        for iid in g["instance_ids"]:
            if ids and iid not in ids:
                continue
            state = g.get("lifecycle", {}).get(iid, "InService")
            rows.append("<member>" + f"{_el('InstanceId', iid)}{_el('AutoScalingGroupName', g['name'])}"
                        f"{_el('AvailabilityZone', g['azs'][0] if g['azs'] else 'us-east-1a')}"
                        f"{_el('LifecycleState', state)}{_el('HealthStatus', 'Healthy' if state != 'Terminating:Wait' else 'Unhealthy')}"
                        f"{_el('ProtectedFromScaleIn', 'false')}" + "</member>")
    return _success("DescribeAutoScalingInstances", f"<AutoScalingInstances>{''.join(rows)}</AutoScalingInstances>")


def _group_of(store, params):
    _apply_due_scheduled_actions(store)
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
    if "HealthCheckType" in params:
        g["health_check_type"] = str(params["HealthCheckType"])
    if "HealthCheckGracePeriod" in params:
        g["health_check_grace_period"] = int(params["HealthCheckGracePeriod"])
    if "VPCZoneIdentifier" in params:
        g["subnet_ids"] = [s for s in str(params["VPCZoneIdentifier"]).split(",") if s]
    lt_ref = _resolve_launch_template_ref(store, params)
    if lt_ref:
        g["launch_template_ref"] = lt_ref
        g["image_id"] = lt_ref["data"].get("ImageId") or g["image_id"]
        g["instance_type"] = lt_ref["data"].get("InstanceType") or g["instance_type"]
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
        _reconcile(store, g, 0, respect_hooks=False)
    store.groups.pop(name, None)
    store.policies = {k: v for k, v in store.policies.items() if v["group"] != name}
    store.scheduled_actions = {k: v for k, v in getattr(store, "scheduled_actions", {}).items() if v["group"] != name}
    store.lifecycle_hooks = {k: v for k, v in getattr(store, "lifecycle_hooks", {}).items() if v["group"] != name}
    store.instance_refreshes = [r for r in getattr(store, "instance_refreshes", []) if r["group"] != name]
    store.persist()
    return _success("DeleteAutoScalingGroup", "")


def _op_put_scaling_policy(store: AutoScalingStore, params: dict) -> AsgResponse:
    g = _group_of(store, params)
    policy_name = str(_req(params, "PolicyName"))
    policy_type = str(params.get("PolicyType") or "SimpleScaling")
    if policy_type not in _POLICY_TYPES:
        raise AsgError("ValidationError", f"PolicyType must be one of {sorted(_POLICY_TYPES)}.")
    policy_id = uuid.uuid4().hex
    key = f"{g['name']}#{policy_name}"
    p = {"group": g["name"], "name": policy_name, "id": policy_id,
         "arn": _policy_arn(store, g["name"], policy_id, policy_name), "policy_type": policy_type,
         "cooldown": int(params.get("Cooldown") or 300),
         "estimated_instance_warmup": int(params.get("EstimatedInstanceWarmup") or 300)}
    if policy_type == "SimpleScaling":
        adj_type = str(params.get("AdjustmentType") or "ChangeInCapacity")
        if adj_type not in _ADJUSTMENT_TYPES:
            raise AsgError("ValidationError", f"AdjustmentType must be one of {sorted(_ADJUSTMENT_TYPES)}.")
        p["adjustment_type"] = adj_type
        p["scaling_adjustment"] = int(_req(params, "ScalingAdjustment"))
    elif policy_type == "StepScaling":
        adj_type = str(params.get("AdjustmentType") or "ChangeInCapacity")
        if adj_type not in _ADJUSTMENT_TYPES:
            raise AsgError("ValidationError", f"AdjustmentType must be one of {sorted(_ADJUSTMENT_TYPES)}.")
        p["adjustment_type"] = adj_type
        steps = []
        for s in _members(params, "StepAdjustments"):
            steps.append({"lower": float(s["MetricIntervalLowerBound"]) if s.get("MetricIntervalLowerBound") not in (None, "") else None,
                          "upper": float(s["MetricIntervalUpperBound"]) if s.get("MetricIntervalUpperBound") not in (None, "") else None,
                          "adjustment": int(s["ScalingAdjustment"])})
        if not steps:
            raise AsgError("ValidationError", "StepScaling requires at least one StepAdjustment.")
        steps.sort(key=lambda s: (s["lower"] is None, s["lower"] if s["lower"] is not None else 0))
        p["step_adjustments"] = steps
    else:  # TargetTrackingScaling
        target = next((v for k, v in params.items() if k.endswith("TargetTrackingConfiguration.TargetValue")), None)
        p["target_tracking_configuration"] = {"target_value": float(target) if target else 50.0}
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
    store.policies.pop(f"{gname}#{policy_name}", None)
    store.persist()
    return _success("DeletePolicy", "")


# ── scheduled actions (lazily evaluated, like this simulator's CloudWatch alarms) ──────
def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None


_DOW = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}


def _cron_field_match(expr: str, value: int, name_map: dict | None = None) -> bool:
    if expr == "*":
        return True
    for part in expr.split(","):
        part = part.strip().upper()
        if name_map and part in name_map:
            if name_map[part] == value:
                return True
            continue
        if "-" in part and part.lstrip("-").isdigit() is False:
            lo, hi = part.split("-", 1)
            if int(lo) <= value <= int(hi):
                return True
            continue
        if part.isdigit() and int(part) == value:
            return True
    return False


def _next_recurrence(expr: str, after: datetime) -> datetime | None:
    """5-field standard cron (minute hour day-of-month month day-of-week, Sun=0) — the
    format ASG's `Recurrence` field accepts. Bounded forward scan (~2 years of minutes)."""
    fields = expr.strip().split()
    if len(fields) != 5:
        return None
    minute, hour, dom, month, dow = fields
    t = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    for _ in range(2 * 366 * 24 * 60):
        if (_cron_field_match(minute, t.minute) and _cron_field_match(hour, t.hour)
                and _cron_field_match(dom, t.day) and _cron_field_match(month, t.month)
                and _cron_field_match(dow, (t.isoweekday() % 7), _DOW)):
            return t
        t += timedelta(minutes=1)
    return None


def _apply_due_scheduled_actions(store: AutoScalingStore) -> None:
    now = datetime.now(timezone.utc)
    changed = False
    for s in getattr(store, "scheduled_actions", {}).values():
        g = store.groups.get(s["group"])
        if g is None or s.get("done"):
            continue
        due = s.get("_next_due")
        if due is None:
            due = _parse_iso(s["start_time"]) if s.get("start_time") else None
            s["_next_due"] = due
        while due is not None and due <= now:
            if s.get("min_size") is not None:
                g["min"] = s["min_size"]
            if s.get("max_size") is not None:
                g["max"] = s["max_size"]
            desired = s["desired_capacity"] if s.get("desired_capacity") is not None else g["desired"]
            desired = max(g["min"], min(g["max"], desired))
            _reconcile(store, g, desired)
            changed = True
            s["last_executed"] = _iso(due.timestamp())
            if s.get("recurrence"):
                due = _next_recurrence(s["recurrence"], due)
                if s.get("end_time"):
                    end = _parse_iso(s["end_time"])
                    if end and due and due > end:
                        due = None
            else:
                s["done"] = True
                due = None
            s["_next_due"] = due
    if changed:
        store.persist()


def _op_put_scheduled_action(store: AutoScalingStore, params: dict) -> AsgResponse:
    g = _group_of(store, params)
    name = str(_req(params, "ScheduledActionName"))
    recurrence = params.get("Recurrence")
    start_time = params.get("StartTime")
    if not recurrence and not start_time:
        raise AsgError("ValidationError", "Either StartTime or Recurrence is required.")
    if recurrence and _next_recurrence(str(recurrence), datetime.now(timezone.utc) - timedelta(minutes=1)) is None:
        raise AsgError("ValidationError", f"Recurrence '{recurrence}' is not a valid 5-field cron expression.")
    store.scheduled_actions = getattr(store, "scheduled_actions", {})
    key = f"{g['name']}#{name}"
    s = {"group": g["name"], "name": name, "arn": _sched_arn(store, g["name"], name),
         "start_time": start_time, "end_time": params.get("EndTime"), "recurrence": recurrence,
         "min_size": int(params["MinSize"]) if "MinSize" in params else None,
         "max_size": int(params["MaxSize"]) if "MaxSize" in params else None,
         "desired_capacity": int(params["DesiredCapacity"]) if "DesiredCapacity" in params else None,
         "done": False, "_next_due": None}
    store.scheduled_actions[key] = s
    store.persist()
    return _success("PutScheduledUpdateGroupAction", "")


def _op_describe_scheduled_actions(store: AutoScalingStore, params: dict) -> AsgResponse:
    _apply_due_scheduled_actions(store)
    gname = params.get("AutoScalingGroupName")
    names = set(_members(params, "ScheduledActionNames"))
    rows = [s for s in getattr(store, "scheduled_actions", {}).values()
            if (not gname or s["group"] == gname) and (not names or s["name"] in names)]
    return _success("DescribeScheduledActions", f"<ScheduledUpdateGroupActions>{''.join(_sched_xml(s) for s in rows)}</ScheduledUpdateGroupActions>")


def _op_delete_scheduled_action(store: AutoScalingStore, params: dict) -> AsgResponse:
    gname = str(_req(params, "AutoScalingGroupName"))
    name = str(_req(params, "ScheduledActionName"))
    getattr(store, "scheduled_actions", {}).pop(f"{gname}#{name}", None)
    store.persist()
    return _success("DeleteScheduledAction", "")


# ── lifecycle hooks ──────────────────────────────────────────────────────────
_TRANSITIONS = {"autoscaling:EC2_INSTANCE_LAUNCHING", "autoscaling:EC2_INSTANCE_TERMINATING"}


def _op_put_lifecycle_hook(store: AutoScalingStore, params: dict) -> AsgResponse:
    g = _group_of(store, params)
    name = str(_req(params, "LifecycleHookName"))
    transition = str(params.get("LifecycleTransition") or "")
    store.lifecycle_hooks = getattr(store, "lifecycle_hooks", {})
    key = f"{g['name']}#{name}"
    existing = store.lifecycle_hooks.get(key)
    if not transition and existing:
        transition = existing["transition"]
    if transition not in _TRANSITIONS:
        raise AsgError("ValidationError", f"LifecycleTransition must be one of {sorted(_TRANSITIONS)}.")
    h = {"group": g["name"], "name": name, "transition": transition,
         "default_result": str(params.get("DefaultResult") or "ABANDON"),
         "heartbeat_timeout": int(params.get("HeartbeatTimeout") or 3600),
         "global_timeout": int(params.get("GlobalTimeout") or 172800)}
    store.lifecycle_hooks[key] = h
    store.persist()
    return _success("PutLifecycleHook", "")


def _op_describe_lifecycle_hooks(store: AutoScalingStore, params: dict) -> AsgResponse:
    gname = str(_req(params, "AutoScalingGroupName"))
    names = set(_members(params, "LifecycleHookNames"))
    rows = [h for h in getattr(store, "lifecycle_hooks", {}).values() if h["group"] == gname and (not names or h["name"] in names)]
    return _success("DescribeLifecycleHooks", f"<LifecycleHooks>{''.join(_hook_xml(h) for h in rows)}</LifecycleHooks>")


def _op_delete_lifecycle_hook(store: AutoScalingStore, params: dict) -> AsgResponse:
    gname = str(_req(params, "AutoScalingGroupName"))
    name = str(_req(params, "LifecycleHookName"))
    getattr(store, "lifecycle_hooks", {}).pop(f"{gname}#{name}", None)
    store.persist()
    return _success("DeleteLifecycleHook", "")


def _op_record_lifecycle_heartbeat(store: AutoScalingStore, params: dict) -> AsgResponse:
    g = _group_of(store, params)
    name = str(_req(params, "LifecycleHookName"))
    hook = getattr(store, "lifecycle_hooks", {}).get(f"{g['name']}#{name}")
    if hook is None:
        raise AsgError("ValidationError", f"Lifecycle hook '{name}' not found.")
    iid = params.get("InstanceId")
    if iid and iid not in g["instance_ids"]:
        raise AsgError("ValidationError", f"Instance '{iid}' is not part of AutoScalingGroup '{g['name']}'.")
    return _success("RecordLifecycleActionHeartbeat", "")


def _op_complete_lifecycle_action(store: AutoScalingStore, params: dict) -> AsgResponse:
    from core import vpc_core as _vpc_mod
    g = _group_of(store, params)
    name = str(_req(params, "LifecycleHookName"))
    iid = str(_req(params, "InstanceId"))
    hook = getattr(store, "lifecycle_hooks", {}).get(f"{g['name']}#{name}")
    if hook is None:
        raise AsgError("ValidationError", f"Lifecycle hook '{name}' not found.")
    state = g.get("lifecycle", {}).get(iid)
    if state == "Pending:Wait":
        result = str(params.get("LifecycleActionResult") or "CONTINUE")
        g["lifecycle"].pop(iid, None)
        if result == "ABANDON" and store.vpc_store is not None:
            if iid in g["instance_ids"]:
                g["instance_ids"].remove(iid)
            _vpc_mod.terminate_for_autoscaling(store.vpc_store, iid)
            _reconcile(store, g, g["desired"])  # backfill the abandoned slot
    elif state == "Terminating:Wait":
        g["lifecycle"].pop(iid, None)
        if iid in g["instance_ids"]:
            g["instance_ids"].remove(iid)
        if store.vpc_store is not None:
            _vpc_mod.terminate_for_autoscaling(store.vpc_store, iid)
    else:
        raise AsgError("ValidationError", f"Instance '{iid}' has no pending lifecycle action for hook '{name}'.")
    store.persist()
    return _success("CompleteLifecycleAction", "")


# ── instance refresh ─────────────────────────────────────────────────────────
def _op_start_instance_refresh(store: AutoScalingStore, params: dict) -> AsgResponse:
    from core import vpc_core as _vpc_mod
    g = _group_of(store, params)
    store.instance_refreshes = getattr(store, "instance_refreshes", [])
    if any(r["group"] == g["name"] and r["status"] == "InProgress" for r in store.instance_refreshes):
        raise AsgError("InstanceRefreshInProgress", f"An instance refresh is already in progress for '{g['name']}'.")
    refresh_id = str(uuid.uuid4())
    instances_to_update = len(g["instance_ids"])
    # Executed eagerly: Vyomi has no background scheduler to spread the rollout over time
    # (see ec2.auto-scaling's limitations), so every instance is replaced immediately.
    old_ids = list(g["instance_ids"])
    for iid in old_ids:
        if iid in g["instance_ids"]:
            g["instance_ids"].remove(iid)
        g.get("lifecycle", {}).pop(iid, None)
        if store.vpc_store is not None:
            _vpc_mod.terminate_for_autoscaling(store.vpc_store, iid)
    _reconcile(store, g, g["desired"])
    r = {"id": refresh_id, "group": g["name"], "status": "Successful", "percentage_complete": 100,
         "instances_to_update": instances_to_update, "start_time": _iso(_now()), "end_time": _iso(_now())}
    store.instance_refreshes.insert(0, r)
    store.persist()
    return _success("StartInstanceRefresh", f"{_el('InstanceRefreshId', refresh_id)}")


def _op_describe_instance_refreshes(store: AutoScalingStore, params: dict) -> AsgResponse:
    gname = str(_req(params, "AutoScalingGroupName"))
    rows = [r for r in getattr(store, "instance_refreshes", []) if r["group"] == gname]
    return _success("DescribeInstanceRefreshes", f"<InstanceRefreshes>{''.join(_refresh_xml(r) for r in rows)}</InstanceRefreshes>")


def _op_cancel_instance_refresh(store: AutoScalingStore, params: dict) -> AsgResponse:
    gname = str(_req(params, "AutoScalingGroupName"))
    in_progress = [r for r in getattr(store, "instance_refreshes", []) if r["group"] == gname and r["status"] == "InProgress"]
    if not in_progress:
        raise AsgError("ActiveInstanceRefreshNotFound", f"No in-progress instance refresh found for AutoScalingGroup '{gname}'.")
    for r in in_progress:
        r["status"] = "Cancelled"
    store.persist()
    return _success("CancelInstanceRefresh", f"{_el('InstanceRefreshId', in_progress[0]['id'])}")


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


def _reconcile(store: AutoScalingStore, g: dict, new_desired: int, respect_hooks: bool = True) -> None:
    """Make the group's real EC2 instance count match `new_desired`, through the same
    instance lifecycle RunInstances/TerminateInstances use (vpc_core.py) — a scaled group's
    instances are indistinguishable from any other EC2 instance in the console. A configured
    launch/terminate lifecycle hook really holds the transition at Pending:Wait /
    Terminating:Wait instead of completing it immediately (see ec2.auto-scaling)."""
    from core import vpc_core as _vpc_mod
    g["desired"] = new_desired
    g.setdefault("lifecycle", {})
    if store.vpc_store is None:
        return
    hooks = [h for h in getattr(store, "lifecycle_hooks", {}).values() if h["group"] == g["name"]] if respect_hooks else []
    launch_hook = next((h for h in hooks if h["transition"] == "autoscaling:EC2_INSTANCE_LAUNCHING"), None)
    terminate_hook = next((h for h in hooks if h["transition"] == "autoscaling:EC2_INSTANCE_TERMINATING"), None)
    settled = [i for i in g["instance_ids"] if g["lifecycle"].get(i) != "Terminating:Wait"]
    current = len(settled)
    if new_desired > current:
        for _ in range(new_desired - current):
            az = g["azs"][len(g["instance_ids"]) % len(g["azs"])] if g["azs"] else None
            iid = _vpc_mod.launch_for_autoscaling(
                store.vpc_store, az=az, instance_type=g.get("instance_type"), image_id=g.get("image_id"),
                subnet_id=(g.get("subnet_ids") or [None])[len(g["instance_ids"]) % len(g["subnet_ids"])] if g.get("subnet_ids") else None,
                security_group_ids=g.get("security_group_ids"), key_name=g.get("key_name"),
                tags={"Name": f"{g['name']}-instance", "aws:autoscaling:groupName": g["name"]})
            g["instance_ids"].append(iid)
            if launch_hook is not None:
                g["lifecycle"][iid] = "Pending:Wait"
    elif new_desired < current:
        for _ in range(current - new_desired):
            candidates = [i for i in g["instance_ids"] if g["lifecycle"].get(i) != "Terminating:Wait"]
            if not candidates:
                break
            iid = candidates[-1]
            if terminate_hook is not None:
                g["lifecycle"][iid] = "Terminating:Wait"
            else:
                g["instance_ids"].remove(iid)
                g["lifecycle"].pop(iid, None)
                _vpc_mod.terminate_for_autoscaling(store.vpc_store, iid)


def execute_policy_arn(store: AutoScalingStore, policy_arn: str) -> bool:
    """Called by cloudwatch_core when a CloudWatch alarm fires an Auto Scaling action ARN
    (arn:...:autoscaling:...:scalingPolicy:...) — see aws.cloudwatch.alarms.actions.compute.
    Really adjusts the group's desired capacity (clamped to MinSize/MaxSize) and reconciles
    real EC2 instances to match, exactly as AWS's Auto Scaling service does under an alarm.
    Vyomi's alarm trigger carries no breach magnitude: StepScaling applies its first
    (smallest-breach) step, and TargetTrackingScaling nudges desired capacity by one instance
    toward the target instead of continuously tracking a live metric value."""
    p = next((p for p in store.policies.values() if p["arn"] == policy_arn), None)
    if p is None:
        return False
    g = store.groups.get(p["group"])
    if g is None:
        return False
    current = g["desired"]
    if p["policy_type"] == "TargetTrackingScaling":
        new_desired = current + 1
    elif p["policy_type"] == "StepScaling":
        step = p["step_adjustments"][0]
        new_desired = current + step["adjustment"] if p["adjustment_type"] != "ExactCapacity" else step["adjustment"]
    elif p["adjustment_type"] == "ExactCapacity":
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
    "DescribeAutoScalingInstances": _op_describe_instances,
    "UpdateAutoScalingGroup": _op_update_group,
    "SetDesiredCapacity": _op_set_desired_capacity,
    "DeleteAutoScalingGroup": _op_delete_group,
    "PutScalingPolicy": _op_put_scaling_policy,
    "DescribePolicies": _op_describe_policies,
    "DeletePolicy": _op_delete_policy,
    "PutScheduledUpdateGroupAction": _op_put_scheduled_action,
    "DescribeScheduledActions": _op_describe_scheduled_actions,
    "DeleteScheduledAction": _op_delete_scheduled_action,
    "PutLifecycleHook": _op_put_lifecycle_hook,
    "DescribeLifecycleHooks": _op_describe_lifecycle_hooks,
    "DeleteLifecycleHook": _op_delete_lifecycle_hook,
    "RecordLifecycleActionHeartbeat": _op_record_lifecycle_heartbeat,
    "CompleteLifecycleAction": _op_complete_lifecycle_action,
    "StartInstanceRefresh": _op_start_instance_refresh,
    "DescribeInstanceRefreshes": _op_describe_instance_refreshes,
    "CancelInstanceRefresh": _op_cancel_instance_refresh,
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
