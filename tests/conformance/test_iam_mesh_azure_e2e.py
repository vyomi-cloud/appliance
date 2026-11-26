"""Mesh end-to-end for Azure: the REAL appliance app (server.py middleware + ARM core + blob data plane) with the faithful-IAM gate.
Resource group, storage account and role assignments are created through the real ARM endpoints (as root, enforcement off); enforcement is
switched through /api/iam/azure/enforcement; requests come from different principals (X-Cloudlearn-Principal and a bearer token with an
oid / appid claim). Control plane: AuthorizationFailed shape. Data plane: blob dataActions via /azure-data/blob/.
Re-runnable: unique names, the resource group (and everything in it) is deleted afterwards."""
import base64, json, os, sys, uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")
pytest.importorskip("fastapi")

SUB = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
ROLE = lambda guid: f"{SUB}/providers/Microsoft.Authorization/roleDefinitions/{guid}"
READER, CONTRIBUTOR, BLOB_READER = ("acdd72a7-3385-48ef-bd42-f606fba81ae7", "b24988ac-6180-42a0-ab88-20f7382dd24c",
                                    "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1")


def _jwt(**claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return enc({"alg": "none", "typ": "JWT"}) + "." + enc(claims) + ".sig"


@pytest.fixture(scope="module")
def env():
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    c.put("/api/iam/azure/enforcement", json={"space": "off"})
    uid = uuid.uuid4().hex[:8]
    rg = f"{SUB}/resourceGroups/rg-iam-{uid}"
    acct = "sa" + uid
    e = {"c": c, "uid": uid, "rg": rg, "acct": acct, "sa": f"{rg}/providers/Microsoft.Storage/storageAccounts/{acct}",
         "reader": f"oid-reader-{uid}", "contrib": f"oid-contrib-{uid}", "blobber": f"oid-blob-{uid}", "nobody": f"oid-none-{uid}"}
    assert c.put(rg + "?api-version=2021-04-01", json={"location": "eastus"}).status_code in (200, 201)
    r = c.put(e["sa"] + "?api-version=2023-01-01", json={"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"})
    assert r.status_code in (200, 201), r.text
    assert c.put(f"/azure-data/blob/{acct}/cont1?restype=container").status_code == 201
    assert c.put(f"/azure-data/blob/{acct}/cont1/b1.txt", content=b"hi", headers={"x-ms-blob-type": "BlockBlob"}).status_code == 201
    for who, role, scope in ((e["reader"], READER, rg), (e["contrib"], CONTRIBUTOR, rg), (e["blobber"], BLOB_READER, e["sa"])):
        r = c.put(f"{scope}/providers/Microsoft.Authorization/roleAssignments/{uuid.uuid4()}?api-version=2022-04-01",
                  json={"properties": {"principalId": who, "roleDefinitionId": ROLE(role), "scope": scope}})
        assert r.status_code in (200, 201), r.text
    yield e
    c.put("/api/iam/azure/enforcement", json={"space": "off"})
    c.delete(rg + "?api-version=2021-04-01")


def _as(who):
    return {"X-Cloudlearn-Principal": who}


def _settings(c, **doc):
    assert c.put("/api/iam/azure/enforcement", json=doc).status_code == 200


def test_azure_control_plane_enforcement_through_the_real_server(env):
    c, rg, sa = env["c"], env["rg"], env["sa"]
    lst = f"{rg}/providers/Microsoft.Storage/storageAccounts?api-version=2023-01-01"
    body = {"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}
    new = f"{rg}/providers/Microsoft.Storage/storageAccounts/new{env['uid']}?api-version=2023-01-01"

    assert c.put(new, headers=_as(env["nobody"]), json=body).status_code == 200      # off (default): nothing changes
    c.delete(new)

    _settings(c, space="enforce")
    assert c.get(lst, headers=_as(env["reader"])).status_code == 200                  # Reader: */read
    den = c.put(new, headers=_as(env["reader"]), json=body)                          # ... but not write
    assert den.status_code == 403
    err = den.json()["error"]
    assert err["code"] == "AuthorizationFailed"
    assert f"'{env['reader']}'" in err["message"] and "'Microsoft.Storage/storageAccounts/write'" in err["message"]
    assert f"over scope '{rg}/providers/Microsoft.Storage/storageAccounts/new{env['uid']}'" in err["message"]
    assert c.put(new, headers=_as(env["contrib"]), json=body).status_code == 200      # Contributor writes (inherited from the RG scope)
    assert c.delete(new, headers=_as(env["contrib"])).status_code in (200, 202, 204)
    assert c.get(lst, headers=_as(env["nobody"])).status_code == 403                  # no assignment
    # assignment scope is the RG: a sibling resource group is NOT covered
    other = f"{SUB}/resourceGroups/rg-other-{env['uid']}/providers/Microsoft.Storage/storageAccounts?api-version=2023-01-01"
    assert c.get(other, headers=_as(env["reader"])).status_code == 403

    # bearer token: oid claim, and appid claim (service principal)
    assert c.get(lst, headers={"Authorization": "Bearer " + _jwt(oid=env["reader"])}).status_code == 200
    assert c.get(lst, headers={"Authorization": "Bearer " + _jwt(appid=env["nobody"])}).status_code == 403
    assert c.put(new, headers={"Authorization": "Bearer " + _jwt(oid=env["reader"])}, json=body).status_code == 403

    # no identity = the subscription owner (root); strict mode rejects it
    assert c.get(lst).status_code == 200
    _settings(c, space="enforce", unknownPrincipal="deny")
    assert c.get(lst).status_code == 403
    _settings(c, space="enforce")

    # audit never blocks, records would-deny
    _settings(c, space="audit")
    assert c.get(lst, headers=_as(env["nobody"])).status_code == 200
    recs = c.get("/api/iam/azure/audit?limit=20").json()["records"]
    assert any(r["action"] == "Microsoft.Storage/storageAccounts/read" and r["mode"] == "audit" and r["decision"] == "would_deny"
               and r["principal"] == env["nobody"] for r in recs)

    # per-resource override beats space off
    one = sa + "?api-version=2023-01-01"
    _settings(c, space="off", resources={sa: "enforce"})
    assert c.get(one, headers=_as(env["nobody"])).status_code == 403
    assert c.get(lst, headers=_as(env["nobody"])).status_code == 200                  # only that resource is enforced
    _settings(c, space="enforce", services={"Microsoft.Storage": "off"})
    assert c.get(lst, headers=_as(env["nobody"])).status_code == 200                  # service-level off (key = provider namespace)
    assert c.get("/_wire/api/iam/azure/enforcement").status_code == 200


def test_azure_checkaccess_agrees_with_enforcement(env):
    """The effective-access view (/api/iam/azure/evaluate) and the live gate give the same answer for the same request."""
    c = env["c"]
    for who, action, want in ((env["reader"], "Microsoft.Storage/storageAccounts/read", True),
                              (env["reader"], "Microsoft.Storage/storageAccounts/write", False),
                              (env["contrib"], "Microsoft.Storage/storageAccounts/write", True)):
        r = c.post("/api/iam/azure/evaluate", json={"principal": {"object_id": who, "type": "user"}, "action": action, "resource": env["rg"]})
        assert r.status_code == 200 and r.json()["allowed"] is want, (who, action, r.text)


def test_azure_data_plane_blob_dataactions(env):
    c, acct = env["c"], env["acct"]
    blob, lst = f"/azure-data/blob/{acct}/cont1/b1.txt", f"/azure-data/blob/{acct}/cont1?restype=container&comp=list"
    _settings(c, space="enforce")
    assert c.get(blob, headers=_as(env["blobber"])).status_code == 200                # Storage Blob Data Reader (assigned on the account)
    assert c.get(lst, headers=_as(env["blobber"])).status_code == 200
    d = c.put(blob, headers={**_as(env["blobber"]), "x-ms-blob-type": "BlockBlob"}, content=b"x")
    assert d.status_code == 403 and d.json()["error"]["code"] == "AuthorizationFailed"
    assert "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write" in d.json()["error"]["message"]
    # Reader / Contributor have no dataActions: control-plane access does not grant blob data access (as in Azure)
    assert c.get(blob, headers=_as(env["reader"])).status_code == 403
    assert c.get(blob, headers=_as(env["contrib"])).status_code == 403
    assert c.get(blob).status_code == 200                                             # root
    assert c.get(blob, headers={"Authorization": "Bearer " + _jwt(oid=env["blobber"])}).status_code == 200
    _settings(c, space="off")
    assert c.get(blob, headers=_as(env["reader"])).status_code == 200


def test_azure_abac_condition_on_blob_data_plane(env):
    """A role assignment with an ABAC condition on the container name is evaluated against the live request's container (found by the Mesh
    verification run: the gate supplied no attribute context, so every conditional assignment denied)."""
    c, acct, sa = env["c"], env["acct"], env["sa"]
    cond = ("((!(ActionMatches{'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'})) OR "
            "(@Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringEquals 'cont1'))")
    who = "oid-abac-" + env["uid"]
    r = c.put(f"{sa}/providers/Microsoft.Authorization/roleAssignments/{uuid.uuid4()}?api-version=2022-04-01",
              json={"properties": {"principalId": who, "roleDefinitionId": ROLE(BLOB_READER), "scope": sa, "condition": cond, "conditionVersion": "2.0"}})
    assert r.status_code in (200, 201), r.text
    assert c.put(f"/azure-data/blob/{acct}/cont2?restype=container").status_code == 201
    assert c.put(f"/azure-data/blob/{acct}/cont2/b2.txt", content=b"hi", headers={"x-ms-blob-type": "BlockBlob"}).status_code == 201
    _settings(c, space="enforce")
    try:
        assert c.get(f"/azure-data/blob/{acct}/cont1/b1.txt", headers=_as(who)).status_code == 200
        assert c.get(f"/azure-data/blob/{acct}/cont2/b2.txt", headers=_as(who)).status_code == 403
    finally:
        _settings(c, space="off")


def test_azure_legacy_enforce_rbac_flag_still_works(env):
    from core import app_context
    c = env["c"]
    _settings(c, space="off")
    sp = app_context.gcp_active_space_dict()
    if not isinstance(sp, dict) or not sp:
        pytest.skip("no active space record to hold the legacy flag in this process")
    sp["enforce_rbac"] = True
    try:
        lst = f"{env['rg']}/providers/Microsoft.Storage/storageAccounts?api-version=2023-01-01"
        assert c.get(lst, headers=_as(env["nobody"])).status_code == 403
        assert c.get(lst, headers=_as(env["reader"])).status_code == 200
    finally:
        sp.pop("enforce_rbac", None)
