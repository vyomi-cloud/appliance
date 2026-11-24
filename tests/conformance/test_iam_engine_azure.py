"""Azure RBAC engine (core/iam_engine/azure_eval.py): scope inheritance, groups, wildcards, notActions, data plane, deny assignments, ABAC, PIM."""
import json, os, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from core.iam_engine import azure_eval as az                      # noqa: E402
from core.iam_engine.types import request                         # noqa: E402

ROLES = json.load(open(os.path.join(ROOT, "core", "iam_catalog", "azure", "_roles.json")))["roles"]
OWNER, CONTRIB, READER, UAA = ("8e3af657-a8ff-443c-a75c-2fe8c4bcb635", "b24988ac-6180-42a0-ab88-20f7382dd24c",
                               "acdd72a7-3385-48ef-bd42-f606fba81ae7", "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9")
SUB = "/subscriptions/11111111-1111-1111-1111-111111111111"
RG = SUB + "/resourceGroups/rg1"
VM = RG + "/providers/Microsoft.Compute/virtualMachines/vm1"
SA = RG + "/providers/Microsoft.Storage/storageAccounts/sa1"
CONT = SA + "/blobServices/default/containers/c1"
U = "aaaaaaaa-0000-0000-0000-000000000001"
BLOB_READ = "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"
BLOB_WRITE = "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write"


def ra(role, scope, pid=U, **kw):
    return {"id": f"ra-{role[:4]}-{len(scope)}", "principal_id": pid, "role_definition_id": role, "scope": scope, **kw}


def ev(state, action, scope=VM, pid=U, data=False, groups=(), context=None):
    return az.evaluate(request("azure", {"object_id": pid, "type": "User", "groups": list(groups)}, action, scope, context, data=data), state)


def ok(state, *a, **k):
    return ev(state, *a, **k)["allowed"]


# ---------------- generated catalog
def test_roles_catalog_counts_and_exact_basics():
    assert len(ROLES) > 400
    assert ROLES[OWNER]["roleName"] == "Owner" and ROLES[OWNER]["actions"] == ["*"] and not ROLES[OWNER]["notActions"]
    assert ROLES[READER]["actions"] == ["*/read"]
    c = ROLES[CONTRIB]
    assert c["actions"] == ["*"] and "Microsoft.Authorization/*/Write" in c["notActions"] and "Microsoft.Authorization/elevateAccess/Action" in c["notActions"]
    assert ROLES[UAA]["actions"] == ["*/read", "Microsoft.Authorization/*", "Microsoft.Support/*"]
    assert all(r["roleName"] and r["id"] for r in ROLES.values())


# ---------------- wildcards
@pytest.mark.parametrize("pat,act,exp", [
    ("*", "Microsoft.Compute/virtualMachines/read", True),
    ("Microsoft.Compute/*", "Microsoft.Compute/virtualMachines/start/action", True),
    ("Microsoft.Compute/*", "Microsoft.Storage/storageAccounts/read", False),
    ("*/read", "Microsoft.Storage/storageAccounts/read", True),
    ("*/read", "Microsoft.Storage/storageAccounts/write", False),
    ("Microsoft.Storage/*/read", "Microsoft.Storage/storageAccounts/blobServices/read", True),
    ("microsoft.compute/virtualmachines/READ", "Microsoft.Compute/virtualMachines/read", True),
    ("Microsoft.Compute/virtualMachines/read", "Microsoft.Compute/virtualMachines/read2", False),
])
def test_wildcards(pat, act, exp):
    assert az.action_matches(pat, act) is exp


# ---------------- built-in roles
def test_owner_allows_everything_in_scope():
    s = {"role_assignments": [ra(OWNER, SUB)]}
    assert ok(s, "Microsoft.Compute/virtualMachines/delete")
    assert ok(s, "Microsoft.Authorization/roleAssignments/write")


def test_contributor_cannot_assign_roles():
    s = {"role_assignments": [ra(CONTRIB, SUB)]}
    assert ok(s, "Microsoft.Compute/virtualMachines/write")
    assert not ok(s, "Microsoft.Authorization/roleAssignments/write")
    assert not ok(s, "Microsoft.Authorization/elevateAccess/Action")
    assert ev(s, "Microsoft.Authorization/roleAssignments/delete")["reason"] == "implicit_deny"


def test_reader_read_only():
    s = {"role_assignments": [ra(READER, SUB)]}
    assert ok(s, "Microsoft.Compute/virtualMachines/read")
    assert not ok(s, "Microsoft.Compute/virtualMachines/write")
    assert not ok(s, "Microsoft.Compute/virtualMachines/start/action")


def test_user_access_administrator():
    s = {"role_assignments": [ra(UAA, SUB)]}
    assert ok(s, "Microsoft.Authorization/roleAssignments/write")
    assert ok(s, "Microsoft.Compute/virtualMachines/read")
    assert not ok(s, "Microsoft.Compute/virtualMachines/write")


def test_role_by_name_and_full_id():
    assert ok({"role_assignments": [ra("Reader", SUB)]}, "Microsoft.Compute/virtualMachines/read")
    assert ok({"role_assignments": [ra("/providers/Microsoft.Authorization/roleDefinitions/" + READER, SUB)]}, "Microsoft.Compute/virtualMachines/read")


def test_unknown_role_grants_nothing():
    assert not ok({"role_assignments": [ra("no-such-role", SUB)]}, "Microsoft.Compute/virtualMachines/read")


def test_vm_contributor_builtin_from_catalog():
    r = next(x for x in ROLES.values() if x["roleName"] == "Virtual Machine Contributor")
    s = {"role_assignments": [ra(r["id"], RG)]}
    assert ok(s, "Microsoft.Compute/virtualMachines/start/action")
    assert not ok(s, "Microsoft.Storage/storageAccounts/write", scope=SA)


def test_every_generated_role_evaluates_without_error():
    for gid, r in ROLES.items():
        s = {"role_assignments": [ra(gid, "/")]}
        for a in r["actions"][:2] or ["Microsoft.Compute/virtualMachines/read"]:
            ev(s, a.replace("*", "x"))
        for a in r["dataActions"][:2]:
            ev(s, a.replace("*", "x"), data=True)


def test_every_role_grants_its_own_first_action():
    for gid, r in ROLES.items():
        if not r["actions"] or "*" in r["actions"][0] or r["notActions"] and any(az.action_matches(n, r["actions"][0]) for n in r["notActions"]):
            continue
        assert ok({"role_assignments": [ra(gid, "/")]}, r["actions"][0]), r["roleName"]


# ---------------- scope inheritance
def test_scope_inheritance_down():
    for sc in (SUB, RG, VM):
        assert ok({"role_assignments": [ra(READER, sc)]}, "Microsoft.Compute/virtualMachines/read", scope=VM)


def test_scope_not_inherited_up_or_sideways():
    assert not ok({"role_assignments": [ra(READER, VM)]}, "Microsoft.Compute/virtualMachines/read", scope=RG)
    assert not ok({"role_assignments": [ra(READER, RG)]}, "Microsoft.Compute/virtualMachines/read", scope=SUB + "/resourceGroups/rg2/x")


def test_scope_prefix_on_segment_boundary_only():
    assert not ok({"role_assignments": [ra(READER, SUB + "/resourceGroups/rg")]}, "x/read", scope=RG + "/providers/a/b/c")
    assert ok({"role_assignments": [ra(READER, SUB + "/resourceGroups/rg1")]}, "x/read", scope=RG + "/providers/a/b/c")


def test_scope_case_insensitive_and_trailing_slash():
    assert ok({"role_assignments": [ra(READER, RG.upper() + "/")]}, "x/read", scope=VM.lower())


def test_root_scope_covers_all():
    assert ok({"role_assignments": [ra(READER, "/")]}, "x/read", scope=VM)


def test_management_group_inheritance():
    mg = "/providers/Microsoft.Management/managementGroups/mg-child"
    st = {"role_assignments": [ra(READER, mg)], "subscriptions": {"11111111-1111-1111-1111-111111111111": "mg-child"}}
    assert ok(st, "x/read", scope=VM)
    st["subscriptions"] = {}
    assert not ok(st, "x/read", scope=VM)


def test_management_group_parent_chain():
    mg = "/providers/Microsoft.Management/managementGroups/root-mg"
    st = {"role_assignments": [ra(READER, mg)], "subscriptions": {"11111111-1111-1111-1111-111111111111": "child"},
          "management_groups": {"child": "mid", "mid": "root-mg", "root-mg": None}}
    assert ok(st, "x/read", scope=VM)


def test_management_group_cycle_terminates():
    st = {"role_assignments": [], "subscriptions": {"11111111-1111-1111-1111-111111111111": "a"}, "management_groups": {"a": "b", "b": "a"}}
    assert not ok(st, "x/read")


# ---------------- principals / groups
def test_other_principal_not_matched():
    assert not ok({"role_assignments": [ra(READER, SUB, pid="someone-else")]}, "x/read")


def test_group_assignment_via_request_groups():
    assert ok({"role_assignments": [ra(READER, SUB, pid="grp1")]}, "x/read", groups=["GRP1"])


def test_group_membership_from_state():
    st = {"role_assignments": [ra(READER, SUB, pid="grp1")], "groups": {"grp1": [U]}}
    assert ok(st, "x/read")


def test_nested_group_membership():
    st = {"role_assignments": [ra(READER, SUB, pid="top")], "groups": {"top": ["mid"], "mid": [U]}}
    assert ok(st, "x/read")


def test_service_principal_and_managed_identity():
    st = {"role_assignments": [ra(READER, SUB, pid="sp-1"), ra(CONTRIB, SUB, pid="mi-1")]}
    assert ok(st, "x/read", pid="sp-1") and not ok(st, "x/write", pid="sp-1")
    assert ok(st, "Microsoft.Compute/virtualMachines/write", pid="mi-1")


def test_union_of_roles_and_notactions_are_per_role():
    st = {"role_assignments": [ra(CONTRIB, SUB), ra(UAA, SUB)]}
    assert ok(st, "Microsoft.Authorization/roleAssignments/write")             # Contributor's notAction does not subtract UAA's grant
    assert len(ev(st, "Microsoft.Authorization/roleAssignments/write")["matched"]) == 1


# ---------------- custom roles
def test_custom_role_flat_and_arm_shape():
    flat = {"id": "cr1", "roleName": "VM Starter", "actions": ["Microsoft.Compute/virtualMachines/start/action"], "notActions": []}
    arm = {"name": "cr2", "properties": {"roleName": "SA Reader", "permissions": [{"actions": ["Microsoft.Storage/storageAccounts/read"]}]}}
    st = {"role_definitions": [flat, arm], "role_assignments": [ra("cr1", SUB), ra("cr2", SUB)]}
    assert ok(st, "Microsoft.Compute/virtualMachines/start/action")
    assert not ok(st, "Microsoft.Compute/virtualMachines/restart/action")
    assert ok(st, "Microsoft.Storage/storageAccounts/read", scope=SA)


def test_notactions_wildcard_subtract():
    st = {"role_definitions": {"x": {"id": "cr", "roleName": "R", "actions": ["Microsoft.Compute/*"], "notActions": ["Microsoft.Compute/*/delete"]}},
          "role_assignments": [ra("cr", SUB)]}
    assert ok(st, "Microsoft.Compute/virtualMachines/write") and not ok(st, "Microsoft.Compute/virtualMachines/delete")


# ---------------- data plane
def test_data_plane_separate_from_control_plane():
    st = {"role_assignments": [ra(OWNER, SUB)]}
    assert not ok(st, BLOB_READ, scope=CONT, data=True)                         # Owner has no dataActions
    assert ok(st, "Microsoft.Storage/storageAccounts/read", scope=SA)


def test_storage_blob_data_reader():
    r = next(x for x in ROLES.values() if x["roleName"] == "Storage Blob Data Reader")
    st = {"role_assignments": [ra(r["id"], SA)]}
    assert ok(st, BLOB_READ, scope=CONT, data=True)
    assert not ok(st, BLOB_WRITE, scope=CONT, data=True)
    assert not ok(st, BLOB_READ, scope=CONT, data=False)                        # same string as a control action: not granted


def test_storage_blob_data_contributor_and_owner():
    for name, write in (("Storage Blob Data Contributor", True), ("Storage Blob Data Owner", True)):
        r = next(x for x in ROLES.values() if x["roleName"] == name)
        assert ok({"role_assignments": [ra(r["id"], SA)]}, BLOB_WRITE, scope=CONT, data=True) is write


def test_not_data_actions_subtract():
    st = {"role_definitions": [{"id": "d", "roleName": "D", "dataActions": ["Microsoft.Storage/*"], "notDataActions": [BLOB_WRITE]}],
          "role_assignments": [ra("d", SA)]}
    assert ok(st, BLOB_READ, scope=CONT, data=True) and not ok(st, BLOB_WRITE, scope=CONT, data=True)


# ---------------- deny assignments
def deny(**kw):
    d = {"id": "da1", "scope": SUB, "principals": [{"id": EVERYONE if False else az.EVERYONE, "type": "SystemDefined"}],
         "permissions": [{"actions": ["Microsoft.Compute/virtualMachines/delete"]}]}
    d.update(kw); return d


def test_deny_beats_owner():
    st = {"role_assignments": [ra(OWNER, SUB)], "deny_assignments": [deny()]}
    d = ev(st, "Microsoft.Compute/virtualMachines/delete")
    assert not d["allowed"] and d["reason"] == "explicit_deny" and d["matched"][0]["source"] == "deny_assignment"
    assert ok(st, "Microsoft.Compute/virtualMachines/write")


def test_deny_exclude_principals():
    st = {"role_assignments": [ra(OWNER, SUB)], "deny_assignments": [deny(exclude_principals=[{"id": U, "type": "User"}])]}
    assert ok(st, "Microsoft.Compute/virtualMachines/delete")


def test_deny_exclude_via_group():
    st = {"role_assignments": [ra(OWNER, SUB)], "groups": {"admins": [U]}, "deny_assignments": [deny(exclude_principals=[{"id": "admins"}])]}
    assert ok(st, "Microsoft.Compute/virtualMachines/delete")


def test_deny_specific_principal_only():
    st = {"role_assignments": [ra(OWNER, SUB, pid="o2"), ra(OWNER, SUB)], "deny_assignments": [deny(principals=[{"id": U}])]}
    assert not ok(st, "Microsoft.Compute/virtualMachines/delete")
    assert ok(st, "Microsoft.Compute/virtualMachines/delete", pid="o2")


def test_deny_scope_and_do_not_apply_to_child():
    st = {"role_assignments": [ra(OWNER, SUB)], "deny_assignments": [deny(scope=RG, do_not_apply_to_child_scopes=True)]}
    assert not ok(st, "Microsoft.Compute/virtualMachines/delete", scope=RG)
    assert ok(st, "Microsoft.Compute/virtualMachines/delete", scope=VM)
    st["deny_assignments"][0]["do_not_apply_to_child_scopes"] = False
    assert not ok(st, "Microsoft.Compute/virtualMachines/delete", scope=VM)
    assert ok(st, "Microsoft.Compute/virtualMachines/delete", scope=SUB + "/resourceGroups/other/x")


def test_deny_notactions_and_data_plane_and_system_protected():
    st = {"role_assignments": [ra(OWNER, SUB)], "deny_assignments": [deny(is_system_protected=True, permissions=[
        {"actions": ["Microsoft.Compute/*"], "notActions": ["Microsoft.Compute/*/read"], "dataActions": ["Microsoft.Storage/*"]}])]}
    assert ok(st, "Microsoft.Compute/virtualMachines/read")
    d = ev(st, "Microsoft.Compute/virtualMachines/write")
    assert not d["allowed"] and d["matched"][0]["statement"]["isSystemProtected"] is True
    assert not ok(st, BLOB_READ, scope=CONT, data=True)
    assert ok(st, BLOB_READ, scope=CONT, data=False)                             # deny's dataActions do not touch the control plane (Owner '*' covers it)


# ---------------- PIM
def test_pim_eligible_inactive_until_activated():
    st = {"role_assignments": [ra(OWNER, SUB, assignment_type="eligible")]}
    assert not ok(st, "x/read")
    st["role_assignments"][0]["activated"] = True
    assert ok(st, "x/read")
    st["role_assignments"][0].update(assignment_type="active", activated=False)
    assert ok(st, "x/read")


# ---------------- ABAC conditions
COND_NAME = ("((!(ActionMatches{'%s'})) OR (@Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringEquals 'c1'))" % BLOB_READ)


def abac_state(cond, role="Storage Blob Data Reader"):
    r = next(x for x in ROLES.values() if x["roleName"] == role)
    return {"role_assignments": [ra(r["id"], SA, condition=cond, condition_version="2.0")]}


def blob(st, name, action=BLOB_READ, **ctx):
    c = {"resource": {"Microsoft.Storage/storageAccounts/blobServices/containers:name": name}}
    c.update(ctx)
    return ok(st, action, scope=CONT, data=True, context=c)


def test_abac_container_name_equals():
    st = abac_state(COND_NAME)
    assert blob(st, "c1") and not blob(st, "c2")


def test_abac_action_not_in_condition_is_unconstrained():
    st = abac_state("((!(ActionMatches{'%s'})) OR (@Resource[x:name] StringEquals 'a'))" % BLOB_WRITE)
    assert blob(st, "whatever")                                                  # read is outside the ActionMatches -> !() true


def test_abac_missing_attribute_false():
    assert not ok(abac_state(COND_NAME), BLOB_READ, scope=CONT, data=True)


def test_abac_string_ops():
    f = lambda c, v: az.eval_condition("@Resource[a:b] %s" % c, "x", {"resource": {"a:b": v}})
    assert f("StringNotEquals 'x'", "y") and not f("StringNotEquals 'x'", "x")
    assert f("StringStartsWith 'logs/'", "logs/2026") and not f("StringStartsWith 'logs/'", "data/1")
    assert f("StringLike 'a*z'", "abcz") and not f("StringLike 'a*z'", "ABCZ")
    assert f("StringNotLike 'a*'", "bcd")
    assert f("StringEqualsIgnoreCase 'ABC'", "abc") and f("StringNotEqualsIgnoreCase 'ABC'", "abd")
    assert f("StringEquals {'a','b'}", "b")


def test_abac_attribute_sources_and_exists():
    c = {"request": {"r": "1"}, "principal": {"p": "dept"}, "environment": {"isPrivateLink": True}}
    e = lambda s: az.eval_condition(s, "x", c)
    assert e("@Request[r] StringEquals '1'") and e("@Principal[p] StringEquals 'dept'") and e("@Environment[isPrivateLink] BoolEquals true")
    assert not e("@Environment[isPrivateLink] BoolEquals false")
    assert e("Exists @Request[r]") and e("NotExists @Request[zz]") and not e("Exists @Resource[r]")
    assert e("@Principal[p] StringEquals @Principal[p]")


def test_abac_numeric_and_bool_ops():
    e = lambda s, v: az.eval_condition(s, "x", {"request": {"n": v}})
    assert e("@Request[n] NumericLessThan 5", 3) and not e("@Request[n] NumericLessThan 5", 5)
    assert e("@Request[n] NumericLessThanEquals 5", 5) and e("@Request[n] NumericGreaterThan 5", 6)
    assert e("@Request[n] NumericGreaterThanEquals 5", 5) and e("@Request[n] NumericEquals 5", 5.0) and e("@Request[n] NumericNotEquals 5", 4)
    assert e("@Request[n] BoolNotEquals true", False)


def test_abac_logical_operators_and_precedence():
    e = lambda s: az.eval_condition(s, "x", {"resource": {"a": "1", "b": "2"}})
    assert e("@Resource[a] StringEquals '1' AND @Resource[b] StringEquals '2'")
    assert not e("@Resource[a] StringEquals '1' AND @Resource[b] StringEquals 'x'")
    assert e("@Resource[a] StringEquals 'x' OR @Resource[b] StringEquals '2'")
    assert e("!(@Resource[a] StringEquals 'x')")
    assert e("@Resource[a] StringEquals 'x' AND @Resource[a] StringEquals 'x' OR @Resource[b] StringEquals '2'")   # AND binds tighter
    assert not e("@Resource[a] StringEquals 'x' AND (@Resource[a] StringEquals 'x' OR @Resource[b] StringEquals '2')")


def test_abac_multivalue_cardinality():
    e = lambda s, v: az.eval_condition(s, "x", {"resource": {"tags": v}})
    assert e("@Resource[tags] ForAnyOfAnyValues:StringEquals {'a','z'}", ["a", "b"])
    assert not e("@Resource[tags] ForAnyOfAnyValues:StringEquals {'y','z'}", ["a", "b"])
    assert e("@Resource[tags] ForAllOfAnyValues:StringEquals {'a','b','c'}", ["a", "b"])
    assert not e("@Resource[tags] ForAllOfAnyValues:StringEquals {'a'}", ["a", "b"])
    assert e("@Resource[tags] ForAllOfAllValues:StringNotEquals {'x','y'}", ["a", "b"])
    assert e("@Resource[tags] ForAnyOfAllValues:StringStartsWith {'a'}", ["abc", "z"])
    assert not e("@Resource[tags] StringEquals 'a'", ["a"])                       # single-valued op on list


def test_abac_suboperation_and_environment_ip_and_datetime():
    assert az.eval_condition("SubOperationMatches{'Blob.Read.WithTagConditions'}", "x", {"suboperation": "Blob.Read.WithTagConditions"})
    assert not az.eval_condition("SubOperationMatches{'Blob.Read.WithTagConditions'}", "x", {})
    assert az.eval_condition("@Request[ip] IpMatch '10.0.0.0/8'", "x", {"request": {"ip": "10.1.2.3"}})
    assert az.eval_condition("@Environment[UtcNow] DateTimeLessThan '2027-01-01T00:00:00Z'", "x", {"environment": {"UtcNow": "2026-11-23T00:00:00Z"}})


def test_abac_bad_condition_fails_closed():
    assert not az.eval_condition("@Resource[a] NoSuchOp 'x'", "x", {"resource": {"a": "1"}})
    assert not az.eval_condition("((", "x", {})
    assert az.eval_condition("", "x", {})


def test_abac_ra_manager_condition_on_role_assignments():
    cond = "((!(Action ActionMatches{'Microsoft.Authorization/roleAssignments/write'})) OR (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {%s}))" % ("acdd72a7-3385-48ef-bd42-f606fba81ae7")
    cond = cond.replace("Action ActionMatches", "ActionMatches")
    st = {"role_assignments": [ra(UAA, RG, condition=cond)]}
    k = "Microsoft.Authorization/roleAssignments:RoleDefinitionId"
    # GuidEquals RHS is a bare token in a set -> parsed as word; Reader id allowed, Owner not
    assert ok(st, "Microsoft.Authorization/roleAssignments/write", scope=RG, context={"request": {k: READER}})
    assert not ok(st, "Microsoft.Authorization/roleAssignments/write", scope=RG, context={"request": {k: OWNER}})


# ---------------- decision shape / check_access
def test_decision_shape_matched_sources():
    d = ev({"role_assignments": [ra(READER, SUB)]}, "x/read")
    assert d["allowed"] and d["reason"] == "allow" and d["matched"][0]["source"] == "role_assignment" and d["matched"][0]["effect"] == "Allow"
    assert d["matched"][0]["statement"]["roleName"] == "Reader" and d["matched"][0]["statement"]["scope"] == SUB


def test_check_access_shape():
    st = {"role_assignments": [ra(READER, SUB)], "deny_assignments": [deny(permissions=[{"actions": ["Microsoft.Compute/virtualMachines/delete"]}])]}
    a = az.check_access(st, U, "Microsoft.Compute/virtualMachines/read", VM)
    assert a["accessDecision"] == "Allowed" and a["roleAssignment"]["roleName"] == "Reader" and a["denyAssignment"] is None and a["isDataAction"] is False
    b = az.check_access(st, U, "Microsoft.Compute/virtualMachines/delete", VM)
    assert b["accessDecision"] == "NotAllowed" and b["denyAssignment"]["id"] == "da1"
    c = az.check_access({"role_assignments": [ra(READER, SUB)]}, U, "Microsoft.Compute/virtualMachines/write", VM)
    assert c["accessDecision"] == "NotAllowed" and c["roleAssignment"] is None and c["decision"]["reason"] == "implicit_deny"


def test_empty_state_implicit_deny():
    assert ev({}, "x/read")["reason"] == "implicit_deny" and ev(None, "x/read")["allowed"] is False


def test_no_forbidden_imports():
    src = open(os.path.join(ROOT, "core", "iam_engine", "azure_eval.py")).read()
    assert "fastapi" not in src and "import socket" not in src
