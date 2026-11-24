from azure.mgmt.apimanagement.models import SubscriptionCreateParameters
from azlab import rid, ensure_rg, RG, LOC, HTTP_ENDPOINT
from azdata import function_key, FUNCTION_APP
from gw import apim, SERVICE, SUBSCRIPTION, subscription_key

ensure_rg()
a = apim()
a.api_management_service.begin_create_or_update(RG, SERVICE, {"location": LOC, "sku": {"name": "Developer", "capacity": 1},
                                                              "publisher_email": "ops@facilities.example.com", "publisher_name": "facilities"}).result()
backend = f"{HTTP_ENDPOINT}/azure-data/functions/{FUNCTION_APP}/api"       # the gateway reaches the Function App over the simulator's plain-http address
a.api.begin_create_or_update(RG, SERVICE, "tools", {"display_name": "facilities-tools", "path": "tools", "protocols": ["https"],
                                                    "subscription_required": True, "service_url": backend}).result()
for op in ("kb-search", "asset-status", "create-work-order"):
    a.api_operation.create_or_update(RG, SERVICE, "tools", op, {"display_name": op, "method": "POST", "url_template": "/" + op})

POLICY = (f'<policies><inbound><base/>'
          f'<set-header name="x-functions-key" exists-action="override"><value>{function_key()}</value></set-header>'
          '<rate-limit-by-key calls="60" renewal-period="60" counter-key="@(context.Subscription.Id)"/>'
          '</inbound><backend><base/></backend><outbound><base/></outbound><on-error><base/></on-error></policies>')
a.api_policy.create_or_update(RG, SERVICE, "tools", "policy", {"value": POLICY, "format": "xml"})
a.subscription.create_or_update(RG, SERVICE, SUBSCRIPTION, SubscriptionCreateParameters(
    display_name="facilities agent", scope=rid("Microsoft.ApiManagement", "service", SERVICE) + "/apis"))
print("gateway", SERVICE, "| catalogue:", sorted(o.name for o in a.api_operation.list_by_api(RG, SERVICE, "tools")), "| subscription key issued:", bool(subscription_key()))
