# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""EventBridge core — substrate-independent event-bus data plane (PARITY P4 #15).
The first real event-bus data plane in the simulator: rules with event patterns +
targets, and PutEvents that MATCHES each event against every rule and DELIVERS it
to the matching rules' targets (SQS queues) — the canonical EventBridge→SQS path.

Speaks the native **EventBridge JSON protocol** (X-Amz-Target `AWSEvents.<Op>`,
JSON body) so an unmodified boto3 `events` client works. NO fastapi / boto3 / socket
imports → loads under Pyodide. Reuses the SAME MessagingStore seam as SQS/SNS
(rules live in `store.event_rules`; delivery uses `sqs_core.enqueue`), so an event
routed to a queue is a real, receivable SQS message.

Scope (v1 slice): PutRule, DeleteRule, ListRules, PutTargets, RemoveTargets,
ListTargetsByRule, PutEvents (pattern match → SQS fan-out). Event-pattern operators:
exact value lists + {"prefix"}, {"anything-but"}, {"exists"} — mirroring SNS filter
policies. Archives, replays, schedules and non-SQS targets slot in next.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core.messaging_store import MessagingStore, REGION
from core import sqs_core


@dataclass
class EventsResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _rules(store: MessagingStore) -> dict:
    m = getattr(store, "event_rules", None)
    if m is None:
        m = {}
        store.event_rules = m
    return m


def _rule_arn(store, bus: str, name: str) -> str:
    return f"arn:aws:events:{REGION}:{store.account_id}:rule/{name}"


# ── event-pattern matching (a faithful subset) ─────────────────────────────
def _match_value(cond, value) -> bool:
    if isinstance(cond, dict):
        if "prefix" in cond:
            return isinstance(value, str) and value.startswith(str(cond["prefix"]))
        if "anything-but" in cond:
            ab = cond["anything-but"]
            ab = ab if isinstance(ab, list) else [ab]
            return value not in ab
        if "exists" in cond:
            return (value is not None) == bool(cond["exists"])
        return False
    return cond == value


def _match_pattern(pattern: dict, event: dict) -> bool:
    """Every key in the pattern must match; a key matches if the event's value is
    in the listed set (OR). Nested dicts (e.g. `detail`) recurse."""
    for key, expected in pattern.items():
        actual = event.get(key)
        if isinstance(expected, dict) and not any(k in expected for k in ("prefix", "anything-but", "exists")):
            if not isinstance(actual, dict) or not _match_pattern(expected, actual):
                return False
            continue
        options = expected if isinstance(expected, list) else [expected]
        if not any(_match_value(o, actual) for o in options):
            return False
    return True


# ── operations ──────────────────────────────────────────────────────────────
def _put_rule(store, body):
    name = str(body.get("Name", "")).strip()
    if not name:
        raise _E("ValidationException", "Name is required.")
    bus = str(body.get("EventBusName", "default") or "default")
    pattern = body.get("EventPattern")
    if isinstance(pattern, str):
        try:
            pattern = json.loads(pattern)
        except Exception:
            pattern = {}
    rule = _rules(store).get(name) or {"targets": {}}
    rule.update({"name": name, "bus": bus, "pattern": pattern or {},
                 "state": str(body.get("State", "ENABLED")),
                 "arn": _rule_arn(store, bus, name)})
    rule.setdefault("targets", {})
    _rules(store)[name] = rule
    store.persist()
    return EventsResponse(body={"RuleArn": rule["arn"]})


def _delete_rule(store, body):
    _rules(store).pop(str(body.get("Name", "")), None)
    store.persist()
    return EventsResponse(body={})


def _list_rules(store, body):
    prefix = str(body.get("NamePrefix", "") or "")
    rules = [{"Name": r["name"], "Arn": r["arn"], "State": r.get("state", "ENABLED"),
              "EventPattern": json.dumps(r.get("pattern", {}))}
             for r in _rules(store).values() if r["name"].startswith(prefix)]
    return EventsResponse(body={"Rules": rules})


def _put_targets(store, body):
    name = str(body.get("Rule", "")).strip()
    rule = _rules(store).get(name)
    if not rule:
        raise _E("ResourceNotFoundException", f"Rule {name} does not exist.")
    for t in body.get("Targets") or []:
        tid = str(t.get("Id") or uuid.uuid4().hex)
        rule["targets"][tid] = {"Id": tid, "Arn": str(t.get("Arn", ""))}
    store.persist()
    return EventsResponse(body={"FailedEntryCount": 0, "FailedEntries": []})


def _remove_targets(store, body):
    rule = _rules(store).get(str(body.get("Rule", "")))
    if rule:
        for tid in body.get("Ids") or []:
            rule["targets"].pop(str(tid), None)
        store.persist()
    return EventsResponse(body={"FailedEntryCount": 0, "FailedEntries": []})


def _list_targets_by_rule(store, body):
    rule = _rules(store).get(str(body.get("Rule", "")))
    if not rule:
        raise _E("ResourceNotFoundException", "Rule does not exist.")
    return EventsResponse(body={"Targets": list(rule["targets"].values())})


def _put_events(store, body):
    entries_out = []
    for entry in body.get("Entries") or []:
        source = entry.get("Source", "")
        detail_type = entry.get("DetailType", "")
        try:
            detail = json.loads(entry["Detail"]) if isinstance(entry.get("Detail"), str) else (entry.get("Detail") or {})
        except Exception:
            detail = {}
        bus = str(entry.get("EventBusName", "default") or "default")
        event_id = uuid.uuid4().hex
        # The event object rules are matched against (EventBridge's flat shape).
        event_obj = {"source": source, "detail-type": detail_type, "detail": detail,
                     "account": store.account_id, "region": REGION}
        envelope = {"version": "0", "id": event_id, "source": source,
                    "detail-type": detail_type, "detail": detail, "time": _now_iso()}
        body_str = json.dumps(envelope)
        for rule in _rules(store).values():
            if rule.get("bus", "default") != bus or rule.get("state") != "ENABLED":
                continue
            if not _match_pattern(rule.get("pattern", {}), event_obj):
                continue
            for tgt in rule["targets"].values():
                queue = store.get_queue_by_arn(tgt["Arn"])
                if queue is not None:
                    sqs_core.enqueue(store, queue, body_str)
        entries_out.append({"EventId": event_id})
    store.persist()
    return EventsResponse(body={"FailedEntryCount": 0, "Entries": entries_out})


class _E(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


_OPS = {
    "PutRule": _put_rule, "DeleteRule": _delete_rule, "ListRules": _list_rules,
    "PutTargets": _put_targets, "RemoveTargets": _remove_targets,
    "ListTargetsByRule": _list_targets_by_rule, "PutEvents": _put_events,
}


def dispatch(store: MessagingStore, target: str, payload: dict | None = None) -> EventsResponse:
    """Native EventBridge JSON router. `target` is the X-Amz-Target header,
    e.g. "AWSEvents.PutEvents"."""
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    op = _OPS.get(action)
    if op is None:
        return EventsResponse(status=400, body={"__type": "UnknownOperationException",
                                                "message": f"Unknown operation {action}."})
    try:
        return op(store, body)
    except _E as e:
        return EventsResponse(status=400, body={"__type": e.code, "message": e.message})
