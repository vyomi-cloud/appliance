# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""EventBridge Scheduler core — substrate-independent cron/rate/one-time schedule
control plane (botocore `scheduler`, 2021-06-30, rest-json).

Speaks the native **Scheduler REST wire** (`/schedules/{name}`, `/schedule-groups/
{name}`; JSON, PascalCase members) so an unmodified boto3 `scheduler` client
works. NO fastapi / boto3 / socket imports → loads under Pyodide.

Vyomi has no background timer, so a schedule does not fire itself while nothing
is looking. Instead — the same trick `gcp_cloudscheduler_core` uses for Cloud
Scheduler — every dispatch call first ADVANCES: any ENABLED schedule whose
computed next occurrence has passed gets delivered to its target (SQS/SNS/Lambda,
via `eventbridge_core.deliver`) and its next occurrence recomputed. So a schedule
really fires, exactly on time, as long as the console/API is polled after that
time; it does not fire while the tab is closed. That limitation is documented in
`core/capabilities/aws/eventbridge.json`.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from core import eventbridge_core as eb

REGION = "us-east-1"
ACCOUNT = "123456789012"


class SchedulerStore:
    """Public dict attrs only → persisted/synced like every other store."""

    def __init__(self):
        self.groups: dict = {"default": {"name": "default", "arn": _group_arn("default"),
                                          "created": _now_iso(), "state": "ACTIVE"}}
        self.schedules: dict = {}  # "{group}/{name}" -> schedule


def _group_arn(name: str) -> str:
    return f"arn:aws:scheduler:{REGION}:{ACCOUNT}:schedule-group/{name}"


def _schedule_arn(group: str, name: str) -> str:
    return f"arn:aws:scheduler:{REGION}:{ACCOUNT}:schedule/{group}/{name}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SchedulerResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


class _E(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _json(status, obj=None):
    return SchedulerResponse(status=status, body=b"" if obj is None else json.dumps(obj).encode())


_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_DOW = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}


def _parse_at(expr: str) -> datetime | None:
    m = re.match(r"^at\(([^)]+)\)$", expr.strip())
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _parse_rate(expr: str):
    m = re.match(r"^rate\((\d+)\s+(minute|minutes|hour|hours|day|days)\)$", expr.strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    mult = {"minute": 60, "minutes": 60, "hour": 3600, "hours": 3600, "day": 86400, "days": 86400}[unit]
    return n * mult


def _field_match(field_expr: str, value: int, name_map: dict | None = None) -> bool:
    if field_expr in ("*", "?"):
        return True
    for part in field_expr.split(","):
        part = part.strip().upper()
        if name_map and part in name_map:
            if name_map[part] == value:
                return True
            continue
        if "/" in part:
            base, step = part.split("/", 1)
            lo = 0 if base in ("*", "?") else int(base)
            if int(step) and value >= lo and (value - lo) % int(step) == 0:
                return True
            continue
        if "-" in part and part.lstrip("-").isdigit() is False and "-" in part[1:]:
            lo, hi = part.split("-", 1)
            if int(lo) <= value <= int(hi):
                return True
            continue
        if part.isdigit() and int(part) == value:
            return True
    return False


def _cron_matches(fields: list[str], dt: datetime) -> bool:
    # AWS cron: minutes hours day-of-month month day-of-week year
    minute, hour, dom, month, dow, year = fields
    if not _field_match(minute, dt.minute):
        return False
    if not _field_match(hour, dt.hour):
        return False
    if not _field_match(year, dt.year):
        return False
    if not _field_match(month, dt.month, _MONTHS):
        return False
    dom_ok = dom in ("*", "?") or _field_match(dom, dt.day)
    dow_ok = dow in ("*", "?") or _field_match(dow, dt.isoweekday() % 7, _DOW)
    if dom not in ("*", "?") and dow not in ("*", "?"):
        return dom_ok or dow_ok
    return dom_ok and dow_ok


def _next_cron(expr: str, after: datetime) -> datetime | None:
    m = re.match(r"^cron\(([^)]+)\)$", expr.strip())
    if not m:
        return None
    fields = m.group(1).split()
    if len(fields) != 6:
        return None
    t = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    for _ in range(2 * 366 * 24 * 60):  # bounded search, ~2 years of minutes
        if _cron_matches(fields, t):
            return t
        t += timedelta(minutes=1)
    return None


def _next_occurrence(expr: str, after: datetime) -> datetime | None:
    expr = (expr or "").strip()
    if expr.startswith("at("):
        return _parse_at(expr)
    if expr.startswith("rate("):
        secs = _parse_rate(expr)
        return after + timedelta(seconds=secs) if secs else None
    if expr.startswith("cron("):
        return _next_cron(expr, after)
    return None


def _view(sched: dict) -> dict:
    return {"Name": sched["name"], "GroupName": sched["group"], "Arn": sched["arn"],
            "State": sched["state"], "ScheduleExpression": sched["expr"],
            "ScheduleExpressionTimezone": sched.get("timezone", "UTC"),
            "FlexibleTimeWindow": sched.get("flexible_time_window", {"Mode": "OFF"}),
            "Target": sched["target"], "Description": sched.get("description", ""),
            "StartDate": sched.get("start_date"), "EndDate": sched.get("end_date"),
            "ActionAfterCompletion": sched.get("action_after_completion", "NONE"),
            "CreationDate": sched["created"], "LastModificationDate": sched["created"],
            "NextInvocationTime": sched.get("next_run"), "LastInvocationTime": sched.get("last_run")}


def _advance(store: SchedulerStore, msg_store=None, lam_store=None, now: datetime | None = None):
    """Fire every ENABLED schedule whose computed next run has passed."""
    now = now or _now_dt()
    for sched in store.schedules.values():
        if sched["state"] != "ENABLED":
            continue
        nxt = sched.get("next_run_dt")
        if nxt is None or nxt > now:
            continue
        tgt = sched["target"]
        try:
            payload = json.loads(tgt.get("Input")) if tgt.get("Input") else {}
        except Exception:
            payload = {"raw": tgt.get("Input")}
        if msg_store is not None:
            eb.deliver(msg_store, lam_store, tgt.get("Arn", ""), json.dumps(payload), payload if isinstance(payload, dict) else {})
        sched["last_run"] = _now_iso()
        one_time = sched["expr"].strip().startswith("at(")
        if one_time and sched.get("action_after_completion") == "DELETE":
            sched["state"] = "DELETED_MARK"
            continue
        if one_time:
            sched["state"] = "DISABLED" if sched.get("action_after_completion") != "NONE" else sched["state"]
            sched["next_run_dt"] = None
            sched["next_run"] = None
            continue
        nxt2 = _next_occurrence(sched["expr"], now)
        sched["next_run_dt"] = nxt2
        sched["next_run"] = nxt2.strftime("%Y-%m-%dT%H:%M:%S.000Z") if nxt2 else None
    for name in [n for n, s in store.schedules.items() if s["state"] == "DELETED_MARK"]:
        store.schedules.pop(name, None)


# ── schedule groups ──────────────────────────────────────────────────────────
def _create_group(store, name, body):
    if name in store.groups:
        raise _E("ConflictException", f"Schedule group {name} already exists.", 409)
    store.groups[name] = {"name": name, "arn": _group_arn(name), "created": _now_iso(), "state": "ACTIVE"}
    return _json(200, {"ScheduleGroupArn": store.groups[name]["arn"]})


def _get_group(store, name):
    g = store.groups.get(name)
    if not g:
        raise _E("ResourceNotFoundException", f"Schedule group {name} does not exist.", 404)
    return _json(200, {"Name": g["name"], "Arn": g["arn"], "State": g["state"], "CreationDate": g["created"]})


def _list_groups(store, query):
    prefix = query.get("NamePrefix", "")
    items = [{"Name": g["name"], "Arn": g["arn"], "State": g["state"], "CreationDate": g["created"]}
             for g in store.groups.values() if g["name"].startswith(prefix)]
    return _json(200, {"ScheduleGroups": items})


def _delete_group(store, name):
    if name == "default":
        raise _E("ValidationException", "Cannot delete the default schedule group.")
    if store.groups.pop(name, None) is None:
        raise _E("ResourceNotFoundException", f"Schedule group {name} does not exist.", 404)
    for key in [k for k, s in store.schedules.items() if s["group"] == name]:
        store.schedules.pop(key, None)
    return _json(200, {})


# ── schedules ────────────────────────────────────────────────────────────────
def _key(group, name):
    return f"{group}/{name}"


def _create_schedule(store, name, body):
    group = body.get("GroupName") or "default"
    if group not in store.groups:
        raise _E("ResourceNotFoundException", f"Schedule group {group} does not exist.", 404)
    key = _key(group, name)
    expr = str(body.get("ScheduleExpression", ""))
    if not expr:
        raise _E("ValidationException", "ScheduleExpression is required.")
    state = str(body.get("State", "ENABLED"))
    now = _now_dt()
    next_dt = _next_occurrence(expr, now) if state == "ENABLED" else None
    sched = {"name": name, "group": group, "arn": _schedule_arn(group, name), "expr": expr,
             "state": state, "target": body.get("Target") or {}, "description": body.get("Description", ""),
             "timezone": body.get("ScheduleExpressionTimezone", "UTC"),
             "flexible_time_window": body.get("FlexibleTimeWindow") or {"Mode": "OFF"},
             "start_date": body.get("StartDate"), "end_date": body.get("EndDate"),
             "action_after_completion": body.get("ActionAfterCompletion", "NONE"),
             "created": _now_iso(), "next_run_dt": next_dt,
             "next_run": next_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z") if next_dt else None, "last_run": None}
    store.schedules[key] = sched
    return _json(200, {"ScheduleArn": sched["arn"]})


def _get_schedule(store, group, name):
    sched = store.schedules.get(_key(group, name))
    if not sched:
        raise _E("ResourceNotFoundException", f"Schedule {name} does not exist.", 404)
    return _json(200, _view(sched))


def _update_schedule(store, name, body):
    group = body.get("GroupName") or "default"
    key = _key(group, name)
    if key not in store.schedules:
        raise _E("ResourceNotFoundException", f"Schedule {name} does not exist.", 404)
    return _create_schedule(store, name, body)


def _delete_schedule(store, group, name):
    if store.schedules.pop(_key(group, name), None) is None:
        raise _E("ResourceNotFoundException", f"Schedule {name} does not exist.", 404)
    return _json(200, {})


def _list_schedules(store, query):
    group = query.get("GroupName")
    prefix = query.get("NamePrefix", "")
    items = [_view(s) for s in store.schedules.values()
             if s["name"].startswith(prefix) and (not group or s["group"] == group)]
    return _json(200, {"Schedules": items})


# ── dispatch ────────────────────────────────────────────────────────────────
_SCHEDULE = re.compile(r"^/schedules/([^/]+)$")
_SCHEDULE_GROUP_ITEM = re.compile(r"^/schedule-groups/([^/]+)$")


def dispatch(store: SchedulerStore, method: str, path: str, query: dict | None = None,
             headers: dict | None = None, body: bytes = b"", msg_store=None, lam_store=None) -> SchedulerResponse:
    query = query or {}
    method = (method or "GET").upper()
    try:
        _advance(store, msg_store, lam_store)
        payload = {}
        if body:
            try:
                payload = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)
            except Exception:
                payload = {}
        if path == "/schedules" and method == "GET":
            return _list_schedules(store, query)
        m = _SCHEDULE.match(path)
        if m:
            name = m.group(1)
            if method == "POST":
                return _create_schedule(store, name, payload)
            if method == "GET":
                return _get_schedule(store, query.get("GroupName", "default"), name)
            if method == "PUT":
                return _update_schedule(store, name, payload)
            if method == "DELETE":
                return _delete_schedule(store, query.get("GroupName", "default"), name)
        if path == "/schedule-groups" and method == "GET":
            return _list_groups(store, query)
        m = _SCHEDULE_GROUP_ITEM.match(path)
        if m:
            name = m.group(1)
            if method == "POST":
                return _create_group(store, name, payload)
            if method == "GET":
                return _get_group(store, name)
            if method == "DELETE":
                return _delete_group(store, name)
        msg = f"No route for {method} {path}"
        return SchedulerResponse(status=404, body=json.dumps({"message": msg, "error": {"code": "NotFound", "message": msg}}).encode())
    except _E as e:
        # Native shape (message + x-amzn-errortype header, like the rest of the AWS JSON/REST
        # services here) PLUS a nested `error` object for consoles/src/common/wire.js's generic
        # restJson() error parsing (shared with the unsigned GCP/Azure lenses).
        return SchedulerResponse(status=e.status, headers={"x-amzn-errortype": e.code},
                                  body=json.dumps({"message": e.message, "error": {"code": e.code, "message": e.message}}).encode())
