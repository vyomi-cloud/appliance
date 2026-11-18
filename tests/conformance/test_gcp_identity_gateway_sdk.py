"""GCP reference-arch component 1 (Access): Identity Platform sign-in + JWKS, API Gateway with PyYAML OpenAPI + ID-token validation.

Real libraries only: google-cloud-api-gateway (REST transport) to create api/config/gateway, google.oauth2.id_token.verify_firebase_token,
PyJWT + its JWKS client, firebase_admin (emulator-mode Admin SDK) for create_user / custom claims. Runs the simulator in-process.
Needs: pip install google-cloud-api-gateway google-auth PyJWT PyYAML requests firebase-admin
"""
import base64, json, os, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
fails = 0


def check(name, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' :: ' + str(extra)[:300]}")


def start_sim():
    import socket, tempfile, asyncio
    work = tempfile.mkdtemp(prefix="idgw-")
    os.environ["CLOUDLEARN_STATE_FILE"] = os.path.join(work, "state.sqlite3")
    cwd = os.getcwd(); os.chdir(work)
    import anyio, uvicorn
    from fastapi import FastAPI, Request
    from core import wire_ingress
    app, router = FastAPI(), wire_ingress.appliance_router()

    @app.api_route("/{p:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
    async def any_(p: str, request: Request):
        body = await request.body()
        return await anyio.to_thread.run_sync(lambda: asyncio.run(wire_ingress.serve(router, request, body=body)))
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        time.sleep(0.05)
    os.chdir(cwd)
    return f"http://127.0.0.1:{port}"


class Backend(BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        Backend.seen.append((self.path, dict(self.headers)))
        body = json.dumps({"ok": True, "path": self.path, "userinfo": self.headers.get("X-Endpoint-API-UserInfo")}).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


def main():
    try:
        import requests, yaml, jwt, firebase_admin  # noqa: F401
        from google.auth.credentials import AnonymousCredentials
        from google.auth.transport import requests as grequests
        from google.oauth2 import id_token as gid
        from google.cloud import apigateway_v1
    except ImportError as e:   # the real SDKs are not in every CI image; never report a pass for something not run
        print("[SKIP] needs the real Google SDKs (%s): pip install google-cloud-api-gateway google-auth PyJWT PyYAML requests firebase-admin" % e)
        sys.exit(0)
    srv = HTTPServer(("127.0.0.1", 0), Backend)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["VYOMI_GATEWAY_BACKEND_OVERRIDES"] = "https://facilities-backend.test=http://127.0.0.1:%d" % srv.server_port
    ep = start_sim()
    P, tag = "vyomi-project", uuid.uuid4().hex[:6]
    X509 = ep + "/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
    JWK = ep + "/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    gid._GOOGLE_APIS_CERTS_URL = X509   # verify_firebase_token reads this module constant at call time

    # ── Identity Platform ───────────────────────────────────────────────
    r = requests.post(ep + "/v1/accounts:signUp?key=fake", json={"email": "duty@example.com", "password": "pw-12345", "returnSecureToken": True})
    check("signUp 200 + idToken + refreshToken", r.status_code == 200 and r.json().get("idToken") and r.json().get("refreshToken"), r.text)
    uid = r.json()["localId"]
    dup = requests.post(ep + "/v1/accounts:signUp?key=fake", json={"email": "duty@example.com", "password": "pw-12345"})
    check("duplicate signUp -> EMAIL_EXISTS", dup.status_code == 400 and dup.json()["error"]["message"] == "EMAIL_EXISTS", dup.text)
    bad = requests.post(ep + "/v1/accounts:signInWithPassword?key=fake", json={"email": "duty@example.com", "password": "nope-nope"})
    check("wrong password -> 400 INVALID_LOGIN_CREDENTIALS", bad.status_code == 400 and bad.json()["error"]["message"] == "INVALID_LOGIN_CREDENTIALS", bad.text)
    si = requests.post(ep + "/v1/accounts:signInWithPassword?key=fake", json={"email": "duty@example.com", "password": "pw-12345", "returnSecureToken": True}).json()
    tok = si["idToken"]
    claims = gid.verify_firebase_token(tok, grequests.Request(), audience=P)
    check("google.oauth2.id_token.verify_firebase_token verifies the ID token (x509 certs)", claims["email"] == "duty@example.com" and claims["sub"] == uid, claims)
    check("claims: iss/aud/firebase", claims["iss"] == "https://securetoken.google.com/" + P and claims["aud"] == P and claims["firebase"]["sign_in_provider"] == "password", claims)
    key = jwt.PyJWKClient(JWK).get_signing_key_from_jwt(tok).key
    c2 = jwt.decode(tok, key, algorithms=["RS256"], audience=P, issuer="https://securetoken.google.com/" + P)
    check("PyJWT + served JWKS verifies the ID token", c2["user_id"] == uid, c2)
    try:
        gid.verify_firebase_token(tok[:-4] + "AAAA", grequests.Request(), audience=P); forged = False
    except Exception:
        forged = True
    check("a tampered token is rejected by the real library", forged)
    lk = requests.post(ep + "/v1/accounts:lookup?key=fake", json={"idToken": tok}).json()
    check("accounts:lookup returns the user", lk["users"][0]["email"] == "duty@example.com", lk)
    rf = requests.post(ep + "/v1/token?key=fake", data={"grant_type": "refresh_token", "refresh_token": si["refreshToken"]}).json()
    check("securetoken refresh grant returns a new verifiable id_token", gid.verify_firebase_token(rf["id_token"], grequests.Request(), audience=P)["sub"] == uid, rf)
    # custom claims through the Admin SDK (emulator-mode transport) and through the raw Admin REST
    os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = ep.split("//", 1)[1]
    import firebase_admin
    from firebase_admin import auth as fauth, credentials
    app = firebase_admin.initialize_app(credentials.AnonymousCredentials() if hasattr(credentials, "AnonymousCredentials") else None, {"projectId": P}, name="t" + tag)
    try:
        fu = fauth.create_user(email="admin-made@example.com", password="pw-123456", app=app)
        fauth.set_custom_user_claims(fu.uid, {"role": "dispatcher", "site": "hq"}, app=app)
        got = fauth.get_user(fu.uid, app=app)
        check("firebase_admin create_user / set_custom_user_claims / get_user", got.custom_claims == {"role": "dispatcher", "site": "hq"} and got.email == "admin-made@example.com", got.custom_claims)
    except Exception as e:  # noqa: BLE001
        check("firebase_admin create_user / set_custom_user_claims / get_user", False, repr(e))
    r = requests.post(ep + f"/v1/projects/{P}/accounts:update", json={"localId": uid, "customAttributes": json.dumps({"role": "approver"})})
    check("Admin REST accounts:update sets customAttributes", r.status_code == 200, r.text)
    tok2 = requests.post(ep + "/v1/accounts:signInWithPassword?key=fake", json={"email": "duty@example.com", "password": "pw-12345"}).json()["idToken"]
    check("custom claim appears as a top-level claim in the next ID token", gid.verify_firebase_token(tok2, grequests.Request(), audience=P).get("role") == "approver")

    # ── API Gateway: real client, PyYAML spec, ID-token validation ──────────────
    sa = f"projects/-/serviceAccounts/agent-sa@{P}.iam.gserviceaccount.com"
    requests.post(ep + f"/v1/projects/{P}/serviceAccounts", json={"accountId": "agent-sa", "serviceAccount": {"displayName": "agent"}})
    sa_tok = requests.post(ep + f"/v1/{sa}:generateIdToken", json={"audience": "https://facilities.example.com", "includeEmail": True}).json()["token"]
    spec = {"swagger": "2.0", "info": {"title": "facilities", "version": "1.0"}, "schemes": ["https"], "produces": ["application/json"],
            "paths": {
                "/ask": {"get": {"operationId": "ask", "x-google-backend": {"address": "https://facilities-backend.test/handler", "path_translation": "APPEND_PATH_TO_ADDRESS"},
                                 "security": [{"firebase": []}], "responses": {"200": {"description": "ok"}}}},
                "/svc": {"get": {"operationId": "svc", "x-google-backend": {"address": "https://facilities-backend.test/handler", "path_translation": "APPEND_PATH_TO_ADDRESS"},
                                 "security": [{"google_id_token": []}], "responses": {"200": {"description": "ok"}}}}},
            "securityDefinitions": {
                "firebase": {"authorizationUrl": "", "flow": "implicit", "type": "oauth2", "x-google-issuer": "https://securetoken.google.com/" + P,
                             "x-google-jwks_uri": "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com", "x-google-audiences": P},
                "google_id_token": {"authorizationUrl": "", "flow": "implicit", "type": "oauth2", "x-google-issuer": "https://accounts.google.com",
                                    "x-google-jwks_uri": "https://www.googleapis.com/oauth2/v3/certs", "x-google-audiences": "https://facilities.example.com"}}}
    yaml_text = yaml.safe_dump(spec)
    flow_text = "{swagger: '2.0', info: {title: flow, version: '1'}, paths: {/p: {get: {operationId: p, x-google-backend: {address: 'https://facilities-backend.test'}, responses: {'200': {description: ok}}}}}}"
    client = apigateway_v1.ApiGatewayServiceClient(transport="rest", credentials=AnonymousCredentials(), client_options={"api_endpoint": ep})
    parent = f"projects/{P}/locations/global"
    api_id = f"fac-{tag}"
    client.create_api(request={"parent": parent, "api_id": api_id, "api": {"display_name": "fac"}}).result()
    cfg = client.create_api_config(request={"parent": f"{parent}/apis/{api_id}", "api_config_id": "c1", "api_config": {
        "openapi_documents": [{"document": {"path": "openapi.yaml", "contents": yaml_text.encode()}}]}}).result()
    check("real client creates an API config from a PyYAML-dumped spec", cfg.name.endswith("/configs/c1"), cfg)
    fcfg = client.create_api_config(request={"parent": f"{parent}/apis/{api_id}", "api_config_id": "c2", "api_config": {
        "openapi_documents": [{"document": {"path": "flow.yaml", "contents": flow_text.encode()}}]}}).result()
    check("flow-style YAML spec accepted", fcfg.name.endswith("/configs/c2"))
    try:
        client.create_api_config(request={"parent": f"{parent}/apis/{api_id}", "api_config_id": "c3", "api_config": {
            "openapi_documents": [{"document": {"path": "bad.yaml", "contents": b"swagger: '2.0'\ninfo: [unclosed\n"}}]}}).result()
        rejected = False
    except Exception as e:  # noqa: BLE001
        rejected = "parse" in str(e).lower() or "invalid" in str(e).lower()
    check("a malformed spec is rejected with a parse error", rejected)
    gw = client.create_gateway(request={"parent": f"projects/{P}/locations/us-central1", "gateway_id": "facilities-gateway", "gateway": {
        "api_config": f"{parent}/apis/{api_id}/configs/c1"}}).result()
    host = gw.default_hostname
    check("gateway created with a *.gateway.dev hostname", host.endswith(".gateway.dev"), host)

    def via(path, token=None, **kw):   # the simulator origin routes a *.gateway.dev Host header to the gateway engine
        h = {"Host": host}
        if token:
            h["Authorization"] = "Bearer " + token
        return requests.get(ep + path, headers=h, **kw)
    r = via("/ask")
    check("no token -> 401 Jwt is missing", r.status_code == 401 and "Jwt is missing" in r.text, (r.status_code, r.text))
    r = via("/ask", "not.a.jwt")
    check("garbage token -> 401", r.status_code == 401, (r.status_code, r.text))
    r = via("/ask", tok2[:-6] + "AAAAAA")
    check("tampered Identity Platform token -> 401", r.status_code == 401, (r.status_code, r.text))
    r = via("/ask", tok2)
    check("Identity Platform ID token accepted, request reaches the x-google-backend", r.status_code == 200 and r.json()["path"] == "/handler/ask", (r.status_code, r.text))
    ui = json.loads(base64.urlsafe_b64decode(r.json()["userinfo"] + "=="))
    check("backend receives X-Endpoint-API-UserInfo with the verified claims", ui["email"] == "duty@example.com" and ui.get("role") == "approver", ui)
    r = via("/ask", sa_tok)
    check("a service-account token is not valid for the firebase definition (wrong issuer) -> 401", r.status_code == 401, (r.status_code, r.text))
    r = via("/svc", sa_tok)
    check("iamcredentials generateIdToken token accepted on the google_id_token definition", r.status_code == 200 and r.json()["path"] == "/handler/svc", (r.status_code, r.text))
    wrong_aud = requests.post(ep + f"/v1/{sa}:generateIdToken", json={"audience": "https://other.example.com"}).json()["token"]
    r = via("/svc", wrong_aud)
    check("service-account token for another audience -> 401", r.status_code == 401, (r.status_code, r.text))
    r = requests.get(ep + "/gcpgw/facilities-gateway/ask", headers={"Authorization": "Bearer " + tok2})
    check("path-style /gcpgw/<gateway>/... also routes", r.status_code == 200, (r.status_code, r.text))
    r = via("/nope", tok2)
    check("unknown route -> 404", r.status_code == 404, r.status_code)

    # ── Cloud Armor ─────────────────────────────────────────────────────
    pol = f"fac-armor-{tag}"
    c = requests.post(ep + f"/compute/v1/projects/{P}/global/securityPolicies", json={"name": pol, "rules": [
        {"priority": 1000, "action": "deny(403)", "match": {"versionedExpr": "SRC_IPS_V1", "config": {"srcIpRanges": ["203.0.113.0/24"]}}},
        {"priority": 2147483647, "action": "allow", "match": {"versionedExpr": "SRC_IPS_V1", "config": {"srcIpRanges": ["*"]}}}]})
    g = requests.get(ep + f"/compute/v1/projects/{P}/global/securityPolicies/{pol}").json()
    check("Cloud Armor securityPolicies create/get keeps the rules", c.status_code in (200, 201) and len(g.get("rules", [])) == 2, (c.status_code, c.text))
    print("[INFO] Cloud Armor: policies are control-plane only; attachment to a gateway/backend is not an API surface here (see branch doc)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
