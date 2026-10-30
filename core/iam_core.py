"""IAM core — substrate-independent, extracted from the appliance IAM handler
(providers/aws_iam.py + server.py `_iam_*`) so the SAME logic runs in Pro/Max
(FastAPI), Nano (Pyodide), and tests. NO fastapi / boto3 / socket / cedarpy
imports → loads under Pyodide. Persists through the IamStore seam and decides
through the AuthzEngine seam (core/iam_store.py).

IAM speaks the AWS **Query protocol**: form-encoded POST with `Action=...&...` and
**XML** responses (https://iam.amazonaws.com/doc/2010-05-08/). The control plane
returns an `IamResponse` (status, XML body, headers) in the native shapes
(<CreateUserResult><User>...</User></...>, <ErrorResponse><Error><Code>...).

The star of this entry is the DECISION path: SimulatePrincipalPolicy resolves a
principal's effective policies (attached managed + inline + group policies) and
runs them through the AuthzEngine, returning native EvaluationResults with
EvalDecision (allowed / explicitDeny / implicitDeny). The default engine is the
pure-Python NativeIamEvaluator; cedar-wasm can swap in behind the seam in-browser.

Scope (v1 slice): users (Create/Get/List/Delete), roles (Create/Get/List/Delete),
managed policies (Create/Get/List/Delete), groups (Create/AddUserToGroup),
attach/detach + ListAttachedUserPolicies, inline Put/Get UserPolicy, access keys
(Create/List), and SimulatePrincipalPolicy. MFA / SAML / instance profiles /
policy versions reuse the same helpers and slot in next.
"""
from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape as _xml_escape

from core.iam_store import IamStore

IAM_NS = "https://iam.amazonaws.com/doc/2010-05-08/"


@dataclass
class IamResponse:
    status: int = 200
    body: str = ""          # XML text
    headers: dict = field(default_factory=dict)
    media_type: str = "text/xml"


class IamError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


# ── primitives ─────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _req_id() -> str:
    return uuid.uuid4().hex


def _id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:17].upper()


def _user_arn(store, name): return f"arn:aws:iam::{store.account_id}:user/{name}"
def _role_arn(store, name): return f"arn:aws:iam::{store.account_id}:role/{name}"
def _group_arn(store, name): return f"arn:aws:iam::{store.account_id}:group/{name}"
def _policy_arn(store, name): return f"arn:aws:iam::{store.account_id}:policy/{name}"


# ── form-encoded param helpers (Query protocol) ────────────────────────────
def _members(params: dict, base: str) -> list[str]:
    """Collect AWS Query list params: base.member.1, base.member.2, ..."""
    out, i = [], 1
    while True:
        key = f"{base}.member.{i}"
        if key not in params:
            break
        out.append(params[key])
        i += 1
    return out


def _json_param(params: dict, key: str) -> dict:
    raw = params.get(key)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        raise IamError("MalformedPolicyDocument", f"{key} is not valid JSON.", 400)


# ── response builders (native IAM Query-protocol XML) ──────────────────────
def _envelope(action: str, result_inner: str = "", status: int = 200) -> IamResponse:
    result = f"<{action}Result>{result_inner}</{action}Result>" if result_inner else ""
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<{action}Response xmlns="{IAM_NS}">{result}'
           f'<ResponseMetadata><RequestId>{_req_id()}</RequestId></ResponseMetadata>'
           f'</{action}Response>')
    return IamResponse(status=status, body=xml)


def _error(code: str, message: str, status: int = 400) -> IamResponse:
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<ErrorResponse xmlns="{IAM_NS}">'
           f'<Error><Type>Sender</Type><Code>{_xml_escape(code)}</Code>'
           f'<Message>{_xml_escape(message)}</Message></Error>'
           f'<RequestId>{_req_id()}</RequestId></ErrorResponse>')
    return IamResponse(status=status, body=xml)


def _el(tag, value): return f"<{tag}>{_xml_escape(str(value))}</{tag}>"


def _user_xml(store, u: dict) -> str:
    return ("<User>" + _el("Path", u.get("path", "/")) + _el("UserName", u["user_name"])
            + _el("UserId", u["user_id"]) + _el("Arn", u["arn"])
            + _el("CreateDate", u["created"])
            + (_el("PermissionsBoundary", u["permissions_boundary"]) if u.get("permissions_boundary") else "")
            + "</User>")


def _role_xml(store, r: dict) -> str:
    doc = r.get("assume_role_policy_document") or {}
    trust = _xml_escape(json.dumps(doc)) if doc else ""
    return ("<Role>" + _el("Path", r.get("path", "/")) + _el("RoleName", r["role_name"])
            + _el("RoleId", r["role_id"]) + _el("Arn", r["arn"]) + _el("CreateDate", r["created"])
            + _el("Description", r.get("description", "")) + _el("MaxSessionDuration", r.get("max_session_duration", 3600))
            + (f"<AssumeRolePolicyDocument>{trust}</AssumeRolePolicyDocument>" if trust else "")
            + (_el("PermissionsBoundary", r["permissions_boundary"]) if r.get("permissions_boundary") else "")
            + "</Role>")


def _policy_xml(store, p: dict) -> str:
    return ("<Policy>" + _el("PolicyName", p["policy_name"]) + _el("PolicyId", p["policy_id"])
            + _el("Arn", p["arn"]) + _el("Path", p.get("path", "/"))
            + _el("Description", p.get("description", ""))
            + _el("DefaultVersionId", p.get("default_version_id", "v1"))
            + _el("AttachmentCount", p.get("attachment_count", 0))
            + _el("CreateDate", p["created"]) + _el("UpdateDate", p.get("updated", p["created"])) + "</Policy>")


# ── helpers ────────────────────────────────────────────────────────────────
def _require_user(store, name):
    u = store.get_user(name)
    if not u:
        raise IamError("NoSuchEntity", f"The user with name {name} cannot be found.", 404)
    return u


def _require_role(store, name):
    r = store.get_role(name)
    if not r:
        raise IamError("NoSuchEntity", f"The role with name {name} cannot be found.", 404)
    return r


def _require_policy(store, arn):
    p = store.get_policy(arn)
    if not p:
        raise IamError("NoSuchEntity", f"Policy {arn} does not exist.", 404)
    return p


def _require_group(store, name):
    g = store.get_group(name)
    if not g:
        raise IamError("NoSuchEntity", f"The group with name {name} cannot be found.", 404)
    return g


# ── tag helpers (shared shape: Tags.member.N.{Key,Value}) ──────────────────
def _parse_tags(params: dict) -> dict:
    out, i = {}, 1
    while True:
        k = params.get(f"Tags.member.{i}.Key")
        if k is None:
            break
        out[k] = params.get(f"Tags.member.{i}.Value", "")
        i += 1
    return out


def _tags_xml(tags: dict) -> str:
    items = "".join("<member>" + _el("Key", k) + _el("Value", v) + "</member>" for k, v in tags.items())
    return f"<Tags>{items}</Tags>"


# ── user operations ─────────────────────────────────────────────────────────
def _create_user(store, params):
    name = str(params.get("UserName", "")).strip()
    if not name:
        raise IamError("ValidationError", "UserName is required.", 400)
    if store.get_user(name):
        raise IamError("EntityAlreadyExists", f"User with name {name} already exists.", 409)
    u = {"user_name": name, "user_id": _id("AIDA"), "path": params.get("Path", "/"),
         "arn": _user_arn(store, name), "created": _now(),
         "attached_policies": [], "inline_policies": {}, "groups": [],
         "tags": _parse_tags(params), "permissions_boundary": None, "login_profile": None}
    store.users[name] = u
    store.persist()
    return _envelope("CreateUser", _user_xml(store, u))


def _get_user(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    return _envelope("GetUser", _user_xml(store, u))


def _list_users(store, params):
    inner = "<Users>" + "".join(_user_xml(store, store.users[n]) for n in sorted(store.users)) + "</Users>"
    return _envelope("ListUsers", inner)


def _delete_user(store, params):
    name = str(params.get("UserName", "")).strip()
    _require_user(store, name)
    del store.users[name]
    store.persist()
    return _envelope("DeleteUser")


# ── role operations ──────────────────────────────────────────────────────────
def _create_role(store, params):
    name = str(params.get("RoleName", "")).strip()
    if not name:
        raise IamError("ValidationError", "RoleName is required.", 400)
    if store.get_role(name):
        raise IamError("EntityAlreadyExists", f"Role with name {name} already exists.", 409)
    r = {"role_name": name, "role_id": _id("AROA"), "path": params.get("Path", "/"),
         "arn": _role_arn(store, name), "created": _now(),
         "assume_role_policy_document": _json_param(params, "AssumeRolePolicyDocument"),
         "description": params.get("Description", ""),
         "max_session_duration": int(params.get("MaxSessionDuration") or 3600),
         "attached_policies": [], "inline_policies": {},
         "tags": _parse_tags(params), "permissions_boundary": None}
    store.roles[name] = r
    store.persist()
    return _envelope("CreateRole", _role_xml(store, r))


def _get_role(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    return _envelope("GetRole", _role_xml(store, r))


def _list_roles(store, params):
    inner = "<Roles>" + "".join(_role_xml(store, store.roles[n]) for n in sorted(store.roles)) + "</Roles>"
    return _envelope("ListRoles", inner)


def _delete_role(store, params):
    name = str(params.get("RoleName", "")).strip()
    _require_role(store, name)
    del store.roles[name]
    store.persist()
    return _envelope("DeleteRole")


# ── managed policy operations ────────────────────────────────────────────────
def _create_policy(store, params):
    name = str(params.get("PolicyName", "")).strip()
    if not name:
        raise IamError("ValidationError", "PolicyName is required.", 400)
    arn = _policy_arn(store, name)
    if store.get_policy(arn):
        raise IamError("EntityAlreadyExists", f"Policy {name} already exists.", 409)
    doc = _json_param(params, "PolicyDocument")
    now = _now()
    p = {"policy_name": name, "policy_id": _id("ANPA"), "arn": arn,
         "path": params.get("Path", "/"), "document": doc, "description": params.get("Description", ""),
         "created": now, "updated": now, "default_version_id": "v1", "attachment_count": 0,
         "tags": _parse_tags(params),
         "versions": {"v1": {"document": doc, "created": now}}}
    store.policies[arn] = p
    store.persist()
    return _envelope("CreatePolicy", _policy_xml(store, p))


def _get_policy(store, params):
    p = _require_policy(store, str(params.get("PolicyArn", "")).strip())
    return _envelope("GetPolicy", _policy_xml(store, p))


def _list_policies(store, params):
    inner = "<Policies>" + "".join(_policy_xml(store, store.policies[a]) for a in sorted(store.policies)) + "</Policies>"
    return _envelope("ListPolicies", inner)


def _delete_policy(store, params):
    arn = str(params.get("PolicyArn", "")).strip()
    _require_policy(store, arn)
    del store.policies[arn]
    for u in store.users.values():
        u["attached_policies"] = [a for a in u["attached_policies"] if a != arn]
    for r in store.roles.values():
        r["attached_policies"] = [a for a in r["attached_policies"] if a != arn]
    for g in store.groups.values():
        g["attached_policies"] = [a for a in g["attached_policies"] if a != arn]
    store.persist()
    return _envelope("DeletePolicy")


# ── attach / detach + inline ─────────────────────────────────────────────────
def _attach_user_policy(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    arn = str(params.get("PolicyArn", "")).strip()
    p = _require_policy(store, arn)
    if arn not in u["attached_policies"]:
        u["attached_policies"].append(arn)
        p["attachment_count"] = p.get("attachment_count", 0) + 1
    store.persist()
    return _envelope("AttachUserPolicy")


def _detach_user_policy(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    arn = str(params.get("PolicyArn", "")).strip()
    if arn in u["attached_policies"]:
        u["attached_policies"].remove(arn)
        p = store.get_policy(arn)
        if p:
            p["attachment_count"] = max(0, p.get("attachment_count", 1) - 1)
    store.persist()
    return _envelope("DetachUserPolicy")


def _list_attached_user_policies(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    items = []
    for arn in u["attached_policies"]:
        p = store.get_policy(arn)
        if p:
            items.append("<member>" + _el("PolicyName", p["policy_name"]) + _el("PolicyArn", arn) + "</member>")
    return _envelope("ListAttachedUserPolicies", f"<AttachedPolicies>{''.join(items)}</AttachedPolicies>")


def _attach_role_policy(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    arn = str(params.get("PolicyArn", "")).strip()
    _require_policy(store, arn)
    if arn not in r["attached_policies"]:
        r["attached_policies"].append(arn)
    store.persist()
    return _envelope("AttachRolePolicy")


def _put_user_policy(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    pname = str(params.get("PolicyName", "")).strip()
    if not pname:
        raise IamError("ValidationError", "PolicyName is required.", 400)
    u["inline_policies"][pname] = _json_param(params, "PolicyDocument")
    store.persist()
    return _envelope("PutUserPolicy")


def _get_user_policy(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    pname = str(params.get("PolicyName", "")).strip()
    doc = u["inline_policies"].get(pname)
    if doc is None:
        raise IamError("NoSuchEntity", f"Inline policy {pname} not found.", 404)
    inner = _el("UserName", u["user_name"]) + _el("PolicyName", pname) + \
        f"<PolicyDocument>{_xml_escape(json.dumps(doc))}</PolicyDocument>"
    return _envelope("GetUserPolicy", inner)


def _list_user_policies(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    inner = "<PolicyNames>" + "".join(_el("member", n) for n in u["inline_policies"]) + "</PolicyNames>"
    return _envelope("ListUserPolicies", inner)


def _delete_user_policy(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    u["inline_policies"].pop(str(params.get("PolicyName", "")).strip(), None)
    store.persist()
    return _envelope("DeleteUserPolicy")


def _update_user(store, params):
    name = str(params.get("UserName", "")).strip()
    u = _require_user(store, name)
    new_name = str(params.get("NewUserName", "")).strip()
    if new_name and new_name != name:
        if store.get_user(new_name):
            raise IamError("EntityAlreadyExists", f"User with name {new_name} already exists.", 409)
        u["user_name"] = new_name
        u["arn"] = _user_arn(store, new_name)
        del store.users[name]
        store.users[new_name] = u
        for g in store.groups.values():
            if name in g["members"]:
                g["members"] = [new_name if m == name else m for m in g["members"]]
    if params.get("NewPath"):
        u["path"] = params["NewPath"]
    store.persist()
    return _envelope("UpdateUser")


def _tag_user(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    u["tags"].update(_parse_tags(params))
    store.persist()
    return _envelope("TagUser")


def _untag_user(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    for k in _members(params, "TagKeys"):
        u["tags"].pop(k, None)
    store.persist()
    return _envelope("UntagUser")


def _list_user_tags(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    return _envelope("ListUserTags", _tags_xml(u["tags"]))


def _put_user_permissions_boundary(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    arn = str(params.get("PermissionsBoundary", "")).strip()
    _require_policy(store, arn)
    u["permissions_boundary"] = arn
    store.persist()
    return _envelope("PutUserPermissionsBoundary")


def _delete_user_permissions_boundary(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    u["permissions_boundary"] = None
    store.persist()
    return _envelope("DeleteUserPermissionsBoundary")


# ── console sign-in (login profile) — limited: stored, never actually authenticated ──
def _create_login_profile(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    if u["login_profile"]:
        raise IamError("EntityAlreadyExists", "Login profile already exists.", 409)
    u["login_profile"] = {"created": _now(),
                          "password_reset_required": str(params.get("PasswordResetRequired", "false")).lower() == "true"}
    store.persist()
    inner = ("<LoginProfile>" + _el("UserName", u["user_name"]) + _el("CreateDate", u["login_profile"]["created"])
             + _el("PasswordResetRequired", str(u["login_profile"]["password_reset_required"]).lower()) + "</LoginProfile>")
    return _envelope("CreateLoginProfile", inner)


def _get_login_profile(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    if not u["login_profile"]:
        raise IamError("NoSuchEntity", "Login profile not found.", 404)
    inner = ("<LoginProfile>" + _el("UserName", u["user_name"]) + _el("CreateDate", u["login_profile"]["created"])
             + _el("PasswordResetRequired", str(u["login_profile"]["password_reset_required"]).lower()) + "</LoginProfile>")
    return _envelope("GetLoginProfile", inner)


def _update_login_profile(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    if not u["login_profile"]:
        raise IamError("NoSuchEntity", "Login profile not found.", 404)
    if "PasswordResetRequired" in params:
        u["login_profile"]["password_reset_required"] = str(params["PasswordResetRequired"]).lower() == "true"
    store.persist()
    return _envelope("UpdateLoginProfile")


def _delete_login_profile(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    u["login_profile"] = None
    store.persist()
    return _envelope("DeleteLoginProfile")


# ── groups ───────────────────────────────────────────────────────────────────
def _create_group(store, params):
    name = str(params.get("GroupName", "")).strip()
    if not name:
        raise IamError("ValidationError", "GroupName is required.", 400)
    if store.get_group(name):
        raise IamError("EntityAlreadyExists", f"Group {name} already exists.", 409)
    g = {"group_name": name, "group_id": _id("AGPA"), "path": params.get("Path", "/"),
         "arn": _group_arn(store, name), "created": _now(), "members": [], "attached_policies": [],
         "inline_policies": {}}
    store.groups[name] = g
    store.persist()
    return _envelope("CreateGroup", _group_xml(store, g))


def _group_xml(store, g: dict) -> str:
    return ("<Group>" + _el("Path", g.get("path", "/")) + _el("GroupName", g["group_name"])
            + _el("GroupId", g["group_id"]) + _el("Arn", g["arn"]) + _el("CreateDate", g["created"]) + "</Group>")


def _list_groups(store, params):
    inner = "<Groups>" + "".join(_group_xml(store, store.groups[n]) for n in sorted(store.groups)) + "</Groups>"
    return _envelope("ListGroups", inner)


def _get_group(store, params):
    g = _require_group(store, str(params.get("GroupName", "")).strip())
    users = "".join(_user_xml(store, store.users[u]) for u in g["members"] if u in store.users)
    return _envelope("GetGroup", _group_xml(store, g) + f"<Users>{users}</Users>")


def _delete_group(store, params):
    name = str(params.get("GroupName", "")).strip()
    g = _require_group(store, name)
    if g["members"] or g["attached_policies"] or g["inline_policies"]:
        raise IamError("DeleteConflict", "Cannot delete a group with members or attached policies.", 409)
    for u in store.users.values():
        if name in u["groups"]:
            u["groups"].remove(name)
    del store.groups[name]
    store.persist()
    return _envelope("DeleteGroup")


def _remove_user_from_group(store, params):
    g = _require_group(store, str(params.get("GroupName", "")).strip())
    name = str(params.get("UserName", "")).strip()
    u = _require_user(store, name)
    if name in g["members"]:
        g["members"].remove(name)
    if g["group_name"] in u["groups"]:
        u["groups"].remove(g["group_name"])
    store.persist()
    return _envelope("RemoveUserFromGroup")


def _list_groups_for_user(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    inner = "<Groups>" + "".join(_group_xml(store, store.groups[n]) for n in u["groups"] if n in store.groups) + "</Groups>"
    return _envelope("ListGroupsForUser", inner)


def _detach_group_policy(store, params):
    g = _require_group(store, str(params.get("GroupName", "")).strip())
    arn = str(params.get("PolicyArn", "")).strip()
    if arn in g["attached_policies"]:
        g["attached_policies"].remove(arn)
        p = store.get_policy(arn)
        if p:
            p["attachment_count"] = max(0, p.get("attachment_count", 1) - 1)
    store.persist()
    return _envelope("DetachGroupPolicy")


def _list_attached_group_policies(store, params):
    g = _require_group(store, str(params.get("GroupName", "")).strip())
    items = []
    for arn in g["attached_policies"]:
        p = store.get_policy(arn)
        if p:
            items.append("<member>" + _el("PolicyName", p["policy_name"]) + _el("PolicyArn", arn) + "</member>")
    return _envelope("ListAttachedGroupPolicies", f"<AttachedPolicies>{''.join(items)}</AttachedPolicies>")


def _put_group_policy(store, params):
    g = _require_group(store, str(params.get("GroupName", "")).strip())
    pname = str(params.get("PolicyName", "")).strip()
    if not pname:
        raise IamError("ValidationError", "PolicyName is required.", 400)
    g["inline_policies"][pname] = _json_param(params, "PolicyDocument")
    store.persist()
    return _envelope("PutGroupPolicy")


def _get_group_policy(store, params):
    g = _require_group(store, str(params.get("GroupName", "")).strip())
    pname = str(params.get("PolicyName", "")).strip()
    doc = g["inline_policies"].get(pname)
    if doc is None:
        raise IamError("NoSuchEntity", f"Inline policy {pname} not found.", 404)
    inner = _el("GroupName", g["group_name"]) + _el("PolicyName", pname) + \
        f"<PolicyDocument>{_xml_escape(json.dumps(doc))}</PolicyDocument>"
    return _envelope("GetGroupPolicy", inner)


def _list_group_policies(store, params):
    g = _require_group(store, str(params.get("GroupName", "")).strip())
    inner = "<PolicyNames>" + "".join(_el("member", n) for n in g["inline_policies"]) + "</PolicyNames>"
    return _envelope("ListGroupPolicies", inner)


def _delete_group_policy(store, params):
    g = _require_group(store, str(params.get("GroupName", "")).strip())
    pname = str(params.get("PolicyName", "")).strip()
    g["inline_policies"].pop(pname, None)
    store.persist()
    return _envelope("DeleteGroupPolicy")


def _add_user_to_group(store, params):
    g = store.get_group(str(params.get("GroupName", "")).strip())
    if not g:
        raise IamError("NoSuchEntity", "Group not found.", 404)
    u = _require_user(store, str(params.get("UserName", "")).strip())
    if u["user_name"] not in g["members"]:
        g["members"].append(u["user_name"])
    if g["group_name"] not in u["groups"]:
        u["groups"].append(g["group_name"])
    store.persist()
    return _envelope("AddUserToGroup")


def _attach_group_policy(store, params):
    g = store.get_group(str(params.get("GroupName", "")).strip())
    if not g:
        raise IamError("NoSuchEntity", "Group not found.", 404)
    arn = str(params.get("PolicyArn", "")).strip()
    _require_policy(store, arn)
    if arn not in g["attached_policies"]:
        g["attached_policies"].append(arn)
    store.persist()
    return _envelope("AttachGroupPolicy")


# ── access keys ──────────────────────────────────────────────────────────────
def _create_access_key(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    akid = "AKIA" + uuid.uuid4().hex[:16].upper()
    secret = uuid.uuid4().hex + uuid.uuid4().hex[:8]
    store.access_keys[akid] = {"access_key_id": akid, "user_name": u["user_name"],
                              "status": "Active", "secret_access_key": secret, "created": _now()}
    store.persist()
    inner = ("<AccessKey>" + _el("UserName", u["user_name"]) + _el("AccessKeyId", akid)
             + _el("Status", "Active") + _el("SecretAccessKey", secret)
             + _el("CreateDate", store.access_keys[akid]["created"]) + "</AccessKey>")
    return _envelope("CreateAccessKey", inner)


def _list_access_keys(store, params):
    name = str(params.get("UserName", "")).strip()
    _require_user(store, name)
    items = []
    for k in store.access_keys.values():
        if k["user_name"] == name:
            items.append("<member>" + _el("UserName", name) + _el("AccessKeyId", k["access_key_id"])
                         + _el("Status", k["status"]) + _el("CreateDate", k["created"]) + "</member>")
    return _envelope("ListAccessKeys", f"<AccessKeyMetadata>{''.join(items)}</AccessKeyMetadata>")


def _require_access_key(store, akid, user_name=None):
    k = store.access_keys.get(akid)
    if not k or (user_name and k["user_name"] != user_name):
        raise IamError("NoSuchEntity", f"Access key {akid} not found.", 404)
    return k


def _update_access_key(store, params):
    akid = str(params.get("AccessKeyId", "")).strip()
    k = _require_access_key(store, akid, str(params.get("UserName", "")).strip() or None)
    status = str(params.get("Status", "")).strip()
    if status not in ("Active", "Inactive"):
        raise IamError("ValidationError", "Status must be Active or Inactive.", 400)
    k["status"] = status
    store.persist()
    return _envelope("UpdateAccessKey")


def _delete_access_key(store, params):
    akid = str(params.get("AccessKeyId", "")).strip()
    _require_access_key(store, akid, str(params.get("UserName", "")).strip() or None)
    del store.access_keys[akid]
    store.persist()
    return _envelope("DeleteAccessKey")


# ── roles: trust policy, session duration, tags, inline/attached policies ──────
def _update_role(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    if params.get("Description") is not None:
        r["description"] = params["Description"]
    if params.get("MaxSessionDuration"):
        r["max_session_duration"] = int(params["MaxSessionDuration"])
    store.persist()
    return _envelope("UpdateRole")


def _update_assume_role_policy(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    r["assume_role_policy_document"] = _json_param(params, "PolicyDocument")
    store.persist()
    return _envelope("UpdateAssumeRolePolicy")


def _list_attached_role_policies(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    items = []
    for arn in r["attached_policies"]:
        p = store.get_policy(arn)
        if p:
            items.append("<member>" + _el("PolicyName", p["policy_name"]) + _el("PolicyArn", arn) + "</member>")
    return _envelope("ListAttachedRolePolicies", f"<AttachedPolicies>{''.join(items)}</AttachedPolicies>")


def _detach_role_policy(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    arn = str(params.get("PolicyArn", "")).strip()
    if arn in r["attached_policies"]:
        r["attached_policies"].remove(arn)
        p = store.get_policy(arn)
        if p:
            p["attachment_count"] = max(0, p.get("attachment_count", 1) - 1)
    store.persist()
    return _envelope("DetachRolePolicy")


def _put_role_policy(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    pname = str(params.get("PolicyName", "")).strip()
    if not pname:
        raise IamError("ValidationError", "PolicyName is required.", 400)
    r["inline_policies"][pname] = _json_param(params, "PolicyDocument")
    store.persist()
    return _envelope("PutRolePolicy")


def _get_role_policy(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    pname = str(params.get("PolicyName", "")).strip()
    doc = r["inline_policies"].get(pname)
    if doc is None:
        raise IamError("NoSuchEntity", f"Inline policy {pname} not found.", 404)
    inner = _el("RoleName", r["role_name"]) + _el("PolicyName", pname) + \
        f"<PolicyDocument>{_xml_escape(json.dumps(doc))}</PolicyDocument>"
    return _envelope("GetRolePolicy", inner)


def _list_role_policies(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    inner = "<PolicyNames>" + "".join(_el("member", n) for n in r["inline_policies"]) + "</PolicyNames>"
    return _envelope("ListRolePolicies", inner)


def _delete_role_policy(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    r["inline_policies"].pop(str(params.get("PolicyName", "")).strip(), None)
    store.persist()
    return _envelope("DeleteRolePolicy")


def _tag_role(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    r["tags"].update(_parse_tags(params))
    store.persist()
    return _envelope("TagRole")


def _untag_role(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    for k in _members(params, "TagKeys"):
        r["tags"].pop(k, None)
    store.persist()
    return _envelope("UntagRole")


def _list_role_tags(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    return _envelope("ListRoleTags", _tags_xml(r["tags"]))


def _put_role_permissions_boundary(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    arn = str(params.get("PermissionsBoundary", "")).strip()
    _require_policy(store, arn)
    r["permissions_boundary"] = arn
    store.persist()
    return _envelope("PutRolePermissionsBoundary")


def _delete_role_permissions_boundary(store, params):
    r = _require_role(store, str(params.get("RoleName", "")).strip())
    r["permissions_boundary"] = None
    store.persist()
    return _envelope("DeleteRolePermissionsBoundary")


# ── managed-policy versions + entities attached ─────────────────────────────
def _create_policy_version(store, params):
    p = _require_policy(store, str(params.get("PolicyArn", "")).strip())
    doc = _json_param(params, "PolicyDocument")
    n = max((int(v[1:]) for v in p["versions"]), default=0) + 1
    vid = f"v{n}"
    now = _now()
    p["versions"][vid] = {"document": doc, "created": now}
    set_default = str(params.get("SetAsDefault", "false")).lower() == "true"
    if set_default:
        p["default_version_id"] = vid
        p["document"] = doc
        p["updated"] = now
    store.persist()
    inner = ("<PolicyVersion>" + _el("VersionId", vid)
             + _el("IsDefaultVersion", str(set_default).lower()) + _el("CreateDate", now)
             + f"<Document>{_xml_escape(json.dumps(doc))}</Document>" + "</PolicyVersion>")
    return _envelope("CreatePolicyVersion", inner)


def _list_policy_versions(store, params):
    p = _require_policy(store, str(params.get("PolicyArn", "")).strip())
    items = []
    for vid in sorted(p["versions"], key=lambda v: int(v[1:])):
        v = p["versions"][vid]
        items.append("<member>" + _el("VersionId", vid)
                     + _el("IsDefaultVersion", str(vid == p["default_version_id"]).lower())
                     + _el("CreateDate", v["created"]) + "</member>")
    return _envelope("ListPolicyVersions", f"<Versions>{''.join(items)}</Versions>")


def _get_policy_version(store, params):
    p = _require_policy(store, str(params.get("PolicyArn", "")).strip())
    vid = str(params.get("VersionId", "")).strip()
    v = p["versions"].get(vid)
    if not v:
        raise IamError("NoSuchEntity", f"Policy version {vid} not found.", 404)
    inner = ("<PolicyVersion>" + _el("VersionId", vid)
             + _el("IsDefaultVersion", str(vid == p["default_version_id"]).lower())
             + _el("CreateDate", v["created"])
             + f"<Document>{_xml_escape(json.dumps(v['document']))}</Document>" + "</PolicyVersion>")
    return _envelope("GetPolicyVersion", inner)


def _set_default_policy_version(store, params):
    p = _require_policy(store, str(params.get("PolicyArn", "")).strip())
    vid = str(params.get("VersionId", "")).strip()
    v = p["versions"].get(vid)
    if not v:
        raise IamError("NoSuchEntity", f"Policy version {vid} not found.", 404)
    p["default_version_id"] = vid
    p["document"] = v["document"]
    p["updated"] = _now()
    store.persist()
    return _envelope("SetDefaultPolicyVersion")


def _delete_policy_version(store, params):
    p = _require_policy(store, str(params.get("PolicyArn", "")).strip())
    vid = str(params.get("VersionId", "")).strip()
    if vid == p["default_version_id"]:
        raise IamError("DeleteConflict", "Cannot delete the default policy version.", 409)
    if vid not in p["versions"]:
        raise IamError("NoSuchEntity", f"Policy version {vid} not found.", 404)
    del p["versions"][vid]
    store.persist()
    return _envelope("DeletePolicyVersion")


def _list_entities_for_policy(store, params):
    arn = str(params.get("PolicyArn", "")).strip()
    _require_policy(store, arn)
    users = [("<member>" + _el("UserName", u["user_name"]) + "</member>")
             for u in store.users.values() if arn in u["attached_policies"]]
    groups = [("<member>" + _el("GroupName", g["group_name"]) + "</member>")
              for g in store.groups.values() if arn in g["attached_policies"]]
    roles = [("<member>" + _el("RoleName", r["role_name"]) + "</member>")
             for r in store.roles.values() if arn in r["attached_policies"]]
    boundary_users = [("<member>" + _el("UserName", u["user_name"]) + "</member>")
                      for u in store.users.values() if u.get("permissions_boundary") == arn]
    boundary_roles = [("<member>" + _el("RoleName", r["role_name"]) + "</member>")
                      for r in store.roles.values() if r.get("permissions_boundary") == arn]
    inner = (f"<PolicyUsers>{''.join(users)}</PolicyUsers>" + f"<PolicyGroups>{''.join(groups)}</PolicyGroups>"
             + f"<PolicyRoles>{''.join(roles)}</PolicyRoles>"
             + f"<PolicyBoundaryUsers>{''.join(boundary_users)}</PolicyBoundaryUsers>"
             + f"<PolicyBoundaryRoles>{''.join(boundary_roles)}</PolicyBoundaryRoles>")
    return _envelope("ListEntitiesForPolicy", inner)


# ── identity providers (SAML / OIDC) ────────────────────────────────────────
def _create_saml_provider(store, params):
    name = str(params.get("Name", "")).strip()
    if not name:
        raise IamError("ValidationError", "Name is required.", 400)
    arn = f"arn:aws:iam::{store.account_id}:saml-provider/{name}"
    if arn in store.saml_providers:
        raise IamError("EntityAlreadyExists", f"SAML provider {name} already exists.", 409)
    p = {"name": name, "arn": arn, "created": _now(),
         "metadata_document": params.get("SAMLMetadataDocument", "")}
    store.saml_providers[arn] = p
    store.persist()
    return _envelope("CreateSAMLProvider", _el("SAMLProviderArn", arn))


def _get_saml_provider(store, params):
    arn = str(params.get("SAMLProviderArn", "")).strip()
    p = store.saml_providers.get(arn)
    if not p:
        raise IamError("NoSuchEntity", f"SAML provider {arn} not found.", 404)
    inner = _el("CreateDate", p["created"]) + f"<SAMLMetadataDocument>{_xml_escape(p['metadata_document'])}</SAMLMetadataDocument>"
    return _envelope("GetSAMLProvider", inner)


def _list_saml_providers(store, params):
    items = ["<member>" + _el("Arn", arn) + _el("CreateDate", p["created"]) + "</member>"
             for arn, p in sorted(store.saml_providers.items())]
    return _envelope("ListSAMLProviders", f"<SAMLProviderList>{''.join(items)}</SAMLProviderList>")


def _delete_saml_provider(store, params):
    arn = str(params.get("SAMLProviderArn", "")).strip()
    if arn not in store.saml_providers:
        raise IamError("NoSuchEntity", f"SAML provider {arn} not found.", 404)
    del store.saml_providers[arn]
    store.persist()
    return _envelope("DeleteSAMLProvider")


def _create_open_id_connect_provider(store, params):
    url = str(params.get("Url", "")).strip()
    if not url:
        raise IamError("ValidationError", "Url is required.", 400)
    host = url.split("//")[-1]
    arn = f"arn:aws:iam::{store.account_id}:oidc-provider/{host}"
    if arn in store.oidc_providers:
        raise IamError("EntityAlreadyExists", f"OIDC provider {host} already exists.", 409)
    store.oidc_providers[arn] = {"url": url, "arn": arn, "created": _now(),
                                "client_ids": _members(params, "ClientIDList"),
                                "thumbprints": _members(params, "ThumbprintList")}
    store.persist()
    return _envelope("CreateOpenIDConnectProvider", _el("OpenIDConnectProviderArn", arn))


def _get_open_id_connect_provider(store, params):
    arn = str(params.get("OpenIDConnectProviderArn", "")).strip()
    p = store.oidc_providers.get(arn)
    if not p:
        raise IamError("NoSuchEntity", f"OIDC provider {arn} not found.", 404)
    inner = (_el("Url", p["url"]) + _el("CreateDate", p["created"])
             + "<ClientIDList>" + "".join(_el("member", c) for c in p["client_ids"]) + "</ClientIDList>"
             + "<ThumbprintList>" + "".join(_el("member", t) for t in p["thumbprints"]) + "</ThumbprintList>")
    return _envelope("GetOpenIDConnectProvider", inner)


def _list_open_id_connect_providers(store, params):
    items = ["<member>" + _el("Arn", arn) + "</member>" for arn in sorted(store.oidc_providers)]
    return _envelope("ListOpenIDConnectProviders", f"<OpenIDConnectProviderList>{''.join(items)}</OpenIDConnectProviderList>")


def _delete_open_id_connect_provider(store, params):
    arn = str(params.get("OpenIDConnectProviderArn", "")).strip()
    if arn not in store.oidc_providers:
        raise IamError("NoSuchEntity", f"OIDC provider {arn} not found.", 404)
    del store.oidc_providers[arn]
    store.persist()
    return _envelope("DeleteOpenIDConnectProvider")


# ── account settings ─────────────────────────────────────────────────────────
_PASSWORD_POLICY_DEFAULTS = {"MinimumPasswordLength": 8, "RequireSymbols": False, "RequireNumbers": False,
                             "RequireUppercaseCharacters": False, "RequireLowercaseCharacters": False,
                             "AllowUsersToChangePassword": False, "ExpirePasswords": False,
                             "MaxPasswordAge": 0, "PasswordReusePrevention": 0, "HardExpiry": False}


def _get_account_password_policy(store, params):
    pol = store.password_policy or _PASSWORD_POLICY_DEFAULTS
    inner = "".join(_el(k, str(v).lower() if isinstance(v, bool) else v) for k, v in pol.items() if v not in (0, False) or k == "MinimumPasswordLength")
    return _envelope("GetAccountPasswordPolicy", f"<PasswordPolicy>{inner}</PasswordPolicy>")


def _update_account_password_policy(store, params):
    pol = dict(_PASSWORD_POLICY_DEFAULTS)
    for k in pol:
        if k in params:
            v = params[k]
            pol[k] = str(v).lower() == "true" if isinstance(pol[k], bool) else int(v)
    store.password_policy = pol
    store.persist()
    return _envelope("UpdateAccountPasswordPolicy")


def _delete_account_password_policy(store, params):
    store.password_policy = None
    store.persist()
    return _envelope("DeleteAccountPasswordPolicy")


def _list_account_aliases(store, params):
    inner = "<AccountAliases>" + "".join(_el("member", a) for a in store.account_aliases) + "</AccountAliases>"
    return _envelope("ListAccountAliases", inner)


def _create_account_alias(store, params):
    alias = str(params.get("AccountAlias", "")).strip()
    if not alias:
        raise IamError("ValidationError", "AccountAlias is required.", 400)
    store.account_aliases = [alias]
    store.persist()
    return _envelope("CreateAccountAlias")


def _delete_account_alias(store, params):
    alias = str(params.get("AccountAlias", "")).strip()
    store.account_aliases = [a for a in store.account_aliases if a != alias]
    store.persist()
    return _envelope("DeleteAccountAlias")


# ── credential report — generated synchronously (no background job) ────────
def _credential_report_csv(store) -> str:
    header = ("user,arn,user_creation_time,password_enabled,password_last_used,mfa_active,"
              "access_key_1_active,access_key_1_last_rotated,access_key_2_active,access_key_2_last_rotated\n")
    rows = []
    for name in sorted(store.users):
        u = store.users[name]
        keys = [k for k in store.access_keys.values() if k["user_name"] == name]
        k1 = keys[0] if len(keys) > 0 else None
        k2 = keys[1] if len(keys) > 1 else None
        rows.append(",".join([
            name, u["arn"], u["created"],
            "true" if u.get("login_profile") else "false", "N/A", "false",
            "true" if k1 and k1["status"] == "Active" else "false", k1["created"] if k1 else "N/A",
            "true" if k2 and k2["status"] == "Active" else "false", k2["created"] if k2 else "N/A",
        ]))
    root = store.account_id
    rows.insert(0, f"<root_account>,arn:aws:iam::{root}:root,N/A,not_supported,N/A,false,false,N/A,false,N/A")
    return header + "\n".join(rows) + "\n"


def _generate_credential_report(store, params):
    store.credential_report = {"generated": _now(), "content": _credential_report_csv(store)}
    store.persist()
    return _envelope("GenerateCredentialReport", _el("State", "COMPLETE") + _el("Description", "Report generated."))


def _get_credential_report(store, params):
    if not store.credential_report:
        raise IamError("ReportNotPresent", "Call GenerateCredentialReport first.", 410)
    content = base64.b64encode(store.credential_report["content"].encode()).decode()
    inner = f"<Content>{content}</Content>" + _el("ReportFormat", "text/csv") + _el("GeneratedTime", store.credential_report["generated"])
    return _envelope("GetCredentialReport", inner)


# ── policy evaluation (the decision path) ─────────────────────────────────────
def _resolve_policy_docs(store, principal: str) -> tuple[dict, list[dict]]:
    """Resolve a principal (name or ARN) to its identity context + effective policy
    documents (attached managed + inline + group-attached)."""
    ref = (principal or "").strip()
    name = ref.split("/")[-1] if ":" in ref else ref
    docs: list[dict] = []
    u = store.get_user(name)
    if u:
        for arn in u["attached_policies"]:
            p = store.get_policy(arn)
            if p:
                docs.append(p["document"])
        docs.extend(u["inline_policies"].values())
        for gname in u["groups"]:
            g = store.get_group(gname)
            if g:
                for arn in g["attached_policies"]:
                    p = store.get_policy(arn)
                    if p:
                        docs.append(p["document"])
                docs.extend(g.get("inline_policies", {}).values())
        return ({"arn": u["arn"], "type": "user", "name": u["user_name"]}, docs)
    r = store.get_role(name)
    if r:
        for arn in r["attached_policies"]:
            p = store.get_policy(arn)
            if p:
                docs.append(p["document"])
        docs.extend(r["inline_policies"].values())
        return ({"arn": r["arn"], "type": "role", "name": r["role_name"]}, docs)
    return ({"arn": ref, "type": "unknown", "name": name}, [])


def _simulate_principal_policy(store, params):
    source = str(params.get("PolicySourceArn", "")).strip()
    if not source:
        raise IamError("ValidationError", "PolicySourceArn is required.", 400)
    actions = _members(params, "ActionNames")
    resources = _members(params, "ResourceArns") or ["*"]
    identity, docs = _resolve_policy_docs(store, source)
    ctx = {"aws:PrincipalArn": identity["arn"], "aws:PrincipalType": identity["type"],
           "aws:username": identity["name"], "aws:RequestedRegion": "us-east-1"}
    results = []
    for action in actions:
        for resource in resources:
            ctx_r = dict(ctx, **{"aws:ResourceArn": resource})
            decision, _ = store.engine.evaluate(docs, action, resource, ctx_r)
            results.append("<member>" + _el("EvalActionName", action)
                           + _el("EvalResourceName", resource)
                           + _el("EvalDecision", decision) + "</member>")
    return _envelope("SimulatePrincipalPolicy", f"<EvaluationResults>{''.join(results)}</EvaluationResults>")


# ── native-wire dispatcher (Query-protocol Action → operation) ─────────────
_OPS = {
    "CreateUser": _create_user, "GetUser": _get_user, "ListUsers": _list_users, "DeleteUser": _delete_user,
    "UpdateUser": _update_user, "TagUser": _tag_user, "UntagUser": _untag_user, "ListUserTags": _list_user_tags,
    "ListUserPolicies": _list_user_policies, "DeleteUserPolicy": _delete_user_policy,
    "PutUserPermissionsBoundary": _put_user_permissions_boundary,
    "DeleteUserPermissionsBoundary": _delete_user_permissions_boundary,
    "CreateLoginProfile": _create_login_profile, "GetLoginProfile": _get_login_profile,
    "UpdateLoginProfile": _update_login_profile, "DeleteLoginProfile": _delete_login_profile,
    "CreateRole": _create_role, "GetRole": _get_role, "ListRoles": _list_roles, "DeleteRole": _delete_role,
    "UpdateRole": _update_role, "UpdateAssumeRolePolicy": _update_assume_role_policy,
    "ListAttachedRolePolicies": _list_attached_role_policies, "DetachRolePolicy": _detach_role_policy,
    "PutRolePolicy": _put_role_policy, "GetRolePolicy": _get_role_policy,
    "ListRolePolicies": _list_role_policies, "DeleteRolePolicy": _delete_role_policy,
    "TagRole": _tag_role, "UntagRole": _untag_role, "ListRoleTags": _list_role_tags,
    "PutRolePermissionsBoundary": _put_role_permissions_boundary,
    "DeleteRolePermissionsBoundary": _delete_role_permissions_boundary,
    "CreatePolicy": _create_policy, "GetPolicy": _get_policy, "ListPolicies": _list_policies, "DeletePolicy": _delete_policy,
    "CreatePolicyVersion": _create_policy_version, "ListPolicyVersions": _list_policy_versions,
    "GetPolicyVersion": _get_policy_version, "SetDefaultPolicyVersion": _set_default_policy_version,
    "DeletePolicyVersion": _delete_policy_version, "ListEntitiesForPolicy": _list_entities_for_policy,
    "AttachUserPolicy": _attach_user_policy, "DetachUserPolicy": _detach_user_policy,
    "ListAttachedUserPolicies": _list_attached_user_policies, "AttachRolePolicy": _attach_role_policy,
    "PutUserPolicy": _put_user_policy, "GetUserPolicy": _get_user_policy,
    "CreateGroup": _create_group, "ListGroups": _list_groups, "GetGroup": _get_group, "DeleteGroup": _delete_group,
    "AddUserToGroup": _add_user_to_group, "RemoveUserFromGroup": _remove_user_from_group,
    "ListGroupsForUser": _list_groups_for_user,
    "AttachGroupPolicy": _attach_group_policy, "DetachGroupPolicy": _detach_group_policy,
    "ListAttachedGroupPolicies": _list_attached_group_policies,
    "PutGroupPolicy": _put_group_policy, "GetGroupPolicy": _get_group_policy,
    "ListGroupPolicies": _list_group_policies, "DeleteGroupPolicy": _delete_group_policy,
    "CreateAccessKey": _create_access_key, "ListAccessKeys": _list_access_keys,
    "UpdateAccessKey": _update_access_key, "DeleteAccessKey": _delete_access_key,
    "CreateSAMLProvider": _create_saml_provider, "GetSAMLProvider": _get_saml_provider,
    "ListSAMLProviders": _list_saml_providers, "DeleteSAMLProvider": _delete_saml_provider,
    "CreateOpenIDConnectProvider": _create_open_id_connect_provider,
    "GetOpenIDConnectProvider": _get_open_id_connect_provider,
    "ListOpenIDConnectProviders": _list_open_id_connect_providers,
    "DeleteOpenIDConnectProvider": _delete_open_id_connect_provider,
    "GetAccountPasswordPolicy": _get_account_password_policy,
    "UpdateAccountPasswordPolicy": _update_account_password_policy,
    "DeleteAccountPasswordPolicy": _delete_account_password_policy,
    "ListAccountAliases": _list_account_aliases, "CreateAccountAlias": _create_account_alias,
    "DeleteAccountAlias": _delete_account_alias,
    "GenerateCredentialReport": _generate_credential_report, "GetCredentialReport": _get_credential_report,
    "SimulatePrincipalPolicy": _simulate_principal_policy,
}


def dispatch(store: IamStore, params: dict | None = None) -> IamResponse:
    """The single routing point for the native AWS IAM Query protocol — what an
    unmodified aws-cli / boto3 IAM client speaks. `params` is the parsed
    form-encoded body ({"Action": "CreateUser", "UserName": ...})."""
    params = params if isinstance(params, dict) else {}
    action = str(params.get("Action", "")).strip()
    if not action:
        return _error("MissingAction", "The request must include an Action.", 400)
    op = _OPS.get(action)
    if op is None:
        return _error("InvalidAction", f"The action {action} is not implemented.", 400)
    try:
        return op(store, params)
    except IamError as e:
        return _error(e.code, e.message, e.status)


# ── decision helper (not a native action — for in-tab enforcement / console) ──
def is_authorized(store: IamStore, principal: str, action: str, resource: str,
                  context: dict | None = None) -> dict:
    """Convenience authorization probe used by in-tab enforcement / the console —
    the analogue of server.py's _iam_authorize. Returns {allowed, decision, reason}."""
    identity, docs = _resolve_policy_docs(store, principal)
    ctx = {"aws:PrincipalArn": identity["arn"], "aws:PrincipalType": identity["type"],
           "aws:username": identity["name"], "aws:RequestedRegion": "us-east-1",
           "aws:ResourceArn": resource}
    if context:
        ctx.update({k: str(v) for k, v in context.items()})
    decision, reason = store.engine.evaluate(docs, action, resource, ctx)
    return {"allowed": decision == "allowed", "decision": decision, "reason": reason}
