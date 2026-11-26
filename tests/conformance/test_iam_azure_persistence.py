"""Azure RBAC persistence + enforcement of the fields the v4 console's pickers send (WP integ-fixes):
role assignment condition / conditionVersion / description / principalType (+ createdOn/updatedOn/createdBy), custom-role assignableScopes,
deny-assignment name / description. Stored by core/azure_iam_core.py, returned in ARM shapes, fed to azure_eval by iam_state_adapters."""
import json, os, sys, types
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "core")]
os.environ.setdefault("CLOUDLEARN_TIER_ENFORCE", "0")

from core import azure_iam_core as az_iam                      # noqa: E402
from core import iam_state_adapters as ad                      # noqa: E402
from core.iam_engine import azure_eval as ev                   # noqa: E402
from core.iam_engine.types import request                      # noqa: E402

SUB = "/subscriptions/00000000-0000-0000-0000-cloudlearn01"
RG1, RG2 = SUB + "/resourceGroups/rg1", SUB + "/resourceGroups/rg2"
SA1 = RG1 + "/providers/Microsoft.Storage/storageAccounts/sa1"
U = "aaaaaaaa-0000-0000-0000-000000000001"
BLOB_READER = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"       # Storage Blob Data Reader
BLOB_READ = "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"
# exactly what the console's ABAC builder generates (consoles/src/azure/kit/pickers/data.js conditionCode)
COND = ("((!(ActionMatches{'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'})) OR "
        "(@Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringEquals 'public'))")


def store():
    return types.SimpleNamespace()


def call(st, method, path, body=None):
    r = az_iam.dispatch(st, method, SUB + "/providers/Microsoft.Authorization/" + path, {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body or b"{}")


def put_ra(st, name, **props):
    base = {"principalId": U, "roleName": "Storage Blob Data Reader", "scope": RG1}
    return call(st, "PUT", f"roleAssignments/{name}", {"properties": {**base, **props}})


def decide(st, resource_attrs=None, scope=SA1, action=BLOB_READ, data=True):
    state = ad.azure_state({}, st)
    return ev.evaluate(request("azure", {"object_id": U, "type": "User", "groups": []}, action, scope,
                               {"resource": resource_attrs or {}}, data=data), state)


def test_assignment_fields_are_persisted_and_returned_in_arm_shape():
    st = store()
    code, b = put_ra(st, "a1", principalType="ServicePrincipal", description="CI reader", condition=COND, conditionVersion="2.0")
    assert code == 201
    p = b["properties"]
    assert (p["condition"], p["conditionVersion"], p["description"], p["principalType"]) == (COND, "2.0", "CI reader", "ServicePrincipal")
    assert p["createdOn"] and p["updatedOn"] and p["createdBy"] and p["updatedBy"]
    assert b["type"] == "Microsoft.Authorization/roleAssignments" and b["id"].endswith("/roleAssignments/a1")
    c, got = call(st, "GET", "roleAssignments/a1")
    assert c == 200 and got["properties"] == p
    c, lst = call(st, "GET", "roleAssignments")
    assert lst["value"][0]["properties"]["condition"] == COND and lst["value"][0]["properties"]["description"] == "CI reader"
    assert call(st, "GET", "roleAssignments/nope")[0] == 404


def test_update_keeps_created_and_bumps_updated():
    st = store()
    first = put_ra(st, "a1", description="v1")[1]["properties"]
    code, second = put_ra(st, "a1", description="v2")
    assert code == 200 and second["properties"]["description"] == "v2"
    assert second["properties"]["createdOn"] == first["createdOn"] and second["properties"]["updatedOn"] >= first["updatedOn"]


def test_invalid_condition_is_rejected_and_unconditional_assignment_has_no_condition_keys():
    st = store()
    assert put_ra(st, "bad", condition="((", conditionVersion="2.0")[0] == 400
    assert put_ra(st, "bad2", condition=COND, conditionVersion="1.0")[0] == 400
    p = put_ra(st, "plain")[1]["properties"]
    assert "condition" not in p and "conditionVersion" not in p and p["principalType"] == "User"


def test_condition_is_enforced_in_the_decision():
    st = store()
    put_ra(st, "a1", condition=COND, conditionVersion="2.0")
    assert decide(st, {"Microsoft.Storage/storageAccounts/blobServices/containers:name": "public"})["allowed"] is True
    assert decide(st, {"Microsoft.Storage/storageAccounts/blobServices/containers:name": "secret"})["allowed"] is False
    assert decide(st, {})["allowed"] is False                        # missing attribute: comparison false, never allow
    # an action the condition does not mention is unaffected
    put_ra(st, "a2", roleName="Reader")
    assert decide(st, {}, action="Microsoft.Storage/storageAccounts/read", data=False)["allowed"] is True


def test_unsupported_condition_never_allows():
    st = store()
    put_ra(st, "a1", condition="((!(ActionMatches{'" + BLOB_READ + "'})) OR (@Resource[x:y] BogusOperator 'v'))", conditionVersion="2.0")
    assert decide(st, {"x:y": "v"})["allowed"] is False


def test_arm_store_assignment_with_condition_is_enforced_too():
    rec = {"id": RG1 + "/providers/Microsoft.Authorization/roleAssignments/r1", "name": "r1", "_type": "microsoft.authorization/roleassignments",
           "properties": {"principalId": U, "scope": RG1, "roleDefinitionId": SUB + "/providers/Microsoft.Authorization/roleDefinitions/" + BLOB_READER,
                          "condition": COND, "conditionVersion": "2.0"}}
    state = ad.azure_state({"r1": rec}, None)
    mk = lambda name: ev.evaluate(request("azure", {"object_id": U, "type": "User", "groups": []}, BLOB_READ, SA1,
                                          {"resource": {"Microsoft.Storage/storageAccounts/blobServices/containers:name": name}}, data=True), state)["allowed"]
    assert mk("public") is True and mk("other") is False


ROLE_BODY = {"properties": {"roleName": "Blob Lister", "description": "list blobs", "type": "CustomRole",
                            "permissions": [{"actions": ["Microsoft.Storage/storageAccounts/read"], "notActions": [], "dataActions": [BLOB_READ], "notDataActions": []}],
                            "assignableScopes": [RG1]}}


def test_custom_role_assignable_scopes_persist_and_are_returned():
    st = store()
    assert call(st, "PUT", "roleDefinitions/rd1", ROLE_BODY)[0] == 201
    c, got = call(st, "GET", "roleDefinitions/Blob Lister")
    pr = got["properties"]
    assert c == 200 and pr["assignableScopes"] == [RG1] and pr["permissions"][0]["dataActions"] == [BLOB_READ] and pr["description"] == "list blobs"


def test_custom_role_only_applies_inside_its_assignable_scopes():
    st = store()
    call(st, "PUT", "roleDefinitions/rd1", ROLE_BODY)
    put_ra(st, "in", roleName="Blob Lister", scope=RG1)
    put_ra(st, "out", roleName="Blob Lister", scope=RG2)
    in_scope = RG1 + "/providers/Microsoft.Storage/storageAccounts/sa1"
    out_scope = RG2 + "/providers/Microsoft.Storage/storageAccounts/sa2"
    assert decide(st, scope=in_scope)["allowed"] is True
    assert decide(st, scope=out_scope)["allowed"] is False         # assigned outside assignableScopes: the role does not exist there
    st2 = store()                                                  # widening to the subscription makes the same assignment effective
    body = json.loads(json.dumps(ROLE_BODY)); body["properties"]["assignableScopes"] = [SUB]
    call(st2, "PUT", "roleDefinitions/rd1", body); put_ra(st2, "out", roleName="Blob Lister", scope=RG2)
    assert decide(st2, scope=out_scope)["allowed"] is True


def test_deny_assignment_name_and_description_persist_and_still_deny():
    st = store()
    put_ra(st, "allow1", roleName="Owner", scope=SUB)
    code, b = call(st, "PUT", "roleAssignments/d1", {"properties": {"kind": "deny", "principalId": U, "principalType": "User", "scope": RG1,
                                                                      "denyActions": ["Microsoft.Storage/storageAccounts/delete"], "description": "no deletes",
                                                                      "denyAssignmentName": "Protect storage"}})
    assert code == 201 and b["type"] == "Microsoft.Authorization/denyAssignments"
    assert b["properties"]["denyAssignmentName"] == "Protect storage" and b["properties"]["description"] == "no deletes"
    assert b["properties"]["permissions"][0]["actions"] == ["Microsoft.Storage/storageAccounts/delete"]
    d = decide(st, scope=SA1, action="Microsoft.Storage/storageAccounts/delete", data=False)
    assert d["allowed"] is False and d["reason"] == "explicit_deny"
    assert decide(st, scope=SA1, action="Microsoft.Storage/storageAccounts/read", data=False)["allowed"] is True


def test_arm_store_kind_deny_assignment_denies():
    own = {"id": SUB + "/providers/Microsoft.Authorization/roleAssignments/o", "name": "o", "_type": "microsoft.authorization/roleassignments",
           "properties": {"principalId": U, "scope": SUB, "roleDefinitionId": "8e3af657-a8ff-443c-a75c-2fe8c4bcb635"}}
    deny = {"id": RG1 + "/providers/Microsoft.Authorization/roleAssignments/d", "name": "d", "_type": "microsoft.authorization/roleassignments",
            "properties": {"kind": "deny", "principalId": U, "scope": RG1, "denyActions": ["Microsoft.Storage/storageAccounts/delete"], "denyAssignmentName": "n"}}
    state = ad.azure_state({"o": own, "d": deny}, None)
    r = ev.evaluate(request("azure", {"object_id": U, "type": "User", "groups": []}, "Microsoft.Storage/storageAccounts/delete", SA1, {}, data=False), state)
    assert r["allowed"] is False and r["reason"] == "explicit_deny"


def test_state_survives_snapshot_roundtrip():
    st = store()
    put_ra(st, "a1", condition=COND, conditionVersion="2.0", description="d")
    st2 = types.SimpleNamespace(_azure_role_assignments=json.loads(json.dumps(st._azure_role_assignments)))
    assert call(st2, "GET", "roleAssignments/a1")[1]["properties"]["condition"] == COND


def test_arm_store_role_assignment_returns_audit_properties_and_keeps_every_field():
    from core.azure_arm_core import AzureArm
    a = AzureArm()
    path = SUB + "/providers/Microsoft.Authorization/roleAssignments/ra1"
    body = {"properties": {"roleDefinitionId": SUB + "/providers/Microsoft.Authorization/roleDefinitions/" + BLOB_READER, "principalId": U, "principalType": "Group",
                           "scope": RG1, "description": "d", "condition": COND, "conditionVersion": "2.0"}}
    r = a.handle("PUT", path, {"api-version": "2022-04-01"}, body)
    assert r["status"] == 201
    p = r["body"]["properties"]
    assert (p["condition"], p["conditionVersion"], p["description"], p["principalType"]) == (COND, "2.0", "d", "Group")
    assert p["createdOn"] and p["updatedOn"] and p["createdBy"]
    r2 = a.handle("PUT", path, {"api-version": "2022-04-01"}, {"properties": {**body["properties"], "description": "d2"}})
    assert r2["body"]["properties"]["createdOn"] == p["createdOn"] and r2["body"]["properties"]["description"] == "d2"
    assert a.handle("GET", path, {"api-version": "2022-04-01"}, None)["body"]["properties"]["condition"] == COND
