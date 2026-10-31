"""EventBridge core — substrate-independent event-bus data plane (PARITY P4 #15,
extended for the v4 native-fidelity console).

Speaks the native **EventBridge JSON protocol** (X-Amz-Target `AWSEvents.<Op>`,
JSON body) so an unmodified boto3 `events` client works. NO fastapi / boto3 / socket
imports → loads under Pyodide. Reuses the SAME MessagingStore seam as SQS/SNS
(rules live in `store.event_rules`; delivery uses `sqs_core.enqueue` /
`sns_core.publish_arn` / `lambda_core.invoke_by_arn`), so an event routed to a
queue/topic/function is a real, receivable delivery, not a log line.

Scope: event buses (default + custom), rules with event patterns + targets
(enable/disable), PutEvents (pattern match → SQS/SNS/Lambda fan-out), archives +
replay (a bounded per-bus event log stands in for AWS's unlimited archive
retention — RetentionDays IS enforced within that bounded window, excluding
events older than it from DescribeArchive/StartReplay; see the
`eventbridge.archives` capability entry for the honest limitation on the window
itself), tags. Event-pattern operators: exact value lists + {"prefix"},
{"anything-but"}, {"exists"} — mirroring SNS filter policies.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from core.messaging_store import MessagingStore, REGION
from core import sqs_core
from core import sns_core as sns_mod
from core import lambda_core as lam_mod

EVENT_LOG_MAX = 500  # per bus — bounds the archive/replay window (documented limitation)


@dataclass
class EventsResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:23], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
    except Exception:
        try:
            return datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            return None


# ── buses ────────────────────────────────────────────────────────────────────
def _bus_arn(store, name: str) -> str:
    return f"arn:aws:events:{REGION}:{store.account_id}:event-bus/{name}"


def _new_bus(store, name, description="", tags=None):
    return {"name": name, "arn": _bus_arn(store, name), "description": description or "",
            "created": _now_iso(), "tags": dict(tags or {}), "event_log": [], "policy": None}


def _buses(store) -> dict:
    m = getattr(store, "event_buses", None)
    if m is None:
        m = {}
        store.event_buses = m
    if "default" not in m:
        m["default"] = _new_bus(store, "default", "The default event bus for this account.")
    return m


# ── rules ────────────────────────────────────────────────────────────────────
def _rules(store) -> dict:
    m = getattr(store, "event_rules", None)
    if m is None:
        m = {}
        store.event_rules = m
    return m


def _rule_key(bus: str, name: str) -> str:
    return f"{bus}|{name}"


def _rule_arn(store, bus: str, name: str) -> str:
    return f"arn:aws:events:{REGION}:{store.account_id}:rule/{bus}/{name}" if bus != "default" \
        else f"arn:aws:events:{REGION}:{store.account_id}:rule/{name}"


def _require_rule(store, bus, name):
    rule = _rules(store).get(_rule_key(bus, name))
    if not rule:
        raise _E("ResourceNotFoundException", f"Rule {name} does not exist on EventBus {bus}.")
    return rule


# ── archives / replays ──────────────────────────────────────────────────────
def _archives(store) -> dict:
    m = getattr(store, "event_archives", None)
    if m is None:
        m = {}
        store.event_archives = m
    return m


def _replays(store) -> dict:
    m = getattr(store, "event_replays", None)
    if m is None:
        m = {}
        store.event_replays = m
    return m


def _archive_arn(store, name: str) -> str:
    return f"arn:aws:events:{REGION}:{store.account_id}:archive/{name}"


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


# ── delivery (SQS / SNS / Lambda — the three target types Vyomi backs) ─────
def deliver(store, lam_store, arn: str, body_str: str, event_obj: dict, group_id=None) -> bool:
    """Deliver one event to a target ARN. A substrate may own the SQS queues or the
    Lambda functions elsewhere (the offline appliance's opted-out handlers / its
    function registry): it then exposes `store.deliver_sqs(arn, body, attrs, group, dedup)`
    / `store.deliver_lambda(arn, event)` and those are used instead."""
    if ":sqs:" in arn:
        hook = getattr(store, "deliver_sqs", None)
        if callable(hook):
            return bool(hook(arn, body_str, None, group_id, None))
    queue = store.get_queue_by_arn(arn)
    if queue is not None:
        dedup = None
        if queue.get("fifo"):
            dedup = sqs_core._md5(body_str)
            group_id = group_id or "default"
        sqs_core.enqueue(store, queue, body_str, message_group_id=group_id, message_dedup_id=dedup)
        return True
    if ":sns:" in arn:
        return sns_mod.publish_arn(store, arn, body_str)
    if ":lambda:" in arn:
        hook = getattr(store, "deliver_lambda", None)
        if callable(hook):
            try:
                if hook(arn, event_obj):
                    return True
            except Exception:
                pass
        if lam_store is not None:
            return lam_mod.invoke_by_arn(lam_store, arn, event_obj)
    return False  # target type Vyomi doesn't deliver to (stored, never invoked — see capability doc)


def _json_path(doc, path: str):
    """The JSONPath subset EventBridge's InputPath / InputPathsMap use: `$`, `$.a.b`,
    `$.a[0]`, `$['a']`."""
    p = str(path or "$").strip()
    if not p.startswith("$"):
        return None
    cur = doc
    import re as _re
    for tok in _re.findall(r"\.([^.\[\]]+)|\[(\d+)\]|\['([^']+)'\]", p[1:]):
        key, idx, qkey = tok
        if idx:
            cur = cur[int(idx)] if isinstance(cur, list) and int(idx) < len(cur) else None
        else:
            k = key or qkey
            cur = cur.get(k) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


def target_payload(tgt: dict, envelope: dict) -> str:
    """What a target receives: the whole event, or its Input (constant JSON), InputPath
    (a part of the event) or InputTransformer (template over InputPathsMap) — as in AWS."""
    if tgt.get("Input") not in (None, ""):
        return str(tgt["Input"])
    if tgt.get("InputPath"):
        part = _json_path(envelope, tgt["InputPath"])
        return json.dumps(part)
    tr = tgt.get("InputTransformer")
    if isinstance(tr, dict) and tr.get("InputTemplate") is not None:
        values = {var: _json_path(envelope, path) for var, path in (tr.get("InputPathsMap") or {}).items()}
        values["aws.events.event.json"] = envelope
        values["aws.events.rule-arn"] = str(tgt.get("_rule_arn", ""))
        return _render_template(str(tr["InputTemplate"]), values)
    return json.dumps(envelope)


def _render_template(tpl: str, values: dict) -> str:
    """InputTemplate rendering as EventBridge does it: a `<var>` inside a JSON string
    literal is replaced by the raw text; outside one, by the JSON value (strings quoted)."""
    out, i, in_str = [], 0, False
    while i < len(tpl):
        ch = tpl[i]
        if ch == '"' and (i == 0 or tpl[i - 1] != "\\"):
            in_str = not in_str
        if ch == "<":
            j = tpl.find(">", i)
            var = tpl[i + 1:j] if j > i else ""
            if var in values:
                v = values[var]
                if in_str:
                    out.append(v if isinstance(v, str) else json.dumps(v))
                else:
                    out.append(json.dumps(v))
                i = j + 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _notify(store, *args) -> None:
    hook = getattr(store, "eventbridge_notify", None)
    if callable(hook):
        try:
            hook(*args)
        except Exception:
            pass


def _deliver_to_bus(store, lam_store, bus: str, envelope: dict, event_obj: dict) -> int:
    """Match `envelope` against every ENABLED rule on `bus` and deliver to targets.
    Returns the count of (rule, target) deliveries attempted."""
    n = 0
    for rule in list(_rules(store).values()):
        if rule.get("bus", "default") != bus or rule.get("state") != "ENABLED":
            continue
        if not _match_pattern(rule.get("pattern", {}), event_obj):
            continue
        for tgt in list(rule["targets"].values()):
            body_str = target_payload(dict(tgt, _rule_arn=rule.get("arn", "")), envelope)
            group = (tgt.get("SqsParameters") or {}).get("MessageGroupId")
            deliver(store, lam_store, tgt["Arn"], body_str, event_obj, group_id=group)
            _notify(store, "target", rule.get("name", ""), tgt.get("Id", ""), envelope)
            n += 1
    return n


# ── operations: event buses ─────────────────────────────────────────────────
def _create_event_bus(store, body):
    name = str(body.get("Name", "")).strip()
    if not name:
        raise _E("ValidationException", "Name is required.")
    buses = _buses(store)
    if name in buses:
        raise _E("ResourceAlreadyExistsException", f"Event bus {name} already exists.")
    tags = {t["Key"]: t.get("Value", "") for t in body.get("Tags") or []}
    buses[name] = _new_bus(store, name, body.get("Description", ""), tags)
    store.persist()
    return EventsResponse(body={"EventBusArn": buses[name]["arn"]})


def _delete_event_bus(store, body):
    name = str(body.get("Name", ""))
    if name == "default":
        raise _E("ValidationException", "Cannot delete the default event bus.")
    buses = _buses(store)
    if buses.pop(name, None) is not None:
        for key in [k for k, r in _rules(store).items() if r.get("bus") == name]:
            _rules(store).pop(key, None)
        for key in [k for k, a in _archives(store).items() if a.get("bus") == name]:
            _archives(store).pop(key, None)
        store.persist()
    return EventsResponse(body={})


def _list_event_buses(store, body):
    prefix = str(body.get("NamePrefix", "") or "")
    buses = [{"Name": b["name"], "Arn": b["arn"], "Description": b.get("description", ""),
              "Policy": b.get("policy")}
             for b in _buses(store).values() if b["name"].startswith(prefix)]
    return EventsResponse(body={"EventBuses": buses})


def _update_event_bus(store, body):
    name = str(body.get("Name", "default") or "default")
    bus = _buses(store).get(name)
    if not bus:
        raise _E("ResourceNotFoundException", f"Event bus {name} does not exist.")
    if "Description" in body:
        bus["description"] = body.get("Description") or ""
    if "Policy" in body:
        bus["policy"] = body.get("Policy")
    store.persist()
    return EventsResponse(body={"Name": bus["name"], "Arn": bus["arn"], "Description": bus.get("description", "")})


def _describe_event_bus(store, body):
    name = str(body.get("Name", "default") or "default")
    bus = _buses(store).get(name)
    if not bus:
        raise _E("ResourceNotFoundException", f"Event bus {name} does not exist.")
    return EventsResponse(body={"Name": bus["name"], "Arn": bus["arn"],
                                 "Description": bus.get("description", ""), "Policy": bus.get("policy")})


# ── operations: rules ───────────────────────────────────────────────────────
def _put_rule(store, body):
    name = str(body.get("Name", "")).strip()
    if not name:
        raise _E("ValidationException", "Name is required.")
    bus = str(body.get("EventBusName", "default") or "default")
    if bus not in _buses(store):
        raise _E("ResourceNotFoundException", f"Event bus {bus} does not exist.")
    pattern = body.get("EventPattern")
    if isinstance(pattern, str) and pattern.strip():
        try:
            pattern = json.loads(pattern)
        except Exception:
            raise _E("InvalidEventPatternException", "Event pattern is not valid. Reason: it is not valid JSON.")
        if not isinstance(pattern, dict):
            raise _E("InvalidEventPatternException", "Event pattern is not valid. Reason: it must be a JSON object.")
    key = _rule_key(bus, name)
    rule = _rules(store).get(key) or {"targets": {}}
    tags = {t["Key"]: t.get("Value", "") for t in body.get("Tags") or []}
    rule.update({"name": name, "bus": bus, "pattern": pattern or {},
                 "state": str(body.get("State", "ENABLED")),
                 "description": body.get("Description", ""),
                 "schedule": body.get("ScheduleExpression", ""),
                 "arn": _rule_arn(store, bus, name)})
    rule.setdefault("targets", {})
    if tags:
        rule["tags"] = tags
    else:
        rule.setdefault("tags", {})
    _rules(store)[key] = rule
    store.persist()
    return EventsResponse(body={"RuleArn": rule["arn"]})


def _delete_rule(store, body):
    bus = str(body.get("EventBusName", "default") or "default")
    _rules(store).pop(_rule_key(bus, str(body.get("Name", ""))), None)
    store.persist()
    return EventsResponse(body={})


def _describe_rule(store, body):
    bus = str(body.get("EventBusName", "default") or "default")
    rule = _require_rule(store, bus, str(body.get("Name", "")))
    return EventsResponse(body={"Name": rule["name"], "Arn": rule["arn"], "EventBusName": rule["bus"],
                                 "EventPattern": json.dumps(rule.get("pattern", {})),
                                 "State": rule.get("state", "ENABLED"), "Description": rule.get("description", ""),
                                 "ScheduleExpression": rule.get("schedule", "")})


def _list_rules(store, body):
    prefix = str(body.get("NamePrefix", "") or "")
    bus = str(body.get("EventBusName", "default") or "default")
    rules = [{"Name": r["name"], "Arn": r["arn"], "State": r.get("state", "ENABLED"),
              "EventBusName": r.get("bus", "default"), "Description": r.get("description", ""),
              "EventPattern": json.dumps(r.get("pattern", {})), "ScheduleExpression": r.get("schedule", "")}
             for r in _rules(store).values() if r.get("bus", "default") == bus and r["name"].startswith(prefix)]
    return EventsResponse(body={"Rules": rules})


def _enable_rule(store, body):
    bus = str(body.get("EventBusName", "default") or "default")
    rule = _require_rule(store, bus, str(body.get("Name", "")))
    rule["state"] = "ENABLED"
    store.persist()
    return EventsResponse(body={})


def _disable_rule(store, body):
    bus = str(body.get("EventBusName", "default") or "default")
    rule = _require_rule(store, bus, str(body.get("Name", "")))
    rule["state"] = "DISABLED"
    store.persist()
    return EventsResponse(body={})


def _put_targets(store, body):
    bus = str(body.get("EventBusName", "default") or "default")
    rule = _require_rule(store, bus, str(body.get("Rule", "")))
    for t in body.get("Targets") or []:
        tid = str(t.get("Id") or uuid.uuid4().hex)
        rec = {"Id": tid, "Arn": str(t.get("Arn", ""))}
        for k in ("RoleArn", "Input", "InputPath", "InputTransformer", "SqsParameters",
                  "DeadLetterConfig", "RetryPolicy", "HttpParameters", "KinesisParameters"):
            if t.get(k) not in (None, ""):
                rec[k] = t[k]
        rule["targets"][tid] = rec
    store.persist()
    return EventsResponse(body={"FailedEntryCount": 0, "FailedEntries": []})


def _remove_targets(store, body):
    bus = str(body.get("EventBusName", "default") or "default")
    rule = _rules(store).get(_rule_key(bus, str(body.get("Rule", ""))))
    if rule:
        for tid in body.get("Ids") or []:
            rule["targets"].pop(str(tid), None)
        store.persist()
    return EventsResponse(body={"FailedEntryCount": 0, "FailedEntries": []})


def _list_targets_by_rule(store, body):
    bus = str(body.get("EventBusName", "default") or "default")
    rule = _require_rule(store, bus, str(body.get("Rule", "")))
    return EventsResponse(body={"Targets": list(rule["targets"].values())})


def _list_rule_names_by_target(store, body):
    bus = str(body.get("EventBusName", "default") or "default")
    arn = str(body.get("TargetArn", ""))
    names = [r["name"] for r in _rules(store).values()
             if r.get("bus", "default") == bus and any(t["Arn"] == arn for t in r["targets"].values())]
    return EventsResponse(body={"RuleNames": names})


# ── operations: events ──────────────────────────────────────────────────────
def _put_events(store, body, lam_store=None):
    entries_out = []
    for entry in body.get("Entries") or []:
        bus = str(entry.get("EventBusName", "default") or "default")
        if bus not in _buses(store):
            entries_out.append({"ErrorCode": "ResourceNotFoundException",
                                 "ErrorMessage": f"Event bus {bus} does not exist."})
            continue
        source = entry.get("Source", "")
        detail_type = entry.get("DetailType", "")
        try:
            detail = json.loads(entry["Detail"]) if isinstance(entry.get("Detail"), str) else (entry.get("Detail") or {})
        except Exception:
            detail = {}
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # The event object rules are matched against (EventBridge's flat shape).
        event_obj = {"source": source, "detail-type": detail_type, "detail": detail,
                     "account": store.account_id, "region": REGION}
        envelope = {"version": "0", "id": event_id, "source": source,
                    "detail-type": detail_type, "detail": detail, "time": now,
                    "account": store.account_id, "region": REGION,
                    "resources": entry.get("Resources") or []}
        log = _buses(store)[bus]["event_log"]
        log.append(envelope)
        del log[:-EVENT_LOG_MAX]
        _notify(store, "put", bus, envelope)
        _deliver_to_bus(store, lam_store, bus, envelope, event_obj)
        entries_out.append({"EventId": event_id})
    store.persist()
    failed = sum(1 for e in entries_out if "ErrorCode" in e)
    return EventsResponse(body={"FailedEntryCount": failed, "Entries": entries_out})


# ── operations: archives / replay ───────────────────────────────────────────
def _create_archive(store, body):
    name = str(body.get("ArchiveName", "")).strip()
    if not name:
        raise _E("ValidationException", "ArchiveName is required.")
    if name in _archives(store):
        raise _E("ResourceAlreadyExistsException", f"Archive {name} already exists.")
    source_arn = str(body.get("EventSourceArn", ""))
    bus = source_arn.rsplit("/", 1)[-1] if source_arn else "default"
    if bus not in _buses(store):
        raise _E("ResourceNotFoundException", f"Event bus {bus} does not exist.")
    pattern = body.get("EventPattern")
    if isinstance(pattern, str):
        try:
            pattern = json.loads(pattern)
        except Exception:
            pattern = {}
    archive = {"name": name, "arn": _archive_arn(store, name), "bus": bus,
               "source_arn": source_arn or _bus_arn(store, bus), "pattern": pattern or {},
               "retention_days": int(body.get("RetentionDays") or 0),
               "description": body.get("Description", ""), "created": _now_iso(), "state": "ENABLED"}
    _archives(store)[name] = archive
    store.persist()
    return EventsResponse(body={"ArchiveArn": archive["arn"], "State": "ENABLED", "CreationTime": archive["created"]})


def _archived_events(store, archive):
    log = _buses(store).get(archive["bus"], {}).get("event_log", [])
    matched = [e for e in log if _match_pattern(archive.get("pattern", {}), {
        "source": e.get("source"), "detail-type": e.get("detail-type"), "detail": e.get("detail")})]
    days = archive.get("retention_days") or 0
    if not days:
        return matched  # 0 = indefinite (bounded only by the shared 500-event log)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [e for e in matched if (_parse_iso(e.get("time")) or cutoff) >= cutoff]


def _describe_archive(store, body):
    archive = _archives(store).get(str(body.get("ArchiveName", "")))
    if not archive:
        raise _E("ResourceNotFoundException", "Archive does not exist.")
    events_ = _archived_events(store, archive)
    return EventsResponse(body={"ArchiveName": archive["name"], "ArchiveArn": archive["arn"],
                                 "EventSourceArn": archive["source_arn"], "State": archive["state"],
                                 "EventPattern": json.dumps(archive.get("pattern", {})),
                                 "RetentionDays": archive["retention_days"], "Description": archive.get("description", ""),
                                 "SizeBytes": sum(len(json.dumps(e)) for e in events_), "EventCount": len(events_),
                                 "CreationTime": archive["created"]})


def _list_archives(store, body):
    prefix = str(body.get("NamePrefix", "") or "")
    source_arn = body.get("EventSourceArn")
    out = []
    for a in _archives(store).values():
        if not a["name"].startswith(prefix):
            continue
        if source_arn and a["source_arn"] != source_arn:
            continue
        out.append({"ArchiveName": a["name"], "EventSourceArn": a["source_arn"], "State": a["state"],
                     "RetentionDays": a["retention_days"], "SizeBytes": sum(len(json.dumps(e)) for e in _archived_events(store, a)),
                     "EventCount": len(_archived_events(store, a)), "CreationTime": a["created"]})
    return EventsResponse(body={"Archives": out})


def _delete_archive(store, body):
    _archives(store).pop(str(body.get("ArchiveName", "")), None)
    store.persist()
    return EventsResponse(body={})


def _update_archive(store, body):
    archive = _archives(store).get(str(body.get("ArchiveName", "")))
    if not archive:
        raise _E("ResourceNotFoundException", "Archive does not exist.")
    if "Description" in body:
        archive["description"] = body.get("Description") or ""
    if "RetentionDays" in body:
        archive["retention_days"] = int(body.get("RetentionDays") or 0)
    pattern = body.get("EventPattern")
    if pattern is not None:
        if isinstance(pattern, str):
            try:
                pattern = json.loads(pattern)
            except Exception:
                pattern = {}
        archive["pattern"] = pattern or {}
    store.persist()
    return EventsResponse(body={"ArchiveArn": archive["arn"], "State": archive["state"], "CreationTime": archive["created"]})


def _start_replay(store, body, lam_store=None):
    name = str(body.get("ReplayName", "")).strip()
    if not name:
        raise _E("ValidationException", "ReplayName is required.")
    source_arn = str(body.get("EventSourceArn", ""))
    archive = next((a for a in _archives(store).values() if a["arn"] == source_arn), None)
    if not archive:
        raise _E("ResourceNotFoundException", "Archive does not exist.")
    dest_arn = str((body.get("Destination") or {}).get("Arn", "")) or _bus_arn(store, archive["bus"])
    dest_bus = dest_arn.rsplit("/", 1)[-1]
    start = _parse_iso(body.get("EventStartTime"))
    end = _parse_iso(body.get("EventEndTime"))
    replayed = 0
    for envelope in _archived_events(store, archive):
        t = _parse_iso(envelope.get("time"))
        if start and t and t < start:
            continue
        if end and t and t > end:
            continue
        event_obj = {"source": envelope.get("source"), "detail-type": envelope.get("detail-type"),
                     "detail": envelope.get("detail"), "account": store.account_id, "region": REGION}
        replay_envelope = dict(envelope, id=uuid.uuid4().hex, **{"replay-name": name})
        _deliver_to_bus(store, lam_store, dest_bus, replay_envelope, event_obj)
        replayed += 1
    replay = {"name": name, "arn": f"arn:aws:events:{REGION}:{store.account_id}:replay/{name}",
              "source_arn": source_arn, "destination_arn": dest_arn, "state": "COMPLETED",
              "event_count": replayed, "started": _now_iso(), "finished": _now_iso()}
    _replays(store)[name] = replay
    store.persist()
    return EventsResponse(body={"ReplayArn": replay["arn"], "State": "COMPLETED", "ReplayStartTime": replay["started"]})


def _describe_replay(store, body):
    replay = _replays(store).get(str(body.get("ReplayName", "")))
    if not replay:
        raise _E("ResourceNotFoundException", "Replay does not exist.")
    return EventsResponse(body={"ReplayName": replay["name"], "ReplayArn": replay["arn"], "State": replay["state"],
                                 "EventSourceArn": replay["source_arn"], "Destination": {"Arn": replay["destination_arn"]},
                                 "EventLastReplayedTime": replay["finished"], "ReplayStartTime": replay["started"],
                                 "ReplayEndTime": replay["finished"]})


def _list_replays(store, body):
    prefix = str(body.get("NamePrefix", "") or "")
    out = [{"ReplayName": r["name"], "State": r["state"], "EventSourceArn": r["source_arn"],
            "EventCount": r["event_count"], "ReplayStartTime": r["started"], "ReplayEndTime": r["finished"]}
           for r in _replays(store).values() if r["name"].startswith(prefix)]
    return EventsResponse(body={"Replays": out})


# ── operations: tags ────────────────────────────────────────────────────────
def _taggable(store, arn):
    for b in _buses(store).values():
        if b["arn"] == arn:
            return b
    for r in _rules(store).values():
        if r["arn"] == arn:
            return r
    for a in _archives(store).values():
        if a["arn"] == arn:
            return a
    return None


def _tag_resource(store, body):
    res = _taggable(store, str(body.get("ResourceARN", "")))
    if res is None:
        raise _E("ResourceNotFoundException", "Resource does not exist.")
    res.setdefault("tags", {}).update({t["Key"]: t.get("Value", "") for t in body.get("Tags") or []})
    store.persist()
    return EventsResponse(body={})


def _untag_resource(store, body):
    res = _taggable(store, str(body.get("ResourceARN", "")))
    if res is not None:
        for k in body.get("TagKeys") or []:
            res.get("tags", {}).pop(k, None)
        store.persist()
    return EventsResponse(body={})


def _list_tags_for_resource(store, body):
    res = _taggable(store, str(body.get("ResourceARN", "")))
    tags = (res or {}).get("tags", {})
    return EventsResponse(body={"Tags": [{"Key": k, "Value": v} for k, v in tags.items()]})


class _E(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


_OPS = {
    "PutRule": _put_rule, "DeleteRule": _delete_rule, "ListRules": _list_rules,
    "DescribeRule": _describe_rule, "EnableRule": _enable_rule, "DisableRule": _disable_rule,
    "PutTargets": _put_targets, "RemoveTargets": _remove_targets,
    "ListTargetsByRule": _list_targets_by_rule, "ListRuleNamesByTarget": _list_rule_names_by_target,
    "CreateEventBus": _create_event_bus, "DeleteEventBus": _delete_event_bus,
    "ListEventBuses": _list_event_buses, "DescribeEventBus": _describe_event_bus,
    "UpdateEventBus": _update_event_bus,
    "CreateArchive": _create_archive, "DescribeArchive": _describe_archive,
    "ListArchives": _list_archives, "DeleteArchive": _delete_archive, "UpdateArchive": _update_archive,
    "StartReplay": _start_replay, "DescribeReplay": _describe_replay, "ListReplays": _list_replays,
    "TagResource": _tag_resource, "UntagResource": _untag_resource, "ListTagsForResource": _list_tags_for_resource,
}

# Ops that need the Lambda function store for target delivery.
_NEEDS_LAMBDA = {"PutEvents", "StartReplay"}


def dispatch(store: MessagingStore, target: str, payload: dict | None = None, lam_store=None) -> EventsResponse:
    """Native EventBridge JSON router. `target` is the X-Amz-Target header,
    e.g. "AWSEvents.PutEvents". `lam_store` (optional) is the Lambda function
    registry, needed only to deliver to Lambda targets."""
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    try:
        if action == "PutEvents":
            return _put_events(store, body, lam_store)
        if action == "StartReplay":
            return _start_replay(store, body, lam_store)
        op = _OPS.get(action)
        if op is None:
            return EventsResponse(status=400, body={"__type": "UnknownOperationException",
                                                    "message": f"Unknown operation {action}."})
        return op(store, body)
    except _E as e:
        return EventsResponse(status=400, body={"__type": e.code, "message": e.message})
