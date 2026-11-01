# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
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
(Create/List), virtual MFA devices (Create/Enable/Deactivate/Delete/List), and
SimulatePrincipalPolicy — which factors a user's real MFA-device state into the
`aws:MultiFactorAuthPresent` condition key. SAML / instance profiles / policy
versions reuse the same helpers and slot in next.
"""
from __future__ import annotations

import base64
import hashlib
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
def _mfa_arn(store, name): return f"arn:aws:iam::{store.account_id}:mfa/{name}"


def _has_mfa(store, user_name: str) -> bool:
    """True if `user_name` has an ENABLED virtual MFA device — the real signal behind
    the `aws:MultiFactorAuthPresent` condition key (see _simulate_principal_policy /
    is_authorized). There is no console sign-in flow to actually challenge for the
    code, so this reflects device assignment, not an authenticated session."""
    return any(d.get("user_name") == user_name for d in store.virtual_mfa_devices.values())


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


def _context_entries(params: dict) -> list[dict]:
    """SimulatePrincipalPolicy's ContextEntries.member.N.{ContextKeyName,ContextKeyValues} —
    the real AWS mechanism for supplying per-request condition keys (aws:MultiFactorAuthPresent,
    aws:SourceIp, …) that the simulator has no live request to read them from. Only the first
    value of a multi-valued entry is honored (the evaluator's context is single-valued)."""
    out, i = [], 1
    while True:
        key = params.get(f"ContextEntries.member.{i}.ContextKeyName")
        if key is None:
            break
        values = _members(params, f"ContextEntries.member.{i}.ContextKeyValues")
        out.append({"key": key, "value": values[0] if values else ""})
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


# ── multi-factor authentication (virtual MFA devices) — limited: assignment is real,
# there is no console sign-in flow to challenge the code against (see console-password) ──
def _check_mfa_codes(code1, code2):
    c1, c2 = str(code1 or "").strip(), str(code2 or "").strip()
    if not (len(c1) == 6 and c1.isdigit()) or not (len(c2) == 6 and c2.isdigit()):
        raise IamError("InvalidAuthenticationCode", "Authentication codes must be two consecutive 6-digit codes.", 403)
    if c1 == c2:
        raise IamError("InvalidAuthenticationCode", "The two authentication codes must be different (consecutive codes).", 403)


def _virtual_mfa_device_xml(d: dict, with_seed: bool = False) -> str:
    inner = _el("SerialNumber", d["serial_number"])
    if with_seed:
        inner += _el("Base32StringSeed", d["base32_seed"]) + "<QRCodePNG></QRCodePNG>"
    if d.get("user_name"):
        inner += "<User>" + _el("UserName", d["user_name"]) + "</User>" + _el("EnableDate", d["enable_date"])
    return f"<VirtualMFADevice>{inner}</VirtualMFADevice>"


def _create_virtual_mfa_device(store, params):
    name = str(params.get("VirtualMFADeviceName", "")).strip()
    if not name:
        raise IamError("ValidationError", "VirtualMFADeviceName is required.", 400)
    arn = _mfa_arn(store, name)
    if arn in store.virtual_mfa_devices:
        raise IamError("EntityAlreadyExists", f"MFA device {name} already exists.", 409)
    seed = base64.b32encode((uuid.uuid4().hex + uuid.uuid4().hex).encode())[:32].decode()
    d = {"serial_number": arn, "device_name": name, "path": params.get("Path", "/"),
         "base32_seed": seed, "created": _now(), "user_name": None, "enable_date": None}
    store.virtual_mfa_devices[arn] = d
    store.persist()
    return _envelope("CreateVirtualMFADevice", _virtual_mfa_device_xml(d, with_seed=True))


def _require_virtual_mfa_device(store, serial):
    d = store.virtual_mfa_devices.get(str(serial or "").strip())
    if not d:
        raise IamError("NoSuchEntity", f"MFA device {serial} not found.", 404)
    return d


def _delete_virtual_mfa_device(store, params):
    d = _require_virtual_mfa_device(store, params.get("SerialNumber"))
    if d.get("user_name"):
        raise IamError("DeleteConflict", "Cannot delete an MFA device that is still assigned to a user.", 409)
    del store.virtual_mfa_devices[d["serial_number"]]
    store.persist()
    return _envelope("DeleteVirtualMFADevice")


def _enable_mfa_device(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    d = _require_virtual_mfa_device(store, params.get("SerialNumber"))
    if d.get("user_name"):
        raise IamError("EntityAlreadyExists", "MFA device is already assigned to a user.", 409)
    _check_mfa_codes(params.get("AuthenticationCode1"), params.get("AuthenticationCode2"))
    d["user_name"] = u["user_name"]
    d["enable_date"] = _now()
    store.persist()
    return _envelope("EnableMFADevice")


def _deactivate_mfa_device(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    d = _require_virtual_mfa_device(store, params.get("SerialNumber"))
    if d.get("user_name") != u["user_name"]:
        raise IamError("NoSuchEntity", "MFA device is not assigned to this user.", 404)
    d["user_name"] = None
    d["enable_date"] = None
    store.persist()
    return _envelope("DeactivateMFADevice")


def _resync_mfa_device(store, params):
    u = _require_user(store, str(params.get("UserName", "")).strip())
    d = _require_virtual_mfa_device(store, params.get("SerialNumber"))
    if d.get("user_name") != u["user_name"]:
        raise IamError("NoSuchEntity", "MFA device is not assigned to this user.", 404)
    _check_mfa_codes(params.get("AuthenticationCode1"), params.get("AuthenticationCode2"))
    return _envelope("ResyncMFADevice")


def _list_mfa_devices(store, params):
    name = str(params.get("UserName", "")).strip()
    _require_user(store, name)
    items = [("<member>" + _el("UserName", name) + _el("SerialNumber", d["serial_number"])
              + _el("EnableDate", d["enable_date"]) + "</member>")
             for d in store.virtual_mfa_devices.values() if d.get("user_name") == name]
    return _envelope("ListMFADevices", f"<MFADevices>{''.join(items)}</MFADevices>")


def _list_virtual_mfa_devices(store, params):
    status = str(params.get("AssignmentStatus", "Any")).strip() or "Any"
    devices = list(store.virtual_mfa_devices.values())
    if status == "Assigned":
        devices = [d for d in devices if d.get("user_name")]
    elif status == "Unassigned":
        devices = [d for d in devices if not d.get("user_name")]
    items = "".join(_virtual_mfa_device_xml(d) for d in sorted(devices, key=lambda d: d["created"]))
    return _envelope("ListVirtualMFADevices", f"<VirtualMFADevices>{items}</VirtualMFADevices>")


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
def _resolve_policy_docs(store, principal: str) -> tuple[dict, list[dict], dict | None]:
    """Resolve a principal (name or ARN) to its identity context, its effective policy
    documents (attached managed + inline + group-attached), and its permissions-boundary
    document (None if it has none, or the boundary policy no longer exists)."""
    ref = (principal or "").strip()
    name = ref.split("/")[-1] if ":" in ref else ref
    docs: list[dict] = []

    def boundary_doc(rec: dict) -> dict | None:
        arn = rec.get("permissions_boundary")
        p = store.get_policy(arn) if arn else None
        return p["document"] if p else None

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
        return ({"arn": u["arn"], "type": "user", "name": u["user_name"]}, docs, boundary_doc(u))
    r = store.get_role(name)
    if r:
        for arn in r["attached_policies"]:
            p = store.get_policy(arn)
            if p:
                docs.append(p["document"])
        docs.extend(r["inline_policies"].values())
        return ({"arn": r["arn"], "type": "role", "name": r["role_name"]}, docs, boundary_doc(r))
    return ({"arn": ref, "type": "unknown", "name": name}, [], None)


def _apply_boundary(store, boundary_doc: dict | None, decision: str, action: str, resource: str, ctx: dict) -> str:
    """A permissions boundary clips what the identity policies allow: the effective
    permission is the INTERSECTION of the identity decision and the boundary decision
    (real AWS semantics) — an explicit deny from either side wins; otherwise both sides
    must allow. Boundaries never WIDEN access, so a non-"allowed" identity decision is
    returned unchanged."""
    if boundary_doc is None or decision != "allowed":
        return decision
    b_decision, _ = store.engine.evaluate([boundary_doc], action, resource, ctx)
    return b_decision if b_decision != "allowed" else "allowed"


def _simulate_principal_policy(store, params):
    source = str(params.get("PolicySourceArn", "")).strip()
    if not source:
        raise IamError("ValidationError", "PolicySourceArn is required.", 400)
    actions = _members(params, "ActionNames")
    resources = _members(params, "ResourceArns") or ["*"]
    identity, docs, boundary = _resolve_policy_docs(store, source)
    mfa_present = identity["type"] == "user" and _has_mfa(store, identity["name"])
    ctx = {"aws:PrincipalArn": identity["arn"], "aws:PrincipalType": identity["type"],
           "aws:username": identity["name"], "aws:RequestedRegion": "us-east-1",
           "aws:MultiFactorAuthPresent": str(mfa_present).lower()}
    for entry in _context_entries(params):
        ctx[entry["key"]] = entry["value"]
    results = []
    for action in actions:
        for resource in resources:
            ctx_r = dict(ctx, **{"aws:ResourceArn": resource})
            decision, _ = store.engine.evaluate(docs, action, resource, ctx_r)
            decision = _apply_boundary(store, boundary, decision, action, resource, ctx_r)
            results.append("<member>" + _el("EvalActionName", action)
                           + _el("EvalResourceName", resource)
                           + _el("EvalDecision", decision) + "</member>")
    return _envelope("SimulatePrincipalPolicy", f"<EvaluationResults>{''.join(results)}</EvaluationResults>")


# ── Organizations policies (SCP/RCP) — Vyomi-only ───────────────────────────
# Real AWS exposes service/resource control policies through a SEPARATE
# "organizations" service (JSON protocol, target AWSOrganizationsV20161128.*).
# The IAM console surfaces them under its own nav ("Multi-account access") for
# convenience, so Vyomi models them here, on IAM's native Query wire, to back
# that console without a second service stack — Vyomi simulates a single
# account, so attachment/enforcement across member accounts is not modeled
# (see core/capabilities/aws/iam.json: iam.organizations = "limited").
_ORG_POLICY_TYPES = {"SERVICE_CONTROL_POLICY", "RESOURCE_CONTROL_POLICY"}


def _org_policy_xml(p: dict) -> str:
    return ("<Policy>" + _el("Id", p["id"]) + _el("Arn", p["arn"]) + _el("Name", p["name"])
            + _el("Description", p.get("description", "")) + _el("Type", p["type"])
            + _el("AwsManaged", "false") + _el("CreatedTimestamp", p["created"])
            + f"<Content>{_xml_escape(p['content'])}</Content>" + "</Policy>")


def _create_org_policy(store, params):
    name = str(params.get("Name", "")).strip()
    ptype = str(params.get("Type", "")).strip().upper()
    if not name:
        raise IamError("ValidationError", "Name is required.", 400)
    if ptype not in _ORG_POLICY_TYPES:
        raise IamError("ValidationError", f"Type must be one of {sorted(_ORG_POLICY_TYPES)}.", 400)
    content = str(params.get("Content", "") or "{}")
    try:
        json.loads(content)
    except Exception:
        raise IamError("MalformedPolicyDocument", "Content is not valid JSON.", 400)
    pid = "p-" + uuid.uuid4().hex[:8]
    p = {"id": pid, "arn": f"arn:aws:organizations::{store.account_id}:policy/o-vyomi/{ptype.lower()}/{pid}",
         "name": name, "description": params.get("Description", ""), "type": ptype,
         "content": content, "created": _now()}
    store.org_policies[pid] = p
    store.persist()
    return _envelope("CreateOrgPolicy", _org_policy_xml(p))


def _list_org_policies(store, params):
    ptype = str(params.get("Type", "")).strip().upper()
    items = [p for p in store.org_policies.values() if not ptype or p["type"] == ptype]
    inner = "<Policies>" + "".join(_org_policy_xml(p) for p in sorted(items, key=lambda p: p["created"])) + "</Policies>"
    return _envelope("ListOrgPolicies", inner)


def _require_org_policy(store, policy_id):
    p = store.org_policies.get(policy_id)
    if not p:
        raise IamError("NoSuchEntity", f"Policy {policy_id} does not exist.", 404)
    return p


def _describe_org_policy(store, params):
    p = _require_org_policy(store, str(params.get("PolicyId", "")).strip())
    return _envelope("DescribeOrgPolicy", _org_policy_xml(p))


def _delete_org_policy(store, params):
    pid = str(params.get("PolicyId", "")).strip()
    _require_org_policy(store, pid)
    del store.org_policies[pid]
    store.persist()
    return _envelope("DeleteOrgPolicy")


# ── Account access requests ("Temporary delegation requests") — Vyomi-only ──
# Centralized root access lets a member account request temporary elevated
# access from the management account; Vyomi has no member accounts to
# originate a request, so there is no "Create" action in the console UI
# itself — this models the record a request would leave behind so the page
# has real (not static) data when one is simulated over the wire.
def _access_request_xml(r: dict) -> str:
    return ("<AccountAccessRequest>" + _el("RequestId", r["id"]) + _el("Status", r["status"])
            + _el("RequestorId", r["requestor_id"]) + _el("InitiatedBy", r["initiated_by"])
            + _el("RequestCreated", r["created"]) + _el("RequestExpires", r["expires"])
            + "</AccountAccessRequest>")


def _request_account_access(store, params):
    requestor = str(params.get("RequestorId", "")).strip() or store.account_id
    initiated_by = str(params.get("InitiatedBy", "")).strip() or requestor
    rid = "ar-" + uuid.uuid4().hex[:12]
    r = {"id": rid, "status": params.get("Status", "Pending"), "requestor_id": requestor,
         "initiated_by": initiated_by, "created": _now(), "expires": params.get("RequestExpires", _now())}
    store.access_requests[rid] = r
    store.persist()
    return _envelope("RequestAccountAccess", _access_request_xml(r))


def _list_account_access_requests(store, params):
    inner = "<AccountAccessRequests>" + "".join(
        _access_request_xml(r) for r in sorted(store.access_requests.values(), key=lambda r: r["created"])) + "</AccountAccessRequests>"
    return _envelope("ListAccountAccessRequests", inner)


# ── native-wire activity log (Vyomi-only) ───────────────────────────────────
# Recorded by core/aws_wire_router.py for every request signed with an IAM USER's own
# access key (a real aws-cli/boto3 caller configured with CreateAccessKey credentials —
# distinguishable because the AKID sits in clear in the SigV4 credential scope even
# though Vyomi never verifies the signature itself). The console's own fixed operator
# credential and the conformance harness's placeholder credentials never match a real
# access key, so they never appear here: every entry is real recorded activity, not
# fabricated. Backs GenerateServiceLastAccessedDetails, the Vyomi-only policy-from-activity
# generator ("Generate policy based on CloudTrail events"), and Access Analyzer's
# unused-access findings below. Roles have no long-term access keys in real AWS either
# (they get temporary AssumeRole credentials, which Vyomi does not mint), so role activity
# is always empty here — a real, honest limitation, not a bug.
_ACTIVITY_CAP = 5000


def record_activity(store, user_name: str, service: str, action: str | None) -> None:
    store.activity.append({"principal_arn": _user_arn(store, user_name), "service": service,
                           "action": action, "time": _now()})
    if len(store.activity) > _ACTIVITY_CAP:
        del store.activity[: len(store.activity) - _ACTIVITY_CAP]
    store.persist()


_SERVICE_NAMESPACE = {   # internal router service-key -> AWS IAM policy prefix (ServiceNamespace)
    "vpc": "ec2", "elbv2": "elasticloadbalancing", "stepfunctions": "states",
}
_SERVICE_NAME = {   # ServiceNamespace -> the display name real AWS's Last Accessed table shows
    "s3": "Amazon S3", "dynamodb": "Amazon DynamoDB", "kms": "AWS Key Management Service",
    "secretsmanager": "AWS Secrets Manager", "sqs": "Amazon Simple Queue Service (SQS)",
    "sns": "Amazon Simple Notification Service (SNS)", "iam": "AWS Identity and Access Management (IAM)",
    "rds": "Amazon Relational Database Service", "ec2": "Amazon EC2", "lambda": "AWS Lambda",
    "cloudwatch": "Amazon CloudWatch", "logs": "Amazon CloudWatch Logs", "events": "Amazon EventBridge",
    "kinesis": "Amazon Kinesis", "ssm": "AWS Systems Manager", "states": "AWS Step Functions",
    "cloudformation": "AWS CloudFormation", "apigateway": "Amazon API Gateway",
    "elasticloadbalancing": "Elastic Load Balancing", "scheduler": "Amazon EventBridge Scheduler",
}


def _namespace(service: str) -> str:
    return _SERVICE_NAMESPACE.get(service, service)


def _principal_names_for_last_accessed(store, arn: str) -> list[str]:
    """Resolve an Arn argument to the IAM USER names whose activity to aggregate — the
    only principal kind Vyomi can attribute activity to (see record_activity). A group
    or policy Arn aggregates its member/attached users; a role Arn always yields none."""
    if ":user/" in arn:
        name = arn.split(":user/", 1)[1]
        return [name] if store.get_user(name) else []
    if ":group/" in arn:
        g = store.get_group(arn.split(":group/", 1)[1])
        return list(g["members"]) if g else []
    if ":policy/" in arn:
        if not store.get_policy(arn):
            return []
        names = [u["user_name"] for u in store.users.values() if arn in u["attached_policies"]]
        for g in store.groups.values():
            if arn in g["attached_policies"]:
                names.extend(g["members"])
        return sorted(set(names))
    return []


def _service_last_accessed_report(store, names: list[str]) -> list[dict]:
    per_service: dict[str, dict] = {}
    for entry in store.activity:
        principal_name = entry["principal_arn"].rsplit("/", 1)[-1]
        if principal_name not in names:
            continue
        ns = _namespace(entry["service"])
        rec = per_service.setdefault(ns, {"last": entry["time"], "entities": set()})
        if entry["time"] > rec["last"]:
            rec["last"] = entry["time"]
        rec["entities"].add(entry["principal_arn"])
    return [{"ServiceNamespace": ns, "ServiceName": _SERVICE_NAME.get(ns, ns), "LastAuthenticated": rec["last"],
             "LastAuthenticatedEntity": sorted(rec["entities"])[0], "TotalAuthenticatedEntities": len(rec["entities"])}
            for ns, rec in sorted(per_service.items())]


def _decode_last_accessed_job(job_id: str):
    if not job_id.startswith("vyomi-"):
        raise IamError("NoSuchEntity", f"Job {job_id} not found.", 404)
    rest = job_id[6:]
    padded = rest + "=" * (-len(rest) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode()
    except Exception:
        raise IamError("NoSuchEntity", f"Job {job_id} not found.", 404)


def _generate_service_last_accessed_details(store, params):
    arn = str(params.get("Arn", "")).strip()
    if not arn:
        raise IamError("ValidationError", "Arn is required.", 400)
    job_id = "vyomi-" + base64.urlsafe_b64encode(arn.encode()).decode().rstrip("=")
    return _envelope("GenerateServiceLastAccessedDetails", _el("JobId", job_id))


def _get_service_last_accessed_details(store, params):
    arn = _decode_last_accessed_job(str(params.get("JobId", "")).strip())
    report = _service_last_accessed_report(store, _principal_names_for_last_accessed(store, arn))
    now = _now()
    items = "".join(
        "<member>" + _el("ServiceNamespace", r["ServiceNamespace"]) + _el("ServiceName", r["ServiceName"])
        + _el("LastAuthenticated", r["LastAuthenticated"]) + _el("LastAuthenticatedEntity", r["LastAuthenticatedEntity"])
        + _el("TotalAuthenticatedEntities", r["TotalAuthenticatedEntities"]) + "</member>"
        for r in report)
    inner = (_el("JobStatus", "COMPLETED") + _el("JobCreationDate", now) + _el("JobCompletionDate", now)
             + f"<ServicesLastAccessed>{items}</ServicesLastAccessed>")
    return _envelope("GetServiceLastAccessedDetails", inner)


# ── policy generation from activity (Vyomi-only) ────────────────────────────
# Real AWS mines CloudTrail management events for "Generate policy based on CloudTrail
# events" (the IAM console routes it through Access Analyzer's StartPolicyGeneration /
# GetGeneratedPolicy). Vyomi doesn't simulate CloudTrail, so this mines the same real
# signal CloudTrail would have recorded for the principal — Vyomi's own native-wire
# activity log (see record_activity) — synchronously, in one call.
def _generate_policy_from_activity(store, params):
    arn = str(params.get("Arn", "")).strip()
    if not arn:
        raise IamError("ValidationError", "Arn is required.", 400)
    names = _principal_names_for_last_accessed(store, arn)
    pairs = set()
    for entry in store.activity:
        if entry["principal_arn"].rsplit("/", 1)[-1] not in names:
            continue
        ns = _namespace(entry["service"])
        pairs.add(f"{ns}:{entry['action']}" if entry.get("action") else f"{ns}:*")
    doc = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": sorted(pairs), "Resource": "*"}] if pairs else []}
    return _envelope("GeneratePolicyFromActivity", f"<GeneratedPolicyDocument>{_xml_escape(json.dumps(doc))}</GeneratedPolicyDocument>")


# ── IAM Access Analyzer (Vyomi-only) ─────────────────────────────────────────
# Real AWS exposes this through a separate "accessanalyzer" service; the IAM console
# surfaces it under its own nav for convenience, same as the SCP/RCP precedent above, so
# Vyomi models it on IAM's native wire. Two real, non-fabricated signals back it:
#   external access — resource-based/trust policies (IAM role trust policies, S3 bucket
#                      policies) naming a principal outside this account, or "*"
#   unused access   — IAM user access keys at least `unused_access_age` days old with NO
#                      entries in the activity log (see record_activity above)
# Vyomi simulates a single account, so cross-account "zone of trust" membership and
# organization-wide analyzers are not modeled (see iam.organizations); external-access
# analysis currently covers IAM role trust policies and S3 bucket policies — not yet KMS
# key policies, SQS/SNS resource policies or Secrets Manager resource policies.
_ANALYZER_TYPES = {"ACCOUNT", "ACCOUNT_UNUSED_ACCESS"}
_NEEDS_S3_STORE = {"ListFindings", "GetFinding"}


def _external_principals(doc: dict, account_id: str) -> list[str]:
    found = []
    for st in (doc or {}).get("Statement") or []:
        if str(st.get("Effect", "")).strip().lower() != "allow":
            continue
        principal = st.get("Principal")
        if principal == "*":
            found.append("*")
            continue
        if isinstance(principal, dict):
            aws = principal.get("AWS")
            for a in ([aws] if isinstance(aws, str) else (aws or [])):
                a = str(a)
                if a == "*" or (f":{account_id}:" not in a and a != account_id):
                    found.append(a)
    return found


def _age_days(iso: str) -> int:
    try:
        then = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=timezone.utc)
    except Exception:
        return 0
    return max(0, (datetime.now(timezone.utc) - then).days)


def _finding_id(analyzer_name: str, kind: str, resource: str) -> str:
    return hashlib.sha1(f"{analyzer_name}|{kind}|{resource}".encode()).hexdigest()[:20]


def _finding(analyzer, kind, resource_type, resource, principals, extra=None):
    fid = _finding_id(analyzer["name"], kind, resource)
    f = {"id": fid, "type": kind, "resource_type": resource_type, "resource": resource,
         "principals": principals, "status": "ARCHIVED" if fid in analyzer["archived"] else "ACTIVE",
         "created": analyzer["created"]}
    if extra:
        f.update(extra)
    return f


def _compute_findings(store, analyzer, s3_store=None) -> list[dict]:
    out = []
    if analyzer["type"] == "ACCOUNT":
        for r in store.roles.values():
            ext = _external_principals(r.get("assume_role_policy_document") or {}, store.account_id)
            if ext:
                out.append(_finding(analyzer, "ExternalAccess", "AWS::IAM::Role", r["arn"], ext))
        for bname, meta in (getattr(s3_store, "buckets", None) or {}).items():
            txt = (meta.get("cfg") or {}).get("policy")
            if not txt:
                continue
            try:
                doc = json.loads(txt)
            except Exception:
                continue
            ext = _external_principals(doc, store.account_id)
            if ext:
                out.append(_finding(analyzer, "ExternalAccess", "AWS::S3::Bucket", f"arn:aws:s3:::{bname}", ext))
    else:   # ACCOUNT_UNUSED_ACCESS
        age = int(analyzer.get("unused_access_age", 90))
        used_users = {e["principal_arn"].rsplit("/", 1)[-1] for e in store.activity}
        for k in store.access_keys.values():
            if k["user_name"] in used_users or _age_days(k["created"]) < age:
                continue
            out.append(_finding(analyzer, "UnusedIAMUserAccessKey", "AWS::IAM::AccessKey", k["access_key_id"],
                                [_user_arn(store, k["user_name"])], {"age_days": _age_days(k["created"])}))
    return out


def _analyzer_xml(a: dict) -> str:
    return ("<AnalyzerSummary>" + _el("Name", a["name"]) + _el("Arn", a["arn"]) + _el("Type", a["type"])
            + _el("Status", "ACTIVE") + _el("CreatedAt", a["created"]) + _el("UnusedAccessAge", a.get("unused_access_age", 90))
            + "</AnalyzerSummary>")


def _create_analyzer(store, params):
    name = str(params.get("AnalyzerName", "")).strip()
    if not name:
        raise IamError("ValidationError", "AnalyzerName is required.", 400)
    atype = str(params.get("Type", "")).strip().upper()
    if atype not in _ANALYZER_TYPES:
        raise IamError("ValidationError", f"Type must be one of {sorted(_ANALYZER_TYPES)}.", 400)
    if name in store.analyzers:
        raise IamError("ConflictException", f"Analyzer {name} already exists.", 409)
    a = {"name": name, "arn": f"arn:aws:access-analyzer:us-east-1:{store.account_id}:analyzer/{name}",
         "type": atype, "created": _now(), "unused_access_age": int(params.get("UnusedAccessAge") or 90), "archived": []}
    store.analyzers[name] = a
    store.persist()
    return _envelope("CreateAnalyzer", _analyzer_xml(a))


def _list_analyzers(store, params):
    inner = "<Analyzers>" + "".join(_analyzer_xml(a) for a in sorted(store.analyzers.values(), key=lambda a: a["created"])) + "</Analyzers>"
    return _envelope("ListAnalyzers", inner)


def _require_analyzer(store, name):
    a = store.analyzers.get(name)
    if not a:
        raise IamError("ResourceNotFoundException", f"Analyzer {name} not found.", 404)
    return a


def _get_analyzer(store, params):
    return _envelope("GetAnalyzer", _analyzer_xml(_require_analyzer(store, str(params.get("AnalyzerName", "")).strip())))


def _update_analyzer(store, params):
    a = _require_analyzer(store, str(params.get("AnalyzerName", "")).strip())
    if params.get("UnusedAccessAge") is not None:
        a["unused_access_age"] = int(params["UnusedAccessAge"])
    store.persist()
    return _envelope("UpdateAnalyzer", _analyzer_xml(a))


def _delete_analyzer(store, params):
    name = str(params.get("AnalyzerName", "")).strip()
    _require_analyzer(store, name)
    del store.analyzers[name]
    store.persist()
    return _envelope("DeleteAnalyzer")


def _finding_xml(f: dict) -> str:
    principals = "".join(_el("member", p) for p in f["principals"])
    extra = _el("AgeDays", f["age_days"]) if "age_days" in f else ""
    return ("<member>" + _el("Id", f["id"]) + _el("FindingType", f["type"]) + _el("ResourceType", f["resource_type"])
            + _el("Resource", f["resource"]) + _el("Status", f["status"]) + _el("CreatedAt", f["created"])
            + f"<Principals>{principals}</Principals>" + extra + "</member>")


def _list_findings(store, params, s3_store=None):
    a = _require_analyzer(store, str(params.get("AnalyzerName", "")).strip())
    status_filter = str(params.get("Status", "")).strip().upper() or None
    findings = _compute_findings(store, a, s3_store=s3_store)
    if status_filter:
        findings = [f for f in findings if f["status"] == status_filter]
    return _envelope("ListFindings", "<Findings>" + "".join(_finding_xml(f) for f in findings) + "</Findings>")


def _get_finding(store, params, s3_store=None):
    a = _require_analyzer(store, str(params.get("AnalyzerName", "")).strip())
    fid = str(params.get("Id", "")).strip()
    for f in _compute_findings(store, a, s3_store=s3_store):
        if f["id"] == fid:
            return _envelope("GetFinding", _finding_xml(f))
    raise IamError("ResourceNotFoundException", f"Finding {fid} not found.", 404)


def _update_finding_status(store, params):
    a = _require_analyzer(store, str(params.get("AnalyzerName", "")).strip())
    fid = str(params.get("Id", "")).strip()
    status = str(params.get("Status", "")).strip().upper()
    if status not in ("ACTIVE", "ARCHIVED"):
        raise IamError("ValidationError", "Status must be ACTIVE or ARCHIVED.", 400)
    if status == "ARCHIVED" and fid not in a["archived"]:
        a["archived"].append(fid)
    elif status == "ACTIVE":
        a["archived"] = [x for x in a["archived"] if x != fid]
    store.persist()
    return _envelope("UpdateFindingStatus")


# ── IAM Roles Anywhere (Vyomi-only) ──────────────────────────────────────────
# Real AWS exposes this through a separate "rolesanywhere" service (X.509-authenticated
# on-prem/non-AWS workloads exchange a certificate for short-term role credentials).
# Vyomi models the control plane (trust anchors, profiles) on IAM's native wire, same
# reason as the other Vyomi-only extensions above. The certificate is format-checked (a
# well-formed PEM block), never cryptographically verified — no different in kind from
# the virtual-MFA flow's two-code format check (see iam.user.mfa); CreateSession (minting
# actual temporary credentials from a signed challenge) is not modeled.
def _is_pem_certificate(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("-----BEGIN CERTIFICATE-----") and t.endswith("-----END CERTIFICATE-----") and len(t) > 64


def _trust_anchor_xml(t: dict) -> str:
    return ("<TrustAnchorDetail>" + _el("TrustAnchorId", t["id"]) + _el("TrustAnchorArn", t["arn"])
            + _el("Name", t["name"]) + _el("Enabled", "true") + _el("CreatedAt", t["created"]) + "</TrustAnchorDetail>")


def _create_trust_anchor(store, params):
    name = str(params.get("Name", "")).strip()
    if not name:
        raise IamError("ValidationError", "Name is required.", 400)
    cert = str(params.get("SourceData", "")).strip()
    if not _is_pem_certificate(cert):
        raise IamError("ValidationException", "SourceData must be a PEM-encoded X.509 certificate.", 400)
    tid = uuid.uuid4().hex[:12]
    arn = f"arn:aws:rolesanywhere:us-east-1:{store.account_id}:trust-anchor/{tid}"
    t = {"id": tid, "arn": arn, "name": name, "source_data": cert, "created": _now()}
    store.trust_anchors[arn] = t
    store.persist()
    return _envelope("CreateTrustAnchor", _trust_anchor_xml(t))


def _list_trust_anchors(store, params):
    items = sorted(store.trust_anchors.values(), key=lambda t: t["created"])
    return _envelope("ListTrustAnchors", "<TrustAnchors>" + "".join(_trust_anchor_xml(t) for t in items) + "</TrustAnchors>")


def _delete_trust_anchor(store, params):
    arn = str(params.get("TrustAnchorArn", "")).strip()
    if arn not in store.trust_anchors:
        raise IamError("ResourceNotFoundException", f"Trust anchor {arn} not found.", 404)
    del store.trust_anchors[arn]
    store.persist()
    return _envelope("DeleteTrustAnchor")


def _profile_xml(p: dict) -> str:
    roles = "".join(_el("member", r) for r in p["role_arns"])
    return ("<ProfileDetail>" + _el("ProfileId", p["id"]) + _el("ProfileArn", p["arn"]) + _el("Name", p["name"])
            + f"<RoleArns>{roles}</RoleArns>" + _el("Enabled", "true") + _el("CreatedAt", p["created"]) + "</ProfileDetail>")


def _create_profile(store, params):
    name = str(params.get("Name", "")).strip()
    if not name:
        raise IamError("ValidationError", "Name is required.", 400)
    role_arns = _members(params, "RoleArns")
    if not role_arns:
        raise IamError("ValidationError", "RoleArns must have at least one role.", 400)
    for arn in role_arns:
        if not any(r["arn"] == arn for r in store.roles.values()):
            raise IamError("ValidationException", f"Role {arn} does not exist.", 400)
    pid = uuid.uuid4().hex[:12]
    arn = f"arn:aws:rolesanywhere:us-east-1:{store.account_id}:profile/{pid}"
    p = {"id": pid, "arn": arn, "name": name, "role_arns": role_arns, "created": _now()}
    store.rolesanywhere_profiles[arn] = p
    store.persist()
    return _envelope("CreateProfile", _profile_xml(p))


def _list_profiles(store, params):
    items = sorted(store.rolesanywhere_profiles.values(), key=lambda p: p["created"])
    return _envelope("ListProfiles", "<Profiles>" + "".join(_profile_xml(p) for p in items) + "</Profiles>")


def _delete_profile(store, params):
    arn = str(params.get("ProfileArn", "")).strip()
    if arn not in store.rolesanywhere_profiles:
        raise IamError("ResourceNotFoundException", f"Profile {arn} not found.", 404)
    del store.rolesanywhere_profiles[arn]
    store.persist()
    return _envelope("DeleteProfile")


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
    "CreateVirtualMFADevice": _create_virtual_mfa_device, "DeleteVirtualMFADevice": _delete_virtual_mfa_device,
    "EnableMFADevice": _enable_mfa_device, "DeactivateMFADevice": _deactivate_mfa_device,
    "ResyncMFADevice": _resync_mfa_device, "ListMFADevices": _list_mfa_devices,
    "ListVirtualMFADevices": _list_virtual_mfa_devices,
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
    # Vyomi-only (see the functions' docstrings above): SCP/RCP + account access requests.
    "CreateOrgPolicy": _create_org_policy, "ListOrgPolicies": _list_org_policies,
    "DescribeOrgPolicy": _describe_org_policy, "DeleteOrgPolicy": _delete_org_policy,
    "RequestAccountAccess": _request_account_access,
    "ListAccountAccessRequests": _list_account_access_requests,
    # Real IAM API: service last-accessed data (see iam.last-accessed).
    "GenerateServiceLastAccessedDetails": _generate_service_last_accessed_details,
    "GetServiceLastAccessedDetails": _get_service_last_accessed_details,
    # Vyomi-only (see the functions' docstrings above): policy-from-activity generator,
    # Access Analyzer, Roles Anywhere.
    "GeneratePolicyFromActivity": _generate_policy_from_activity,
    "CreateAnalyzer": _create_analyzer, "ListAnalyzers": _list_analyzers, "GetAnalyzer": _get_analyzer,
    "UpdateAnalyzer": _update_analyzer, "DeleteAnalyzer": _delete_analyzer,
    "ListFindings": _list_findings, "GetFinding": _get_finding, "UpdateFindingStatus": _update_finding_status,
    "CreateTrustAnchor": _create_trust_anchor, "ListTrustAnchors": _list_trust_anchors,
    "DeleteTrustAnchor": _delete_trust_anchor,
    "CreateProfile": _create_profile, "ListProfiles": _list_profiles, "DeleteProfile": _delete_profile,
}


def dispatch(store: IamStore, params: dict | None = None, s3_store=None) -> IamResponse:
    """The single routing point for the native AWS IAM Query protocol — what an
    unmodified aws-cli / boto3 IAM client speaks. `params` is the parsed
    form-encoded body ({"Action": "CreateUser", "UserName": ...}). `s3_store` backs
    Access Analyzer's external-access scan over S3 bucket policies (Vyomi-only)."""
    params = params if isinstance(params, dict) else {}
    action = str(params.get("Action", "")).strip()
    if not action:
        return _error("MissingAction", "The request must include an Action.", 400)
    op = _OPS.get(action)
    if op is None:
        return _error("InvalidAction", f"The action {action} is not implemented.", 400)
    try:
        if action in _NEEDS_S3_STORE:
            return op(store, params, s3_store=s3_store)
        return op(store, params)
    except IamError as e:
        return _error(e.code, e.message, e.status)


# ── decision helper (not a native action — for in-tab enforcement / console) ──
def is_authorized(store: IamStore, principal: str, action: str, resource: str,
                  context: dict | None = None) -> dict:
    """Convenience authorization probe used by in-tab enforcement / the console —
    the analogue of server.py's _iam_authorize. Returns {allowed, decision, reason}."""
    identity, docs, boundary = _resolve_policy_docs(store, principal)
    mfa_present = identity["type"] == "user" and _has_mfa(store, identity["name"])
    ctx = {"aws:PrincipalArn": identity["arn"], "aws:PrincipalType": identity["type"],
           "aws:username": identity["name"], "aws:RequestedRegion": "us-east-1",
           "aws:ResourceArn": resource, "aws:MultiFactorAuthPresent": str(mfa_present).lower()}
    if context:
        ctx.update({k: str(v) for k, v in context.items()})
    decision, reason = store.engine.evaluate(docs, action, resource, ctx)
    decision = _apply_boundary(store, boundary, decision, action, resource, ctx)
    if decision != "allowed" and reason == "":
        reason = f"permissions boundary clips {action} on {resource}"
    return {"allowed": decision == "allowed", "decision": decision, "reason": reason}
