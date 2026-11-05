# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""App Service / Function App Entra authentication (Easy Auth ``authsettingsV2``) + Azure OpenAI hookup, substrate-free.

* **authsettingsV2** (``config/authsettingsV2``) is a real round-tripped config: ``platform.enabled``, ``globalValidation``
  (``unauthenticatedClientAction`` RedirectToLoginPage|AllowAnonymous|Return401|Return403, ``redirectToProvider``,
  ``excludedPaths``, ``requireAuthentication``), ``identityProviders.azureActiveDirectory`` (``registration``: ``clientId`` GUID,
  ``openIdIssuerUrl`` https://login.microsoftonline.com/{tenant}/v2.0 | sts.windows.net/{tenant}/, ``clientSecretSettingName``
  that must be an existing app setting; ``validation.allowedAudiences``), ``login.tokenStore``, ``httpSettings.requireHttps``.
  The legacy simulator bearer token (``token`` in the view) keeps working.
* **Enforcement** (``evaluate``): the site front door (Function App invoke / Kudu / the offline function host) applies the
  configured action to a request with no valid credential: 302 to the Entra authorize endpoint, 401 or 403, or pass-through.
  ``/.auth/*`` and ``excludedPaths`` bypass. A credential is the legacy token or a JWT bearer whose CLAIMS (exp, aud,
  iss/tid) validate against the configured provider. NOT verified: the JWT signature -- Vyomi's Entra issues opaque tokens
  and has no signing keys -- and there is no interactive browser sign-in flow.
* **Azure OpenAI hookup** (``config/appsettings`` + ``aoaiconnection``): AZURE_OPENAI_* app settings are validated against a real
  Cognitive Services OpenAI/AIServices account in the same state (endpoint host, deployment exists, literal key matches);
  ``aoaiconnection`` PUT {accountId, deploymentName, apiVersion, authMode key|managedIdentity} writes the settings.
"""
from __future__ import annotations

import base64
import json
import re
import time

_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_ISSUER = re.compile(r"^https://(login\.microsoftonline\.com/([0-9a-fA-F-]{36}|common|organizations)(/v2\.0)?|sts\.windows\.net/[0-9a-fA-F-]{36}/?|[\w.-]+\.ciamlogin\.com/[\w.-]+/v2\.0)/?$")
ACTIONS = ("RedirectToLoginPage", "AllowAnonymous", "Return401", "Return403")
AOAI_KEYS = ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_DEPLOYMENT_NAME", "AZURE_OPENAI_API_VERSION")
_API_VER = re.compile(r"^\d{4}-\d{2}-\d{2}(-preview)?$|^v1$")
COG_TYPE = "microsoft.cognitiveservices/accounts"


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def _ok(body=None, status=200):
    return {"status": status, "headers": {}, "body": body, "lro": False}


def _bool(v, d=False):
    if v is None:
        return d
    return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes", "on")


# ── authsettingsV2 ─────────────────────────────────────────────────────────────────────
def default_auth():
    return {"enabled": False, "token": None, "v2": {}}


def _tenant_of(issuer):
    m = re.search(r"([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})", issuer or "")
    return m.group(1).lower() if m else None


def merge_auth(old, new):
    out = dict(old or {})
    for k, v in (new or {}).items():
        out[k] = merge_auth(out.get(k), v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def validate_auth(rec, props, method):
    """None if ok else an error dict. ``props`` is the PUT/PATCH properties bag; PATCH merges over the stored v2 config."""
    cur = (rec.get("_authsettingsv2") or {}).get("v2") or {}
    v2 = merge_auth(cur, props) if method == "PATCH" else dict(props or {})
    plat = v2.get("platform") or {}
    if "enabled" in plat and not isinstance(plat["enabled"], (bool, str)):
        return _err(400, "BadRequest", "platform.enabled must be true or false.")
    gv = v2.get("globalValidation") or {}
    act = gv.get("unauthenticatedClientAction")
    if act is not None and act not in ACTIONS:
        return _err(400, "BadRequest", f"globalValidation.unauthenticatedClientAction '{act}' is not valid. Allowed: {', '.join(ACTIONS)}.")
    for pth in gv.get("excludedPaths") or []:
        if not isinstance(pth, str) or not pth.startswith("/"):
            return _err(400, "BadRequest", f"globalValidation.excludedPaths entry '{pth}' must be a path starting with '/'.")
    providers = v2.get("identityProviders") or {}
    aad = providers.get("azureActiveDirectory")
    if act == "RedirectToLoginPage" and not gv.get("redirectToProvider"):
        v2.setdefault("globalValidation", {})["redirectToProvider"] = "azureactivedirectory" if aad else None
        if not aad:
            return _err(400, "BadRequest", "RedirectToLoginPage needs globalValidation.redirectToProvider and a configured identity provider.")
    rp = gv.get("redirectToProvider")
    if rp and str(rp).lower() != "azureactivedirectory" and not providers.get(rp) and not any(str(k).lower() == str(rp).lower() for k in providers):
        return _err(400, "BadRequest", f"redirectToProvider '{rp}' is not a configured identity provider.")
    if aad is not None:
        reg = aad.get("registration") or {}
        if _bool(plat.get("enabled")) and _bool(aad.get("enabled"), True):
            if not reg.get("clientId"):
                return _err(400, "BadRequest", "identityProviders.azureActiveDirectory.registration.clientId is required.")
            if not _GUID.match(str(reg["clientId"])):
                return _err(400, "BadRequest", f"registration.clientId '{reg['clientId']}' is not a valid application (client) ID GUID.")
            iss = reg.get("openIdIssuerUrl")
            if not iss or not _ISSUER.match(str(iss)):
                return _err(400, "BadRequest", "registration.openIdIssuerUrl must be https://login.microsoftonline.com/{tenant-id}/v2.0 (or sts.windows.net/{tenant-id}/).")
            sn = reg.get("clientSecretSettingName")
            if sn and sn not in (rec.get("_appsettings") or {}):
                return _err(400, "BadRequest", f"registration.clientSecretSettingName '{sn}' is not an application setting on this app; add it first.")
        for a in (aad.get("validation") or {}).get("allowedAudiences") or []:
            if not isinstance(a, str) or not a:
                return _err(400, "BadRequest", "validation.allowedAudiences must be non-empty strings.")
    auth = rec.setdefault("_authsettingsv2", default_auth())
    return {"ok": True, "v2": v2, "auth": auth}


def apply_auth(rec, v2, existing_token_fn):
    auth = rec["_authsettingsv2"]
    auth["v2"] = v2
    auth["enabled"] = _bool((v2.get("platform") or {}).get("enabled"), False)
    if auth["enabled"] and not auth.get("token"):
        auth["token"] = existing_token_fn()


def auth_view(rec):
    auth = rec.get("_authsettingsv2") or default_auth()
    v2 = json.loads(json.dumps(auth.get("v2") or {}))
    v2.setdefault("platform", {})["enabled"] = auth["enabled"]
    if auth["enabled"]:
        v2.setdefault("globalValidation", {}).setdefault("unauthenticatedClientAction", "RedirectToLoginPage")
        v2.setdefault("login", {}).setdefault("tokenStore", {"enabled": False})
        v2.setdefault("httpSettings", {}).setdefault("requireHttps", True)
    v2["token"] = auth["token"] if auth["enabled"] else None
    return v2


def _jwt_claims(tok):
    parts = tok.split(".")
    if len(parts) != 3:
        return None
    try:
        pad = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(pad))
    except Exception:
        return None


def evaluate(rec, headers, path="/", now=None):
    """None = request may proceed; else (status, code, message, response_headers) from the site's Easy Auth."""
    auth = (rec or {}).get("_authsettingsv2") or {}
    if not auth.get("enabled"):
        return None
    path = path or "/"
    if path.startswith("/.auth/"):
        return None
    v2 = auth.get("v2") or {}
    gv = v2.get("globalValidation") or {}
    if any(path == p or (p.endswith("*") and path.startswith(p[:-1])) or path.startswith(p.rstrip("/") + "/") for p in gv.get("excludedPaths") or []):
        return None
    h = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    bearer = h.get("authorization", "")
    tok = bearer[7:] if bearer.lower().startswith("bearer ") else ""
    if tok and tok == auth.get("token"):
        return None
    aad = (v2.get("identityProviders") or {}).get("azureActiveDirectory") or {}
    reg = aad.get("registration") or {}
    problem = None
    if tok:
        claims = _jwt_claims(tok)
        if claims is None:
            problem = "invalid_token: the bearer token is not a JWT"
        else:
            aud = set((aad.get("validation") or {}).get("allowedAudiences") or [])
            if reg.get("clientId"):
                aud |= {reg["clientId"], f"api://{reg['clientId']}"}
            ten = _tenant_of(reg.get("openIdIssuerUrl"))
            if claims.get("exp") is not None and float(claims["exp"]) < (now or time.time()):
                problem = "invalid_token: the token is expired"
            elif aud and claims.get("aud") not in aud:
                problem = f"invalid_token: audience '{claims.get('aud')}' is not allowed"
            elif ten and str(claims.get("tid", "")).lower() != ten and ten not in str(claims.get("iss", "")).lower():
                problem = "invalid_token: the token was issued by a different tenant"
        if problem is None:
            return None
    if gv.get("requireAuthentication") is False:
        return None
    action = gv.get("unauthenticatedClientAction") or "RedirectToLoginPage"
    if action == "AllowAnonymous":
        return None
    if action == "Return403":
        return (403, "Forbidden", problem or "You do not have permission to view this directory or page.", {})
    if action == "Return401" or problem:
        return (401, "Unauthorized", (problem or "You do not have permission to view this directory or page.") + " (Easy Auth)",
                {"www-authenticate": 'Bearer realm="' + str(rec.get("name", "")) + '"'})
    tenant = _tenant_of(reg.get("openIdIssuerUrl")) or "common"
    host = (rec.get("properties") or {}).get("defaultHostName") or f"{rec.get('name')}.azurewebsites.net"
    loc = (f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?client_id={reg.get('clientId', '')}&response_type=code+id_token"
           f"&redirect_uri=https%3A%2F%2F{host}%2F.auth%2Flogin%2Faad%2Fcallback&scope=openid+profile+email")
    return (302, "Found", "Redirecting to the Microsoft Entra sign-in page.", {"location": loc})


# ── Azure OpenAI hookup ────────────────────────────────────────────────────────────────
def _accounts(state):
    return [r for r in state.values() if isinstance(r, dict) and str(r.get("_type", "")).lower() == COG_TYPE
            and r.get("kind") in ("OpenAI", "AIServices")]


def _host(url):
    m = re.match(r"^https://([^/]+)/?", str(url or ""))
    return m.group(1).lower() if m else None


def find_aoai_account(state, endpoint):
    host = _host(endpoint)
    if not host:
        return None
    for a in _accounts(state):
        sd = str((a.get("properties") or {}).get("customSubDomainName") or "").lower()
        if sd and host in (f"{sd}.openai.azure.com", f"{sd}.cognitiveservices.azure.com", f"{sd}.services.ai.azure.com"):
            return a
        for ep in ((a.get("properties") or {}).get("endpoints") or {}).values():
            if _host(ep) == host:
                return a
    return None


def validate_settings(state, rec, incoming):
    """Validate AZURE_OPENAI_* in an app-settings write (``incoming`` = the resulting settings bag). None if ok."""
    s = {k: v for k, v in (incoming or {}).items() if k in AOAI_KEYS}
    if not s:
        return None
    ep = s.get("AZURE_OPENAI_ENDPOINT")
    if not ep:
        return _err(400, "BadRequest", "AZURE_OPENAI_* settings need AZURE_OPENAI_ENDPOINT (https://{resource}.openai.azure.com/).")
    acct = find_aoai_account(state, ep)
    if acct is None:
        return _err(400, "InvalidAzureOpenAIEndpoint", f"AZURE_OPENAI_ENDPOINT '{ep}' does not match any Azure OpenAI / AI Services account.")
    dep = s.get("AZURE_OPENAI_DEPLOYMENT") or s.get("AZURE_OPENAI_DEPLOYMENT_NAME")
    if dep and str(dep).lower() not in (acct.get("_deployments") or {}):
        return _err(400, "DeploymentNotFound", f"The Azure OpenAI deployment '{dep}' does not exist on account '{acct['name']}'.")
    ver = s.get("AZURE_OPENAI_API_VERSION")
    if ver and not _API_VER.match(str(ver)):
        return _err(400, "BadRequest", f"AZURE_OPENAI_API_VERSION '{ver}' is not a valid API version (yyyy-mm-dd[-preview]).")
    key = s.get("AZURE_OPENAI_API_KEY")
    if key and not str(key).startswith("@Microsoft.KeyVault(") and key not in (acct.get("_keys") or {}).values():
        return _err(400, "InvalidAzureOpenAIKey", f"AZURE_OPENAI_API_KEY does not match a key of account '{acct['name']}'. Use a Key Vault reference or one of its keys.")
    return None


def connection_view(state, rec):
    sett = rec.get("_appsettings") or {}
    acct = find_aoai_account(state, sett.get("AZURE_OPENAI_ENDPOINT"))
    if acct is None:
        return None
    dep = sett.get("AZURE_OPENAI_DEPLOYMENT") or sett.get("AZURE_OPENAI_DEPLOYMENT_NAME")
    return {"accountId": acct["id"], "endpoint": sett.get("AZURE_OPENAI_ENDPOINT"), "deploymentName": dep,
            "apiVersion": sett.get("AZURE_OPENAI_API_VERSION"),
            "authMode": "key" if sett.get("AZURE_OPENAI_API_KEY") else "managedIdentity",
            "deploymentExists": bool(dep and str(dep).lower() in (acct.get("_deployments") or {})),
            "armChatPath": f"{acct['id']}/openai/deployments/{dep}/chat/completions" if dep else None}


def handles(rest):
    return rest[0].lower() == "aoaiconnection"


def dispatch(state, rec, rest, method, payload):
    sett = rec.setdefault("_appsettings", {})
    if method == "GET":
        v = connection_view(state, rec)
        return _ok({"properties": v}) if v else _err(404, "ResourceNotFound", "No Azure OpenAI connection is configured on this app.")
    if method == "DELETE":
        for k in AOAI_KEYS:
            sett.pop(k, None)
        return _ok(None, 200)
    if method not in ("PUT", "PATCH"):
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")
    p = ((payload or {}).get("properties") if isinstance(payload, dict) else None) or {}
    aid = str(p.get("accountId") or "")
    acct = state.get(aid.lower())
    if acct is None or str(acct.get("_type", "")).lower() != COG_TYPE or acct.get("kind") not in ("OpenAI", "AIServices"):
        return _err(400, "InvalidAzureOpenAIAccount", f"accountId '{aid}' is not an Azure OpenAI / AI Services account.")
    mode = p.get("authMode") or "key"
    if mode not in ("key", "managedIdentity"):
        return _err(400, "BadRequest", "authMode must be key or managedIdentity.")
    if mode == "managedIdentity" and str((rec.get("identity") or {}).get("type", "None")).lower() in ("none", ""):
        return _err(400, "ManagedIdentityRequired", "authMode managedIdentity needs a system- or user-assigned identity on the app.")
    sd = (acct.get("properties") or {}).get("customSubDomainName")
    if not sd:
        return _err(400, "CustomSubdomainRequired", "The account has no custom subdomain, so it has no OpenAI endpoint.")
    new = {"AZURE_OPENAI_ENDPOINT": f"https://{sd}.openai.azure.com/"}
    if p.get("deploymentName"):
        new["AZURE_OPENAI_DEPLOYMENT"] = p["deploymentName"]
    if p.get("apiVersion"):
        new["AZURE_OPENAI_API_VERSION"] = p["apiVersion"]
    if mode == "key":
        new["AZURE_OPENAI_API_KEY"] = acct["_keys"]["key1"]
    e = validate_settings(state, rec, new)
    if e:
        return e
    if mode == "managedIdentity":
        sett.pop("AZURE_OPENAI_API_KEY", None)
    sett.update(new)
    return _ok({"properties": connection_view(state, rec)})
