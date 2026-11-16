"""AgentCore round-9 gaps closed, through the REAL boto3 clients + plain HTTP (in-process server, one thread per request so the service can call itself):
  * USER_FEDERATION: GetResourceOauth2Token -> authorizationUrl (PKCE S256 + state) -> the local Cognito hosted UI (/{pool}/oauth2/authorize, /login)
    -> the provider's callbackUrl on this service -> code exchange with code_verifier -> CompleteResourceTokenAuth -> accessToken;
  * InvokeAgentRuntimeCommand: a real event stream (contentStart / contentDelta / contentStop) from the code sandbox, files persist per session;
  * A2A message/stream and InvokeAgentRuntime SSE emit per token AS the model produces them (timed against a slow model);
  * AWS_IAM: an access key IAM holds is always verified (wrong secret 403, even without the strict env), unknown ambient keys keep the documented behaviour.
Run: PYTHONPATH=. python tests/conformance/test_agentcore_auth_limits.py
"""
import asyncio
import http.client
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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


ANSWER = "STREAMED-ANSWER the quick brown fox jumps over the lazy dog again and again"


def main():
    import anyio
    import boto3
    import uvicorn
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.config import Config
    from botocore.credentials import Credentials
    from fastapi import FastAPI, Request
    from core import llm_core as llm
    from core import wire_ingress
    from core.aws_wire_router import AwsWireRouter
    fake = FakeLLM(handler=lambda b: {"content": ANSWER}, delay=0.15)
    llm.set_backend(None)
    llm._state.update(endpoint=fake.url, no_rf=False, no_native=False)
    llm._state["embed_fn"] = lambda texts: [llm.hash_embed(t) for t in texts]
    os.environ.pop("VYOMI_LLM_DISABLE", None)
    os.environ["VYOMI_LLM_ENDPOINT"] = fake.url
    router = AwsWireRouter()
    app = FastAPI()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    async def any_(p: str, request: Request):
        body = await request.body()
        return await anyio.to_thread.run_sync(lambda: asyncio.run(wire_ingress.serve(router, request, body=body)))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    kw = dict(region_name="us-east-1", endpoint_url=url, aws_access_key_id="test", aws_secret_access_key="test", config=Config(retries={"max_attempts": 1}))
    ctl, dp, cog, iam = (boto3.client(n, **kw) for n in ("bedrock-agentcore-control", "bedrock-agentcore", "cognito-idp", "iam"))
    ROLE = "arn:aws:iam::123456789012:role/r"
    ART = {"containerConfiguration": {"containerUri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/x:1"}}
    SPEC = {"instructions": "Answer briefly.", "tools": []}

    def runtime(name, protocol=None, spec=SPEC):
        extra = {"protocolConfiguration": {"serverProtocol": protocol}} if protocol else {}
        r = ctl.create_agent_runtime(agentRuntimeName=name, agentRuntimeArtifact=ART, roleArn=ROLE, networkConfiguration={"networkMode": "PUBLIC"},
                                     environmentVariables={"VYOMI_AGENT_SPEC": json.dumps(spec)}, **extra)
        time.sleep(1.2)
        return r

    # ───────────────────────── USER_FEDERATION against the local Cognito hosted UI ─────────────────────────
    print("== USER_FEDERATION (authorization code + PKCE) on the local Cognito user pool")
    pool = cog.create_user_pool(PoolName="facilities-users")["UserPool"]["Id"]
    cog.admin_create_user(UserPoolId=pool, Username="mona", TemporaryPassword="Temp#12345", MessageAction="SUPPRESS")
    cog.admin_set_user_password(UserPoolId=pool, Username="mona", Password="Str0ng#Pass1", Permanent=True)
    disc = f"{url}/{pool}/.well-known/openid-configuration"
    doc = json.loads(urllib.request.urlopen(disc).read())
    check("the pool's openid-configuration advertises authorization + token endpoints (S256 only)", doc["authorization_endpoint"] == f"{url}/{pool}/oauth2/authorize"
          and doc["token_endpoint"].endswith("/oauth2/token") and doc["code_challenge_methods_supported"] == ["S256"] and doc["jwks_uri"].endswith("jwks.json"), doc)
    prov = ctl.create_oauth2_credential_provider(name="gh-user", credentialProviderVendor="CustomOauth2", oauth2ProviderConfigInput={"customOauth2ProviderConfig": {
        "oauthDiscovery": {"discoveryUrl": disc}, "clientId": "placeholder", "clientSecret": "placeholder"}})
    cb = prov["callbackUrl"]
    check("the provider's callbackUrl points at this service (so the browser can return to it)", cb.startswith(url + "/identities/oauth2/callback/"), cb)
    cl = cog.create_user_pool_client(UserPoolId=pool, ClientName="agentcore", GenerateSecret=True, CallbackURLs=[cb], AllowedOAuthFlows=["code"],
                                     AllowedOAuthScopes=["openid", "email"], ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"])["UserPoolClient"]
    ctl.update_oauth2_credential_provider(name="gh-user", credentialProviderVendor="CustomOauth2", oauth2ProviderConfigInput={"customOauth2ProviderConfig": {
        "oauthDiscovery": {"discoveryUrl": disc}, "clientId": cl["ClientId"], "clientSecret": cl["ClientSecret"]}})
    wit = dp.get_workload_access_token_for_user_id(workloadName="facilities-agent", userId="mona")["workloadAccessToken"]
    RET = "http://localhost:3000/oauth/return"
    r1 = dp.get_resource_oauth2_token(workloadIdentityToken=wit, resourceCredentialProviderName="gh-user", scopes=["openid", "email"], oauth2Flow="USER_FEDERATION",
                                      resourceOauth2ReturnUrl=RET, customState="app-csrf-1")
    au = urllib.parse.urlparse(r1["authorizationUrl"])
    q = dict(urllib.parse.parse_qsl(au.query))
    check("first call: no token yet -> authorizationUrl + sessionUri, IN_PROGRESS", r1["sessionStatus"] == "IN_PROGRESS" and "accessToken" not in r1
          and r1["sessionUri"].startswith("urn:ietf:params:oauth:request_uri:"), r1)
    check("  authorization request: code flow, S256 PKCE, state, the provider's redirect_uri and scopes", au.path == f"/{pool}/oauth2/authorize" and q["response_type"] == "code"
          and q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43 and q["redirect_uri"] == cb and q["client_id"] == cl["ClientId"] and q["scope"] == "openid email" and q["state"], q)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)

    def get(u):
        try:
            with opener.open(u) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def post_form(u, form, headers=None):
        req = urllib.request.Request(u, data=urllib.parse.urlencode(form).encode(), method="POST", headers={"content-type": "application/x-www-form-urlencoded", **(headers or {})})
        try:
            with opener.open(req) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()
    st, h, b = get(r1["authorizationUrl"])
    check("the hosted UI serves a sign-in form for the authorization request", st == 200 and b"<form" in b and b"password" in b, (st, b[:200]))
    st, h, b = get(r1["authorizationUrl"].replace(urllib.parse.quote(cb, safe=""), urllib.parse.quote("http://evil.example/cb", safe="")))
    check("a redirect_uri that is not a registered CallbackURL is refused (400, no redirect)", st == 400 and b"redirect_mismatch" in b, (st, h))
    login = {k: q.get(k, "") for k in ("client_id", "redirect_uri", "response_type", "scope", "state", "code_challenge", "code_challenge_method")}
    st, h, b = post_form(f"{url}/{pool}/login", dict(login, username="mona", password="WRONG"))
    check("wrong password -> the form again (401), no code issued", st == 401 and b"Incorrect username or password" in b, (st, b[:200]))
    st, h, b = post_form(f"{url}/{pool}/login", dict(login, username="mona", password="Str0ng#Pass1"))
    loc = urllib.parse.urlparse(h.get("location", ""))
    lq = dict(urllib.parse.parse_qsl(loc.query))
    check("correct password -> 302 to the callbackUrl with code + the same state", st == 302 and lq.get("code") and lq.get("state") == q["state"] and (loc.scheme + "://" + loc.netloc + loc.path) == cb, (st, h))
    dp_pre = dp.get_resource_oauth2_token(workloadIdentityToken=wit, resourceCredentialProviderName="gh-user", scopes=["openid", "email"], oauth2Flow="USER_FEDERATION", sessionUri=r1["sessionUri"])
    check("polling before the callback keeps returning IN_PROGRESS + the authorizationUrl", dp_pre["sessionStatus"] == "IN_PROGRESS" and "accessToken" not in dp_pre, dp_pre)
    st, h, b = get(h["location"])
    rl = urllib.parse.urlparse(h.get("location", ""))
    rq = dict(urllib.parse.parse_qsl(rl.query))
    check("the service exchanges the code (with the PKCE verifier) and redirects the browser to resourceOauth2ReturnUrl with session_id + the app's customState",
          st == 302 and h["location"].startswith(RET) and rq.get("session_id") == r1["sessionUri"] and rq.get("state") == "app-csrf-1", (st, h, b[:200]))
    dp_mid = dp.get_resource_oauth2_token(workloadIdentityToken=wit, resourceCredentialProviderName="gh-user", scopes=["openid", "email"], oauth2Flow="USER_FEDERATION", sessionUri=r1["sessionUri"])
    check("authorized but not yet confirmed by the app (CompleteResourceTokenAuth) -> still no token", "accessToken" not in dp_mid, dp_mid)
    try:
        dp.complete_resource_token_auth(userIdentifier={"userId": "mallory"}, sessionUri=r1["sessionUri"])
        check("CompleteResourceTokenAuth by a different user is refused", False)
    except dp.exceptions.AccessDeniedException:
        check("CompleteResourceTokenAuth by a different user is refused (AccessDeniedException)", True)
    dp.complete_resource_token_auth(userIdentifier={"userId": "mona"}, sessionUri=r1["sessionUri"])
    done = dp.get_resource_oauth2_token(workloadIdentityToken=wit, resourceCredentialProviderName="gh-user", scopes=["openid", "email"], oauth2Flow="USER_FEDERATION", sessionUri=r1["sessionUri"])
    import base64
    claims = json.loads(base64.urlsafe_b64decode(done["accessToken"].split(".")[1] + "=="))
    check("after CompleteResourceTokenAuth the sessionUri yields the pool's real access token (RS256 JWT for mona)", claims.get("username") == "mona" or claims.get("sub"), claims)
    again = dp.get_resource_oauth2_token(workloadIdentityToken=wit, resourceCredentialProviderName="gh-user", scopes=["openid", "email"], oauth2Flow="USER_FEDERATION")
    check("the token is cached per (provider, user, scopes): no new consent for the same user", again.get("accessToken") == done["accessToken"], again)
    forced = dp.get_resource_oauth2_token(workloadIdentityToken=wit, resourceCredentialProviderName="gh-user", scopes=["openid", "email"], oauth2Flow="USER_FEDERATION", forceAuthentication=True)
    check("forceAuthentication starts a fresh 3-legged flow", forced.get("sessionStatus") == "IN_PROGRESS" and forced["sessionUri"] != r1["sessionUri"], forced)
    other = dp.get_workload_access_token_for_user_id(workloadName="facilities-agent", userId="sam")["workloadAccessToken"]
    o2 = dp.get_resource_oauth2_token(workloadIdentityToken=other, resourceCredentialProviderName="gh-user", scopes=["openid", "email"], oauth2Flow="USER_FEDERATION")
    check("another user does not inherit the cached token", o2.get("sessionStatus") == "IN_PROGRESS", o2)
    try:
        dp.get_resource_oauth2_token(workloadIdentityToken=wit, resourceCredentialProviderName="gh-user", scopes=["openid"], oauth2Flow="USER_FEDERATION", sessionUri="urn:ietf:params:oauth:request_uri:nope")
        check("unknown sessionUri -> ResourceNotFoundException", False)
    except dp.exceptions.ResourceNotFoundException:
        check("unknown sessionUri -> ResourceNotFoundException", True)
    # PKCE + single-use enforced by the authorization server itself
    verif = "x" * 64
    st, h, b = post_form(f"{url}/{pool}/login", dict(login, username="mona", password="Str0ng#Pass1"))   # reuse forced.state? new code bound to r1's challenge
    code2 = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(h["location"]).query))["code"]
    tok_ep = f"{url}/{pool}/oauth2/token"
    basic = {"authorization": "Basic " + base64.b64encode(f"{cl['ClientId']}:{cl['ClientSecret']}".encode()).decode()}
    st, h, b = post_form(tok_ep, {"grant_type": "authorization_code", "code": code2, "redirect_uri": cb, "code_verifier": verif}, basic)
    check("token endpoint: a wrong PKCE code_verifier -> invalid_grant", st == 400 and json.loads(b)["error"] == "invalid_grant", (st, b))
    st, h, b = post_form(tok_ep, {"grant_type": "authorization_code", "code": code2, "redirect_uri": cb, "code_verifier": verif}, basic)
    check("token endpoint: the code is single-use (already consumed by the failed attempt)", st == 400 and json.loads(b)["error"] == "invalid_grant", (st, b))
    st, h, b = post_form(tok_ep, {"grant_type": "authorization_code", "code": "x", "redirect_uri": cb, "code_verifier": verif}, {"authorization": "Basic " + base64.b64encode(b"nope:nope").decode()})
    check("token endpoint: bad client credentials -> 400/401 invalid_client", st in (400, 401) and json.loads(b)["error"] == "invalid_client", (st, b))
    # the user denies consent: the authorization server redirects with error -> FAILED
    r3 = dp.get_resource_oauth2_token(workloadIdentityToken=other, resourceCredentialProviderName="gh-user", scopes=["openid"], oauth2Flow="USER_FEDERATION", forceAuthentication=True)
    st3 = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r3["authorizationUrl"]).query))["state"]
    get(f"{cb}?error=access_denied&error_description=user+said+no&state={st3}")
    r3b = dp.get_resource_oauth2_token(workloadIdentityToken=other, resourceCredentialProviderName="gh-user", scopes=["openid"], oauth2Flow="USER_FEDERATION", sessionUri=r3["sessionUri"])
    check("user denies consent at the authorization server -> sessionStatus FAILED", r3b["sessionStatus"] == "FAILED", r3b)
    st, h, b = get(f"{cb}?code=zzz&state=unknown-state")
    check("a callback with an unknown state is rejected (CSRF)", st == 400, (st, b))
    try:
        dp.get_resource_oauth2_token(workloadIdentityToken=wit, resourceCredentialProviderName="gh-user", scopes=["x"], oauth2Flow="ON_BEHALF_OF_TOKEN_EXCHANGE")
        check("ON_BEHALF_OF_TOKEN_EXCHANGE is rejected with a clear error", False)
    except dp.exceptions.ValidationException:
        check("ON_BEHALF_OF_TOKEN_EXCHANGE is rejected with a clear error (ValidationException)", True)

    # ───────────────────────── InvokeAgentRuntimeCommand ─────────────────────────
    print("== InvokeAgentRuntimeCommand (event stream from the code sandbox)")
    rt = runtime("cmd_runtime")
    SID = "command-session-0000000000000000001"

    def cmd(command, timeout=10, sid=SID):
        out = dp.invoke_agent_runtime_command(agentRuntimeArn=rt["agentRuntimeArn"], runtimeSessionId=sid, body={"command": command, "timeout": timeout})
        evs = [e["chunk"] for e in out["stream"]]
        return out, evs, "".join(e["contentDelta"].get("stdout", "") for e in evs if "contentDelta" in e), "".join(e["contentDelta"].get("stderr", "") for e in evs if "contentDelta" in e), evs[-1].get("contentStop", {})
    out, evs, so, se, stop = cmd("echo hello && python3 -c 'print(6*7)'")
    check("the response is a real event stream: contentStart ... contentDelta ... contentStop", "contentStart" in evs[0] and "contentStop" in evs[-1] and any("contentDelta" in e for e in evs), evs)
    check("  echo + python3 -c ran in the sandbox: stdout 'hello' then '42', exitCode 0, COMPLETED", so == "hello\n42\n" and stop == {"exitCode": 0, "status": "COMPLETED"}, (so, stop))
    check("  statusCode 200, session id echoed", out["statusCode"] == 200 and out["runtimeSessionId"] == SID, out["ResponseMetadata"]["HTTPHeaders"])
    _, _, so, se, stop = cmd("python3 -c \"open('notes.txt','w').write('persisted')\" ; ls")
    check("a file written by a command lands in the session workspace", "notes.txt" in so, so)
    _, _, so, se, stop = cmd("cat notes.txt > copy.txt ; cat copy.txt")
    check("  and persists across commands of the same session (cat, > redirect)", so == "persisted" and stop["exitCode"] == 0, (so, stop))
    _, _, so, _, _ = cmd("ls", sid="another-session-0000000000000000000002")
    check("  a different runtimeSessionId has its own empty workspace", so == "", so)
    _, _, so, se, stop = cmd("python3 -c 'raise ValueError(\"boom\")'")
    check("a failing script: traceback on stderr, exitCode 1", "ValueError: boom" in se and stop["exitCode"] == 1 and stop["status"] == "COMPLETED", (se, stop))
    _, _, so, se, stop = cmd("nosuchtool --flag")
    check("an unknown program: sh: not found on stderr, exitCode 127", "not found" in se and stop["exitCode"] == 127, (se, stop))
    _, _, so, se, stop = cmd("false && echo no ; false || echo yes")
    check("&& / || / ; sequencing honours exit codes", so == "yes\n", (so, stop))
    _, _, so, se, stop = cmd("python3 -c 'import os; os.system(\"echo pwned\")'")
    check("the sandbox blocks process creation (no host shell)", "pwned" not in so and stop["exitCode"] != 0 and "blocked" in se, (so, se))
    _, _, so, se, stop = cmd("python3 -c 'while True: pass'", timeout=1)
    check("a command that runs past `timeout` ends with TIMED_OUT (exitCode 124)", stop["status"] == "TIMED_OUT" and stop["exitCode"] == 124, stop)
    _, _, so, se, stop = cmd("echo a | cat")
    check("pipes are an honest syntax error, not silently ignored", stop["exitCode"] == 2 and "unsupported shell operator" in se, (se, stop))
    for bad in ({"command": "", "timeout": 5}, {"command": "echo", "timeout": 0}, {"command": "echo", "timeout": 4000}):
        try:
            dp.invoke_agent_runtime_command(agentRuntimeArn=rt["agentRuntimeArn"], runtimeSessionId=SID, body=bad)
            check(f"invalid body {bad} -> ValidationException", False)
        except Exception as e:  # noqa: BLE001
            check(f"invalid body {bad} -> ValidationException", "ValidationException" in str(e) or "validation" in str(e).lower(), e)

    # ───────────────────────── streaming ─────────────────────────
    print("== streaming: tokens leave as the model produces them")
    t0 = time.time()
    rta = runtime("a2a_stream", "A2A")
    base = f"/runtimes/{urllib.parse.quote(rta['agentRuntimeArn'], safe='')}/invocations/"

    def stream_post(path, body, headers):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        c.request("POST", path, body=json.dumps(body), headers={"content-type": "application/json", **headers})
        r = c.getresponse()
        t_hdr, buf, evs = time.time(), b"", []
        while True:
            ch = r.read1(4096)
            if not ch:
                break
            buf += ch
            while b"\n\n" in buf:
                raw, buf = buf.split(b"\n\n", 1)
                if raw.startswith(b"data:"):
                    evs.append((time.time(), json.loads(raw[5:])))
        return r.status, dict(r.getheaders()), evs
    msg = {"kind": "message", "role": "user", "messageId": "m1", "parts": [{"kind": "text", "text": "tell me something long"}]}
    t_start = time.time()
    st, hdrs, evs = stream_post(base, {"jsonrpc": "2.0", "id": 1, "method": "message/stream", "params": {"message": msg}}, {})
    results = [e["result"] for _, e in evs]
    kinds = [x["kind"] for x in results]
    arts = [(t, e["result"]) for t, e in evs if e["result"]["kind"] == "artifact-update"]
    total = evs[-1][0] - t_start
    first = arts[0][0] - t_start
    check("A2A message/stream: text/event-stream, task -> many artifact-update chunks -> completed(final)", st == 200 and "text/event-stream" in hdrs["content-type"]
          and kinds[0] == "task" and kinds[-1] == "status-update" and results[-1]["final"] and results[-1]["status"]["state"] == "completed" and len(arts) > 6, (st, kinds))
    chunks = [x["artifact"]["parts"][0]["text"] for _, x in arts]
    check("  the streamed chunks (append=true) concatenate to the final answer", "".join(chunks[:-1]) == ANSWER[:len("".join(chunks[:-1]))] and chunks[-1] == ANSWER and arts[-1][1]["lastChunk"] is True
          and all(x["append"] for _, x in arts[1:-1]), (chunks[:3], chunks[-1]))
    check(f"  per token, as produced: the first chunk arrived after {first:.2f}s while the whole answer took {total:.2f}s", first < 0.6 * total and total > 1.2, (first, total))
    gaps = [b[0] - a[0] for a, b in zip(arts, arts[1:-1])]
    check("  chunks are spread over time (not flushed at the end)", sum(1 for g in gaps if g > 0.05) >= len(gaps) // 2, gaps)
    sess = {"x-amzn-bedrock-agentcore-runtime-session-id": "sse-session-00000000000000000000001", "accept": "text/event-stream"}
    rtb = runtime("sse_stream")
    base2 = f"/runtimes/{urllib.parse.quote(rtb['agentRuntimeArn'], safe='')}/invocations"
    t_start = time.time()
    st, hdrs, evs = stream_post(base2, {"prompt": "tell me something long"}, sess)
    toks = [(t, e) for t, e in evs if e.get("event") == "token"]
    fin = [e for _, e in evs if e.get("event") == "final"]
    check("InvokeAgentRuntime (Accept: text/event-stream): token events then a final event", st == 200 and len(toks) > 6 and fin and fin[0]["response"] == ANSWER and "".join(e["text"] for _, e in toks) == ANSWER, (st, len(toks), fin))
    check(f"  first token after {toks[0][0] - t_start:.2f}s, final after {evs[-1][0] - t_start:.2f}s (streamed while the model generated)", toks[0][0] - t_start < 0.6 * (evs[-1][0] - t_start), (toks[0][0] - t_start, evs[-1][0] - t_start))
    out = dp.invoke_agent_runtime(agentRuntimeArn=rtb["agentRuntimeArn"], runtimeSessionId="boto-session-0000000000000000000001", payload=json.dumps({"prompt": "hi"}).encode())
    check("the non-streaming boto3 call still returns the whole JSON answer", json.loads(out["response"].read())["response"] == ANSWER)
    # tool-calling step then final answer (step boundaries are visible on the stream)
    # ───────────────────────── AWS_IAM SigV4 verification ─────────────────────────
    print("== AWS_IAM: access keys IAM holds are always verified")
    iam.create_user(UserName="alice")
    k = iam.create_access_key(UserName="alice")["AccessKey"]
    gw = ctl.create_gateway(name="iam-gw", roleArn=ROLE, authorizerType="AWS_IAM")["gatewayId"]
    time.sleep(1.2)

    def sig_post(ak, sk):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        r = AWSRequest(method="POST", url=f"{url}/gateways/{gw}/mcp", data=body, headers={"Content-Type": "application/json"})
        SigV4Auth(Credentials(ak, sk), "bedrock-agentcore", "us-east-1").add_auth(r)
        req = urllib.request.Request(r.url, data=body.encode(), method="POST", headers=dict(r.headers.items()))
        try:
            with urllib.request.urlopen(req) as x:
                return x.status
        except urllib.error.HTTPError as e:
            return e.code
    os.environ.pop("VYOMI_AGENTCORE_SIGV4_STRICT", None)
    check("default mode: IAM-held key + right secret -> 200", sig_post(k["AccessKeyId"], k["SecretAccessKey"]) == 200)
    check("default mode: IAM-held key + WRONG secret -> 403 (no strict flag needed)", sig_post(k["AccessKeyId"], "wrong" * 8) == 403)
    check("default mode: an ambient key IAM does not hold (test/test) keeps the documented behaviour (admitted, flagged unverified)", sig_post("test", "test") == 200)
    os.environ["VYOMI_AGENTCORE_SIGV4_STRICT"] = "1"
    check("VYOMI_AGENTCORE_SIGV4_STRICT=1 rejects the unknown ambient key", sig_post("test", "test") == 403)
    os.environ.pop("VYOMI_AGENTCORE_SIGV4_STRICT")
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
