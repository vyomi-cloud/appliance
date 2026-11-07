"""Application Auto Scaling for DynamoDB (service `application-autoscaling`, JSON 1.1, X-Amz-Target `AnyScaleFrontendService.*`).

Substrate-independent (no fastapi / boto3 / socket imports; loads under Pyodide). Implements the real control plane for
the `dynamodb` service namespace: RegisterScalableTarget / DeregisterScalableTarget / DescribeScalableTargets,
PutScalingPolicy / DeleteScalingPolicy / DescribeScalingPolicies, DescribeScalingActivities.

The scaling is REAL: a TargetTrackingScaling policy reads the table's `ConsumedReadCapacityUnits` /
`ConsumedWriteCapacityUnits` CloudWatch datapoints (the ones DynamoDB emits for every request), computes utilisation against
the provisioned capacity per one-minute period and, exactly like the alarms Application Auto Scaling creates, scales OUT
after 3 consecutive minutes above the target and scales IN after 15 consecutive minutes below (target - 20 points). The new
capacity is applied to the table through the same UpdateTable path (so throttling immediately uses it), clamped to the
scalable target's Min/MaxCapacity and honouring cooldowns, DisableScaleIn and SuspendedState. Every change is recorded as a
scaling activity.

State lives on the table record (`table["appas"]`), so it persists with the table.

Honest limits: evaluation is driven by `evaluate()` which runs on every Application Auto Scaling call and on DynamoDB
DescribeTable / UpdateTable (the console also polls it), not by a background clock; the CloudWatch alarms real Application
Auto Scaling creates for a policy are not materialised (the policy's `Alarms` list is empty); StepScaling policies are stored
and describable but never invoked automatically; scheduled actions, tags, custom-metric tracking and the non-DynamoDB
namespaces (ecs, ec2, lambda, ...) are not implemented; the DynamoDB per-day capacity-decrease quota is not modelled.
"""
from __future__ import annotations

import math
import re
import time
import uuid

try:
    from core import dynamodb_core as _ddb
    from core import cloudwatch_core as _cw_core
except ImportError:  # pragma: no cover - Pyodide flat layout
    import dynamodb_core as _ddb  # type: ignore
    import cloudwatch_core as _cw_core  # type: ignore

_ACCOUNT = "123456789012"
_REGION = "us-east-1"
TARGET_PREFIX = "AnyScaleFrontendService"
_NAMESPACES = ("ecs", "elasticmapreduce", "ec2", "appstream", "dynamodb", "rds", "sagemaker", "custom-resource", "comprehend",
               "lambda", "cassandra", "kafka", "elasticache", "neptune", "workspaces")
_DIMS = {
    "dynamodb:table:ReadCapacityUnits": ("table", "read"),
    "dynamodb:table:WriteCapacityUnits": ("table", "write"),
    "dynamodb:index:ReadCapacityUnits": ("index", "read"),
    "dynamodb:index:WriteCapacityUnits": ("index", "write"),
}
_PREDEFINED = {"DynamoDBReadCapacityUtilization": "read", "DynamoDBWriteCapacityUtilization": "write"}
_OUT_MINUTES = 3
_IN_MINUTES = 15
_IN_MARGIN = 20.0
_RES_RE = re.compile(r"^table/([A-Za-z0-9_.-]{3,255})(?:/index/([A-Za-z0-9_.-]{3,255}))?$")


class AppAsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status


class AppAsResponse:
    def __init__(self, status: int = 200, body: dict | None = None, headers: dict | None = None) -> None:
        self.status, self.body, self.headers = status, body or {}, headers or {}


def _bad(msg: str) -> AppAsError:
    return AppAsError("ValidationException", msg, 400)


def _state(table: dict) -> dict:
    st = table.setdefault("appas", {})
    st.setdefault("targets", {})       # dimension -> target record (resource is the table / index)
    st.setdefault("policies", {})      # (dimension, name) -> record, keyed "dimension|name"
    st.setdefault("activities", [])    # newest first
    return st


def _resolve(store, ns: str, rid: str, dim: str, *, must_exist: bool = True):
    """Validate the (namespace, resource, dimension) triple the way the real service does; returns (table, index_name|None)."""
    if ns not in _NAMESPACES:
        raise _bad(f"1 validation error detected: Value '{ns}' at 'serviceNamespace' failed to satisfy constraint: "
                   f"Member must satisfy enum value set: {sorted(_NAMESPACES)}")
    if ns != "dynamodb":
        raise _bad(f"The service namespace '{ns}' is not implemented by this simulator; only 'dynamodb' is supported.")
    if dim not in _DIMS:
        raise _bad(f"Invalid scalable dimension '{dim}' for service namespace 'dynamodb'. "
                   f"Supported: {sorted(_DIMS)}")
    m = _RES_RE.match(rid or "")
    if not m:
        raise _bad(f"Invalid resource ID '{rid}' for dynamodb. Expected table/<name> or table/<name>/index/<index>.")
    kind = _DIMS[dim][0]
    if (kind == "index") != bool(m.group(2)):
        raise _bad(f"Scalable dimension '{dim}' does not match resource ID '{rid}'.")
    table = store.get_table(m.group(1))
    if table is None:
        if must_exist:
            raise _bad(f"Unable to find the DynamoDB table '{m.group(1)}' referenced by resource ID '{rid}'.")
        return None, m.group(2)
    if m.group(2) and not any(g.get("name") == m.group(2) for g in table.get("indexes", [])):
        if must_exist:
            raise _bad(f"Unable to find the global secondary index '{m.group(2)}' on table '{m.group(1)}'.")
    return table, m.group(2)


def _key(rid: str, dim: str) -> str:
    return f"{rid}|{dim}"


def _target_arn(rid: str, dim: str) -> str:
    return f"arn:aws:application-autoscaling:{_REGION}:{_ACCOUNT}:scalable-target/{uuid.uuid5(uuid.NAMESPACE_URL, rid + dim).hex[:36]}"


def _capacity(table: dict, index: str | None, kind: str) -> int:
    pt = table.get("provisioned_throughput") or {}
    if index:
        for g in table.get("indexes", []):
            if g.get("name") == index:
                pt = g.get("provisioned_throughput") or pt
    return int(pt.get("ReadCapacityUnits" if kind == "read" else "WriteCapacityUnits", 5) or 5)


def _set_capacity(store, table: dict, index: str | None, kind: str, units: int) -> None:
    field = "ReadCapacityUnits" if kind == "read" else "WriteCapacityUnits"
    if index:
        g = next(g for g in table["indexes"] if g.get("name") == index)
        cur = g.get("provisioned_throughput") or table.get("provisioned_throughput", {})
        g["provisioned_throughput"] = {"ReadCapacityUnits": int(cur.get("ReadCapacityUnits", 5)),
                                       "WriteCapacityUnits": int(cur.get("WriteCapacityUnits", 5)), field: int(units)}
        table["last_modified"] = _ddb._now()
        store.persist()
        return
    cur = table.get("provisioned_throughput") or {}
    pt = {"ReadCapacityUnits": int(cur.get("ReadCapacityUnits", 5)), "WriteCapacityUnits": int(cur.get("WriteCapacityUnits", 5))}
    pt[field] = int(units)
    _ddb._update_table_record(store, table, {"ProvisionedThroughput": pt})


def _activity(st: dict, rid: str, dim: str, desc: str, cause: str, ok: bool, msg: str, now: float) -> None:
    st["activities"].insert(0, {
        "ActivityId": str(uuid.uuid4()), "ServiceNamespace": "dynamodb", "ResourceId": rid, "ScalableDimension": dim,
        "Description": desc, "Cause": cause, "StartTime": now, "EndTime": now,
        "StatusCode": "Successful" if ok else "Failed", "StatusMessage": msg,
    })
    del st["activities"][200:]


def _minute_sums(cw, table_name: str, index: str | None, kind: str, now: float, minutes: int) -> list[float]:
    """Consumed units per minute for the last `minutes` complete-or-current minutes, oldest first (missing minutes are 0)."""
    metric = "ConsumedReadCapacityUnits" if kind == "read" else "ConsumedWriteCapacityUnits"
    dims = [{"Name": "TableName", "Value": table_name}]
    if index:
        dims = sorted(dims + [{"Name": "GlobalSecondaryIndexName", "Value": index}], key=lambda d: d["Name"])
    s = _cw_core._series(cw, "AWS/DynamoDB", metric, dims) if cw is not None else None
    out = [0.0] * minutes
    if not s:
        return out
    end_min = int(now // 60)
    for p in s["points"]:
        idx = int(p[0] // 60) - (end_min - minutes + 1)
        if 0 <= idx < minutes:
            out[idx] += float(p[1])
    return out


def _evaluate_target(store, table: dict, st: dict, dim: str, rid: str, now: float) -> None:
    tgt = st["targets"].get(_key(rid, dim))
    if not tgt or str(table.get("billing_mode", "")).upper() == "PAY_PER_REQUEST":
        return
    kind_idx, kind = _DIMS[dim]
    index = _RES_RE.match(rid).group(2)
    cw = getattr(store, "cw_store", None)
    sus = tgt.get("SuspendedState") or {}
    for pol in [p for k, p in st["policies"].items() if k.startswith(_key(rid, dim) + "|") and p["PolicyType"] == "TargetTrackingScaling"]:
        cfg = pol["TargetTrackingScalingPolicyConfiguration"]
        target = float(cfg["TargetValue"])
        cur = _capacity(table, index, kind)
        if cur <= 0:
            continue
        last = pol.get("_last", {})
        age = now - pol["_created"]
        out_rates = [x / 60.0 for x in _minute_sums(cw, table["table_name"], index, kind, now, _OUT_MINUTES)]
        in_rates = [x / 60.0 for x in _minute_sums(cw, table["table_name"], index, kind, now, _IN_MINUTES)]
        new = None
        direction = None
        if age >= _OUT_MINUTES * 60 and not sus.get("DynamicScalingOutSuspended") and \
                all(r / cur * 100.0 > target for r in out_rates):
            new = math.ceil(max(out_rates) / (target / 100.0))
            direction = "out"
            if now - last.get("out", -1e18) < float(cfg.get("ScaleOutCooldown", 0)):
                new = None
        elif age >= _IN_MINUTES * 60 and not sus.get("DynamicScalingInSuspended") and not cfg.get("DisableScaleIn") and \
                all(r / cur * 100.0 < target - _IN_MARGIN for r in in_rates):
            new = math.ceil(max(in_rates) / (target / 100.0))
            direction = "in"
            if now - last.get("in", -1e18) < float(cfg.get("ScaleInCooldown", 0)):
                new = None
        if new is None:
            continue
        new = max(int(tgt["MinCapacity"]), min(int(tgt["MaxCapacity"]), max(1, new)))
        if new == cur or (direction == "out" and new < cur) or (direction == "in" and new > cur):
            continue
        what = ("read" if kind == "read" else "write") + " capacity units"
        _set_capacity(store, table, index, kind, new)
        pol.setdefault("_last", {})[direction] = now
        _activity(st, rid, dim, f"Setting {what} to {new}.",
                  f"monitor alarm TargetTracking-{rid}-Alarm{'High' if direction == 'out' else 'Low'}-{pol['_uid']} in state ALARM "
                  f"triggered policy {pol['PolicyName']}",
                  True, f"Successfully set {what} to {new}. Change successfully fulfilled by dynamodb.", now)


def evaluate(store, now: float | None = None) -> int:
    """Run every registered target's scaling policies once. Returns how many capacity changes were applied."""
    now = time.time() if now is None else float(now)
    changes = 0
    for table in list(store.tables.values()):
        st = table.get("appas")
        if not st or not st["targets"]:
            continue
        before = len(st["activities"])
        for tk in list(st["targets"]):
            rid, dim = tk.split("|", 1)
            _evaluate_target(store, table, st, dim, rid, now)
        changes += len(st["activities"]) - before
    return changes


# ── operations ────────────────────────────────────────────────────────────
def _req(p: dict, name: str):
    v = p.get(name)
    if v in (None, ""):
        raise _bad(f"1 validation error detected: Value null at '{name[0].lower() + name[1:]}' failed to satisfy constraint: "
                   "Member must not be null")
    return v


def _target_view(rid: str, dim: str, t: dict) -> dict:
    return {"ServiceNamespace": "dynamodb", "ResourceId": rid, "ScalableDimension": dim, "MinCapacity": t["MinCapacity"],
            "MaxCapacity": t["MaxCapacity"], "RoleARN": t["RoleARN"], "CreationTime": t["CreationTime"],
            "SuspendedState": t.get("SuspendedState") or {"DynamicScalingInSuspended": False, "DynamicScalingOutSuspended": False,
                                                          "ScheduledScalingSuspended": False},
            "ScalableTargetARN": _target_arn(rid, dim)}


def op_register_scalable_target(store, p, now):
    ns, rid, dim = str(_req(p, "ServiceNamespace")), str(_req(p, "ResourceId")), str(_req(p, "ScalableDimension"))
    table, index = _resolve(store, ns, rid, dim)
    st = _state(table)
    k = _key(rid, dim)
    old = st["targets"].get(k)
    if "MinCapacity" not in p and "MaxCapacity" not in p and not old:
        raise _bad("MinCapacity and MaxCapacity are required when registering a scalable target for the first time.")
    mn = int(p.get("MinCapacity", old["MinCapacity"] if old else 0))
    mx = int(p.get("MaxCapacity", old["MaxCapacity"] if old else 0))
    if mn < 0 or mx < 0:
        raise _bad("MinCapacity and MaxCapacity must be non-negative.")
    if mn > mx:
        raise _bad(f"MinCapacity ({mn}) cannot be greater than MaxCapacity ({mx}).")
    if str(table.get("billing_mode", "")).upper() == "PAY_PER_REQUEST":
        raise _bad(f"Table '{table['table_name']}' uses on-demand capacity; auto scaling applies to PROVISIONED tables only.")
    rec = old or {"CreationTime": now, "RoleARN": p.get("RoleARN") or
                  f"arn:aws:iam::{_ACCOUNT}:role/aws-service-role/dynamodb.application-autoscaling.amazonaws.com/"
                  "AWSServiceRoleForApplicationAutoScaling_DynamoDBTable"}
    rec["MinCapacity"], rec["MaxCapacity"] = mn, mx
    if p.get("RoleARN"):
        rec["RoleARN"] = p["RoleARN"]
    if isinstance(p.get("SuspendedState"), dict):
        rec["SuspendedState"] = {"DynamicScalingInSuspended": bool(p["SuspendedState"].get("DynamicScalingInSuspended")),
                                 "DynamicScalingOutSuspended": bool(p["SuspendedState"].get("DynamicScalingOutSuspended")),
                                 "ScheduledScalingSuspended": bool(p["SuspendedState"].get("ScheduledScalingSuspended"))}
    st["targets"][k] = rec
    kind = _DIMS[dim][1]
    cur = _capacity(table, index, kind)
    clamped = max(mn, min(mx, cur))
    if clamped != cur and clamped > 0:       # real service: capacity outside the new range is pulled inside it
        what = f"{kind} capacity units"
        _set_capacity(store, table, index, kind, clamped)
        _activity(st, rid, dim, f"Setting {what} to {clamped}.",
                  f"minimum capacity was set to {mn}" if clamped > cur else f"maximum capacity was set to {mx}",
                  True, f"Successfully set {what} to {clamped}. Change successfully fulfilled by dynamodb.", now)
    store.persist()
    return {"ScalableTargetARN": _target_arn(rid, dim)}


def op_deregister_scalable_target(store, p, now):
    ns, rid, dim = str(_req(p, "ServiceNamespace")), str(_req(p, "ResourceId")), str(_req(p, "ScalableDimension"))
    table, _ = _resolve(store, ns, rid, dim, must_exist=False)
    k = _key(rid, dim)
    st = table.get("appas") if table else None
    if not st or k not in st["targets"]:
        raise AppAsError("ObjectNotFoundException", f"No scalable target found for service namespace: {ns}, resource ID: {rid}, "
                         f"scalable dimension: {dim}", 400)
    del st["targets"][k]
    for pk in [pk for pk in st["policies"] if pk.startswith(k + "|")]:     # deregistering removes the policies with it
        del st["policies"][pk]
    store.persist()
    return {}


def _page(items: list, p: dict):
    n = int(p.get("MaxResults") or 50)
    if n < 1 or n > 50:
        raise _bad("MaxResults must be between 1 and 50.")
    start = int(p["NextToken"]) if str(p.get("NextToken") or "").isdigit() else 0
    out = {"items": items[start:start + n]}
    if start + n < len(items):
        out["NextToken"] = str(start + n)
    return out


def _scan(store, p: dict):
    ns = str(_req(p, "ServiceNamespace"))
    if ns not in _NAMESPACES:
        raise _bad(f"Value '{ns}' at 'serviceNamespace' failed to satisfy constraint: Member must satisfy enum value set.")
    rids = p.get("ResourceIds") or []
    dim = p.get("ScalableDimension")
    for t in store.tables.values():
        st = t.get("appas")
        if not st or ns != "dynamodb":
            continue
        yield t, st


def op_describe_scalable_targets(store, p, now):
    rows = []
    for t, st in _scan(store, p):
        for k, rec in st["targets"].items():
            rid, dim = k.split("|", 1)
            if (not p.get("ResourceIds") or rid in p["ResourceIds"]) and (not p.get("ScalableDimension") or dim == p["ScalableDimension"]):
                rows.append(_target_view(rid, dim, rec))
    pg = _page(sorted(rows, key=lambda r: (r["ResourceId"], r["ScalableDimension"])), p)
    return {"ScalableTargets": pg["items"], **({"NextToken": pg["NextToken"]} if "NextToken" in pg else {})}


def _policy_view(rid, dim, rec):
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    out.update({"ServiceNamespace": "dynamodb", "ResourceId": rid, "ScalableDimension": dim, "Alarms": [], "CreationTime": rec["_created"]})
    return out


def op_put_scaling_policy(store, p, now):
    name = str(_req(p, "PolicyName"))
    ns, rid, dim = str(_req(p, "ServiceNamespace")), str(_req(p, "ResourceId")), str(_req(p, "ScalableDimension"))
    if not re.match(r"^[\w\-/.:#+=@ ]{1,256}$", name):
        raise _bad("PolicyName must be 1-256 characters.")
    table, index = _resolve(store, ns, rid, dim)
    st = _state(table)
    if _key(rid, dim) not in st["targets"]:
        raise AppAsError("ObjectNotFoundException", f"No scalable target registered for service namespace: {ns}, resource ID: {rid}, "
                         f"scalable dimension: {dim}", 400)
    ptype = str(p.get("PolicyType") or "StepScaling")
    if ptype not in ("StepScaling", "TargetTrackingScaling"):
        raise _bad(f"PolicyType '{ptype}' is not supported for the dynamodb namespace (use TargetTrackingScaling or StepScaling).")
    pk = f"{_key(rid, dim)}|{name}"
    old = st["policies"].get(pk)
    rec = {"PolicyName": name, "PolicyType": ptype, "_created": old["_created"] if old else now,
           "_uid": old["_uid"] if old else uuid.uuid4().hex[:8], "_last": old.get("_last", {}) if old else {}}
    rec["PolicyARN"] = old["PolicyARN"] if old else (
        f"arn:aws:autoscaling:{_REGION}:{_ACCOUNT}:scalingPolicy:{uuid.uuid4()}:resource/dynamodb/{rid}:policyName/{name}")
    if ptype == "TargetTrackingScaling":
        cfg = p.get("TargetTrackingScalingPolicyConfiguration")
        if not isinstance(cfg, dict):
            raise _bad("TargetTrackingScalingPolicyConfiguration is required for TargetTrackingScaling policies.")
        if "TargetValue" not in cfg:
            raise _bad("TargetTrackingScalingPolicyConfiguration.TargetValue is required.")
        tv = float(cfg["TargetValue"])
        if not (0 < tv <= 100):
            raise _bad("TargetValue must be greater than 0 and no more than 100 for DynamoDB utilization metrics.")
        pm = cfg.get("PredefinedMetricSpecification")
        if not isinstance(pm, dict) or "PredefinedMetricType" not in pm:
            raise _bad("A PredefinedMetricSpecification is required (custom-metric tracking is not implemented by this simulator).")
        want = _DIMS[dim][1]
        if _PREDEFINED.get(pm["PredefinedMetricType"]) != want:
            raise _bad(f"PredefinedMetricType '{pm['PredefinedMetricType']}' is not valid for scalable dimension '{dim}'.")
        for c in ("ScaleInCooldown", "ScaleOutCooldown"):
            if c in cfg and int(cfg[c]) < 0:
                raise _bad(f"{c} must be non-negative.")
        rec["TargetTrackingScalingPolicyConfiguration"] = {k: v for k, v in cfg.items()
                                                          if k in ("TargetValue", "PredefinedMetricSpecification", "ScaleInCooldown",
                                                                   "ScaleOutCooldown", "DisableScaleIn")}
        rec["TargetTrackingScalingPolicyConfiguration"].setdefault("ScaleInCooldown", 0)
        rec["TargetTrackingScalingPolicyConfiguration"].setdefault("ScaleOutCooldown", 0)
    else:
        cfg = p.get("StepScalingPolicyConfiguration")
        if not isinstance(cfg, dict) or not cfg.get("StepAdjustments"):
            raise _bad("StepScalingPolicyConfiguration with at least one StepAdjustment is required for StepScaling policies.")
        rec["StepScalingPolicyConfiguration"] = cfg
    st["policies"][pk] = rec
    store.persist()
    return {"PolicyARN": rec["PolicyARN"], "Alarms": []}


def op_delete_scaling_policy(store, p, now):
    name = str(_req(p, "PolicyName"))
    ns, rid, dim = str(_req(p, "ServiceNamespace")), str(_req(p, "ResourceId")), str(_req(p, "ScalableDimension"))
    table, _ = _resolve(store, ns, rid, dim, must_exist=False)
    st = table.get("appas") if table else None
    pk = f"{_key(rid, dim)}|{name}"
    if not st or pk not in st["policies"]:
        raise AppAsError("ObjectNotFoundException", f"No scaling policy found for service namespace: {ns}, resource ID: {rid}, "
                         f"scalable dimension: {dim}, policy name: {name}", 400)
    del st["policies"][pk]
    store.persist()
    return {}


def op_describe_scaling_policies(store, p, now):
    rows = []
    for t, st in _scan(store, p):
        for pk, rec in st["policies"].items():
            rid, dim, name = pk.split("|", 2)
            if (not p.get("ResourceId") or rid == p["ResourceId"]) and (not p.get("ScalableDimension") or dim == p["ScalableDimension"]) \
                    and (not p.get("PolicyNames") or name in p["PolicyNames"]):
                rows.append(_policy_view(rid, dim, rec))
    pg = _page(sorted(rows, key=lambda r: (r["ResourceId"], r["PolicyName"])), p)
    return {"ScalingPolicies": pg["items"], **({"NextToken": pg["NextToken"]} if "NextToken" in pg else {})}


def op_describe_scaling_activities(store, p, now):
    rows = []
    for t, st in _scan(store, p):
        for a in st["activities"]:
            if (not p.get("ResourceId") or a["ResourceId"] == p["ResourceId"]) and \
                    (not p.get("ScalableDimension") or a["ScalableDimension"] == p["ScalableDimension"]):
                rows.append(a)
    rows.sort(key=lambda a: -a["StartTime"])
    pg = _page(rows, p)
    return {"ScalingActivities": pg["items"], **({"NextToken": pg["NextToken"]} if "NextToken" in pg else {})}


_OPS = {
    "RegisterScalableTarget": op_register_scalable_target, "DeregisterScalableTarget": op_deregister_scalable_target,
    "DescribeScalableTargets": op_describe_scalable_targets, "PutScalingPolicy": op_put_scaling_policy,
    "DeleteScalingPolicy": op_delete_scaling_policy, "DescribeScalingPolicies": op_describe_scaling_policies,
    "DescribeScalingActivities": op_describe_scaling_activities,
}


def dispatch(store, target: str, payload: dict, now: float | None = None) -> AppAsResponse:
    """`store` is the DynamoDB NoSqlStore. `target` is the X-Amz-Target header (`AnyScaleFrontendService.<Op>`)."""
    now = time.time() if now is None else float(now)
    op = (target or "").split(".", 1)[-1]
    fn = _OPS.get(op)
    if fn is None:
        return AppAsResponse(400, {"__type": "UnknownOperationException", "message": f"Operation {op} is not implemented by this simulator."})
    try:
        evaluate(store, now)
        return AppAsResponse(200, fn(store, payload or {}, now))
    except AppAsError as e:
        return AppAsResponse(e.status, {"__type": e.code, "message": e.message})
    except (ValueError, TypeError) as e:
        return AppAsResponse(400, {"__type": "ValidationException", "message": f"Invalid request: {e}"})
