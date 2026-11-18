# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Entra ID token issuance: REAL RS256 JWTs + OIDC discovery + JWKS (substrate-free, pure Python; Pyodide-loadable).

Before this module the simulator's token endpoint returned an opaque ``vyomi.<hex>`` string, so no real library could use the
token: APIM ``validate-jwt`` rejected it, ``PyJWT``/``msal`` could not decode it and there was no JWKS. Now every grant of
``core/azure_graph_core`` (client_credentials, password/ROPC, authorization_code, refresh_token; v1 ``/oauth2/token`` and v2
``/oauth2/v2.0/token``) returns a signed JWT with the claims real Entra puts in it, and the keys that verify it are published at
the standard URLs:

  GET /{tenant}/v2.0/.well-known/openid-configuration   (v2 issuer https://login.microsoftonline.com/{tid}/v2.0)
  GET /{tenant}/.well-known/openid-configuration        (v1 issuer https://sts.windows.net/{tid}/)
  GET /{tenant}/discovery/v2.0/keys  |  /{tenant}/discovery/keys  |  /discovery/v2.0/keys  |  /common/discovery/instance

Signing: the simulator's one fixed RSA-2048 key (pure-Python RS256, ``core/gcp_iamcredentials_core.rsa_sign``), published with a
distinct Entra ``kid``. A fixed key is deliberate (tokens survive restarts, JWKS is stable, works in the browser build). It is a
SIMULATOR key: never a secret. Honest limits: no ``x5c`` certificate chain in the JWKS (the JWK ``n``/``e`` is what PyJWT, msal,
azure-identity and APIM validate against); ``aud`` is the resource exactly as requested (real Entra rewrites custom-API audiences
to the app GUID for v2 tokens); no claims-challenge/CAE, no optional-claims configuration.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid

V2 = "https://login.microsoftonline.com/{tid}/v2.0"
V1 = "https://sts.windows.net/{tid}/"
OIDC_SCOPES = {"openid", "profile", "email", "offline_access"}
LIFETIME = 3599


def _iamc():
    try:
        from core import gcp_iamcredentials_core as m
    except ImportError:   # pragma: no cover - Pyodide flat layout
        import gcp_iamcredentials_core as m  # type: ignore
    return m


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def kid() -> str:
    return b64u(hashlib.sha1(b"vyomi-entra-signing-key").digest())[:27]


def issuer(tid: str, v2: bool = True) -> str:
    return (V2 if v2 else V1).format(tid=tid)


def jwks() -> dict:
    jwk = dict(_iamc().public_jwk())
    jwk["kid"] = kid()
    jwk["x5t"] = kid()
    jwk.pop("alg", None)
    jwk["issuer"] = V2
    return {"keys": [jwk]}


def openid_config(base: str, tid: str, v2: bool = True) -> dict:
    """``base`` = the externally visible origin of this simulator (scheme://host:port), no trailing slash. Every endpoint points back
    at the simulator; ``issuer`` is the real Entra value (that is what tokens carry), so validators compare ``iss`` with it."""
    b = base.rstrip("/")
    t = "{tenantid}"
    ep = f"{b}/{tid}"
    doc = {
        "token_endpoint": f"{ep}/oauth2/v2.0/token" if v2 else f"{ep}/oauth2/token",
        "token_endpoint_auth_methods_supported": ["client_secret_post", "private_key_jwt", "client_secret_basic"],
        "jwks_uri": f"{ep}/discovery/v2.0/keys" if v2 else f"{ep}/discovery/keys",
        "response_modes_supported": ["query", "fragment", "form_post"],
        "subject_types_supported": ["pairwise"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "response_types_supported": ["code", "id_token", "code id_token", "id_token token"],
        "scopes_supported": ["openid", "profile", "email", "offline_access"],
        "issuer": issuer(tid, v2),
        "request_uri_parameter_supported": False,
        "userinfo_endpoint": f"{b}/v1.0/me",
        "authorization_endpoint": f"{ep}/oauth2/v2.0/authorize" if v2 else f"{ep}/oauth2/authorize",
        "device_authorization_endpoint": f"{ep}/oauth2/v2.0/devicecode",
        "http_logout_supported": True,
        "frontchannel_logout_supported": True,
        "end_session_endpoint": f"{ep}/oauth2/v2.0/logout",
        "claims_supported": ["sub", "iss", "cloud_instance_name", "cloud_instance_host_name", "cloud_graph_host_name", "msgraph_host",
                             "aud", "exp", "iat", "auth_time", "acr", "nonce", "preferred_username", "name", "tid", "ver", "at_hash",
                             "c_hash", "email"],
        "kerberos_endpoint": f"{ep}/kerberos",
        "tenant_region_scope": "NA",
        "cloud_instance_name": "microsoftonline.com",
        "cloud_graph_host_name": "graph.windows.net",
        "msgraph_host": "graph.microsoft.com",
        "rbac_url": "https://pas.windows.net",
    }
    _ = t
    return doc


def instance_discovery(base: str, tid: str = "common") -> dict:
    return {"tenant_discovery_endpoint": f"{base.rstrip('/')}/{tid}/v2.0/.well-known/openid-configuration", "api-version": "1.1",
            "metadata": []}


def split_scope(scope: str):
    """'api://x/Read api://x/Write openid' -> (resource 'api://x', ['Read','Write'], oidc scopes). '.default' stays as the name."""
    res, names, oidc = "", [], []
    for s in (scope or "").split():
        if s.lower() in OIDC_SCOPES:
            oidc.append(s.lower())
            continue
        if "/" in s:
            r, _, n = s.rpartition("/")
        else:
            r, n = "", s
        res = res or r
        names.append(n)
    return res, names, oidc


def _sign(claims: dict, hdr_extra=None) -> str:
    hdr = {"typ": "JWT", "alg": "RS256", "kid": kid(), "x5t": kid()}
    hdr.update(hdr_extra or {})
    si = (b64u(json.dumps(hdr, separators=(",", ":")).encode()) + "." + b64u(json.dumps(claims, separators=(",", ":")).encode()))
    return si + "." + b64u(_iamc().rsa_sign(si.encode()))


def access_token(*, tid: str, v2: bool, aud: str, client_id: str, now: float = None, lifetime: int = LIFETIME,
                 oid: str = "", roles=None, scp=None, user: dict = None, nonce: str = None) -> tuple:
    """-> (jwt, claims). ``user`` = {"id","upn","name","given_name","family_name"} for delegated tokens, None for app-only."""
    now = int(time.time() if now is None else now)
    iss = issuer(tid, v2)
    c = {"aud": aud, "iss": iss, "iat": now, "nbf": now, "exp": now + lifetime, "aio": b64u(uuid.uuid4().bytes + uuid.uuid4().bytes)}
    if v2:
        c.update({"azp": client_id, "azpacr": "0" if user else "1"})
    else:
        c.update({"appid": client_id, "appidacr": "0" if user else "1", "idp": iss})
    if user:
        c["oid"] = user["id"]
        c["sub"] = hashlib.sha256((client_id + user["id"]).encode()).hexdigest()[:43]
        c["name"] = user.get("name") or user["upn"]
        c["upn"] = user["upn"]
        if v2:
            c["preferred_username"] = user["upn"]
        else:
            c["unique_name"] = user["upn"]
            c["family_name"] = user.get("family_name", "")
            c["given_name"] = user.get("given_name", "")
            c["ipaddr"] = "127.0.0.1"
        if scp:
            c["scp"] = " ".join(scp)
    else:
        c["oid"] = oid
        c["sub"] = oid
    if roles:
        c["roles"] = list(roles)
    c.update({"rh": b64u(uuid.uuid4().bytes)[:22] + ".", "tid": tid, "uti": b64u(uuid.uuid4().bytes)[:22], "ver": "2.0" if v2 else "1.0"})
    if nonce:
        c["nonce"] = nonce
    return _sign(c), c


def id_token(*, tid: str, client_id: str, user: dict, now: float = None, nonce: str = None, lifetime: int = LIFETIME) -> str:
    now = int(time.time() if now is None else now)
    c = {"aud": client_id, "iss": issuer(tid, True), "iat": now, "nbf": now, "exp": now + lifetime, "name": user.get("name") or user["upn"],
         "oid": user["id"], "preferred_username": user["upn"], "rh": b64u(uuid.uuid4().bytes)[:22] + ".",
         "sub": hashlib.sha256((client_id + user["id"]).encode()).hexdigest()[:43], "tid": tid, "uti": b64u(uuid.uuid4().bytes)[:22], "ver": "2.0"}
    if nonce:
        c["nonce"] = nonce
    return _sign(c)


def client_info(oid: str, tid: str) -> str:
    return b64u(json.dumps({"uid": oid, "utid": tid}, separators=(",", ":")).encode())


def decode(token: str):
    """-> (header, claims) without verifying, or None."""
    try:
        h, p, _ = token.split(".")
        return json.loads(b64u_dec(h)), json.loads(b64u_dec(p))
    except Exception:
        return None


def verify(token: str) -> bool:
    """True iff ``token`` is RS256, carries the Entra kid and the signature checks against the simulator key (pure Python, no network)."""
    try:
        hdr, _ = decode(token)
        if hdr.get("alg") != "RS256" or hdr.get("kid") != kid():
            return False
        h, p, sig = token.split(".")
        return bool(_iamc().rsa_verify(f"{h}.{p}".encode(), b64u_dec(sig)))
    except Exception:
        return False
