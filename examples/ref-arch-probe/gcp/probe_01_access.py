"""C1 Access: Identity Platform sign-up/sign-in, Google ID token (iamcredentials), API Gateway with JWT security, Cloud Armor security policy. Plain REST: the SDK-less APIs."""
from _common import *

s = Step()
P = PROJECT


def idp():
    r = call("POST", "/v1/accounts:signUp", {"email": f"duty-{TAG}@example.com", "password": "pw-12345", "returnSecureToken": True}, params={"key": "fake"})
    assert r.get("idToken"), r
    r2 = call("POST", "/v1/accounts:signInWithPassword", {"email": f"duty-{TAG}@example.com", "password": "pw-12345", "returnSecureToken": True}, params={"key": "fake"})
    assert r2.get("idToken"), r2
    return "idToken len %d" % len(r2["idToken"])


def idtoken():
    sa = f"projects/-/serviceAccounts/agent-sa@{P}.iam.gserviceaccount.com"
    call("POST", f"/v1/projects/{P}/serviceAccounts", {"accountId": "agent-sa", "serviceAccount": {"displayName": "agent"}}, expect=(200, 201, 409))
    r = call("POST", f"/v1/{sa}:generateIdToken", {"audience": "https://facilities.example.com", "includeEmail": True})
    assert r.get("token", "").count(".") == 2, r
    return "id token is a JWT"


def _spec():
    return {"swagger": "2.0", "info": {"title": "fac", "version": "1"}, "schemes": ["https"], "produces": ["application/json"],
            "paths": {"/ask": {"get": {"operationId": "ask", "x-google-backend": {"address": "https://example.com"}, "security": [{"google_id_token": []}], "responses": {"200": {"description": "ok"}}}}},
            "securityDefinitions": {"google_id_token": {"authorizationUrl": "", "flow": "implicit", "type": "oauth2", "x-google-issuer": "https://accounts.google.com",
                                                        "x-google-jwks_uri": "https://www.googleapis.com/oauth2/v3/certs", "x-google-audiences": "https://facilities.example.com"}}}


def _cfg(api, cid, text):
    import base64
    call("POST", f"/v1/projects/{P}/locations/global/apis/{api}/configs", {"openapiDocuments": [{"document": {"path": "spec", "contents": base64.b64encode(text.encode()).decode()}}]}, params={"apiConfigId": cid})


def apigw_yaml():
    """What a real user uploads: an OpenAPI YAML file (PyYAML block style)."""
    import yaml
    api = f"fac-ay-{TAG}"
    call("POST", f"/v1/projects/{P}/locations/global/apis", {}, params={"apiId": api})
    _cfg(api, "cfg1", yaml.safe_dump(_spec()))
    return "yaml spec accepted"


def apigw_gateway():
    api = f"fac-aj-{TAG}"
    call("POST", f"/v1/projects/{P}/locations/global/apis", {}, params={"apiId": api})
    _cfg(api, "cfg1", json.dumps(_spec()))
    call("POST", f"/v1/projects/{P}/locations/{LOC}/gateways", {"apiConfig": f"projects/{P}/locations/global/apis/{api}/configs/cfg1"}, params={"gatewayId": "gw1"})
    g = call("GET", f"/v1/projects/{P}/locations/{LOC}/gateways/gw1")
    s.gw = g
    return "gateway " + g.get("name", "") + " host " + str(g.get("defaultHostname"))


def apigw_jwt():
    r = http().get(endpoint() + "/gcpgw/gw1/ask")
    assert r.status_code == 401, f"no token should be 401, got {r.status_code} {r.text[:150]}"
    sa = f"projects/-/serviceAccounts/agent-sa@{P}.iam.gserviceaccount.com"
    tok = call("POST", f"/v1/{sa}:generateIdToken", {"audience": "https://facilities.example.com", "includeEmail": True})["token"]
    r2 = http().get(endpoint() + "/gcpgw/gw1/ask", headers={"Authorization": "Bearer " + tok})
    import base64 as _b
    claims = json.loads(_b.urlsafe_b64decode(tok.split(".")[1] + "=="))
    assert r2.status_code != 401, f"token claims iss={claims.get('iss')} aud={claims.get('aud')}; valid sim-issued ID token rejected: {r2.status_code} {r2.text[:150]}"
    return f"no token -> 401; sim-issued token -> HTTP {r2.status_code} {r2.text[:80]}"


def armor():
    r = call("POST", f"/compute/v1/projects/{P}/global/securityPolicies", {"name": f"fac-armor-{TAG}", "rules": [{"priority": 1000, "action": "deny(403)", "match": {"expr": {"expression": "evaluatePreconfiguredExpr('xss-stable')"}}}]})
    got = call("GET", f"/compute/v1/projects/{P}/global/securityPolicies/fac-armor-{TAG}")
    assert got.get("name") == f"fac-armor-{TAG}", got
    return "securityPolicy created"


s("Identity Platform accounts:signUp + signInWithPassword", idp)
s("iamcredentials generateIdToken", idtoken)
s("API Gateway: OpenAPI YAML config upload", apigw_yaml)
s("API Gateway: JSON config + gateway create", apigw_gateway)
s("API Gateway data plane enforces JWT (401 without, accepted with ID token)", apigw_jwt)
s("Cloud Armor compute securityPolicies create/get", armor)
s.finish()
