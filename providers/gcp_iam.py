from __future__ import annotations

import base64
import copy
import json
import uuid
from typing import Any

from fastapi import HTTPException

from core.app_context import (
    gcp_iam_state,
    gcp_project_name as _gcp_project_name,
    id_gen as _id,
    now as _now,
)


def _server():
    import server as server_module

    return server_module


def _strip_action_suffix(value: str, *suffixes: str) -> str:
    text = str(value or "")
    for suffix in suffixes:
        if suffix and text.endswith(suffix):
            return text[: -len(suffix)]
    return text


# ── org policy enforcement + Data Access audit log, shared with core/gcp_iam_core.py ──
# This legacy handler keeps its own service-account state (gcp_iam_state) rather than
# core/gcp_iam_core's, but the console's Org Policies and Audit logs pages are backed by
# the SAME durable stores on both substrates (net_new_core_stores()["gcp_rm"], the
# active space's Cloud Logging slot) — so a policy created there must be honoured here too.
def _deny_if_org_policy_enforced(project: str, constraint_id: str) -> None:
    from core.appliance_stores import net_new_core_stores
    from core.gcp_iam_core import org_policy_enforced
    rm_store = net_new_core_stores()["gcp_rm"]
    if org_policy_enforced(rm_store, project, constraint_id):
        from core.native_errors import NativeHTTPError   # top-level {"error": …}, like GCP
        raise NativeHTTPError(412, {
            "error": {"code": 412,
                      "message": f"Operation denied by org policy: 'constraints/{constraint_id}' "
                                 f"is enforced on 'projects/{project}'.",
                      "status": "FAILED_PRECONDITION"}})


def _iam_audit_log(project: str, log_type: str, message: str) -> None:
    from core.gcp_iam_core import audit_log_enabled
    policy = gcp_iam_state.get("policies", {}).get(project) or {}
    if not audit_log_enabled(policy, "iam.googleapis.com", log_type):
        return
    try:
        from core import gcp_logging_core as lg
        from routes.gcp_logging import _STORE
    except Exception:
        return
    entry = {
        "logName": f"projects/{project}/logs/iam.googleapis.com%2Fdata_access",
        "resource": {"type": "project", "labels": {"project_id": project}},
        "severity": "NOTICE",
        "textPayload": message,
        "labels": {"logType": log_type},
    }
    lg.write_entries(_STORE, None, {"entries": [entry]})


def api_gcp_iam_get_policy(project: str):
    s = _server()
    project = _strip_action_suffix(project, ":getIamPolicy", ":setIamPolicy", ":testIamPermissions")
    project = _gcp_project_name(project)
    _iam_audit_log(project, "ADMIN_READ", f"iam.googleapis.com getIamPolicy on projects/{project}")
    return s._gcp_iam_policy_view(project)


async def api_gcp_iam_set_policy(project: str, request):
    s = _server()
    project = _strip_action_suffix(project, ":getIamPolicy", ":setIamPolicy", ":testIamPermissions")
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    policy = s._gcp_iam_set_policy(project, payload.get("policy", payload) if isinstance(payload.get("policy"), dict) else payload)
    return policy


async def api_gcp_iam_test_permissions(project: str, request):
    s = _server()
    project = _strip_action_suffix(project, ":getIamPolicy", ":setIamPolicy", ":testIamPermissions")
    project = _gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    permissions = payload.get("permissions", []) if isinstance(payload, dict) else []
    permissions = permissions if isinstance(permissions, list) else []
    # Return only the permissions actually granted to the calling principal by
    # the project's policy bindings (instead of echoing the request).
    try:
        from core import gcp_iam_policy
        space = s._gcp_active_space_dict()
        principal = request.headers.get("x-cloudlearn-principal") or str(space.get("active_principal") or "root")
        policies = gcp_iam_state.get("policies", {}) if isinstance(gcp_iam_state.get("policies"), dict) else {}
        policy = policies.get(project) or {}
        bindings = policy.get("bindings", []) if isinstance(policy, dict) else []
        granted = [p for p in permissions if gcp_iam_policy.authorize(principal, p, bindings)]
        return {"permissions": granted}
    except Exception:
        return {"permissions": permissions}


def api_gcp_iam_list_service_accounts(project: str):
    s = _server()
    project = _gcp_project_name(project)
    _iam_audit_log(project, "ADMIN_READ", f"iam.googleapis.com serviceAccounts.list on projects/{project}")
    sas = []
    for sa in gcp_iam_state.setdefault("service_accounts", {}).get(project, {}).values():
        sas.append({
            "name": sa["name"],
            "projectId": project,
            "uniqueId": sa.get("uniqueId", s._gcp_compute_numeric_id(f"{project}:{sa['name']}")),
            "email": sa["email"],
            "displayName": sa.get("displayName", sa["name"]),
            "description": sa.get("description", ""),
            "oauth2ClientId": sa.get("oauth2ClientId", ""),
            "disabled": bool(sa.get("disabled", False)),
            "createTime": sa.get("createTime", _now()),
            "etag": sa.get("etag", ""),
        })
    return {"accounts": sas, "nextPageToken": "", "kind": "iam#serviceAccountList"}


async def api_gcp_iam_create_service_account(project: str, request):
    s = _server()
    project = _gcp_project_name(project)
    _deny_if_org_policy_enforced(project, "iam.disableServiceAccountCreation")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    sa_id = str(payload.get("accountId") or payload.get("serviceAccountId") or payload.get("name") or _id("sa")).split("/")[-1].strip()
    display_name = str(payload.get("displayName") or payload.get("display_name") or sa_id)
    email = f"{sa_id}@{project}.iam.gserviceaccount.com"
    rec = {"name": sa_id, "project": project, "uniqueId": s._gcp_compute_numeric_id(f"{project}:{sa_id}"), "email": email, "displayName": display_name, "description": str(payload.get("description") or ""), "oauth2ClientId": _id("oauth"), "disabled": bool(payload.get("disabled", False)), "createTime": _now(), "etag": _id("etag")}
    gcp_iam_state.setdefault("service_accounts", {}).setdefault(project, {})[sa_id] = rec
    return {"name": f"projects/{project}/serviceAccounts/{email}", "projectId": project, "uniqueId": rec["uniqueId"], "email": email, "displayName": display_name, "description": rec["description"], "oauth2ClientId": rec["oauth2ClientId"], "disabled": rec["disabled"], "etag": rec["etag"]}


def api_gcp_iam_get_service_account(project: str, account: str):
    project = _gcp_project_name(project)
    s = _server()
    accounts = gcp_iam_state.setdefault("service_accounts", {}).setdefault(project, {})
    for key, rec in accounts.items():
        if account in {key, rec.get("email", ""), rec.get("name", "")}:
            _iam_audit_log(project, "ADMIN_READ", f"iam.googleapis.com serviceAccounts.get {rec.get('email', account)}")
            return {
                "name": f"projects/{project}/serviceAccounts/{rec['email']}",
                "projectId": project,
                "uniqueId": rec.get("uniqueId", s._gcp_compute_numeric_id(f"{project}:{rec['name']}")),
                "email": rec["email"],
                "displayName": rec.get("displayName", rec["name"]),
                "description": rec.get("description", ""),
                "oauth2ClientId": rec.get("oauth2ClientId", ""),
                "disabled": bool(rec.get("disabled", False)),
                "createTime": rec.get("createTime", _now()),
                "etag": rec.get("etag", ""),
            }
    raise HTTPException(404, detail="Service account not found")


def api_gcp_iam_delete_service_account(project: str, account: str):
    project = _gcp_project_name(project)
    accounts = gcp_iam_state.setdefault("service_accounts", {}).setdefault(project, {})
    target = None
    for key, rec in accounts.items():
        if account in {key, rec.get("email", ""), rec.get("name", "")}:
            target = key
            break
    if not target:
        raise HTTPException(404, detail="Service account not found")
    del accounts[target]
    return {"done": True}


async def api_gcp_iam_patch_service_account(project: str, account: str, request):
    """PATCH .../serviceAccounts/{account} — update displayName/description/disabled."""
    project = _gcp_project_name(project)
    accounts = gcp_iam_state.setdefault("service_accounts", {}).setdefault(project, {})
    target = None
    for key, rec in accounts.items():
        if account in {key, rec.get("email", ""), rec.get("name", "")}:
            target = key
            break
    if not target:
        raise HTTPException(404, detail="Service account not found")
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    # Real GCP nests the new fields under "serviceAccount" with an updateMask.
    body = payload.get("serviceAccount") if isinstance(payload.get("serviceAccount"), dict) else payload
    rec = accounts[target]
    if "displayName" in body:
        rec["displayName"] = str(body.get("displayName") or "")
    if "description" in body:
        rec["description"] = str(body.get("description") or "")
    was_disabled = bool(rec.get("disabled"))
    if "disabled" in body:
        rec["disabled"] = bool(body.get("disabled"))
    if "disabled" in body and bool(rec["disabled"]) != was_disabled:
        _sa_event(rec, project, "DISABLE" if rec["disabled"] else "ENABLE")
    if "displayName" in body or "description" in body:
        _sa_event(rec, project, "UPDATE")
    accounts[target] = rec
    return {"name": f"projects/{project}/serviceAccounts/{rec['email']}", "projectId": project, "uniqueId": rec.get("uniqueId", ""), "email": rec["email"], "displayName": rec.get("displayName", ""), "description": rec.get("description", ""), "oauth2ClientId": rec.get("oauth2ClientId", ""), "disabled": rec.get("disabled", False), "etag": rec.get("etag", "")}


def api_gcp_iam_list_users():
    project = _gcp_project_name(None)
    users = list(gcp_iam_state.setdefault("users", {}).get(project, {}).values())
    return {"users": users, "count": len(users)}


async def api_gcp_iam_create_user(request):
    s = _server()
    project = _gcp_project_name(None)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("user_name") or payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="User name is required")
    rec = {"user_id": _id("user"), "user_name": name, "arn": f"{s._gcp_iam_root()}/projects/{project}/users/{name}", "policies": [], "groups": [], "created": _now()}
    gcp_iam_state.setdefault("users", {}).setdefault(project, {})[rec["user_id"]] = rec
    return rec


def api_gcp_iam_delete_user(user_id: str):
    project = _gcp_project_name(None)
    users = gcp_iam_state.setdefault("users", {}).setdefault(project, {})
    if user_id not in users:
        raise HTTPException(404, detail="User not found")
    del users[user_id]
    return {"deleted": True, "user_id": user_id}


def api_gcp_iam_list_groups():
    project = _gcp_project_name(None)
    groups = list(gcp_iam_state.setdefault("groups", {}).get(project, {}).values())
    return {"groups": groups, "count": len(groups)}


async def api_gcp_iam_create_group(request):
    project = _gcp_project_name(None)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("group_name") or payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Group name is required")
    rec = {"group_id": _id("group"), "group_name": name, "path": str(payload.get("path") or "/"), "users": [], "policies": [], "created": _now()}
    gcp_iam_state.setdefault("groups", {}).setdefault(project, {})[rec["group_id"]] = rec
    return rec


def api_gcp_iam_delete_group(group_id: str):
    project = _gcp_project_name(None)
    groups = gcp_iam_state.setdefault("groups", {}).setdefault(project, {})
    if group_id not in groups:
        raise HTTPException(404, detail="Group not found")
    del groups[group_id]
    return {"deleted": True, "group_id": group_id}


def api_gcp_iam_list_roles():
    project = _gcp_project_name(None)
    roles = list(gcp_iam_state.setdefault("roles", {}).get(project, {}).values())
    return {"roles": roles, "count": len(roles)}


async def api_gcp_iam_create_role(request):
    project = _gcp_project_name(None)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("role_name") or payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Role name is required")
    rec = {"role_id": _id("role"), "role_name": name, "policies": [], "created": _now()}
    gcp_iam_state.setdefault("roles", {}).setdefault(project, {})[rec["role_id"]] = rec
    return rec


def api_gcp_iam_delete_role(role_id: str):
    project = _gcp_project_name(None)
    roles = gcp_iam_state.setdefault("roles", {}).setdefault(project, {})
    if role_id not in roles:
        raise HTTPException(404, detail="Role not found")
    del roles[role_id]
    return {"deleted": True, "role_id": role_id}


def api_gcp_iam_list_policies():
    project = _gcp_project_name(None)
    policies = list(gcp_iam_state.setdefault("policies", {}).get(project, {}).values())
    return {"policies": policies, "count": len(policies)}


async def api_gcp_iam_create_policy(request):
    project = _gcp_project_name(None)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("policy_name") or payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Policy name is required")
    rec = {"policy_id": _id("policy"), "policy_name": name, "document": payload.get("document") or {}, "created": _now()}
    gcp_iam_state.setdefault("policies", {}).setdefault(project, {})[rec["policy_id"]] = rec
    return rec


def api_gcp_iam_delete_policy(policy_id: str):
    project = _gcp_project_name(None)
    policies = gcp_iam_state.setdefault("policies", {}).setdefault(project, {})
    if policy_id not in policies:
        raise HTTPException(404, detail="Policy not found")
    del policies[policy_id]
    return {"deleted": True, "policy_id": policy_id}


def api_gcp_iam_get_account_settings():
    project = _gcp_project_name(None)
    account_settings = gcp_iam_state.setdefault("account_settings", {}).setdefault(project, {"password_policy": {"minimum_length": 8, "require_symbols": True, "require_numbers": True, "require_uppercase": True, "require_lowercase": True}})
    return {"account_settings": account_settings}


async def api_gcp_iam_update_account_settings(request):
    project = _gcp_project_name(None)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    account_settings = payload.get("account_settings") if isinstance(payload.get("account_settings"), dict) else payload
    gcp_iam_state.setdefault("account_settings", {})[project] = account_settings
    return {"account_settings": account_settings}


def api_gcp_iam_list_identity_providers():
    project = _gcp_project_name(None)
    providers = list(gcp_iam_state.setdefault("identity_providers", {}).get(project, {}).values())
    return {"identity_providers": providers, "count": len(providers)}


async def api_gcp_iam_create_identity_provider(request):
    project = _gcp_project_name(None)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("provider_name") or payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="Provider name is required")
    rec = {"provider_id": _id("idp"), "provider_name": name, "provider_type": str(payload.get("provider_type") or "SAML"), "url": str(payload.get("url") or ""), "created": _now()}
    gcp_iam_state.setdefault("identity_providers", {}).setdefault(project, {})[rec["provider_id"]] = rec
    return rec


def api_gcp_iam_delete_identity_provider(provider_id: str):
    project = _gcp_project_name(None)
    providers = gcp_iam_state.setdefault("identity_providers", {}).setdefault(project, {})
    if provider_id not in providers:
        raise HTTPException(404, detail="Identity provider not found")
    del providers[provider_id]
    return {"deleted": True, "provider_id": provider_id}


def _iam_find_sa(project: str, account: str):
    accounts = gcp_iam_state.setdefault("service_accounts", {}).setdefault(project, {})
    for rec in accounts.values():
        if isinstance(rec, dict) and account in {rec.get("name", ""), rec.get("email", ""), str(rec.get("uniqueId", ""))}:
            return rec
    return accounts.get(account)


async def api_gcp_iam_create_service_account_key(project: str, account: str, request=None):
    """POST serviceAccounts/{account}/keys — mint a user-managed key (google_service_account_key)."""
    project = _gcp_project_name(project)
    _deny_if_org_policy_enforced(project, "iam.disableServiceAccountKeyCreation")
    sa = _iam_find_sa(project, account)
    if not sa:
        raise HTTPException(404, detail="Service account not found")
    key_id = uuid.uuid4().hex
    email = sa.get("email", account)
    name = f"projects/{project}/serviceAccounts/{email}/keys/{key_id}"
    keyfile = {
        "type": "service_account", "project_id": project, "private_key_id": key_id,
        "client_email": email, "client_id": str(sa.get("uniqueId") or ""),
        "private_key": "-----BEGIN PRIVATE KEY-----\nSIMULATED-KEY\n-----END PRIVATE KEY-----\n",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    rec = {
        "name": name, "keyAlgorithm": "KEY_ALG_RSA_2048", "keyType": "USER_MANAGED",
        "keyOrigin": "GOOGLE_PROVIDED", "validAfterTime": _now(), "validBeforeTime": "2099-12-31T23:59:59Z",
        "privateKeyType": "TYPE_GOOGLE_CREDENTIALS_FILE",
        "privateKeyData": base64.b64encode(json.dumps(keyfile).encode()).decode("ascii"),
        "_key_id": key_id,
    }
    sa.setdefault("keys", {})[key_id] = rec
    _sa_event(sa, project, "CREATE_KEY", key_id)
    return rec  # create is the only call that returns privateKeyData


def _key_public_view(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k not in ("privateKeyData", "_key_id")}


def api_gcp_iam_list_service_account_keys(project: str, account: str):
    project = _gcp_project_name(project)
    sa = _iam_find_sa(project, account)
    if not sa:
        raise HTTPException(404, detail="Service account not found")
    _iam_audit_log(project, "ADMIN_READ", f"iam.googleapis.com keys.list for {sa.get('email', account)}")
    return {"keys": [_key_public_view(k) for k in sa.get("keys", {}).values()]}


def api_gcp_iam_get_service_account_key(project: str, account: str, key: str):
    project = _gcp_project_name(project)
    sa = _iam_find_sa(project, account)
    if not sa:
        raise HTTPException(404, detail="Service account not found")
    rec = sa.get("keys", {}).get(str(key).split("/")[-1])
    if not rec:
        raise HTTPException(404, detail="Key not found")
    _iam_audit_log(project, "ADMIN_READ", f"iam.googleapis.com keys.get {key} for {sa.get('email', account)}")
    return _key_public_view(rec)


def api_gcp_iam_delete_service_account_key(project: str, account: str, key: str):
    project = _gcp_project_name(project)
    sa = _iam_find_sa(project, account)
    if not sa:
        raise HTTPException(404, detail="Service account not found")
    kid = str(key).split("/")[-1]
    if sa.setdefault("keys", {}).pop(kid, None) is not None:
        _sa_event(sa, project, "DELETE_KEY", kid)
    return {}


# ── per-service-account admin activity (what the console's service-account Logs tab reads via
# GET .../serviceAccounts/{email}/policyActivity — same entry shape as core/gcp_iam_core on Nano) ──
def _sa_event(sa: dict, project: str, action: str, detail: str = "") -> None:
    from datetime import datetime, timezone
    log = sa.setdefault("_activity", [])
    log.append({"id": uuid.uuid4().hex[:12], "resource": f"projects/{project}/serviceAccounts/{sa.get('email', '')}",
                "action": action, "role": "", "member": detail,
                "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    del log[:max(0, len(log) - 500)]


def api_gcp_iam_service_account_activity(project: str, account: str):
    project = _gcp_project_name(project)
    sa = _iam_find_sa(project, account)
    if not sa:
        raise HTTPException(404, detail="Service account not found")
    return {"activity": [dict(e) for e in reversed(sa.get("_activity") or [])]}

