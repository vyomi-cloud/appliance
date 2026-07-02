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
(Create/List), and SimulatePrincipalPolicy. MFA / SAML / instance profiles /
policy versions reuse the same helpers and slot in next.
"""
from __future__ import annotations

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
            + _el("CreateDate", u["created"]) + "</User>")


def _role_xml(store, r: dict) -> str:
    doc = r.get("assume_role_policy_document") or {}
    trust = _xml_escape(json.dumps(doc)) if doc else ""
    return ("<Role>" + _el("Path", r.get("path", "/")) + _el("RoleName", r["role_name"])
            + _el("RoleId", r["role_id"]) + _el("Arn", r["arn"]) + _el("CreateDate", r["created"])
            + (f"<AssumeRolePolicyDocument>{trust}</AssumeRolePolicyDocument>" if trust else "")
            + "</Role>")


def _policy_xml(store, p: dict) -> str:
    return ("<Policy>" + _el("PolicyName", p["policy_name"]) + _el("PolicyId", p["policy_id"])
            + _el("Arn", p["arn"]) + _el("Path", p.get("path", "/"))
            + _el("DefaultVersionId", p.get("default_version_id", "v1"))
            + _el("AttachmentCount", p.get("attachment_count", 0))
            + _el("CreateDate", p["created"]) + "</Policy>")


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


# ── user operations ─────────────────────────────────────────────────────────
def _create_user(store, params):
    name = str(params.get("UserName", "")).strip()
    if not name:
        raise IamError("ValidationError", "UserName is required.", 400)
    if store.get_user(name):
        raise IamError("EntityAlreadyExists", f"User with name {name} already exists.", 409)
    u = {"user_name": name, "user_id": _id("AIDA"), "path": params.get("Path", "/"),
         "arn": _user_arn(store, name), "created": _now(),
         "attached_policies": [], "inline_policies": {}, "groups": []}
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
         "attached_policies": [], "inline_policies": {}}
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
    p = {"policy_name": name, "policy_id": _id("ANPA"), "arn": arn,
         "path": params.get("Path", "/"), "document": _json_param(params, "PolicyDocument"),
         "created": _now(), "default_version_id": "v1", "attachment_count": 0}
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


# ── groups ───────────────────────────────────────────────────────────────────
def _create_group(store, params):
    name = str(params.get("GroupName", "")).strip()
    if not name:
        raise IamError("ValidationError", "GroupName is required.", 400)
    if store.get_group(name):
        raise IamError("EntityAlreadyExists", f"Group {name} already exists.", 409)
    g = {"group_name": name, "group_id": _id("AGPA"), "path": params.get("Path", "/"),
         "arn": _group_arn(store, name), "created": _now(), "members": [], "attached_policies": []}
    store.groups[name] = g
    store.persist()
    inner = ("<Group>" + _el("Path", g["path"]) + _el("GroupName", name) + _el("GroupId", g["group_id"])
             + _el("Arn", g["arn"]) + _el("CreateDate", g["created"]) + "</Group>")
    return _envelope("CreateGroup", inner)


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
    "CreateRole": _create_role, "GetRole": _get_role, "ListRoles": _list_roles, "DeleteRole": _delete_role,
    "CreatePolicy": _create_policy, "GetPolicy": _get_policy, "ListPolicies": _list_policies, "DeletePolicy": _delete_policy,
    "AttachUserPolicy": _attach_user_policy, "DetachUserPolicy": _detach_user_policy,
    "ListAttachedUserPolicies": _list_attached_user_policies, "AttachRolePolicy": _attach_role_policy,
    "PutUserPolicy": _put_user_policy, "GetUserPolicy": _get_user_policy,
    "CreateGroup": _create_group, "AddUserToGroup": _add_user_to_group, "AttachGroupPolicy": _attach_group_policy,
    "CreateAccessKey": _create_access_key, "ListAccessKeys": _list_access_keys,
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
