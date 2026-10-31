"""CloudWatch Logs core — substrate-independent log groups / streams / events.

Speaks the native **CloudWatch Logs JSON protocol** (X-Amz-Target
`Logs_20140328.<Op>`, `application/x-amz-json-1.1`) so an unmodified AWS SDK /
CLI works with only the endpoint changed. Names, request/response members and
error codes follow the botocore `logs` service model.

NO fastapi / boto3 / socket imports → loads under Pyodide (Nano) and on the
host. State lives in PUBLIC dict attrs of a `LogsStore` (the persistence seam):
the offline appliance subclasses it with a SQLite write-through
(core/persistent_store.PersistentLogsStore), Nano snapshots it through
nano_persist.

Scope: log groups, streams, PutLogEvents / GetLogEvents / FilterLogEvents,
retention, tags (legacy + ARN based), metric filters (with TestMetricFilter),
subscription filters, resource policies, KMS association, saved query
definitions and Logs Insights queries (`fields`, `filter`, `sort`, `limit`,
`stats count(*)`).
"""
from __future__ import annotations

import base64
import gzip
import json
import re
import time
import uuid
from dataclasses import dataclass, field

from core import kinesis_core as _kinesis_mod
from core import lambda_core as _lam_mod

DEFAULT_ACCOUNT_ID = "123456789012"
REGION = "us-east-1"
RETENTION_DAYS = {1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731,
                  1096, 1827, 2192, 2557, 2922, 3288, 3653}
MAX_EVENT_BYTES = 256 * 1024
MAX_BATCH_EVENTS = 10000
_NAME_RE = re.compile(r"^[\.\-_/#A-Za-z0-9]+$")
_STREAM_RE = re.compile(r"^[^:*]*$")


@dataclass
class LogsResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class _E(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class LogsStore:
    """Seam: public dict attrs are the whole persisted state."""

    def __init__(self, account_id: str = DEFAULT_ACCOUNT_ID, region: str = REGION) -> None:
        self.account_id = account_id
        self.region = region
        self.log_groups: dict[str, dict] = {}        # name -> group (streams nested)
        self.resource_policies: dict[str, dict] = {}
        self.query_definitions: dict[str, dict] = {}
        self.queries: dict[str, dict] = {}
        self._clock: float | None = None
        self.lam_store = None       # the shared Lambda function registry (set by the wire router) — real subscription-filter delivery
        self.kinesis_store = None   # the shared Kinesis stream store (set by the wire router) — real subscription-filter delivery

    def now_ms(self) -> int:
        return int((self._clock if self._clock is not None else time.time()) * 1000)

    def set_time(self, t: float) -> None:
        self._clock = t

    def persist(self) -> None:  # overridden by durable substrates
        pass


# ── helpers ────────────────────────────────────────────────────────────────
def _group_arn(store, name):
    return f"arn:aws:logs:{store.region}:{store.account_id}:log-group:{name}"


def _stream_arn(store, group, stream):
    return f"{_group_arn(store, group)}:log-stream:{stream}"


def _req(body, key):
    v = body.get(key)
    if v is None or v == "":
        raise _E("InvalidParameterException", f"{key} is required.")
    return v


def _group(store, name):
    g = store.log_groups.get(name)
    if g is None:
        raise _E("ResourceNotFoundException", "The specified log group does not exist.")
    return g


def _resolve_group(store, body):
    name = body.get("logGroupName")
    if not name and body.get("logGroupIdentifier"):
        name = str(body["logGroupIdentifier"])
        if name.startswith("arn:"):
            name = name.split(":log-group:", 1)[-1].split(":", 1)[0]
    return _group(store, _req({"logGroupName": name}, "logGroupName"))


def _stream(group, name):
    s = group["streams"].get(name)
    if s is None:
        raise _E("ResourceNotFoundException", "The specified log stream does not exist.")
    return s


def _group_view(store, g):
    out = {"logGroupName": g["name"], "creationTime": g["creationTime"],
           "metricFilterCount": len(g["metricFilters"]),
           "arn": g["arn"] + ":*", "storedBytes": g["storedBytes"],
           "logGroupClass": g.get("logGroupClass", "STANDARD"),
           "logGroupArn": g["arn"]}
    if g.get("retentionInDays"):
        out["retentionInDays"] = g["retentionInDays"]
    if g.get("kmsKeyId"):
        out["kmsKeyId"] = g["kmsKeyId"]
    out["deletionProtectionEnabled"] = bool(g.get("deletionProtectionEnabled", False))
    # Vyomi console convenience fields (ignored by real SDKs, which deserialize by shape).
    out["dataProtectionMode"] = (g.get("dataProtectionPolicy") or {}).get("_mode")
    out["dataProtectionFindings"] = g.get("dataProtectionFindings", 0)
    return out


def _stream_view(g, s):
    out = {"logStreamName": s["name"], "creationTime": s["creationTime"],
           "arn": s["arn"], "storedBytes": s["storedBytes"],
           "uploadSequenceToken": s["uploadSequenceToken"]}
    if s["events"]:
        out["firstEventTimestamp"] = s["firstEventTimestamp"]
        out["lastEventTimestamp"] = s["lastEventTimestamp"]
        out["lastIngestionTime"] = s["lastIngestionTime"]
    return out


def _page(items, body, key_fn, limit_default=50, limit_max=50):
    """Token pagination: nextToken is the key of the last item returned."""
    limit = int(body.get("limit") or limit_default)
    if limit < 1 or limit > limit_max:
        raise _E("InvalidParameterException", f"limit must be between 1 and {limit_max}.")
    tok = body.get("nextToken")
    if tok:
        items = [i for i in items if key_fn(i) > tok]
    page = items[:limit]
    nxt = key_fn(page[-1]) if len(items) > limit else None
    return page, nxt


# ── log groups ─────────────────────────────────────────────────────────────
def _create_log_group(store, body):
    name = str(_req(body, "logGroupName"))
    if len(name) > 512 or not _NAME_RE.match(name):
        raise _E("InvalidParameterException", "Log group name contains invalid characters or is too long.")
    if name in store.log_groups:
        raise _E("ResourceAlreadyExistsException", "The specified log group already exists")
    g = {"name": name, "arn": _group_arn(store, name), "creationTime": store.now_ms(),
         "storedBytes": 0, "tags": dict(body.get("tags") or {}), "streams": {},
         "metricFilters": {}, "subscriptionFilters": {},
         "logGroupClass": body.get("logGroupClass") or "STANDARD",
         "deletionProtectionEnabled": bool(body.get("deletionProtectionEnabled", False))}
    if body.get("kmsKeyId"):
        g["kmsKeyId"] = body["kmsKeyId"]
    store.log_groups[name] = g
    store.persist()
    return LogsResponse(body={})


def _delete_log_group(store, body):
    name = str(_req(body, "logGroupName"))
    g = _group(store, name)
    if g.get("deletionProtectionEnabled"):
        raise _E("OperationAbortedException", "The specified log group is protected from deletion. Turn off deletion protection to delete it.")
    del store.log_groups[name]
    store.persist()
    return LogsResponse(body={})


def _update_log_group_deletion_protection(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    g["deletionProtectionEnabled"] = bool(body.get("deletionProtectionEnabled", False))
    store.persist()
    return LogsResponse(body={})


def _describe_log_groups(store, body):
    pref, pat = body.get("logGroupNamePrefix"), body.get("logGroupNamePattern")
    groups = sorted(store.log_groups.values(), key=lambda g: g["name"])
    if pref:
        groups = [g for g in groups if g["name"].startswith(pref)]
    if pat:
        groups = [g for g in groups if pat.lower() in g["name"].lower()]
    page, nxt = _page(groups, body, lambda g: g["name"])
    out = {"logGroups": [_group_view(store, g) for g in page]}
    if nxt:
        out["nextToken"] = nxt
    return LogsResponse(body=out)


def _put_retention_policy(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    days = body.get("retentionInDays")
    if days not in RETENTION_DAYS:
        raise _E("InvalidParameterException", "Invalid retentionInDays value.")
    g["retentionInDays"] = int(days)
    store.persist()
    return LogsResponse(body={})


def _delete_retention_policy(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    g.pop("retentionInDays", None)
    store.persist()
    return LogsResponse(body={})


def _associate_kms_key(store, body):
    g = _resolve_group(store, body)
    g["kmsKeyId"] = str(_req(body, "kmsKeyId"))
    store.persist()
    return LogsResponse(body={})


def _disassociate_kms_key(store, body):
    g = _resolve_group(store, body)
    g.pop("kmsKeyId", None)
    store.persist()
    return LogsResponse(body={})


# ── data protection (PII masking) ────────────────────────────────────────────
# A subset of AWS's managed data identifiers — see aws.cloudwatch.logs.data-protection
# for the ones Vyomi doesn't recognize (accepted and stored, but never matched).
_DATA_IDENTIFIERS = {
    "EmailAddress": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "CreditCardNumber": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "Ssn-US": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "AwsSecretKey": re.compile(r"\b[A-Za-z0-9/+=]{40}\b"),
    "AwsAccessKey": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "PhoneNumber-US": re.compile(r"\b\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),
    "IpAddress": re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d{1,2})\.){3}(?:25[0-5]|2[0-4]\d|1?\d{1,2})\b"),
    "Url": re.compile(r"\bhttps?://[^\s\"']+"),
}


def _dp_identifiers(doc: dict) -> set:
    ids = set()
    for stmt in doc.get("Statement") or []:
        for d in stmt.get("DataIdentifier") or []:
            name = str(d).rsplit("/", 1)[-1]
            if name in _DATA_IDENTIFIERS:
                ids.add(name)
    return ids


def _dp_mode(doc: dict) -> str | None:
    """'mask' if any Statement Deidentifies (masking wins when a policy mixes Audit
    statements with Deidentify ones, matching how AWS applies the strictest operation)."""
    saw_audit = False
    for stmt in doc.get("Statement") or []:
        op = stmt.get("Operation") or {}
        if "Deidentify" in op:
            return "mask"
        if "Audit" in op:
            saw_audit = True
    return "audit" if saw_audit else None


def _dp_parse(doc_str: str) -> dict:
    try:
        doc = json.loads(doc_str)
    except Exception:
        raise _E("InvalidParameterException", "The data protection policy is not valid JSON.")
    if not isinstance(doc, dict) or not isinstance(doc.get("Statement"), list) or not doc["Statement"]:
        raise _E("InvalidParameterException", "The data protection policy document must have a non-empty Statement list.")
    return doc


def _apply_data_protection(g: dict, message: str) -> str:
    """Masks the managed data identifiers a Deidentify policy names; an Audit-only policy
    just counts findings (dataProtectionFindings) without altering the stored message —
    both only recognize the identifiers in _DATA_IDENTIFIERS."""
    pol = g.get("dataProtectionPolicy")
    if not pol or not pol["_identifiers"] or not pol["_mode"]:
        return message
    out, total = message, 0
    for name in pol["_identifiers"]:
        rx = _DATA_IDENTIFIERS[name]
        total += len(rx.findall(out))
        if pol["_mode"] == "mask":
            out = rx.sub(lambda m: "*" * len(m.group(0)), out)
    if total:
        g["dataProtectionFindings"] = g.get("dataProtectionFindings", 0) + total
    return out


def _put_data_protection_policy(store, body):
    g = _resolve_group(store, body)
    doc_str = str(_req(body, "policyDocument"))
    doc = _dp_parse(doc_str)
    g["dataProtectionPolicy"] = {"policyDocument": doc_str, "lastUpdatedTime": store.now_ms(),
                                 "_identifiers": _dp_identifiers(doc), "_mode": _dp_mode(doc)}
    store.persist()
    return LogsResponse(body={"logGroupIdentifier": body.get("logGroupIdentifier") or body.get("logGroupName"),
                              "policyDocument": doc_str, "lastUpdatedTime": g["dataProtectionPolicy"]["lastUpdatedTime"]})


def _get_data_protection_policy(store, body):
    g = _resolve_group(store, body)
    pol = g.get("dataProtectionPolicy")
    if not pol:
        raise _E("ResourceNotFoundException", "No data protection policy was found for this log group.")
    return LogsResponse(body={"logGroupIdentifier": body.get("logGroupIdentifier") or body.get("logGroupName"),
                              "policyDocument": pol["policyDocument"], "lastUpdatedTime": pol["lastUpdatedTime"]})


def _delete_data_protection_policy(store, body):
    g = _resolve_group(store, body)
    g.pop("dataProtectionPolicy", None)
    store.persist()
    return LogsResponse(body={})


# ── field indexes ─────────────────────────────────────────────────────────
_FIELD_NAME_RE = re.compile(r"^[@A-Za-z][\w.\-]{0,127}$")


def _index_policy_view(g: dict) -> dict:
    p = g["fieldIndexPolicy"]
    return {"logGroupIdentifier": g["arn"], "lastUpdateTime": p["lastUpdateTime"],
            "policyDocument": p["policyDocument"], "source": "LOG_GROUP"}


def _put_index_policy(store, body):
    g = _resolve_group(store, body)
    doc_str = str(_req(body, "policyDocument"))
    try:
        doc = json.loads(doc_str)
    except Exception:
        raise _E("InvalidParameterException", "The index policy document is not valid JSON.")
    fields = doc.get("fields")
    if not isinstance(fields, list) or not 1 <= len(fields) <= 20:
        raise _E("InvalidParameterException", "fields must be a list of 1 to 20 field names.")
    for f in fields:
        if not isinstance(f, str) or not _FIELD_NAME_RE.match(f):
            raise _E("InvalidParameterException", f"Invalid field name: {f!r}")
    g["fieldIndexPolicy"] = {"policyDocument": doc_str, "lastUpdateTime": store.now_ms()}
    store.persist()
    return LogsResponse(body={"indexPolicyDocument": _index_policy_view(g)})


def _get_index_policy(store, body):
    g = _resolve_group(store, body)
    if "fieldIndexPolicy" not in g:
        raise _E("ResourceNotFoundException", "There is no index policy for this log group.")
    return LogsResponse(body={"indexPolicyDocument": _index_policy_view(g)})


def _delete_index_policy(store, body):
    g = _resolve_group(store, body)
    g.pop("fieldIndexPolicy", None)
    store.persist()
    return LogsResponse(body={})


def _describe_index_policies(store, body):
    out = []
    for ident in body.get("logGroupIdentifiers") or []:
        try:
            g = _resolve_group(store, {"logGroupIdentifier": ident})
        except _E:
            continue
        if "fieldIndexPolicy" in g:
            out.append(_index_policy_view(g))
    return LogsResponse(body={"indexPolicies": out})


# ── transformer (ingestion-time processor pipeline) ────────────────────────
# A subset of AWS's processors — see aws.cloudwatch.logs.transformer for the rest.
_TRANSFORMER_PROCESSORS = {"parseJSON", "addKeys", "deleteKeys", "renameKeys"}


def _validate_transformer_config(cfg):
    if not isinstance(cfg, list) or not cfg:
        raise _E("InvalidParameterException", "transformerConfig must be a non-empty list of processors.")
    for proc in cfg:
        if not isinstance(proc, dict) or len(proc) != 1 or next(iter(proc)) not in _TRANSFORMER_PROCESSORS:
            raise _E("InvalidParameterException", f"Unsupported or malformed processor: {proc!r}")


def _run_transformer(cfg: list, message: str) -> str:
    """Runs the ingestion-time processor pipeline, returning the message that gets stored
    (a JSON rendering of the working document if any processor touched it, else the raw
    message unchanged)."""
    doc: dict = {"@message": message}
    changed = False
    for proc in cfg:
        kind, params = next(iter(proc.items()))
        params = params or {}
        if kind == "parseJSON":
            try:
                parsed = json.loads(doc.get(params.get("source", "@message"), ""))
            except Exception:
                continue
            if not isinstance(parsed, dict):
                continue
            dest = params.get("destination")
            if dest:
                doc[dest] = parsed
            else:
                doc.update(parsed)
            changed = True
        elif kind == "addKeys":
            for e in params.get("entries") or []:
                k = e.get("key")
                if k and (e.get("overwriteIfExists") or k not in doc):
                    doc[k] = e.get("value")
                    changed = True
        elif kind == "deleteKeys":
            for k in params.get("withKeys") or []:
                if doc.pop(k, None) is not None:
                    changed = True
        elif kind == "renameKeys":
            for e in params.get("entries") or []:
                k, new = e.get("key"), e.get("renameTo")
                if new and k in doc:
                    doc[new] = doc.pop(k)
                    changed = True
    if not changed:
        return message
    out = dict(doc)
    out.pop("@message", None)
    return json.dumps(out, separators=(",", ":"))


def _put_transformer(store, body):
    g = _resolve_group(store, body)
    cfg = body.get("transformerConfig")
    _validate_transformer_config(cfg)
    g["transformerConfig"] = cfg
    store.persist()
    return LogsResponse(body={})


def _get_transformer(store, body):
    g = _resolve_group(store, body)
    cfg = g.get("transformerConfig")
    if cfg is None:
        raise _E("ResourceNotFoundException", "There is no transformer for this log group.")
    return LogsResponse(body={"logGroupIdentifier": body.get("logGroupIdentifier") or body.get("logGroupName"), "transformerConfig": cfg})


def _delete_transformer(store, body):
    g = _resolve_group(store, body)
    g.pop("transformerConfig", None)
    store.persist()
    return LogsResponse(body={})


# ── tags ───────────────────────────────────────────────────────────────────
def _tag_log_group(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    g["tags"].update({str(k): str(v) for k, v in (body.get("tags") or {}).items()})
    store.persist()
    return LogsResponse(body={})


def _untag_log_group(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    for k in body.get("tags") or []:
        g["tags"].pop(k, None)
    store.persist()
    return LogsResponse(body={})


def _list_tags_log_group(store, body):
    return LogsResponse(body={"tags": dict(_group(store, str(_req(body, "logGroupName")))["tags"])})


def _group_by_arn(store, arn):
    arn = str(arn)
    for g in store.log_groups.values():
        if arn in (g["arn"], g["arn"] + ":*"):
            return g
    raise _E("ResourceNotFoundException", "The specified resource does not exist.")


def _tag_resource(store, body):
    g = _group_by_arn(store, _req(body, "resourceArn"))
    g["tags"].update({str(k): str(v) for k, v in (body.get("tags") or {}).items()})
    store.persist()
    return LogsResponse(body={})


def _untag_resource(store, body):
    g = _group_by_arn(store, _req(body, "resourceArn"))
    for k in body.get("tagKeys") or []:
        g["tags"].pop(k, None)
    store.persist()
    return LogsResponse(body={})


def _list_tags_for_resource(store, body):
    return LogsResponse(body={"tags": dict(_group_by_arn(store, _req(body, "resourceArn"))["tags"])})


# ── streams + events ───────────────────────────────────────────────────────
def _create_log_stream(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    name = str(_req(body, "logStreamName"))
    if len(name) > 512 or not _STREAM_RE.match(name):
        raise _E("InvalidParameterException", "Log stream name contains invalid characters or is too long.")
    if name in g["streams"]:
        raise _E("ResourceAlreadyExistsException", "The specified log stream already exists")
    g["streams"][name] = {"name": name, "arn": _stream_arn(store, g["name"], name),
                          "creationTime": store.now_ms(), "storedBytes": 0,
                          "uploadSequenceToken": "49" + uuid.uuid4().hex[:24] + str(store.now_ms())[-8:],
                          "events": [], "firstEventTimestamp": 0, "lastEventTimestamp": 0,
                          "lastIngestionTime": 0}
    store.persist()
    return LogsResponse(body={})


def _delete_log_stream(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    name = str(_req(body, "logStreamName"))
    s = _stream(g, name)
    g["storedBytes"] -= s["storedBytes"]
    del g["streams"][name]
    store.persist()
    return LogsResponse(body={})


def _describe_log_streams(store, body):
    g = _resolve_group(store, body)
    pref = body.get("logStreamNamePrefix")
    if pref and body.get("orderBy") == "LastEventTime":
        raise _E("InvalidParameterException", "Cannot order by LastEventTime with a logStreamNamePrefix.")
    ss = list(g["streams"].values())
    if pref:
        ss = [s for s in ss if s["name"].startswith(pref)]
    if body.get("orderBy") == "LastEventTime":
        ss.sort(key=lambda s: s["lastEventTimestamp"], reverse=bool(body.get("descending")))
        limit = int(body.get("limit") or 50)
        return LogsResponse(body={"logStreams": [_stream_view(g, s) for s in ss[:limit]]})
    ss.sort(key=lambda s: s["name"], reverse=bool(body.get("descending")))
    page, nxt = _page(ss, body, lambda s: s["name"]) if not body.get("descending") else (ss[:int(body.get("limit") or 50)], None)
    out = {"logStreams": [_stream_view(g, s) for s in page]}
    if nxt:
        out["nextToken"] = nxt
    return LogsResponse(body=out)


def _put_log_events(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    s = _stream(g, str(_req(body, "logStreamName")))
    events = body.get("logEvents")
    if not events:
        raise _E("InvalidParameterException", "logEvents must contain at least 1 event.")
    if len(events) > MAX_BATCH_EVENTS:
        raise _E("InvalidParameterException", f"Log event batch exceeds {MAX_BATCH_EVENTS} events.")
    now = store.now_ms()
    day = 24 * 3600 * 1000
    retention = g.get("retentionInDays")
    ok, too_old, too_new, expired = [], 0, 0, 0
    for e in events:
        ts, msg = e.get("timestamp"), e.get("message")
        if ts is None or msg is None:
            raise _E("InvalidParameterException", "Each log event requires timestamp and message.")
        if len(str(msg).encode("utf-8")) + 26 > MAX_EVENT_BYTES:
            raise _E("InvalidParameterException", "Log event exceeds the 256 KB limit.")
        if ts < now - 14 * day:
            too_old += 1
        elif ts > now + 2 * 3600 * 1000:
            too_new += 1
        elif retention and ts < now - retention * day:
            expired += 1
        else:
            out_msg = str(msg)
            if g.get("transformerConfig"):
                out_msg = _run_transformer(g["transformerConfig"], out_msg)
            out_msg = _apply_data_protection(g, out_msg)
            ok.append({"timestamp": int(ts), "message": out_msg, "ingestionTime": now})
    ok.sort(key=lambda e: e["timestamp"])
    added = sum(len(e["message"].encode("utf-8")) + 26 for e in ok)
    s["events"].extend(ok)
    s["events"].sort(key=lambda e: e["timestamp"])
    s["storedBytes"] += added
    g["storedBytes"] += added
    if ok:
        s["firstEventTimestamp"] = s["events"][0]["timestamp"]
        s["lastEventTimestamp"] = s["events"][-1]["timestamp"]
        s["lastIngestionTime"] = now
    s["uploadSequenceToken"] = "49" + uuid.uuid4().hex[:24] + str(now)[-8:]
    out = {"nextSequenceToken": s["uploadSequenceToken"]}
    rej = {}
    if too_old:
        rej["tooOldLogEventEndIndex"] = too_old
    if too_new:
        rej["tooNewLogEventStartIndex"] = len(events) - too_new
    if expired:
        rej["expiredLogEventEndIndex"] = expired
    if rej:
        out["rejectedLogEventsInfo"] = rej
    _deliver_subscriptions(store, g, s, ok)
    store.persist()
    return LogsResponse(body=out)


def _subscription_envelope(store, g, s, events) -> bytes:
    """The gzip-compressed JSON payload a real CloudWatch Logs subscription delivers
    (CloudWatch Logs -> Lambda/Kinesis), matching the `awslogs`/`DATA_MESSAGE` shape."""
    doc = {"messageType": "DATA_MESSAGE", "owner": store.account_id, "logGroup": g["name"], "logStream": s["name"],
           "subscriptionFilters": [f["filterName"] for f in g["subscriptionFilters"].values()],
           "logEvents": [{"id": uuid.uuid4().hex, "timestamp": e["timestamp"], "message": e["message"]} for e in events]}
    return gzip.compress(json.dumps(doc).encode())


def _deliver_subscriptions(store, g, s, events):
    """Subscription filters really fan out: a Lambda destination is invoked (lambda_core.
    invoke_by_arn) and a Kinesis destination really receives a PutRecord (kinesis_core.
    put_record), both with the real gzip+base64 `awslogs` envelope. A Firehose destination
    has no backing core and is kept as a delivery counter — see
    aws.cloudwatch.logs.subscription-filters."""
    for f in g["subscriptionFilters"].values():
        matched = [e for e in events if _filter_match(f.get("filterPattern", ""), e["message"])]
        if not matched:
            continue
        f["deliveredEvents"] = f.get("deliveredEvents", 0) + len(matched)
        arn = str(f.get("destinationArn", ""))
        if ":lambda:" in arn and store.lam_store is not None:
            payload = base64.b64encode(_subscription_envelope(store, g, s, matched)).decode()
            try:
                _lam_mod.invoke_by_arn(store.lam_store, arn, {"awslogs": {"data": payload}})
            except Exception:
                pass
        elif ":kinesis:" in arn and store.kinesis_store is not None:
            payload = base64.b64encode(_subscription_envelope(store, g, s, matched)).decode()
            try:
                _kinesis_mod.put_record(store.kinesis_store, {"StreamARN": arn, "Data": payload, "PartitionKey": s["name"]})
            except Exception:
                pass


def _get_log_events(store, body):
    g = _resolve_group(store, body)
    s = _stream(g, str(_req(body, "logStreamName")))
    evs = s["events"]
    start, end = body.get("startTime"), body.get("endTime")
    if start is not None:
        evs = [e for e in evs if e["timestamp"] >= start]
    if end is not None:
        evs = [e for e in evs if e["timestamp"] < end]
    limit = int(body.get("limit") or 10000)
    start_from_head = bool(body.get("startFromHead"))
    tok = body.get("nextToken")
    if tok and tok[:2] in ("f/", "b/"):
        pos = int(tok[2:])
        if tok[0] == "f":
            page, lo = evs[pos:pos + limit], pos
            hi = pos + len(page)
        else:
            lo = max(0, pos - limit)
            page, hi = evs[lo:pos], pos
    elif start_from_head:
        page, lo, hi = evs[:limit], 0, min(limit, len(evs))
    else:
        lo = max(0, len(evs) - limit)
        page, hi = evs[lo:], len(evs)
    out = {"events": [dict(e) for e in page],
           "nextForwardToken": f"f/{hi}", "nextBackwardToken": f"b/{lo}"}
    return LogsResponse(body=out)


def _filter_match(pattern, message) -> bool:
    p = (pattern or "").strip()
    if not p:
        return True
    if p.startswith("{") and p.endswith("}"):
        return _json_filter(p[1:-1].strip(), message)
    toks = re.findall(r'-?"[^"]*"|-?\?"[^"]*"|\?\S+|-?\S+', p)
    any_of = [t[1:].strip('"') for t in toks if t.startswith("?")]
    if any_of and not any(a in message for a in any_of):
        return False
    for t in toks:
        if t.startswith("?"):
            continue
        neg = t.startswith("-")
        term = t[1:] if neg else t
        term = term.strip('"')
        if (term in message) == neg:
            return False
    return True


def _json_filter(expr, message) -> bool:
    try:
        doc = json.loads(message)
    except Exception:
        return False
    for clause in re.split(r"\s*&&\s*", expr):
        m = re.match(r'^\$\.?([\w\.\[\]]+)\s*(=|!=|>=|<=|>|<)\s*(.+)$', clause.strip())
        if not m:
            return False
        path, op, raw = m.groups()
        cur = doc
        for part in re.split(r"\.", path):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return False
        raw = raw.strip().strip('"')
        try:
            lhs, rhs = float(cur), float(raw)
        except (TypeError, ValueError):
            lhs, rhs = str(cur), raw
        ok = {"=": lhs == rhs, "!=": lhs != rhs, ">": lhs > rhs, "<": lhs < rhs,
              ">=": lhs >= rhs, "<=": lhs <= rhs}[op]
        if not ok:
            return False
    return True


def _filter_log_events(store, body):
    g = _resolve_group(store, body)
    names = body.get("logStreamNames")
    pref = body.get("logStreamNamePrefix")
    streams = [s for n, s in g["streams"].items()
               if (not names or n in names) and (not pref or n.startswith(pref))]
    pattern = body.get("filterPattern", "")
    start, end = body.get("startTime"), body.get("endTime")
    rows = []
    for s in streams:
        for i, e in enumerate(s["events"]):
            if start is not None and e["timestamp"] < start:
                continue
            if end is not None and e["timestamp"] > end:
                continue
            if _filter_match(pattern, e["message"]):
                rows.append({"logStreamName": s["name"], "timestamp": e["timestamp"],
                             "message": e["message"], "ingestionTime": e["ingestionTime"],
                             "eventId": f"{e['ingestionTime']:x}{i:08x}{len(s['name']):08d}"})
    rows.sort(key=lambda r: (r["timestamp"], r["logStreamName"]))
    limit = int(body.get("limit") or 10000)
    pos = int(body["nextToken"]) if body.get("nextToken") else 0
    page = rows[pos:pos + limit]
    out = {"events": page,
           "searchedLogStreams": [{"logStreamName": s["name"], "searchedCompletely": True} for s in streams]}
    if pos + limit < len(rows):
        out["nextToken"] = str(pos + limit)
    return LogsResponse(body=out)


# ── metric filters ─────────────────────────────────────────────────────────
def _put_metric_filter(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    name = str(_req(body, "filterName"))
    tr = _req(body, "metricTransformations")
    if not isinstance(tr, list) or not tr:
        raise _E("InvalidParameterException", "metricTransformations must contain 1 item.")
    if name not in g["metricFilters"] and len(g["metricFilters"]) >= 100:
        raise _E("LimitExceededException", "Resource limit exceeded.")
    g["metricFilters"][name] = {"filterName": name, "filterPattern": body.get("filterPattern", ""),
                                "metricTransformations": tr, "creationTime": store.now_ms(),
                                "logGroupName": g["name"]}
    store.persist()
    return LogsResponse(body={})


def _describe_metric_filters(store, body):
    fs = []
    if body.get("logGroupName"):
        fs = list(_group(store, body["logGroupName"])["metricFilters"].values())
    else:
        for g in store.log_groups.values():
            fs += list(g["metricFilters"].values())
    if body.get("filterNamePrefix"):
        fs = [f for f in fs if f["filterName"].startswith(body["filterNamePrefix"])]
    mn, ns = body.get("metricName"), body.get("metricNamespace")
    if mn and ns:
        fs = [f for f in fs if any(t.get("metricName") == mn and t.get("metricNamespace") == ns
                                   for t in f["metricTransformations"])]
    fs.sort(key=lambda f: f["filterName"])
    page, nxt = _page(fs, body, lambda f: f["filterName"])
    out = {"metricFilters": page}
    if nxt:
        out["nextToken"] = nxt
    return LogsResponse(body=out)


def _delete_metric_filter(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    name = str(_req(body, "filterName"))
    if name not in g["metricFilters"]:
        raise _E("ResourceNotFoundException", "The specified metric filter does not exist.")
    del g["metricFilters"][name]
    store.persist()
    return LogsResponse(body={})


def _test_metric_filter(store, body):
    pattern = body.get("filterPattern", "")
    msgs = _req(body, "logEventMessages")
    matches = [{"eventNumber": i + 1, "eventMessage": m, "extractedValues": {}}
               for i, m in enumerate(msgs) if _filter_match(pattern, m)]
    return LogsResponse(body={"matches": matches})


# ── subscription filters ───────────────────────────────────────────────────
def _put_subscription_filter(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    name = str(_req(body, "filterName"))
    if name not in g["subscriptionFilters"] and len(g["subscriptionFilters"]) >= 2:
        raise _E("LimitExceededException", "Resource limit exceeded.")
    g["subscriptionFilters"][name] = {
        "filterName": name, "logGroupName": g["name"],
        "filterPattern": body.get("filterPattern", ""),
        "destinationArn": str(_req(body, "destinationArn")),
        "roleArn": body.get("roleArn", ""), "distribution": body.get("distribution", "ByLogStream"),
        "creationTime": store.now_ms()}
    store.persist()
    return LogsResponse(body={})


def _describe_subscription_filters(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    fs = sorted(g["subscriptionFilters"].values(), key=lambda f: f["filterName"])
    if body.get("filterNamePrefix"):
        fs = [f for f in fs if f["filterName"].startswith(body["filterNamePrefix"])]
    page, nxt = _page(fs, body, lambda f: f["filterName"])
    out = {"subscriptionFilters": [{k: v for k, v in f.items() if k != "deliveredEvents"} for f in page]}
    if nxt:
        out["nextToken"] = nxt
    return LogsResponse(body=out)


def _delete_subscription_filter(store, body):
    g = _group(store, str(_req(body, "logGroupName")))
    name = str(_req(body, "filterName"))
    if name not in g["subscriptionFilters"]:
        raise _E("ResourceNotFoundException", "The specified subscription filter does not exist.")
    del g["subscriptionFilters"][name]
    store.persist()
    return LogsResponse(body={})


# ── resource policies ──────────────────────────────────────────────────────
def _put_resource_policy(store, body):
    name = str(body.get("policyName") or "")
    if not name:
        raise _E("InvalidParameterException", "policyName is required.")
    doc = str(_req(body, "policyDocument"))
    try:
        json.loads(doc)
    except Exception:
        raise _E("InvalidParameterException", "policyDocument is not valid JSON.")
    p = {"policyName": name, "policyDocument": doc, "lastUpdatedTime": store.now_ms()}
    store.resource_policies[name] = p
    store.persist()
    return LogsResponse(body={"resourcePolicy": p})


def _describe_resource_policies(store, body):
    ps = sorted(store.resource_policies.values(), key=lambda p: p["policyName"])
    return LogsResponse(body={"resourcePolicies": ps})


def _delete_resource_policy(store, body):
    name = str(_req(body, "policyName"))
    if name not in store.resource_policies:
        raise _E("ResourceNotFoundException", "The specified policy does not exist.")
    del store.resource_policies[name]
    store.persist()
    return LogsResponse(body={})


# ── saved queries + Logs Insights ──────────────────────────────────────────
def _put_query_definition(store, body):
    name = str(_req(body, "name"))
    qid = body.get("queryDefinitionId") or str(uuid.uuid4())
    if body.get("queryDefinitionId") and qid not in store.query_definitions:
        raise _E("ResourceNotFoundException", "The specified query definition does not exist.")
    store.query_definitions[qid] = {
        "queryDefinitionId": qid, "name": name, "queryString": str(_req(body, "queryString")),
        "logGroupNames": list(body.get("logGroupNames") or []), "lastModified": store.now_ms()}
    store.persist()
    return LogsResponse(body={"queryDefinitionId": qid})


def _describe_query_definitions(store, body):
    qs = sorted(store.query_definitions.values(), key=lambda q: q["name"])
    if body.get("queryDefinitionNamePrefix"):
        qs = [q for q in qs if q["name"].startswith(body["queryDefinitionNamePrefix"])]
    return LogsResponse(body={"queryDefinitions": qs})


def _delete_query_definition(store, body):
    qid = str(_req(body, "queryDefinitionId"))
    ok = store.query_definitions.pop(qid, None) is not None
    store.persist()
    return LogsResponse(body={"success": ok})


def _start_query(store, body):
    names = body.get("logGroupNames") or []
    if body.get("logGroupName"):
        names = [body["logGroupName"]]
    for n in names:
        _group(store, n)
    if not names:
        raise _E("InvalidParameterException", "At least one log group must be specified.")
    qs = str(_req(body, "queryString"))
    start, end = int(_req(body, "startTime")), int(_req(body, "endTime"))
    if end < start:
        raise _E("InvalidParameterException", "End time must not be before start time.")
    rows, stats = _run_insights(store, names, qs, start * 1000, end * 1000)
    qid = str(uuid.uuid4())
    store.queries[qid] = {"queryId": qid, "queryString": qs, "status": "Complete",
                          "createTime": store.now_ms(), "logGroupName": names[0],
                          "results": rows, "statistics": stats}
    store.persist()
    return LogsResponse(body={"queryId": qid})


_PATTERN_TOKEN_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|0x[0-9a-fA-F]+|\b[0-9a-fA-F]{12,}\b|\d+(?:\.\d+)?")


def _mine_pattern(msg: str) -> str:
    """The template a log line reduces to once its variable parts (numbers, hex blobs,
    UUIDs) are masked — the same tokenization Logs Insights' `pattern` command and the
    console's Patterns tab use to group similar lines (see aws.cloudwatch.logs.patterns-visualization)."""
    return _PATTERN_TOKEN_RE.sub("<*>", msg)


def _duration_secs(s: str) -> int:
    total = sum(int(n) * {"s": 1, "m": 60, "h": 3600}[u] for n, u in re.findall(r"(\d+)\s*([smh])", s, re.I))
    return total or 60


def _run_insights(store, groups, qs, start_ms, end_ms):
    stages = [s.strip() for s in qs.split("|") if s.strip()]
    recs = []
    for gn in groups:
        for s in store.log_groups[gn]["streams"].values():
            for e in s["events"]:
                if start_ms <= e["timestamp"] <= end_ms:
                    recs.append({"@timestamp": _iso(e["timestamp"]), "@message": e["message"],
                                 "@logStream": s["name"], "@log": f"{store.account_id}:{gn}",
                                 "_ts": e["timestamp"]})
    scanned = len(recs)
    fields = None
    stats_col = None
    for st in stages:
        low = st.lower()
        if low.startswith("fields") or low.startswith("display"):
            fields = [f.strip() for f in st.split(None, 1)[1].split(",")]
        elif low.startswith("filter"):
            m = re.match(r'^filter\s+(@?\w+)\s*(like|=|!=|>=|<=|>|<)\s*(.+)$', st, re.I)
            if m:
                f, op, val = m.groups()
                val = val.strip()
                if op.lower() == "like":
                    pat = val.strip("/\"'")
                    recs = [r for r in recs if re.search(pat, str(r.get(f, "")))]
                else:
                    v = val.strip("\"'")
                    def cmp(r, f=f, op=op, v=v):
                        a = r.get(f, "")
                        try:
                            a, b = float(a), float(v)
                        except (TypeError, ValueError):
                            a, b = str(a), v
                        return {"=": a == b, "!=": a != b, ">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]
                    recs = [r for r in recs if cmp(r)]
        elif low.startswith("sort"):
            m = re.match(r'^sort\s+(@?\w+)\s*(asc|desc)?', st, re.I)
            if m:
                recs.sort(key=lambda r: r.get(m.group(1), ""), reverse=(m.group(2) or "asc").lower() == "desc")
        elif low.startswith("limit"):
            recs = recs[:int(st.split()[1])]
        elif low.startswith("pattern"):
            m = re.match(r'^pattern\s+(@?\w+)\s*$', st, re.I)
            field = m.group(1) if m else "@message"
            mined: dict[str, list] = {}
            for r in recs:
                mined.setdefault(_mine_pattern(str(r.get(field, ""))), []).append(r)
            total = len(recs) or 1
            rows = []
            for tmpl, members in mined.items():
                rows.append({"@pattern": tmpl, "@severityLabel": "ERROR" if re.search(r"error|exception|fail", tmpl, re.I) else "BASELINE",
                            "@ratio": f"{len(members) / total:.4f}", "@sampleCount": str(len(members)),
                            "@logSamples": json.dumps([m.get(field, "") for m in members[:3]])})
            rows.sort(key=lambda r: -int(r["@sampleCount"]))
            recs = rows
            fields = ["@pattern", "@severityLabel", "@ratio", "@sampleCount", "@logSamples"]
            stats_col = True
        elif low.startswith("stats"):
            m = re.match(r'^stats\s+count\(\*?\)\s*(?:as\s+(\w+))?\s*(?:by\s+(.+))?$', st, re.I)
            if m:
                alias, by = m.group(1) or "count(*)", (m.group(2) or "").strip()
                if by:
                    bm = re.match(r'^bin\(\s*([\dsmh]+)\s*\)$', by, re.I)
                    if bm:
                        secs_ms = _duration_secs(bm.group(1)) * 1000
                        key = lambda r: _iso(int(r["_ts"] // secs_ms * secs_ms))
                    else:
                        key = lambda r: str(r.get(by, ""))
                    buckets: dict = {}
                    for r in recs:
                        k = key(r)
                        buckets[k] = buckets.get(k, 0) + 1
                    recs = [{by: k, alias: str(v)} for k, v in sorted(buckets.items())]
                    fields = [by, alias]
                else:
                    recs = [{alias: str(len(recs))}]
                    fields = [alias]
                stats_col = True
    if fields is None:
        fields = ["@timestamp", "@message"]
    out = []
    for r in recs:
        row = [{"field": f, "value": str(r.get(f, ""))} for f in fields if f in r or not stats_col]
        row.append({"field": "@ptr", "value": uuid.uuid4().hex})
        out.append(row)
    return out, {"recordsMatched": float(len(recs)), "recordsScanned": float(scanned),
                 "bytesScanned": float(sum(len(r.get("@message", "")) for r in recs))}


def _iso(ms):
    t = time.gmtime(ms / 1000)
    return time.strftime("%Y-%m-%d %H:%M:%S", t) + f".{int(ms % 1000):03d}"


def _get_query_results(store, body):
    q = store.queries.get(str(_req(body, "queryId")))
    if q is None:
        raise _E("ResourceNotFoundException", "The specified query does not exist.")
    return LogsResponse(body={"queryLanguage": "CWLI", "results": q["results"],
                              "statistics": q["statistics"], "status": q["status"]})


def _stop_query(store, body):
    q = store.queries.get(str(_req(body, "queryId")))
    if q is None:
        raise _E("ResourceNotFoundException", "The specified query does not exist.")
    return LogsResponse(body={"success": q["status"] == "Running"})


def _describe_queries(store, body):
    qs = [{"queryId": q["queryId"], "queryString": q["queryString"], "status": q["status"],
           "createTime": q["createTime"], "logGroupName": q["logGroupName"], "queryLanguage": "CWLI"}
          for q in store.queries.values()]
    if body.get("logGroupName"):
        qs = [q for q in qs if q["logGroupName"] == body["logGroupName"]]
    if body.get("status"):
        qs = [q for q in qs if q["status"] == body["status"]]
    return LogsResponse(body={"queries": qs})


_OPS = {
    "CreateLogGroup": _create_log_group, "DeleteLogGroup": _delete_log_group,
    "DescribeLogGroups": _describe_log_groups, "PutRetentionPolicy": _put_retention_policy,
    "DeleteRetentionPolicy": _delete_retention_policy,
    "AssociateKmsKey": _associate_kms_key, "DisassociateKmsKey": _disassociate_kms_key,
    "PutDataProtectionPolicy": _put_data_protection_policy, "GetDataProtectionPolicy": _get_data_protection_policy,
    "DeleteDataProtectionPolicy": _delete_data_protection_policy,
    "PutIndexPolicy": _put_index_policy, "GetIndexPolicy": _get_index_policy,
    "DeleteIndexPolicy": _delete_index_policy, "DescribeIndexPolicies": _describe_index_policies,
    "PutTransformer": _put_transformer, "GetTransformer": _get_transformer, "DeleteTransformer": _delete_transformer,
    "TagLogGroup": _tag_log_group, "UntagLogGroup": _untag_log_group,
    "ListTagsLogGroup": _list_tags_log_group, "TagResource": _tag_resource,
    "UntagResource": _untag_resource, "ListTagsForResource": _list_tags_for_resource,
    "CreateLogStream": _create_log_stream, "DeleteLogStream": _delete_log_stream,
    "DescribeLogStreams": _describe_log_streams, "PutLogEvents": _put_log_events,
    "GetLogEvents": _get_log_events, "FilterLogEvents": _filter_log_events,
    "PutMetricFilter": _put_metric_filter, "DescribeMetricFilters": _describe_metric_filters,
    "DeleteMetricFilter": _delete_metric_filter, "TestMetricFilter": _test_metric_filter,
    "PutSubscriptionFilter": _put_subscription_filter,
    "DescribeSubscriptionFilters": _describe_subscription_filters,
    "DeleteSubscriptionFilter": _delete_subscription_filter,
    "PutResourcePolicy": _put_resource_policy,
    "DescribeResourcePolicies": _describe_resource_policies,
    "DeleteResourcePolicy": _delete_resource_policy,
    "PutQueryDefinition": _put_query_definition,
    "DescribeQueryDefinitions": _describe_query_definitions,
    "DeleteQueryDefinition": _delete_query_definition,
    "StartQuery": _start_query, "GetQueryResults": _get_query_results,
    "StopQuery": _stop_query, "DescribeQueries": _describe_queries,
    "UpdateLogGroupDeletionProtection": _update_log_group_deletion_protection,
}
OPERATIONS = sorted(_OPS)


def dispatch(store: LogsStore, target: str, payload: dict | None = None) -> LogsResponse:
    """Native CloudWatch Logs JSON router. `target` is the X-Amz-Target header,
    e.g. "Logs_20140328.PutLogEvents"."""
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    op = _OPS.get(action)
    if op is None:
        return LogsResponse(status=400, body={"__type": "UnknownOperationException",
                                              "message": f"Unknown operation {action}."})
    try:
        return op(store, body)
    except _E as e:
        return LogsResponse(status=400, body={"__type": e.code, "message": e.message})


# ── console REST (shared by the offline appliance and Nano) ────────────────
# The console speaks friendly REST under /api/logs/...; both consoles route it
# here so the two can never drift. Pure: (store, method, subpath, query, body).
def _human_bytes(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _iso_ms(ms):
    return _iso(ms).replace(" ", "T") + "Z"


def _group_row(g):
    days = g.get("retentionInDays")
    return {"name": g["name"], "arn": g["arn"],
            "log_class": "Infrequent Access" if g.get("logGroupClass") == "INFREQUENT_ACCESS" else "Standard",
            "retention": f"{days} days" if days else "Never expire",
            "retention_in_days": days or 0,
            "stream_count": len(g["streams"]),
            "metric_filter_count": len(g["metricFilters"]),
            "subscription_filter_count": len(g["subscriptionFilters"]),
            "stored": _human_bytes(g["storedBytes"]),
            "kms_key": g.get("kmsKeyId") or "Not associated",
            "deletion_protection": bool(g.get("deletionProtectionEnabled", False)),
            "created": _iso_ms(g["creationTime"]),
            "tags": dict(g["tags"])}


def _cerr(status, msg):
    return status, {"detail": msg}


def console_dispatch(store: LogsStore, method: str, path: str, query: dict | None = None,
                     body: dict | None = None):
    """Console REST for CloudWatch Logs. Returns (status, json-able)."""
    from urllib.parse import unquote
    query, body = query or {}, body if isinstance(body, dict) else {}
    method = method.upper()
    p = unquote(path).strip("/")
    if p.startswith("api/logs"):
        p = p[len("api/logs"):].strip("/")

    try:
        if p == "log-groups":
            if method == "GET":
                rows = [_group_row(g) for g in sorted(store.log_groups.values(), key=lambda g: g["name"])]
                return 200, {"items": rows}
            if method == "POST":
                name = str(body.get("name") or body.get("logGroupName") or "").strip()
                cls = str(body.get("log_group_class") or "STANDARD")
                _create_log_group(store, {"logGroupName": name, "tags": body.get("tags") or {},
                                          "logGroupClass": {"Standard": "STANDARD", "Infrequent Access": "INFREQUENT_ACCESS"}.get(cls, cls),
                                          "kmsKeyId": body.get("kms_key_id") or None,
                                          "deletionProtectionEnabled": bool(body.get("deletion_protection"))})
                days = body.get("retention_in_days")
                if days not in (None, "", 0, "0", "never"):
                    _put_retention_policy(store, {"logGroupName": name, "retentionInDays": int(days)})
                return 201, _group_row(store.log_groups[name])
            return _cerr(405, "method not allowed")
        m = re.match(r"^log-groups/(.+?)(?:/(streams|events|metric-filters|subscription-filters))?$", p)
        if not m:
            return _cerr(404, "not found")
        name, sub = m.group(1), m.group(2)
        g = _group(store, name)
        if sub is None:
            if method == "GET":
                return 200, _group_row(g)
            if method == "DELETE":
                _delete_log_group(store, {"logGroupName": name})
                return 200, {"deleted": name}
            if method in ("PUT", "PATCH"):
                if "tags" in body:
                    g["tags"] = {str(k): str(v) for k, v in (body["tags"] or {}).items()}
                days = body.get("retention_in_days", body.get("value"))
                if days is not None:
                    if str(days) in ("", "0", "never"):
                        g.pop("retentionInDays", None)
                    else:
                        _put_retention_policy(store, {"logGroupName": name, "retentionInDays": int(days)})
                if "deletion_protection" in body:
                    _update_log_group_deletion_protection(store, {"logGroupName": name, "deletionProtectionEnabled": bool(body["deletion_protection"])})
                store.persist()
                return 200, _group_row(g)
            return _cerr(405, "method not allowed")
        if sub == "streams":
            if method == "POST":
                sn = str(body.get("name") or body.get("logStreamName") or "")
                _create_log_stream(store, {"logGroupName": name, "logStreamName": sn})
                return 201, {"name": sn}
            rows = [{"name": s["name"], "created": _iso_ms(s["creationTime"]),
                     "first_event": _iso_ms(s["firstEventTimestamp"]) if s["events"] else "No events",
                     "last_event": _iso_ms(s["lastEventTimestamp"]) if s["events"] else "No events",
                     "event_count": len(s["events"]), "stored": _human_bytes(s["storedBytes"])}
                    for s in sorted(g["streams"].values(), key=lambda s: s["name"])]
            return 200, {"items": rows}
        if sub == "events":
            if method == "POST":
                sn = str(body.get("stream") or "")
                if sn not in g["streams"]:
                    _create_log_stream(store, {"logGroupName": name, "logStreamName": sn})
                _put_log_events(store, {"logGroupName": name, "logStreamName": sn,
                                        "logEvents": [{"timestamp": store.now_ms(), "message": str(body.get("message", ""))}]})
                return 201, {"stream": sn}
            r = _filter_log_events(store, {"logGroupName": name, "filterPattern": query.get("filter", ""),
                                           "logStreamNames": [query["stream"]] if query.get("stream") else None,
                                           "limit": int(query.get("limit") or 100)})
            evs = sorted(r.body["events"], key=lambda e: e["timestamp"], reverse=True)
            return 200, {"items": [{"timestamp": _iso_ms(e["timestamp"]), "stream": e["logStreamName"],
                                    "message": e["message"]} for e in evs]}
        if sub == "metric-filters":
            return 200, {"items": [{"name": f["filterName"], "pattern": f.get("filterPattern") or "(match all)",
                                    "metric": ", ".join(f"{t['metricNamespace']}/{t['metricName']}" for t in f["metricTransformations"]),
                                    "created": _iso_ms(f["creationTime"])} for f in g["metricFilters"].values()]}
        return 200, {"items": [{"name": f["filterName"], "pattern": f.get("filterPattern") or "(match all)",
                                "destination": f["destinationArn"], "created": _iso_ms(f["creationTime"])}
                               for f in g["subscriptionFilters"].values()]}
    except _E as e:
        code = 404 if e.code == "ResourceNotFoundException" else 409 if e.code == "ResourceAlreadyExistsException" else 400
        return _cerr(code, f"{e.code}: {e.message}")
