"""C1: Identity Platform sign-in (ID token), Cloud Armor security policy, API Gateway in front of the tools (JWT validation)."""
import base64, json, time
import requests
from ..runtime import NAMES, LANE, Blocked
from .. import deploy

USER, PW = "maria.ops@example.com", "Fac!lities-2026"
ISSUER = f"https://securetoken.google.com/{NAMES['users']}"      # Identity Platform / Firebase ID token issuer for project facilities-users


def claims(token):
    return json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=" * (-len(token.split(".")[1]) % 4)))


def _idp(ctx, op, body):
    """Identity Platform / Firebase Auth REST (identitytoolkit v1). It has no Google client library for end-user sign-in: the documented client is this REST API."""
    r = requests.post(f"{ctx.endpoint}/v1/accounts:{op}", params={"key": "vyomi-local"}, json=body, timeout=30,
                      headers={"x-goog-user-project": NAMES["users"]})        # the Identity Platform project (tenant of users) the sign-in belongs to
    if r.status_code in (404, 405):
        raise Blocked(LANE["identity"], f"Identity Platform accounts:{op} is not served (HTTP {r.status_code})")
    if r.status_code != 200:
        raise RuntimeError(f"accounts:{op} HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def sign_in(ctx):
    def signup():
        try:
            _idp(ctx, "signUp", {"email": USER, "password": PW, "returnSecureToken": True})
        except RuntimeError as e:
            if "EMAIL_EXISTS" not in str(e):
                raise
        r = _idp(ctx, "signInWithPassword", {"email": USER, "password": PW, "returnSecureToken": True})
        tok = r["idToken"]
        assert tok.count(".") == 2, "idToken is not a JWT"
        c = claims(tok)
        assert c.get("email") == USER, f"token email claim is {c.get('email')}"
        ctx.state.update(jwt=tok, user=USER, jwt_claims=c)
        return f"signed in as {USER}, JWT {len(tok)} chars, iss={c.get('iss')}"
    ctx.step("identity platform: accounts:signUp + signInWithPassword -> ID token", signup, lane=LANE["identity"])
    if "jwt" not in ctx.state:
        ctx.state["user"] = "anonymous (no identity provider yet)"

    def verify():
        """What the app's backend does: verify the Firebase / Identity Platform ID token with google-auth against the project's public certs."""
        from google.auth.transport import requests as gr
        from google.oauth2 import id_token
        c = id_token.verify_token(ctx.state["jwt"], gr.Request(), audience=NAMES["users"],
                                  certs_url=f"{ctx.endpoint}/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com")
        assert c["iss"] == ISSUER and c["email"] == USER, c
        return f"google.oauth2.id_token.verify_token ok: iss={c['iss']} aud={c['aud']} email={c['email']}"
    if ctx.state.get("jwt"):
        ctx.step("google-auth: verify the ID token signature, audience and issuer against the project certs", verify, lane=LANE["identity"])

    def sa_token():
        from google.cloud import iam_credentials_v1 as ic
        sa = f"agent-sa@{ctx.project}.iam.gserviceaccount.com"
        ctx.api("POST", f"/v1/projects/{ctx.project}/serviceAccounts", {"accountId": NAMES["agent_sa"], "serviceAccount": {"displayName": "facilities agent"}}, expect=(200, 201, 409))
        t = ctx.rest(ic.IAMCredentialsClient).generate_id_token(request={"name": f"projects/-/serviceAccounts/{sa}", "audience": "https://facilities.example.com", "include_email": True}).token
        assert t.count(".") == 2
        ctx.state["sa_token"] = t
        return "service-account ID token (iamcredentials generateIdToken) is a JWT"
    ctx.step("iamcredentials: service account + generateIdToken for the agent identity", sa_token)

    def armor():
        from google.cloud import compute_v1 as cv
        c = ctx.rest(cv.SecurityPoliciesClient)
        pol = cv.SecurityPolicy(name="facilities-armor", description="facilities edge policy", rules=[
            cv.SecurityPolicyRule(priority=1000, action="deny(403)", match=cv.SecurityPolicyRuleMatcher(expr=cv.Expr(expression="evaluatePreconfiguredExpr('xss-stable')"))),
            cv.SecurityPolicyRule(priority=2147483647, action="allow", match=cv.SecurityPolicyRuleMatcher(versioned_expr="SRC_IPS_V1", config=cv.SecurityPolicyRuleMatcherConfig(src_ip_ranges=["*"])))])
        try:
            c.insert(project=ctx.project, security_policy_resource=pol)
        except Exception as e:
            if "already exists" not in str(e).lower() and "409" not in str(e):
                raise
        got = c.get(project=ctx.project, security_policy="facilities-armor")
        assert got.name == "facilities-armor" and any("xss" in r.match.expr.expression for r in got.rules), got
        ctx.state["armor"] = got.name
        return "Cloud Armor policy facilities-armor with an XSS preconfigured-WAF rule"
    ctx.step("cloud armor: compute securityPolicies insert + get (WAF rule)", armor)


def _openapi(backend):
    """What a real user uploads: an OpenAPI 2.0 document as YAML, with x-google-backend and an Identity Platform (Firebase) JWT security definition."""
    import yaml
    return yaml.safe_dump({
        "swagger": "2.0", "info": {"title": "facilities-api", "version": "1.0.0"}, "schemes": ["https"], "produces": ["application/json"],
        "paths": {"/search": {"post": {"operationId": "search", "x-google-backend": {"address": backend, "path_translation": "CONSTANT_ADDRESS"}, "security": [{"firebase": []}, {"google_id_token": []}],
                                       "responses": {"200": {"description": "ok"}}}}},
        "securityDefinitions": {"google_id_token": {"authorizationUrl": "", "flow": "implicit", "type": "oauth2", "x-google-issuer": "https://accounts.google.com",
                                                    "x-google-jwks_uri": "https://www.googleapis.com/oauth2/v3/certs", "x-google-audiences": "https://facilities.example.com"},
                                "firebase": {"authorizationUrl": "", "flow": "implicit", "type": "oauth2", "x-google-issuer": ISSUER,
                                             "x-google-jwks_uri": "https://www.googleapis.com/service_accounts/v1/metadata/x509/securetoken@system.gserviceaccount.com",
                                             "x-google-audiences": NAMES["users"]}}})


def edge(ctx):
    """API Gateway -> kb-search function (read-only knowledge search); JWT validated at the gateway when an identity provider exists."""
    from google.cloud import apigateway_v1 as ag
    backend = ctx.state.get("kb_uri")
    if backend:       # real Cloud Functions URL shape (https); the simulator routes it to its function runtime
        backend = f"https://{ctx.loc}-{ctx.project}.cloudfunctions.net/facilities-kb-search"
    if not backend:
        ctx.step("api gateway: needs the kb-search function", lambda: (_ for _ in ()).throw(Blocked(LANE["sandbox"], "kb-search function was not deployed (component 7)")))
        return
    c = ctx.rest(ag.ApiGatewayServiceClient)
    glob = f"projects/{ctx.project}/locations/global"

    def wait(getter, what):
        for _ in range(40):
            r = getter()
            if r.state.name == "ACTIVE":
                return r
            assert r.state.name != "FAILED", f"{what} state FAILED"
            time.sleep(0.5)
        raise AssertionError(f"{what} did not reach ACTIVE (state {r.state.name})")

    def build():
        c.create_api(request={"parent": glob, "api_id": NAMES["api"], "api": ag.Api(display_name=NAMES["api"])})
        wait(lambda: c.get_api(request={"name": f"{glob}/apis/{NAMES['api']}"}), "api")
        c.create_api_config(request={"parent": f"{glob}/apis/{NAMES['api']}", "api_config_id": "cfg1", "api_config": ag.ApiConfig(
            display_name="cfg1", openapi_documents=[ag.ApiConfig.OpenApiDocument(document=ag.ApiConfig.File(path="openapi.yaml", contents=_openapi(backend).encode()))])})
        cfg = wait(lambda: c.get_api_config(request={"name": f"{glob}/apis/{NAMES['api']}/configs/cfg1"}), "api config")
        c.create_gateway(request={"parent": ctx.parent, "gateway_id": NAMES["api_gateway"], "gateway": ag.Gateway(api_config=cfg.name, display_name=NAMES["api_gateway"])})
        gw = wait(lambda: c.get_gateway(request={"name": f"{ctx.parent}/gateways/{NAMES['api_gateway']}"}), "gateway")
        ctx.state["api_gw"] = gw.name
        return f"gateway {gw.name} host {gw.default_hostname}"
    ok = ctx.step("api gateway: create API + config (OpenAPI YAML with x-google-backend + JWT security) + gateway", build, lane=LANE["identity"])

    def lro():
        """The SDK pattern is create_api(...).result(): the operation's response must decode to a typed Api."""
        api = c.create_api(request={"parent": glob, "api_id": NAMES["api"] + "-lro", "api": ag.Api(display_name="lro check")}).result(timeout=60)
        assert api.name.endswith(NAMES["api"] + "-lro"), api
        return "create_api(...).result() returned the typed Api"
    ctx.step("api gateway: create_api(...).result() decodes the long-running operation response", lro)
    if not ok:
        return
    url = f"{ctx.endpoint}/gcpgw/{NAMES['api_gateway']}/search"       # simulator data plane address; on GCP use https://<gateway.default_hostname>/search

    def post(tok):
        h = {"Content-Type": "application/json"}
        if tok:
            h["Authorization"] = "Bearer " + tok
        return requests.post(url, json={"query": "boiler pressure limit"}, headers=h, timeout=60)

    def authed():
        r = post(ctx.state.get("jwt") or ctx.state.get("sa_token"))
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        out = r.json()
        assert out.get("results"), out
        return f"HTTP 200 via API Gateway with a {'user' if ctx.state.get('jwt') else 'service-account'} ID token; caller={out.get('caller')}"
    ctx.step("api gateway: invoke /search with a valid ID token", authed, lane=LANE["identity"])

    def anon():
        r = post(None)
        assert r.status_code in (401, 403), f"unauthenticated call got HTTP {r.status_code}, expected 401/403"
        return f"unauthenticated call rejected with HTTP {r.status_code}"
    ctx.step("api gateway: request without a token is rejected", anon)

    def forged():
        h = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
        p = base64.urlsafe_b64encode(json.dumps({"iss": ISSUER, "aud": NAMES["users"], "email": "evil@example.com"}).encode()).decode().rstrip("=")
        r = post(f"{h}.{p}.")
        assert r.status_code in (401, 403), f"unsigned token got HTTP {r.status_code}, expected 401/403"
        return f"unsigned token rejected with HTTP {r.status_code}"
    ctx.step("api gateway: an unsigned (alg=none) token is rejected", forged)
