"""Console REST facade for Cognito user pools — the friendly JSON the AWS console
SPA speaks (`/api/cognito-idp/...`), served by the SAME engine (core/cognito_idp_core)
as the native SDK/CLI wire. One implementation for the offline appliance (FastAPI
route) and Nano (service-worker -> Pyodide adapter). Pure: stdlib + the core only.

    handle(store, method, path, query, body) -> (status, json-able)

`path` is the part after `/api/cognito-idp`.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from core import cognito_idp_core as cg

PFX = cg.TARGET_PREFIX


def _iso(epoch) -> str:
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""


def _call(store, op, **p):
    r = cg.dispatch(store, PFX + op, p)
    if r.status >= 400:
        raise cg.CognitoError(r.body.get("__type", "Error"), r.body.get("message", op + " failed"), r.status)
    return r.body


def _pool_view(store, pool: dict) -> dict:
    pid = pool["Id"]
    pol = (pool.get("Policies") or {}).get("PasswordPolicy") or {}
    return {
        "id": pid, "name": pool["Name"], "arn": pool["Arn"], "status": "Active",
        "region": store.region, "tier": (pool.get("UserPoolTier") or "ESSENTIALS").title(),
        "users": len(store.users.get(pid, {})), "clients": len(store.clients.get(pid, {})),
        "groups": len(store.groups.get(pid, {})), "mfa": pool.get("MfaConfiguration", "OFF"),
        "sign_in": ", ".join(pool.get("UsernameAttributes") or []) or "username",
        "domain": pool.get("Domain") or "", "created": _iso(pool["CreationDate"]),
        "last_modified": _iso(pool["LastModifiedDate"]),
        "deletion_protection": pool.get("DeletionProtection", "INACTIVE"),
        "min_password_length": pol.get("MinimumLength", 8),
        "issuer": f"https://cognito-idp.{store.region}.amazonaws.com/{pid}",
        "tags": dict(pool.get("UserPoolTags") or {}),
        "auto_verified": ", ".join(pool.get("AutoVerifiedAttributes") or []) or "none",
    }


def _user_view(u: dict) -> dict:
    am = {a["Name"]: a["Value"] for a in u["Attributes"]}
    return {"username": u["Username"], "email": am.get("email", ""),
            "email_verified": am.get("email_verified", "false"), "status": u["UserStatus"],
            "enabled": "Enabled" if u["Enabled"] else "Disabled", "sub": am.get("sub", ""),
            "groups": ", ".join(u.get("_groups", [])), "created": _iso(u["UserCreateDate"]),
            "last_modified": _iso(u["UserLastModifiedDate"])}


def _client_view(c: dict) -> dict:
    return {"client_id": c["ClientId"], "name": c["ClientName"],
            "secret": "Yes" if c.get("ClientSecret") else "No",
            "auth_flows": ", ".join(c.get("ExplicitAuthFlows") or []),
            "created": _iso(c["CreationDate"]),
            "access_token_validity": f'{c.get("AccessTokenValidity", 60)} {(c.get("TokenValidityUnits") or {}).get("AccessToken", "minutes")}'}


def _group_view(g: dict, store, pid) -> dict:
    members = sum(1 for u in store.users[pid].values() if g["GroupName"] in u.get("_groups", []))
    return {"group_name": g["GroupName"], "description": g.get("Description") or "No description",
            "precedence": g.get("Precedence", "None"), "members": members, "created": _iso(g["CreationDate"]),
            "role_arn": g.get("RoleArn") or "None"}


def handle(store, method, path, query=None, body=None):
    query, body = query or {}, body or {}
    path = "/" + path.strip("/")
    method = method.upper()
    try:
        if path == "/user-pools":
            if method == "GET":
                pools = sorted(store.pools.values(), key=lambda p: p["CreationDate"])
                return 200, {"user_pools": [_pool_view(store, p) for p in pools]}
            if method == "POST":
                name = body.get("name") or body.get("PoolName") or "my-user-pool"
                req = {"PoolName": name}
                if body.get("sign_in") in ("email", "phone_number"):
                    req["UsernameAttributes"] = [body["sign_in"]]
                if body.get("mfa") in ("OFF", "ON", "OPTIONAL"):
                    req["MfaConfiguration"] = body["mfa"]
                if body.get("min_password_length"):
                    req["Policies"] = {"PasswordPolicy": {"MinimumLength": int(body["min_password_length"])}}
                if body.get("auto_verified") in ("email", "phone_number"):
                    req["AutoVerifiedAttributes"] = [body["auto_verified"]]
                if isinstance(body.get("tags"), dict) and body["tags"]:
                    req["UserPoolTags"] = body["tags"]
                if req.get("MfaConfiguration") in ("ON", "OPTIONAL"):
                    req["MfaConfiguration"] = "OFF"   # MFA needs an SMS/TOTP config the emulator lacks
                pool = _call(store, "CreateUserPool", **req)["UserPool"]
                # a pool is only useful with an app client: create the default one like the console wizard
                _call(store, "CreateUserPoolClient", UserPoolId=pool["Id"], ClientName=body.get("client_name") or f"{name}-client",
                      ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"])
                return 201, {"ok": True, **_pool_view(store, store.pools[pool["Id"]])}
        m = re.fullmatch(r"/user-pools/([^/]+)", path)
        if m:
            pid = m.group(1)
            if method == "GET":
                return 200, _pool_view(store, cg._pool(store, pid))
            if method == "DELETE":
                if store.pools.get(pid, {}).get("DeletionProtection") == "ACTIVE":
                    _call(store, "UpdateUserPool", UserPoolId=pid, DeletionProtection="INACTIVE")
                _call(store, "DeleteUserPool", UserPoolId=pid)
                return 200, {"ok": True}
            if method in ("PUT", "PATCH"):
                req = {"UserPoolId": pid}
                if "tags" in body:
                    req["UserPoolTags"] = body["tags"] or {}
                if body.get("mfa"):
                    req["MfaConfiguration"] = body["mfa"]
                if "deletion_protection" in body:
                    req["DeletionProtection"] = body["deletion_protection"]
                _call(store, "UpdateUserPool", **req)
                return 200, _pool_view(store, store.pools[pid])
        m = re.fullmatch(r"/user-pools/([^/]+)/(users|groups|clients)", path)
        if m:
            pid, kind = m.groups()
            cg._pool(store, pid)
            if kind == "users":
                if method == "GET":
                    return 200, {"users": [_user_view(u) for u in sorted(store.users[pid].values(), key=lambda u: u["UserCreateDate"])]}
                attrs = [{"Name": "email", "Value": body["email"]}, {"Name": "email_verified", "Value": "true"}] if body.get("email") else []
                req = {"UserPoolId": pid, "Username": body.get("username") or "user1", "UserAttributes": attrs}
                if body.get("password"):
                    req["TemporaryPassword"] = body["password"]
                u = _call(store, "AdminCreateUser", **req)["User"]
                return 201, {"ok": True, "username": u["Username"], "status": u["UserStatus"]}
            if kind == "groups":
                if method == "GET":
                    return 200, {"groups": [_group_view(g, store, pid) for g in sorted(store.groups[pid].values(), key=lambda g: g["GroupName"])]}
                req = {"UserPoolId": pid, "GroupName": body.get("group_name") or body.get("name") or "group1",
                       "Description": body.get("description") or ""}
                if body.get("precedence") not in (None, ""):
                    req["Precedence"] = int(body["precedence"])
                _call(store, "CreateGroup", **req)
                return 201, {"ok": True}
            if method == "GET":
                return 200, {"clients": [_client_view(c) for c in sorted(store.clients[pid].values(), key=lambda c: c["CreationDate"])]}
            flows = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
            c = _call(store, "CreateUserPoolClient", UserPoolId=pid, ClientName=body.get("name") or "app-client",
                      GenerateSecret=bool(body.get("generate_secret")), ExplicitAuthFlows=flows)["UserPoolClient"]
            return 201, {"ok": True, "client_id": c["ClientId"]}
        m = re.fullmatch(r"/user-pools/([^/]+)/(users|groups|clients)/([^/]+)(?:/([a-z\-]+))?", path)
        if m:
            pid, kind, ident, act = m.groups()
            if kind == "users":
                if method == "DELETE":
                    _call(store, "AdminDeleteUser", UserPoolId=pid, Username=ident)
                    return 200, {"ok": True}
                if method == "GET":
                    return 200, _user_view(cg._find_user(store, pid, ident))
                ops = {"enable": "AdminEnableUser", "disable": "AdminDisableUser", "confirm": "AdminConfirmSignUp",
                       "reset-password": "AdminResetUserPassword", "sign-out": "AdminUserGlobalSignOut"}
                if act in ops:
                    _call(store, ops[act], UserPoolId=pid, Username=ident)
                    return 200, {"ok": True}
            if kind == "groups" and method == "DELETE":
                _call(store, "DeleteGroup", UserPoolId=pid, GroupName=ident)
                return 200, {"ok": True}
            if kind == "clients" and method == "DELETE":
                _call(store, "DeleteUserPoolClient", UserPoolId=pid, ClientId=ident)
                return 200, {"ok": True}
        m = re.fullmatch(r"/user-pools/([^/]+)/domain", path)
        if m:
            pid = m.group(1)
            pool = cg._pool(store, pid)
            if method == "GET":
                d = store.domains.get(pool.get("Domain") or "")
                return 200, {"domain": (d or {}).get("Domain", ""), "status": (d or {}).get("Status", ""),
                             "cloudfront": (d or {}).get("CloudFrontDistribution", "")}
            if method == "POST":
                _call(store, "CreateUserPoolDomain", UserPoolId=pid, Domain=body.get("domain") or f"{pool['Name']}-{pid[-6:]}".lower())
                return 201, {"ok": True}
            if method == "DELETE":
                _call(store, "DeleteUserPoolDomain", UserPoolId=pid, Domain=pool.get("Domain", ""))
                return 200, {"ok": True}
        return 404, {"code": "NotFound", "message": f"No console route {method} {path}"}
    except cg.CognitoError as e:
        return e.status, {"ok": False, "code": e.code, "message": e.message}
