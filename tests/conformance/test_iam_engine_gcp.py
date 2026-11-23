"""GCP IAM engine: inheritance, deny, PAB, groups, conditions, custom/basic roles (core/iam_engine/gcp_eval.py)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from core.iam_engine import gcp_eval as g  # noqa: E402

P = "//pubsub.googleapis.com/projects/p1/topics/t1"
PUB = "pubsub.topics.publish"
U = {"member": "user:a@x.com"}
SA = {"member": "serviceAccount:sa@p1.iam.gserviceaccount.com"}

HIER = {"projects/p1": "folders/f1", "folders/f1": "organizations/o1", "projects/p2": "organizations/o1"}


def st(**kw):
    base = {"hierarchy": HIER, "allow_policies": {}, "deny_policies": {}, "custom_roles": {}, "groups": {}}
    base.update(kw)
    return base


def allow(ap, role, members, cond=None):
    b = {"role": role, "members": members}
    if cond:
        b["condition"] = cond
    return {ap: {"bindings": [b]}}


def ev(state, perm=PUB, res=P, who=U, **ctx):
    return g.evaluate({"cloud": "gcp", "principal": who, "action": perm, "resource": res, "context": ctx}, state)


def ok(state, *a, **k):
    return ev(state, *a, **k)["allowed"]


# ---- allow basics / inheritance
def test_no_policy_implicit_deny():
    d = ev(st())
    assert not d["allowed"] and d["reason"] == "implicit_deny"


def test_resource_level_binding():
    assert ok(st(allow_policies=allow("projects/p1/topics/t1", "roles/pubsub.publisher", ["user:a@x.com"])))


def test_resource_binding_with_full_name_key():
    assert ok(st(allow_policies=allow(P, "roles/pubsub.publisher", ["user:a@x.com"])))


def test_project_inherits_to_resource():
    assert ok(st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["user:a@x.com"])))


def test_folder_inherits():
    assert ok(st(allow_policies=allow("folders/f1", "roles/pubsub.publisher", ["user:a@x.com"])))


def test_org_inherits():
    assert ok(st(allow_policies=allow("organizations/o1", "roles/pubsub.publisher", ["user:a@x.com"])))


def test_sibling_project_does_not_inherit():
    assert not ok(st(allow_policies=allow("projects/p2", "roles/pubsub.publisher", ["user:a@x.com"])))


def test_child_resource_does_not_grant_parent():
    assert not ok(st(allow_policies=allow("projects/p1/topics/t1", "roles/pubsub.publisher", ["user:a@x.com"])), res="//cloudresourcemanager.googleapis.com/projects/p1")


def test_union_across_levels():
    s = st(allow_policies={**allow("projects/p1", "roles/pubsub.subscriber", ["user:a@x.com"]),
                           **allow("organizations/o1", "roles/pubsub.publisher", ["user:a@x.com"])})
    assert ok(s, PUB) and ok(s, "pubsub.subscriptions.consume")


def test_wrong_permission_not_granted():
    assert not ok(st(allow_policies=allow("projects/p1", "roles/pubsub.subscriber", ["user:a@x.com"])), PUB)


def test_unknown_role_grants_nothing():
    assert not ok(st(allow_policies=allow("projects/p1", "roles/does.notExist", ["user:a@x.com"])))


def test_matched_reports_allow_policy():
    d = ev(st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["user:a@x.com"])))
    assert d["matched"][0]["source"] == "allow_policy" and d["matched"][0]["effect"] == "Allow"


def test_bare_path_resource():
    assert ok(st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["user:a@x.com"])), res="projects/p1/topics/t1")


# ---- principals
def test_other_user_not_matched():
    assert not ok(st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["user:b@x.com"])))


def test_service_account_member():
    assert ok(st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", [SA["member"]])), who=SA)


def test_all_users_matches_anonymous():
    assert ok(st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["allUsers"])), who={"member": ""})


def test_all_authenticated_not_anonymous():
    s = st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["allAuthenticatedUsers"]))
    assert ok(s) and not ok(s, who={"member": "allUsers"})


def test_domain_member():
    s = st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["domain:x.com"]))
    assert ok(s) and not ok(s, who={"member": "user:z@other.com"})


def test_group_member_direct():
    s = st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["group:eng@x.com"]), groups={"group:eng@x.com": ["user:a@x.com"]})
    assert ok(s)


def test_group_nested_membership():
    s = st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["group:all@x.com"]),
           groups={"group:all@x.com": ["group:eng@x.com"], "group:eng@x.com": ["user:a@x.com"]})
    assert ok(s)


def test_group_not_member():
    s = st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["group:eng@x.com"]), groups={"group:eng@x.com": ["user:b@x.com"]})
    assert not ok(s)


def test_principalset_group_form():
    s = st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["principalSet://goog/group/eng@x.com"]), groups={"group:eng@x.com": ["user:a@x.com"]})
    assert ok(s)


def test_principal_subject_form():
    assert ok(st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["principal://goog/subject/a@x.com"])))


def test_deleted_member_never_matches():
    assert not ok(st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["deleted:user:a@x.com?uid=123"])))


def test_project_owner_convenience_member():
    s = st(allow_policies={**allow("projects/p1", "roles/owner", ["user:a@x.com"]),
                           "projects/p1/topics/t1": {"bindings": [{"role": "roles/pubsub.publisher", "members": ["projectOwner:p1"]}]}})
    assert ok(s)
    assert not ok(s, who={"member": "user:z@x.com"})


# ---- basic + custom roles
def test_owner_role_grants_everything():
    s = st(allow_policies=allow("projects/p1", "roles/owner", ["user:a@x.com"]))
    assert ok(s, PUB) and ok(s, "compute.instances.delete")


def test_viewer_role_read_only():
    s = st(allow_policies=allow("projects/p1", "roles/viewer", ["user:a@x.com"]))
    assert ok(s, "pubsub.topics.get") and not ok(s, PUB) and not ok(s, "compute.instances.delete")


def test_editor_role_writes_but_no_setiam():
    s = st(allow_policies=allow("projects/p1", "roles/editor", ["user:a@x.com"]))
    assert ok(s, PUB) and not ok(s, "pubsub.topics.setIamPolicy")


def test_custom_role_project_scope():
    s = st(custom_roles={"projects/p1/roles/pub": {"includedPermissions": [PUB]}},
           allow_policies=allow("projects/p1", "projects/p1/roles/pub", ["user:a@x.com"]))
    assert ok(s) and not ok(s, "pubsub.topics.delete")


def test_custom_role_org_scope():
    s = st(custom_roles={"organizations/o1/roles/pub": {"includedPermissions": [PUB]}},
           allow_policies=allow("organizations/o1", "organizations/o1/roles/pub", ["user:a@x.com"]))
    assert ok(s)


def test_deleted_custom_role_grants_nothing():
    s = st(custom_roles={"projects/p1/roles/pub": {"includedPermissions": [PUB], "deleted": True}},
           allow_policies=allow("projects/p1", "projects/p1/roles/pub", ["user:a@x.com"]))
    assert not ok(s)


def test_catalog_override_in_state():
    s = st(catalog={"roles": {"roles/x": [PUB]}, "permissions": [PUB]}, allow_policies=allow("projects/p1", "roles/x", ["user:a@x.com"]))
    assert ok(s)


# ---- deny
def deny(ap, principals, perms, exc_p=None, exc_perm=None, cond=None):
    r = {"deniedPrincipals": principals, "deniedPermissions": perms}
    if exc_p:
        r["exceptionPrincipals"] = exc_p
    if exc_perm:
        r["exceptionPermissions"] = exc_perm
    if cond:
        r["denialCondition"] = {"expression": cond}
    return {ap: [{"name": "pol1", "rules": [{"denyRule": r}]}]}


GRANT = allow("projects/p1", "roles/pubsub.publisher", ["user:a@x.com"])
PUBD = "pubsub.googleapis.com/topics.publish"


def test_deny_wins_over_allow():
    d = ev(st(allow_policies=GRANT, deny_policies=deny("projects/p1", ["user:a@x.com"], [PUBD])))
    assert not d["allowed"] and d["reason"] == "explicit_deny" and d["matched"][-1]["source"] == "deny_policy"


def test_deny_at_org_applies_to_resource():
    assert not ok(st(allow_policies=GRANT, deny_policies=deny("organizations/o1", ["user:a@x.com"], [PUBD])))


def test_deny_at_folder():
    assert not ok(st(allow_policies=GRANT, deny_policies=deny("folders/f1", ["user:a@x.com"], [PUBD])))


def test_deny_other_project_ignored():
    assert ok(st(allow_policies=GRANT, deny_policies=deny("projects/p2", ["user:a@x.com"], [PUBD])))


def test_deny_other_principal_ignored():
    assert ok(st(allow_policies=GRANT, deny_policies=deny("projects/p1", ["user:b@x.com"], [PUBD])))


def test_deny_exception_principal():
    s = st(allow_policies=GRANT, deny_policies=deny("projects/p1", ["domain:x.com"], [PUBD], exc_p=["user:a@x.com"]))
    assert ok(s)


def test_deny_exception_permission():
    s = st(allow_policies=GRANT, deny_policies=deny("projects/p1", ["user:a@x.com"], ["pubsub.googleapis.com/topics.*"], exc_perm=[PUBD]))
    assert ok(s)


def test_deny_wildcard_verb():
    s = st(allow_policies=allow("projects/p1", "roles/pubsub.admin", ["user:a@x.com"]), deny_policies=deny("projects/p1", ["user:a@x.com"], ["pubsub.googleapis.com/topics.*"]))
    assert not ok(s, PUB) and not ok(s, "pubsub.topics.delete")
    assert ok(s, "pubsub.subscriptions.create")


def test_deny_wildcard_resource():
    s = st(allow_policies=allow("projects/p1", "roles/owner", ["user:a@x.com"]), deny_policies=deny("projects/p1", ["user:a@x.com"], ["pubsub.googleapis.com/*.create"]))
    assert not ok(s, "pubsub.topics.create") and not ok(s, "pubsub.subscriptions.create") and ok(s, PUB)


def test_deny_service_fqdn_mismatch():
    s = st(allow_policies=GRANT, deny_policies=deny("projects/p1", ["user:a@x.com"], ["compute.googleapis.com/topics.publish"]))
    assert ok(s)


def test_deny_bare_permission_form():
    assert not ok(st(allow_policies=GRANT, deny_policies=deny("projects/p1", ["user:a@x.com"], [PUB])))


def test_deny_resourcemanager_fqdn():
    s = st(allow_policies=allow("projects/p1", "roles/owner", ["user:a@x.com"]), deny_policies=deny("projects/p1", ["user:a@x.com"], ["cloudresourcemanager.googleapis.com/projects.delete"]))
    assert not ok(s, "resourcemanager.projects.delete", res="//cloudresourcemanager.googleapis.com/projects/p1")


def test_deny_group_principal():
    s = st(allow_policies=GRANT, groups={"group:g@x.com": ["user:a@x.com"]}, deny_policies=deny("projects/p1", ["group:g@x.com"], [PUBD]))
    assert not ok(s)


def test_deny_public_all():
    s = st(allow_policies=GRANT, deny_policies=deny("projects/p1", ["principalSet://goog/public:all"], [PUBD]))
    assert not ok(s)


def test_deny_condition_true_and_false():
    s = st(allow_policies=GRANT, deny_policies=deny("projects/p1", ["user:a@x.com"], [PUBD], cond="resource.name.startsWith('projects/p1/topics/secret')"))
    assert ok(s)
    assert not ok(s, res="//pubsub.googleapis.com/projects/p1/topics/secret-1")


def test_deny_unsupported_condition_fails_closed():
    s = st(allow_policies=GRANT, deny_policies=deny("projects/p1", ["user:a@x.com"], [PUBD], cond="foo.bar.baz(1)"))
    d = ev(s)
    assert not d["allowed"] and "fail closed" in d["matched"][-1]["note"]


def test_deny_dict_keyed_policies():
    s = st(allow_policies=GRANT, deny_policies={"projects/p1": {"pol1": {"rules": [{"denyRule": {"deniedPrincipals": ["user:a@x.com"], "deniedPermissions": [PUBD]}}]}}})
    assert not ok(s)


# ---- PAB
def pab(resources, who="user:a@x.com"):
    return {"pab_policies": {"organizations/o1/locations/global/principalAccessBoundaryPolicies/b": {"rules": [{"resources": resources, "effect": "ALLOW"}]}},
            "pab_bindings": [{"policy": "organizations/o1/locations/global/principalAccessBoundaryPolicies/b", "target": {"principalSet": who}}]}


def test_pab_inside_boundary_allows():
    assert ok(st(allow_policies=GRANT, **pab(["//cloudresourcemanager.googleapis.com/projects/p1"])))


def test_pab_outside_boundary_denies():
    d = ev(st(allow_policies=GRANT, **pab(["//cloudresourcemanager.googleapis.com/projects/p2"])))
    assert not d["allowed"] and d["matched"][0]["source"] == "pab"


def test_pab_folder_boundary_covers_project():
    assert ok(st(allow_policies=GRANT, **pab(["//cloudresourcemanager.googleapis.com/folders/f1"])))


def test_pab_does_not_widen():
    assert not ok(st(**pab(["//cloudresourcemanager.googleapis.com/projects/p1"])))


def test_pab_other_principal_unaffected():
    assert ok(st(allow_policies=GRANT, **pab(["//cloudresourcemanager.googleapis.com/projects/p2"], who="user:z@x.com")))


def test_pab_before_deny_reports_pab():
    d = ev(st(allow_policies=GRANT, deny_policies=deny("projects/p1", ["user:a@x.com"], [PUBD]), **pab(["//cloudresourcemanager.googleapis.com/projects/p2"])))
    assert d["matched"][0]["source"] == "pab"


# ---- conditions
def cond(expr):
    return allow("projects/p1", "roles/pubsub.publisher", ["user:a@x.com"], {"expression": expr, "title": "c"})


def test_cond_time_before_future():
    assert ok(st(allow_policies=cond('request.time < timestamp("2099-01-01T00:00:00Z")')))


def test_cond_time_expired():
    assert not ok(st(allow_policies=cond('request.time < timestamp("2000-01-01T00:00:00Z")')))


def test_cond_time_context_override():
    s = st(allow_policies=cond('request.time < timestamp("2025-01-01T00:00:00Z")'))
    assert ok(s, time="2024-06-01T00:00:00Z") and not ok(s, time="2026-06-01T00:00:00Z")


def test_cond_resource_name_startswith():
    s = st(allow_policies=cond('resource.name.startsWith("projects/p1/topics/t")'))
    assert ok(s) and not ok(s, res="//pubsub.googleapis.com/projects/p1/topics/zz")


def test_cond_resource_type_and_service():
    s = st(allow_policies=cond('resource.type == "pubsub.googleapis.com/Topic" && resource.service == "pubsub.googleapis.com"'))
    assert ok(s, resource_type="pubsub.googleapis.com/Topic")
    assert not ok(s, resource_type="pubsub.googleapis.com/Subscription")


def test_cond_or_not_in():
    s = st(allow_policies=cond('!(resource.name in ["a","b"]) || false'))
    assert ok(s)


def test_cond_endswith_contains_matches():
    assert ok(st(allow_policies=cond('resource.name.endsWith("t1") && resource.name.contains("topics") && resource.name.matches("^projects/p[0-9]/")')))


def test_cond_has_missing_field():
    s = st(allow_policies=cond('has(resource.labels) && resource.labels.env == "p"'))
    assert not ok(s)
    assert ok(s, resource={"labels": {"env": "p"}})


def test_cond_neq_and_ternary():
    assert ok(st(allow_policies=cond('resource.name != "x" ? true : false')))


def test_cond_time_functions():
    s = st(allow_policies=cond('request.time.getHours("+00:00") >= 9 && request.time.getHours("+00:00") < 17'))
    assert ok(s, time="2026-01-05T10:00:00Z") and not ok(s, time="2026-01-05T20:00:00Z")


def test_cond_day_of_week():
    s = st(allow_policies=cond("request.time.getDayOfWeek() != 0"))
    assert ok(s, time="2026-01-05T10:00:00Z") and not ok(s, time="2026-01-04T10:00:00Z")  # Mon vs Sun


def test_cond_duration_arith():
    s = st(allow_policies=cond('request.time < timestamp("2026-01-01T00:00:00Z") + duration("24h")'))
    assert ok(s, time="2026-01-01T12:00:00Z") and not ok(s, time="2026-01-03T00:00:00Z")


def test_cond_unsupported_noted_not_granted():
    d = ev(st(allow_policies=cond("resource.name.frobnicate()")))
    assert not d["allowed"] and d["matched"][0]["effect"] == "NotApplicable" and "unsupported" in d["matched"][0]["note"]


def test_cond_syntax_error_not_granted():
    assert not ok(st(allow_policies=cond("resource.name ==")))


def test_cond_non_bool_not_granted():
    assert not ok(st(allow_policies=cond("1 + 1")))


def test_cond_error_absorbed_by_short_circuit():
    assert ok(st(allow_policies=cond("true || nosuchvar.x == 1")))


def test_cond_unconditional_binding_still_grants_when_other_cond_fails():
    s = st(allow_policies={"projects/p1": {"bindings": [
        {"role": "roles/pubsub.publisher", "members": ["user:a@x.com"], "condition": {"expression": "false"}},
        {"role": "roles/pubsub.publisher", "members": ["user:a@x.com"]}]}})
    assert ok(s)


# ---- testIamPermissions
def test_test_iam_permissions_subset():
    s = st(allow_policies=allow("projects/p1", "roles/pubsub.publisher", ["user:a@x.com"]))
    assert g.test_iam_permissions(U, P, [PUB, "pubsub.topics.delete"], s) == [PUB]


def test_test_iam_permissions_applies_deny():
    s = st(allow_policies=GRANT, deny_policies=deny("projects/p1", ["user:a@x.com"], [PUBD]))
    assert g.test_iam_permissions(U, P, [PUB], s) == []


def test_catalog_loads_and_basic_roles_derived():
    c = g.load_catalog()
    assert c["roles"]["roles/pubsub.publisher"] and len(c["permissions"]) > 5000
    assert PUB in g.role_permissions("roles/owner", {})
