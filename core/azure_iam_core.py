"""Azure RBAC decision core — the Azure peer of AWS IAM's SimulatePrincipalPolicy
and GCP IAM's testIamPermissions, closing the identity-decision symmetry gap
(PARITY P3 #12). Azure had role assignments/definitions as inert ARM catalog only;
this adds a real **checkAccess** evaluator: given a principal, an action and a
scope, it resolves the principal's role assignments, expands each role's
actions/notActions, and decides Allowed / NotAllowed with Azure's wildcard +
scope-inheritance + notActions/deny semantics.

NO fastapi / azure-sdk / socket imports → loads under Pyodide. Role definitions and
assignments live on the store (lazy dicts), seeded with the Azure built-in roles
Owner / Contributor / Reader.

Decision model (faithful subset):
  - a role's `actions` (with `*` wildcards) grant; its `notActions` subtract.
  - an assignment applies when its scope is a prefix of the request scope
    (management-group → subscription → resource-group → resource inheritance).
  - a `deny` assignment (denyActions) wins over any allow (explicit-deny-wins).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# Azure built-in roles (the common three) as {actions, notActions}.
_BUILTIN_ROLES = {
    "Owner": {"actions": ["*"], "notActions": []},
    "Contributor": {"actions": ["*"],
                    "notActions": ["Microsoft.Authorization/*/Delete",
                                   "Microsoft.Authorization/*/Write",
                                   "Microsoft.Authorization/elevateAccess/Action"]},
    "Reader": {"actions": ["*/read"], "notActions": []},
}


@dataclass
class AzureIamResponse:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=dict)
    media_type: str | None = "application/json"


def _json(status: int, obj: dict) -> AzureIamResponse:
    return AzureIamResponse(status=status, body=json.dumps(obj).encode())


def _err(status: int, code: str, message: str) -> AzureIamResponse:
    return AzureIamResponse(status=status, body=json.dumps({"error": {"code": code, "message": message}}).encode())


def _role_defs(store) -> dict:
    m = getattr(store, "_azure_role_defs", None)
    if m is None:
        m = {name: {"roleName": name, **perms} for name, perms in _BUILTIN_ROLES.items()}
        store._azure_role_defs = m
    return m


def _assignments(store) -> dict:
    m = getattr(store, "_azure_role_assignments", None)
    if m is None:
        m = {}
        store._azure_role_assignments = m
    return m


def _wildcard_match(pattern: str, action: str) -> bool:
    """Azure action wildcard: `*` matches any run of characters (including '/').
    Case-insensitive, as Azure treats action strings."""
    regex = "^" + "".join(".*" if part == "*" else re.escape(part)
                          for part in re.split(r"(\*)", pattern)) + "$"
    return re.match(regex, action, re.IGNORECASE) is not None


def _matches_any(patterns, action: str) -> bool:
    return any(_wildcard_match(p, action) for p in (patterns or []))


def _scope_covers(assignment_scope: str, request_scope: str) -> bool:
    """An assignment at a broader scope covers narrower request scopes (Azure's
    hierarchical inheritance). Normalise trailing slashes."""
    a = (assignment_scope or "/").rstrip("/") or "/"
    r = (request_scope or "/").rstrip("/") or "/"
    if a == "/" or a == r:
        return True
    return r.startswith(a + "/")


def _resolve_role(store, role_ref: str) -> dict | None:
    defs = _role_defs(store)
    if role_ref in defs:
        return defs[role_ref]
    # role_ref may be a full roleDefinitionId ending in the name/guid
    tail = role_ref.rsplit("/", 1)[-1]
    return defs.get(tail)


# ── control plane ───────────────────────────────────────────────────────────
def _put_role_definition(store, name: str, body: dict) -> AzureIamResponse:
    perms = (body.get("properties") or body).get("permissions") or []
    actions, not_actions = [], []
    for p in perms:
        actions.extend(p.get("actions") or [])
        not_actions.extend(p.get("notActions") or [])
    role_name = (body.get("properties") or body).get("roleName") or name
    _role_defs(store)[role_name] = {"roleName": role_name, "actions": actions, "notActions": not_actions}
    return _json(201, {"name": name, "properties": {"roleName": role_name, "type": "CustomRole"}})


def _put_role_assignment(store, name: str, body: dict) -> AzureIamResponse:
    props = body.get("properties") or body
    assignment = {
        "name": name,
        "principalId": props.get("principalId", ""),
        "roleDefinition": props.get("roleName") or props.get("roleDefinitionId", ""),
        "scope": props.get("scope", "/"),
        "kind": str(props.get("kind", "allow")).lower(),   # "allow" | "deny"
        "denyActions": props.get("denyActions") or [],
    }
    _assignments(store)[name] = assignment
    return _json(201, {"name": name, "properties": {"principalId": assignment["principalId"],
                                                    "roleDefinitionId": assignment["roleDefinition"],
                                                    "scope": assignment["scope"]}})


def _delete_role_assignment(store, name: str) -> AzureIamResponse:
    if _assignments(store).pop(name, None) is None:
        return _err(404, "RoleAssignmentNotFound", f"Assignment '{name}' not found.")
    return _json(200, {})


# ── decision plane ──────────────────────────────────────────────────────────
def check_access(store, principal_id: str, action: str, scope: str) -> dict:
    """Return {accessDecision: 'Allowed'|'NotAllowed', roles:[...]} for a principal
    performing `action` on `scope`. Explicit deny wins over any allow."""
    allowed = False
    granting_roles = []
    denied = False
    for a in _assignments(store).values():
        if a["principalId"] != principal_id:
            continue
        if not _scope_covers(a["scope"], scope):
            continue
        if a["kind"] == "deny":
            if _matches_any(a.get("denyActions"), action):
                denied = True
            continue
        role = _resolve_role(store, a["roleDefinition"])
        if not role:
            continue
        if _matches_any(role.get("actions"), action) and not _matches_any(role.get("notActions"), action):
            allowed = True
            granting_roles.append(role["roleName"])
    decision = "Allowed" if (allowed and not denied) else "NotAllowed"
    return {"accessDecision": decision, "roles": granting_roles,
            "hasDenyAssignment": denied}


def _check_access(store, body: dict) -> AzureIamResponse:
    subject = body.get("subject") or {}
    principal_id = body.get("principalId") or subject.get("principalId") or subject.get("attributes", {}).get("ObjectId", "")
    scope = body.get("scope") or (body.get("resource") or {}).get("id") or "/"
    actions = body.get("actions")
    if actions is None:
        single = body.get("action") or ""
        actions = [{"id": single}] if single else []
    results = []
    for a in actions:
        act = a.get("id") if isinstance(a, dict) else str(a)
        dec = check_access(store, principal_id, act, scope)
        results.append({"actionId": act, "accessDecision": dec["accessDecision"],
                        "roles": dec["roles"]})
    return _json(200, {"value": results})


# ── dispatch ────────────────────────────────────────────────────────────────
def dispatch(store, method: str, path: str,
             query: dict | None = None, headers: dict | None = None,
             body: bytes = b"") -> AzureIamResponse:
    """Native-ish Azure Authorization wire:
        PUT  /providers/Microsoft.Authorization/roleDefinitions/{id}
        PUT  /providers/Microsoft.Authorization/roleAssignments/{id}
        DELETE /providers/Microsoft.Authorization/roleAssignments/{id}
        POST /providers/Microsoft.Authorization/checkAccess
    (a leading /subscriptions/{id}/... or other scope prefix is accepted and
    ignored for routing — the scope travels in the assignment/request body.)
    """
    method = (method or "GET").upper()
    p = path.split("?", 1)[0]
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        payload = {}

    segs = [s for s in p.split("/") if s != ""]
    # find the Microsoft.Authorization marker; route on what follows.
    try:
        i = next(idx for idx, s in enumerate(segs) if s.lower() == "microsoft.authorization")
    except StopIteration:
        return _err(404, "NotFound", f"Not an Authorization path: {path}")
    tail = segs[i + 1:]
    if not tail:
        return _err(404, "NotFound", f"Unknown path: {path}")

    kind = tail[0].lower()
    if kind == "checkaccess" and method == "POST":
        return _check_access(store, payload)
    if kind == "roledefinitions" and len(tail) >= 2 and method == "PUT":
        return _put_role_definition(store, tail[1], payload)
    if kind == "roleassignments" and len(tail) >= 2:
        if method == "PUT":
            return _put_role_assignment(store, tail[1], payload)
        if method == "DELETE":
            return _delete_role_assignment(store, tail[1])
    return _err(404, "NotFound", f"Unsupported {method} {path}")
