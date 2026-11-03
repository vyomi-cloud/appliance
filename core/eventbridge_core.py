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
import re
import time
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


# ── event-pattern matching (the standard EventBridge pattern language) ─────
def _num_ok(cond, value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    c = list(cond) if isinstance(cond, (list, tuple)) else []
    if not c or len(c) % 2:
        return False
    for i in range(0, len(c), 2):
        op, ref = c[i], c[i + 1]
        if isinstance(ref, bool) or not isinstance(ref, (int, float)):
            return False
        if not ((op == "=" and value == ref) or (op == ">" and value > ref) or (op == ">=" and value >= ref)
                or (op == "<" and value < ref) or (op == "<=" and value <= ref)):
            return False
    return True


def _wild(pat: str, value) -> bool:
    return isinstance(value, str) and re.fullmatch(".*".join(re.escape(x) for x in pat.split("*")), value, re.S) is not None


def _match_leaf(cond, value) -> bool:
    """One leaf condition against ONE scalar event value."""
    if isinstance(cond, dict):
        if "prefix" in cond:
            p = cond["prefix"]
            if isinstance(p, dict) and "equals-ignore-case" in p:
                return isinstance(value, str) and value.lower().startswith(str(p["equals-ignore-case"]).lower())
            return isinstance(value, str) and value.startswith(str(p))
        if "suffix" in cond:
            return isinstance(value, str) and value.endswith(str(cond["suffix"]))
        if "equals-ignore-case" in cond:
            return isinstance(value, str) and value.lower() == str(cond["equals-ignore-case"]).lower()
        if "wildcard" in cond:
            return _wild(str(cond["wildcard"]), value)
        if "numeric" in cond:
            return _num_ok(cond["numeric"], value)
        if "anything-but" in cond:
            ab = cond["anything-but"]
            if isinstance(ab, dict):                      # {"anything-but": {"prefix": "x"}}
                return value is not None and not _match_leaf(ab, value)
            ab = ab if isinstance(ab, list) else [ab]
            return value is not None and value not in ab
        return False
    return cond == value


def _match_value(cond, value) -> bool:
    if isinstance(cond, dict) and "exists" in cond:
        return (value is not None) == bool(cond["exists"])
    if isinstance(cond, dict) and "anything-but" in cond and isinstance(value, list):
        return all(_match_leaf(cond, v) for v in value) and bool(value)
    if isinstance(value, list):                            # an array event value matches if ANY element does
        return any(_match_leaf(cond, v) for v in value)
    return _match_leaf(cond, value)


_LEAF_OPS = ("prefix", "suffix", "anything-but", "exists", "numeric", "equals-ignore-case", "wildcard")


def _match_pattern(pattern: dict, event: dict) -> bool:
    """Every key in the pattern must match (AND); a leaf array is an OR of its values;
    nested dicts (e.g. `detail`) recurse; `$or` is a list of alternative sub-patterns."""
    if not isinstance(pattern, dict):
        return False
    for key, expected in pattern.items():
        if key == "$or":
            if not any(_match_pattern(alt, event) for alt in (expected or [])):
                return False
            continue
        actual = event.get(key) if isinstance(event, dict) else None
        if isinstance(expected, dict) and not any(k in expected for k in _LEAF_OPS):
            if isinstance(actual, list):                   # arrays of objects: any element
                if not any(isinstance(el, dict) and _match_pattern(expected, el) for el in actual):
                    return False
            elif not isinstance(actual, dict) or not _match_pattern(expected, actual):
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
        # Keep every target field the caller set (Input, InputPath, InputTransformer,
        # RetryPolicy, DeadLetterConfig, RoleArn…) so ListTargetsByRule returns them.
        rule["targets"][tid] = {**{k: v for k, v in t.items() if v is not None},
                                "Id": tid, "Arn": str(t.get("Arn", ""))}
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


def _json_path(doc, path):
    """Resolve a `$.a.b[0]` JSONPath subset; returns (found, value)."""
    cur = doc
    for part in re.findall(r"[^.\[\]$]+|\[\d+\]", path or ""):
        try:
            if part.startswith("["):
                cur = cur[int(part[1:-1])]
            else:
                cur = cur[part]
        except (KeyError, IndexError, TypeError):
            return False, None
    return True, cur


def _target_input(tgt, envelope, body_str):
    """Apply the target's Input / InputPath / InputTransformer to the event."""
    if tgt.get("Input") is not None:
        return str(tgt["Input"])
    if tgt.get("InputPath"):
        ok, val = _json_path(envelope, tgt["InputPath"])
        return json.dumps(val) if ok else body_str
    tr = tgt.get("InputTransformer")
    if tr:
        values = {}
        for k, path in (tr.get("InputPathsMap") or {}).items():
            ok, val = _json_path(envelope, path)
            values[k] = val if ok else None

        def sub(m):
            v = values.get(m.group(1))
            if v is None:
                return ""
            return v if isinstance(v, str) else json.dumps(v)
        return re.sub(r"<([A-Za-z0-9_.\-]+)>", sub, str(tr.get("InputTemplate", "")))
    return body_str


def _deliver_sns(store, topic_arn, body_str):
    """SNS rule target: publish the event envelope to the topic (fans out to its
    subscriptions). A missing/FIFO-incompatible topic is a failed delivery, which
    EventBridge swallows (retries then DLQ), never a PutEvents error."""
    try:
        try:
            from core import sns_core
        except ImportError:  # Pyodide flat layout
            import sns_core  # type: ignore
        topic = store.get_topic(topic_arn)
        if topic is None:
            raise LookupError(f"SNS topic {topic_arn} does not exist")
        sns_core._publish_to_topic(store, topic, {"Message": body_str, "Subject": None,
                                                  "MessageStructure": "", "attrs": {},
                                                  "group": "", "dedup": ""})
    except Exception:
        raise  # route_event retries per the target's RetryPolicy, then dead-letters


# Offline hook: the appliance's own Lambda registry (server.py) is not an `lambda_core` store.
_LAMBDA_INVOKER = None


def set_lambda_invoker(fn) -> None:
    """fn(function_name, payload_json_str) -> None. Installed by the offline appliance so
    EventBridge Lambda targets run the appliance's real functions."""
    global _LAMBDA_INVOKER
    _LAMBDA_INVOKER = fn


# Stores for Kinesis / CloudWatch Logs targets (they live outside the messaging store);
# installed by the offline appliance (server.py) and by Nano's registry.
_TARGET_STORES: dict = {}


def set_target_store(kind: str, store) -> None:
    """kind: "kinesis" | "logs"."""
    _TARGET_STORES[kind] = store


def _deliver_kinesis(arn, body_str, tgt, event_id):
    """Kinesis rule target: PutRecord of the (transformed) event; partition key from
    KinesisParameters.PartitionKeyPath if present, else the event id."""
    import base64
    st = _TARGET_STORES.get("kinesis")
    if st is None:
        raise LookupError("Kinesis is not available")
    try:
        from core import kinesis_core
    except ImportError:  # Pyodide flat layout
        import kinesis_core  # type: ignore
    pk = event_id
    path = ((tgt or {}).get("KinesisParameters") or {}).get("PartitionKeyPath")
    if path:
        try:
            found, v = _json_path(json.loads(body_str), path)
            if found and v not in (None, ""):
                pk = str(v)
        except Exception:
            pass
    r = kinesis_core.dispatch(st, "Kinesis_20131202.PutRecord", {
        "StreamName": arn.rsplit("stream/", 1)[-1], "PartitionKey": pk,
        "Data": base64.b64encode(body_str.encode("utf-8")).decode()})
    if r.status >= 300:
        raise RuntimeError(f"Kinesis PutRecord failed: {r.body}")


def _deliver_logs(arn, body_str):
    """CloudWatch Logs rule target: one log event in a fresh stream of the group."""
    st = _TARGET_STORES.get("logs")
    if st is None:
        raise LookupError("CloudWatch Logs is not available")
    try:
        from core import logs_core
    except ImportError:  # Pyodide flat layout
        import logs_core  # type: ignore
    group = arn.split("log-group:", 1)[-1]
    group = group[:-2] if group.endswith(":*") else group
    stream = f"{datetime.now(timezone.utc):%Y/%m/%d}/{uuid.uuid4().hex}"
    h = "Logs_20140328."
    logs_core.dispatch(st, h + "CreateLogGroup", {"logGroupName": group})  # exists -> benign
    logs_core.dispatch(st, h + "CreateLogStream", {"logGroupName": group, "logStreamName": stream})
    r = logs_core.dispatch(st, h + "PutLogEvents", {"logGroupName": group, "logStreamName": stream,
                           "logEvents": [{"timestamp": int(time.time() * 1000), "message": body_str}]})
    if r.status >= 300:
        raise RuntimeError(f"PutLogEvents failed: {r.body}")


def _fn_name(arn: str) -> str:
    return arn.split(":function:", 1)[-1].split(":", 1)[0] if ":function:" in arn else arn


def _deliver_lambda(lambda_store, arn, body_str):
    """Lambda rule target: asynchronous invoke with the (transformed) event as the payload.
    A failed delivery is swallowed (EventBridge retries then DLQs), never a PutEvents error."""
    try:
        name = _fn_name(arn)
        if _LAMBDA_INVOKER is not None:
            _LAMBDA_INVOKER(name, body_str)
        elif lambda_store is not None:
            try:
                from core import lambda_core
            except ImportError:  # Pyodide flat layout
                import lambda_core  # type: ignore
            lambda_core.dispatch(lambda_store, "POST", f"/2015-03-31/functions/{name}/invocations", {}, {},
                                 body_str.encode("utf-8"))
    except Exception:
        raise  # route_event retries per the target's RetryPolicy, then dead-letters


_MAX_LOCAL_RETRIES = 5   # EventBridge allows up to 185 over 24h; retried back-to-back here, capped


def _deliver_with_retry(tgt, fn, send_sqs, envelope_str):
    """Call `fn()`; on failure retry per the target's RetryPolicy.MaximumRetryAttempts, then
    send the event to DeadLetterConfig.Arn (an SQS queue) if set. Never raises: EventBridge
    swallows target failures, PutEvents succeeds regardless."""
    try:
        extra = int((tgt.get("RetryPolicy") or {}).get("MaximumRetryAttempts", 0) or 0)
    except (TypeError, ValueError):
        extra = 0
    for _ in range(1 + max(0, min(extra, _MAX_LOCAL_RETRIES))):
        try:
            fn()
            return True
        except Exception:
            continue
    dlq = str((tgt.get("DeadLetterConfig") or {}).get("Arn") or "")
    if dlq and ":sqs:" in dlq:
        try:
            send_sqs(dlq, envelope_str)
        except Exception:
            pass
    return False


def route_event(rules, bus, event_obj, envelope, send_sqs, invoke_lambda, publish_sns, deliver_other=None):
    """Match `event_obj` against every ENABLED rule on `bus` and hand each matching target
    its (Input/InputPath/InputTransformer-shaped) body via the three delivery callbacks.
    Shared by the Nano wire (eventbridge_core) and the offline appliance. Returns #deliveries."""
    base_str = json.dumps(envelope)
    n = 0
    for rule in rules:
        if rule.get("bus", "default") != bus or rule.get("state") != "ENABLED":
            continue
        if not _match_pattern(rule.get("pattern", {}), event_obj):
            continue
        for tgt in rule["targets"].values():
            arn = tgt["Arn"]
            body_str = _target_input(tgt, envelope, base_str)
            if ":sqs:" in arn:
                fn = lambda a=arn, b=body_str: send_sqs(a, b)
            elif ":sns:" in arn:
                fn = lambda a=arn, b=body_str: publish_sns(a, b)
            elif ":lambda:" in arn or ":function:" in arn:
                fn = lambda a=arn, b=body_str: invoke_lambda(a, b)
            elif deliver_other is not None and (":event-bus/" in arn or ":stateMachine:" in arn or ":api-destination/" in arn
                                                or ":kinesis:" in arn or ":log-group:" in arn):
                fn = lambda a=arn, b=body_str, t=tgt: deliver_other(a, b, t)
            else:
                continue
            _deliver_with_retry(tgt, fn, send_sqs, base_str)
            n += 1
    return n


def _store_map(store, attr):
    m = getattr(store, attr, None)
    if m is None:
        m = {}
        setattr(store, attr, m)
    return m


def _create_connection(store, body):
    name = str(body.get("Name", "")).strip()
    if not name:
        raise _E("ValidationException", "Name is required.")
    arn = f"arn:aws:events:{REGION}:{store.account_id}:connection/{name}/{uuid.uuid4()}"
    _store_map(store, "event_connections")[name] = {
        "Name": name, "ConnectionArn": arn, "ConnectionState": "AUTHORIZED",
        "AuthorizationType": body.get("AuthorizationType", "API_KEY"),
        "AuthParameters": body.get("AuthParameters") or {}, "Description": body.get("Description", ""),
        "CreationTime": time.time(), "LastModifiedTime": time.time()}
    store.persist()
    return EventsResponse(body={"ConnectionArn": arn, "ConnectionState": "AUTHORIZED",
                                "CreationTime": time.time(), "LastModifiedTime": time.time()})


def _describe_connection(store, body):
    c = _store_map(store, "event_connections").get(str(body.get("Name", "")))
    if not c:
        raise _E("ResourceNotFoundException", f"Connection {body.get('Name')} does not exist.")
    return EventsResponse(body={k: v for k, v in c.items() if k != "AuthParameters"})


def _delete_connection(store, body):
    _store_map(store, "event_connections").pop(str(body.get("Name", "")), None)
    store.persist()
    return EventsResponse(body={})


def _create_api_destination(store, body):
    name = str(body.get("Name", "")).strip()
    if not name or not body.get("InvocationEndpoint") or not body.get("ConnectionArn"):
        raise _E("ValidationException", "Name, ConnectionArn, InvocationEndpoint and HttpMethod are required.")
    arn = f"arn:aws:events:{REGION}:{store.account_id}:api-destination/{name}/{uuid.uuid4()}"
    _store_map(store, "event_api_destinations")[name] = {
        "Name": name, "ApiDestinationArn": arn, "ApiDestinationState": "ACTIVE",
        "ConnectionArn": body["ConnectionArn"], "InvocationEndpoint": body["InvocationEndpoint"],
        "HttpMethod": body.get("HttpMethod", "POST"), "Description": body.get("Description", ""),
        "InvocationRateLimitPerSecond": body.get("InvocationRateLimitPerSecond", 300),
        "CreationTime": time.time(), "LastModifiedTime": time.time()}
    store.persist()
    return EventsResponse(body={"ApiDestinationArn": arn, "ApiDestinationState": "ACTIVE",
                                "CreationTime": time.time(), "LastModifiedTime": time.time()})


def _describe_api_destination(store, body):
    d = _store_map(store, "event_api_destinations").get(str(body.get("Name", "")))
    if not d:
        raise _E("ResourceNotFoundException", f"An api-destination '{body.get('Name')}' does not exist.")
    return EventsResponse(body=dict(d))


def _list_api_destinations(store, body):
    return EventsResponse(body={"ApiDestinations": list(_store_map(store, "event_api_destinations").values())})


def _delete_api_destination(store, body):
    _store_map(store, "event_api_destinations").pop(str(body.get("Name", "")), None)
    store.persist()
    return EventsResponse(body={})


def _deliver_api_destination(store, arn, body_str, tgt=None):
    """POST/PUT/... the (transformed) event to the destination's endpoint with the connection's auth."""
    import urllib.request
    dest = next((d for d in _store_map(store, "event_api_destinations").values()
                 if d["ApiDestinationArn"] == arn), None)
    if dest is None:
        raise LookupError(f"API destination {arn} does not exist")
    headers = {"Content-Type": "application/json"}
    conn = next((c for c in _store_map(store, "event_connections").values()
                 if c["ConnectionArn"] == dest["ConnectionArn"]), None)
    if conn:
        ap = conn.get("AuthParameters") or {}
        if conn["AuthorizationType"] == "API_KEY" and ap.get("ApiKeyAuthParameters"):
            k = ap["ApiKeyAuthParameters"]
            headers[k.get("ApiKeyName", "x-api-key")] = k.get("ApiKeyValue", "")
        elif conn["AuthorizationType"] == "BASIC" and ap.get("BasicAuthParameters"):
            import base64
            b = ap["BasicAuthParameters"]
            headers["Authorization"] = "Basic " + base64.b64encode(
                f"{b.get('Username', '')}:{b.get('Password', '')}".encode()).decode()
    req = urllib.request.Request(dest["InvocationEndpoint"], data=body_str.encode(),
                                 method=dest.get("HttpMethod", "POST"), headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        if r.status >= 300:
            raise RuntimeError(f"API destination returned {r.status}")


def _put_events(store, body, lambda_store=None, depth=0):
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
        resources = entry.get("Resources") or []
        # The event object rules are matched against (EventBridge's flat shape).
        event_obj = {"source": source, "detail-type": detail_type, "detail": detail,
                     "account": store.account_id, "region": REGION, "resources": resources}
        envelope = {"version": "0", "id": event_id, "detail-type": detail_type, "source": source,
                    "account": store.account_id, "time": _now_iso(), "region": REGION,
                    "resources": resources, "detail": detail}

        def send_sqs(arn, body_str):
            queue = store.get_queue_by_arn(arn)
            if queue is None:
                raise LookupError(f"SQS queue {arn} does not exist")
            sqs_core.enqueue(store, queue, body_str)

        def deliver_other(arn, body_str, tgt=None):
            if ":kinesis:" in arn:
                _deliver_kinesis(arn, body_str, tgt, event_id)
            elif ":log-group:" in arn:
                _deliver_logs(arn, body_str)
            elif ":event-bus/" in arn:
                # Another event bus: re-route the (possibly transformed) event on that bus (depth-capped).
                if depth >= 3:
                    return
                try:
                    ev2 = json.loads(body_str)
                except Exception:
                    return
                if not isinstance(ev2, dict):
                    return
                _put_events(store, {"Entries": [{
                    "Source": ev2.get("source", source), "DetailType": ev2.get("detail-type", detail_type),
                    "Detail": json.dumps(ev2.get("detail", {})), "Resources": ev2.get("resources", []),
                    "EventBusName": arn.rsplit("/", 1)[-1]}]}, lambda_store, depth + 1)
            elif ":api-destination/" in arn:
                _deliver_api_destination(store, arn, body_str, tgt)
            else:  # Step Functions StartExecution with the event as input
                try:
                    from core import stepfunctions_core as sfn
                except ImportError:  # Pyodide flat layout
                    import stepfunctions_core as sfn  # type: ignore
                r = sfn.dispatch(sfn.shared_store(), "AWSStepFunctions.StartExecution",
                                 {"stateMachineArn": arn, "input": body_str}, lambda_store)
                if r.status >= 300:
                    raise RuntimeError(f"StartExecution failed: {r.body}")

        route_event(_rules(store).values(), bus, event_obj, envelope, send_sqs,
                    lambda arn, b: _deliver_lambda(lambda_store, arn, b),
                    lambda arn, b: _deliver_sns(store, arn, b), deliver_other)
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
    "CreateConnection": _create_connection, "DescribeConnection": _describe_connection,
    "DeleteConnection": _delete_connection, "CreateApiDestination": _create_api_destination,
    "DescribeApiDestination": _describe_api_destination, "ListApiDestinations": _list_api_destinations,
    "DeleteApiDestination": _delete_api_destination,
}


def dispatch(store: MessagingStore, target: str, payload: dict | None = None, lambda_store=None) -> EventsResponse:
    """Native EventBridge JSON router. `target` is the X-Amz-Target header,
    e.g. "AWSEvents.PutEvents"."""
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    op = _OPS.get(action)
    if op is None:
        return EventsResponse(status=400, body={"__type": "UnknownOperationException",
                                                "message": f"Unknown operation {action}."})
    try:
        if action == "PutEvents":
            return _put_events(store, body, lambda_store)
        return op(store, body)
    except _E as e:
        return EventsResponse(status=400, body={"__type": e.code, "message": e.message})
