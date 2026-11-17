"""Component 4 Gateway: APIM exposing the tool catalog (API + operations), subscription keys, policies, MCP exposure; no Cedar equivalent exists on Azure."""
import json, requests
from _common import *

P = Probe(4, "gateway", "Gateway: APIM tool catalog + subscription key + policies + MCP")
B = endpoint(); ensure_rg(B)
A = {}


def setup():
    from azure.mgmt.apimanagement import ApiManagementClient
    a = arm(ApiManagementClient, B); A["c"] = a
    a.api_management_service.begin_create_or_update(RG, "apim1", {"location": LOC, "sku": {"name": "Developer", "capacity": 1}, "publisher_email": "a@b.c", "publisher_name": "p"}).result()
    a.api.begin_create_or_update(RG, "apim1", "tools", {"display_name": "facilities-tools", "path": "tools", "protocols": ["https"], "subscription_required": True, "service_url": "http://127.0.0.1:1"}).result()
    for op, m, u in (("create_work_order", "POST", "/work-orders"), ("lookup_asset", "GET", "/assets/{id}"), ("get_policy", "GET", "/policy")):
        a.api_operation.create_or_update(RG, "apim1", "tools", op, {"display_name": op, "method": m, "url_template": u})
    ops = [o.name for o in a.api_operation.list_by_api(RG, "apim1", "tools")]
    assert len(ops) == 3, ops
    a.subscription.create_or_update(RG, "apim1", "agent-sub", {"display_name": "agent", "scope": "/apis/tools"})
    A["key"] = a.subscription.list_secrets(RG, "apim1", "agent-sub").primary_key
    return ops


def gw(path, method="GET", key=None, **kw):
    h = {"Ocp-Apim-Subscription-Key": key} if key else {}
    return requests.request(method, B + "/azure-data/apim/apim1/tools" + path, headers=h, timeout=10, **kw)


def key_check():
    assert gw("/policy").status_code == 401, "no key accepted"
    assert gw("/policy", key="wrong").status_code == 401, "wrong key accepted"
    return "401 without / with wrong key"


def policies():
    pol = '<policies><inbound><base/><rate-limit calls="2" renewal-period="60"/><set-header name="x-agent" exists-action="override"><value>facilities</value></set-header><choose><when condition="@(context.Request.Headers.GetValueOrDefault(&quot;x-deny&quot;,&quot;&quot;) == &quot;1&quot;)"><return-response><set-status code="403"/><set-body>denied</set-body></return-response></when></choose><return-response><set-status code="200"/><set-body>{"policy":"approvals above 500 need a manager"}</set-body></return-response></inbound><backend><base/></backend><outbound><base/></outbound></policies>'
    A["c"].api_operation_policy.create_or_update(RG, "apim1", "tools", "get_policy", "policy", {"value": pol, "format": "xml"})
    r1 = gw("/policy", key=A["key"]); r2 = gw("/policy", key=A["key"]); r3 = gw("/policy", key=A["key"])
    assert r1.status_code == 200 and "approvals above 500" in r1.text, (r1.status_code, r1.text)
    assert 429 in (r2.status_code, r3.status_code), f"rate-limit not enforced: {r1.status_code},{r2.status_code},{r3.status_code}"
    return f"{r1.status_code},{r2.status_code},{r3.status_code}"


def conditional_deny():
    """The Cedar-like step: a conditional allow/deny on a request attribute. APIM's equivalent is a choose/when expression policy."""
    a = A["c"]
    a.api_operation.create_or_update(RG, "apim1", "tools", "deny_test", {"display_name": "deny_test", "method": "GET", "url_template": "/deny"})
    pol = ('<policies><inbound><base/><choose><when condition="@(context.Request.Headers.GetValueOrDefault(&quot;x-deny&quot;,&quot;&quot;) == &quot;1&quot;)">'
           '<return-response><set-status code="403"/><set-body>denied</set-body></return-response></when></choose>'
           '<return-response><set-status code="200"/><set-body>allowed</set-body></return-response></inbound><backend><base/></backend><outbound><base/></outbound></policies>')
    a.api_operation_policy.create_or_update(RG, "apim1", "tools", "deny_test", "policy", {"value": pol, "format": "xml"})
    ok = requests.get(B + "/azure-data/apim/apim1/tools/deny", headers={"Ocp-Apim-Subscription-Key": A["key"]}, timeout=10)
    no = requests.get(B + "/azure-data/apim/apim1/tools/deny", headers={"Ocp-Apim-Subscription-Key": A["key"], "x-deny": "1"}, timeout=10)
    assert (ok.status_code, no.status_code) == (200, 403), f"choose/when @(...) not evaluated: allow={ok.status_code} deny={no.status_code} skipped={no.headers.get('x-vyomi-apim-skipped-policies')}"
    return "allow 200 / deny 403"


def mcp_api():
    """APIM can expose an API as an MCP server (api type 'mcp'): create it and call tools/list as JSON-RPC at the gateway."""
    a = A["c"]
    a.api.begin_create_or_update(RG, "apim1", "mcp1", {"display_name": "mcp", "path": "mcp", "protocols": ["https"], "subscription_required": True, "api_type": "mcp",
                                                       "service_url": "http://127.0.0.1:1"}).result()
    r = requests.post(B + "/azure-data/apim/apim1/mcp", headers={"Ocp-Apim-Subscription-Key": A["key"], "Content-Type": "application/json"},
                      json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=10)
    assert r.status_code == 200 and "tools" in r.text, (r.status_code, r.text[:150])
    return r.text[:120]


if P.step("APIM service + 'tools' API + 3 operations (the tool catalog) via azure-mgmt-apimanagement", setup):
    P.step("subscription key required and checked at the gateway", key_check)
    P.step("operation policy: rate-limit + set-header + return-response executed", policies)
    P.step("conditional deny via choose/when with an @(...) expression (Cedar substitute)", conditional_deny)
P.step("MCP exposure: APIM api type=mcp + JSON-RPC tools/list through the gateway", mcp_api)
P.note("Cedar-like policy engine on Azure", "does not exist natively (the doc agrees); APIM policy expressions are the substitute. Not a simulator gap.")
P.finish()
