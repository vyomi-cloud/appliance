"""Amazon Data Lifecycle Manager core — automated EBS snapshot / AMI policies
(ec2.lifecycle-manager). A policy with an ENABLED state and a real schedule
really creates snapshots/AMIs for every EBS volume / EC2 instance tagged with its
TargetTags, through the SAME CreateSnapshot/CreateImage path the console's
"Create snapshot now" button uses (core/vpc_core.py) — and really prunes old
snapshots/AMIs past RetainRule.Count. Evaluated lazily (on every read, like this
simulator's CloudWatch alarms and Auto Scaling's scheduled actions) rather than by
a live background clock: no DLM "schedule window" (Times-of-day) is modeled, only
the Interval/IntervalUnit cadence.

Speaks the native DLM **REST JSON** wire (`POST /policies`, `GET /policies`,
`GET/PATCH/DELETE /policies/{policyId}`) so an unmodified boto3 `dlm` client
works. NO fastapi / boto3 / socket imports → loads under Pyodide.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field

DEFAULT_ACCOUNT_ID = "123456789012"
REGION = "us-east-1"
_STATES = {"ENABLED", "DISABLED"}
_RESOURCE_TYPES = {"VOLUME", "INSTANCE"}


@dataclass
class DlmResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str = "application/json"


class DlmError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


@dataclass
class DlmStore:
    account_id: str = DEFAULT_ACCOUNT_ID
    region: str = REGION
    policies: dict = field(default_factory=dict)   # policy_id -> record
    vpc_store: object = None   # the shared EC2/VPC model — set by the wire router

    def persist(self) -> None:
        pass


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _json(status: int, payload) -> DlmResponse:
    return DlmResponse(status=status, body=json.dumps(payload).encode())


def _error(code: str, message: str, status: int = 400) -> DlmResponse:
    return DlmResponse(status=status, body=json.dumps({"message": message}).encode(),
                       headers={"x-amzn-errortype": code})


def _policy_arn(store, policy_id: str) -> str:
    return f"arn:aws:dlm:{store.region}:{store.account_id}:policy/{policy_id}"


def _validate_schedule(sched: dict) -> None:
    rule = (sched.get("CreateRule") or {})
    unit = str(rule.get("IntervalUnit") or "HOURS")
    interval = rule.get("Interval")
    if unit != "HOURS" or not isinstance(interval, int) or interval <= 0:
        raise DlmError("ValidationException", "CreateRule.Interval must be a positive integer of HOURS "
                                              "(Vyomi models the interval cadence only, not Times-of-day windows).")
    retain = (sched.get("RetainRule") or {}).get("Count")
    if not isinstance(retain, int) or retain <= 0:
        raise DlmError("ValidationException", "RetainRule.Count must be a positive integer.")


def _create_policy(store: DlmStore, body: dict) -> DlmResponse:
    state = str(body.get("State") or "ENABLED")
    if state not in _STATES:
        raise DlmError("ValidationException", f"State must be one of {sorted(_STATES)}.")
    details = body.get("PolicyDetails") or {}
    rtypes = details.get("ResourceTypes") or []
    if not rtypes or any(t not in _RESOURCE_TYPES for t in rtypes):
        raise DlmError("ValidationException", f"PolicyDetails.ResourceTypes must be a non-empty subset of {sorted(_RESOURCE_TYPES)}.")
    schedules = details.get("Schedules") or []
    if not schedules:
        raise DlmError("ValidationException", "PolicyDetails.Schedules must contain at least one schedule.")
    for s in schedules:
        _validate_schedule(s)
    policy_id = "policy-" + uuid.uuid4().hex[:17].upper()
    now = _now()
    p = {
        "PolicyId": policy_id, "Description": str(body.get("Description") or ""), "State": state,
        "ExecutionRoleArn": body.get("ExecutionRoleArn") or f"arn:aws:iam::{store.account_id}:role/AWSDataLifecycleManagerDefaultRole",
        "PolicyDetails": details, "Tags": body.get("Tags") or {},
        "DateCreated": _iso(now), "DateModified": _iso(now),
        "_created_ts": now,
        # per-schedule bookkeeping: name -> {next_due, last_run, created: [resource ids this policy made]}
        "_schedule_state": {s.get("Name") or f"schedule-{i}": {"next_due": now, "last_run": None, "created": {}}
                            for i, s in enumerate(schedules)},
    }
    store.policies[policy_id] = p
    store.persist()
    return _json(200, {"PolicyId": policy_id})


def _resource_matches(tags: dict, target_tags: list) -> bool:
    if not target_tags:
        return False
    return any((tags or {}).get(t.get("Key")) == t.get("Value") for t in target_tags)


def _run_schedule(store: DlmStore, policy: dict, schedule: dict, sched_state: dict) -> None:
    """Really create a snapshot/AMI for every matching, tagged resource, and prune past
    RetainRule.Count — exactly what the console's manual 'Create snapshot now' does, just
    triggered by the schedule instead of a button."""
    if store.vpc_store is None:
        return
    from core import vpc_core as _vpc
    details = policy["PolicyDetails"]
    target_tags = details.get("TargetTags") or []
    model = getattr(store.vpc_store, "_vpc_model", None) or {}
    created = sched_state.setdefault("created", {})
    retain = schedule["RetainRule"]["Count"]
    for rtype in details.get("ResourceTypes") or []:
        if rtype == "VOLUME":
            for vol in (model.get("volumes") or {}).values():
                if not _resource_matches(vol.get("tags"), target_tags):
                    continue
                r = _vpc.dispatch(store.vpc_store, {
                    "Action": "CreateSnapshot", "VolumeId": vol["id"],
                    "Description": f"Created by DLM policy {policy['PolicyId']} schedule {schedule.get('Name', '')}",
                    "TagSpecification.1.ResourceType": "snapshot",
                    "TagSpecification.1.Tag.1.Key": "aws:dlm:lifecycle-policy-id", "TagSpecification.1.Tag.1.Value": policy["PolicyId"],
                    "TagSpecification.1.Tag.2.Key": "aws:dlm:lifecycle-schedule-name", "TagSpecification.1.Tag.2.Value": schedule.get("Name", "")})
                if r.status == 200:
                    m = re.search(r"<snapshotId>(.*?)</snapshotId>", r.body)
                    if m:
                        created.setdefault(vol["id"], []).append(m.group(1))
        else:  # INSTANCE
            for inst in (model.get("instances") or {}).values():
                if not _resource_matches(inst.get("tags"), target_tags):
                    continue
                r = _vpc.dispatch(store.vpc_store, {
                    "Action": "CreateImage", "InstanceId": inst["id"],
                    "Name": f"dlm-{policy['PolicyId']}-{int(_now())}",
                    "TagSpecification.1.ResourceType": "image",
                    "TagSpecification.1.Tag.1.Key": "aws:dlm:lifecycle-policy-id", "TagSpecification.1.Tag.1.Value": policy["PolicyId"]})
                if r.status == 200:
                    m = re.search(r"<imageId>(.*?)</imageId>", r.body)
                    if m:
                        created.setdefault(inst["id"], []).append(m.group(1))
    # prune: keep only the `retain` most recent per resource
    is_volume = "VOLUME" in (details.get("ResourceTypes") or [])
    for rid, made in created.items():
        while len(made) > retain:
            old = made.pop(0)
            action = "DeleteSnapshot" if is_volume else "DeregisterImage"
            key = "SnapshotId" if is_volume else "ImageId"
            _vpc.dispatch(store.vpc_store, {"Action": action, key: old})


def _evaluate_due_policies(store: DlmStore) -> None:
    now = _now()
    for p in store.policies.values():
        if p["State"] != "ENABLED":
            continue
        for sched in p["PolicyDetails"].get("Schedules") or []:
            name = sched.get("Name") or ""
            sstate = p["_schedule_state"].get(name)
            if sstate is None:
                continue
            while sstate["next_due"] is not None and sstate["next_due"] <= now:
                _run_schedule(store, p, sched, sstate)
                sstate["last_run"] = sstate["next_due"]
                interval_hours = sched["CreateRule"]["Interval"]
                sstate["next_due"] = sstate["next_due"] + interval_hours * 3600
    store.persist()


def _policy_summary(p: dict) -> dict:
    return {"PolicyId": p["PolicyId"], "Description": p["Description"], "State": p["State"],
            "Tags": p["Tags"], "PolicyType": "EBS_SNAPSHOT_MANAGEMENT" if "VOLUME" in p["PolicyDetails"].get("ResourceTypes", []) else "IMAGE_MANAGEMENT"}


def _policy_detail(store: DlmStore, p: dict) -> dict:
    last_runs = [s["last_run"] for s in p["_schedule_state"].values() if s.get("last_run")]
    return {"PolicyId": p["PolicyId"], "Description": p["Description"], "State": p["State"],
            "ExecutionRoleArn": p["ExecutionRoleArn"], "DateCreated": p["DateCreated"], "DateModified": p["DateModified"],
            "PolicyArn": _policy_arn(store, p["PolicyId"]), "PolicyDetails": p["PolicyDetails"], "Tags": p["Tags"],
            "LastRunStatus": "SUCCESS" if last_runs else "NOT_RUN_YET",
            "LastRunTime": _iso(max(last_runs)) if last_runs else None}


def _get_policy(store: DlmStore, policy_id: str) -> dict:
    p = store.policies.get(policy_id)
    if p is None:
        raise DlmError("ResourceNotFoundException", f"Policy '{policy_id}' not found.", 404)
    return p


def _get_policies(store: DlmStore, query: dict) -> DlmResponse:
    _evaluate_due_policies(store)
    ids = [v for k, v in query.items() if k == "policyIds"]
    rows = [p for p in store.policies.values() if not ids or p["PolicyId"] in ids]
    return _json(200, {"Policies": [_policy_summary(p) for p in rows]})


def _get_policy_op(store: DlmStore, policy_id: str) -> DlmResponse:
    _evaluate_due_policies(store)
    p = _get_policy(store, policy_id)
    return _json(200, {"Policy": _policy_detail(store, p)})


def _update_policy(store: DlmStore, policy_id: str, body: dict) -> DlmResponse:
    p = _get_policy(store, policy_id)
    if "State" in body:
        if body["State"] not in _STATES:
            raise DlmError("ValidationException", f"State must be one of {sorted(_STATES)}.")
        p["State"] = body["State"]
    if "Description" in body:
        p["Description"] = body["Description"]
    if "ExecutionRoleArn" in body:
        p["ExecutionRoleArn"] = body["ExecutionRoleArn"]
    if "PolicyDetails" in body:
        for s in body["PolicyDetails"].get("Schedules") or []:
            _validate_schedule(s)
        p["PolicyDetails"] = body["PolicyDetails"]
        now = _now()
        p["_schedule_state"] = {s.get("Name") or f"schedule-{i}": {"next_due": now, "last_run": None, "created": {}}
                                for i, s in enumerate(p["PolicyDetails"].get("Schedules") or [])}
    p["DateModified"] = _iso(_now())
    store.persist()
    return _json(200, {})


def _delete_policy(store: DlmStore, policy_id: str) -> DlmResponse:
    _get_policy(store, policy_id)
    store.policies.pop(policy_id, None)
    store.persist()
    return _json(200, {})


def dispatch(store: DlmStore, method: str, path: str, query: dict, headers: dict, body: bytes) -> DlmResponse:
    """Native DLM REST-JSON router. `path` is already stripped of any `/_wire` prefix."""
    segs = [s for s in (path or "/").split("?", 1)[0].split("/") if s]
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}
    try:
        if segs == ["policies"] and method == "POST":
            return _create_policy(store, payload)
        if segs == ["policies"] and method == "GET":
            return _get_policies(store, query or {})
        if len(segs) == 2 and segs[0] == "policies":
            policy_id = segs[1]
            if method == "GET":
                return _get_policy_op(store, policy_id)
            if method == "PATCH":
                return _update_policy(store, policy_id, payload)
            if method == "DELETE":
                return _delete_policy(store, policy_id)
        return _error("InvalidAction", f"{method} {path} is not implemented by the simulator.", 400)
    except DlmError as e:
        return _error(e.code, e.message, e.status)
