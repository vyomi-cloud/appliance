"""C1: Entra ID sign-in (app client-credentials + user sign-in, JWT verified against the tenant JWKS), APIM `validate-jwt` in front of the tools,
WAF policies (Front Door + Application Gateway)."""
import base64, json
import requests
from ..runtime import NAMES, LANE, Blocked, RG, LOC, TENANT

USER, PW = "maria.ops@facilities.example.com", "Fac!lities-2026"
API_URI = "api://facilities-api"


def claims(token):
    return json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=" * (-len(token.split(".")[1]) % 4)))


def _graph(ctx, method, path, body=None):
    """Microsoft Graph REST (applications, users). The app registration is plain Graph v1.0; this is the call `az ad app create` makes."""
    r = requests.request(method, f"{ctx.endpoint}/v1.0{path}", json=body, headers={"Authorization": "Bearer vyomi-local"}, timeout=30)
    if r.status_code in (404, 405):
        raise Blocked(LANE["gateway"], f"Graph {method} {path} is not served (HTTP {r.status_code})")
    if r.status_code >= 300 and "already exists" not in r.text.lower():
        raise RuntimeError(f"Graph {method} {path} HTTP {r.status_code}: {r.text[:200]}")
    return r.json() if r.text else {}


def sign_in(ctx):
    ctx.ensure_rg()

    def register():
        app = _graph(ctx, "POST", "/applications", {"displayName": NAMES["users"], "identifierUris": [API_URI]})
        sec = _graph(ctx, "POST", f"/applications/{app['id']}/addPassword", {"passwordCredential": {"displayName": "facilities-agent"}})
        _graph(ctx, "POST", "/users", {"displayName": "Maria Ops", "userPrincipalName": USER, "mailNickname": "maria.ops", "accountEnabled": True,
                                       "passwordProfile": {"password": PW, "forceChangePasswordNextSignIn": False}})
        ctx.state.update(app_id=app["appId"], app_secret=sec["secretText"])
        return f"app registration {NAMES['users']} client_id={app['appId']}, secret, user {USER}"
    ctx.step("entra: app registration + client secret + user (Graph v1.0)", register, lane=LANE["gateway"])
    if "app_id" not in ctx.state:
        ctx.state["user"] = "anonymous (no identity provider yet)"
        return

    def sdk_token():
        from azure.identity import ClientSecretCredential
        # azure-identity requires an https authority: the harness serves the simulator over TLS with a local CA (REQUESTS_CA_BUNDLE), no shim
        cred = ClientSecretCredential(TENANT, ctx.state["app_id"], ctx.state["app_secret"], authority=ctx.endpoint, disable_instance_discovery=True)
        tok = cred.get_token(API_URI + "/.default")
        assert tok.token.count(".") == 2, "access token is not a JWT"
        ctx.state.update(access_token=tok.token, credential=cred)
        return f"azure-identity ClientSecretCredential -> JWT ({len(tok.token)} chars)"
    if not ctx.tls:
        ctx.step("azure-identity ClientSecretCredential gets an app token", lambda: (_ for _ in ()).throw(
            Blocked("https endpoint", "azure-identity refuses a non-https authority; run against https:// (the in-process harness does)")))
    else:
        ctx.step("azure-identity ClientSecretCredential gets an app token (client credentials)", sdk_token, lane=LANE["gateway"])

    def raw_token():
        r = requests.post(f"{ctx.endpoint}/{TENANT}/oauth2/v2.0/token", data={"grant_type": "client_credentials", "client_id": ctx.state["app_id"],
                          "client_secret": ctx.state["app_secret"], "scope": API_URI + "/.default"}, timeout=30)
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:160]}"
        tok = r.json()["access_token"]
        if tok.count(".") != 2:
            raise Blocked(LANE["gateway"], f"access_token is not a JWT ({tok[:24]}...), so a policy cannot validate it")
        ctx.state["access_token"] = tok
        return f"JWT {len(tok)} chars (OAuth2 token endpoint, used when the SDK credential step is blocked)"
    if "access_token" not in ctx.state:
        ctx.step("entra: OAuth2 client-credentials POST /oauth2/v2.0/token returns a JWT", raw_token, lane=LANE["gateway"])

    def user_token():
        from azure.identity import UsernamePasswordCredential
        cred = UsernamePasswordCredential(ctx.state["app_id"], USER, PW, tenant_id=TENANT, authority=ctx.endpoint, disable_instance_discovery=True)
        tok = cred.get_token(API_URI + "/.default")
        c = claims(tok.token)
        assert USER in (c.get("preferred_username"), c.get("upn"), c.get("unique_name"), c.get("email")), c
        ctx.state.update(user=USER, user_token=tok.token, user_claims=c)
        return f"user sign-in (ROPC) as {USER}, JWT claims oid={c.get('oid')}"
    if ctx.tls:
        ctx.step("azure-identity UsernamePasswordCredential: user sign-in", user_token, lane=LANE["gateway"])
    ctx.state.setdefault("user", USER if ctx.state.get("user_token") else "anonymous (no user token)")

    def verify():
        """What the app's backend does: verify the token signature against the tenant's published JWKS (PyJWT)."""
        import jwt
        tok = ctx.state.get("user_token") or ctx.state["access_token"]
        key = jwt.PyJWKClient(f"{ctx.endpoint}/{TENANT}/discovery/v2.0/keys").get_signing_key_from_jwt(tok).key
        c = jwt.decode(tok, key, algorithms=["RS256"], audience=[API_URI, ctx.state["app_id"]], options={"verify_iss": False})
        return f"signature verified against {TENANT} JWKS; aud={c.get('aud')} iss={c.get('iss')}"
    if ctx.state.get("access_token"):
        ctx.step("jwks: the token verifies against the tenant signing keys (RS256)", verify, lane=LANE["gateway"])


def _policy(ctx):
    """The inbound policy a team would write: validate-jwt against the tenant's OpenID configuration, audience check, then the subscription key is enforced by APIM itself."""
    cfg = f"{ctx.endpoint}/{TENANT}/v2.0/.well-known/openid-configuration"
    return ('<policies><inbound><base/>'
            '<validate-jwt header-name="Authorization" failed-validation-httpcode="401" failed-validation-error-message="Unauthorized. Access token is missing or invalid.">'
            f'<openid-config url="{cfg}"/><audiences><audience>{API_URI}</audience><audience>{ctx.state.get("app_id", "")}</audience></audiences></validate-jwt>'
            '<rate-limit-by-key calls="60" renewal-period="60" counter-key="@(context.Subscription.Id)"/>'
            '<set-header name="x-vyomi-caller" exists-action="override"><value>@(context.Request.Headers.GetValueOrDefault("Authorization","").AsJwt()?.Claims.GetValueOrDefault("appid","anonymous"))</value></set-header>'
            '</inbound><backend><base/></backend><outbound><base/></outbound><on-error><base/></on-error></policies>')


def edge(ctx):
    """APIM in front of the kb-search function (read-only knowledge search): subscription key + validate-jwt; WAF policies for Front Door and Application Gateway."""
    from azure.mgmt.apimanagement import ApiManagementClient
    apim = ctx.arm(ApiManagementClient)
    ctx.state["apim_client"] = apim
    backend = f"{ctx.http}/azure-data/functions/{NAMES['functions']}/api"      # the Function App; the simulator's gateway reaches it over its own plain-http address

    def build():
        apim.api_management_service.begin_create_or_update(RG, NAMES["apim"], {"location": LOC, "sku": {"name": "Developer", "capacity": 1}, "publisher_email": "ops@facilities.example.com",
                                                                               "publisher_name": "facilities"}).result()
        apim.api.begin_create_or_update(RG, NAMES["apim"], "tools", {"display_name": "facilities-tools", "path": "tools", "protocols": ["https"], "subscription_required": True,
                                                                     "service_url": backend}).result()
        for op, url in (("kb-search", "/kb-search"), ("asset-status", "/asset-status"), ("create-work-order", "/create-work-order")):
            apim.api_operation.create_or_update(RG, NAMES["apim"], "tools", op, {"display_name": op, "method": "POST", "url_template": url})
        apim.api_policy.create_or_update(RG, NAMES["apim"], "tools", "policy", {"value": _policy(ctx), "format": "xml"})
        apim.subscription.create_or_update(RG, NAMES["apim"], "agent-sub", {"display_name": "facilities agent", "scope": "/apis/tools"})
        ctx.state["apim_key"] = apim.subscription.list_secrets(RG, NAMES["apim"], "agent-sub").primary_key
        return f"APIM {NAMES['apim']}: API tools (3 operations) -> Function App, validate-jwt + subscription key"
    ok = ctx.step("apim: service + API + operations + validate-jwt policy + subscription (azure-mgmt-apimanagement)", build)
    if ok:
        def post(op, key=True, tok=None):
            h = {"Content-Type": "application/json"}
            if key:
                h["Ocp-Apim-Subscription-Key"] = ctx.state["apim_key"]
            if tok:
                h["Authorization"] = "Bearer " + tok
            return requests.post(ctx.apim_url(f"tools/{op}"), json={"query": "boiler pressure limit"}, headers=h, timeout=60)

        def nokey():
            r = post("kb-search", key=False, tok=ctx.state.get("access_token"))
            assert r.status_code == 401, f"HTTP {r.status_code}"
            return "no subscription key -> 401"
        ctx.step("apim: a call without a subscription key is rejected", nokey)

        def notoken():
            r = post("kb-search")
            assert r.status_code == 401, f"no bearer token got HTTP {r.status_code}, expected 401"
            return "subscription key but no JWT -> 401"
        ctx.step("apim validate-jwt: a call without a token is rejected", notoken, lane=LANE["gateway"])

        def forged():
            h = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
            p = base64.urlsafe_b64encode(json.dumps({"aud": API_URI, "appid": "evil"}).encode()).decode().rstrip("=")
            r = post("kb-search", tok=f"{h}.{p}.")
            assert r.status_code == 401, f"unsigned token got HTTP {r.status_code}, expected 401"
            return "alg=none token -> 401"
        ctx.step("apim validate-jwt: an unsigned (alg=none) token is rejected", forged, lane=LANE["gateway"])

        def authed():
            if not ctx.state.get("access_token"):
                raise Blocked(LANE["gateway"], "no Entra JWT to present (the sign-in steps above are blocked)")
            r = post("kb-search", tok=ctx.state.get("user_token") or ctx.state["access_token"])
            assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
            out = r.json()
            assert out.get("results"), out
            return f"HTTP 200 through APIM with the Entra token; caller={out.get('caller')}"
        ctx.step("apim validate-jwt: the Entra-issued token is accepted and the tool answers", authed, lane=LANE["gateway"])

    def waf_fd():
        from azure.mgmt.frontdoor import FrontDoorManagementClient
        c = ctx.arm(FrontDoorManagementClient)
        c.policies.begin_create_or_update(RG, NAMES["waf"], {
            "location": "global", "sku": {"name": "Premium_AzureFrontDoor"}, "policy_settings": {"enabled_state": "Enabled", "mode": "Prevention"},
            "managed_rules": {"managed_rule_sets": [{"rule_set_type": "Microsoft_DefaultRuleSet", "rule_set_version": "2.1"}]}}).result()
        got = c.policies.get(RG, NAMES["waf"])
        assert str(getattr(got.policy_settings.mode, "value", got.policy_settings.mode)) == "Prevention", got.policy_settings
        return f"Front Door WAF policy {got.name} in Prevention mode with the default rule set"
    ctx.step("waf: Front Door policy (azure-mgmt-frontdoor)", waf_fd, lane=LANE["gateway"])

    def waf_appgw():
        from azure.mgmt.network import NetworkManagementClient
        n = ctx.arm(NetworkManagementClient)
        n.web_application_firewall_policies.create_or_update(RG, NAMES["waf"] + "gw", {"location": LOC, "policy_settings": {"state": "Enabled", "mode": "Prevention"},
            "managed_rules": {"managed_rule_sets": [{"rule_set_type": "OWASP", "rule_set_version": "3.2"}]}})
        got = n.web_application_firewall_policies.get(RG, NAMES["waf"] + "gw")
        assert str(getattr(got.policy_settings.mode, "value", got.policy_settings.mode)) == "Prevention", got.policy_settings
        return f"Application Gateway WAF policy {got.name} (OWASP 3.2, Prevention)"
    ctx.step("waf: Application Gateway policy (azure-mgmt-network)", waf_appgw, lane=LANE["gateway"])
    ctx.note("WAF policies are created and read back, not enforced against traffic by the simulator (no L7 firewall engine).")
