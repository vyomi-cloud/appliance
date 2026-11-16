"""AgentCore gateway hardening through the REAL boto3 clients + plain HTTP: CUSTOM_JWT really validated (RS256 signature against the issuer's JWKS,
issuer, expiry, audience / client), openApiSchema + mcpServer targets callable, API-key and OAuth2 client-credentials credential providers,
and MCP / A2A runtime protocols.   Run: PYTHONPATH=. python tests/conformance/test_agentcore_gateway_targets.py
"""
import base64
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jwt_issuer import Issuer  # noqa: E402
from llm_fakes import FakeLLM  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:700]}")


UP_LOG = []


class Upstream(BaseHTTPRequestHandler):
    """A fake business API (key / bearer protected), its OAuth token endpoint and a tiny MCP server."""
    def log_message(self, *a):
        pass

    def _send(self, code, doc, ctype="application/json"):
        b = json.dumps(doc).encode()
        self.send_response(code); self.send_header("content-type", ctype); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        UP_LOG.append(("GET", self.path, dict(self.headers)))
        if self.path.startswith("/assets/"):
            if self.headers.get("X-Api-Key") != "s3cr3t-key":
                return self._send(401, {"error": "bad key"})
            return self._send(200, {"id": self.path.split("/")[2].split("?")[0], "status": "ok", "q": self.path.partition("?")[2]})
        if self.path.startswith("/secure/"):
            if self.headers.get("Authorization") != "Bearer tok-123":
                return self._send(401, {"error": "bad token"})
            return self._send(200, {"secure": True})
        self._send(404, {"error": "nf"})

    def do_POST(self):
        raw = self._body()
        UP_LOG.append(("POST", self.path, dict(self.headers)))
        if self.path == "/token":
            auth = self.headers.get("Authorization", "")
            form = dict(p.split("=") for p in raw.decode().split("&"))
            if auth != "Basic " + base64.b64encode(b"cid:csecret").decode() or form.get("grant_type") != "client_credentials":
                return self._send(401, {"error": "invalid_client"})
            return self._send(200, {"access_token": "tok-123", "token_type": "Bearer", "expires_in": 3600, "scope": form.get("scope", "")})
        if self.path == "/orders":
            return self._send(201, {"orderId": "O-77", "item": json.loads(raw)["item"]})
        if self.path == "/mcp":
            req = json.loads(raw)
            if self.headers.get("Authorization") != "Bearer tok-123":
                return self._send(401, {"error": "bad token"})
            m = req.get("method")
            if m == "initialize":
                return self._send(200, {"jsonrpc": "2.0", "id": req["id"], "result": {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "up", "version": "1"}}})
            if m == "tools/list":
                return self._send(200, {"jsonrpc": "2.0", "id": req["id"], "result": {"tools": [{"name": "echo", "description": "Echo text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]}})
            if m == "tools/call":
                return self._send(200, {"jsonrpc": "2.0", "id": req["id"], "result": {"isError": False, "content": [{"type": "text", "text": "echo:" + req["params"]["arguments"]["text"]}]}})
            self.send_response(202); self.send_header("content-length", "0"); self.end_headers(); return
        self._send(404, {"error": "nf"})


SPEC = {"openapi": "3.0.0", "info": {"title": "assets", "version": "1"}, "servers": [{"url": ""}],
        "paths": {"/assets/{assetId}": {"get": {"operationId": "getAsset", "summary": "Fetch an asset", "parameters": [
                      {"name": "assetId", "in": "path", "required": True, "schema": {"type": "string"}}, {"name": "verbose", "in": "query", "schema": {"type": "string"}}]}},
                  "/secure/ping": {"get": {"operationId": "securePing", "summary": "Bearer protected"}},
                  "/orders": {"post": {"operationId": "createOrder", "summary": "Create an order", "requestBody": {"required": True, "content": {"application/json": {
                      "schema": {"$ref": "#/components/schemas/Order"}}}}}}},
        "components": {"schemas": {"Order": {"type": "object", "required": ["item"], "properties": {"item": {"type": "string"}}}}}}


def main():
    import boto3
    import uvicorn
    from botocore.config import Config
    from fastapi import FastAPI, Request
    from core import llm_core as llm
    from core.aws_wire_router import AwsWireRouter
    from core import wire_ingress
    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    UP = f"http://127.0.0.1:{up.server_address[1]}"
    fake = FakeLLM(handler=lambda b: {"content": "A2A-ANSWER: " + b["messages"][-1]["content"][:60]}, delay=0.0)
    llm.set_backend(None)
    llm._state.update(endpoint=fake.url, no_rf=False, no_native=False)
    llm._state["embed_fn"] = lambda texts: [llm.hash_embed(t) for t in texts]
    os.environ.pop("VYOMI_LLM_DISABLE", None)
    router = AwsWireRouter()
    app = FastAPI()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def any_(p: str, request: Request):
        return await wire_ingress.serve(router, request)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    kw = dict(region_name="us-east-1", endpoint_url=url, aws_access_key_id="x", aws_secret_access_key="y", config=Config(retries={"max_attempts": 1}))
    ctl, dp = boto3.client("bedrock-agentcore-control", **kw), boto3.client("bedrock-agentcore", **kw)
    ROLE = "arn:aws:iam::123456789012:role/r"
    ISS, OTHER = Issuer("k1"), Issuer("k1")   # OTHER has the same kid but a different key

    def mcp(gid, method, params=None, token=None, raw_auth=None):
        h = {"content-type": "application/json", "authorization": "AWS4-HMAC-SHA256 Credential=T/20261116/us-east-1/bedrock-agentcore/aws4_request, SignedHeaders=host, Signature=0"}
        if token:
            h["x-amzn-bedrock-agentcore-runtime-custom-authorization"] = "Bearer " + token
        req = urllib.request.Request(f"{url}/gateways/{gid}/mcp", method="POST", headers=h, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode())
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    print("== CUSTOM_JWT inbound validation")
    lam_spec = {"mcp": {"lambda": {"lambdaArn": "arn:aws:lambda:us-east-1:123456789012:function:nofn", "toolSchema": {"inlinePayload": [{"name": "t", "description": "d", "inputSchema": {"type": "object"}}]}}}}
    gw = ctl.create_gateway(name="jwt-gw", roleArn=ROLE, authorizerType="CUSTOM_JWT", authorizerConfiguration={"customJWTAuthorizer": {
        "discoveryUrl": ISS.discovery_url, "allowedClients": ["app-client"], "allowedAudience": ["facilities"]}})
    gid = gw["gatewayId"]
    ctl.create_gateway_target(gatewayIdentifier=gid, name="lt", targetConfiguration=lam_spec)
    time.sleep(1.2)
    good = ISS.mint("alice", extra={"aud": "facilities"})
    st, r = mcp(gid, "tools/list", token=good)
    check("valid RS256 token -> tools/list 200", st == 200 and r["result"]["tools"][0]["name"] == "lt___t", (st, r))
    st, r = mcp(gid, "tools/list")
    check("no token -> 401", st == 401, (st, r))
    st, r = mcp(gid, "tools/list", token=good[:-6] + "AAAAAA")
    check("tampered signature -> 401", st == 401, (st, r))
    st, r = mcp(gid, "tools/list", token=OTHER.mint("evil", extra={"aud": "facilities"}, iss=ISS.issuer))
    check("token signed by a different key (same kid) -> 401", st == 401, (st, r))
    st, r = mcp(gid, "tools/list", token=ISS.mint("a", exp_in=-10, extra={"aud": "facilities"}))
    check("expired token -> 401", st == 401, (st, r))
    st, r = mcp(gid, "tools/list", token=ISS.mint("a", iss="https://evil.example/pool", extra={"aud": "facilities"}))
    check("wrong issuer -> 401", st == 401, (st, r))
    st, r = mcp(gid, "tools/list", token=ISS.mint("a", extra={"aud": "other"}))
    check("audience not allowed -> 403", st == 403, (st, r))
    st, r = mcp(gid, "tools/list", token=ISS.mint("a", extra={"aud": "facilities", "client_id": "rogue"}))
    check("client not allowed -> 403", st == 403, (st, r))
    st, r = mcp(gid, "tools/list", token="a.b.c")
    check("garbage token -> 401", st == 401, (st, r))

    print("== CUSTOM_JWT against this simulator's own Cognito pool (identity lane JWKS, no network)")
    try:
        idp = boto3.client("cognito-idp", **kw)
        pool = idp.create_user_pool(PoolName="facilities-users")["UserPool"]
        cl = idp.create_user_pool_client(UserPoolId=pool["Id"], ClientName="web", ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"])["UserPoolClient"]
        idp.admin_create_user(UserPoolId=pool["Id"], Username="maria", MessageAction="SUPPRESS")
        idp.admin_set_user_password(UserPoolId=pool["Id"], Username="maria", Password="Fac!lities9", Permanent=True)
        au = idp.initiate_auth(ClientId=cl["ClientId"], AuthFlow="USER_PASSWORD_AUTH", AuthParameters={"USERNAME": "maria", "PASSWORD": "Fac!lities9"})["AuthenticationResult"]
        cg = ctl.create_gateway(name="cognito-gw", roleArn=ROLE, authorizerType="CUSTOM_JWT", authorizerConfiguration={"customJWTAuthorizer": {
            "discoveryUrl": f"https://cognito-idp.us-east-1.amazonaws.com/{pool['Id']}/.well-known/openid-configuration", "allowedClients": [cl["ClientId"]]}})
        ctl.create_gateway_target(gatewayIdentifier=cg["gatewayId"], name="lt", targetConfiguration=lam_spec)
        time.sleep(1.2)
        st, r = mcp(cg["gatewayId"], "tools/list", token=au["AccessToken"])
        check("real Cognito access token admitted", st == 200 and r["result"]["tools"][0]["name"] == "lt___t", (st, r))
        st, r = mcp(cg["gatewayId"], "tools/list", token=ISS.mint("x"))
        check("token from another issuer rejected for the Cognito gateway", st == 401, (st, r))
        st, r = mcp(cg["gatewayId"], "tools/list", token=au["AccessToken"][:-8] + "AAAAAAAA")
        check("tampered Cognito token rejected", st == 401, (st, r))
    except Exception as e:  # noqa: BLE001
        check("Cognito-lane gateway auth", False, repr(e))

    print("== Credential providers (control plane + data plane)")
    ak = ctl.create_api_key_credential_provider(name="assets-key", apiKey="s3cr3t-key")
    check("CreateApiKeyCredentialProvider -> ARN, key never echoed", ak["credentialProviderArn"].endswith("apikeycredentialprovider/assets-key") and "apiKey" not in ak, ak)
    check("GetApiKeyCredentialProvider / List", ctl.get_api_key_credential_provider(name="assets-key")["name"] == "assets-key" and len(ctl.list_api_key_credential_providers()["credentialProviders"]) == 1)
    oa = ctl.create_oauth2_credential_provider(name="up-oauth", credentialProviderVendor="CustomOauth2", oauth2ProviderConfigInput={"customOauth2ProviderConfig": {
        "oauthDiscovery": {"authorizationServerMetadata": {"issuer": UP, "authorizationEndpoint": UP + "/authorize", "tokenEndpoint": UP + "/token", "responseTypes": ["code"]}},
        "clientId": "cid", "clientSecret": "csecret"}})
    check("CreateOauth2CredentialProvider -> ARN + callbackUrl, secret not echoed", oa["credentialProviderArn"].endswith("oauth2credentialprovider/up-oauth") and oa["callbackUrl"] and "csecret" not in json.dumps(oa), oa)
    try:
        ctl.create_api_key_credential_provider(name="assets-key", apiKey="x"); check("duplicate provider -> ConflictException", False)
    except ctl.exceptions.ConflictException:
        check("duplicate provider -> ConflictException", True)
    check("GetResourceApiKey (data plane)", dp.get_resource_api_key(workloadIdentityToken="wit", resourceCredentialProviderName="assets-key")["apiKey"] == "s3cr3t-key")
    check("GetResourceOauth2Token M2M (data plane) does a real client-credentials exchange",
          dp.get_resource_oauth2_token(workloadIdentityToken="wit", resourceCredentialProviderName="up-oauth", scopes=["assets.read"], oauth2Flow="M2M")["accessToken"] == "tok-123")
    try:
        ctl.create_oauth2_credential_provider(name="bad", credentialProviderVendor="CustomOauth2", oauth2ProviderConfigInput={"customOauth2ProviderConfig": {"oauthDiscovery": {"discoveryUrl": "x"}, "clientId": "a", "clientSecret": ""}}); check("incomplete OAuth provider -> ValidationException", False)
    except ctl.exceptions.ValidationException:
        check("incomplete OAuth provider -> ValidationException", True)

    print("== openApiSchema targets are callable")
    gw2 = ctl.create_gateway(name="api-gw", roleArn=ROLE, authorizerType="CUSTOM_JWT", authorizerConfiguration={"customJWTAuthorizer": {"discoveryUrl": ISS.discovery_url}})
    g2 = gw2["gatewayId"]
    spec = json.loads(json.dumps(SPEC)); spec["servers"][0]["url"] = UP
    key_cfg = [{"credentialProviderType": "API_KEY", "credentialProvider": {"apiKeyCredentialProvider": {"providerArn": ak["credentialProviderArn"], "credentialParameterName": "X-Api-Key", "credentialLocation": "HEADER"}}}]
    oauth_cfg = [{"credentialProviderType": "OAUTH", "credentialProvider": {"oauthCredentialProvider": {"providerArn": oa["credentialProviderArn"], "scopes": ["assets.read"], "grantType": "CLIENT_CREDENTIALS"}}}]
    try:
        ctl.create_gateway_target(gatewayIdentifier=g2, name="bad", targetConfiguration={"mcp": {"openApiSchema": {"inlinePayload": "{not json"}}}, credentialProviderConfigurations=key_cfg)
        check("unparsable OpenAPI -> ValidationException", False)
    except ctl.exceptions.ValidationException:
        check("unparsable OpenAPI -> ValidationException", True)
    try:
        ctl.create_gateway_target(gatewayIdentifier=g2, name="bad2", targetConfiguration={"mcp": {"openApiSchema": {"inlinePayload": json.dumps(spec)}}}, credentialProviderConfigurations=[
            {"credentialProviderType": "API_KEY", "credentialProvider": {"apiKeyCredentialProvider": {"providerArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:token-vault/default/apikeycredentialprovider/nope"}}}])
        check("unknown credential provider -> ValidationException", False)
    except ctl.exceptions.ValidationException:
        check("unknown credential provider -> ValidationException", True)
    ctl.create_gateway_target(gatewayIdentifier=g2, name="assets", targetConfiguration={"mcp": {"openApiSchema": {"inlinePayload": json.dumps(spec)}}}, credentialProviderConfigurations=key_cfg)
    spec2 = json.loads(json.dumps(spec)); spec2["paths"] = {k: v for k, v in spec2["paths"].items() if k == "/secure/ping"}
    ctl.create_gateway_target(gatewayIdentifier=g2, name="sec", targetConfiguration={"mcp": {"openApiSchema": {"inlinePayload": json.dumps(spec2)}}}, credentialProviderConfigurations=oauth_cfg)
    time.sleep(1.2)
    tok = ISS.mint("alice")
    st, r = mcp(g2, "tools/list", token=tok)
    names = sorted(t["name"] for t in r["result"]["tools"])
    check("tools/list exposes operationIds as <target>___<op>", names == ["assets___createOrder", "assets___getAsset", "assets___securePing", "sec___securePing"], names)
    sch = next(t for t in r["result"]["tools"] if t["name"] == "assets___getAsset")["inputSchema"]
    check("inputSchema from path/query parameters (assetId required)", sch["required"] == ["assetId"] and "verbose" in sch["properties"], sch)
    st, r = mcp(g2, "tools/call", {"name": "assets___getAsset", "arguments": {"assetId": "A 1", "verbose": "yes"}}, token=tok)
    check("getAsset performs the HTTP GET with the API-key header + path/query", r["result"]["isError"] is False and r["result"]["structuredContent"] == {"id": "A%201", "status": "ok", "q": "verbose=yes"}, r)
    st, r = mcp(g2, "tools/call", {"name": "assets___createOrder", "arguments": {"item": "pump"}}, token=tok)
    check("createOrder POSTs the JSON body ($ref schema flattened)", r["result"]["structuredContent"] == {"orderId": "O-77", "item": "pump"}, r)
    st, r = mcp(g2, "tools/call", {"name": "sec___securePing", "arguments": {}}, token=tok)
    check("OAuth client-credentials provider: gateway fetched a token and sent Bearer", r["result"]["isError"] is False and r["result"]["structuredContent"] == {"secure": True}, r)
    st, r = mcp(g2, "tools/call", {"name": "assets___securePing", "arguments": {}}, token=tok)
    check("upstream 401 (API key target hitting a bearer endpoint) -> isError with HTTP status", r["result"]["isError"] is True and "HTTP 401" in r["result"]["content"][0]["text"], r)
    ctl.update_api_key_credential_provider(name="assets-key", apiKey="rotated")
    st, r = mcp(g2, "tools/call", {"name": "assets___getAsset", "arguments": {"assetId": "A"}}, token=tok)
    check("rotated API key is used (upstream now rejects the old secret)", r["result"]["isError"] is True and "HTTP 401" in r["result"]["content"][0]["text"], r)

    print("== mcpServer target proxies a real MCP server")
    ctl.create_gateway_target(gatewayIdentifier=g2, name="upmcp", targetConfiguration={"mcp": {"mcpServer": {"endpoint": UP + "/mcp"}}}, credentialProviderConfigurations=oauth_cfg)
    time.sleep(1.2)
    st, r = mcp(g2, "tools/list", token=tok)
    check("upstream MCP tools appear in the gateway catalog", "upmcp___echo" in [t["name"] for t in r["result"]["tools"]], r)
    st, r = mcp(g2, "tools/call", {"name": "upmcp___echo", "arguments": {"text": "hi"}}, token=tok)
    check("tools/call is proxied (JSON-RPC to upstream, OAuth bearer attached)", r["result"]["content"][0]["text"] == "echo:hi", r)

    print("== Runtime protocol variants")
    spec_rt = {"instructions": "Answer briefly.", "tools": [{"name": "add_tax", "type": "template", "template": "total={total}", "description": "Format total",
                                                              "parameters": {"type": "object", "properties": {"total": {"type": "string"}}}}]}
    art = {"containerConfiguration": {"containerUri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/x:1"}}
    mk = lambda n, proto: ctl.create_agent_runtime(agentRuntimeName=n, agentRuntimeArtifact=art, roleArn=ROLE, networkConfiguration={"networkMode": "PUBLIC"},  # noqa: E731
                                                  protocolConfiguration={"serverProtocol": proto}, environmentVariables={"VYOMI_AGENT_SPEC": json.dumps(spec_rt)})
    rm, ra = mk("mcp_rt", "MCP"), mk("a2a_rt", "A2A")
    time.sleep(1.2)

    def rpc(rt, method, params=None, sid=None, rid=1):
        out = dp.invoke_agent_runtime(agentRuntimeArn=rt["agentRuntimeArn"], runtimeSessionId=sid or "s" * 33, payload=json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}).encode())
        return json.loads(out["response"].read())
    check("MCP runtime: initialize", rpc(rm, "initialize")["result"]["serverInfo"]["name"] == "mcp_rt")
    check("MCP runtime: tools/list = spec tools", [t["name"] for t in rpc(rm, "tools/list")["result"]["tools"]] == ["add_tax"])
    check("MCP runtime: tools/call executes the tool", rpc(rm, "tools/call", {"name": "add_tax", "arguments": {"total": "9"}})["result"]["content"][0]["text"] == "total=9")
    check("MCP runtime: unknown tool -> JSON-RPC error", rpc(rm, "tools/call", {"name": "nope"})["error"]["code"] == -32602)
    msg = {"kind": "message", "role": "user", "messageId": "m1", "parts": [{"kind": "text", "text": "hello agent"}]}
    r = rpc(ra, "message/send", {"message": msg})["result"]
    check("A2A runtime: message/send -> completed Task with the agent answer", r["kind"] == "task" and r["status"]["state"] == "completed" and "A2A-ANSWER" in r["artifacts"][0]["parts"][0]["text"], r)
    check("A2A runtime: tasks/get returns the task", rpc(ra, "tasks/get", {"id": r["id"]})["result"]["id"] == r["id"])
    check("A2A runtime: agent card", rpc(ra, "agent/getAuthenticatedExtendedCard")["result"]["skills"][0]["id"] == "add_tax")
    check("A2A runtime: bad method -> -32601", rpc(ra, "bogus")["error"]["code"] == -32601)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
