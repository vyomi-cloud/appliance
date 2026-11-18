"""Azure reference-arch component 1 (Access): real RS256 Entra JWTs + OIDC discovery + JWKS, validated by the REAL libraries.

msal / azure-identity (ClientSecretCredential, UsernamePasswordCredential over the simulator's HTTPS front, `authority=localhost:<port>`),
PyJWT + PyJWKClient (signature, issuer, audience, claims), refresh-token rotation, v1 and v2 endpoints. Runs the real appliance app (server.py)
in-process with the TLS front on a free port. Needs: pip install azure-identity msal PyJWT cryptography requests (+ the appliance requirements).
"""
import json, os, socket, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
fails = 0
TENANT = "00000000-0000-0000-0000-cloudlearn01"


def check(name, ok, extra=""):
    global fails
    fails += 0 if ok else 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else ' :: ' + str(extra)[:400]}", flush=True)


def start_sim(tls=True):
    """The real appliance app in-process. Returns (http base, https base or '', ca pem path or '')."""
    work = tempfile.mkdtemp(prefix="azentra-")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    os.environ.update({"CLOUDLEARN_STATE_FILE": os.path.join(work, "state.sqlite3"), "VYOMI_AZSB_DB": os.path.join(work, "azsb.sqlite"),
                       "VYOMI_DATA_DIR": work, "VYOMI_AMQP_PORT": "0", "VYOMI_AMQPS_PORT": "0", "CLOUDLEARN_TIER_ENFORCE": "0"})
    if tls:
        os.environ["VYOMI_AZURE_TLS_PORT"] = "0"
    cwd = os.getcwd(); os.chdir(REPO)
    import uvicorn
    import server
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    t0 = time.time()
    while not srv.started:
        if time.time() - t0 > 180:
            raise SystemExit("appliance did not start")
        time.sleep(0.1)
    time.sleep(0.5)
    return f"http://127.0.0.1:{port}", os.environ.get("VYOMI_AZURE_TLS_ENDPOINT", ""), os.environ.get("VYOMI_AZURE_TLS_CA", "")


def main():
    import requests, jwt
    http, tls, ca = start_sim()
    H = {"Authorization": "Bearer x", "Content-Type": "application/json"}
    check("TLS front is up with a CA file", bool(tls) and os.path.exists(ca), (tls, ca))
    os.environ["REQUESTS_CA_BUNDLE"] = ca
    authority_host = tls.split("//", 1)[1]            # localhost:<port>

    # --- directory: resource API app (appRoles + scope), client app (role grant + secret), user pool user
    role_id = "11111111-1111-1111-1111-111111111111"
    api = requests.post(http + "/v1.0/applications", json={"displayName": "facilities-api", "identifierUris": ["api://facilities-api"],
                        "appRoles": [{"id": role_id, "value": "Facilities.Invoke", "displayName": "Invoke", "description": "d", "isEnabled": True,
                                      "allowedMemberTypes": ["Application"]}],
                        "api": {"oauth2PermissionScopes": [{"id": "22222222-2222-2222-2222-222222222222", "value": "Facilities.Read", "isEnabled": True,
                                                            "type": "User", "adminConsentDisplayName": "r", "adminConsentDescription": "r"}]}}, headers=H).json()
    cli = requests.post(http + "/v1.0/applications", json={"displayName": "agent-client", "publicClient": {"redirectUris": ["http://localhost"]},
                        "requiredResourceAccess": [{"resourceAppId": api["appId"], "resourceAccess": [{"id": role_id, "type": "Role"}]}]}, headers=H).json()
    sec = requests.post(http + f"/v1.0/applications/{cli['id']}/addPassword", json={"passwordCredential": {"displayName": "d"}}, headers=H).json()["secretText"]
    user = requests.post(http + "/v1.0/users", json={"displayName": "Dana Facilities", "givenName": "Dana", "surname": "Facilities", "mailNickname": "dana",
                         "userPrincipalName": "dana@vyomi.onmicrosoft.com", "accountEnabled": True,
                         "passwordProfile": {"password": "Fac1lities!pw", "forceChangePasswordNextSignIn": False}}, headers=H).json()
    check("directory seeded (api app with appRoles, client app + secret, user)", bool(api.get("appId") and sec and user.get("id")), (api, user))

    # --- OIDC discovery + JWKS (http and https)
    for base in (http, tls):
        r = requests.get(base + f"/{TENANT}/v2.0/.well-known/openid-configuration", verify=ca if base == tls else True)
        d = r.json()
        check(f"v2 openid-configuration ({base.split(':')[0]})", r.status_code == 200 and d["issuer"] == f"https://login.microsoftonline.com/{TENANT}/v2.0"
              and d["jwks_uri"].startswith(base) and d["token_endpoint"].startswith(base), r.text)
    d1 = requests.get(http + f"/{TENANT}/.well-known/openid-configuration").json()
    check("v1 openid-configuration issuer is sts.windows.net", d1["issuer"] == f"https://sts.windows.net/{TENANT}/", d1)
    k = requests.get(http + "/discovery/v2.0/keys").json()["keys"][0]
    check("JWKS key shape", k["kty"] == "RSA" and k["use"] == "sig" and k["kid"] and k["n"] and k["e"], k)
    ids = requests.get(http + "/us-east-1_AbC123/.well-known/openid-configuration")
    check("Cognito pool ids are not shadowed by the Entra discovery route", "login.microsoftonline" not in ids.text, ids.text[:100])

    # --- azure-identity ClientSecretCredential over TLS: the real flow
    from azure.identity import ClientSecretCredential, UsernamePasswordCredential
    cred = ClientSecretCredential(TENANT, cli["appId"], sec, authority=tls, disable_instance_discovery=True, connection_verify=ca)
    at = cred.get_token("api://facilities-api/.default")
    check("ClientSecretCredential.get_token returns a 3-segment JWT", at.token.count(".") == 2, at.token[:30])
    jwk_client = jwt.PyJWKClient(d["jwks_uri"].replace(tls, http))
    key = jwk_client.get_signing_key_from_jwt(at.token).key
    claims = jwt.decode(at.token, key, algorithms=["RS256"], audience="api://facilities-api", issuer=f"https://login.microsoftonline.com/{TENANT}/v2.0")
    check("PyJWT verifies RS256 signature + iss + aud", True)
    check("app-only claims: azp/appid, tid, oid, sub, roles, ver", claims["azp"] == cli["appId"] and claims["tid"] == TENANT and claims["oid"] == claims["sub"]
          and claims["roles"] == ["Facilities.Invoke"] and claims["ver"] == "2.0" and claims["exp"] > time.time() > claims["iat"] - 5 and "scp" not in claims, claims)
    bad = jwt.decode(at.token, key, algorithms=["RS256"], options={"verify_aud": False, "verify_exp": False})
    tampered = at.token[:-4] + ("AAAA" if not at.token.endswith("AAAA") else "BBBB")
    try:
        jwt.decode(tampered, key, algorithms=["RS256"], audience="api://facilities-api"); ok = False
    except jwt.InvalidTokenError:
        ok = True
    check("tampered token fails signature verification", ok)
    try:
        ClientSecretCredential(TENANT, cli["appId"], "wrong", authority=tls, disable_instance_discovery=True, connection_verify=ca).get_token("api://facilities-api/.default")
        ok = False
    except Exception as e:
        ok = "AADSTS7000215" in str(e) or "invalid_client" in str(e)
    check("wrong client secret rejected by the SDK (AADSTS7000215)", ok)

    # --- v1 endpoint
    r1 = requests.post(http + f"/{TENANT}/oauth2/token", data={"grant_type": "client_credentials", "client_id": cli["appId"], "client_secret": sec, "resource": "api://facilities-api"}).json()
    c1 = jwt.decode(r1["access_token"], key, algorithms=["RS256"], audience="api://facilities-api", issuer=f"https://sts.windows.net/{TENANT}/")
    check("v1 token: iss sts.windows.net, appid, ver 1.0, resource/expires_on in response", c1["appid"] == cli["appId"] and c1["ver"] == "1.0" and r1["resource"] == "api://facilities-api" and "expires_on" in r1, (c1, r1.keys()))

    # msal builds the user-realm URL from the bare hostname (it drops the port), so on a non-443 TLS port tell msal to skip realm discovery
    # (on port 443, e.g. VYOMI_AZURE_TLS_PORT=443 inside the Mesh/Codespace container, nothing is needed).
    import msal.authority
    msal.authority.Authority._domains_without_user_realm_discovery.add("localhost")
    # --- ROPC via azure-identity UsernamePasswordCredential + msal, delegated claims, refresh grant
    upc = UsernamePasswordCredential(cli["appId"], "dana@vyomi.onmicrosoft.com", "Fac1lities!pw", tenant_id=TENANT, authority=tls,
                                     disable_instance_discovery=True, connection_verify=ca)
    ut = upc.get_token("api://facilities-api/Facilities.Read")
    uc = jwt.decode(ut.token, key, algorithms=["RS256"], audience="api://facilities-api")
    check("UsernamePasswordCredential delegated token: scp, upn, preferred_username, oid", uc["scp"] == "Facilities.Read" and uc["upn"] == "dana@vyomi.onmicrosoft.com"
          and uc["preferred_username"] == uc["upn"] and uc["oid"] == user["id"] and "roles" not in uc, uc)
    import msal
    pub = msal.PublicClientApplication(cli["appId"], authority=f"https://{authority_host}/{TENANT}", validate_authority=False, verify=ca)
    res = pub.acquire_token_by_username_password("dana@vyomi.onmicrosoft.com", "Fac1lities!pw", scopes=["api://facilities-api/Facilities.Read"])
    check("msal ROPC returns access_token + id_token + refresh_token", all(res.get(x) for x in ("access_token", "id_token", "refresh_token")), res)
    idc = jwt.decode(res["id_token"], key, algorithms=["RS256"], audience=cli["appId"])
    check("id_token claims (aud=client, preferred_username, tid)", idc["preferred_username"] == "dana@vyomi.onmicrosoft.com" and idc["tid"] == TENANT, idc)
    rr = pub.acquire_token_by_refresh_token(res["refresh_token"], scopes=["api://facilities-api/Facilities.Read"])
    check("msal refresh-token grant returns a new access token + rotated refresh token", rr.get("access_token") and rr.get("refresh_token") and rr["refresh_token"] != res["refresh_token"], rr)
    again = pub.acquire_token_by_refresh_token(res["refresh_token"], scopes=["api://facilities-api/Facilities.Read"])
    check("a used refresh token is rejected (rotation)", "error" in again, again)
    acct = pub.get_accounts(username="dana@vyomi.onmicrosoft.com")
    check("msal cached the account (client_info/id_token accepted)", bool(acct), acct)
    badp = pub.acquire_token_by_username_password("dana@vyomi.onmicrosoft.com", "nope", scopes=["api://facilities-api/.default"])
    check("ROPC wrong password -> AADSTS50126", "AADSTS50126" in json.dumps(badp), badp)
    conf = msal.ConfidentialClientApplication(cli["appId"], client_credential=sec, authority=f"https://{authority_host}/{TENANT}", validate_authority=False, verify=ca)
    cres = conf.acquire_token_for_client(scopes=["api://facilities-api/.default"])
    check("msal ConfidentialClientApplication.acquire_token_for_client", cres.get("access_token", "").count(".") == 2, cres)
    print(f"RESULT fails={fails}", flush=True)
    os._exit(1 if fails else 0)


if __name__ == "__main__":
    main()
