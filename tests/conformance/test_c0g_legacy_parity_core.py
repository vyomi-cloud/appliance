"""v4 C0g — AWS IAM joins the unified wire ingress.

The offline appliance's IAM native wire used to be served by a small pre-v4 handler
(server.py `api_iam_query` + providers/aws_iam.py) that only knew CreateUser/GetUser/
ListUsers/DeleteUser/CreateRole/GetRole/ListRoles/DeleteRole/CreatePolicy/GetPolicy/
ListPolicies/DeletePolicy — every other IAM action the v4 console calls (groups, tags,
access keys, login profile, policy versions, entities-for-policy, SimulatePrincipalPolicy,
identity providers, account settings, credential report, org policies, access requests)
answered `InvalidAction`, even though core/iam_core.py (Nano's IAM) already implements all
of it. This suite pins the fix: `core.wire_ingress.dispatch_service("iam", ...)` reaches
core/iam_core.py — the SAME router Nano uses — and the appliance upgrade path
(core/appliance_stores.py: adopting the pre-v4 handler's users/groups/roles/policies/
identity-providers/password-policy once per space) converts what the classic console
created.

Run:  PYTHONPATH=. python3 tests/conformance/test_c0g_legacy_parity_core.py
"""
from urllib.parse import urlencode

from core.aws_wire_router import AwsWireRouter
from core.iam_store import InMemoryIamStore


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


# ── dispatch_service("iam", ...) reaches core/iam_core.py ──────────────────────────────
def unified_dispatch():
    from core import wire_ingress as wi

    router = AwsWireRouter(stores={"iam": InMemoryIamStore()})

    def call(action, **params):
        body = urlencode({"Action": action, **params}).encode()
        return wi.dispatch_service("iam", "POST", "/", {}, {"content-type": "application/x-www-form-urlencoded"},
                                   body, router=router)

    out = call("CreateUser", UserName="alice")
    _check("dispatch_service(iam): CreateUser -> core/iam_core.py XML",
           out["status"] == 200 and b"<UserName>alice</UserName>" in out["body"])
    _check("dispatch_service(iam): text/xml content-type", "text/xml" in out["headers"].get("content-type", ""))

    out = call("ListGroups")
    _check("dispatch_service(iam): ListGroups (the reported offline gap) now answers 200",
           out["status"] == 200 and b"<ListGroupsResponse" in out["body"])

    out = call("CreateGroup", GroupName="devs")
    _check("dispatch_service(iam): CreateGroup", out["status"] == 200 and b"<GroupName>devs</GroupName>" in out["body"])

    out = call("AddUserToGroup", GroupName="devs", UserName="alice")
    _check("dispatch_service(iam): AddUserToGroup", out["status"] == 200)

    out = call("ListGroupsForUser", UserName="alice")
    _check("dispatch_service(iam): ListGroupsForUser sees the group alice just joined",
           b"<GroupName>devs</GroupName>" in out["body"])

    out = call("CreateUser", UserName="alice")
    _check("dispatch_service(iam): duplicate CreateUser -> EntityAlreadyExists (not a 500)",
           out["status"] == 409 and b"EntityAlreadyExists" in out["body"])

    out = call("GetUser", UserName="nope")
    _check("dispatch_service(iam): unknown user -> NoSuchEntity", out["status"] == 404 and b"NoSuchEntity" in out["body"])


# ── appliance upgrade path (pre-v4 iam_state -> the core shape) ────────────────────────
def upgrade_path():
    try:
        from core import appliance_stores as aps
    except Exception as exc:   # pragma: no cover - not on Pyodide
        print(f"  skip upgrade path ({exc})")
        return

    legacy = {
        "users": {"user-1": {"user_id": "user-1", "user_name": "bob", "path": "/", "created": "2026-01-01T00:00:00Z",
                              "policies": ["policy-1"], "groups": ["group-1"]}},
        "groups": {"group-1": {"group_id": "group-1", "group_name": "admins", "path": "/",
                                "created": "2026-01-01T00:00:00Z", "members": ["user-1"], "policies": ["policy-1"]}},
        "roles": {"role-1": {"role_id": "role-1", "role_name": "ci-role", "path": "/",
                             "assume_role_policy_document": {"Version": "2012-10-17"}, "description": "pre-v4 role",
                             "created": "2026-01-01T00:00:00Z", "policies": ["policy-1"]}},
        "policies": {"policy-1": {"policy_id": "policy-1", "policy_name": "AdminAccess",
                                  "document": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]},
                                  "created": "2026-01-01T00:00:00Z"}},
        "attachments": [{"target_type": "user", "target_id": "user-1", "policy_id": "policy-1"}],
        "identity_providers": {"idp-1": {"provider_id": "idp-1", "provider_name": "corp-saml",
                                         "provider_type": "SAML", "url": "<EntityDescriptor/>",
                                         "created": "2026-01-01T00:00:00Z", "tags": []}},
        "account_settings": {"password_policy": {"minimum_length": 14, "require_symbols": True}},
    }
    slot = {}
    n = aps.adopt_legacy_iam(slot, legacy, account_id="123456789012")
    _check("[upgrade] every pre-v4 entity converted", n == 5)
    _check("[upgrade] user re-keyed by name, ARN computed",
           "bob" in slot["users"] and slot["users"]["bob"]["arn"] == "arn:aws:iam::123456789012:user/bob")
    _check("[upgrade] user's policy_id resolved to the policy's ARN",
           slot["users"]["bob"]["attached_policies"] == ["arn:aws:iam::123456789012:policy/AdminAccess"])
    _check("[upgrade] user's group membership carried by name", slot["users"]["bob"]["groups"] == ["admins"])
    _check("[upgrade] group membership carried (reverse link)", slot["groups"]["admins"]["members"] == ["bob"])
    _check("[upgrade] role carried (trust policy, description, policies)",
           slot["roles"]["ci-role"]["assume_role_policy_document"] == {"Version": "2012-10-17"}
           and slot["roles"]["ci-role"]["attached_policies"])
    _check("[upgrade] policy attachment_count reflects the adopted attachments",
           slot["policies"]["arn:aws:iam::123456789012:policy/AdminAccess"]["attachment_count"] == 3)
    _check("[upgrade] SAML identity provider carried",
           any(p["name"] == "corp-saml" for p in slot["saml_providers"].values()))
    _check("[upgrade] account password policy carried", slot["password_policy"]["minimum_length"] == 14)
    _check("[upgrade] idempotent (second pass converts nothing new)", aps.adopt_legacy_iam(slot, legacy) == 0)

    # the adopted records are served natively by core/iam_core.py (not just shaped like it)
    from core import iam_core as iam
    st = InMemoryIamStore()
    st.users, st.groups, st.roles, st.policies = slot["users"], slot["groups"], slot["roles"], slot["policies"]
    r = iam.dispatch(st, {"Action": "GetUser", "UserName": "bob"})
    _check("[upgrade] the converted user is served by core/iam_core.py", r.status == 200 and "bob" in r.body)


def run() -> int:
    print("Unified dispatch:")
    unified_dispatch()
    print("Upgrade path:")
    upgrade_path()
    print("\nC0g legacy-parity (IAM joins the unified wire ingress): ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
