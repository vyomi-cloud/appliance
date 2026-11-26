import json

import approval
import gcp

approval.ensure_inbox()
publisher, subscriber = gcp.pubsub_clients()
publisher.publish(approval.TOPIC, json.dumps({"request_id": "smoke", "summary": "inbox smoke test"}).encode(), kind="smoke", requester="duty").result(timeout=30)
got = []
for _ in range(10):
    got = subscriber.pull(request={"subscription": approval.INBOX, "max_messages": 10}, timeout=15).received_messages
    got = [m for m in got if b"smoke" in m.message.data] or got
    if any(b"smoke" in m.message.data for m in got):
        break
mine = [m for m in got if b"smoke" in m.message.data]
assert mine, "nothing arrived in the approver inbox"
print("received:", json.loads(mine[0].message.data)["summary"], "| requester attribute:", mine[0].message.attributes["requester"])
subscriber.acknowledge(request={"subscription": approval.INBOX, "ack_ids": [m.ack_id for m in mine]})
again = subscriber.pull(request={"subscription": approval.INBOX, "max_messages": 10, "return_immediately": True}, timeout=15).received_messages
print("redelivered after ack:", any(b"smoke" in m.message.data for m in again))
