import json
import time
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azlab import HOST, AMQP_PORT
from azdata import table

TOPIC, INBOX, LEDGER = "work-order-approval", "approver-inbox", "approvalledger"


def conn():
    return f"Endpoint=sb://{HOST}:{AMQP_PORT};SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=vyomi;UseDevelopmentEmulator=true"


def request_approval(request_id, asset_id, summary, priority, requester):
    payload = {"request_id": request_id, "asset_id": asset_id, "summary": summary, "priority": priority, "requester": requester}
    table(LEDGER).upsert_entity(dict(PartitionKey="req", RowKey=request_id, status="PENDING", ts=int(time.time()), **payload))
    with ServiceBusClient.from_connection_string(conn()) as c, c.get_topic_sender(TOPIC) as s:
        s.send_messages(ServiceBusMessage(json.dumps(payload), subject="work-order", application_properties={"requester": requester, "kind": "work-order"}))
    return {"request_id": request_id, "status": "PENDING_APPROVAL"}


def pull_request(request_id, tries=15):
    """The approver reads the inbox: complete our message, abandon (put back) anyone else's."""
    with ServiceBusClient.from_connection_string(conn()) as c:
        for _ in range(tries):
            with c.get_subscription_receiver(TOPIC, INBOX, max_wait_time=2) as r:
                for m in r.receive_messages(max_message_count=10, max_wait_time=2):
                    body = json.loads(b"".join(m.body).decode())
                    if body.get("request_id") == request_id:
                        r.complete_message(m)
                        return body
                    r.abandon_message(m)
    return None


def ledger_row(request_id):
    return dict(table(LEDGER).get_entity("req", request_id))


def wait_decision(request_id, out, tries=80):
    for _ in range(tries):
        row = ledger_row(request_id)
        if row.get("status") not in (None, "PENDING"):
            out["row"] = row
            return
        time.sleep(0.25)


def work_orders():
    return [dict(e) for e in table("workorders").list_entities()]
