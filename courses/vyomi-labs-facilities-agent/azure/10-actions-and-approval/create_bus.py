from azure.mgmt.servicebus import ServiceBusManagementClient
from azlab import arm, ensure_rg, RG, LOC

ensure_rg()
sb = arm(ServiceBusManagementClient)
sb.namespaces.begin_create_or_update(RG, "facilities-bus", {"location": LOC, "sku": {"name": "Standard", "tier": "Standard"}}).result()
sb.topics.create_or_update(RG, "facilities-bus", "work-order-approval", {})
sb.subscriptions.create_or_update(RG, "facilities-bus", "work-order-approval", "approver-inbox", {})
print("namespace facilities-bus | topic work-order-approval | subscription", [s.name for s in sb.subscriptions.list_by_topic(RG, "facilities-bus", "work-order-approval")][0])
