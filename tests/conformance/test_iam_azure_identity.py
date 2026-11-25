"""Azure managed identities through the REAL server: IMDS token endpoint, token as an RBAC principal, federated identity credential exchange."""
import base64, json, os, sys, time, uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")
import tempfile as _tf
os.environ.setdefault("CLOUDLEARN_STATE_FILE", os.path.join(_tf.mkdtemp(prefix="vyomi-iam-"), "state.sqlite3"))   # never leak enforcement settings between runs
pytest.importorskip("fastapi")

SUB = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
READER = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
CONTRIB = "b24988ac-6180-42a0-ab88-20f7382dd24c"


def _jwt(**claims):
    e = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")      # noqa: E731
    return e({"alg": "RS256", "typ": "JWT"}) + "." + e(claims) + ".sig"


def _decode(tok):
    p = tok.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


@pytest.fixture(scope="module")
def env():
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    c.put("/api/iam/azure/enforcement", json={"space": "off"})
    uid = uuid.uuid4().hex[:8]
    rg = f"{SUB}/resourceGroups/rg-mi-{uid}"
    assert c.put(rg + "?api-version=2021-04-01", json={"location": "eastus"}).status_code in (200, 201)
    mi = f"{rg}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami-{uid}"
    r = c.put(mi + "?api-version=2023-01-31", json={"location": "eastus"})
    assert r.status_code in (200, 201), r.text
    p = r.json()["properties"]
    fic = c.put(mi + "/federatedIdentityCredentials/gh?api-version=2023-01-31",
                json={"properties": {"issuer": "https://token.actions.githubusercontent.com", "subject": "repo:acme/app:ref:refs/heads/main",
                                     "audiences": ["api://AzureADTokenExchange"]}})
    assert fic.status_code in (200, 201), fic.text
    e = {"c": c, "rg": rg, "mi": mi, "uid": uid, "client": p["clientId"], "principal": p["principalId"]}
    yield e
    c.put("/api/iam/azure/enforcement", json={"space": "off"})
    c.delete(rg + "?api-version=2021-04-01")


def test_imds_requires_header_and_resource_and_finds_the_identity(env):
    c = env["c"]
    base = "/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/"
    r = c.get(base)
    assert r.status_code == 400 and "metadata header" in r.json()["error_description"]
    r = c.get("/metadata/identity/oauth2/token?api-version=2018-02-01", headers={"Metadata": "true"})
    assert r.status_code == 400 and "'resource'" in r.json()["error_description"]
    r = c.get(base + "&client_id=" + str(uuid.uuid4()), headers={"Metadata": "true"})
    assert r.status_code == 400 and r.json()["error_description"] == "Identity not found"
    r = c.get(base + "&client_id=" + env["client"], headers={"Metadata": "true"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["token_type"] == "Bearer" and d["resource"] == "https://management.azure.com/" and d["client_id"] == env["client"] and int(d["expires_on"]) > time.time()
    cl = _decode(d["access_token"])
    assert cl["oid"] == env["principal"] and cl["appid"] == env["client"] and cl["aud"] == "https://management.azure.com/" and cl["idtyp"] == "app"
    assert cl["xms_mirid"].lower() == env["mi"].lower()
    from core import azure_entra_tokens_core as m
    assert m.verify(d["access_token"])                                                      # a real RS256 token published with the JWKS
    r2 = c.get(base + "&object_id=" + env["principal"], headers={"Metadata": "true"})
    assert r2.status_code == 200 and _decode(r2.json()["access_token"])["oid"] == env["principal"]


def test_the_token_is_a_principal_rbac_evaluates(env):
    c, rg = env["c"], env["rg"]
    tok = c.get("/metadata/identity/oauth2/token?resource=https://management.azure.com/&client_id=" + env["client"], headers={"Metadata": "true"}).json()["access_token"]
    new = f"{rg}/providers/Microsoft.Storage/storageAccounts/mi{env['uid']}?api-version=2023-01-01"
    body = {"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}
    c.put("/api/iam/azure/enforcement", json={"space": "enforce"})
    h = {"Authorization": "Bearer " + tok}
    assert c.put(new, headers=h, json=body).status_code == 403                                # no role yet
    ra = c.put(f"{rg}/providers/Microsoft.Authorization/roleAssignments/{uuid.uuid4()}?api-version=2022-04-01",
               json={"properties": {"principalId": env["principal"], "roleDefinitionId": f"{SUB}/providers/Microsoft.Authorization/roleDefinitions/{CONTRIB}", "scope": rg}})
    assert ra.status_code in (200, 201), ra.text
    assert c.put(new, headers=h, json=body).status_code in (200, 201)                         # the identity now acts with its role
    c.put("/api/iam/azure/enforcement", json={"space": "off"})


def test_federated_credential_exchange(env):
    c = env["c"]
    tenant = "00000000-0000-0000-0000-000000000000"

    def exchange(**claims):
        a = _jwt(**claims)
        return c.post(f"/{tenant}/oauth2/v2.0/token", data={"grant_type": "client_credentials", "client_id": env["client"], "scope": "https://management.azure.com/.default",
                      "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", "client_assertion": a})
    ok = dict(iss="https://token.actions.githubusercontent.com", sub="repo:acme/app:ref:refs/heads/main", aud="api://AzureADTokenExchange", exp=time.time() + 300)
    r = exchange(**ok)
    assert r.status_code == 200, r.text
    assert _decode(r.json()["access_token"])["oid"] == env["principal"]
    r = exchange(**dict(ok, sub="repo:acme/app:ref:refs/heads/dev"))
    assert r.status_code == 400 and "AADSTS70021" in r.json()["error_description"] and "repo:acme/app:ref:refs/heads/dev" in r.json()["error_description"]
    r = exchange(**dict(ok, iss="https://evil.example"))
    assert r.status_code == 400 and "AADSTS70021" in r.json()["error_description"]
    r = exchange(**dict(ok, aud="other"))
    assert r.status_code == 400 and "AADSTS70021" in r.json()["error_description"]
    r = exchange(**dict(ok, exp=time.time() - 60))
    assert r.status_code == 400 and "AADSTS700024" in r.json()["error_description"]
    r = c.post(f"/{tenant}/oauth2/v2.0/token", data={"grant_type": "client_credentials", "client_id": str(uuid.uuid4()), "scope": "x/.default",
               "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer", "client_assertion": _jwt(**ok)})
    assert r.status_code == 400 and "AADSTS700016" in r.json()["error_description"]
