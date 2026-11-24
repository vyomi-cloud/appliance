import json
import time
import uuid

from google.api_core import exceptions as gex

import gcp

TOPIC = f"projects/{gcp.PROJECT}/topics/work-order-approval"
INBOX = f"projects/{gcp.PROJECT}/subscriptions/approver-inbox"
LEDGER = "approval-ledger"


def ensure_inbox():
    publisher, subscriber = gcp.pubsub_clients()
    for create, request in ((publisher.create_topic, {"name": TOPIC}), (subscriber.create_subscription, {"name": INBOX, "topic": TOPIC, "ack_deadline_seconds": 30})):
        try:
            create(request=request)
        except gex.AlreadyExists:
            pass


def request_approval(asset_id, summary, priority, requester):
    """The write path: the ledger row first (PENDING), then the message for the approver. Nothing is written to work-orders."""
    rid = "req-" + uuid.uuid4().hex[:10]
    payload = {"request_id": rid, "asset_id": asset_id, "summary": summary, "priority": priority, "requester": requester}
    gcp.firestore_client().collection(LEDGER).document(rid).set(dict(payload, status="PENDING", ts=int(time.time())))
    publisher, _ = gcp.pubsub_clients()
    publisher.publish(TOPIC, json.dumps(payload).encode(), requester=requester, kind="work-order").result(timeout=30)
    return rid


def pull_request(rid):
    """What an approver's tool does: pull from approver-inbox until the message for this request arrives. Returns (message body, ack id)."""
    _, subscriber = gcp.pubsub_clients()
    for _ in range(30):
        for m in subscriber.pull(request={"subscription": INBOX, "max_messages": 10}, timeout=15).received_messages:
            body = json.loads(m.message.data)
            if body.get("request_id") == rid:
                return body, m.ack_id
            subscriber.modify_ack_deadline(request={"subscription": INBOX, "ack_ids": [m.ack_id], "ack_deadline_seconds": 0})     # not ours: release it
        time.sleep(0.3)
    return None, None


def ack(ack_id):
    gcp.pubsub_clients()[1].acknowledge(request={"subscription": INBOX, "ack_ids": [ack_id]})


def ledger_row(rid):
    return gcp.firestore_client().collection(LEDGER).document(rid).get().to_dict() or {}


def wait_for_decision(rid, tries=80):
    """The waiting caller: poll the ledger until the status leaves PENDING."""
    for _ in range(tries):
        row = ledger_row(rid)
        if row.get("status") not in (None, "PENDING"):
            return row
        time.sleep(0.25)
    return ledger_row(rid)
