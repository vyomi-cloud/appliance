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


# More built-ins, keyed by their real, stable role-definition GUIDs (Owner/Contributor/Reader are above).
# Data-plane roles carry dataActions: a request is data-plane when the action matches dataActions.
_BUILTIN_IDS = {
    "8e3af657-a8ff-443c-a75c-2fe8c4bcb635": "Owner",
    "b24988ac-6180-42a0-ab88-20f7382dd24c": "Contributor",
    "acdd72a7-3385-48ef-bd42-f606fba81ae7": "Reader",
    "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9": "User Access Administrator",
    "9980e02c-c2be-4d73-94e8-173b1dc7cf3c": "Virtual Machine Contributor",
    "4d97b98b-1d4f-4787-a291-c67834d212e7": "Network Contributor",
    "43d0d8ad-25c7-4714-9337-8ba259a9fe05": "Monitoring Reader",
    "ba92f5b4-2d11-453d-a403-e96b0029c9fe": "Storage Blob Data Contributor",
    "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1": "Storage Blob Data Reader",
    "b7e6dc6d-f1e8-4753-8033-0f276bb0955b": "Storage Blob Data Owner",
    "974c5e8b-45b9-4653-ba55-5f855dd0fb88": "Storage Queue Data Contributor",
    "00482a5a-887f-4fb3-b363-3b7fe8e74483": "Key Vault Administrator",
    "b86a8fe4-44ce-4948-aee5-eccb2c155cd7": "Key Vault Secrets Officer",
    "4633458b-17de-408a-b874-0445c86b69e6": "Key Vault Secrets User",
    "090c5cfd-751d-490a-894a-3ce6f1109419": "Azure Service Bus Data Owner",
}
_BUILTIN_ROLES.update({
    "User Access Administrator": {"actions": ["*/read", "Microsoft.Authorization/*", "Microsoft.Support/*"], "notActions": []},
    "Virtual Machine Contributor": {"actions": ["Microsoft.Compute/virtualMachines/*", "Microsoft.Compute/disks/*", "Microsoft.Network/networkInterfaces/*",
                                                 "Microsoft.Network/virtualNetworks/read", "Microsoft.Network/virtualNetworks/subnets/join/action",
                                                 "Microsoft.Resources/subscriptions/resourceGroups/read", "Microsoft.Storage/storageAccounts/read"], "notActions": []},
    "Network Contributor": {"actions": ["Microsoft.Network/*"], "notActions": []},
    "Monitoring Reader": {"actions": ["*/read", "Microsoft.Insights/*/read"], "notActions": []},
    "Storage Blob Data Contributor": {"actions": ["Microsoft.Storage/storageAccounts/blobServices/containers/delete", "Microsoft.Storage/storageAccounts/blobServices/containers/read", "Microsoft.Storage/storageAccounts/blobServices/containers/write"], "notActions": [],
                                      "dataActions": ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/*"]},
    "Storage Blob Data Reader": {"actions": ["Microsoft.Storage/storageAccounts/blobServices/containers/read"], "notActions": [],
                                 "dataActions": ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read"]},
    "Storage Blob Data Owner": {"actions": ["Microsoft.Storage/storageAccounts/blobServices/containers/delete", "Microsoft.Storage/storageAccounts/blobServices/containers/read", "Microsoft.Storage/storageAccounts/blobServices/containers/write"], "notActions": [],
                                "dataActions": ["Microsoft.Storage/storageAccounts/blobServices/containers/blobs/*"]},
    "Storage Queue Data Contributor": {"actions": ["Microsoft.Storage/storageAccounts/queueServices/queues/delete", "Microsoft.Storage/storageAccounts/queueServices/queues/read", "Microsoft.Storage/storageAccounts/queueServices/queues/write"], "notActions": [],
                                       "dataActions": ["Microsoft.Storage/storageAccounts/queueServices/queues/messages/*"]},
    "Key Vault Administrator": {"actions": ["Microsoft.KeyVault/checkNameAvailability/read", "Microsoft.KeyVault/vaults/*"], "notActions": [],
                                "dataActions": ["Microsoft.KeyVault/vaults/*"]},
    "Key Vault Secrets Officer": {"actions": ["Microsoft.KeyVault/vaults/read"], "notActions": [],
                                  "dataActions": ["Microsoft.KeyVault/vaults/secrets/*"]},
    "Key Vault Secrets User": {"actions": ["Microsoft.KeyVault/vaults/read"], "notActions": [],
                               "dataActions": ["Microsoft.KeyVault/vaults/secrets/getSecret/action", "Microsoft.KeyVault/vaults/secrets/readMetadata/action"]},
    "Azure Service Bus Data Owner": {"actions": ["Microsoft.ServiceBus/*"], "notActions": [],
                                     "dataActions": ["Microsoft.ServiceBus/*"]},
})


def builtin_role_definitions(sub="00000000-0000-0000-0000-cloudlearn01"):
    """ARM-shaped built-in role definitions (what `GET /subscriptions/{s}/providers/Microsoft.Authorization/roleDefinitions` lists)."""
    out = []
    for guid, name in _BUILTIN_IDS.items():
        r = _BUILTIN_ROLES[name]
        out.append({"id": f"/subscriptions/{sub}/providers/Microsoft.Authorization/roleDefinitions/{guid}", "name": guid,
                    "type": "Microsoft.Authorization/roleDefinitions",
                    "properties": {"roleName": name, "type": "BuiltInRole", "description": f"Built-in role: {name}.",
                                   "assignableScopes": ["/"],
                                   "permissions": [{"actions": list(r["actions"]), "notActions": list(r.get("notActions", [])),
                                                    "dataActions": list(r.get("dataActions", [])), "notDataActions": []}]}})
    return out


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
    if tail.lower() in _BUILTIN_IDS:
        return {"roleName": _BUILTIN_IDS[tail.lower()], **_BUILTIN_ROLES[_BUILTIN_IDS[tail.lower()]]}
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


def _role_from_arm_def(rec):
    """A custom roleDefinitions ARM record -> {roleName, actions, notActions, dataActions}."""
    p = rec.get("properties") or {}
    perms = p.get("permissions") or []
    return {"roleName": p.get("roleName") or rec.get("name"),
            "actions": [a for x in perms for a in (x.get("actions") or [])],
            "notActions": [a for x in perms for a in (x.get("notActions") or [])],
            "dataActions": [a for x in perms for a in (x.get("dataActions") or [])],
            "notDataActions": [a for x in perms for a in (x.get("notDataActions") or [])]}


def arm_check_access(state, store, principal_id, action, scope):
    """checkAccess over BOTH the ARM role assignments in `state` (the ones `PUT .../roleAssignments` creates) and the legacy
    store, with built-in roles resolved by GUID/name and custom roles from ARM roleDefinitions records."""
    if store is None:
        class _S: pass
        store = _S()
    out = dict(check_access(store, principal_id, action, scope))
    roles, allowed, denied = list(out["roles"]), out["accessDecision"] == "Allowed", out["hasDenyAssignment"]
    is_data = False
    for rec in list((state or {}).values()):
        if not isinstance(rec, dict) or str(rec.get("_type", rec.get("type", ""))).lower() != "microsoft.authorization/roleassignments":
            continue
        p = rec.get("properties") or {}
        if p.get("principalId") != principal_id:
            continue
        sc = p.get("scope") or rec.get("_scope") or rec.get("id", "").rsplit("/providers/Microsoft.Authorization/roleAssignments/", 1)[0]
        if not _scope_covers(sc, scope):
            continue
        ref = str(p.get("roleDefinitionId", ""))
        tail = ref.rsplit("/", 1)[-1]
        role = None
        if tail.lower() in _BUILTIN_IDS:
            role = dict(_BUILTIN_ROLES[_BUILTIN_IDS[tail.lower()]], roleName=_BUILTIN_IDS[tail.lower()])
        elif tail in _BUILTIN_ROLES:
            role = dict(_BUILTIN_ROLES[tail], roleName=tail)
        else:
            d = state.get(ref.lower()) or next((r for r in state.values() if isinstance(r, dict) and r.get("name") == tail
                                                and str(r.get("_type", r.get("type", ""))).lower() == "microsoft.authorization/roledefinitions"), None)
            if d:
                role = _role_from_arm_def(d)
        if not role:
            continue
        if _matches_any(role.get("actions"), action) and not _matches_any(role.get("notActions"), action):
            allowed = True
            roles.append(role["roleName"])
        elif _matches_any(role.get("dataActions"), action) and not _matches_any(role.get("notDataActions"), action):
            allowed = is_data = True
            roles.append(role["roleName"])
    return {"accessDecision": "Allowed" if (allowed and not denied) else "NotAllowed", "roles": sorted(set(roles)),
            "hasDenyAssignment": denied, "isDataAction": is_data}


def arm_check_access_request(state, store, body):
    """Body of POST {scope}/providers/Microsoft.Authorization/checkAccess (api 2018-09-01-preview)."""
    body = body or {}
    subject = body.get("subject") or {}
    principal = body.get("principalId") or subject.get("principalId") or (subject.get("attributes") or {}).get("ObjectId", "")
    scope = body.get("scope") or (body.get("resource") or {}).get("id") or "/"
    acts = body.get("actions") or ([{"id": body["action"]}] if body.get("action") else [])
    res = []
    for a in acts:
        act = a.get("id") if isinstance(a, dict) else str(a)
        d = arm_check_access(state, store, principal, act, scope)
        res.append({"actionId": act, "accessDecision": d["accessDecision"], "isDataAction": d["isDataAction"], "roles": d["roles"],
                    "roleAssignment": None, "denyAssignment": None, "timeToLiveInMs": 300000})
    return {"value": res}


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
