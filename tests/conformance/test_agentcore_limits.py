"""AgentCore round-8 limits closed, through the REAL boto3 clients + plain HTTP:
  * Nano egress: OpenAPI / mcpServer targets, OAuth token exchange and JWKS discovery reach the network through the awaited egress bridge
    (llm_core.set_async_http, the same hook wasm/gw-bridge.js feeds on Nano), with the Nano code path forced on;
  * smithyModel targets are callable (awsJson1_0 and restJson1 operations executed against the simulator's own wire);
  * AWS_IAM gateways verify the SigV4 signature of an IAM access key (wrong secret -> 403; ambient dev keys flagged unverified; strict mode rejects them);
  * runtime inbound JWT is verified; the A2A agent card is served at /.well-known/agent-card.json; message/stream emits SSE task events (per token since round 9: test_agentcore_auth_limits.py).
Run: PYTHONPATH=. python tests/conformance/test_agentcore_limits.py
"""
import asyncio
import base64
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jwt_issuer import Issuer  # noqa: E402
from llm_fakes import FakeLLM  # noqa: E402
from test_agentcore_gateway_targets import SPEC, UP_LOG, Upstream  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {str(extra)[:700]}")


DDB = {"smithy": "2.0", "shapes": {
    "com.amazonaws.dynamodb#DynamoDB_20120810": {"type": "service", "version": "2012-08-10", "operations": [{"target": "com.amazonaws.dynamodb#ListTables"}, {"target": "com.amazonaws.dynamodb#DescribeTable"}],
        "traits": {"aws.api#service": {"sdkId": "DynamoDB", "arnNamespace": "dynamodb"}, "aws.auth#sigv4": {"name": "dynamodb"}, "aws.protocols#awsJson1_0": {}}},
    "com.amazonaws.dynamodb#ListTables": {"type": "operation", "input": {"target": "com.amazonaws.dynamodb#ListTablesInput"}, "traits": {"smithy.api#documentation": "List table names"}},
    "com.amazonaws.dynamodb#ListTablesInput": {"type": "structure", "members": {"Limit": {"target": "smithy.api#Integer"}}},
    "com.amazonaws.dynamodb#DescribeTable": {"type": "operation", "input": {"target": "com.amazonaws.dynamodb#DescribeTableInput"}},
    "com.amazonaws.dynamodb#DescribeTableInput": {"type": "structure", "members": {"TableName": {"target": "smithy.api#String", "traits": {"smithy.api#required": {}}}}}}}
LAM = {"smithy": "2.0", "shapes": {
    "com.amazonaws.lambda#AWSGirApiService": {"type": "service", "version": "2015-03-31", "operations": [{"target": "com.amazonaws.lambda#ListFunctions"}, {"target": "com.amazonaws.lambda#GetFunction"}],
        "traits": {"aws.api#service": {"arnNamespace": "lambda"}, "aws.protocols#restJson1": {}}},
    "com.amazonaws.lambda#ListFunctions": {"type": "operation", "input": {"target": "com.amazonaws.lambda#ListFunctionsRequest"}, "traits": {"smithy.api#http": {"method": "GET", "uri": "/2015-03-31/functions/", "code": 200}}},
    "com.amazonaws.lambda#ListFunctionsRequest": {"type": "structure", "members": {"MaxItems": {"target": "smithy.api#Integer", "traits": {"smithy.api#httpQuery": "MaxItems"}}}},
    "com.amazonaws.lambda#GetFunction": {"type": "operation", "input": {"target": "com.amazonaws.lambda#GetFunctionRequest"}, "traits": {"smithy.api#http": {"method": "GET", "uri": "/2015-03-31/functions/{FunctionName}", "code": 200}}},
    "com.amazonaws.lambda#GetFunctionRequest": {"type": "structure", "members": {"FunctionName": {"target": "smithy.api#String", "traits": {"smithy.api#httpLabel": {}, "smithy.api#required": {}}}}}}}
QUERY = {"smithy": "2.0", "shapes": {"x#Svc": {"type": "service", "operations": [{"target": "x#Op"}], "traits": {"aws.protocols#awsQuery": {}}}, "x#Op": {"type": "operation"}}}


def main():
    import boto3
    import uvicorn
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.config import Config
    from botocore.credentials import Credentials
    from fastapi import FastAPI, Request
    from core import agentcore_gateway_targets as gt
    from core import llm_core as llm
    from core import wire_ingress
    from core.aws_wire_router import AwsWireRouter
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
    kw = dict(region_name="us-east-1", endpoint_url=url, aws_access_key_id="test", aws_secret_access_key="test", config=Config(retries={"max_attempts": 1}))
    ctl, dp, ddb, iam = (boto3.client(n, **kw) for n in ("bedrock-agentcore-control", "bedrock-agentcore", "dynamodb", "iam"))
    ROLE = "arn:aws:iam::123456789012:role/r"
    ISS = Issuer("k1")

    def post(path, doc, headers=None, raw=False):
        req = urllib.request.Request(url + path, method="POST", headers={"content-type": "application/json", **(headers or {})}, data=json.dumps(doc).encode())
        try:
            with urllib.request.urlopen(req) as r:
                b = r.read()
                return r.status, (b if raw else json.loads(b or b"{}")), dict(r.headers)
        except urllib.error.HTTPError as e:
            b = e.read()
            return e.code, (b if raw else (json.loads(b) if b[:1] == b"{" else {})), dict(e.headers)

    def signed(path, doc, ak, sk):
        body = json.dumps(doc)
        r = AWSRequest(method="POST", url=url + path, data=body, headers={"Content-Type": "application/json"})
        SigV4Auth(Credentials(ak, sk), "bedrock-agentcore", "us-east-1").add_auth(r)
        return post(path, doc, dict(r.headers.items()))

    def mcp_iam(gid, method, params=None, ak="test", sk="test"):
        return signed(f"/gateways/{gid}/mcp", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, ak, sk)

    def mcp(gid, method, params=None, token=None):
        h = {"authorization": "Bearer " + token} if token else {}
        return post(f"/gateways/{gid}/mcp", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}, h)

    # ───────────────────────── smithyModel + AWS_IAM (SigV4 verified) ─────────────────────────
    print("== AWS_IAM gateway: SigV4 verified against IAM access keys")
    ddb.create_table(TableName="orders", KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}], AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
    iam.create_user(UserName="alice")
    k = iam.create_access_key(UserName="alice")["AccessKey"]
    gw = ctl.create_gateway(name="iam-gw", roleArn=ROLE, authorizerType="AWS_IAM")["gatewayId"]
    ctl.create_gateway_target(gatewayIdentifier=gw, name="ddb", targetConfiguration={"mcp": {"smithyModel": {"inlinePayload": json.dumps(DDB)}}}, credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}])
    ctl.create_gateway_target(gatewayIdentifier=gw, name="lam", targetConfiguration={"mcp": {"smithyModel": {"inlinePayload": json.dumps(LAM)}}}, credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}])
    time.sleep(1.2)
    st, r, _ = mcp_iam(gw, "tools/list", ak=k["AccessKeyId"], sk=k["SecretAccessKey"])
    names = sorted(t["name"] for t in r["result"]["tools"]) if st == 200 else r
    check("IAM key with the right secret -> signature verified, tools listed", st == 200 and names == ["ddb___DescribeTable", "ddb___ListTables", "lam___GetFunction", "lam___ListFunctions"], (st, r))
    st, r, _ = mcp_iam(gw, "tools/list", ak=k["AccessKeyId"], sk="wrong-secret-wrong-secret-wrong-secret!!")
    check("IAM key with a WRONG secret -> 403 signature mismatch", st == 403 and "signature" in json.dumps(r).lower(), (st, r))
    st, r, _ = post(f"/gateways/{gw}/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    check("unsigned request -> 403", st == 403, (st, r))
    st, r, _ = post(f"/gateways/{gw}/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {"authorization": "Bearer abc"})
    check("a Bearer header is no longer enough for AWS_IAM -> 403", st == 403, (st, r))
    st, r, _ = post(f"/gateways/{gw}/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {"authorization": "AWS4-HMAC-SHA256 Credential=T/20261116/us-east-1/bedrock-agentcore/aws4_request"})
    check("a malformed SigV4 header (no SignedHeaders / Signature) -> 403", st == 403, (st, r))
    st, r, _ = mcp_iam(gw, "tools/list")
    check("ambient dev credentials (key not in IAM) are admitted but unverified in default mode", st == 200, (st, r))
    os.environ["VYOMI_AGENTCORE_SIGV4_STRICT"] = "1"
    st, r, _ = mcp_iam(gw, "tools/list")
    check("strict mode rejects an access key IAM does not hold -> 403", st == 403, (st, r))
    st, r, _ = mcp_iam(gw, "tools/list", ak=k["AccessKeyId"], sk=k["SecretAccessKey"])
    check("strict mode still admits the verified IAM key", st == 200, (st, r))
    os.environ.pop("VYOMI_AGENTCORE_SIGV4_STRICT")

    print("== smithyModel targets are callable")
    A = dict(ak=k["AccessKeyId"], sk=k["SecretAccessKey"])
    st, r, _ = mcp_iam(gw, "tools/call", {"name": "ddb___ListTables", "arguments": {}}, **A)
    check("awsJson1_0: ListTables runs on the simulator's DynamoDB", st == 200 and not r["result"]["isError"] and r["result"]["structuredContent"]["TableNames"] == ["orders"], r)
    st, r, _ = mcp_iam(gw, "tools/call", {"name": "ddb___DescribeTable", "arguments": {"TableName": "orders"}}, **A)
    check("awsJson1_0: DescribeTable returns the real table", r["result"]["structuredContent"]["Table"]["TableName"] == "orders", r)
    st, r, _ = mcp_iam(gw, "tools/call", {"name": "ddb___DescribeTable", "arguments": {"TableName": "nope"}}, **A)
    check("modeled service error -> isError with the service's message", r["result"]["isError"] is True and "HTTP 400" in r["result"]["content"][0]["text"], r)
    boto3.client("lambda", **kw).create_function(FunctionName="hello", Runtime="python3.12", Role=ROLE, Handler="h.handler", Code={"ZipFile": b"PK\x05\x06" + b"\x00" * 18})
    st, r, _ = mcp_iam(gw, "tools/call", {"name": "lam___ListFunctions", "arguments": {"MaxItems": 5}}, **A)
    check("restJson1: ListFunctions (http trait, httpQuery)", [f["FunctionName"] for f in r["result"]["structuredContent"]["Functions"]] == ["hello"], r)
    st, r, _ = mcp_iam(gw, "tools/call", {"name": "lam___GetFunction", "arguments": {"FunctionName": "hello"}}, **A)
    check("restJson1: GetFunction (httpLabel)", r["result"]["structuredContent"]["Configuration"]["FunctionName"] == "hello", r)
    sch = next(t for t in mcp_iam(gw, "tools/list", **A)[1]["result"]["tools"] if t["name"] == "ddb___DescribeTable")["inputSchema"]
    check("tool inputSchema comes from the Smithy input structure (required member)", sch["required"] == ["TableName"] and sch["properties"]["TableName"]["type"] == "string", sch)
    try:
        ctl.create_gateway_target(gatewayIdentifier=gw, name="q", targetConfiguration={"mcp": {"smithyModel": {"inlinePayload": json.dumps(QUERY)}}}, credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}])
        check("unsupported protocol (awsQuery) rejected at create", False)
    except ctl.exceptions.ValidationException:
        check("unsupported protocol (awsQuery) rejected at create", True)

    # ───────────────────────── Nano egress (the Nano code path forced on, bridge = the awaited hook) ─────────────────────────
    print("== Nano egress: targets + OAuth + JWKS through the awaited bridge")
    calls = []

    async def bridge(req):   # what wasm/gw-bridge.js does in the browser: send the request out, answer {status, headers, body(b64)}
        calls.append((req["method"], req["url"]))

        def go():
            r = urllib.request.Request(req["url"], data=base64.b64decode(req["body"]) or None, method=req["method"], headers=req["headers"])
            try:
                with urllib.request.urlopen(r, timeout=5) as x:
                    return {"status": x.status, "headers": dict(x.headers), "body": base64.b64encode(x.read()).decode()}
            except urllib.error.HTTPError as e:
                return {"status": e.code, "headers": dict(e.headers), "body": base64.b64encode(e.read()).decode()}
        return await asyncio.get_running_loop().run_in_executor(None, go)

    gt._NANO = True
    gt._VERIFIER.clear(); gt._DISC.clear()
    ak = ctl.create_api_key_credential_provider(name="assets-key", apiKey="s3cr3t-key")
    oa = ctl.create_oauth2_credential_provider(name="up-oauth", credentialProviderVendor="CustomOauth2", oauth2ProviderConfigInput={"customOauth2ProviderConfig": {
        "oauthDiscovery": {"authorizationServerMetadata": {"issuer": UP, "authorizationEndpoint": UP + "/authorize", "tokenEndpoint": UP + "/token", "responseTypes": ["code"]}},
        "clientId": "cid", "clientSecret": "csecret"}})
    g2 = ctl.create_gateway(name="api-gw", roleArn=ROLE, authorizerType="CUSTOM_JWT", authorizerConfiguration={"customJWTAuthorizer": {"discoveryUrl": ISS.discovery_url}})["gatewayId"]
    spec = json.loads(json.dumps(SPEC)); spec["servers"][0]["url"] = UP
    key_cfg = [{"credentialProviderType": "API_KEY", "credentialProvider": {"apiKeyCredentialProvider": {"providerArn": ak["credentialProviderArn"], "credentialParameterName": "X-Api-Key", "credentialLocation": "HEADER"}}}]
    oauth_cfg = [{"credentialProviderType": "OAUTH", "credentialProvider": {"oauthCredentialProvider": {"providerArn": oa["credentialProviderArn"], "scopes": ["assets.read"], "grantType": "CLIENT_CREDENTIALS"}}}]
    ctl.create_gateway_target(gatewayIdentifier=g2, name="assets", targetConfiguration={"mcp": {"openApiSchema": {"inlinePayload": json.dumps(spec)}}}, credentialProviderConfigurations=key_cfg)
    ctl.create_gateway_target(gatewayIdentifier=g2, name="upmcp", targetConfiguration={"mcp": {"mcpServer": {"endpoint": UP + "/mcp"}}}, credentialProviderConfigurations=oauth_cfg)
    time.sleep(1.2)
    tok = ISS.mint("alice")
    llm.set_async_http(None)
    st, r, _ = mcp(g2, "tools/call", {"name": "assets___getAsset", "arguments": {"assetId": "A1"}}, token=tok)
    check("Nano with NO egress relay: JWKS cannot be fetched -> fails closed (401), never admitted", st == 401, (st, r))
    llm.set_async_http(bridge)
    calls.clear()
    st, r, _ = mcp(g2, "tools/call", {"name": "assets___getAsset", "arguments": {"assetId": "A1"}}, token=tok)
    check("Nano + relay: issuer discovery + JWKS fetched through the bridge, token verified, OpenAPI call made",
          st == 200 and r["result"]["isError"] is False and r["result"].get("structuredContent", {}).get("id") == "A1", (st, r))
    check("  the API-key header was applied to the bridged request", any(h.get("X-Api-Key") == "s3cr3t-key" for m, p, h in UP_LOG if p.startswith("/assets/A1")), UP_LOG[-3:])
    check("  every network hop went through the bridge (discovery, jwks, upstream)", any("openid-configuration" in u for _m, u in calls) and any("/assets/A1" in u for _m, u in calls), calls)
    st, r, _ = mcp(g2, "tools/call", {"name": "upmcp___echo", "arguments": {"text": "hi"}}, token=tok)
    check("Nano + relay: mcpServer proxy with OAuth token exchange (POST /token via the bridge)",
          st == 200 and r["result"]["content"][0]["text"] == "echo:hi" and any(u.endswith("/token") for _m, u in calls), (st, r, calls))
    st, r, _ = post("/identities/oauth2/token", {"workloadIdentityToken": "w", "resourceCredentialProviderName": "up-oauth", "scopes": ["x"], "oauth2Flow": "M2M"},
                    {"authorization": "AWS4-HMAC-SHA256 Credential=T/20261116/us-east-1/bedrock-agentcore/aws4_request, SignedHeaders=host, Signature=0"})
    check("Nano + relay: GetResourceOauth2Token exchanges against the token endpoint", st == 200 and r.get("accessToken") == "tok-123", (st, r))
    # agent-spec webhook tools use the same bridge on Nano
    import types
    from core import agent_spec_core as agc
    real_sys, agc.sys = agc.sys, types.SimpleNamespace(platform="emscripten")
    try:
        hook = {"name": "order", "type": "webhook", "url": UP + "/orders", "description": "create order"}
        got = asyncio.run(llm.arun(lambda: agc.exec_tool(hook, {"item": "valve"})))
        check("Nano: an agent-spec webhook tool POSTs through the bridge", got == ({"orderId": "O-77", "item": "valve"}, False), got)
        llm.set_async_http(None)
        res, err = agc.exec_tool(hook, {"item": "valve"})
        check("Nano without a relay: the webhook tool fails with the reason (tool error, no crash)", err is True and "egress relay" in json.dumps(res), res)
    finally:
        agc.sys = real_sys
    llm.set_async_http(None)
    gt._NANO = False
    gt._VERIFIER.clear(); gt._DISC.clear()

    # ───────────────────────── runtime inbound JWT + A2A card + streaming ─────────────────────────
    print("== Runtime: inbound JWT verified, A2A card at /.well-known/agent-card.json, message/stream")
    spec_rt = {"instructions": "Answer briefly.", "tools": [{"name": "add_tax", "type": "template", "template": "total={total}", "description": "Format total",
                                                              "parameters": {"type": "object", "properties": {"total": {"type": "string"}}}}]}
    art = {"containerConfiguration": {"containerUri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/x:1"}}
    auth = {"customJWTAuthorizer": {"discoveryUrl": ISS.discovery_url, "allowedAudience": ["agents"]}}
    ra = ctl.create_agent_runtime(agentRuntimeName="a2a_secure", agentRuntimeArtifact=art, roleArn=ROLE, networkConfiguration={"networkMode": "PUBLIC"},
                                  protocolConfiguration={"serverProtocol": "A2A"}, authorizerConfiguration=auth, environmentVariables={"VYOMI_AGENT_SPEC": json.dumps(spec_rt)})
    check("GetAgentRuntime echoes the authorizerConfiguration", ctl.get_agent_runtime(agentRuntimeId=ra["agentRuntimeId"]).get("authorizerConfiguration") == auth)
    time.sleep(1.2)
    from urllib.parse import quote
    base = f"/runtimes/{quote(ra['agentRuntimeArn'], safe='')}/invocations/"
    msg = {"kind": "message", "role": "user", "messageId": "m1", "parts": [{"kind": "text", "text": "hello agent"}]}
    rpc = lambda method, params, tok=None: post(base, {"jsonrpc": "2.0", "id": 7, "method": method, "params": params}, {"authorization": "Bearer " + tok} if tok else None, raw=True)  # noqa: E731
    st, b, _ = rpc("message/send", {"message": msg})
    check("runtime with a JWT authorizer: no token -> 401", st == 401, (st, b))
    st, b, _ = rpc("message/send", {"message": msg}, tok=ISS.mint("a", extra={"aud": "agents"})[:-6] + "AAAAAA")
    check("tampered token -> 401", st == 401, (st, b))
    st, b, _ = rpc("message/send", {"message": msg}, tok=ISS.mint("a", extra={"aud": "other"}))
    check("audience not allowed -> 403", st == 403, (st, b))
    good = ISS.mint("alice", extra={"aud": "agents"})
    st, b, _ = rpc("message/send", {"message": msg}, tok=good)
    check("valid token -> A2A message/send works", st == 200 and json.loads(b)["result"]["status"]["state"] == "completed", (st, b))
    card_req = urllib.request.Request(url + base + ".well-known/agent-card.json")
    try:
        urllib.request.urlopen(card_req); check("agent card is protected by the same inbound auth", False)
    except urllib.error.HTTPError as e:
        check("agent card is protected by the same inbound auth", e.code == 401, e.code)
    card_req = urllib.request.Request(url + base + ".well-known/agent-card.json", headers={"authorization": "Bearer " + good})
    with urllib.request.urlopen(card_req) as r:
        card = json.loads(r.read())
        check("GET .../invocations/.well-known/agent-card.json serves the card (200, JSON)", r.status == 200 and "json" in r.headers["content-type"], r.status)
    check("  card: name, skills from the agent spec, streaming capability, invocation url", card["name"] == "a2a_secure" and card["skills"][0]["id"] == "add_tax" and card["capabilities"]["streaming"] is True and card["url"].endswith("/invocations/"), card)
    st, raw, hdrs = rpc("message/stream", {"message": msg}, tok=good)
    evs = [json.loads(ln[5:]) for ln in raw.decode().split("\n\n") if ln.startswith("data:") for ln in [ln.strip()]]
    kinds = [e["result"]["kind"] for e in evs]
    check("message/stream answers text/event-stream", st == 200 and "text/event-stream" in hdrs.get("content-type", ""), hdrs)
    check("  task events in order: task, artifact-update chunk(s), final artifact-update, completed(final)", kinds[0] == "task" and kinds[-1] == "status-update" and set(kinds[1:-1]) == {"artifact-update"}
          and evs[-1]["result"]["final"] is True and evs[-1]["result"]["status"]["state"] == "completed" and evs[-2]["result"]["lastChunk"] is True
          and "A2A-ANSWER" in evs[-2]["result"]["artifact"]["parts"][0]["text"], evs)
    plain = ctl.create_agent_runtime(agentRuntimeName="plain_http", agentRuntimeArtifact=art, roleArn=ROLE, networkConfiguration={"networkMode": "PUBLIC"})
    time.sleep(1.2)
    try:
        urllib.request.urlopen(url + f"/runtimes/{quote(plain['agentRuntimeArn'], safe='')}/invocations/.well-known/agent-card.json"); check("non-A2A runtime has no agent card -> 404", False)
    except urllib.error.HTTPError as e:
        check("non-A2A runtime has no agent card -> 404", e.code == 404, e.code)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
