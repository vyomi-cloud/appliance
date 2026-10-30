"""Amazon SNS core — substrate-independent pub/sub on the NATIVE AWS SNS wire: the
**Query protocol** (form-encoded `Action=Publish&...`, XML responses,
http://sns.amazonaws.com/doc/2010-03-31/), so an unmodified AWS SDK / `aws sns`
client works with only the endpoint changed. NO fastapi / boto3 / socket imports →
loads under Pyodide (Nano) and on the appliance alike. State persists through the
MessagingStore seam (core/messaging_store.py): topics live in `store.topics`
(subscriptions nested in the topic), everything else SNS owns (platform
applications + endpoints, SMS settings + sandbox, the delivery log) in `store.sns`.

Operations (the botocore `sns` model): topics (Create/Delete/List/Get+SetAttributes,
tags, AddPermission/RemovePermission, data-protection policy), subscriptions
(Subscribe/ConfirmSubscription/Unsubscribe/List*/Get+SetSubscriptionAttributes with
filter policies on attributes or body, raw delivery, FIFO), Publish/PublishBatch with
**real fan-out** (SQS subscriptions receive the SNS notification envelope as a real,
receivable SQS message via core/sqs_core.enqueue; every other protocol is recorded in
the delivery log, which is what a developer inspects offline), mobile push platform
applications + endpoints, and SMS attributes / opt-out / sandbox.

Also here: `console_dispatch` — the flat-JSON REST the web console uses
(`/api/aws/sns/...`), shared by the appliance server and Nano.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import unquote
from xml.sax.saxutils import escape as _xml_escape

from core.messaging_store import MessagingStore, REGION
from core import sqs_core

SNS_NS = "http://sns.amazonaws.com/doc/2010-03-31/"
MAX_MESSAGE_BYTES = 262144
PAGE = 100
DELIVERY_LOG_MAX = 500
PROTOCOLS = ("http", "https", "email", "email-json", "sms", "sqs", "application", "lambda", "firehose")
PLATFORMS = ("ADM", "APNS", "APNS_SANDBOX", "APNS_VOIP", "APNS_VOIP_SANDBOX", "BAIDU", "GCM",
             "MACOS", "MACOS_SANDBOX", "MPNS", "WNS")
TOPIC_SETTABLE = {"DeliveryPolicy", "DisplayName", "Policy", "TracingConfig", "KmsMasterKeyId",
                  "SignatureVersion", "ContentBasedDeduplication", "ArchivePolicy",
                  "FifoThroughputScope", "BeginningArchiveTime"}
TOPIC_SETTABLE_PREFIXES = ("HTTP", "Lambda", "SQS", "Application", "Firehose")
SUB_SETTABLE = {"DeliveryPolicy", "FilterPolicy", "FilterPolicyScope", "RawMessageDelivery",
                "RedrivePolicy", "SubscriptionRoleArn", "ReplayPolicy"}
SMS_ATTRS = {"MonthlySpendLimit", "DeliveryStatusIAMRole", "DeliveryStatusSuccessSamplingRate",
             "DefaultSenderID", "DefaultSMSType", "UsageReportS3Bucket"}


@dataclass
class SnsResponse:
    status: int = 200
    body: str = ""          # XML text
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class SnsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _req_id() -> str:
    return str(uuid.uuid4())


def _topic_arn(store, name: str) -> str:
    return f"arn:aws:sns:{REGION}:{store.account_id}:{name}"


def _state(store) -> dict:
    """SNS-owned state that is not a topic (persisted with the messaging store)."""
    s = getattr(store, "sns", None)
    if not isinstance(s, dict):
        s = {}
        store.sns = s
    for k, default in (("platform_apps", {}), ("endpoints", {}), ("sms_attributes", {}),
                       ("sandbox", {}), ("opted_out", []), ("deliveries", []), ("dedup", {}),
                       ("sequence", 0)):
        if k not in s:
            s[k] = default.copy() if isinstance(default, (dict, list)) else default
    return s


# ── response builders (native SNS Query-protocol XML) ──────────────────────
def _envelope(action: str, result_inner: str = "", always_result: bool = False) -> SnsResponse:
    result = (f"<{action}Result>{result_inner}</{action}Result>"
              if (result_inner or always_result) else "")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<{action}Response xmlns="{SNS_NS}">{result}'
           f'<ResponseMetadata><RequestId>{_req_id()}</RequestId></ResponseMetadata>'
           f'</{action}Response>')
    return SnsResponse(body=xml)


def _error(code: str, message: str, status: int = 400) -> SnsResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<ErrorResponse xmlns="{SNS_NS}">'
           f'<Error><Type>Sender</Type><Code>{_xml_escape(code)}</Code>'
           f'<Message>{_xml_escape(message)}</Message></Error>'
           f'<RequestId>{_req_id()}</RequestId></ErrorResponse>')
    return SnsResponse(status=status, body=xml)


def _el(tag, value):
    return f"<{tag}>{_xml_escape(str(value))}</{tag}>"


def _entry_map(attrs: dict, wrapper: str = "Attributes") -> str:
    entries = "".join("<entry>" + _el("key", k) + _el("value", v) + "</entry>"
                      for k, v in attrs.items())
    return f"<{wrapper}>{entries}</{wrapper}>"


def _invalid(msg: str) -> SnsError:
    return SnsError("InvalidParameter", msg, 400)


def _p(params: dict, key: str) -> str:
    return str(params.get(key, "") or "").strip()


# ── Query-wire parameter helpers (flattened lists / maps) ──────────────────
def _members(params: dict, prefix: str) -> list[str]:
    """`Prefix.member.N` → ordered values."""
    out = []
    for k, v in params.items():
        m = re.match(rf"^{re.escape(prefix)}\.member\.(\d+)$", str(k))
        if m:
            out.append((int(m.group(1)), str(v)))
    return [v for _, v in sorted(out)]


def _entries(params: dict, prefix: str) -> dict:
    """`Prefix.entry.N.key/.value` → {key: value}."""
    ks, vs = {}, {}
    for k, v in params.items():
        m = re.match(rf"^{re.escape(prefix)}\.entry\.(\d+)\.(key|value)$", str(k))
        if m:
            (ks if m.group(2) == "key" else vs)[m.group(1)] = str(v)
    return {ks[i]: vs.get(i, "") for i in sorted(ks, key=int)}


def _tags(params: dict, prefix: str = "Tags") -> dict:
    ks, vs = {}, {}
    for k, v in params.items():
        m = re.match(rf"^{re.escape(prefix)}\.member\.(\d+)\.(Key|Value)$", str(k))
        if m:
            (ks if m.group(2) == "Key" else vs)[m.group(1)] = str(v)
    return {ks[i]: vs.get(i, "") for i in sorted(ks, key=int)}


def _message_attributes_from_params(params: dict, prefix: str = "MessageAttributes") -> dict:
    """Reconstruct the SNS MessageAttributes map from the flattened Query wire
    (`MessageAttributes.entry.N.Name` / `.Value.DataType` / `.Value.StringValue|BinaryValue`).
    Returns {name: {"DataType": ..., "Value": ...}}."""
    attrs: dict = {}
    for key, val in params.items():
        m = re.match(rf"^{re.escape(prefix)}\.entry\.(\d+)\.Name$", str(key))
        if not m:
            continue
        idx = m.group(1)
        dtype = params.get(f"{prefix}.entry.{idx}.Value.DataType")
        if not dtype:
            raise _invalid("Invalid parameter: Message attribute DataType is required")
        sval = params.get(f"{prefix}.entry.{idx}.Value.StringValue")
        bval = params.get(f"{prefix}.entry.{idx}.Value.BinaryValue")
        if sval is None and bval is None:
            raise _invalid(f"Invalid parameter: Value of message attribute {val} must have a value")
        attrs[str(val)] = {"DataType": dtype, "Value": sval if sval is not None else bval}
    return attrs


def _page(items: list, token: str) -> tuple[list, str]:
    try:
        start = int(token) if token else 0
    except ValueError:
        raise _invalid("Invalid parameter: NextToken")
    chunk = items[start:start + PAGE]
    return chunk, (str(start + PAGE) if start + PAGE < len(items) else "")


def _next(token: str) -> str:
    return _el("NextToken", token) if token else ""


def _log_delivery(store, **rec) -> dict:
    s = _state(store)
    rec.setdefault("id", uuid.uuid4().hex)
    rec.setdefault("timestamp", _now_iso())
    s["deliveries"].append(rec)
    del s["deliveries"][:-DELIVERY_LOG_MAX]
    return rec


# ── topics ──────────────────────────────────────────────────────────────────
_DEFAULT_DELIVERY_POLICY = {"http": {"defaultHealthyRetryPolicy": {
    "minDelayTarget": 20, "maxDelayTarget": 20, "numRetries": 3, "numMaxDelayRetries": 0,
    "numNoDelayRetries": 0, "numMinDelayRetries": 0, "backoffFunction": "linear"},
    "disableSubscriptionOverrides": False, "defaultRequestPolicy": {"headerContentType": "text/plain; charset=UTF-8"}}}


def _default_policy(store, arn: str) -> str:
    return json.dumps({
        "Version": "2008-10-17", "Id": "__default_policy_ID",
        "Statement": [{
            "Sid": "__default_statement_ID", "Effect": "Allow", "Principal": {"AWS": "*"},
            "Action": ["SNS:GetTopicAttributes", "SNS:SetTopicAttributes", "SNS:AddPermission",
                       "SNS:RemovePermission", "SNS:DeleteTopic", "SNS:Subscribe",
                       "SNS:ListSubscriptionsByTopic", "SNS:Publish"],
            "Resource": arn,
            "Condition": {"StringEquals": {"AWS:SourceOwner": store.account_id}}}]})


def _validate_topic_name(name: str, fifo: bool) -> None:
    base = name[:-5] if name.endswith(".fifo") else name
    if not name or len(name) > 256 or not re.match(r"^[A-Za-z0-9_-]+$", base):
        raise _invalid("Invalid parameter: Topic Name")
    if fifo and not name.endswith(".fifo"):
        raise _invalid("Invalid parameter: Topic Name Reason: Fifo Topic names must end with .fifo")
    if name.endswith(".fifo") and not fifo:
        raise _invalid("Invalid parameter: Topic Name Reason: .fifo suffix is only valid for FIFO topics")


def _is_fifo(topic: dict) -> bool:
    return str(topic.get("attributes", {}).get("FifoTopic", "")).lower() == "true"


def _topic_attributes(store, topic: dict) -> dict:
    arn = topic["topic_arn"]
    subs = topic["subscriptions"].values()
    confirmed = sum(1 for s in subs if not s.get("pending"))
    attrs = {
        "TopicArn": arn, "Owner": store.account_id,
        "Policy": _default_policy(store, arn), "DisplayName": "",
        "SubscriptionsConfirmed": str(confirmed),
        "SubscriptionsPending": str(sum(1 for s in subs if s.get("pending"))),
        "SubscriptionsDeleted": str(topic.get("deleted_subscriptions", 0)),
        "EffectiveDeliveryPolicy": json.dumps(_DEFAULT_DELIVERY_POLICY),
        "SignatureVersion": "1",
    }
    attrs.update(topic.get("attributes", {}))
    if _is_fifo(topic):
        attrs.setdefault("ContentBasedDeduplication", "false")
    return attrs


def _require_topic(store, arn):
    t = store.get_topic(arn) if arn else None
    if not t:
        raise SnsError("NotFound", "Topic does not exist", 404)
    return t


def _create_topic(store, params):
    name = _p(params, "Name")
    attrs = _entries(params, "Attributes")
    tags = _tags(params)
    for k in attrs:
        if k not in TOPIC_SETTABLE and k not in ("FifoTopic",) and not k.startswith(TOPIC_SETTABLE_PREFIXES):
            raise _invalid(f"Invalid parameter: Attributes Reason: Invalid attribute name {k}")
    fifo = str(attrs.get("FifoTopic", "")).lower() == "true"
    _validate_topic_name(name, fifo)
    if "Policy" in attrs:
        _json_attr("Policy", attrs["Policy"])
    arn = _topic_arn(store, name)
    existing = store.get_topic(arn)
    if existing:
        for k, v in attrs.items():
            if str(existing.get("attributes", {}).get(k, "")) != v:
                raise _invalid("Invalid parameter: Attributes Reason: Topic already exists with different attributes")
    else:
        if len(store.topics) >= 100000:
            raise SnsError("TopicLimitExceeded", "Topic limit exceeded", 403)
        topic = {"topic_arn": arn, "name": name, "subscriptions": {},
                 "created": _now_iso(), "attributes": dict(attrs), "tags": tags,
                 "deleted_subscriptions": 0}
        if fifo:
            topic["attributes"]["FifoTopic"] = "true"
        store.put_topic(arn, topic)
        store.persist()
    return _envelope("CreateTopic", _el("TopicArn", arn))


def _list_topics(store, params):
    arns, nxt = _page(store.topic_arns(), _p(params, "NextToken"))
    members = "".join("<member>" + _el("TopicArn", a) + "</member>" for a in arns)
    return _envelope("ListTopics", f"<Topics>{members}</Topics>{_next(nxt)}")


def _delete_topic(store, params):
    arn = _p(params, "TopicArn")
    if store.get_topic(arn):
        store.drop_topic(arn)
        store.persist()
    elif not arn:
        raise _invalid("Invalid parameter: TopicArn")
    return _envelope("DeleteTopic")


def _get_topic_attributes(store, params):
    topic = _require_topic(store, _p(params, "TopicArn"))
    return _envelope("GetTopicAttributes", _entry_map(_topic_attributes(store, topic)))


def _json_attr(name: str, raw: str):
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        raise _invalid(f"Invalid parameter: AttributeValue Reason: {name} must be valid JSON")


def _set_topic_attributes(store, params):
    topic = _require_topic(store, _p(params, "TopicArn"))
    name = _p(params, "AttributeName")
    if not name:
        raise _invalid("Invalid parameter: AttributeName")
    if name not in TOPIC_SETTABLE and not name.startswith(TOPIC_SETTABLE_PREFIXES):
        raise _invalid("Invalid parameter: AttributeName")
    raw = params.get("AttributeValue")
    raw = "" if raw is None else str(raw)
    if name in ("Policy", "DeliveryPolicy", "ArchivePolicy") and raw:
        _json_attr(name, raw)
    if name == "TracingConfig" and raw not in ("", "Active", "PassThrough"):
        raise _invalid("Invalid parameter: TracingConfig")
    if name == "SignatureVersion" and raw not in ("1", "2"):
        raise _invalid("Invalid parameter: SignatureVersion")
    if name == "ContentBasedDeduplication" and not _is_fifo(topic):
        raise _invalid("Invalid parameter: AttributeName Reason: ContentBasedDeduplication is only valid for FIFO topics")
    topic["attributes"][name] = raw
    store.persist()
    return _envelope("SetTopicAttributes")


def _policy_doc(store, topic: dict) -> dict:
    raw = topic.get("attributes", {}).get("Policy") or _default_policy(store, topic["topic_arn"])
    return json.loads(raw)


def _add_permission(store, params):
    topic = _require_topic(store, _p(params, "TopicArn"))
    label = _p(params, "Label")
    accounts = _members(params, "AWSAccountId")
    actions = _members(params, "ActionName")
    if not label:
        raise _invalid("Invalid parameter: Label")
    if not accounts or not actions:
        raise _invalid("Invalid parameter: AWSAccountId and ActionName are required")
    doc = _policy_doc(store, topic)
    if any(s.get("Sid") == label for s in doc["Statement"]):
        raise _invalid("Invalid parameter: Statement already exists")
    doc["Statement"].append({
        "Sid": label, "Effect": "Allow",
        "Principal": {"AWS": [f"arn:aws:iam::{a}:root" for a in accounts]},
        "Action": [f"SNS:{a}" for a in actions], "Resource": topic["topic_arn"]})
    topic["attributes"]["Policy"] = json.dumps(doc)
    store.persist()
    return _envelope("AddPermission")


def _remove_permission(store, params):
    topic = _require_topic(store, _p(params, "TopicArn"))
    label = _p(params, "Label")
    doc = _policy_doc(store, topic)
    kept = [s for s in doc["Statement"] if s.get("Sid") != label]
    if len(kept) == len(doc["Statement"]):
        raise _invalid("Invalid parameter: Statement does not exist")
    doc["Statement"] = kept
    topic["attributes"]["Policy"] = json.dumps(doc)
    store.persist()
    return _envelope("RemovePermission")


# ── tags + data protection (topics) ─────────────────────────────────────────
def _tagged(store, arn: str):
    t = store.get_topic(arn)
    if not t:
        raise SnsError("ResourceNotFound", "Resource does not exist", 404)
    return t


def _tag_resource(store, params):
    t = _tagged(store, _p(params, "ResourceArn"))
    new = _tags(params)
    if not new:
        raise _invalid("Invalid parameter: Tags")
    merged = {**t.setdefault("tags", {}), **new}
    if len(merged) > 50:
        raise SnsError("TagLimitExceeded", "Could not complete request: tag quota of per resource exceeded", 400)
    t["tags"] = merged
    store.persist()
    return _envelope("TagResource", always_result=True)


def _untag_resource(store, params):
    t = _tagged(store, _p(params, "ResourceArn"))
    for k in _members(params, "TagKeys"):
        t.setdefault("tags", {}).pop(k, None)
    store.persist()
    return _envelope("UntagResource", always_result=True)


def _list_tags_for_resource(store, params):
    t = _tagged(store, _p(params, "ResourceArn"))
    members = "".join("<member>" + _el("Key", k) + _el("Value", v) + "</member>"
                      for k, v in t.get("tags", {}).items())
    return _envelope("ListTagsForResource", f"<Tags>{members}</Tags>")


def _put_data_protection_policy(store, params):
    t = _require_topic(store, _p(params, "ResourceArn"))
    raw = _p(params, "DataProtectionPolicy")
    doc = _json_attr("DataProtectionPolicy", raw)
    if not isinstance(doc, dict) or "Statement" not in doc:
        raise _invalid("Invalid parameter: DataProtectionPolicy Reason: Statement is required")
    t["data_protection_policy"] = raw
    store.persist()
    return _envelope("PutDataProtectionPolicy")


def _get_data_protection_policy(store, params):
    t = _require_topic(store, _p(params, "ResourceArn"))
    return _envelope("GetDataProtectionPolicy", _el("DataProtectionPolicy", t.get("data_protection_policy", "")))


# ── subscriptions ───────────────────────────────────────────────────────────
def _validate_endpoint(protocol: str, endpoint: str) -> None:
    if protocol not in PROTOCOLS:
        raise _invalid("Invalid parameter: Protocol")
    ok = {
        "http": endpoint.startswith("http://"), "https": endpoint.startswith("https://"),
        "email": "@" in endpoint, "email-json": "@" in endpoint,
        "sms": bool(re.match(r"^\+?[0-9]{7,15}$", endpoint)),
        "sqs": endpoint.startswith("arn:aws:sqs:"), "lambda": endpoint.startswith("arn:aws:lambda:"),
        "application": endpoint.startswith("arn:aws:sns:"),
        "firehose": endpoint.startswith("arn:aws:firehose:"),
    }[protocol]
    if not ok:
        raise _invalid(f"Invalid parameter: Endpoint Reason: Invalid endpoint for protocol {protocol}")


def _find_sub(store, sub_arn: str):
    for topic in store.topics.values():
        sub = topic["subscriptions"].get(sub_arn)
        if sub is not None:
            return topic, sub
    return None, None


def _sub_attributes(store, topic: dict, sub: dict) -> dict:
    attrs = {"SubscriptionArn": sub["subscription_arn"] if not sub.get("pending") else sub["subscription_arn"],
             "TopicArn": topic["topic_arn"], "Protocol": sub["protocol"],
             "Endpoint": sub["endpoint"], "Owner": store.account_id,
             "ConfirmationWasAuthenticated": "true",
             "PendingConfirmation": "true" if sub.get("pending") else "false",
             "RawMessageDelivery": "false", "FilterPolicyScope": "MessageAttributes"}
    if sub.get("filter_policy"):
        attrs["FilterPolicy"] = json.dumps(sub["filter_policy"])
    attrs.update(sub.get("attributes", {}))
    return attrs


def _apply_sub_attribute(sub: dict, name: str, raw) -> None:
    if name not in SUB_SETTABLE:
        raise _invalid("Invalid parameter: AttributeName")
    raw = "" if raw is None else str(raw)
    if name == "FilterPolicy":
        try:
            sub["filter_policy"] = json.loads(raw) if raw else {}
        except Exception:
            raise _invalid("Invalid parameter: FilterPolicy: failed to parse JSON.")
        if not isinstance(sub["filter_policy"], dict):
            raise _invalid("Invalid parameter: FilterPolicy: policy must be a JSON object")
    elif name == "FilterPolicyScope":
        if raw not in ("MessageAttributes", "MessageBody"):
            raise _invalid("Invalid parameter: FilterPolicyScope")
        sub.setdefault("attributes", {})[name] = raw
    elif name == "RawMessageDelivery":
        if raw.lower() not in ("true", "false"):
            raise _invalid("Invalid parameter: RawMessageDelivery")
        sub.setdefault("attributes", {})[name] = raw.lower()
    else:
        if name in ("DeliveryPolicy", "RedrivePolicy", "ReplayPolicy") and raw:
            _json_attr(name, raw)
        sub.setdefault("attributes", {})[name] = raw


def _subscribe(store, params):
    arn = _p(params, "TopicArn")
    topic = _require_topic(store, arn)
    protocol = _p(params, "Protocol").lower()
    endpoint = _p(params, "Endpoint")
    if not protocol:
        raise _invalid("Invalid parameter: Protocol")
    if protocol != "sms" and not endpoint:
        raise _invalid("Invalid parameter: Endpoint")
    _validate_endpoint(protocol, endpoint)
    attrs = _entries(params, "Attributes")
    for sub in topic["subscriptions"].values():
        if sub["protocol"] == protocol and sub["endpoint"] == endpoint:
            return _subscribe_result(sub, params)
    if _is_fifo(topic) and protocol in ("email", "email-json", "sms"):
        raise _invalid(f"Invalid parameter: Protocol Reason: FIFO SNS topics can't have {protocol} subscriptions")
    needs_confirmation = protocol in ("http", "https", "email", "email-json")
    sub_arn = f"{arn}:{uuid.uuid4()}"
    sub = {"subscription_arn": sub_arn, "protocol": protocol, "endpoint": endpoint,
           "created": _now_iso(), "pending": needs_confirmation}
    for k, v in attrs.items():
        _apply_sub_attribute(sub, k, v)
    if needs_confirmation:
        sub["token"] = hashlib.sha256(sub_arn.encode()).hexdigest()[:64]
    topic["subscriptions"][sub_arn] = sub
    if needs_confirmation:
        _log_delivery(store, kind="SubscriptionConfirmation", topic_arn=arn, protocol=protocol,
                      endpoint=endpoint, subscription_arn=sub_arn, subject="",
                      message=f"You have chosen to subscribe to the topic {arn}. "
                              f"To confirm the subscription, use token {sub['token']}",
                      token=sub["token"])
        if protocol in ("http", "https"):
            _enqueue_delivery(
                store, topic, sub, kind="SubscriptionConfirmation", token=sub["token"], subject="",
                message=f"You have chosen to subscribe to the topic {arn}.\nTo confirm the subscription, "
                        f"visit the SubscribeURL included in this message.",
                message_id=str(uuid.uuid4()), raw=False, group="", attributes={})
    store.persist()
    return _subscribe_result(sub, params)


def _subscribe_result(sub: dict, params: dict) -> SnsResponse:
    if sub.get("pending") and _p(params, "ReturnSubscriptionArn").lower() != "true":
        return _envelope("Subscribe", _el("SubscriptionArn", "pending confirmation"))
    return _envelope("Subscribe", _el("SubscriptionArn", sub["subscription_arn"]))


def _confirm_subscription(store, params):
    topic = _require_topic(store, _p(params, "TopicArn"))
    token = _p(params, "Token")
    if not token:
        raise _invalid("Invalid parameter: Token")
    for sub in topic["subscriptions"].values():
        if sub.get("token") == token:
            sub["pending"] = False
            sub.pop("token", None)
            store.persist()
            return _envelope("ConfirmSubscription", _el("SubscriptionArn", sub["subscription_arn"]))
    raise _invalid("Invalid parameter: Token Reason: Invalid token")


def _unsubscribe(store, params):
    sub_arn = _p(params, "SubscriptionArn")
    topic, sub = _find_sub(store, sub_arn)
    if sub is None:
        if sub_arn == "pending confirmation" or not sub_arn.startswith("arn:"):
            raise _invalid("Invalid parameter: SubscriptionArn Reason: An ARN must have at least 6 elements, not 1")
        raise SnsError("NotFound", "Subscription does not exist", 404)
    del topic["subscriptions"][sub_arn]
    topic["deleted_subscriptions"] = topic.get("deleted_subscriptions", 0) + 1
    store.persist()
    return _envelope("Unsubscribe")


def _sub_member(store, topic: dict, sub: dict) -> str:
    arn = "PendingConfirmation" if sub.get("pending") else sub["subscription_arn"]
    return ("<member>" + _el("SubscriptionArn", arn) + _el("Owner", store.account_id)
            + _el("Protocol", sub["protocol"]) + _el("Endpoint", sub["endpoint"])
            + _el("TopicArn", topic["topic_arn"]) + "</member>")


def _list_subscriptions(store, params):
    allsubs = [(t, s) for a in store.topic_arns() for t in [store.topics[a]]
               for s in t["subscriptions"].values()]
    chunk, nxt = _page(allsubs, _p(params, "NextToken"))
    members = "".join(_sub_member(store, t, s) for t, s in chunk)
    return _envelope("ListSubscriptions", f"<Subscriptions>{members}</Subscriptions>{_next(nxt)}")


def _list_subscriptions_by_topic(store, params):
    topic = _require_topic(store, _p(params, "TopicArn"))
    chunk, nxt = _page(list(topic["subscriptions"].values()), _p(params, "NextToken"))
    members = "".join(_sub_member(store, topic, s) for s in chunk)
    return _envelope("ListSubscriptionsByTopic", f"<Subscriptions>{members}</Subscriptions>{_next(nxt)}")


def _set_subscription_attributes(store, params):
    topic, sub = _find_sub(store, _p(params, "SubscriptionArn"))
    if sub is None:
        raise SnsError("NotFound", "Subscription does not exist", 404)
    name = _p(params, "AttributeName")
    if not name:
        raise _invalid("Invalid parameter: AttributeName")
    _apply_sub_attribute(sub, name, params.get("AttributeValue"))
    store.persist()
    return _envelope("SetSubscriptionAttributes")


def _get_subscription_attributes(store, params):
    topic, sub = _find_sub(store, _p(params, "SubscriptionArn"))
    if sub is None:
        raise SnsError("NotFound", "Subscription does not exist", 404)
    return _envelope("GetSubscriptionAttributes", _entry_map(_sub_attributes(store, topic, sub)))


# ── filter policies ─────────────────────────────────────────────────────────
def _match_condition(cond, value) -> bool:
    """Evaluate one SNS filter-policy condition against an attribute value."""
    if isinstance(cond, str):
        return value == cond
    if isinstance(cond, (int, float)):
        try:
            return float(value) == float(cond)
        except (TypeError, ValueError):
            return False
    if isinstance(cond, dict):
        if "prefix" in cond:
            return isinstance(value, str) and value.startswith(str(cond["prefix"]))
        if "anything-but" in cond:
            ab = cond["anything-but"]
            ab = ab if isinstance(ab, list) else [ab]
            return value not in [str(x) for x in ab]
        if "exists" in cond:
            return (value is not None) == bool(cond["exists"])
        if "numeric" in cond:
            spec = cond["numeric"]
            try:
                v = float(value)
            except (TypeError, ValueError):
                return False
            i = 0
            ok = True
            while i < len(spec) - 1:
                op, n = spec[i], float(spec[i + 1])
                ok = ok and ((op == "=" and v == n) or (op == ">" and v > n) or
                             (op == "<" and v < n) or (op == ">=" and v >= n) or
                             (op == "<=" and v <= n))
                i += 2
            return ok
    return False


def _passes_filter_policy(policy: dict, msg_attrs: dict) -> bool:
    """SNS filter-policy semantics: every key in the policy must match (AND); a
    key matches if the attribute's value satisfies ANY listed condition (OR)."""
    if not policy:
        return True
    for key, conds in policy.items():
        attr = msg_attrs.get(key)
        value = attr.get("Value") if isinstance(attr, dict) else None
        conds = conds if isinstance(conds, list) else [conds]
        if not any(_match_condition(c, value) for c in conds):
            return False
    return True


def _values_of(value) -> list:
    return value if isinstance(value, list) else [value]


def _passes_body_policy(policy: dict, body) -> bool:
    """FilterPolicyScope=MessageBody: the policy is matched against the JSON body;
    nested objects in the policy match nested objects in the message."""
    if not policy:
        return True
    if not isinstance(body, dict):
        return False
    for key, conds in policy.items():
        value = body.get(key)
        if isinstance(conds, dict):
            if not any(_passes_body_policy(conds, v) for v in _values_of(value)):
                return False
            continue
        conds = conds if isinstance(conds, list) else [conds]
        if not any(_match_condition(c, v) for c in conds for v in _values_of(value)):
            return False
    return True


# ── publish ─────────────────────────────────────────────────────────────────
def _check_message(msg: dict, fifo: bool, require_default: bool = True) -> None:
    message = msg["Message"]
    if message is None or message == "":
        raise _invalid("Invalid parameter: Empty message")
    size = len(message.encode("utf-8")) + sum(
        len(k.encode()) + len(str(v.get("DataType", "")).encode()) + len(str(v.get("Value") or "").encode())
        for k, v in msg["attrs"].items())
    if size > MAX_MESSAGE_BYTES:
        raise _invalid("Invalid parameter: Message too long")
    subject = msg.get("Subject")
    if subject is not None and subject != "":
        if len(subject) > 100:
            raise _invalid("Invalid parameter: Subject Reason: Subject must be less than 100 characters")
        if not subject.isprintable() or subject.startswith((" ", "\t")):
            raise _invalid("Invalid parameter: Subject Reason: Subject must be ASCII text that begins with a letter, number, or punctuation mark")
    if msg.get("MessageStructure") == "json":
        doc = _json_attr("Message", message)
        if not isinstance(doc, dict) or (require_default and "default" not in doc) or not doc:
            raise _invalid("Invalid parameter: Message Structure - No default entry in JSON message body")
    elif msg.get("MessageStructure"):
        raise _invalid("Invalid parameter: MessageStructure")
    if fifo and not msg.get("group"):
        raise _invalid("Invalid parameter: The MessageGroupId parameter is required for FIFO topics")
    if not fifo and (msg.get("group") or msg.get("dedup")):
        raise _invalid("Invalid parameter: MessageGroupId and MessageDeduplicationId are only valid for FIFO topics")


def _message_for_protocol(msg: dict, protocol: str, platform: str = "") -> str:
    if msg.get("MessageStructure") == "json":
        doc = json.loads(msg["Message"])
        if platform and platform in doc:
            return str(doc[platform])
        if "default" not in doc:
            raise _invalid("Invalid parameter: Message Structure - No default entry in JSON message body")
        key = {"sqs": "sqs", "lambda": "lambda", "http": "http", "https": "https", "email": "email",
               "email-json": "email-json", "sms": "sms", "application": "default",
               "firehose": "firehose"}.get(protocol, "default")
        return str(doc.get(key, doc["default"]))
    return msg["Message"]


def _deliver_sqs(store, endpoint: str, body: str, attrs: dict | None, group, dedup) -> bool:
    hook = getattr(store, "deliver_sqs", None)
    if hook is not None:
        return bool(hook(endpoint, body, attrs, group, dedup))
    queue = store.get_queue_by_arn(endpoint)
    if queue is None:
        return False
    sqs_core.enqueue(store, queue, body, attrs or None, message_group_id=group, message_dedup_id=dedup)
    return True


DEDUP_WINDOW_SECONDS = 300      # FIFO topics drop a repeat MessageDeduplicationId for 5 minutes
_PUSH_PROTOCOLS = ("http", "https", "lambda", "email", "email-json")


def _retry_policy(topic: dict, sub: dict) -> dict:
    """Effective retry policy for a subscription: the subscription's DeliveryPolicy
    (healthyRetryPolicy) wins, then the topic's (http.defaultHealthyRetryPolicy), then
    SNS's defaults (3 retries, 20 s)."""
    out = dict(_DEFAULT_DELIVERY_POLICY["http"]["defaultHealthyRetryPolicy"])
    for raw, path in ((topic.get("attributes", {}).get("DeliveryPolicy"), ("http", "defaultHealthyRetryPolicy")),
                      (sub.get("attributes", {}).get("DeliveryPolicy"), ("healthyRetryPolicy",))):
        try:
            doc = json.loads(raw) if raw else {}
            for k in path:
                doc = doc.get(k, {})
            if isinstance(doc, dict):
                out.update({k: v for k, v in doc.items() if v is not None})
        except Exception:
            pass
    return out


def _redrive_target(sub: dict) -> str:
    try:
        return str(json.loads(sub.get("attributes", {}).get("RedrivePolicy") or "{}").get("deadLetterTargetArn", ""))
    except Exception:
        return ""


def _enqueue_delivery(store, topic: dict, sub: dict, **job) -> bool:
    """Hand a push delivery (HTTP/S, Lambda, email) to the store's delivery workers, when it
    has them (the offline appliance: durable NATS JetStream consumers). Without workers
    (Nano) the delivery is only recorded in the delivery log, as before."""
    hook = getattr(store, "enqueue_delivery", None)
    if hook is None:
        return False
    job.update(id=str(uuid.uuid4()), topic_arn=topic["topic_arn"], subscription_arn=sub["subscription_arn"],
               protocol=sub["protocol"], endpoint=sub["endpoint"], retry_policy=_retry_policy(topic, sub),
               signature_version=str(topic.get("attributes", {}).get("SignatureVersion") or "1"),
               redrive_arn=_redrive_target(sub), enqueued=_now_iso())
    try:
        return bool(hook(job))
    except Exception:
        return False


def _publish_to_topic(store, topic: dict, msg: dict) -> tuple[str, str]:
    fifo = _is_fifo(topic)
    _check_message(msg, fifo)
    arn = topic["topic_arn"]
    seq = ""
    dedup = msg.get("dedup")
    if fifo:
        if not dedup:
            if str(topic["attributes"].get("ContentBasedDeduplication", "")).lower() == "true":
                dedup = hashlib.sha256(msg["Message"].encode()).hexdigest()
            else:
                raise _invalid("Invalid parameter: The topic should either have ContentBasedDeduplication enabled or MessageDeduplicationId provided explicitly")
        now = time.time()
        window = _state(store)["dedup"]
        for k in [k for k, v in window.items() if now - v.get("ts", 0) > DEDUP_WINDOW_SECONDS]:
            del window[k]
        seen = window.get(f"{arn}|{dedup}")
        if seen:
            return seen["id"], seen["seq"]
        s = _state(store)
        s["sequence"] += 1
        seq = str(s["sequence"]).zfill(20)
    message_id = str(uuid.uuid4())
    if fifo:
        _state(store)["dedup"][f"{arn}|{dedup}"] = {"id": message_id, "seq": seq, "ts": time.time()}
    attrs = msg["attrs"]
    envelope = {"Type": "Notification", "MessageId": message_id, "TopicArn": arn,
                "Message": msg["Message"], "Timestamp": _now_iso(), "SignatureVersion": "1",
                "Signature": "vyomi-simulated-signature",
                "SigningCertURL": f"https://sns.{REGION}.amazonaws.com/SimpleNotificationService-vyomi.pem",
                "UnsubscribeURL": f"https://sns.{REGION}.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=%s"}
    if msg.get("Subject") not in (None, ""):
        envelope["Subject"] = msg["Subject"]
    if attrs:
        envelope["MessageAttributes"] = {k: {"Type": v.get("DataType", "String"), "Value": v.get("Value")}
                                         for k, v in attrs.items()}
    try:
        body_json = json.loads(msg["Message"])
    except Exception:
        body_json = None
    for sub in list(topic["subscriptions"].values()):
        if sub.get("pending"):
            continue
        scope = sub.get("attributes", {}).get("FilterPolicyScope", "MessageAttributes")
        policy = sub.get("filter_policy")
        if scope == "MessageBody":
            if not _passes_body_policy(policy, body_json):
                continue
        elif not _passes_filter_policy(policy, attrs):
            continue
        text = _message_for_protocol(msg, sub["protocol"])
        raw = sub.get("attributes", {}).get("RawMessageDelivery") == "true"
        if sub["protocol"] == "sqs":
            if raw:
                body, sattrs = text, attrs
            else:
                env = dict(envelope, Message=text,
                           UnsubscribeURL=envelope["UnsubscribeURL"] % sub["subscription_arn"])
                body, sattrs = json.dumps(env), None
            if _deliver_sqs(store, sub["endpoint"], body, sattrs, msg.get("group"), dedup):
                continue
            _log_delivery(store, kind="DeliveryFailure", topic_arn=arn, protocol="sqs",
                          endpoint=sub["endpoint"], subscription_arn=sub["subscription_arn"],
                          subject=msg.get("Subject") or "", message=text, message_id=message_id,
                          error="queue does not exist")
        else:
            queued = False
            if sub["protocol"] in _PUSH_PROTOCOLS:
                env = dict(envelope, Message=text,
                           UnsubscribeURL=envelope["UnsubscribeURL"] % sub["subscription_arn"])
                queued = _enqueue_delivery(
                    store, topic, sub, kind="Notification", subject=msg.get("Subject") or "", message=text,
                    message_id=message_id, raw=raw, envelope=env, group=msg.get("group") or "",
                    attributes=attrs or {})
            if not queued:
                _log_delivery(store, kind="Notification", topic_arn=arn, protocol=sub["protocol"],
                              endpoint=sub["endpoint"], subscription_arn=sub["subscription_arn"],
                              subject=msg.get("Subject") or "", message=text, message_id=message_id)
    return message_id, seq


def _publish_to_endpoint(store, endpoint_arn: str, msg: dict) -> str:
    ep = _state(store)["endpoints"].get(endpoint_arn)
    if ep is None:
        raise SnsError("NotFound", "Endpoint does not exist", 404)
    _check_message(msg, False, require_default=False)
    if str(ep["attributes"].get("Enabled", "true")).lower() != "true":
        raise SnsError("EndpointDisabled", "Endpoint is disabled", 400)
    message_id = str(uuid.uuid4())
    _log_delivery(store, kind="Notification", topic_arn="", protocol="application", endpoint=endpoint_arn,
                  subscription_arn="", subject=msg.get("Subject") or "",
                  message=_message_for_protocol(msg, "application", ep["endpoint_platform"]), message_id=message_id)
    return message_id


def _publish_to_phone(store, phone: str, msg: dict) -> str:
    if not re.match(r"^\+[1-9][0-9]{6,14}$", phone):
        raise _invalid("Invalid parameter: PhoneNumber Reason: " + phone + " is not valid to publish to")
    _check_message(msg, False)
    s = _state(store)
    if phone in s["opted_out"]:
        raise SnsError("OptedOut", "Phone number is opted out", 400)
    sb = s["sandbox"].get(phone)
    if sb is None or sb["status"] != "Verified":
        raise SnsError("InvalidParameter", "Invalid parameter: PhoneNumber Reason: Destination phone number is not verified in the SMS sandbox", 400)
    message_id = str(uuid.uuid4())
    _log_delivery(store, kind="Notification", topic_arn="", protocol="sms", endpoint=phone,
                  subscription_arn="", subject="", message=msg["Message"], message_id=message_id)
    return message_id


def publish_arn(store, topic_arn: str, message: str) -> bool:
    """Public cross-core seam: publish a raw message to an SNS topic by ARN,
    for callers that already have an envelope ready (EventBridge targets).
    Returns False if the topic does not exist, instead of raising."""
    topic = store.get_topic(topic_arn)
    if not topic:
        return False
    msg = {"Message": message, "Subject": None, "MessageStructure": None,
           "attrs": {}, "group": None, "dedup": None}
    try:
        _publish_to_topic(store, topic, msg)
    except Exception:
        return False
    return True


def _msg_from_params(params: dict) -> dict:
    return {"Message": params.get("Message"), "Subject": params.get("Subject"),
            "MessageStructure": _p(params, "MessageStructure"),
            "attrs": _message_attributes_from_params(params),
            "group": _p(params, "MessageGroupId"), "dedup": _p(params, "MessageDeduplicationId")}


def _publish(store, params):
    topic_arn, target, phone = _p(params, "TopicArn"), _p(params, "TargetArn"), _p(params, "PhoneNumber")
    if not (topic_arn or target or phone):
        raise _invalid("Invalid parameter: TopicArn or TargetArn Reason: no value for required parameter")
    if sum(bool(x) for x in (topic_arn, target, phone)) > 1 and not (topic_arn and not target and not phone):
        raise _invalid("Invalid parameter: Only one of TopicArn, TargetArn or PhoneNumber may be specified")
    if params.get("Message") is None:
        raise _invalid("Invalid parameter: Message Reason: Message is required")
    msg = _msg_from_params(params)
    if phone:
        return _envelope("Publish", _el("MessageId", _publish_to_phone(store, phone, msg)))
    dest = topic_arn or target
    if ":endpoint/" in dest:
        return _envelope("Publish", _el("MessageId", _publish_to_endpoint(store, dest, msg)))
    topic = _require_topic(store, dest)
    message_id, seq = _publish_to_topic(store, topic, msg)
    store.persist()
    return _envelope("Publish", _el("MessageId", message_id) + (_el("SequenceNumber", seq) if seq else ""))


def _publish_batch(store, params):
    topic = _require_topic(store, _p(params, "TopicArn"))
    idxs = sorted({int(m.group(1)) for k in params
                   for m in [re.match(r"^PublishBatchRequestEntries\.member\.(\d+)\.Id$", str(k))] if m})
    if not idxs:
        raise SnsError("EmptyBatchRequest", "The batch request doesn't contain any entries.", 400)
    if len(idxs) > 10:
        raise SnsError("TooManyEntriesInBatchRequest", "The batch request contains more entries than permissible.", 400)
    ids = [str(params[f"PublishBatchRequestEntries.member.{i}.Id"]) for i in idxs]
    if len(set(ids)) != len(ids):
        raise SnsError("BatchEntryIdsNotDistinct", "Two or more batch entries in the request have the same Id.", 400)
    entries = []
    for i in idxs:
        pre = f"PublishBatchRequestEntries.member.{i}"
        sub = {k[len(pre) + 1:]: v for k, v in params.items() if str(k).startswith(pre + ".")}
        entries.append((sub["Id"], _msg_from_params(sub) if "Message" in sub else None))
    total = sum(len((m["Message"] or "").encode()) for _, m in entries if m)
    if total > MAX_MESSAGE_BYTES:
        raise SnsError("BatchRequestTooLong", "The length of all the messages put together is more than the limit.", 400)
    ok, failed = [], []
    for eid, msg in entries:
        try:
            if msg is None:
                raise _invalid("Invalid parameter: Message Reason: Message is required")
            mid, seq = _publish_to_topic(store, topic, msg)
            ok.append("<member>" + _el("Id", eid) + _el("MessageId", mid)
                      + (_el("SequenceNumber", seq) if seq else "") + "</member>")
        except SnsError as e:
            failed.append("<member>" + _el("Id", eid) + _el("Code", e.code) + _el("Message", e.message)
                          + "<SenderFault>true</SenderFault></member>")
    store.persist()
    return _envelope("PublishBatch", f"<Successful>{''.join(ok)}</Successful><Failed>{''.join(failed)}</Failed>")


# ── mobile push: platform applications + endpoints ──────────────────────────
def _app_arn(store, platform: str, name: str) -> str:
    return f"arn:aws:sns:{REGION}:{store.account_id}:app/{platform}/{name}"


def _require_app(store, arn: str) -> dict:
    app = _state(store)["platform_apps"].get(arn)
    if app is None:
        raise SnsError("NotFound", "PlatformApplication does not exist", 404)
    return app


def _create_platform_application(store, params):
    name, platform = _p(params, "Name"), _p(params, "Platform")
    attrs = _entries(params, "Attributes")
    if not name or not re.match(r"^[A-Za-z0-9_.-]{1,256}$", name):
        raise _invalid("Invalid parameter: Name")
    if platform not in PLATFORMS:
        raise _invalid(f"Invalid parameter: Platform Reason: {platform or 'None'} is not supported")
    if not attrs.get("PlatformCredential"):
        raise _invalid("Invalid parameter: Attributes Reason: PlatformCredential is required")
    arn = _app_arn(store, platform, name)
    apps = _state(store)["platform_apps"]
    if arn not in apps:
        apps[arn] = {"arn": arn, "name": name, "platform": platform,
                     "attributes": {"Enabled": "true", **attrs}, "created": _now_iso()}
    else:
        apps[arn]["attributes"].update(attrs)
    store.persist()
    return _envelope("CreatePlatformApplication", _el("PlatformApplicationArn", arn))


def _app_public_attrs(app: dict) -> dict:
    return {k: v for k, v in app["attributes"].items() if k != "PlatformCredential"}


def _get_platform_application_attributes(store, params):
    app = _require_app(store, _p(params, "PlatformApplicationArn"))
    return _envelope("GetPlatformApplicationAttributes", _entry_map(_app_public_attrs(app)))


def _set_platform_application_attributes(store, params):
    app = _require_app(store, _p(params, "PlatformApplicationArn"))
    app["attributes"].update(_entries(params, "Attributes"))
    store.persist()
    return _envelope("SetPlatformApplicationAttributes")


def _list_platform_applications(store, params):
    apps = [a for _, a in sorted(_state(store)["platform_apps"].items())]
    chunk, nxt = _page(apps, _p(params, "NextToken"))
    members = "".join("<member>" + _el("PlatformApplicationArn", a["arn"])
                      + _entry_map(_app_public_attrs(a)) + "</member>" for a in chunk)
    return _envelope("ListPlatformApplications", f"<PlatformApplications>{members}</PlatformApplications>{_next(nxt)}")


def _delete_platform_application(store, params):
    arn = _p(params, "PlatformApplicationArn")
    s = _state(store)
    if s["platform_apps"].pop(arn, None) is not None:
        for e in [e for e, v in s["endpoints"].items() if v["application_arn"] == arn]:
            del s["endpoints"][e]
        store.persist()
    return _envelope("DeletePlatformApplication")


def _create_platform_endpoint(store, params):
    app = _require_app(store, _p(params, "PlatformApplicationArn"))
    token = _p(params, "Token")
    if not token:
        raise _invalid("Invalid parameter: Token")
    attrs = {"Enabled": "true", "Token": token}
    if _p(params, "CustomUserData"):
        attrs["CustomUserData"] = _p(params, "CustomUserData")
    attrs.update(_entries(params, "Attributes"))
    s = _state(store)
    for ep in s["endpoints"].values():
        if ep["application_arn"] == app["arn"] and ep["attributes"].get("Token") == token:
            if any(ep["attributes"].get(k) != v for k, v in attrs.items() if k != "Enabled" or "Enabled" in _entries(params, "Attributes")):
                raise _invalid(f"Invalid parameter: Token Reason: Endpoint {ep['arn']} already exists with the same Token, but different attributes.")
            return _envelope("CreatePlatformEndpoint", _el("EndpointArn", ep["arn"]))
    arn = f"arn:aws:sns:{REGION}:{store.account_id}:endpoint/{app['platform']}/{app['name']}/{uuid.uuid4()}"
    s["endpoints"][arn] = {"arn": arn, "application_arn": app["arn"], "endpoint_platform": app["platform"], "attributes": attrs,
                           "created": _now_iso()}
    store.persist()
    return _envelope("CreatePlatformEndpoint", _el("EndpointArn", arn))


def _require_endpoint(store, arn: str) -> dict:
    ep = _state(store)["endpoints"].get(arn)
    if ep is None:
        raise SnsError("NotFound", "Endpoint does not exist", 404)
    return ep


def _get_endpoint_attributes(store, params):
    ep = _require_endpoint(store, _p(params, "EndpointArn"))
    return _envelope("GetEndpointAttributes", _entry_map(ep["attributes"]))


def _set_endpoint_attributes(store, params):
    ep = _require_endpoint(store, _p(params, "EndpointArn"))
    ep["attributes"].update(_entries(params, "Attributes"))
    store.persist()
    return _envelope("SetEndpointAttributes")


def _delete_endpoint(store, params):
    if _state(store)["endpoints"].pop(_p(params, "EndpointArn"), None) is not None:
        store.persist()
    return _envelope("DeleteEndpoint")


def _list_endpoints_by_platform_application(store, params):
    app = _require_app(store, _p(params, "PlatformApplicationArn"))
    eps = [e for _, e in sorted(_state(store)["endpoints"].items()) if e["application_arn"] == app["arn"]]
    chunk, nxt = _page(eps, _p(params, "NextToken"))
    members = "".join("<member>" + _el("EndpointArn", e["arn"]) + _entry_map(e["attributes"]) + "</member>"
                      for e in chunk)
    return _envelope("ListEndpointsByPlatformApplication", f"<Endpoints>{members}</Endpoints>{_next(nxt)}")


# ── SMS: attributes, opt-out, sandbox ───────────────────────────────────────
def _set_sms_attributes(store, params):
    attrs = _entries(params, "attributes")
    for k in attrs:
        if k not in SMS_ATTRS:
            raise _invalid(f"Invalid parameter: {k}")
    if "DefaultSMSType" in attrs and attrs["DefaultSMSType"] not in ("Promotional", "Transactional"):
        raise _invalid("Invalid parameter: DefaultSMSType")
    _state(store)["sms_attributes"].update(attrs)
    store.persist()
    return _envelope("SetSMSAttributes", always_result=True)


def _get_sms_attributes(store, params):
    want = _members(params, "attributes")
    cur = {"MonthlySpendLimit": "1", "DefaultSMSType": "Promotional", **_state(store)["sms_attributes"]}
    out = {k: v for k, v in cur.items() if not want or k in want}
    return _envelope("GetSMSAttributes", _entry_map(out, "attributes"))


def _phone(params: dict, key: str = "phoneNumber") -> str:
    ph = _p(params, key)
    if not ph:
        raise _invalid(f"Invalid parameter: {key}")
    return ph


def _check_opted_out(store, params):
    out = _phone(params) in _state(store)["opted_out"]
    return _envelope("CheckIfPhoneNumberIsOptedOut", _el("isOptedOut", "true" if out else "false"))


def _list_phone_numbers_opted_out(store, params):
    chunk, nxt = _page(list(_state(store)["opted_out"]), _p(params, "nextToken"))
    members = "".join(_el("member", p) for p in chunk)
    return _envelope("ListPhoneNumbersOptedOut",
                     f"<phoneNumbers>{members}</phoneNumbers>" + (_el("nextToken", nxt) if nxt else ""))


def _opt_in_phone_number(store, params):
    ph = _phone(params)
    o = _state(store)["opted_out"]
    if ph in o:
        o.remove(ph)
        store.persist()
    return _envelope("OptInPhoneNumber", always_result=True)


def _create_sms_sandbox_phone_number(store, params):
    ph = _p(params, "PhoneNumber")
    if not re.match(r"^\+[1-9][0-9]{6,14}$", ph):
        raise SnsError("InvalidParameter", "Invalid parameter: PhoneNumber", 400)
    sb = _state(store)["sandbox"]
    if ph in sb and sb[ph]["status"] == "Verified":
        raise SnsError("UserError", "Phone number is already verified", 400)
    if len(sb) >= 10 and ph not in sb:
        raise SnsError("UserError", "The sandbox phone number limit (10) was reached", 400)
    otp = str(int(hashlib.sha256((ph + uuid.uuid4().hex).encode()).hexdigest(), 16) % 900000 + 100000)
    sb[ph] = {"phone": ph, "status": "Pending", "otp": otp, "language": _p(params, "LanguageCode") or "en-US"}
    _log_delivery(store, kind="SMSSandboxVerification", topic_arn="", protocol="sms", endpoint=ph,
                  subscription_arn="", subject="", message=f"Your verification code is {otp}", token=otp)
    store.persist()
    return _envelope("CreateSMSSandboxPhoneNumber", always_result=True)


def _verify_sms_sandbox_phone_number(store, params):
    ph, otp = _p(params, "PhoneNumber"), _p(params, "OneTimePassword")
    sb = _state(store)["sandbox"].get(ph)
    if sb is None:
        raise SnsError("ResourceNotFound", "No sandbox phone number found for the supplied phone number", 404)
    if sb["otp"] != otp:
        raise SnsError("VerificationException", "The OTP provided does not match", 400)
    sb["status"] = "Verified"
    store.persist()
    return _envelope("VerifySMSSandboxPhoneNumber", always_result=True)


def _delete_sms_sandbox_phone_number(store, params):
    ph = _p(params, "PhoneNumber")
    if _state(store)["sandbox"].pop(ph, None) is None:
        raise SnsError("ResourceNotFound", "No sandbox phone number found for the supplied phone number", 404)
    store.persist()
    return _envelope("DeleteSMSSandboxPhoneNumber", always_result=True)


def _list_sms_sandbox_phone_numbers(store, params):
    nums = [v for _, v in sorted(_state(store)["sandbox"].items())]
    chunk, nxt = _page(nums, _p(params, "NextToken"))
    members = "".join("<member>" + _el("PhoneNumber", n["phone"]) + _el("Status", n["status"]) + "</member>"
                      for n in chunk)
    return _envelope("ListSMSSandboxPhoneNumbers", f"<PhoneNumbers>{members}</PhoneNumbers>{_next(nxt)}")


def _get_sms_sandbox_account_status(store, params):
    return _envelope("GetSMSSandboxAccountStatus", _el("IsInSandbox", "true"))


def _list_origination_numbers(store, params):
    return _envelope("ListOriginationNumbers", "<PhoneNumbers></PhoneNumbers>")


_OPS = {
    "CreateTopic": _create_topic, "ListTopics": _list_topics, "DeleteTopic": _delete_topic,
    "GetTopicAttributes": _get_topic_attributes, "SetTopicAttributes": _set_topic_attributes,
    "AddPermission": _add_permission, "RemovePermission": _remove_permission,
    "TagResource": _tag_resource, "UntagResource": _untag_resource,
    "ListTagsForResource": _list_tags_for_resource,
    "PutDataProtectionPolicy": _put_data_protection_policy,
    "GetDataProtectionPolicy": _get_data_protection_policy,
    "Subscribe": _subscribe, "ConfirmSubscription": _confirm_subscription,
    "Unsubscribe": _unsubscribe, "ListSubscriptions": _list_subscriptions,
    "ListSubscriptionsByTopic": _list_subscriptions_by_topic,
    "SetSubscriptionAttributes": _set_subscription_attributes,
    "GetSubscriptionAttributes": _get_subscription_attributes,
    "Publish": _publish, "PublishBatch": _publish_batch,
    "CreatePlatformApplication": _create_platform_application,
    "GetPlatformApplicationAttributes": _get_platform_application_attributes,
    "SetPlatformApplicationAttributes": _set_platform_application_attributes,
    "ListPlatformApplications": _list_platform_applications,
    "DeletePlatformApplication": _delete_platform_application,
    "CreatePlatformEndpoint": _create_platform_endpoint,
    "GetEndpointAttributes": _get_endpoint_attributes,
    "SetEndpointAttributes": _set_endpoint_attributes, "DeleteEndpoint": _delete_endpoint,
    "ListEndpointsByPlatformApplication": _list_endpoints_by_platform_application,
    "SetSMSAttributes": _set_sms_attributes, "GetSMSAttributes": _get_sms_attributes,
    "CheckIfPhoneNumberIsOptedOut": _check_opted_out,
    "ListPhoneNumbersOptedOut": _list_phone_numbers_opted_out,
    "OptInPhoneNumber": _opt_in_phone_number,
    "CreateSMSSandboxPhoneNumber": _create_sms_sandbox_phone_number,
    "VerifySMSSandboxPhoneNumber": _verify_sms_sandbox_phone_number,
    "DeleteSMSSandboxPhoneNumber": _delete_sms_sandbox_phone_number,
    "ListSMSSandboxPhoneNumbers": _list_sms_sandbox_phone_numbers,
    "GetSMSSandboxAccountStatus": _get_sms_sandbox_account_status,
    "ListOriginationNumbers": _list_origination_numbers,
}


def dispatch(store: MessagingStore, params: dict | None = None) -> SnsResponse:
    """Native AWS SNS Query-protocol router. `params` is the parsed form-encoded
    body ({"Action": "Publish", "TopicArn": ..., "Message": ...})."""
    params = params if isinstance(params, dict) else {}
    action = str(params.get("Action", "")).strip()
    if not action:
        return _error("MissingAction", "The request must include an Action.", 400)
    op = _OPS.get(action)
    if op is None:
        return _error("InvalidAction", f"The action {action} is not implemented.", 400)
    try:
        return op(store, params)
    except SnsError as e:
        return _error(e.code, e.message, e.status)


# ── console REST (flat JSON) — shared by the appliance server and Nano ─────
NOT_SET = "Not set"


def _call(store, action: str, **params):
    """Run a wire op for the console; raise SnsError on an error response."""
    resp = dispatch(store, dict(params, Action=action))
    if resp.status >= 400:
        code = re.search(r"<Code>(.*?)</Code>", resp.body)
        msg = re.search(r"<Message>(.*?)</Message>", resp.body)
        raise SnsError(code.group(1) if code else "Error", _xml_unescape(msg.group(1) if msg else action), resp.status)
    return resp.body


def _xml_unescape(s: str) -> str:
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&amp;", "&")


def _topic_view(store, topic: dict, detail: bool = False) -> dict:
    attrs = _topic_attributes(store, topic)
    key = attrs.get("KmsMasterKeyId")
    v = {
        "name": topic["name"],
        "type": "FIFO" if _is_fifo(topic) else "Standard",
        "arn": topic["topic_arn"],
        "subscriptions": int(attrs["SubscriptionsConfirmed"]),
        "pending": int(attrs["SubscriptionsPending"]),
        "display_name": attrs.get("DisplayName") or NOT_SET,
        "encryption": f"Enabled ({key})" if key else "Disabled",
        "owner": store.account_id, "region": REGION, "created": topic.get("created", ""),
        "tags": dict(topic.get("tags", {})),
    }
    if detail:
        v["attributes"] = attrs
        v["policy"] = attrs["Policy"]
        v["subscription_list"] = [_sub_view(store, topic, s) for s in topic["subscriptions"].values()]
    return v


def _sub_view(store, topic: dict, sub: dict) -> dict:
    return {
        "name": sub["subscription_arn"].rsplit(":", 1)[-1],
        "arn": sub["subscription_arn"], "topic": topic["name"], "topic_arn": topic["topic_arn"],
        "protocol": sub["protocol"],
        "endpoint": sub["endpoint"],
        "status": "Pending confirmation" if sub.get("pending") else "Confirmed",
        "filter_policy": "Set" if sub.get("filter_policy") else NOT_SET,
        "raw_delivery": sub.get("attributes", {}).get("RawMessageDelivery", "false"),
        "created": sub.get("created", ""),
    }


def _all_sub_views(store) -> list:
    return [_sub_view(store, t, s) for a in store.topic_arns() for t in [store.topics[a]]
            for s in t["subscriptions"].values()]


def _app_view(store, app: dict) -> dict:
    eps = sum(1 for e in _state(store)["endpoints"].values() if e["application_arn"] == app["arn"])
    return {"name": app["name"], "platform": app["platform"],
            "enabled": "Yes" if str(app["attributes"].get("Enabled", "true")).lower() == "true" else "No",
            "endpoints": eps, "arn": app["arn"], "created": app.get("created", "")}


def _delivery_view(d: dict) -> dict:
    return {"name": d["id"], "kind": d.get("kind", "Notification"), "topic": (d.get("topic_arn") or "").rsplit(":", 1)[-1] or "Direct",
            "protocol": d.get("protocol", ""), "endpoint": d.get("endpoint", ""),
            "subject": d.get("subject") or NOT_SET, "message": d.get("message", ""),
            "timestamp": d.get("timestamp", ""), "token": d.get("token", "")}


def _sandbox_view(n: dict) -> dict:
    return {"name": n["phone"], "status": n["status"], "language": n.get("language", "en-US")}


def _find_topic_by_name(store, name: str) -> dict:
    arn = _topic_arn(store, name)
    t = store.get_topic(arn)
    if not t:
        raise SnsError("NotFound", f"Topic {name} does not exist", 404)
    return t


def console_dispatch(store, method: str, path: str, query: dict | None, body: dict | None):
    """Serve `/api/aws/sns/...`; returns (status, json-able). Shared by server + Nano."""
    sub = path.split("/api/aws/sns", 1)[-1].strip("/")
    parts = [unquote(x) for x in sub.split("/") if x]
    body = body or {}
    s = _state(store)
    try:
        if parts[:1] == ["topics"]:
            if len(parts) == 1 and method == "GET":
                views = [_topic_view(store, store.topics[a]) for a in store.topic_arns()]
                return 200, {"topics": views, "items": views, "count": len(views)}
            if len(parts) == 1 and method == "POST":
                name = str(body.get("name") or "").strip()
                fifo = str(body.get("type") or "Standard").lower() == "fifo"
                if fifo and not name.endswith(".fifo"):
                    name += ".fifo"
                params = {"Name": name}
                n = 0
                if fifo:
                    params.update({"Attributes.entry.1.key": "FifoTopic", "Attributes.entry.1.value": "true",
                                   "Attributes.entry.2.key": "ContentBasedDeduplication",
                                   "Attributes.entry.2.value": "true"})
                    n = 2
                dn = str(body.get("display_name") or "").strip()
                if dn and dn != NOT_SET:
                    n += 1
                    params.update({f"Attributes.entry.{n}.key": "DisplayName", f"Attributes.entry.{n}.value": dn})
                _call(store, "CreateTopic", **params)
                return 200, _topic_view(store, _find_topic_by_name(store, name), True)
            topic = _find_topic_by_name(store, parts[1]) if len(parts) > 1 else None
            if len(parts) == 2 and method == "GET":
                return 200, _topic_view(store, topic, True)
            if len(parts) == 2 and method == "PATCH":
                want = {str(k): str(v) for k, v in (body.get("tags") or {}).items() if str(k)}
                drop = [k for k in topic.get("tags", {}) if k not in want]
                if drop:
                    _call(store, "UntagResource", ResourceArn=topic["topic_arn"],
                          **{f"TagKeys.member.{i}": k for i, k in enumerate(drop, 1)})
                if want:
                    flat = {}
                    for i, (k, v) in enumerate(want.items(), 1):
                        flat[f"Tags.member.{i}.Key"], flat[f"Tags.member.{i}.Value"] = k, v
                    _call(store, "TagResource", ResourceArn=topic["topic_arn"], **flat)
                return 200, _topic_view(store, topic, True)
            if len(parts) == 2 and method == "DELETE":
                _call(store, "DeleteTopic", TopicArn=topic["topic_arn"])
                return 200, {"deleted": True, "name": topic["name"]}
            if len(parts) == 3 and parts[2] == "publish" and method == "POST":
                params = {"TopicArn": topic["topic_arn"], "Message": str(body.get("message", ""))}
                if body.get("subject"):
                    params["Subject"] = str(body["subject"])
                if _is_fifo(topic):
                    params["MessageGroupId"] = str(body.get("group_id") or "default")
                    params["MessageDeduplicationId"] = str(body.get("deduplication_id") or uuid.uuid4())
                out = _call(store, "Publish", **params)
                return 200, {"message_id": re.search(r"<MessageId>(.*?)</MessageId>", out).group(1)}
            if len(parts) == 3 and parts[2] == "subscriptions":
                if method == "GET":
                    items = [_sub_view(store, topic, x) for x in topic["subscriptions"].values()]
                    return 200, {"items": items, "count": len(items)}
                if method == "POST":
                    _call(store, "Subscribe", TopicArn=topic["topic_arn"], Protocol=str(body.get("protocol", "")).lower(),
                          Endpoint=str(body.get("endpoint", "")), ReturnSubscriptionArn="true")
                    return 200, {"subscribed": True}
        elif parts[:1] == ["subscriptions"]:
            if len(parts) == 1 and method == "GET":
                items = _all_sub_views(store)
                return 200, {"items": items, "count": len(items)}
            if len(parts) == 1 and method == "POST":
                t = _find_topic_by_name(store, str(body.get("topic") or body.get("name") or ""))
                _call(store, "Subscribe", TopicArn=t["topic_arn"], Protocol=str(body.get("protocol", "")).lower(),
                      Endpoint=str(body.get("endpoint", "")), ReturnSubscriptionArn="true")
                return 200, {"subscribed": True}
            if len(parts) == 2 and method == "DELETE":
                v = next((x for x in _all_sub_views(store) if x["name"] == parts[1]), None)
                if v is None:
                    raise SnsError("NotFound", "Subscription does not exist", 404)
                _call(store, "Unsubscribe", SubscriptionArn=v["arn"])
                return 200, {"deleted": True, "name": parts[1]}
            if len(parts) == 3 and parts[2] == "confirm" and method == "POST":
                v = next((x for x in _all_sub_views(store) if x["name"] == parts[1]), None)
                if v is None:
                    raise SnsError("NotFound", "Subscription does not exist", 404)
                tok = store.topics[v["topic_arn"]]["subscriptions"][v["arn"]].get("token", "")
                _call(store, "ConfirmSubscription", TopicArn=v["topic_arn"], Token=tok)
                return 200, {"confirmed": True}
        elif parts[:1] == ["platform-applications"]:
            if len(parts) == 1 and method == "GET":
                items = [_app_view(store, a) for _, a in sorted(s["platform_apps"].items())]
                return 200, {"items": items, "count": len(items)}
            if len(parts) == 1 and method == "POST":
                _call(store, "CreatePlatformApplication", Name=str(body.get("name", "")),
                      Platform=str(body.get("platform") or "GCM"),
                      **{"Attributes.entry.1.key": "PlatformCredential",
                         "Attributes.entry.1.value": str(body.get("credential") or "vyomi-demo-api-key")})
                return 200, {"created": True}
            if len(parts) == 2 and method == "DELETE":
                app = next((a for a in s["platform_apps"].values() if a["name"] == parts[1]), None)
                if app is None:
                    raise SnsError("NotFound", "PlatformApplication does not exist", 404)
                _call(store, "DeletePlatformApplication", PlatformApplicationArn=app["arn"])
                return 200, {"deleted": True, "name": parts[1]}
        elif parts[:1] == ["deliveries"] and len(parts) == 1:
            if method == "GET":
                items = [_delivery_view(d) for d in reversed(s["deliveries"])]
                return 200, {"items": items, "count": len(items)}
            if method == "DELETE":
                s["deliveries"].clear()
                store.persist()
                return 200, {"cleared": True}
        elif parts[:1] == ["sms-sandbox"]:
            if len(parts) == 1 and method == "GET":
                items = [_sandbox_view(n) for _, n in sorted(s["sandbox"].items())]
                return 200, {"items": items, "count": len(items)}
            if len(parts) == 1 and method == "POST":
                _call(store, "CreateSMSSandboxPhoneNumber", PhoneNumber=str(body.get("phone") or body.get("name") or ""))
                return 200, {"created": True}
            if len(parts) == 2 and method == "DELETE":
                _call(store, "DeleteSMSSandboxPhoneNumber", PhoneNumber=parts[1])
                return 200, {"deleted": True, "name": parts[1]}
        return 404, {"error": f"No such route: {method} {path}"}
    except SnsError as e:
        return e.status, {"error": e.message, "code": e.code}


def is_sns_console_path(path: str) -> bool:
    return path.startswith("/api/aws/sns/") or path == "/api/aws/sns"
