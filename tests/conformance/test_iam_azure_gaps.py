"""Azure faithful-IAM gaps: Shared Key + SAS storage authorization (not RBAC), queue / table / Key Vault data planes driven live through the
real appliance app, root-wire (account-less) Storage paths, Entra group membership in role assignments, management-group feed.
Same style as test_iam_mesh_azure_e2e.py: unique names, the resource group (and everything in it) is deleted afterwards."""
import base64, json, os, sys, uuid
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")

from core import iam_state_adapters as ad
from core.iam_engine import azure_eval, azure_sas, gate, map_azure

SUB = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
ROLE = lambda guid: f"{SUB}/providers/Microsoft.Authorization/roleDefinitions/{guid}"          # noqa: E731
QUEUE_CONTRIB, QUEUE_SENDER, TABLE_CONTRIB, SECRETS_USER, SECRETS_OFFICER, BLOB_READER = (
    "974c5e8b-45b9-4653-ba55-5f855dd0fb88", "c6a89b2d-59bc-44d0-9896-0f6e12d7b80a", "0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3", "4633458b-17de-408a-b874-0445c86b69e6",
    "b86a8fe4-44ce-4948-aee5-eccb2c155cd7", "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1")
FAR = "2099-01-01T00:00:00Z"
BLOB, QUEUE, TABLE = ("Microsoft.Storage/storageAccounts/blobServices/containers/blobs", "Microsoft.Storage/storageAccounts/queueServices/queues/messages",
                      "Microsoft.Storage/storageAccounts/tableServices/tables/entities")


# ------------------------------------------------------------------------------------------------ unit: map
def test_root_wire_paths_are_mapped_with_the_account_from_host_or_shared_key():
    got = map_azure.required("POST", "/azure-data/queue-core/jobs/messages", host="sa1.queue.localtest.me")
    assert got == [{"action": QUEUE + "/add/action", "resource": "/sa1/jobs/messages", "data": True}]
    sk = map_azure.required("GET", "/azure-data/queue-core/jobs/messages?peekonly=true", headers={"Authorization": "SharedKey sa2:c2ln"})
    assert sk[0]["action"] == QUEUE + "/read" and sk[0]["resource"] == "/sa2/jobs/messages"
    anon = map_azure.required("GET", "/azure-data/tableroot/Tables")
    assert anon[0]["resource"] == "/_default/Tables" and anon[0]["data"] is True
    put = map_azure.required("PUT", "/azure-data/queue-core/jobs/messages/m1", host="sa1.queue.localtest.me")
    assert put[0]["hint"] == "update" and map_azure.required("GET", "/azure-data/blob/sa1/c?restype=container&comp=list")[0]["hint"] == "list"


# ------------------------------------------------------------------------------------------------ unit: SAS / Shared Key rule
def ev(action, resource, principal, state=None, hint=None, data=True, now=None):
    req = {"cloud": "azure", "principal": principal, "action": action, "resource": resource, "context": {"hint": hint} if hint else {}, "data": data}
    return azure_sas.evaluate(req, state or {}, rbac=azure_eval._rbac, now=now)


def sas(account="sa1", **tok):
    return {"object_id": "sas:x", "type": "sas", "account": account, "sas": dict({"sv": "2021-08-06", "sig": "x", "se": FAR}, **tok)}


def test_sas_permissions_decide_not_rbac():
    b = "/sa1/c/b.txt"
    assert ev(BLOB + "/read", b, sas(sp="r", sr="b"))["allowed"] is True
    d = ev(BLOB + "/write", b, sas(sp="r", sr="b"))
    assert d["allowed"] is False and d["storageError"]["code"] == "AuthorizationPermissionMismatch" and d["storageError"]["status"] == 403
    assert ev(BLOB + "/write", b, sas(sp="w", sr="b"))["allowed"] is True and ev(BLOB + "/write", b, sas(sp="c", sr="b"))["allowed"] is True
    assert ev(BLOB + "/delete", b, sas(sp="rw", sr="b"))["allowed"] is False and ev(BLOB + "/delete", b, sas(sp="d", sr="b"))["allowed"] is True
    assert ev(BLOB + "/tags/read", b, sas(sp="t", sr="b"))["allowed"] is True
    assert ev(BLOB + "/add/action", b, sas(sp="a", sr="b"))["allowed"] is True
    # list needs `l`, read needs `r`
    lst = "/sa1/c"
    assert ev(BLOB + "/read", lst, sas(sp="r", sr="c"), hint="list")["allowed"] is False
    assert ev(BLOB + "/read", lst, sas(sp="rl", sr="c"), hint="list")["allowed"] is True
    assert ev(BLOB + "/read", lst, sas(sp="r", sr="b"), hint="list")["storageError"]["code"] == "AuthorizationResourceTypeMismatch"   # blob SAS cannot list


def test_sas_expiry_start_account_and_control_plane():
    b = "/sa1/c/b.txt"
    now = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    assert ev(BLOB + "/read", b, sas(sp="r", sr="b", se="2026-11-23T11:00:00Z"), now=now)["storageError"]["code"] == "AuthenticationFailed"
    assert ev(BLOB + "/read", b, sas(sp="r", sr="b", se="2026-11-23T13:00:00Z"), now=now)["allowed"] is True
    assert ev(BLOB + "/read", b, sas(sp="r", sr="b", st="2026-11-23T13:00:00Z"), now=now)["allowed"] is False
    assert ev(BLOB + "/read", "/other/c/b", sas(sp="r", sr="b"))["storageError"]["code"] == "AuthenticationFailed"       # token of another account
    arm = ev("Microsoft.Storage/storageAccounts/read", "/subscriptions/s/resourceGroups/r/providers/Microsoft.Storage/storageAccounts/sa1", sas(sp="r", sr="b"), data=False)
    assert arm["allowed"] is False                                                                                       # SAS never reaches ARM
    assert ev("Microsoft.KeyVault/vaults/secrets/getSecret/action", "/vaults/v/secrets/s", sas(sp="r", sr="b"))["allowed"] is False


def test_account_sas_scope_services_and_resource_types():
    acct = lambda **k: sas(ss="bqt", srt="sco", sp="rwdlacup", **k)           # noqa: E731
    assert ev(BLOB + "/read", "/sa1/c/b", acct())["allowed"] is True
    assert ev(QUEUE + "/add/action", "/sa1/q/messages", acct())["allowed"] is True
    assert ev(TABLE + "/add/action", "/sa1/t", acct())["allowed"] is True
    only_blob = sas(ss="b", srt="o", sp="rw")
    assert ev(BLOB + "/read", "/sa1/c/b", only_blob)["allowed"] is True
    assert ev(QUEUE + "/read", "/sa1/q/messages", only_blob)["storageError"]["code"] == "AuthorizationResourceTypeMismatch"      # service not in ss
    assert ev(BLOB + "/read", "/sa1/c", only_blob, hint="list")["storageError"]["code"] == "AuthorizationResourceTypeMismatch"   # container level not in srt
    assert ev(BLOB + "/read", "/sa1", sas(ss="b", srt="s", sp="l"), hint="list")["allowed"] is True                              # list containers
    # queue: peek = r, dequeue = p, add = a, update = u
    q = lambda **k: sas(sp=k.pop("sp"))                                                                                            # noqa: E731
    assert ev(QUEUE + "/read", "/sa1/q/messages", q(sp="r"))["allowed"] is True
    assert ev(QUEUE + "/process/action", "/sa1/q/messages", q(sp="r"))["allowed"] is False
    assert ev(QUEUE + "/process/action", "/sa1/q/messages", q(sp="p"))["allowed"] is True
    assert ev(QUEUE + "/process/action", "/sa1/q/messages/m", q(sp="p"), hint="update")["allowed"] is False
    assert ev(QUEUE + "/process/action", "/sa1/q/messages/m", q(sp="u"), hint="update")["allowed"] is True
    # table: entities
    assert ev(TABLE + "/read", "/sa1/t", sas(sp="r"))["allowed"] is True and ev(TABLE + "/add/action", "/sa1/t", sas(sp="r"))["allowed"] is False
    assert ev(TABLE + "/update/action", "/sa1/t", sas(sp="u"))["allowed"] is True and ev(TABLE + "/delete", "/sa1/t", sas(sp="d"))["allowed"] is True


def test_shared_key_is_full_access_to_its_own_account_only():
    sk = {"object_id": "sharedkey:sa1", "type": "sharedkey", "account": "sa1"}
    for act, res in ((BLOB + "/write", "/sa1/c/b"), (BLOB + "/delete", "/sa1/c/b"), (QUEUE + "/delete", "/sa1/q/messages"), (TABLE + "/delete", "/sa1/t")):
        assert ev(act, res, sk)["allowed"] is True, act
    assert ev(BLOB + "/read", "/sa2/c/b", sk)["storageError"]["code"] == "AuthenticationFailed"
    assert ev("Microsoft.Storage/storageAccounts/write", "/subscriptions/s", sk, data=False)["allowed"] is False
    off = {"storage_accounts": {"sa1": {"allowSharedKeyAccess": False}}}
    assert ev(BLOB + "/read", "/sa1/c/b", sk, off)["storageError"]["code"] == "KeyBasedAuthenticationNotPermitted"
    assert ev(BLOB + "/read", "/sa1/c/b", sas(sp="r", sr="b"), off)["storageError"]["code"] == "KeyBasedAuthenticationNotPermitted"


def test_user_delegation_sas_is_the_intersection_with_the_delegators_rbac():
    st = {"role_assignments": [{"id": "a", "principal_id": "oid-d", "role_definition_id": BLOB_READER, "scope": "/subscriptions/s"}],
          "data_scopes": {"/sa1": "/subscriptions/s/resourceGroups/r/providers/Microsoft.Storage/storageAccounts/sa1"}}
    assert ev(BLOB + "/read", "/sa1/c/b", sas(sp="r", sr="b", skoid="oid-d"), st)["allowed"] is True
    assert ev(BLOB + "/read", "/sa1/c/b", sas(sp="r", sr="b", skoid="oid-nobody"), st)["allowed"] is False         # delegator has no data role
    assert ev(BLOB + "/write", "/sa1/c/b", sas(sp="w", sr="b", skoid="oid-d"), st)["allowed"] is False             # token allows it, role does not


def test_gate_answers_with_the_storage_error_shape():
    pr = sas(sp="r", sr="b")
    hr = {"method": "PUT", "path": "/azure-data/blob/sa1/c/b", "headers": {"host": "localhost"}, "query": "sp=r", "principal": pr}
    spec = gate.check("azure", hr, {}, {"space": "enforce"})
    assert spec["status"] == 403 and "<Code>AuthorizationPermissionMismatch</Code>" in spec["body"] and spec["headers"]["x-ms-error-code"] == "AuthorizationPermissionMismatch"
    assert gate.check("azure", dict(hr, method="GET"), {}, {"space": "enforce"}) is None


# ------------------------------------------------------------------------------------------------ unit: adapters
def test_principal_resolution_order():
    h = lambda **k: {k2.lower(): v for k2, v in k.items()}                       # noqa: E731
    assert ad.azure_principal(h(Authorization="SharedKey sa1:abc"), {})["type"] == "sharedkey"
    assert ad.azure_principal(h(Authorization="SharedKey sa1:abc"), {})["account"] == "sa1"
    p = ad.azure_principal({}, {}, "sv=2021-08-06&sp=rl&se=2099-01-01T00%3A00%3A00Z&sig=zz&sr=c")
    assert p["type"] == "sas" and p["sas"]["sp"] == "rl" and p["sas"]["sr"] == "c"
    assert ad.azure_principal({}, {}, "api-version=2021-04-01")["type"] == "root"                  # not a SAS (no sig)
    assert ad.azure_principal(h(**{"X-Cloudlearn-Principal": "oid-1", "Authorization": "SharedKey sa1:abc"}), {})["object_id"] == "oid-1"   # explicit override wins


def test_graph_groups_and_upn_resolution_feed_the_engine():
    import types
    g = types.SimpleNamespace(users={"u-1": {"userPrincipalName": "Ann@contoso.com", "mail": None}}, groups={"g-1": {}, "g-2": {}},
                              group_members={"g-1": {"u-1"}, "g-2": {"g-1"}}, service_principals={"sp-1": {"appId": "app-1"}})
    assert ad.azure_groups(g) == {"g-1": ["u-1"], "g-2": ["g-1"]}
    assert ad.azure_principal({"x-cloudlearn-principal": "ann@contoso.com"}, {}, "", g)["object_id"] == "u-1"
    assert ad.azure_principal({"x-cloudlearn-principal": "app-1"}, {}, "", g)["object_id"] == "sp-1"
    sa = f"{SUB}/resourceGroups/r/providers/Microsoft.Storage/storageAccounts/sa1"
    arm = {"sa": {"_type": "microsoft.storage/storageaccounts", "id": sa, "name": "sa1", "properties": {}},
           "ra": {"_type": "microsoft.authorization/roleassignments", "id": sa + "/providers/Microsoft.Authorization/roleAssignments/x",
                  "properties": {"principalId": "g-2", "roleDefinitionId": ROLE(BLOB_READER)}}}
    st = ad.azure_state(arm, None, g)
    assert st["groups"]["g-2"] == ["g-1"] and st["data_scopes"]["/_default"] == sa and st["storage_accounts"]["sa1"]["allowSharedKeyAccess"] is True
    d = azure_eval.evaluate({"cloud": "azure", "principal": {"object_id": "u-1", "type": "user"}, "action": BLOB + "/read", "resource": "/sa1/c/b", "data": True}, st)
    assert d["allowed"] is True and d["matched"][0]["statement"]["principalId"] == "g-2"          # user -> g-1 -> g-2 (nested) -> assignment


def test_management_groups_are_fed_when_a_store_models_them():
    arm = {"mg": {"_type": "microsoft.management/managementgroups", "name": "mg-child", "id": "/providers/Microsoft.Management/managementGroups/mg-child",
                  "properties": {"details": {"parent": {"id": "/providers/Microsoft.Management/managementGroups/mg-root"}}}},
           "mr": {"_type": "microsoft.management/managementgroups", "name": "mg-root", "properties": {}},
           "ms": {"_type": "microsoft.management/managementgroups/subscriptions", "name": "sub1",
                  "id": "/providers/Microsoft.Management/managementGroups/mg-child/subscriptions/sub1"}}
    st = ad.azure_state(arm)
    assert st["management_groups"] == {"mg-child": "mg-root", "mg-root": None} and st["subscriptions"] == {"sub1": "mg-child"}
    st["role_assignments"] = [{"id": "a", "principal_id": "p", "role_definition_id": "Reader", "scope": "/providers/Microsoft.Management/managementGroups/mg-root"}]
    assert azure_eval.evaluate({"cloud": "azure", "principal": {"object_id": "p", "type": "user"}, "action": "Microsoft.Storage/storageAccounts/read",
                                "resource": "/subscriptions/sub1/resourceGroups/r"}, st)["allowed"] is True


# ------------------------------------------------------------------------------------------------ live: the real app
def _jwt(**claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")      # noqa: E731
    return enc({"alg": "none", "typ": "JWT"}) + "." + enc(claims) + ".sig"


@pytest.fixture(scope="module")
def env():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import server
    os.environ["VYOMI_AZURE_STORAGE_SUFFIX"] = "localtest.me"       # host-style queue endpoint -> the queue core (what the SDKs hit)
    c = TestClient(server.app)
    c.put("/api/iam/azure/enforcement", json={"space": "off"})
    uid = uuid.uuid4().hex[:8]
    rg = f"{SUB}/resourceGroups/rg-iamg-{uid}"
    e = {"c": c, "uid": uid, "rg": rg, "acct": "sg" + uid, "acct2": "sk" + uid, "vault": "kv" + uid, "queue": "q" + uid, "table": "t" + uid,
         "who": {n: f"oid-{n}-{uid}" for n in ("queue", "qsend", "table", "kvu", "kvo", "none")}, "made_users": [], "made_groups": []}
    e["sa"] = f"{rg}/providers/Microsoft.Storage/storageAccounts/{e['acct']}"
    e["kv"] = f"{rg}/providers/Microsoft.KeyVault/vaults/{e['vault']}"
    assert c.put(rg + "?api-version=2021-04-01", json={"location": "eastus"}).status_code in (200, 201)
    body = {"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}
    assert c.put(e["sa"] + "?api-version=2023-01-01", json=body).status_code in (200, 201)
    off = dict(body, properties={"allowSharedKeyAccess": False})
    assert c.put(f"{rg}/providers/Microsoft.Storage/storageAccounts/{e['acct2']}?api-version=2023-01-01", json=off).status_code in (200, 201)
    r = c.put(e["kv"] + "?api-version=2022-07-01", json={"location": "eastus", "properties": {"tenantId": "00000000-0000-0000-0000-000000000000", "sku": {"family": "A", "name": "standard"}}})
    assert r.status_code in (200, 201), r.text
    # data, created as root (enforcement off)
    qh = {"host": f"{e['acct']}.queue.localtest.me", "x-ms-version": "2021-08-06", "Content-Type": "application/xml"}
    assert c.put(f"/{e['queue']}", headers=qh).status_code == 201
    th = {"Content-Type": "application/json", "Accept": "application/json;odata=nometadata"}
    assert c.post(f"/azure-data/table/{e['acct']}/Tables", content=json.dumps({"TableName": e["table"]}), headers=th).status_code == 201
    assert c.put(f"/azure-data/keyvault/{e['vault']}/secrets/s1?api-version=7.4", json={"value": "v"}).status_code == 200
    assert c.put(f"/azure-data/blob/{e['acct']}/cont1?restype=container").status_code == 201
    assert c.put(f"/azure-data/blob/{e['acct']}/cont1/b1.txt", content=b"hi", headers={"x-ms-blob-type": "BlockBlob"}).status_code == 201
    # Entra: a user in a group nested in another group
    gname = lambda n: {"displayName": n, "mailEnabled": False, "mailNickname": n, "securityEnabled": True}      # noqa: E731
    e["g_inner"] = c.post("/v1.0/groups", json=gname("gi" + uid)).json()["id"]
    e["g_outer"] = c.post("/v1.0/groups", json=gname("go" + uid)).json()["id"]
    e["upn"] = f"gu{uid}@contoso.onmicrosoft.com"
    e["user"] = c.post("/v1.0/users", json={"displayName": "gu" + uid, "userPrincipalName": e["upn"], "mailNickname": "gu" + uid, "accountEnabled": True,
                                            "passwordProfile": {"password": "Xx1!aaaaaaaa"}}).json()["id"]
    e["made_groups"] += [e["g_inner"], e["g_outer"]]
    assert c.post(f"/v1.0/groups/{e['g_inner']}/members/$ref", json={"@odata.id": f"/v1.0/users/{e['user']}"}).status_code in (200, 204)
    assert c.post(f"/v1.0/groups/{e['g_outer']}/members/$ref", json={"@odata.id": f"/v1.0/groups/{e['g_inner']}"}).status_code in (200, 204)
    assigns = ((e["who"]["queue"], QUEUE_CONTRIB, e["sa"]), (e["who"]["qsend"], QUEUE_SENDER, e["sa"]), (e["who"]["table"], TABLE_CONTRIB, rg), (e["who"]["kvu"], SECRETS_USER, e["kv"]),
               (e["who"]["kvo"], SECRETS_OFFICER, rg), (e["g_outer"], BLOB_READER, e["sa"]))
    for who, role, scope in assigns:
        r = c.put(f"{scope}/providers/Microsoft.Authorization/roleAssignments/{uuid.uuid4()}?api-version=2022-04-01",
                  json={"properties": {"principalId": who, "roleDefinitionId": ROLE(role), "scope": scope}})
        assert r.status_code in (200, 201), r.text
    yield e
    c.put("/api/iam/azure/enforcement", json={"space": "off"})
    c.delete(rg + "?api-version=2021-04-01")
    for g in e["made_groups"]:
        c.delete(f"/v1.0/groups/{g}")
    c.delete(f"/v1.0/users/{e['user']}")
    os.environ.pop("VYOMI_AZURE_STORAGE_SUFFIX", None)


def _as(who):
    return {"X-Cloudlearn-Principal": who}


def _on(c, **doc):
    assert c.put("/api/iam/azure/enforcement", json=doc).status_code == 200


def _code(r):
    return r.headers.get("x-ms-error-code") or (r.json().get("error", {}).get("code") if "json" in r.headers.get("content-type", "") else "")


def test_live_queue_data_plane_rbac(env):
    c, q, qh = env["c"], env["queue"], {"host": f"{env['acct']}.queue.localtest.me", "x-ms-version": "2021-08-06", "Content-Type": "application/xml"}
    msg = b"<QueueMessage><MessageText>aGk=</MessageText></QueueMessage>"
    _on(c, space="enforce")
    ok = c.post(f"/{q}/messages", headers={**qh, **_as(env["who"]["qsend"])}, content=msg)
    assert ok.status_code == 201, ok.text                                                              # Queue Data Message Sender: messages/add/action
    assert c.get(f"/{q}/messages?peekonly=true", headers={**qh, **_as(env["who"]["qsend"])}).status_code == 403   # the sender role cannot read
    assert c.get(f"/{q}/messages?peekonly=true", headers={**qh, **_as(env["who"]["queue"])}).status_code == 200  # Queue Data Contributor: messages/read
    assert c.get(f"/{q}/messages", headers={**qh, **_as(env["who"]["queue"])}).status_code == 200               # dequeue = messages/process/action
    den = c.post(f"/{q}/messages", headers={**qh, **_as(env["who"]["none"])}, content=msg)
    assert den.status_code == 403 and den.json()["error"]["code"] == "AuthorizationFailed"
    assert "queueServices/queues/messages/add/action" in den.json()["error"]["message"]
    assert c.get(f"/{q}/messages?peekonly=true", headers={**qh, **_as(env["who"]["table"])}).status_code == 403   # a table role is not a queue role
    assert c.get(f"/{q}/messages?peekonly=true", headers=qh).status_code == 200                       # no identity = root
    _on(c, space="off")


def test_live_table_data_plane_rbac(env):
    c, t, a = env["c"], env["table"], env["acct"]
    th = {"Content-Type": "application/json", "Accept": "application/json;odata=nometadata"}
    ent = json.dumps({"PartitionKey": "p", "RowKey": "r1", "v": "1"})
    _on(c, space="enforce")
    assert c.post(f"/azure-data/table/{a}/{t}", content=ent, headers={**th, **_as(env["who"]["table"])}).status_code == 201   # Table Data Contributor (RG scope)
    assert c.get(f"/azure-data/table/{a}/{t}", headers={**th, **_as(env["who"]["table"])}).status_code == 200
    den = c.post(f"/azure-data/table/{a}/{t}", content=ent.replace("r1", "r2"), headers={**th, **_as(env["who"]["queue"])})
    assert den.status_code == 403 and den.json()["error"]["code"] == "AuthorizationFailed"
    assert "tableServices/tables/entities/add/action" in den.json()["error"]["message"]
    assert c.get(f"/azure-data/table/{a}/Tables", headers={**th, **_as(env["who"]["none"])}).status_code == 403
    # the account-less root wire maps too (account `_default` -> the Azure space's storage account)
    assert c.get(f"/azure-data/tableroot/{t}", headers={**th, **_as(env["who"]["none"])}).status_code == 403
    _on(c, space="off")


def test_live_key_vault_data_plane_rbac(env):
    c, v = env["c"], env["vault"]
    s1, s2 = f"/azure-data/keyvault/{v}/secrets/s1?api-version=7.4", f"/azure-data/keyvault/{v}/secrets/s2?api-version=7.4"
    _on(c, space="enforce")
    assert c.get(s1, headers=_as(env["who"]["kvu"])).status_code == 200                                # Secrets User (vault scope): getSecret
    d = c.put(s2, headers=_as(env["who"]["kvu"]), json={"value": "x"})
    assert d.status_code == 403 and "secrets/setSecret/action" in d.json()["error"]["message"]        # ... but not setSecret
    assert c.put(s2, headers=_as(env["who"]["kvo"]), json={"value": "x"}).status_code == 200           # Secrets Officer (RG scope)
    assert c.delete(f"/azure-data/keyvault/{v}/secrets/s2?api-version=7.4", headers=_as(env["who"]["kvo"])).status_code in (200, 204)
    assert c.get(s1, headers=_as(env["who"]["none"])).status_code == 403
    assert c.get(s1, headers={"Authorization": "Bearer " + _jwt(oid=env["who"]["kvu"])}).status_code == 200
    assert c.get(f"/azure-data/keyvault/{v}/secrets/s1?api-version=7.4&sv=2021-08-06&sp=r&sig=zz").status_code == 200   # a SAS has no meaning on Key Vault: still root
    _on(c, space="off")


def test_live_group_membership_and_upn(env):
    c, a = env["c"], env["acct"]
    blob = f"/azure-data/blob/{a}/cont1/b1.txt"
    _on(c, space="enforce")
    assert c.get(blob, headers=_as(env["user"])).status_code == 200                                    # user -> inner group -> outer group (Blob Data Reader)
    assert c.get(blob, headers=_as(env["upn"])).status_code == 200                                     # the UPN resolves to the same object
    d = c.put(blob, headers={**_as(env["user"]), "x-ms-blob-type": "BlockBlob"}, content=b"x")
    assert d.status_code == 403 and "blobs/write" in d.json()["error"]["message"]
    c.delete(f"/v1.0/groups/{env['g_inner']}/members/{env['user']}/$ref")
    assert c.get(blob, headers=_as(env["user"])).status_code == 403                                    # membership removed: access gone
    assert c.post(f"/v1.0/groups/{env['g_inner']}/members/$ref", json={"@odata.id": f"/v1.0/users/{env['user']}"}).status_code in (200, 204)
    _on(c, space="off")


def test_live_sas_authorizes_by_token_permissions(env):
    c, a = env["c"], env["acct"]
    tok = lambda **k: "&".join(f"{n}={v}" for n, v in dict({"sv": "2021-08-06", "se": FAR, "sig": "Zm9v"}, **k).items())      # noqa: E731
    blob = f"/azure-data/blob/{a}/cont1/b1.txt"
    _on(c, space="enforce")
    assert c.get(f"{blob}?{tok(sp='r', sr='b')}").status_code == 200                                   # no RBAC role anywhere: the token is the authorization
    w = c.put(f"{blob}?{tok(sp='r', sr='b')}", content=b"x", headers={"x-ms-blob-type": "BlockBlob"})
    assert w.status_code == 403 and _code(w) == "AuthorizationPermissionMismatch" and "<Code>AuthorizationPermissionMismatch</Code>" in w.text
    assert c.put(f"{blob}?{tok(sp='rw', sr='b')}", content=b"x2", headers={"x-ms-blob-type": "BlockBlob"}).status_code == 201
    assert c.delete(f"{blob}?{tok(sp='rw', sr='b')}").status_code == 403
    exp = c.get(f"{blob}?{tok(sp='r', sr='b', se='2020-01-01T00:00:00Z')}")
    assert exp.status_code == 403 and _code(exp) == "AuthenticationFailed"                             # expired
    lst = f"/azure-data/blob/{a}/cont1?restype=container&comp=list"
    assert c.get(f"{lst}&{tok(sp='rl', sr='c')}").status_code == 200
    assert c.get(f"{lst}&{tok(sp='r', sr='c')}").status_code == 403                                    # list needs `l`
    assert _code(c.get(f"{lst}&{tok(sp='rl', sr='b')}")) == "AuthorizationResourceTypeMismatch"
    assert c.get(f"{blob}?{tok(sp='r', sr='b')}", headers=_as(env["who"]["none"])).status_code == 403  # an explicit identity header outranks the token (test override)
    # queue (host-style, queue core): add needs `a`, peek `r`, dequeue `p`
    qh = {"host": f"{a}.queue.localtest.me", "x-ms-version": "2021-08-06", "Content-Type": "application/xml"}
    q = env["queue"]
    msg = b"<QueueMessage><MessageText>aGk=</MessageText></QueueMessage>"
    assert c.post(f"/{q}/messages?{tok(sp='a')}", headers=qh, content=msg).status_code == 201
    assert c.get(f"/{q}/messages?peekonly=true&{tok(sp='a')}", headers=qh).status_code == 403
    assert c.get(f"/{q}/messages?peekonly=true&{tok(sp='r')}", headers=qh).status_code == 200
    assert c.get(f"/{q}/messages?{tok(sp='r')}", headers=qh).status_code == 403                        # dequeue = Process
    assert c.get(f"/{q}/messages?{tok(sp='p')}", headers=qh).status_code == 200
    # table: account SAS (ss=t srt=co), query needs r, insert needs a
    t = env["table"]
    th = {"Content-Type": "application/json", "Accept": "application/json;odata=nometadata"}
    assert c.get(f"/azure-data/table/{a}/{t}?{tok(sp='r', ss='t', srt='co')}", headers=th).status_code == 200
    ins = c.post(f"/azure-data/table/{a}/{t}?{tok(sp='r', ss='t', srt='co')}", content=json.dumps({"PartitionKey": "p", "RowKey": "s1"}), headers=th)
    assert ins.status_code == 403
    assert c.post(f"/azure-data/table/{a}/{t}?{tok(sp='ra', ss='t', srt='co')}", content=json.dumps({"PartitionKey": "p", "RowKey": "s1"}), headers=th).status_code == 201
    assert c.get(f"{blob}?{tok(sp='r', ss='t', srt='co')}").status_code == 403                        # table-only account SAS on a blob
    _on(c, space="off")


def test_live_shared_key_full_access_own_account_only(env):
    c, a, a2 = env["c"], env["acct"], env["acct2"]
    sk = lambda acct: {"Authorization": f"SharedKey {acct}:c2ln", "x-ms-version": "2021-08-06"}          # noqa: E731
    blob = f"/azure-data/blob/{a}/cont1/b1.txt"
    _on(c, space="enforce")
    assert c.get(blob, headers=sk(a)).status_code == 200                                               # no role assignment, the account key is enough
    assert c.put(f"/azure-data/blob/{a}/cont1/sk.txt", headers={**sk(a), "x-ms-blob-type": "BlockBlob"}, content=b"k").status_code == 201
    assert c.delete(f"/azure-data/blob/{a}/cont1/sk.txt", headers=sk(a)).status_code == 202
    d = c.get(blob, headers=sk("someotheraccount"))
    assert d.status_code == 403 and _code(d) == "AuthenticationFailed"                                 # key of another account
    off = c.get(f"/azure-data/blob/{a2}/cont1/b1.txt", headers=sk(a2))
    assert off.status_code == 403 and _code(off) == "KeyBasedAuthenticationNotPermitted"               # allowSharedKeyAccess=false on that account
    arm = c.get(f"{env['rg']}/providers/Microsoft.Storage/storageAccounts?api-version=2023-01-01", headers=sk(a))
    assert arm.status_code == 403                                                                      # Shared Key does not authorise ARM
    _on(c, space="audit")
    assert c.get(blob, headers=sk("someotheraccount")).status_code != 403                              # audit never blocks
    recs = c.get("/api/iam/azure/audit?limit=50").json()["records"]
    assert any(r["decision"] == "would_deny" and r["principal"].startswith("sharedkey:") for r in recs)
    _on(c, space="off")
