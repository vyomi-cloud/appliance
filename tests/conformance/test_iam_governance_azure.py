"""Azure management groups: native ARM wire (Microsoft.Management), hierarchy rules, RBAC + Azure Policy inheritance through the groups,
enforced by the real engine behind the real server (Mesh) and over the pure core (the code Nano vendors)."""
import os, sys, uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")

from core import azure_mgmt_groups_core as mg  # noqa: E402
from core.iam_engine import azure_eval  # noqa: E402

SUB = mg.SUB
MGP = "/providers/Microsoft.Management/managementGroups/"


def call(st, m, p, body=None, q=None):
    return mg.handle(st, m, p, q, body)


def mkgroup(st, name, parent=None, display=None):
    props = {"displayName": display or name}
    if parent:
        props["details"] = {"parent": {"id": MGP + parent}}
    return call(st, "PUT", MGP + name, {"properties": props})


# ---------------------------------------------------------------- pure core
def test_create_list_get_move_delete_and_rules():
    st = {}
    r = mkgroup(st, "contoso", display="Contoso")
    assert r["status"] == 200 and r["body"]["properties"]["details"]["parent"]["name"] == mg.TENANT_ID
    assert mkgroup(st, "eng", "contoso")["status"] == 200
    assert mkgroup(st, "eng-prod", "eng")["status"] == 200
    names = [v["name"] for v in call(st, "GET", MGP[:-1])["body"]["value"]]
    assert names == sorted(names, key=str.lower) and {"contoso", "eng", "eng-prod", mg.TENANT_ID} <= set(names)
    # $expand=children&$recurse
    tree = call(st, "GET", MGP + "contoso", q={"$expand": "children", "$recurse": "true"})["body"]["properties"]["children"]
    assert tree[0]["name"] == "eng" and tree[0]["children"][0]["name"] == "eng-prod"
    assert [d["name"] for d in call(st, "GET", MGP + "contoso/descendants")["body"]["value"]] == ["eng", "eng-prod"]
    # cannot move under itself / a descendant, unknown parent
    assert mkgroup(st, "contoso", "eng-prod")["status"] == 400
    assert mkgroup(st, "x1", "nope")["status"] == 400
    # delete with children -> 409; leaf delete ok; root never
    assert call(st, "DELETE", MGP + "eng")["status"] == 409
    assert call(st, "DELETE", MGP + "eng-prod")["status"] == 200
    assert call(st, "DELETE", MGP + "eng")["status"] == 200
    assert call(st, "DELETE", MGP + mg.TENANT_ID)["status"] == 400
    assert call(st, "GET", MGP + "gone")["status"] == 404
    assert call(st, "POST", "/providers/Microsoft.Management/checkNameAvailability", {"name": "contoso", "type": mg.MG_T})["body"]["nameAvailable"] is False
    assert call(st, "POST", "/providers/Microsoft.Management/checkNameAvailability", {"name": "fresh", "type": mg.MG_T})["body"]["nameAvailable"] is True


def test_depth_limit_is_six_levels():
    st, parent = {}, None
    for i in range(6):
        assert mkgroup(st, f"l{i}", parent)["status"] == 200
        parent = f"l{i}"
    assert mkgroup(st, "l6", parent)["status"] == 400


def test_subscription_membership_and_chain():
    st = {}
    mkgroup(st, "a"); mkgroup(st, "b", "a")
    assert mg.sub_parent(st, SUB) == mg.TENANT_ID                      # default: under the root
    assert call(st, "PUT", MGP + "b/subscriptions/" + SUB)["status"] == 200
    assert mg.sub_chain(st, SUB) == ["b", "a", mg.TENANT_ID]
    assert call(st, "DELETE", MGP + "b")["status"] == 409              # has a subscription
    assert call(st, "PUT", MGP + "b/subscriptions/not-a-sub")["status"] == 404
    assert call(st, "DELETE", MGP + "b/subscriptions/" + SUB)["status"] == 200
    assert mg.sub_chain(st, SUB) == [mg.TENANT_ID]


# ---------------------------------------------------------------- engine: RBAC through the groups
def _state(st, assignments):
    s = {"cloud": "azure", "role_assignments": assignments, "role_definitions": [], "deny_assignments": [], "groups": {},
         "management_groups": {r["name"]: (r["properties"]["details"]["parent"] or {}).get("name") if False else
                             (r["properties"]["details"].get("parent") or {"id": ""})["id"].rsplit("/", 1)[-1] or None
                             for r in mg.groups(st).values()},
         "subscriptions": {m["name"]: m["properties"]["parent"]["id"].rsplit("/", 1)[-1] for m in mg.members(st)}}
    return s


READER = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
RES = f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/sa"


def _can(state, who):
    return azure_eval.evaluate({"cloud": "azure", "principal": {"object_id": who, "type": "User", "groups": []},
                                "action": "Microsoft.Storage/storageAccounts/read", "resource": RES}, state)["allowed"]


def test_role_assignment_at_management_group_reaches_subscriptions_below_only():
    st = {}
    mkgroup(st, "a"); mkgroup(st, "b", "a")
    call(st, "PUT", MGP + "b/subscriptions/" + SUB)
    asg = [{"id": "x", "principal_id": "alice", "role_definition_id": READER, "scope": MGP + "a"}]
    assert _can(_state(st, asg), "alice") is True                       # assigned on the grandparent group
    assert _can(_state(st, [dict(asg[0], scope=MGP + "b")]), "alice") is True
    other = {"id": "y", "principal_id": "bob", "role_definition_id": READER, "scope": MGP + "zz"}
    mkgroup(st, "zz")
    assert _can(_state(st, [other]), "bob") is False                    # a sibling group does not cover the subscription
    call(st, "DELETE", MGP + "b/subscriptions/" + SUB)                  # moved back under the root
    assert _can(_state(st, asg), "alice") is False                      # group 'a' no longer encloses it
    assert _can(_state(st, [dict(asg[0], scope=MGP + mg.TENANT_ID)]), "alice") is True   # the root group still does


def test_policy_assignment_at_management_group_scope():
    st = {}
    mkgroup(st, "a")
    ok = call(st, "PUT", MGP + "a/providers/Microsoft.Authorization/policyAssignments/pa1",
              {"properties": {"policyDefinitionId": "/providers/Microsoft.Authorization/policyDefinitions/e56962a6-4747-49cd-b67b-bf8b01975c4c",
                              "parameters": {"listOfAllowedLocations": {"value": ["westeurope"]}}}})
    assert ok["status"] == 201 and ok["body"]["properties"]["scope"] == MGP + "a"
    call(st, "PUT", MGP + "a/subscriptions/" + SUB)
    assert [r["name"] for r in mg.policy_assignments_above(st, SUB)] == ["pa1"]
    assert call(st, "GET", MGP + "a/providers/Microsoft.Authorization/policyAssignments")["body"]["value"][0]["name"] == "pa1"
    call(st, "DELETE", MGP + "a/subscriptions/" + SUB)
    assert mg.policy_assignments_above(st, SUB) == []


# ---------------------------------------------------------------- the real server (Mesh)
@pytest.fixture(scope="module")
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    c.put("/api/iam/azure/enforcement", json={"space": "off"})
    yield c
    c.put("/api/iam/azure/enforcement", json={"space": "off"})


def test_mesh_wire_and_enforced_inheritance(client):
    c, u = client, uuid.uuid4().hex[:6]
    top, leaf = f"gov-top-{u}", f"gov-leaf-{u}"
    api = "?api-version=2021-04-01"
    assert c.put(MGP + top + api, json={"properties": {"displayName": "Top " + u}}).status_code == 200
    r = c.put(MGP + leaf + api, json={"properties": {"displayName": "Leaf", "details": {"parent": {"id": MGP + top}}}})
    assert r.status_code == 200 and r.json()["properties"]["details"]["parent"]["name"] == top
    assert c.put(MGP + leaf + "/subscriptions/" + SUB + api).status_code == 200
    tree = c.get(MGP + top + api + "&$expand=children&$recurse=true").json()["properties"]["children"]
    assert tree[0]["name"] == leaf and tree[0]["children"][0]["type"] == "/subscriptions"
    who = "oid-mgreader-" + u
    rg = f"/subscriptions/{SUB}/resourceGroups/rg-gov-{u}"
    assert c.put(rg + "?api-version=2021-04-01", json={"location": "eastus"}).status_code in (200, 201)
    # role assignment at the TOP group, scope taken from the URL (no scope in the body)
    ra_id = str(uuid.uuid4())
    ra = MGP + top + "/providers/Microsoft.Authorization/roleAssignments/" + ra_id + "?api-version=2022-04-01"
    rd = f"/providers/Microsoft.Authorization/roleDefinitions/{READER}"
    assert c.put(ra, json={"properties": {"principalId": who, "roleDefinitionId": rd}}).status_code in (200, 201)
    lst = f"{rg}/providers/Microsoft.Storage/storageAccounts?api-version=2023-01-01"
    try:
        assert c.put("/api/iam/azure/enforcement", json={"space": "enforce"}).status_code == 200
        assert c.get(lst, headers={"X-Cloudlearn-Principal": who}).status_code == 200            # inherited through leaf -> top
        assert c.get(lst, headers={"X-Cloudlearn-Principal": "oid-nobody-" + u}).status_code == 403
        # move the subscription out of the group: access is gone
        assert c.delete(MGP + leaf + "/subscriptions/" + SUB + api).status_code == 200
        assert c.get(lst, headers={"X-Cloudlearn-Principal": who}).status_code == 403
        # the effective-access view (Troubleshooter / simulator front end) agrees
        ev = c.post("/api/iam/azure/evaluate", json={"principal": {"object_id": who, "type": "User"}, "action": "Microsoft.Storage/storageAccounts/read", "resource": rg}).json()
        assert ev["allowed"] is False
    finally:
        c.put("/api/iam/azure/enforcement", json={"space": "off"})
        c.delete(ra)
        c.delete(rg + "?api-version=2021-04-01")
        c.delete(MGP + leaf + api)
        c.delete(MGP + top + api)


def test_mesh_policy_assignment_at_management_group_blocks_resources_below(client):
    c, u = client, uuid.uuid4().hex[:6]
    g, api = f"gov-pol-{u}", "?api-version=2021-04-01"
    rg = f"/subscriptions/{SUB}/resourceGroups/rg-pol-{u}"
    sa = f"{rg}/providers/Microsoft.Storage/storageAccounts/pol{u}?api-version=2023-01-01"
    body = {"location": "eastus", "sku": {"name": "Standard_LRS"}, "kind": "StorageV2"}
    pa = MGP + g + "/providers/Microsoft.Authorization/policyAssignments/loc-" + u + "?api-version=2021-06-01"
    assert c.put(MGP + g + api, json={"properties": {"displayName": g}}).status_code == 200
    assert c.put(rg + "?api-version=2021-04-01", json={"location": "eastus"}).status_code in (200, 201)
    try:
        r = c.put(pa, json={"properties": {"displayName": "Allowed locations", "policyDefinitionId": "/providers/Microsoft.Authorization/policyDefinitions/e56962a6-4747-49cd-b67b-bf8b01975c4c",
                                           "parameters": {"listOfAllowedLocations": {"value": ["westeurope"]}}}})
        assert r.status_code == 201, r.text
        assert c.put(sa, json=body).status_code == 200                                    # group has no subscription yet: not applied
        c.delete(sa)
        assert c.put(MGP + g + "/subscriptions/" + SUB + api).status_code == 200
        den = c.put(sa, json=body)
        assert den.status_code == 403 and den.json()["error"]["code"] == "RequestDisallowedByPolicy", den.text
        assert c.put(sa, json=dict(body, location="westeurope")).status_code == 200      # an allowed location passes
        c.delete(sa)
        assert c.delete(MGP + g + "/subscriptions/" + SUB + api).status_code == 200      # leaves the group: not applied any more
        assert c.put(sa, json=body).status_code == 200
    finally:
        c.delete(sa)
        c.delete(pa)
        c.delete(rg + "?api-version=2021-04-01")
        c.delete(MGP + g + api)
