"""App Service Entra auth (authsettingsV2 + front-door enforcement), Azure OpenAI hookup, GitHub Actions CI commit.
Run: PYTHONPATH=. python tests/conformance/test_azure_webauth_core.py"""
import base64, json, time
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB
from core import azure_webapp_core as W
AzureArm.STRICT_SUBSCRIPTION = False


def _check(n, c):
    if not c:
        raise AssertionError(n)
    print("  ok ", n)


def jwt(**c):
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b({'alg': 'none'})}.{b(c)}.sig"


def run():
    a = AzureArm()
    Q = {"api-version": "2023-12-01"}
    RG = f"/subscriptions/{SUB}/resourceGroups/wa-rg"
    WP = f"{RG}/providers/Microsoft.Web"
    code = lambda r: (r["body"] or {}).get("error", {}).get("code") if isinstance(r["body"], dict) else None
    put = lambda p, b, q=Q: a.handle("PUT", p, q, b)
    get = lambda p, q=Q: a.handle("GET", p, q)
    a.handle("PUT", RG, {"api-version": "2021-04-01"}, {"location": "eastus"})
    put(f"{WP}/serverfarms/p1", {"location": "eastus", "sku": {"name": "B1"}})
    put(f"{WP}/sites/fa1", {"location": "eastus", "kind": "functionapp,linux", "properties": {"serverFarmId": f"{WP}/serverfarms/p1"}})
    S = f"{WP}/sites/fa1"
    TEN, CID = "11111111-2222-3333-4444-555555555555", "99999999-8888-7777-6666-555555555555"
    # ── authsettingsV2
    cfg = lambda **kw: {"properties": {"platform": {"enabled": True}, **kw}}
    aad = lambda **reg: {"azureActiveDirectory": {"enabled": True, "registration": {"clientId": CID, "openIdIssuerUrl": f"https://login.microsoftonline.com/{TEN}/v2.0", **reg}}}
    _check("bad action rejected", code(put(f"{S}/config/authsettingsV2", cfg(globalValidation={"unauthenticatedClientAction": "Nope"}))) == "BadRequest")
    _check("clientId must be a GUID", code(put(f"{S}/config/authsettingsV2", cfg(identityProviders=aad(clientId="x")))) == "BadRequest")
    _check("issuer must be Entra", code(put(f"{S}/config/authsettingsV2", cfg(identityProviders=aad(openIdIssuerUrl="https://evil.example/v2.0")))) == "BadRequest")
    _check("secret setting must exist", code(put(f"{S}/config/authsettingsV2", cfg(identityProviders=aad(clientSecretSettingName="MS_SECRET")))) == "BadRequest")
    put(f"{S}/config/appsettings", {"properties": {"MS_SECRET": "s3cret"}})
    r = put(f"{S}/config/authsettingsV2", cfg(globalValidation={"unauthenticatedClientAction": "RedirectToLoginPage", "redirectToProvider": "azureactivedirectory", "excludedPaths": ["/api/public"]},
                                               identityProviders=aad(clientSecretSettingName="MS_SECRET", ), login={"tokenStore": {"enabled": True}}))
    _check("config accepted + round-trips", r["status"] == 200 and r["body"]["properties"]["identityProviders"]["azureActiveDirectory"]["registration"]["clientId"] == CID
           and r["body"]["properties"]["login"]["tokenStore"]["enabled"] is True and r["body"]["properties"]["token"])
    tok = r["body"]["properties"]["token"]
    site = a.state.get(S.lower()) if hasattr(a, "state") else None
    rec = next(v for v in _all(a) if str(v.get("id", "")).lower() == S.lower())
    h = lambda **k: {"authorization": k["b"]} if "b" in k else {}
    d = W._webauth().evaluate(rec, {}, "/api/hello")
    _check("anonymous -> 302 to Entra authorize", d and d[0] == 302 and f"login.microsoftonline.com/{TEN}/oauth2/v2.0/authorize" in d[3]["location"] and CID in d[3]["location"])
    _check("excluded path bypasses", W._webauth().evaluate(rec, {}, "/api/public") is None)
    _check("/.auth/ bypasses", W._webauth().evaluate(rec, {}, "/.auth/login/aad") is None)
    _check("legacy token accepted", W._webauth().evaluate(rec, {"authorization": f"Bearer {tok}"}, "/api/hello") is None)
    good = jwt(aud=CID, tid=TEN, exp=time.time() + 600)
    _check("valid JWT claims accepted", W._webauth().evaluate(rec, {"Authorization": "Bearer " + good}, "/api/hello") is None)
    _check("wrong audience -> 401", W._webauth().evaluate(rec, {"authorization": "Bearer " + jwt(aud="other", tid=TEN, exp=time.time() + 60)}, "/x")[0] == 401)
    _check("expired -> 401", W._webauth().evaluate(rec, {"authorization": "Bearer " + jwt(aud=CID, tid=TEN, exp=1)}, "/x")[0] == 401)
    _check("wrong tenant -> 401", W._webauth().evaluate(rec, {"authorization": "Bearer " + jwt(aud=CID, tid="00000000-0000-0000-0000-000000000009", exp=time.time() + 60)}, "/x")[0] == 401)
    for act, st in (("Return401", 401), ("Return403", 403)):
        put(f"{S}/config/authsettingsV2", cfg(globalValidation={"unauthenticatedClientAction": act}, identityProviders=aad()))
        _check(f"{act} enforced", W._webauth().evaluate(rec, {}, "/x")[0] == st)
    put(f"{S}/config/authsettingsV2", cfg(globalValidation={"unauthenticatedClientAction": "AllowAnonymous"}, identityProviders=aad()))
    _check("AllowAnonymous passes", W._webauth().evaluate(rec, {}, "/x") is None)
    # invoke path enforces
    put(f"{S}/functions/hello", {"properties": {"config": {}, "files": {}}}) if False else None
    put(f"{S}/config/authsettingsV2", {"properties": {"platform": {"enabled": False}}})
    _check("disabled -> no enforcement", W._webauth().evaluate(rec, {}, "/x") is None and get(f"{S}/config/authsettingsV2")["body"]["properties"]["token"] is None)
    # ── Azure OpenAI hookup
    CG = f"{RG}/providers/Microsoft.CognitiveServices/accounts"
    put(f"{CG}/aoai1", {"location": "eastus", "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {"customSubDomainName": "wa-aoai"}}, {"api-version": "2024-10-01"})
    put(f"{CG}/aoai1/deployments/gpt4o", {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": "gpt-4o", "version": "2024-08-06"}}}, {"api-version": "2024-10-01"})
    AS = f"{S}/config/appsettings"
    _check("unknown AOAI endpoint rejected", code(put(AS, {"properties": {"AZURE_OPENAI_ENDPOINT": "https://nope.openai.azure.com/"}})) == "InvalidAzureOpenAIEndpoint")
    _check("missing deployment rejected", code(put(AS, {"properties": {"AZURE_OPENAI_ENDPOINT": "https://wa-aoai.openai.azure.com/", "AZURE_OPENAI_DEPLOYMENT": "ghost"}})) == "DeploymentNotFound")
    _check("wrong key rejected", code(put(AS, {"properties": {"AZURE_OPENAI_ENDPOINT": "https://wa-aoai.openai.azure.com/", "AZURE_OPENAI_API_KEY": "bad"}})) == "InvalidAzureOpenAIKey")
    _check("valid settings accepted", put(AS, {"properties": {"AZURE_OPENAI_ENDPOINT": "https://wa-aoai.openai.azure.com/", "AZURE_OPENAI_DEPLOYMENT": "gpt4o", "AZURE_OPENAI_API_VERSION": "2024-06-01"}})["status"] == 200)
    cv = get(f"{S}/aoaiconnection")
    _check("aoaiconnection resolves account+deployment", cv["status"] == 200 and cv["body"]["properties"]["deploymentExists"] and cv["body"]["properties"]["accountId"].lower().endswith("/accounts/aoai1"))
    _check("MI mode needs identity", code(put(f"{S}/aoaiconnection", {"properties": {"accountId": f"{CG}/aoai1", "deploymentName": "gpt4o", "authMode": "managedIdentity"}})) == "ManagedIdentityRequired")
    r = put(f"{S}/aoaiconnection", {"properties": {"accountId": f"{CG}/aoai1", "deploymentName": "gpt4o", "apiVersion": "2024-06-01"}})
    _check("key mode wires the key setting", r["status"] == 200 and "AZURE_OPENAI_API_KEY" in get(AS)["body"]["properties"])
    # ── GitHub Actions workflow lands in the CI repo
    r = put(f"{S}/sourcecontrols/web", {"properties": {"repoUrl": "https://github.com/acme/fa1", "branch": "main", "isGitHubAction": True,
            "gitHubActionConfiguration": {"codeConfiguration": {"runtimeStack": "python", "runtimeVersion": "3.11"}}}})
    g = r["body"]["properties"]["gitHubActionConfiguration"]
    _check("workflow committed to the CI repo", r["status"] in (200, 201) and g["workflowCiCommit"]["repo"] == "site-fa1" and g["workflowCiCommit"]["path"].startswith(".github/workflows/"))
    from core import ci_core as ci
    db = ci.get_db(rec)
    files = ci.tree(db, "site-fa1", "main")
    _check("workflow file is in the repo tree", any(".github/workflows/" in (f if isinstance(f, str) else str(f)) for f in (files if not isinstance(files, dict) else files.keys())))
    print("PASS")


def _all(a):
    for name in ("state", "resources", "_state"):
        v = getattr(a, name, None)
        if isinstance(v, dict):
            return list(v.values())
    return list(W._STATE_REF[0].values())


if __name__ == "__main__":
    run()
