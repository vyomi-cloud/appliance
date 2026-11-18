"""Azure reference-arch component 4 (Gateway): APIM policy expressions, validate-jwt with Entra tokens, ip-filter, MCP API type, WAF policies.

Real libraries only: azure-mgmt-apimanagement / azure-mgmt-frontdoor / azure-mgmt-network (ARM), azure-identity (Entra token over the HTTPS front),
PyJWT, the official `mcp` client (streamable HTTP), requests for the gateway data plane. Runs the real appliance app (server.py) in-process.
Needs: pip install azure-mgmt-apimanagement azure-mgmt-frontdoor azure-mgmt-network azure-mgmt-resource azure-identity PyJWT mcp requests
"""
import asyncio, json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_azure_entra_jwt_sdk import start_sim, check, TENANT  # noqa: E402
import test_azure_entra_jwt_sdk as _E  # noqa: E402

SUB = "00000000-0000-0000-0000-cloudlearn01"
RG, LOC = "rg-gw", "eastus"
SEEN = []


class Backend(BaseHTTPRequestHandler):
    def _do(self):
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n).decode() if n else ""
        SEEN.append({"method": self.command, "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        out = json.dumps({"ok": True, "method": self.command, "path": self.path, "body": body}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(out))); self.end_headers(); self.wfile.write(out)
    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _do

    def log_message(self, *a):
        pass


def _err(r):
    return bool(getattr(r, "isError", None) if hasattr(r, "isError") else getattr(r, "is_error", False))


def _sch(t):
    return getattr(t, "inputSchema", None) or getattr(t, "input_schema")


def arm(cls, base, **kw):
    from azure.core.credentials import AccessToken
    from azure.core.pipeline.policies import SansIOHTTPPolicy

    class Cred:
        def get_token(self, *a, **k):
            return AccessToken("x", 4102444800)
    return cls(Cred(), SUB, base_url=base, authentication_policy=SansIOHTTPPolicy(), polling_interval=0, **kw)


def main():
    import requests, jwt
    from azure.identity import ClientSecretCredential
    from azure.mgmt.apimanagement import ApiManagementClient
    from azure.mgmt.resource.resources import ResourceManagementClient
    http, tls, ca = start_sim()
    os.environ["REQUESTS_CA_BUNDLE"] = ca
    H = {"Authorization": "Bearer x", "Content-Type": "application/json"}
    bsrv = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    threading.Thread(target=bsrv.serve_forever, daemon=True).start()
    backend = f"http://127.0.0.1:{bsrv.server_address[1]}"
    arm(ResourceManagementClient, http).resource_groups.create_or_update(RG, {"location": LOC})

    # ---- Entra: API app with a role, two clients (one granted, one not), one user
    role = "11111111-1111-1111-1111-111111111111"
    api_app = requests.post(http + "/v1.0/applications", json={"displayName": "facilities-api", "identifierUris": ["api://facilities-api"],
                            "appRoles": [{"id": role, "value": "Facilities.Invoke", "displayName": "Invoke", "description": "d", "isEnabled": True, "allowedMemberTypes": ["Application"]}]}, headers=H).json()

    def client(name, granted):
        a = requests.post(http + "/v1.0/applications", json={"displayName": name, **({"requiredResourceAccess": [{"resourceAppId": api_app["appId"], "resourceAccess": [{"id": role, "type": "Role"}]}]} if granted else {})}, headers=H).json()
        sec = requests.post(http + f"/v1.0/applications/{a['id']}/addPassword", json={"passwordCredential": {"displayName": "d"}}, headers=H).json()["secretText"]
        return a["appId"], sec

    good_id, good_sec = client("agent-granted", True)
    bad_id, bad_sec = client("agent-ungranted", False)

    def token(cid, sec, scope="api://facilities-api/.default"):
        return ClientSecretCredential(TENANT, cid, sec, authority=tls, disable_instance_discovery=True, connection_verify=ca).get_token(scope).token
    tok = token(good_id, good_sec)
    tok_norole = token(bad_id, bad_sec)
    tok_other_aud = token(good_id, good_sec, "api://someone-else/.default")
    v1 = requests.post(http + f"/{TENANT}/oauth2/token", data={"grant_type": "client_credentials", "client_id": good_id, "client_secret": good_sec, "resource": "api://facilities-api"}).json()["access_token"]

    # ---- APIM via azure-mgmt-apimanagement
    a = arm(ApiManagementClient, http)
    a.api_management_service.begin_create_or_update(RG, "facilities-apim", {"location": LOC, "sku": {"name": "Developer", "capacity": 1}, "publisher_email": "a@b.c", "publisher_name": "p"}).result()
    a.api.begin_create_or_update(RG, "facilities-apim", "tools", {"display_name": "facilities-tools", "path": "tools", "protocols": ["https"], "subscription_required": True, "service_url": backend}).result()
    for op, m, u in (("create_work_order", "POST", "/work-orders"), ("lookup_asset", "GET", "/assets/{id}"), ("get_policy", "GET", "/policy"), ("admin_only", "GET", "/admin")):
        a.api_operation.create_or_update(RG, "facilities-apim", "tools", op, {"display_name": op, "method": m, "url_template": u, "description": f"tool {op}"})
    a.subscription.create_or_update(RG, "facilities-apim", "agent-sub", {"display_name": "agent", "scope": "/apis"})
    key = a.subscription.list_secrets(RG, "facilities-apim", "agent-sub").primary_key
    oc = f"{http}/{TENANT}/v2.0/.well-known/openid-configuration"
    api_pol = f'''<policies><inbound><base/>
      <validate-jwt header-name="Authorization" failed-validation-httpcode="401" failed-validation-error-message="Unauthorized. Access token is missing or invalid.">
        <openid-config url="{oc}"/>
        <audiences><audience>api://facilities-api</audience></audiences>
        <required-claims><claim name="roles" match="any"><value>Facilities.Invoke</value></claim></required-claims>
      </validate-jwt>
      <set-header name="x-caller" exists-action="override"><value>@(context.Request.Headers.GetValueOrDefault("Authorization","").Split(' ').Last().AsJwt()?.Claims.GetValueOrDefault("azp", new string[]{{}}).FirstOrDefault() ?? "none")</value></set-header>
      <set-variable name="amount" value="@(int.Parse(context.Request.Url.Query.GetValueOrDefault(&quot;amount&quot;, &quot;0&quot;)))"/>
      <choose>
        <when condition="@(context.Request.Headers.GetValueOrDefault(&quot;x-deny&quot;,&quot;&quot;) == &quot;1&quot;)"><return-response><set-status code="403"/><set-body>denied by policy</set-body></return-response></when>
        <when condition="@(context.Variables.GetValueOrDefault(&quot;amount&quot;, 0) > 500 &amp;&amp; !context.Request.Headers.ContainsKey(&quot;x-manager&quot;))"><return-response><set-status code="403"/><set-header name="x-reason" exists-action="override"><value>manager approval needed</value></set-header><set-body>@("amount " + context.Variables["amount"] + " needs a manager")</set-body></return-response></when>
        <otherwise><set-header name="x-checked" exists-action="override"><value>@(context.Request.Method + ":" + context.Operation.Id)</value></set-header></otherwise>
      </choose>
      </inbound><backend><base/></backend><outbound><base/><set-header name="x-served-by" exists-action="override"><value>@("apim-" + context.Deployment.ServiceName)</value></set-header></outbound></policies>'''
    a.api_policy.create_or_update(RG, "facilities-apim", "tools", "policy", {"value": api_pol, "format": "xml"})
    a.api_operation_policy.create_or_update(RG, "facilities-apim", "tools", "admin_only", "policy", {"format": "xml", "value":
        '<policies><inbound><base/><ip-filter action="allow"><address>10.1.2.3</address><address-range from="192.168.0.1" to="192.168.0.20"/></ip-filter></inbound><backend><base/></backend><outbound><base/></outbound></policies>'})
    a.api_operation_policy.create_or_update(RG, "facilities-apim", "tools", "get_policy", "policy", {"format": "xml", "value":
        '<policies><inbound><base/><return-response><set-status code="200"/><set-header name="content-type" exists-action="override"><value>application/json</value></set-header><set-body>@{ var r = context.Request.Headers.GetValueOrDefault("x-caller", "?"); return new Newtonsoft.Json.Linq.JObject().ToString(); }</set-body></return-response></inbound><backend><base/></backend><outbound><base/></outbound></policies>'})
    # get_policy: a statement-block body that does not use unsupported types is checked separately below
    a.api_operation_policy.create_or_update(RG, "facilities-apim", "tools", "get_policy", "policy", {"format": "xml", "value":
        '<policies><inbound><base/><return-response><set-status code="200"/><set-header name="content-type" exists-action="override"><value>application/json</value></set-header><set-body>@{ var who = context.Request.Headers.GetValueOrDefault("Authorization", "").Split(\' \').Last().AsJwt()?.Subject ?? "anon"; if (who == "anon") { return "{}"; } return "{\\"policy\\":\\"approvals above 500 need a manager\\"}"; }</set-body></return-response></inbound><backend><base/></backend><outbound><base/></outbound></policies>'})
    GW = f"{http}/azure-data/apim/facilities-apim/tools"
    K = {"Ocp-Apim-Subscription-Key": key}
    B = lambda t: {"Authorization": "Bearer " + t}  # noqa: E731

    r = requests.get(GW + "/assets/a1", headers=B(tok)); check("no subscription key -> 401", r.status_code == 401 and "subscription key" in r.text, (r.status_code, r.text))
    r = requests.get(GW + "/assets/a1", headers=K); check("key, no token -> 401 (validate-jwt)", r.status_code == 401, (r.status_code, r.text))
    SEEN.clear()
    r = requests.get(GW + "/assets/a1", headers={**K, **B(tok)})
    check("Entra token validated by APIM validate-jwt (openid-config -> simulator JWKS) -> 200", r.status_code == 200 and "x-vyomi-apim-warning" not in r.headers, (r.status_code, r.text, dict(r.headers)))
    check("expression set-header: caller azp from AsJwt() claims reached the backend", SEEN and SEEN[-1]["headers"].get("x-caller") == good_id and SEEN[-1]["headers"].get("x-checked") == "GET:lookup_asset", SEEN[-1:] if SEEN else None)
    check("outbound expression header", r.headers.get("x-served-by") == "apim-facilities-apim", dict(r.headers))
    check("choose/when is evaluated, not skipped", "choose" not in r.headers.get("x-vyomi-apim-skipped-policies", ""), r.headers.get("x-vyomi-apim-skipped-policies"))
    r = requests.get(GW + "/assets/a1", headers={**K, **B(tok_norole)}); check("token without the required role -> 401", r.status_code == 401, (r.status_code, r.text))
    r = requests.get(GW + "/assets/a1", headers={**K, **B(tok_other_aud)}); check("token for another audience -> 401", r.status_code == 401, (r.status_code, r.text))
    r = requests.get(GW + "/assets/a1", headers={**K, **B(v1)}); check("v1 token against a v2 openid-config -> 401 (issuer mismatch)", r.status_code == 401, (r.status_code, r.text))
    t2 = tok[:-6] + ("AAAAAA" if not tok.endswith("AAAAAA") else "BBBBBB")
    r = requests.get(GW + "/assets/a1", headers={**K, **B(t2)}); check("tampered token -> 401 (signature)", r.status_code == 401, (r.status_code, r.text))
    r = requests.get(GW + "/assets/a1", headers={**K, **B(tok), "x-deny": "1"}); check("choose/when header expression -> 403 denied", r.status_code == 403 and "denied" in r.text, (r.status_code, r.text))
    r = requests.get(GW + "/assets/a1?amount=900", headers={**K, **B(tok)}); check("set-variable + expression in choose -> 403 with computed body", r.status_code == 403 and "amount 900 needs a manager" in r.text and r.headers.get("x-reason") == "manager approval needed", (r.status_code, r.text))
    r = requests.get(GW + "/assets/a1?amount=900", headers={**K, **B(tok), "x-manager": "1"}); check("same call with the manager header -> 200", r.status_code == 200, (r.status_code, r.text))
    r = requests.get(GW + "/policy", headers={**K, **B(tok)}); check("@{ } statement block: return-response body computed from the JWT subject", r.status_code == 200 and "approvals above 500" in r.text, (r.status_code, r.text))
    r = requests.get(GW + "/admin", headers={**K, **B(tok)}); check("ip-filter allow: default client 127.0.0.1 -> 403", r.status_code == 403 and "IP address is not allowed" in r.text, (r.status_code, r.text))
    r = requests.get(GW + "/admin", headers={**K, **B(tok), "X-Forwarded-For": "192.168.0.7"}); check("ip-filter allow: address-range member -> 200", r.status_code == 200, (r.status_code, r.text))
    r = requests.get(GW + "/admin", headers={**K, **B(tok), "X-Forwarded-For": "10.1.2.3"}); check("ip-filter allow: single address -> 200", r.status_code == 200, (r.status_code, r.text))
    SEEN.clear()
    r = requests.post(GW + "/work-orders", headers={**K, **B(tok), "content-type": "application/json"}, json={"asset": "a1"})
    check("POST through the gateway reaches the backend with the body", r.status_code == 200 and SEEN and SEEN[-1]["body"] == '{"asset": "a1"}' and SEEN[-1]["path"] == "/work-orders", SEEN[-1:])

    # ---- skipped policies are reported, never silently passed
    a.api_operation_policy.create_or_update(RG, "facilities-apim", "tools", "lookup_asset", "policy", {"format": "xml", "value":
        '<policies><inbound><base/><cache-lookup vary-by-developer="false" vary-by-developer-groups="false"/><rewrite-uri template="/v2/assets/{id}"/><set-header name="x-op" exists-action="override"><value>op-level</value></set-header></inbound><backend><base/></backend><outbound><base/></outbound></policies>'})
    SEEN.clear()
    r = requests.get(GW + "/assets/a9", headers={**K, **B(tok)})
    check("rewrite-uri + set-header honoured; cache-lookup listed as skipped", r.status_code == 200 and SEEN[-1]["path"] == "/v2/assets/a9" and SEEN[-1]["headers"].get("x-op") == "op-level"
          and r.headers.get("x-vyomi-apim-skipped-policies") == "cache-lookup", (SEEN[-1:], dict(r.headers)))
    a.api_operation_policy.delete(RG, "facilities-apim", "tools", "lookup_asset", "policy", "*")

    # ---- MCP API type: tools from the REST API's operations, served through the gateway, driven by the official mcp client
    a.api.begin_create_or_update(RG, "facilities-apim", "facilities-mcp", {"display_name": "facilities-mcp", "path": "mcp", "protocols": ["https"], "subscription_required": True,
                                 "api_type": "mcp", "source_api_id": f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.ApiManagement/service/facilities-apim/apis/tools"}).result()
    a.api_policy.create_or_update(RG, "facilities-apim", "facilities-mcp", "policy", {"format": "xml", "value":
        f'<policies><inbound><base/><validate-azure-ad-token tenant-id="{TENANT}"><audiences><audience>api://facilities-api</audience></audiences><required-claims><claim name="roles" match="any"><value>Facilities.Invoke</value></claim></required-claims></validate-azure-ad-token></inbound><backend><base/></backend><outbound><base/></outbound></policies>'})
    MCP = f"{http}/azure-data/apim/facilities-apim/mcp"
    r = requests.post(MCP, headers=K, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}); check("MCP endpoint without token -> 401 (validate-azure-ad-token)", r.status_code == 401, (r.status_code, r.text))

    async def mcp_flow():
        from mcp import ClientSession
        hdrs = {**K, **B(tok)}
        try:     # mcp 2.x
            from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
            cm = streamable_http_client(MCP, http_client=create_mcp_http_client(headers=hdrs))
        except ImportError:   # mcp 1.x
            from mcp.client.streamable_http import streamablehttp_client
            cm = streamablehttp_client(MCP, headers=hdrs)
        async with cm as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                init = await s.initialize()
                tools = await s.list_tools()
                SEEN.clear()
                res = await s.call_tool("lookup_asset", {"id": "a42"})
                res2 = await s.call_tool("create_work_order", {"body": {"asset": "a42", "priority": 2}})
                try:
                    bad = await s.call_tool("nope", {})
                except Exception as e:  # noqa: BLE001
                    bad = e
                return init, tools, res, res2, bad
    init, tools, res, res2, bad = asyncio.run(mcp_flow())
    names = sorted(t.name for t in tools.tools)
    check("mcp client initialize + tools/list = the REST API's operations", names == ["admin_only", "create_work_order", "get_policy", "lookup_asset"] and (getattr(init, "server_info", None) or getattr(init, "serverInfo")).name == "facilities-mcp", (names, init))
    ls = next(t for t in tools.tools if t.name == "lookup_asset")
    check("tool inputSchema derived from the url template", _sch(ls)["required"] == ["id"] and "id" in _sch(ls)["properties"] and "body" in _sch(next(t for t in tools.tools if t.name == "create_work_order"))["properties"], _sch(ls))
    check("tools/call lookup_asset executes the source operation (policies + backend)", not _err(res) and json.loads(res.content[0].text)["path"] == "/assets/a42" and any(x["path"] == "/assets/a42" and x["headers"].get("x-caller") == good_id for x in SEEN), (res, SEEN))
    check("tools/call create_work_order forwards the JSON body", not _err(res2) and any(x["method"] == "POST" and json.loads(x["body"]) == {"asset": "a42", "priority": 2} for x in SEEN), (res2, SEEN))
    check("unknown tool -> JSON-RPC error", ("Unknown tool" in str(bad)) or _err(bad), bad)
    r = requests.post(MCP, headers={**K, **B(tok_norole)}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}); check("MCP endpoint: token without the role -> 401", r.status_code == 401, (r.status_code, r.text))
    print(f"RESULT fails={_E.fails}", flush=True)
    os._exit(1 if _E.fails else 0)


if __name__ == "__main__":
    main()
