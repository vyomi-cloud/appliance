# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""SNS core — substrate-independent in-memory pub/sub. The appliance has no SNS
yet, so this is GREENFIELD (nothing to port) but targets the NATIVE AWS SNS wire
— the **Query protocol** (form-encoded `Action=Publish&...`, XML responses,
http://sns.amazonaws.com/doc/2010-03-31/) — so an unmodified boto3/aws-cli SNS
client works. NO fastapi / boto3 / socket imports → loads under Pyodide. Persists
through the MessagingStore seam (core/messaging_store.py).

This is the pub/sub half of the eventing swap-table entry (the WASM analogue of
NATS): topics + subscriptions + **real fan-out** — `Publish` delivers the SNS
notification envelope into every subscribed SQS queue (the canonical
SNS→SQS event pattern), reusing core/sqs_core.enqueue so the message is a real,
receivable SQS message.

Scope (v1 slice): CreateTopic, ListTopics, DeleteTopic, Subscribe, Unsubscribe,
ListSubscriptionsByTopic, Publish (sqs fan-out). HTTP/email/Lambda protocols,
filter policies, and raw-message-delivery reuse the same helpers and slot in next.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

from core.messaging_store import MessagingStore, REGION
from core import sqs_core

SNS_NS = "http://sns.amazonaws.com/doc/2010-03-31/"


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
    return uuid.uuid4().hex


def _topic_arn(store, name: str) -> str:
    return f"arn:aws:sns:{REGION}:{store.account_id}:{name}"


# ── response builders (native SNS Query-protocol XML) ──────────────────────
def _envelope(action: str, result_inner: str = "") -> SnsResponse:
    result = f"<{action}Result>{result_inner}</{action}Result>" if result_inner else ""
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


def _require_topic(store, arn):
    t = store.get_topic(arn)
    if not t:
        raise SnsError("NotFound", "Topic does not exist.", 404)
    return t


# ── operations ──────────────────────────────────────────────────────────────
def _create_topic(store, params):
    name = str(params.get("Name", "")).strip()
    if not name:
        raise SnsError("InvalidParameter", "Name is required.", 400)
    arn = _topic_arn(store, name)
    if not store.get_topic(arn):
        store.put_topic(arn, {"topic_arn": arn, "name": name, "subscriptions": {},
                              "created": _now_iso()})
        store.persist()
    return _envelope("CreateTopic", _el("TopicArn", arn))


def _list_topics(store, params):
    members = "".join("<member>" + _el("TopicArn", a) + "</member>" for a in store.topic_arns())
    return _envelope("ListTopics", f"<Topics>{members}</Topics>")


def _delete_topic(store, params):
    arn = str(params.get("TopicArn", "")).strip()
    _require_topic(store, arn)
    store.drop_topic(arn)
    store.persist()
    return _envelope("DeleteTopic")


def _subscribe(store, params):
    arn = str(params.get("TopicArn", "")).strip()
    topic = _require_topic(store, arn)
    protocol = str(params.get("Protocol", "")).strip()
    endpoint = str(params.get("Endpoint", "")).strip()
    if not protocol or not endpoint:
        raise SnsError("InvalidParameter", "Protocol and Endpoint are required.", 400)
    sub_arn = f"{arn}:{uuid.uuid4().hex[:8]}"
    topic["subscriptions"][sub_arn] = {"subscription_arn": sub_arn, "protocol": protocol,
                                       "endpoint": endpoint}
    store.persist()
    return _envelope("Subscribe", _el("SubscriptionArn", sub_arn))


def _unsubscribe(store, params):
    sub_arn = str(params.get("SubscriptionArn", "")).strip()
    for topic in store.topics.values():
        if sub_arn in topic["subscriptions"]:
            del topic["subscriptions"][sub_arn]
            store.persist()
            return _envelope("Unsubscribe")
    raise SnsError("NotFound", "Subscription does not exist.", 404)


def _list_subscriptions_by_topic(store, params):
    arn = str(params.get("TopicArn", "")).strip()
    topic = _require_topic(store, arn)
    members = []
    for sub in topic["subscriptions"].values():
        members.append("<member>" + _el("SubscriptionArn", sub["subscription_arn"])
                       + _el("Owner", store.account_id) + _el("Protocol", sub["protocol"])
                       + _el("Endpoint", sub["endpoint"]) + _el("TopicArn", arn) + "</member>")
    return _envelope("ListSubscriptionsByTopic", f"<Subscriptions>{''.join(members)}</Subscriptions>")


def _publish(store, params):
    arn = str(params.get("TopicArn", "")).strip()
    topic = _require_topic(store, arn)
    message = params.get("Message")
    if message is None:
        raise SnsError("InvalidParameter", "Message is required.", 400)
    message = str(message)
    subject = params.get("Subject")
    message_id = uuid.uuid4().hex
    # Fan out to every SQS subscription (the canonical SNS→SQS event pattern).
    envelope = {
        "Type": "Notification", "MessageId": message_id, "TopicArn": arn,
        "Message": message, "Timestamp": _now_iso(), "SignatureVersion": "1",
    }
    if subject is not None:
        envelope["Subject"] = str(subject)
    body = json.dumps(envelope)
    for sub in topic["subscriptions"].values():
        if sub["protocol"] != "sqs":
            continue  # other protocols (http/email/lambda) slot in next
        queue = store.get_queue_by_arn(sub["endpoint"])
        if queue is not None:
            sqs_core.enqueue(store, queue, body)
    store.persist()
    return _envelope("Publish", _el("MessageId", message_id))


_OPS = {
    "CreateTopic": _create_topic, "ListTopics": _list_topics, "DeleteTopic": _delete_topic,
    "Subscribe": _subscribe, "Unsubscribe": _unsubscribe,
    "ListSubscriptionsByTopic": _list_subscriptions_by_topic, "Publish": _publish,
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
