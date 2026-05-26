from __future__ import annotations

import copy
from typing import Any

from fastapi import HTTPException


def _server():
    import server as server_module

    return server_module


def _strip_action_suffix(value: str, *suffixes: str) -> str:
    text = str(value or "")
    for suffix in suffixes:
        if suffix and text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def api_gcp_iam_get_policy(project: str):
    s = _server()
    project = _strip_action_suffix(project, ":getIamPolicy", ":setIamPolicy", ":testIamPermissions")
    project = s._gcp_project_name(project)
    return s._gcp_iam_policy_view(project)


async def api_gcp_iam_set_policy(project: str, request):
    s = _server()
    project = _strip_action_suffix(project, ":getIamPolicy", ":setIamPolicy", ":testIamPermissions")
    project = s._gcp_project_name(project)
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
    project = s._gcp_project_name(project)
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
        policies = s.gcp_iam_state.get("policies", {}) if isinstance(s.gcp_iam_state.get("policies"), dict) else {}
        policy = policies.get(project) or {}
        bindings = policy.get("bindings", []) if isinstance(policy, dict) else []
        granted = [p for p in permissions if gcp_iam_policy.authorize(principal, p, bindings)]
        return {"permissions": granted}
    except Exception:
        return {"permissions": permissions}


def api_gcp_iam_list_service_accounts(project: str):
    s = _server()
    project = s._gcp_project_name(project)
    sas = []
    for sa in s.gcp_iam_state.setdefault("service_accounts", {}).get(project, {}).values():
        sas.append({
            "name": sa["name"],
            "projectId": project,
            "uniqueId": sa.get("uniqueId", s._gcp_compute_numeric_id(f"{project}:{sa['name']}")),
            "email": sa["email"],
            "displayName": sa.get("displayName", sa["name"]),
            "description": sa.get("description", ""),
            "oauth2ClientId": sa.get("oauth2ClientId", ""),
            "disabled": bool(sa.get("disabled", False)),
            "createTime": sa.get("createTime", s._now()),
            "etag": sa.get("etag", ""),
        })
    return {"accounts": sas, "nextPageToken": "", "kind": "iam#serviceAccountList"}


async def api_gcp_iam_create_service_account(project: str, request):
    s = _server()
    project = s._gcp_project_name(project)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    sa_id = str(payload.get("accountId") or payload.get("serviceAccountId") or payload.get("name") or s._id("sa")).split("/")[-1].strip()
    display_name = str(payload.get("displayName") or payload.get("display_name") or sa_id)
    email = f"{sa_id}@{project}.iam.gserviceaccount.com"
    rec = {"name": sa_id, "project": project, "uniqueId": s._gcp_compute_numeric_id(f"{project}:{sa_id}"), "email": email, "displayName": display_name, "description": str(payload.get("description") or ""), "oauth2ClientId": s._id("oauth"), "disabled": bool(payload.get("disabled", False)), "createTime": s._now(), "etag": s._id("etag")}
    s.gcp_iam_state.setdefault("service_accounts", {}).setdefault(project, {})[sa_id] = rec
    return {"name": f"projects/{project}/serviceAccounts/{email}", "projectId": project, "uniqueId": rec["uniqueId"], "email": email, "displayName": display_name, "description": rec["description"], "oauth2ClientId": rec["oauth2ClientId"], "disabled": rec["disabled"], "etag": rec["etag"]}


def api_gcp_iam_delete_service_account(project: str, account: str):
    s = _server()
    project = s._gcp_project_name(project)
    accounts = s.gcp_iam_state.setdefault("service_accounts", {}).setdefault(project, {})
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
    s = _server()
    project = s._gcp_project_name(project)
    accounts = s.gcp_iam_state.setdefault("service_accounts", {}).setdefault(project, {})
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
    if "disabled" in body:
        rec["disabled"] = bool(body.get("disabled"))
    accounts[target] = rec
    return {"name": f"projects/{project}/serviceAccounts/{rec['email']}", "projectId": project, "uniqueId": rec.get("uniqueId", ""), "email": rec["email"], "displayName": rec.get("displayName", ""), "description": rec.get("description", ""), "oauth2ClientId": rec.get("oauth2ClientId", ""), "disabled": rec.get("disabled", False), "etag": rec.get("etag", "")}


def api_gcp_iam_list_users():
    s = _server()
    project = s._gcp_project_name(None)
    users = list(s.gcp_iam_state.setdefault("users", {}).get(project, {}).values())
    return {"users": users, "count": len(users)}


async def api_gcp_iam_create_user(request):
    s = _server()
    project = s._gcp_project_name(None)
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
    rec = {"user_id": s._id("user"), "user_name": name, "arn": f"{s._gcp_iam_root()}/projects/{project}/users/{name}", "policies": [], "groups": [], "created": s._now()}
    s.gcp_iam_state.setdefault("users", {}).setdefault(project, {})[rec["user_id"]] = rec
    return rec


def api_gcp_iam_delete_user(user_id: str):
    s = _server()
    project = s._gcp_project_name(None)
    users = s.gcp_iam_state.setdefault("users", {}).setdefault(project, {})
    if user_id not in users:
        raise HTTPException(404, detail="User not found")
    del users[user_id]
    return {"deleted": True, "user_id": user_id}


def api_gcp_iam_list_groups():
    s = _server()
    project = s._gcp_project_name(None)
    groups = list(s.gcp_iam_state.setdefault("groups", {}).get(project, {}).values())
    return {"groups": groups, "count": len(groups)}


async def api_gcp_iam_create_group(request):
    s = _server()
    project = s._gcp_project_name(None)
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
    rec = {"group_id": s._id("group"), "group_name": name, "path": str(payload.get("path") or "/"), "users": [], "policies": [], "created": s._now()}
    s.gcp_iam_state.setdefault("groups", {}).setdefault(project, {})[rec["group_id"]] = rec
    return rec


def api_gcp_iam_delete_group(group_id: str):
    s = _server()
    project = s._gcp_project_name(None)
    groups = s.gcp_iam_state.setdefault("groups", {}).setdefault(project, {})
    if group_id not in groups:
        raise HTTPException(404, detail="Group not found")
    del groups[group_id]
    return {"deleted": True, "group_id": group_id}


def api_gcp_iam_list_roles():
    s = _server()
    project = s._gcp_project_name(None)
    roles = list(s.gcp_iam_state.setdefault("roles", {}).get(project, {}).values())
    return {"roles": roles, "count": len(roles)}


async def api_gcp_iam_create_role(request):
    s = _server()
    project = s._gcp_project_name(None)
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
    rec = {"role_id": s._id("role"), "role_name": name, "policies": [], "created": s._now()}
    s.gcp_iam_state.setdefault("roles", {}).setdefault(project, {})[rec["role_id"]] = rec
    return rec


def api_gcp_iam_delete_role(role_id: str):
    s = _server()
    project = s._gcp_project_name(None)
    roles = s.gcp_iam_state.setdefault("roles", {}).setdefault(project, {})
    if role_id not in roles:
        raise HTTPException(404, detail="Role not found")
    del roles[role_id]
    return {"deleted": True, "role_id": role_id}


def api_gcp_iam_list_policies():
    s = _server()
    project = s._gcp_project_name(None)
    policies = list(s.gcp_iam_state.setdefault("policies", {}).get(project, {}).values())
    return {"policies": policies, "count": len(policies)}


async def api_gcp_iam_create_policy(request):
    s = _server()
    project = s._gcp_project_name(None)
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
    rec = {"policy_id": s._id("policy"), "policy_name": name, "document": payload.get("document") or {}, "created": s._now()}
    s.gcp_iam_state.setdefault("policies", {}).setdefault(project, {})[rec["policy_id"]] = rec
    return rec


def api_gcp_iam_delete_policy(policy_id: str):
    s = _server()
    project = s._gcp_project_name(None)
    policies = s.gcp_iam_state.setdefault("policies", {}).setdefault(project, {})
    if policy_id not in policies:
        raise HTTPException(404, detail="Policy not found")
    del policies[policy_id]
    return {"deleted": True, "policy_id": policy_id}


def api_gcp_iam_get_account_settings():
    s = _server()
    project = s._gcp_project_name(None)
    account_settings = s.gcp_iam_state.setdefault("account_settings", {}).setdefault(project, {"password_policy": {"minimum_length": 8, "require_symbols": True, "require_numbers": True, "require_uppercase": True, "require_lowercase": True}})
    return {"account_settings": account_settings}


async def api_gcp_iam_update_account_settings(request):
    s = _server()
    project = s._gcp_project_name(None)
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    account_settings = payload.get("account_settings") if isinstance(payload.get("account_settings"), dict) else payload
    s.gcp_iam_state.setdefault("account_settings", {})[project] = account_settings
    return {"account_settings": account_settings}


def api_gcp_iam_list_identity_providers():
    s = _server()
    project = s._gcp_project_name(None)
    providers = list(s.gcp_iam_state.setdefault("identity_providers", {}).get(project, {}).values())
    return {"identity_providers": providers, "count": len(providers)}


async def api_gcp_iam_create_identity_provider(request):
    s = _server()
    project = s._gcp_project_name(None)
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
    rec = {"provider_id": s._id("idp"), "provider_name": name, "provider_type": str(payload.get("provider_type") or "SAML"), "url": str(payload.get("url") or ""), "created": s._now()}
    s.gcp_iam_state.setdefault("identity_providers", {}).setdefault(project, {})[rec["provider_id"]] = rec
    return rec


def api_gcp_iam_delete_identity_provider(provider_id: str):
    s = _server()
    project = s._gcp_project_name(None)
    providers = s.gcp_iam_state.setdefault("identity_providers", {}).setdefault(project, {})
    if provider_id not in providers:
        raise HTTPException(404, detail="Identity provider not found")
    del providers[provider_id]
    return {"deleted": True, "provider_id": provider_id}
