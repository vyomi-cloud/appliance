"""Component 1 Access: Entra client-credentials token, APIM validate-jwt on an API, WAF policy (Front Door + App Gateway)."""
import base64, hashlib, hmac, json, sys, time, requests
from _common import *

P = Probe(1, "access", "Access: Entra token + APIM validate-jwt + WAF")
B = endpoint(); ensure_rg(B)
H = {"Authorization": "Bearer x", "Content-Type": "application/json"}
S = {}


def entra():
    app = requests.post(B + "/v1.0/applications", json={"displayName": "agent-client"}, headers=H).json()
    sec = requests.post(B + f"/v1.0/applications/{app['id']}/addPassword", json={"passwordCredential": {"displayName": "d"}}, headers=H).json()
    r = requests.post(B + "/tenant1/oauth2/v2.0/token", data={"grant_type": "client_credentials", "client_id": app["appId"], "client_secret": sec["secretText"], "scope": "api://x/.default"})
    assert r.status_code == 200, r.text
    S["token"] = r.json()["access_token"]
    return {"token_prefix": S["token"][:12]}


def is_jwt():
    parts = S["token"].split(".")
    assert len(parts) == 3, f"access_token is not a JWT (opaque, {len(parts)} segments): {S['token'][:20]}..."
    json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
    return "JWT"


def sdk_identity():
    from azure.identity import ClientSecretCredential
    # azure-identity (MSAL) refuses a non-https authority, so the real SDK credential cannot target a local simulator
    ClientSecretCredential("tenant1", "x", "y", authority=B, disable_instance_discovery=True).get_token("api://x/.default")


def jwks():
    r = requests.get(B + "/tenant1/discovery/v2.0/keys")
    assert r.status_code == 200 and "keys" in r.json(), f"{r.status_code} {r.text[:120]}"


apim = {}


def apim_setup():
    from azure.mgmt.apimanagement import ApiManagementClient
    a = arm(ApiManagementClient, B); apim["c"] = a
    a.api_management_service.begin_create_or_update(RG, "apim1", {"location": LOC, "sku": {"name": "Developer", "capacity": 1}, "publisher_email": "a@b.c", "publisher_name": "p"}).result()
    a.api.begin_create_or_update(RG, "apim1", "tools", {"display_name": "tools", "path": "tools", "protocols": ["https"], "subscription_required": True, "service_url": "http://127.0.0.1:1"}).result()
    a.api_operation.create_or_update(RG, "apim1", "tools", "getw", {"display_name": "get", "method": "GET", "url_template": "/w"})
    k = "c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0c2VjcmV0MTI="
    pol = f'<policies><inbound><base/><validate-jwt header-name="Authorization" failed-validation-httpcode="401"><issuer-signing-keys><key>{k}</key></issuer-signing-keys><audiences><audience>api://x</audience></audiences></validate-jwt><return-response><set-status code="200"/><set-body>ok</set-body></return-response></inbound><backend><base/></backend><outbound><base/></outbound></policies>'
    a.api_policy.create_or_update(RG, "apim1", "tools", "policy", {"value": pol, "format": "xml"})
    a.subscription.create_or_update(RG, "apim1", "s1", {"display_name": "s1", "scope": "/apis"})
    apim["key"] = a.subscription.list_secrets(RG, "apim1", "s1").primary_key
    apim["hs"] = base64.b64decode(k)
    return "apim service + api + op + validate-jwt policy + subscription"


def gw(hdr):
    return requests.get(B + "/azure-data/apim/apim1/tools/w", headers=hdr)


def no_key():
    r = gw({}); assert r.status_code == 401 and "subscription key" in r.text, (r.status_code, r.text); return r.text[:80]


def b64(x): return base64.urlsafe_b64encode(x).rstrip(b"=").decode()


def own_jwt_ok():
    h = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()); p = b64(json.dumps({"aud": "api://x", "exp": int(time.time()) + 600}).encode())
    sig = b64(hmac.new(apim["hs"], (h + "." + p).encode(), hashlib.sha256).digest())
    r = gw({"Ocp-Apim-Subscription-Key": apim["key"], "Authorization": f"Bearer {h}.{p}.{sig}"})
    assert r.status_code == 200, (r.status_code, r.text); return "HS256 JWT signed with the policy key -> 200"


def bad_jwt_rejected():
    r = gw({"Ocp-Apim-Subscription-Key": apim["key"], "Authorization": "Bearer not.a.jwt"}); assert r.status_code == 401, r.status_code; return "garbage token -> 401"


def entra_token_through_apim():
    r = gw({"Ocp-Apim-Subscription-Key": apim["key"], "Authorization": "Bearer " + S["token"]})
    assert r.status_code == 200, f"Entra-issued token rejected by validate-jwt: {r.status_code} {r.text[:100]}"


def waf_fd():
    from azure.mgmt.frontdoor import FrontDoorManagementClient
    arm(FrontDoorManagementClient, B).policies.begin_create_or_update(RG, "wafpol", {"location": "global", "sku": {"name": "Premium_AzureFrontDoor"}, "policy_settings": {"enabled_state": "Enabled", "mode": "Prevention"}, "managed_rules": {"managed_rule_sets": [{"rule_set_type": "Microsoft_DefaultRuleSet", "rule_set_version": "2.1"}]}}).result()


def waf_appgw():
    from azure.mgmt.network import NetworkManagementClient
    arm(NetworkManagementClient, B).web_application_firewall_policies.create_or_update(RG, "wafpol2", {"location": LOC, "policy_settings": {"state": "Enabled", "mode": "Prevention"}, "managed_rules": {"managed_rule_sets": [{"rule_set_type": "OWASP", "rule_set_version": "3.2"}]}})


P.step("Entra client-credentials token via /oauth2/v2.0/token (app + secret from Graph)", entra)
P.step("access token is a JWT (so a policy can validate it)", is_jwt, "b")
P.step("azure-identity ClientSecretCredential can reach the token endpoint", sdk_identity, blocked="azure-identity refuses a non-https authority; the probe serves plain http (not a simulator gap)")
P.step("OIDC signing keys endpoint (/discovery/v2.0/keys) for validate-jwt openid-config", jwks)
if P.step("APIM: service, API, operation, validate-jwt policy, subscription (azure-mgmt-apimanagement)", apim_setup):
    P.step("APIM rejects a call with no subscription key", no_key)
    P.step("APIM validate-jwt accepts a correctly signed HS256 JWT", own_jwt_ok)
    P.step("APIM validate-jwt rejects a garbage token", bad_jwt_rejected)
    P.step("APIM validate-jwt accepts the token Entra just issued (the real chain)", entra_token_through_apim, "b")
P.step("WAF policy on Front Door (azure-mgmt-frontdoor)", waf_fd)
P.step("WAF policy on Application Gateway (azure-mgmt-network)", waf_appgw)
P.finish()
