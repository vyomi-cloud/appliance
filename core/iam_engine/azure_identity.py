"""Azure managed identities: the IMDS token endpoint and the federated-identity-credential token exchange (pure Python, Pyodide-safe).

  GET /metadata/identity/oauth2/token?resource=..&client_id|object_id|msi_res_id=..      (header Metadata: true)     the VM / App Service IMDS call
  POST /{tenant}/oauth2[/v2.0]/token  client_credentials + client_assertion (jwt-bearer)                            workload identity federation

REAL: identities are the ARM records of the space (Microsoft.ManagedIdentity/userAssignedIdentities with their real clientId / principalId, and
any resource whose identity.type includes SystemAssigned). The IMDS call needs the `Metadata: true` header and a `resource`, selects the identity by
client_id / object_id / msi_res_id (or the single identity when only one exists, or `x-vyomi-resource-id` naming the calling VM / app for its system
identity), and returns the IMDS JSON ({access_token, client_id, expires_in, expires_on, not_before, resource, token_type}). The token is the same
real RS256 JWT the Entra token endpoint issues (azure_entra_tokens_core), carrying oid / appid / idtyp=app / xms_mirid, so RBAC evaluates it as that
identity (X-Cloudlearn-Principal not needed). The assertion exchange checks the user-assigned identity's federatedIdentityCredentials: issuer + subject
must match one and the assertion audience must be in its `audiences` (default api://AzureADTokenExchange); an expired assertion and a missing match
fail with the AADSTS70021 / AADSTS700024 messages.

APPROXIMATED: the assertion's signature is NOT verified (no JWKS egress); `x-vyomi-resource-id` stands in for 'which VM is calling' (the real IMDS is
link-local to its VM); managed identities of the Entra directory (service principal objects) are not created, the principalId is the ARM one."""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.parse

UAMI = "microsoft.managedidentity/userassignedidentities"
FIC = "microsoft.managedidentity/userassignedidentities/federatedidentitycredentials"
DEFAULT_AUDIENCE = "api://AzureADTokenExchange"
TENANT_FALLBACK = "00000000-0000-0000-0000-000000000000"


def _tok():
    try:
        from core import azure_entra_tokens_core as m
    except ImportError:   # pragma: no cover
        import azure_entra_tokens_core as m  # type: ignore
    return m


def arm_records():
    """The Azure ARM record map of the active space (Mesh: the ARM provider's map; Nano: the in-browser ARM core's state)."""
    try:
        from core import app_context as ctx
        from providers import azure_services
        tok = ctx.REQUEST_PROVIDER.set("azure")
        try:
            st = azure_services._state
            return st._target() if hasattr(st, "_target") else st
        finally:
            ctx.REQUEST_PROVIDER.reset(tok)
    except ImportError:
        from core import nano_registry
        return getattr(nano_registry.get().get("az_arm"), "state", None)


def _type(rec):
    return str(rec.get("_type") or rec.get("type") or "").lower()


def identities(arm):
    out = []
    for rec in list((arm or {}).values()):
        if not isinstance(rec, dict):
            continue
        p = rec.get("properties") or {}
        if _type(rec) == UAMI and p.get("principalId"):
            out.append({"kind": "user", "id": rec.get("id", ""), "name": rec.get("name", ""), "clientId": p.get("clientId") or "",
                        "principalId": p["principalId"], "tenantId": p.get("tenantId") or TENANT_FALLBACK})
        ident = rec.get("identity") or {}
        if "systemassigned" in str(ident.get("type") or "").lower().replace(" ", "") and ident.get("principalId"):
            out.append({"kind": "system", "id": rec.get("id", ""), "name": rec.get("name", ""), "clientId": ident.get("clientId") or ident["principalId"],
                        "principalId": ident["principalId"], "tenantId": ident.get("tenantId") or TENANT_FALLBACK})
    return out


def find_identity(arm, client_id=None, object_id=None, mi_res_id=None, resource_id=None):
    ids = identities(arm)
    low = lambda s: str(s or "").lower()                                    # noqa: E731
    if client_id:
        return next((i for i in ids if low(i["clientId"]) == low(client_id)), None)
    if object_id:
        return next((i for i in ids if low(i["principalId"]) == low(object_id)), None)
    if mi_res_id:
        return next((i for i in ids if low(i["id"]) == low(mi_res_id)), None)
    if resource_id:                                                         # the calling VM / app: its system-assigned identity, else its single user-assigned one
        sysi = next((i for i in ids if i["kind"] == "system" and low(i["id"]) == low(resource_id)), None)
        if sysi:
            return sysi
        rec = (arm or {}).get(low(resource_id)) or {}
        ua = list(((rec.get("identity") or {}).get("userAssignedIdentities") or {}))
        if len(ua) == 1:
            return next((i for i in ids if low(i["id"]) == low(ua[0])), None)
        return None
    return ids[0] if len(ids) == 1 else None


def _mint(identity, resource, v2=False, lifetime=86399, extra=None):
    m = _tok()
    jwt, claims = m.access_token(tid=identity["tenantId"], v2=v2, aud=resource, client_id=identity["clientId"] or identity["principalId"],
                                 oid=identity["principalId"], lifetime=lifetime)
    claims = dict(claims, idtyp="app", xms_mirid=identity["id"], xms_az_rid=identity["id"])
    if extra:
        claims.update(extra)
    return m._sign(claims), claims


# ------------------------------------------------------------------ IMDS
def _q(query):
    if isinstance(query, str):
        query = {k: v[0] for k, v in urllib.parse.parse_qs(query.lstrip("?"), keep_blank_values=True).items()}
    return {str(k).lower(): (v[0] if isinstance(v, list) and v else v) for k, v in (query or {}).items()}


def match_imds(method, path):
    return str(method).upper() == "GET" and str(path or "").split("?", 1)[0].rstrip("/") == "/metadata/identity/oauth2/token"


def imds_token(arm, query, headers):
    """-> (status, json)."""
    h = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    q = _q(query)
    if h.get("metadata", "").lower() != "true":
        return 400, {"error": "invalid_request", "error_description": "Required metadata header not specified or not correct"}
    if h.get("x-forwarded-for"):
        return 403, {"error": "invalid_request", "error_description": "Forwarded requests are not permitted"}
    resource = q.get("resource")
    if not resource:
        return 400, {"error": "invalid_request", "error_description": "Required query variable 'resource' is missing"}
    ident = find_identity(arm, q.get("client_id"), q.get("object_id"), q.get("msi_res_id") or q.get("mi_res_id"), h.get("x-vyomi-resource-id"))
    if ident is None:
        return 400, {"error": "invalid_request", "error_description": "Identity not found"}
    jwt, c = _mint(ident, resource)
    return 200, {"access_token": jwt, "client_id": ident["clientId"], "expires_in": str(c["exp"] - c["iat"]), "expires_on": str(c["exp"]),
                 "ext_expires_in": str(c["exp"] - c["iat"]), "not_before": str(c["nbf"]), "resource": resource, "token_type": "Bearer"}


# ------------------------------------------------------------------ federated assertion exchange
def _claims(jwt):
    parts = str(jwt or "").split(".")
    if len(parts) != 3:
        return None
    try:
        d = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def federated_credentials(arm, identity):
    pre = identity["id"].lower() + "/federatedidentitycredentials/"
    return [r for k, r in (arm or {}).items() if isinstance(r, dict) and str(k).startswith(pre)]


def federated_exchange(arm, form, tid, v2):
    """-> None when `client_id` is not a managed identity of this space (the caller falls through to app registrations), else (status, json)."""
    ident = find_identity(arm, client_id=form.get("client_id"))
    if ident is None or ident["kind"] != "user":
        return None
    c = _claims(form.get("client_assertion"))
    if c is None:
        return 400, {"error": "invalid_client", "error_description": "AADSTS50027: JWT token is invalid or malformed."}
    now = time.time()
    if isinstance(c.get("exp"), (int, float)) and c["exp"] < now:
        return 400, {"error": "invalid_client", "error_description": "AADSTS700024: Client assertion is not within its valid time range. "
                     f"Current time: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))}, assertion valid from "
                     f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(c.get('nbf') or c.get('iat') or 0))}, expiry time of assertion "
                     f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(c['exp']))}."}
    iss, sub = str(c.get("iss") or ""), str(c.get("sub") or "")
    auds = [str(a) for a in (c["aud"] if isinstance(c.get("aud"), list) else [c.get("aud")]) if a]
    hit = None
    for r in federated_credentials(arm, ident):
        p = r.get("properties") or {}
        if str(p.get("issuer") or "") == iss and str(p.get("subject") or "") == sub and \
                any(a in (p.get("audiences") or [DEFAULT_AUDIENCE]) for a in auds):
            hit = r
            break
    if hit is None:
        return 400, {"error": "invalid_request", "error_description":
                     f"AADSTS70021: No matching federated identity record found for presented assertion. Assertion Issuer: '{iss}'. "
                     f"Assertion Subject: '{sub}'. Assertion Audience: '{auds[0] if auds else ''}'."}
    scope = str(form.get("scope") or form.get("resource") or "https://management.azure.com/.default")
    resource = scope[:-len("/.default")] if scope.endswith("/.default") else scope
    jwt, cl = _mint(ident, resource, v2=bool(v2), lifetime=3599, extra=None)
    return 200, {"token_type": "Bearer", "expires_in": 3599, "ext_expires_in": 3599, "access_token": jwt}
