# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""EventBridge core — substrate-independent event-bus data plane (PARITY P4 #15,
extended for the v4 native-fidelity console).

Speaks the native **EventBridge JSON protocol** (X-Amz-Target `AWSEvents.<Op>`,
JSON body) so an unmodified boto3 `events` client works. NO fastapi / boto3 / socket
imports → loads under Pyodide. Reuses the SAME MessagingStore seam as SQS/SNS
(rules live in `store.event_rules`; delivery uses `sqs_core.enqueue` /
`sns_core.publish_arn` / `lambda_core.invoke_by_arn` / `stepfunctions_core.op_start_execution` /
`kinesis_core.put_record`), so an event routed to a queue/topic/function/state
machine/stream is a real, receivable delivery, not a log line.

Scope: event buses (default + custom), rules with event patterns + targets
(enable/disable), PutEvents (pattern match → SQS/SNS/Lambda/Step Functions/Kinesis
fan-out), archives + replay (a bounded per-bus event log stands in for AWS's
unlimited archive retention — RetentionDays IS enforced within that bounded
window, excluding events older than it from DescribeArchive/StartReplay; see the
`eventbridge.archives` capability entry for the honest limitation on the window
itself), tags. Event-pattern operators: exact value lists + {"prefix"},
{"anything-but"}, {"exists"} — mirroring SNS filter policies.
"""
from __future__ import annotations

import base64
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from core.messaging_store import MessagingStore, REGION
from core import sqs_core
from core import sns_core as sns_mod
from core import lambda_core as lam_mod
from core import kinesis_core as kinesis_mod
from core import stepfunctions_core as sfn_mod
from core import cloudwatch_core as _cw_core

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


# ── KMS encryption, bus logs, resource policy (v4 sweep AWS-08) ─────────────
def _kms_call(store, action: str, body: dict) -> dict:
    from core import kms_core
    kms = getattr(store, "kms_store", None)
    if kms is None:
        raise _E("ValidationException", "KMS is not available in this runtime.")
    r = kms_core.dispatch(kms, f"TrentService.{action}", body)
    if getattr(r, "status", 200) != 200:
        b = getattr(r, "body", {}) or {}
        raise _E(str(b.get("__type", "KMSInvalidStateException")).split("#")[-1], b.get("message", "KMS call failed."))
    return r.body


def _validate_kms_key(store, key_id: str) -> str:
    """The key must exist and be usable (Enabled) — resolved through the real KMS core."""
    if not key_id:
        return ""
    md = _kms_call(store, "DescribeKey", {"KeyId": key_id}).get("KeyMetadata") or {}
    if md.get("KeyState") != "Enabled":
        raise _E("ValidationException", f"KMS key {key_id} is in state {md.get('KeyState')}; EventBridge needs an Enabled key.")
    if md.get("KeyUsage") not in (None, "ENCRYPT_DECRYPT"):
        raise _E("ValidationException", "The KMS key must be a symmetric ENCRYPT_DECRYPT key.")
    return md.get("Arn") or key_id


def _seal_envelope(store, bus: dict, envelope: dict) -> dict:
    """Event as stored at rest: with a customer key the payload is real KMS ciphertext."""
    kid = bus.get("kms_key")
    if not kid:
        return envelope
    blob = _kms_call(store, "Encrypt", {"KeyId": kid, "Plaintext": base64.b64encode(json.dumps(envelope).encode()).decode()})
    return {"id": envelope["id"], "time": envelope["time"], "source": envelope.get("source"),
            "detail-type": envelope.get("detail-type"), "_enc": blob["CiphertextBlob"], "_kms": kid}


def _open_envelope(store, e: dict) -> dict | None:
    if "_enc" not in e:
        return e
    try:
        pt = _kms_call(store, "Decrypt", {"CiphertextBlob": e["_enc"]})["Plaintext"]
        return json.loads(base64.b64decode(pt))
    except Exception:
        return None  # key disabled/deleted: the archived payload is unreadable, like real KMS


def _bus_events(store, bus: str) -> list:
    out = []
    for e in _buses(store).get(bus, {}).get("event_log", []):
        o = _open_envelope(store, e)
        if o is not None:
            out.append(o)
    return out


_LOG_LEVELS = {"OFF": 0, "ERROR": 1, "INFO": 2, "TRACE": 3}


def _bus_log(store, bus: dict, level: str, message: str, detail: dict | None = None, envelope: dict | None = None) -> None:
    """Write one structured record to the bus's CloudWatch Logs group (real PutLogEvents)."""
    cfg = bus.get("log_config") or {}
    if _LOG_LEVELS.get(cfg.get("Level", "OFF"), 0) < _LOG_LEVELS[level] or _LOG_LEVELS[level] == 0:
        return
    logs = getattr(store, "logs_store", None)
    if logs is None:
        return
    from core import logs_core
    group = f"/aws/vendedlogs/events/event-bus/{bus['name']}"
    stream = f"{store.account_id}-{bus['name']}"
    logs_core.dispatch(logs, "Logs_20140328.CreateLogGroup", {"logGroupName": group})
    logs_core.dispatch(logs, "Logs_20140328.CreateLogStream", {"logGroupName": group, "logStreamName": stream})
    rec = {"message_type": message, "event_bus_name": bus["name"], "log_level": level, "account": store.account_id}
    if envelope is not None:
        rec.update({"event_id": envelope.get("id"), "source": envelope.get("source"), "detail_type": envelope.get("detail-type")})
        if cfg.get("IncludeDetail") == "FULL":
            rec["detail"] = envelope.get("detail")
    if detail:
        rec.update(detail)
    logs_core.dispatch(logs, "Logs_20140328.PutLogEvents", {"logGroupName": group, "logStreamName": stream, "logEvents": [
        {"timestamp": int(datetime.now(timezone.utc).timestamp() * 1000), "message": json.dumps(rec)}]})


def _norm_log_config(cfg) -> dict:
    cfg = dict(cfg or {})
    lvl = str(cfg.get("Level", "OFF")).upper()
    inc = str(cfg.get("IncludeDetail", "NONE")).upper()
    if lvl not in _LOG_LEVELS:
        raise _E("ValidationException", "LogConfig.Level must be one of OFF, ERROR, INFO, TRACE.")
    if inc not in ("NONE", "FULL"):
        raise _E("ValidationException", "LogConfig.IncludeDetail must be NONE or FULL.")
    return {"Level": lvl, "IncludeDetail": inc}


def _policy_doc(bus: dict) -> dict:
    try:
        d = json.loads(bus.get("policy") or "")
    except Exception:
        d = None
    return d if isinstance(d, dict) else {"Version": "2012-10-17", "Statement": []}


def _principal_account(p) -> list:
    out = []
    vals = p if isinstance(p, list) else [p]
    if isinstance(p, dict):
        vals = p.get("AWS", [])
        vals = vals if isinstance(vals, list) else [vals]
    for v in vals:
        v = str(v)
        out.append("*" if v == "*" else (v.split(":")[4] if v.startswith("arn:") and v.count(":") >= 4 else v))
    return out


def _put_allowed(store, bus: dict, caller_account: str | None) -> bool:
    """Cross-account PutEvents is allowed only by an explicit Allow in the bus resource policy."""
    if not caller_account or caller_account == store.account_id:
        return True
    allowed = False
    for st in _policy_doc(bus).get("Statement", []):
        acts = st.get("Action", [])
        acts = acts if isinstance(acts, list) else [acts]
        if not any(a in ("events:PutEvents", "events:*", "*") for a in acts):
            continue
        princ = _principal_account(st.get("Principal"))
        if caller_account not in princ and "*" not in princ:
            continue
        if st.get("Effect") == "Deny":
            return False
        if st.get("Effect") == "Allow":
            allowed = True
    return allowed


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
def _numeric(ops, value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    it = iter(ops)
    for op in it:
        try:
            n = float(next(it))
        except (StopIteration, TypeError, ValueError):
            return False
        if not {"=": value == n, ">": value > n, ">=": value >= n, "<": value < n, "<=": value <= n}.get(op, False):
            return False
    return True


def _wild(pat: str, value: str) -> bool:
    return re.fullmatch(".*".join(re.escape(x) for x in pat.split("*")), value, re.S) is not None


def _match_value(cond, value) -> bool:
    if isinstance(value, list) and not isinstance(cond, dict):
        return any(_match_value(cond, v) for v in value)
    if isinstance(cond, dict):
        if "prefix" in cond:
            pre = cond["prefix"]
            if isinstance(pre, dict):
                return isinstance(value, str) and value.lower().startswith(str(pre.get("equals-ignore-case", "")).lower())
            return isinstance(value, str) and value.startswith(str(pre))
        if "suffix" in cond:
            suf = cond["suffix"]
            if isinstance(suf, dict):
                return isinstance(value, str) and value.lower().endswith(str(suf.get("equals-ignore-case", "")).lower())
            return isinstance(value, str) and value.endswith(str(suf))
        if "equals-ignore-case" in cond:
            return isinstance(value, str) and value.lower() == str(cond["equals-ignore-case"]).lower()
        if "wildcard" in cond:
            return isinstance(value, str) and _wild(str(cond["wildcard"]), value)
        if "numeric" in cond:
            return _numeric(cond["numeric"], value)
        if "anything-but" in cond:
            ab = cond["anything-but"]
            if isinstance(ab, dict):
                return value is not None and not _match_value(ab, value)
            ab = ab if isinstance(ab, list) else [ab]
            vals = value if isinstance(value, list) else [value]
            return value is not None and not any(v in ab for v in vals)
        if "exists" in cond:
            return (value is not None) == bool(cond["exists"])
        return False
    return cond == value


_LEAF_OPS = ("prefix", "suffix", "anything-but", "exists", "equals-ignore-case", "wildcard", "numeric")


def _match_pattern(pattern: dict, event: dict) -> bool:
    """Every key in the pattern must match; a key matches if the event's value is
    in the listed set (OR). Nested dicts (e.g. `detail`) recurse. `$or` alternates sub-patterns."""
    for key, expected in pattern.items():
        if key == "$or":
            if not any(_match_pattern(alt, event) for alt in expected if isinstance(alt, dict)):
                return False
            continue
        actual = event.get(key)
        if isinstance(expected, dict) and not any(k in expected for k in _LEAF_OPS):
            if isinstance(actual, list):
                if not any(isinstance(a, dict) and _match_pattern(expected, a) for a in actual):
                    return False
            elif not isinstance(actual, dict) or not _match_pattern(expected, actual):
                return False
            continue
        options = expected if isinstance(expected, list) else [expected]
        if not any(_match_value(o, actual) for o in options):
            return False
    return True


# ── delivery (SQS / SNS / Lambda / Step Functions / Kinesis — the target
#    types Vyomi backs; see eventbridge.rule.targets for the rest) ─────────
def deliver(store, lam_store, arn: str, body_str: str, event_obj: dict, group_id=None,
            kinesis_store=None, sfn_store=None, partition_key=None) -> bool:
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
        return False
    if ":states:" in arn and sfn_store is not None:
        try:
            sfn_mod.op_start_execution(sfn_store, {"stateMachineArn": arn, "input": body_str})
            return True
        except Exception:
            return False
    if ":kinesis:" in arn and kinesis_store is not None:
        try:
            kinesis_mod.put_record(kinesis_store, {
                "StreamARN": arn, "PartitionKey": str(partition_key or "eventbridge")[:256],
                "Data": base64.b64encode(body_str.encode()).decode(),
            })
            return True
        except Exception:
            return False
    if ":api-destination/" in arn:
        return deliver_api_destination(store, arn, body_str)
    return False  # target type Vyomi doesn't deliver to (stored, never invoked — see capability doc)


def emit_metric(store, namespace: str, metric: str, dims: list, value: float = 1.0, unit: str = "Count") -> None:
    """eventbridge.metrics: real AWS/Events + AWS/Scheduler datapoints derived from actual
    matching/delivery. `store.cw_store` is a runtime link set by the wire router / nano_registry;
    absent (bare conformance store) it is a no-op."""
    cw = getattr(store, "cw_store", None)
    if cw is not None:
        _cw_core.ingest_internal_metric(cw, namespace, metric, dims, value, unit=unit)


def emit_pipe_metrics(store, pipe_name: str, ok: bool, duration_ms: float) -> None:
    """eventbridge.pipes.metrics: real AWS/EventBridge/Pipes datapoints per actual pipe execution."""
    d = [{"Name": "PipeName", "Value": pipe_name}]
    for dims in (d,):
        emit_metric(store, "AWS/EventBridge/Pipes", "Execution", dims)
        emit_metric(store, "AWS/EventBridge/Pipes", "ExecutionSucceeded" if ok else "ExecutionFailed", dims)
        emit_metric(store, "AWS/EventBridge/Pipes", "Duration", dims, max(duration_ms, 0.0), unit="Milliseconds")


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


def _deliver_to_bus(store, lam_store, bus: str, envelope: dict, event_obj: dict,
                     kinesis_store=None, sfn_store=None) -> int:
    """Match `envelope` against every ENABLED rule on `bus` and deliver to targets.
    Returns the count of (rule, target) deliveries attempted."""
    n = 0
    for rule in list(_rules(store).values()):
        if rule.get("bus", "default") != bus or rule.get("state") != "ENABLED":
            continue
        if not _match_pattern(rule.get("pattern", {}), event_obj):
            continue
        rname = rule.get("name", "")
        rdims = [{"Name": "RuleName", "Value": rname}]
        bdims = [{"Name": "EventBusName", "Value": bus}, {"Name": "RuleName", "Value": rname}]
        for d in (rdims, bdims, [{"Name": "EventBusName", "Value": bus}], []):
            emit_metric(store, "AWS/Events", "TriggeredRules", d)
            emit_metric(store, "AWS/Events", "MatchedEvents", d)
        for tgt in list(rule["targets"].values()):
            body_str = target_payload(dict(tgt, _rule_arn=rule.get("arn", "")), envelope)
            group = (tgt.get("SqsParameters") or {}).get("MessageGroupId")
            pk_path = (tgt.get("KinesisParameters") or {}).get("PartitionKeyPath")
            partition_key = _json_path(envelope, pk_path) if pk_path else None
            ok = deliver(store, lam_store, tgt["Arn"], body_str, event_obj, group_id=group,
                         kinesis_store=kinesis_store, sfn_store=sfn_store,
                         partition_key=partition_key or envelope.get("id"))
            for d in (rdims, bdims, [{"Name": "EventBusName", "Value": bus}], []):
                emit_metric(store, "AWS/Events", "Invocations", d)
                if not ok:
                    emit_metric(store, "AWS/Events", "FailedInvocations", d)
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
    key = _validate_kms_key(store, str(body.get("KmsKeyIdentifier") or ""))
    lc = _norm_log_config(body["LogConfig"]) if body.get("LogConfig") else None
    if body.get("EventSourceName"):
        from core import eventbridge_partner_core as _partner
        _partner.associate_bus(store, name, str(body["EventSourceName"]))
    buses[name] = _new_bus(store, name, body.get("Description", ""), tags)
    buses[name].update({"kms_key": key or None, "log_config": lc, "event_source_name": body.get("EventSourceName") or None})
    store.persist()
    out = {"EventBusArn": buses[name]["arn"], "Description": buses[name]["description"]}
    if key:
        out["KmsKeyIdentifier"] = key
    if lc:
        out["LogConfig"] = lc
    return EventsResponse(body=out)


def _delete_event_bus(store, body):
    name = str(body.get("Name", ""))
    if name == "default":
        raise _E("ValidationException", "Cannot delete the default event bus.")
    buses = _buses(store)
    if buses.pop(name, None) is not None:
        from core import eventbridge_partner_core as _partner
        _partner.bus_deleted(store, name)
        for key in [k for k, r in _rules(store).items() if r.get("bus") == name]:
            _rules(store).pop(key, None)
        for key in [k for k, a in _archives(store).items() if a.get("bus") == name]:
            _archives(store).pop(key, None)
        store.persist()
    return EventsResponse(body={})


def _bus_view(b: dict) -> dict:
    v = {"Name": b["name"], "Arn": b["arn"], "Description": b.get("description", ""), "Policy": b.get("policy"),
         "CreationTime": b.get("created"), "LastModifiedTime": b.get("modified") or b.get("created")}
    if b.get("kms_key"):
        v["KmsKeyIdentifier"] = b["kms_key"]
    if b.get("log_config"):
        v["LogConfig"] = b["log_config"]
    return v


def _list_event_buses(store, body):
    prefix = str(body.get("NamePrefix", "") or "")
    buses = [_bus_view(b)
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
    if "KmsKeyIdentifier" in body:
        bus["kms_key"] = _validate_kms_key(store, str(body.get("KmsKeyIdentifier") or "")) or None
    if "LogConfig" in body:
        bus["log_config"] = _norm_log_config(body.get("LogConfig"))
    bus["modified"] = _now_iso()
    store.persist()
    return EventsResponse(body=_bus_view(bus))


def _put_permission(store, body):
    bus = _buses(store).get(str(body.get("EventBusName", "default") or "default"))
    if not bus:
        raise _E("ResourceNotFoundException", "Event bus does not exist.")
    if body.get("Policy"):
        try:
            doc = json.loads(body["Policy"]) if isinstance(body["Policy"], str) else dict(body["Policy"])
        except Exception:
            raise _E("MalformedPolicyDocumentException", "The policy is not valid JSON.")
        bus["policy"] = json.dumps(doc)
    else:
        sid, princ = body.get("StatementId"), body.get("Principal")
        if not sid or not princ:
            raise _E("ValidationException", "StatementId and Principal are required.")
        doc = _policy_doc(bus)
        if any(st.get("Sid") == sid for st in doc["Statement"]):
            raise _E("ResourceConflictException", f"Statement with the provided id already exists.")
        st = {"Sid": sid, "Effect": "Allow", "Principal": "*" if princ == "*" else {"AWS": f"arn:aws:iam::{princ}:root"},
              "Action": body.get("Action") or "events:PutEvents", "Resource": bus["arn"]}
        if body.get("Condition"):
            st["Condition"] = {body["Condition"].get("Type", "StringEquals"): {body["Condition"].get("Key", "aws:PrincipalOrgID"): body["Condition"].get("Value", "")}}
        doc["Statement"].append(st)
        bus["policy"] = json.dumps(doc)
    store.persist()
    return EventsResponse(body={})


def _remove_permission(store, body):
    bus = _buses(store).get(str(body.get("EventBusName", "default") or "default"))
    if not bus:
        raise _E("ResourceNotFoundException", "Event bus does not exist.")
    if body.get("RemoveAllPermissions"):
        bus["policy"] = None
    else:
        doc = _policy_doc(bus)
        keep = [st for st in doc["Statement"] if st.get("Sid") != body.get("StatementId")]
        if len(keep) == len(doc["Statement"]):
            raise _E("ResourceNotFoundException", "Statement with the provided id does not exist.")
        doc["Statement"] = keep
        bus["policy"] = json.dumps(doc) if keep else None
    store.persist()
    return EventsResponse(body={})


def _describe_event_bus(store, body):
    name = str(body.get("Name", "default") or "default")
    bus = _buses(store).get(name)
    if not bus:
        raise _E("ResourceNotFoundException", f"Event bus {name} does not exist.")
    return EventsResponse(body=_bus_view(bus))


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
def _put_events(store, body, lam_store=None, kinesis_store=None, sfn_store=None, caller_account=None):
    entries_out = []
    for entry in body.get("Entries") or []:
        bus = str(entry.get("EventBusName", "default") or "default")
        if bus not in _buses(store):
            entries_out.append({"ErrorCode": "ResourceNotFoundException",
                                 "ErrorMessage": f"Event bus {bus} does not exist."})
            continue
        if not _put_allowed(store, _buses(store)[bus], caller_account):
            _bus_log(store, _buses(store)[bus], "ERROR", "EVENT_DENIED_BY_RESOURCE_POLICY", {"caller_account": caller_account})
            entries_out.append({"ErrorCode": "AccessDeniedException",
                                 "ErrorMessage": f"Account {caller_account} is not authorized to put events to event bus {bus}: no resource-based policy allows events:PutEvents."})
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
        bus_rec = _buses(store)[bus]
        try:
            sealed = _seal_envelope(store, bus_rec, envelope)
        except _E as e:
            _bus_log(store, bus_rec, "ERROR", "EVENT_ENCRYPTION_FAILED", {"error": e.message}, envelope)
            entries_out.append({"ErrorCode": "InternalFailure", "ErrorMessage": f"Event bus KMS key unusable: {e.message}"})
            continue
        log = bus_rec["event_log"]
        log.append(sealed)
        del log[:-EVENT_LOG_MAX]
        _bus_log(store, bus_rec, "INFO", "EVENT_RECEIVED", None, envelope)
        _notify(store, "put", bus, envelope)
        n = _deliver_to_bus(store, lam_store, bus, envelope, event_obj, kinesis_store=kinesis_store, sfn_store=sfn_store)
        _bus_log(store, bus_rec, "INFO", "INVOKE_SUCCEEDED" if n else "NO_MATCHING_RULES", {"deliveries": n}, envelope)
        try:   # real schema discovery: a STARTED discoverer on this bus infers + versions the event's schema
            from core import eventbridge_schemas_core as _schemas
            _schemas.discover(store, bus, envelope)
        except Exception:
            pass
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
               "description": body.get("Description", ""), "created": _now_iso(), "state": "ENABLED",
               "kms_key": _validate_kms_key(store, str(body.get("KmsKeyIdentifier") or "")) or None}
    _archives(store)[name] = archive
    store.persist()
    return EventsResponse(body={"ArchiveArn": archive["arn"], "State": "ENABLED", "CreationTime": archive["created"]})


def _archived_events(store, archive):
    log = _bus_events(store, archive["bus"])
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
                                 "CreationTime": archive["created"],
                                 **({"KmsKeyIdentifier": archive["kms_key"]} if archive.get("kms_key") else {})})


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


def _start_replay(store, body, lam_store=None, kinesis_store=None, sfn_store=None):
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
        _deliver_to_bus(store, lam_store, dest_bus, replay_envelope, event_obj, kinesis_store=kinesis_store, sfn_store=sfn_store)
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


# ── Connections / API destinations / Global endpoints / TestEventPattern ─────────────────
def _bag(store, key: str) -> dict:
    eb = getattr(store, "_eb", None)
    if callable(eb):
        return eb().setdefault(key, {})
    return store.__dict__.setdefault("eb_bag", {}).setdefault(key, {})


def _auth_view(ctype: str, params: dict) -> dict:
    """DescribeConnection never echoes secrets — only the non-secret identifying fields."""
    params = params or {}
    if ctype == "API_KEY":
        return {"ApiKeyAuthParameters": {"ApiKeyName": (params.get("ApiKeyAuthParameters") or {}).get("ApiKeyName", "")}}
    if ctype == "BASIC":
        return {"BasicAuthParameters": {"Username": (params.get("BasicAuthParameters") or {}).get("Username", "")}}
    o = params.get("OAuthParameters") or {}
    return {"OAuthParameters": {"AuthorizationEndpoint": o.get("AuthorizationEndpoint", ""), "HttpMethod": o.get("HttpMethod", "POST"),
                                "ClientParameters": {"ClientID": (o.get("ClientParameters") or {}).get("ClientID", "")}}}


def _conn_view(c: dict) -> dict:
    return {"ConnectionArn": c["arn"], "Name": c["name"], "Description": c.get("description", ""),
            "ConnectionState": c["state"], "AuthorizationType": c["auth_type"],
            "AuthParameters": _auth_view(c["auth_type"], c["auth"]), "SecretArn": c["secret_arn"],
            "CreationTime": c["created"], "LastModifiedTime": c["modified"], "LastAuthorizedTime": c["authorized"]}


def _require_conn(store, name):
    c = _bag(store, "connections").get(name)
    if c is None:
        raise _E("ResourceNotFoundException", f"Failed to describe the connection(s). Connection '{name}' does not exist.")
    return c


def _create_connection(store, body):
    name = str(body.get("Name", "")).strip()
    atype = body.get("AuthorizationType")
    if not name or not re.fullmatch(r"[\.\-_A-Za-z0-9]{1,64}", name):
        raise _E("ValidationException", "Name must match [\\.\\-_A-Za-z0-9]+ and be 1-64 characters.")
    if atype not in ("BASIC", "OAUTH_CLIENT_CREDENTIALS", "API_KEY"):
        raise _E("ValidationException", "AuthorizationType must be one of BASIC, OAUTH_CLIENT_CREDENTIALS, API_KEY.")
    auth = body.get("AuthParameters") or {}
    need = {"API_KEY": "ApiKeyAuthParameters", "BASIC": "BasicAuthParameters", "OAUTH_CLIENT_CREDENTIALS": "OAuthParameters"}[atype]
    if need not in auth:
        raise _E("ValidationException", f"AuthParameters.{need} is required for AuthorizationType {atype}.")
    bag = _bag(store, "connections")
    if name in bag:
        raise _E("ResourceAlreadyExistsException", f"Connection {name} already exists.")
    uid = str(uuid.uuid4())
    now = _now_iso()
    bag[name] = {"name": name, "arn": f"arn:aws:events:{REGION}:{store.account_id}:connection/{name}/{uid}",
                 "description": body.get("Description", ""), "auth_type": atype, "auth": auth, "state": "AUTHORIZED",
                 "secret_arn": f"arn:aws:secretsmanager:{REGION}:{store.account_id}:secret:events!connection/{name}/{uid}-{uid[:6]}",
                 "created": now, "modified": now, "authorized": now}
    store.persist()
    c = bag[name]
    return EventsResponse(body={"ConnectionArn": c["arn"], "ConnectionState": c["state"], "CreationTime": now, "LastModifiedTime": now})


def _describe_connection(store, body):
    return EventsResponse(body=_conn_view(_require_conn(store, str(body.get("Name", "")))))


def _list_connections(store, body):
    pre, st = str(body.get("NamePrefix") or ""), body.get("ConnectionState")
    out = [{k: v for k, v in _conn_view(c).items() if k not in ("AuthParameters", "SecretArn", "Description")}
           for c in _bag(store, "connections").values() if c["name"].startswith(pre) and (not st or c["state"] == st)]
    return EventsResponse(body={"Connections": out})


def _update_connection(store, body):
    c = _require_conn(store, str(body.get("Name", "")))
    if body.get("Description") is not None:
        c["description"] = body["Description"]
    if body.get("AuthorizationType"):
        if body["AuthorizationType"] not in ("BASIC", "OAUTH_CLIENT_CREDENTIALS", "API_KEY"):
            raise _E("ValidationException", "Invalid AuthorizationType.")
        c["auth_type"] = body["AuthorizationType"]
    if body.get("AuthParameters"):
        c["auth"] = {**(c["auth"] if c["auth_type"] == body.get("AuthorizationType", c["auth_type"]) else {}), **body["AuthParameters"]}
    c["modified"] = c["authorized"] = _now_iso()
    c["state"] = "AUTHORIZED"
    store.persist()
    return EventsResponse(body={"ConnectionArn": c["arn"], "ConnectionState": c["state"], "CreationTime": c["created"],
                                "LastModifiedTime": c["modified"], "LastAuthorizedTime": c["authorized"]})


def _deauthorize_connection(store, body):
    c = _require_conn(store, str(body.get("Name", "")))
    c["state"], c["modified"] = "DEAUTHORIZED", _now_iso()
    store.persist()
    return EventsResponse(body={"ConnectionArn": c["arn"], "ConnectionState": c["state"], "CreationTime": c["created"],
                                "LastModifiedTime": c["modified"], "LastAuthorizedTime": c["authorized"]})


def _delete_connection(store, body):
    c = _require_conn(store, str(body.get("Name", "")))
    used = [d["name"] for d in _bag(store, "apidests").values() if d["connection_arn"] == c["arn"]]
    if used:
        raise _E("ResourceInUseException", f"Connection {c['name']} is used by API destination(s): {', '.join(sorted(used))}.")
    del _bag(store, "connections")[c["name"]]
    store.persist()
    return EventsResponse(body={"ConnectionArn": c["arn"], "ConnectionState": "DELETING", "CreationTime": c["created"],
                                "LastModifiedTime": _now_iso(), "LastAuthorizedTime": c["authorized"]})


_HTTP = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


def _dest_view(d: dict) -> dict:
    return {"ApiDestinationArn": d["arn"], "Name": d["name"], "ApiDestinationState": d["state"], "ConnectionArn": d["connection_arn"],
            "InvocationEndpoint": d["endpoint"], "HttpMethod": d["method"], "InvocationRateLimitPerSecond": d["rate"],
            "Description": d.get("description", ""), "CreationTime": d["created"], "LastModifiedTime": d["modified"]}


def _require_dest(store, name):
    d = _bag(store, "apidests").get(name)
    if d is None:
        raise _E("ResourceNotFoundException", f"An api-destination '{name}' does not exist.")
    return d


def _check_dest(body, d=None):
    ep, m = body.get("InvocationEndpoint", (d or {}).get("endpoint")), body.get("HttpMethod", (d or {}).get("method"))
    if not ep or not re.match(r"^https?://", str(ep)):
        raise _E("ValidationException", "InvocationEndpoint must be a valid http(s) URL.")
    if m not in _HTTP:
        raise _E("ValidationException", f"HttpMethod must be one of {', '.join(_HTTP)}.")
    rate = int(body.get("InvocationRateLimitPerSecond", (d or {}).get("rate") or 300))
    if rate < 1:
        raise _E("ValidationException", "InvocationRateLimitPerSecond must be at least 1.")
    return ep, m, rate


def _create_api_destination(store, body):
    name = str(body.get("Name", "")).strip()
    if not name or not re.fullmatch(r"[\.\-_A-Za-z0-9]{1,64}", name):
        raise _E("ValidationException", "Name must match [\\.\\-_A-Za-z0-9]+ and be 1-64 characters.")
    ep, m, rate = _check_dest(body)
    conn_arn = str(body.get("ConnectionArn", ""))
    if not any(c["arn"] == conn_arn for c in _bag(store, "connections").values()):
        raise _E("ResourceNotFoundException", f"Connection {conn_arn} does not exist.")
    bag = _bag(store, "apidests")
    if name in bag:
        raise _E("ResourceAlreadyExistsException", f"ApiDestination {name} already exists.")
    now = _now_iso()
    bag[name] = {"name": name, "arn": f"arn:aws:events:{REGION}:{store.account_id}:api-destination/{name}/{uuid.uuid4()}",
                 "state": "ACTIVE", "connection_arn": conn_arn, "endpoint": ep, "method": m, "rate": rate,
                 "description": body.get("Description", ""), "created": now, "modified": now}
    store.persist()
    d = bag[name]
    return EventsResponse(body={"ApiDestinationArn": d["arn"], "ApiDestinationState": d["state"], "CreationTime": now, "LastModifiedTime": now})


def _describe_api_destination(store, body):
    return EventsResponse(body=_dest_view(_require_dest(store, str(body.get("Name", "")))))


def _list_api_destinations(store, body):
    pre, ca = str(body.get("NamePrefix") or ""), body.get("ConnectionArn")
    return EventsResponse(body={"ApiDestinations": [
        {k: v for k, v in _dest_view(d).items() if k != "Description"}
        for d in _bag(store, "apidests").values() if d["name"].startswith(pre) and (not ca or d["connection_arn"] == ca)]})


def _update_api_destination(store, body):
    d = _require_dest(store, str(body.get("Name", "")))
    ep, m, rate = _check_dest(body, d)
    if body.get("ConnectionArn"):
        if not any(c["arn"] == body["ConnectionArn"] for c in _bag(store, "connections").values()):
            raise _E("ResourceNotFoundException", f"Connection {body['ConnectionArn']} does not exist.")
        d["connection_arn"] = body["ConnectionArn"]
    d.update(endpoint=ep, method=m, rate=rate, modified=_now_iso())
    if body.get("Description") is not None:
        d["description"] = body["Description"]
    store.persist()
    return EventsResponse(body={"ApiDestinationArn": d["arn"], "ApiDestinationState": d["state"], "CreationTime": d["created"], "LastModifiedTime": d["modified"]})


def _delete_api_destination(store, body):
    d = _require_dest(store, str(body.get("Name", "")))
    del _bag(store, "apidests")[d["name"]]
    store.persist()
    return EventsResponse(body={})


def _endpoint_view(e: dict) -> dict:
    return {"Name": e["name"], "Description": e.get("description", ""), "Arn": e["arn"], "RoutingConfig": e["routing"],
            "ReplicationConfig": e["replication"], "EventBuses": e["buses"], "RoleArn": e.get("role_arn", ""),
            "EndpointId": e["id"], "EndpointUrl": f"https://{e['id']}.endpoint.events.amazonaws.com",
            "State": "ACTIVE", "StateReason": "", "CreationTime": e["created"], "LastModifiedTime": e["modified"]}


def _check_endpoint(body):
    rc = body.get("RoutingConfig") or {}
    fo = rc.get("FailoverConfig") or {}
    if not (fo.get("Primary") or {}).get("HealthCheck") or not (fo.get("Secondary") or {}).get("Route"):
        raise _E("ValidationException", "RoutingConfig.FailoverConfig needs Primary.HealthCheck and Secondary.Route.")
    buses = body.get("EventBuses") or []
    if len(buses) != 2:
        raise _E("ValidationException", "EventBuses must contain exactly two event bus ARNs (primary and secondary region).")
    return rc, buses


def _create_endpoint(store, body):
    name = str(body.get("Name", "")).strip()
    if not name or not re.fullmatch(r"[\.\-_A-Za-z0-9]{1,64}", name):
        raise _E("ValidationException", "Name must match [\\.\\-_A-Za-z0-9]+ and be 1-64 characters.")
    rc, buses = _check_endpoint(body)
    bag = _bag(store, "endpoints")
    if name in bag:
        raise _E("ResourceAlreadyExistsException", f"Endpoint {name} already exists.")
    repl = body.get("ReplicationConfig") or {"State": "ENABLED"}
    now = _now_iso()
    eid = uuid.uuid4().hex[:5] + ".veo"
    bag[name] = {"name": name, "arn": f"arn:aws:events:{REGION}:{store.account_id}:endpoint/{name}", "id": eid, "routing": rc,
                 "replication": repl, "buses": buses, "role_arn": body.get("RoleArn", ""),
                 "description": body.get("Description", ""), "created": now, "modified": now}
    store.persist()
    e = bag[name]
    return EventsResponse(body={"Name": name, "Arn": e["arn"], "RoutingConfig": rc, "ReplicationConfig": repl,
                                "EventBuses": buses, "RoleArn": e["role_arn"], "State": "ACTIVE"})


def _require_endpoint(store, name):
    e = _bag(store, "endpoints").get(name)
    if e is None:
        raise _E("ResourceNotFoundException", f"Endpoint {name} does not exist.")
    return e


def _describe_endpoint(store, body):
    return EventsResponse(body=_endpoint_view(_require_endpoint(store, str(body.get("Name", "")))))


def _list_endpoints(store, body):
    pre = str(body.get("NamePrefix") or "")
    return EventsResponse(body={"Endpoints": [_endpoint_view(e) for e in _bag(store, "endpoints").values() if e["name"].startswith(pre)]})


def _update_endpoint(store, body):
    e = _require_endpoint(store, str(body.get("Name", "")))
    if body.get("RoutingConfig") or body.get("EventBuses"):
        rc, buses = _check_endpoint({"RoutingConfig": body.get("RoutingConfig") or e["routing"], "EventBuses": body.get("EventBuses") or e["buses"]})
        e["routing"], e["buses"] = rc, buses
    for src, dst in (("ReplicationConfig", "replication"), ("RoleArn", "role_arn"), ("Description", "description")):
        if body.get(src) is not None:
            e[dst] = body[src]
    e["modified"] = _now_iso()
    store.persist()
    return EventsResponse(body={"Name": e["name"], "Arn": e["arn"], "RoutingConfig": e["routing"], "ReplicationConfig": e["replication"],
                                "EventBuses": e["buses"], "RoleArn": e["role_arn"], "EndpointId": e["id"],
                                "EndpointUrl": _endpoint_view(e)["EndpointUrl"], "State": "ACTIVE"})


def _delete_endpoint(store, body):
    e = _require_endpoint(store, str(body.get("Name", "")))
    del _bag(store, "endpoints")[e["name"]]
    store.persist()
    return EventsResponse(body={})


def _test_event_pattern(store, body):
    try:
        pattern = json.loads(body.get("EventPattern") or "")
        event = json.loads(body.get("Event") or "")
    except Exception:
        raise _E("InvalidEventPatternException", "Event pattern and event must be valid JSON.")
    if not isinstance(pattern, dict) or not isinstance(event, dict):
        raise _E("InvalidEventPatternException", "Event pattern and event must be JSON objects.")
    for req in ("id", "account", "source", "time", "region", "resources", "detail-type"):
        if req not in event:
            raise _E("ValidationException", f"Parameter Event is not valid. Reason: {req} not found")
    return EventsResponse(body={"Result": bool(_match_pattern(pattern, event))})


def deliver_api_destination(store, arn: str, body_str: str) -> bool:
    """A rule/pipe/schedule target that is an API destination: a real HTTP request to
    InvocationEndpoint with the Connection's auth applied. Offline only has sockets; in the
    browser (Nano) the request cannot leave the sandbox and counts as a FailedInvocation."""
    d = next((x for x in _bag(store, "apidests").values() if x["arn"] == arn), None)
    if d is None or d["state"] != "ACTIVE":
        return False
    c = next((x for x in _bag(store, "connections").values() if x["arn"] == d["connection_arn"]), None)
    if c is None or c["state"] != "AUTHORIZED":
        return False
    headers = {"Content-Type": "application/json", "User-Agent": "Amazon/EventBridge/ApiDestinations"}
    a = c["auth"]
    if c["auth_type"] == "API_KEY":
        k = a.get("ApiKeyAuthParameters") or {}
        headers[k.get("ApiKeyName", "x-api-key")] = k.get("ApiKeyValue", "")
    elif c["auth_type"] == "BASIC":
        b = a.get("BasicAuthParameters") or {}
        headers["Authorization"] = "Basic " + base64.b64encode(f"{b.get('Username','')}:{b.get('Password','')}".encode()).decode()
    try:
        import urllib.request
        req = urllib.request.Request(d["endpoint"], data=body_str.encode() if d["method"] not in ("GET", "HEAD") else None,
                                     headers=headers, method=d["method"])
        with urllib.request.urlopen(req, timeout=5) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


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
    "UpdateEventBus": _update_event_bus, "PutPermission": _put_permission, "RemovePermission": _remove_permission,
    "CreateArchive": _create_archive, "DescribeArchive": _describe_archive,
    "ListArchives": _list_archives, "DeleteArchive": _delete_archive, "UpdateArchive": _update_archive,
    "StartReplay": _start_replay, "DescribeReplay": _describe_replay, "ListReplays": _list_replays,
    "CreateConnection": _create_connection, "DescribeConnection": _describe_connection,
    "ListConnections": _list_connections, "UpdateConnection": _update_connection,
    "DeauthorizeConnection": _deauthorize_connection, "DeleteConnection": _delete_connection,
    "CreateApiDestination": _create_api_destination, "DescribeApiDestination": _describe_api_destination,
    "ListApiDestinations": _list_api_destinations, "UpdateApiDestination": _update_api_destination,
    "DeleteApiDestination": _delete_api_destination,
    "CreateEndpoint": _create_endpoint, "DescribeEndpoint": _describe_endpoint, "ListEndpoints": _list_endpoints,
    "UpdateEndpoint": _update_endpoint, "DeleteEndpoint": _delete_endpoint, "TestEventPattern": _test_event_pattern,
    "TagResource": _tag_resource, "UntagResource": _untag_resource, "ListTagsForResource": _list_tags_for_resource,
}

def _register_partner_ops():
    from core import eventbridge_partner_core as _p
    _OPS.update(_p.OPS)
    _OPS["ActivateEventSource"] = _p.activate_event_source


_register_partner_ops()

# Ops that need the Lambda function store for target delivery.
_NEEDS_LAMBDA = {"PutEvents", "StartReplay"}


def dispatch(store: MessagingStore, target: str, payload: dict | None = None, lam_store=None,
              kinesis_store=None, sfn_store=None, caller_account=None) -> EventsResponse:
    """Native EventBridge JSON router. `target` is the X-Amz-Target header,
    e.g. "AWSEvents.PutEvents". `lam_store` / `kinesis_store` / `sfn_store` (all optional)
    are the Lambda / Kinesis / Step Functions registries, needed only to deliver to
    those target types."""
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    try:
        if action == "PutEvents":
            return _put_events(store, body, lam_store, kinesis_store, sfn_store, caller_account)
        if action == "StartReplay":
            return _start_replay(store, body, lam_store, kinesis_store, sfn_store)
        if action == "PutPartnerEvents":
            from core import eventbridge_partner_core as _partner
            return _partner.put_partner_events(store, body, lam_store, kinesis_store, sfn_store)
        op = _OPS.get(action)
        if op is None:
            return EventsResponse(status=400, body={"__type": "UnknownOperationException",
                                                    "message": f"Unknown operation {action}."})
        return op(store, body)
    except _E as e:
        return EventsResponse(status=400, body={"__type": e.code, "message": e.message})


# ── EventBridge Pipes (REST, botocore `pipes` 2015-10-07) ───────────────────────────────
# A Pipe continuously polls one Source (an SQS queue here — Kinesis/DynamoDB Streams are
# the other real source types, not modeled) and forwards every record straight to a Target
# ARN via the SAME `deliver()` fan-out Rules/Targets and Scheduler use — so a queue wired
# to a RUNNING pipe really drains into its target, not a stored config. Vyomi has no
# standalone poller process, so delivery happens synchronously the moment a message lands
# in the source (see sqs_core._fire_triggers), exactly the "fires when next looked at"
# simplification documented for EventBridge Scheduler. Enrichment and InputTemplate/
# filtering on pipes are accepted and stored but not applied — the raw message body is
# forwarded as-is (see sqs.eventbridge-pipes limitations).
@dataclass
class PipesResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


class _PE(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _pjson(status, obj=None) -> PipesResponse:
    return PipesResponse(status=status, body=b"" if obj is None else json.dumps(obj).encode())


def _pipes(store) -> dict:
    m = getattr(store, "eb_pipes", None)
    if m is None:
        m = {}
        store.eb_pipes = m
    return m


def _pipe_arn(store, name: str) -> str:
    return f"arn:aws:pipes:{REGION}:{store.account_id}:pipe/{name}"


def _pipe_view(p: dict) -> dict:
    return {"Name": p["Name"], "Arn": p["Arn"], "Source": p["Source"], "Target": p["Target"],
            "SourceParameters": p.get("SourceParameters") or {}, "TargetParameters": p.get("TargetParameters") or {},
            "Enrichment": p.get("Enrichment", ""), "RoleArn": p.get("RoleArn", ""),
            "Description": p.get("Description", ""), "DesiredState": p["DesiredState"],
            "CurrentState": p["CurrentState"], "StateReason": p.get("StateReason", ""),
            "CreationTime": p["CreationTime"], "LastModifiedTime": p["LastModifiedTime"]}


def _create_pipe(store, name, body):
    if not name:
        raise _PE("ValidationException", "Name is required.")
    if name in _pipes(store):
        raise _PE("ConflictException", f"Pipe {name} already exists.", 409)
    source = str(body.get("Source", "")).strip()
    target = str(body.get("Target", "")).strip()
    if not source or not target:
        raise _PE("ValidationException", "Source and Target are required.")
    desired = str(body.get("DesiredState") or "RUNNING")
    now = _now_iso()
    p = {"Name": name, "Arn": _pipe_arn(store, name), "Source": source, "Target": target,
         "SourceParameters": body.get("SourceParameters") or {}, "TargetParameters": body.get("TargetParameters") or {},
         "Enrichment": body.get("Enrichment", ""), "RoleArn": body.get("RoleArn", ""),
         "Description": body.get("Description", ""), "DesiredState": desired, "CurrentState": desired,
         "CreationTime": now, "LastModifiedTime": now}
    _pipes(store)[name] = p
    store.persist()
    return _pjson(200, _pipe_view(p))


def _require_pipe(store, name):
    p = _pipes(store).get(name)
    if not p:
        raise _PE("NotFoundException", f"Pipe {name} does not exist.", 404)
    return p


def _describe_pipe(store, name):
    return _pjson(200, _pipe_view(_require_pipe(store, name)))


def _list_pipes(store, query):
    prefix = query.get("NamePrefix", "")
    source_prefix = query.get("SourcePrefix", "")
    rows = [_pipe_view(p) for p in _pipes(store).values()
            if p["Name"].startswith(prefix) and p["Source"].startswith(source_prefix)]
    return _pjson(200, {"Pipes": rows})


def _update_pipe(store, name, body):
    p = _require_pipe(store, name)
    for key in ("Target", "SourceParameters", "TargetParameters", "Enrichment", "Description", "RoleArn"):
        if key in body:
            p[key] = body[key]
    if "DesiredState" in body:
        p["DesiredState"] = str(body["DesiredState"])
        p["CurrentState"] = p["DesiredState"]
    p["LastModifiedTime"] = _now_iso()
    store.persist()
    return _pjson(200, _pipe_view(p))


def _delete_pipe(store, name):
    p = _require_pipe(store, name)
    _pipes(store).pop(name, None)
    p["CurrentState"] = "DELETED"
    store.persist()
    return _pjson(200, _pipe_view(p))


def _set_pipe_state(store, name, state):
    p = _require_pipe(store, name)
    p["DesiredState"] = state
    p["CurrentState"] = state
    p["LastModifiedTime"] = _now_iso()
    store.persist()
    return _pjson(200, _pipe_view(p))


def active_pipes_for_source(store, source_arn: str) -> list[dict]:
    """RUNNING pipes whose Source is `source_arn` — called by the source's own core
    (sqs_core, on SendMessage) the moment a record lands, since Vyomi has no
    standalone poller process to drive this on its own."""
    return [p for p in _pipes(store).values() if p.get("Source") == source_arn and p.get("CurrentState") == "RUNNING"]


_PIPE_START = re.compile(r"^/v1/pipes/([^/]+)/start$")
_PIPE_STOP = re.compile(r"^/v1/pipes/([^/]+)/stop$")
_PIPE_ITEM = re.compile(r"^/v1/pipes/([^/]+)$")


def dispatch_pipes(store, method: str, path: str, query: dict | None = None,
                    headers: dict | None = None, body: bytes = b"") -> PipesResponse:
    """Native EventBridge Pipes REST router (`/v1/pipes[/{Name}[/start|/stop]]`)."""
    query = query or {}
    method = (method or "GET").upper()
    try:
        payload = {}
        if body:
            try:
                payload = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)
            except Exception:
                payload = {}
        if path == "/v1/pipes" and method == "GET":
            return _list_pipes(store, query)
        m = _PIPE_START.match(path)
        if m and method == "POST":
            return _set_pipe_state(store, m.group(1), "RUNNING")
        m = _PIPE_STOP.match(path)
        if m and method == "POST":
            return _set_pipe_state(store, m.group(1), "STOPPED")
        m = _PIPE_ITEM.match(path)
        if m:
            name = m.group(1)
            if method == "POST":
                return _create_pipe(store, name, payload)
            if method == "GET":
                return _describe_pipe(store, name)
            if method == "PUT":
                return _update_pipe(store, name, payload)
            if method == "DELETE":
                return _delete_pipe(store, name)
        msg = f"No route for {method} {path}"
        return PipesResponse(status=404, body=json.dumps({"message": msg, "error": {"code": "NotFoundException", "message": msg}}).encode())
    except _PE as e:
        return PipesResponse(status=e.status, headers={"x-amzn-errortype": e.code},
                              body=json.dumps({"message": e.message, "error": {"code": e.code, "message": e.message}}).encode())
