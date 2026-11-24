import requests
from azlab import RG
from gw import apim, SERVICE, url, headers

BASE = "<backend><base/></backend><outbound><base/></outbound><on-error><base/></on-error></policies>"
apim().api_operation_policy.create_or_update(RG, SERVICE, "tools", "asset-status", "policy", {
    "value": '<policies><inbound><base/><rate-limit calls="1000" renewal-period="60"/></inbound>' + BASE, "format": "xml"})

DENY_WRITE = ('<policies><inbound><base/><choose><when condition="@(string.IsNullOrEmpty(context.Request.Headers.GetValueOrDefault(&quot;x-approval-id&quot;,&quot;&quot;)))">'
              '<return-response><set-status code="403" reason="Forbidden"/><set-header name="Content-Type" exists-action="override"><value>application/json</value></set-header>'
              '<set-body>{"error":"write tools need an approved request (x-approval-id)"}</set-body></return-response></when></choose></inbound>' + BASE)
apim().api_operation_policy.create_or_update(RG, SERVICE, "tools", "create-work-order", "policy", {"value": DENY_WRITE, "format": "xml"})

no = requests.post(url("tools/create-work-order"), json={"request_id": "x"}, headers=headers(), timeout=30)
yes = requests.post(url("tools/create-work-order"), json={"request_id": "nonexistent"}, headers=headers({"x-approval-id": "req-none"}), timeout=60)
print("write tool without x-approval-id:", no.status_code, no.json()["error"])
print("write tool with x-approval-id: reaches the function ->", yes.status_code, yes.json())
