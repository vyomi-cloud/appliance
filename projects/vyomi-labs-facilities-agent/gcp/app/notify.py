import time

from google.api_core import exceptions as gex

import gcp

publisher, subscriber = gcp.pubsub_clients()
topic = f"projects/{gcp.PROJECT}/topics/facilities-doc-events"
subscription = f"projects/{gcp.PROJECT}/subscriptions/facilities-doc-events-sub"
for create, request in ((publisher.create_topic, {"name": topic}), (subscriber.create_subscription, {"name": subscription, "topic": topic})):
    try:
        create(request=request)
    except gex.AlreadyExists:
        pass

bucket = gcp.storage_client().bucket("facilities-docs")
bucket.notification(topic_name="facilities-doc-events", topic_project=gcp.PROJECT, event_types=["OBJECT_FINALIZE"], payload_format="JSON_API_V1").create()
bucket.blob("docs/notify-probe.md").upload_from_string(b"# Notify probe\nThis object only exists to prove the bucket notification.")

received = []
for _ in range(20):
    received = subscriber.pull(request={"subscription": subscription, "max_messages": 5}, timeout=15).received_messages
    if received:
        break
    time.sleep(0.5)
assert received, "no notification arrived"
attributes = dict(received[0].message.attributes)
print("notification:", attributes["eventType"], attributes["objectId"])
subscriber.acknowledge(request={"subscription": subscription, "ack_ids": [m.ack_id for m in received]})
bucket.blob("docs/notify-probe.md").delete()
