import json
from azure.mgmt.servicebus import ServiceBusManagementClient
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azlab import arm, RG, LOC
from approval import conn, TOPIC, INBOX

sb = arm(ServiceBusManagementClient)
sb.namespaces.begin_create_or_update(RG, "facilities-bus", {"location": LOC, "sku": {"name": "Standard", "tier": "Standard"}}).result()
sb.topics.create_or_update(RG, "facilities-bus", TOPIC, {})
sb.subscriptions.create_or_update(RG, "facilities-bus", TOPIC, INBOX, {})

with ServiceBusClient.from_connection_string(conn()) as c:
    with c.get_topic_sender(TOPIC) as s:
        s.send_messages(ServiceBusMessage(json.dumps({"request_id": "smoke", "summary": "inbox smoke test"}), subject="smoke", application_properties={"requester": "duty"}))
    print("messages waiting in the inbox (ARM):", sb.subscriptions.get(RG, "facilities-bus", TOPIC, INBOX).message_count)
    with c.get_subscription_receiver(TOPIC, INBOX, max_wait_time=10) as r:
        got = r.receive_messages(max_message_count=5, max_wait_time=10)
        print("received:", json.loads(b"".join(got[0].body))["summary"], "| requester property:", got[0].application_properties.get(b"requester"))
        for m in got:
            r.complete_message(m)
    with c.get_subscription_receiver(TOPIC, INBOX, max_wait_time=2) as r:
        print("redelivered after complete:", len(r.receive_messages(max_message_count=1, max_wait_time=2)))
