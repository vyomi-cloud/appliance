# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Identity Platform / Firebase Auth (identitytoolkit.googleapis.com + securetoken.googleapis.com) — substrate-independent, stdlib only.

Serves the REST surface the Firebase Auth client SDKs and the Firebase Admin SDK speak, so an app can sign users up / in with
email + password, carry custom claims, refresh tokens, and a backend (API Gateway, a function, `google.oauth2.id_token`, PyJWT)
can verify the resulting Google-style ID token with a real library:

  POST /v1/accounts:signUp | signInWithPassword | lookup | update | delete | sendOobCode      (?key=API_KEY; project from the key)
  POST /v1/projects/{p}/accounts | accounts:update | accounts:lookup | accounts:delete | accounts:batchGet   (Admin: create user,
                                                                                    set custom claims via customAttributes)
  POST /v1/token   grant_type=refresh_token (securetoken.googleapis.com; form or JSON)
  GET  /robot/v1/metadata/x509/securetoken@system.gserviceaccount.com   x509 certs {kid: PEM}   (what verify_firebase_token reads)
  GET  /service_accounts/v1/jwk/securetoken@system.gserviceaccount.com  JWKS
  GET  /oauth2/v3/certs | /oauth2/v1/certs                              the same key for accounts.google.com ID tokens (iamcredentials)
  GET  /securetoken.google.com/{p}/.well-known/openid-configuration

ID tokens are real RS256 JWTs: header {alg RS256, kid "vyomi-securetoken-1", typ JWT}; claims iss=https://securetoken.google.com/<project>,
aud=<project>, sub=user_id=<localId>, auth_time/iat/exp (1 h), email, email_verified, firebase{identities, sign_in_provider}, plus the
user's custom claims at the top level (as Firebase does). They verify with `google.oauth2.id_token.verify_firebase_token(certs_url=...)`
and PyJWT against the JWKS.

The signing key is the simulator's one public emulator key (core/gcp_iamcredentials_core, RSA-2048, NOT a secret) and `_CERT_PEM` is a
self-signed X.509 certificate over that same key, so the x509 endpoint hands real libraries a real certificate.
Own code (no open-source engine fits): the Firebase Auth emulator is not in the local google-cloud-cli:emulators image and its
tokens are unsigned alg:none JWTs that `verify_id_token` rejects by design.
Honest limits: email/password + anonymous only (no phone / OAuth providers / MFA / tenants / email-link); sendOobCode is accepted and
records nothing; the Admin SDK's `verify_id_token` fetches certs from a hard-coded Google URL, so use verify_firebase_token(certs_url=...).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import parse_qs, unquote

try:
    from core import gcp_iamcredentials_core as iamc
    from core.gcp_firestore_core import FirestoreResponse
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gcp_iamcredentials_core as iamc  # type: ignore
    from gcp_firestore_core import FirestoreResponse  # type: ignore

KID = "vyomi-securetoken-1"
ID_TOKEN_TTL = 3600
SECURETOKEN_SA = "securetoken@system.gserviceaccount.com"
_RESERVED = {"iss", "aud", "sub", "iat", "exp", "auth_time", "user_id", "firebase", "email", "email_verified", "azp", "nbf", "jti", "nonce"}

# Self-signed X.509 over the emulator key (generated once with `cryptography`; valid 2024-2099). Public, not a secret.
_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIDPTCCAiWgAwIBAgIBATANBgkqhkiG9w0BAQsFADBhMS8wLQYDVQQDDCZzZWN1
cmV0b2tlbkBzeXN0ZW0uZ3NlcnZpY2VhY2NvdW50LmNvbTEuMCwGA1UECgwlVnlv
bWkgc2ltdWxhdG9yIChwdWJsaWMgZW11bGF0b3Iga2V5KTAgFw0yNDAxMDEwMDAw
MDBaGA8yMDk5MTIzMTAwMDAwMFowYTEvMC0GA1UEAwwmc2VjdXJldG9rZW5Ac3lz
dGVtLmdzZXJ2aWNlYWNjb3VudC5jb20xLjAsBgNVBAoMJVZ5b21pIHNpbXVsYXRv
ciAocHVibGljIGVtdWxhdG9yIGtleSkwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAw
ggEKAoIBAQCxCYkEx91EOQssq3j82gh1wxN5s23o5lEztc8IZ21IHyO9KYEpppiC
Aw1bB9BUbdJKj3+4PQYdqPba15/u+lkvtqhhjlcMXM1HqIxxyFJZt0g96kWrvzNy
8Oz4mOt0c47C6HHxwF3l/fOvnsPyVunA1TCF7hVrqUKgNI0K9ODhG0lERCwGR66v
TqyRxoEEx9lu7S0afN/X0EaS5Eam4OJ5awjYu+k6EnwCxC33/UXM0Jb0kuUE4oLM
Qg6AIMT9nayZ0vKhJfaLtXxkNAn9jKevfb32WSHDVkB9Lzjqv3Dh8NLhsAp3Nmep
h0rhMRz8BewOQ5R6NhcrB3jqu4nHli8vAgMBAAEwDQYJKoZIhvcNAQELBQADggEB
AJxVuY+SklbbVLf0qwfPskHijfzOwJ5ExfCEnDygf96285128yawITOMP781x5Fl
nUDUEn679OnAoCmR595VInQwcVMaWMebVUZidAgssr4Nnfai0/ZP3LucASV+OF01
mJV402JZmtw5EsO7L96MMwBraRT3qvVHlLDYDaRCXAcTtzulyMsAFiYweDW4lCD1
tkXJ/vVQ6zBk/cj8slHJ8ucYtcCd6gr4gvss7f7sJtFFtd/HaYUtVskAW13cXz2F
yzeOO7fcDN+ZDtPN4tj8jHjniSSnzXOIXPaFjXWmxWKaS2PvQafDDHwlwxVXwh5t
dpFspWgDs11PkPxKGLvDiBo=
-----END CERTIFICATE-----
"""

_JWKS_PATHS = re.compile(r"^/(robot/v1/metadata/(x509|jwk)/[^/]+|service_accounts/v1/(jwk|metadata/x509)/[^/]+|oauth2/v[13]/certs|oauth2/v1/certs)$")
_WELLKNOWN = re.compile(r"^/securetoken\.google\.com/([^/]+)/\.well-known/openid-configuration$")
_ACCT = re.compile(r"^/v[12]/(?:projects/([^/]+)/)?accounts(?::([A-Za-z]+))?$")


_HOST_PREFIX = re.compile(r"^/(identitytoolkit|securetoken)\.googleapis\.com(?=/)")   # Firebase Admin SDK in emulator mode (FIREBASE_AUTH_EMULATOR_HOST)


def _norm(path: str) -> str:
    return _HOST_PREFIX.sub("", path, count=1)


def handles(path: str, body: bytes = b"") -> bool:
    p = _norm(path.split("?", 1)[0])
    if _JWKS_PATHS.match(p) or _WELLKNOWN.match(p) or _ACCT.match(p):
        return True
    if p == "/v1/token":   # also the STS token-exchange path: only the refresh grant is ours
        return _grant_type(body) == "refresh_token"
    return False


def is_certs_path(p: str) -> bool:
    return bool(_JWKS_PATHS.match(p.split("?", 1)[0]))


def _grant_type(body: bytes) -> str:
    try:
        t = bytes(body or b"").decode("utf-8", "replace").strip()
        if t.startswith("{"):
            return str(json.loads(t).get("grantType") or json.loads(t).get("grant_type") or "")
        return (parse_qs(t).get("grant_type") or [""])[0]
    except Exception:
        return ""


def _json(status, obj, headers=None):
    return FirestoreResponse(status, {"content-type": "application/json", **(headers or {})}, json.dumps(obj).encode())


def _err(status, message, reason="invalid"):
    """The Identity Toolkit error envelope: {"error": {"code", "message": "EMAIL_EXISTS", "errors": [...]}}."""
    return _json(status, {"error": {"code": status, "message": message, "errors": [{"message": message, "domain": "global", "reason": reason}]}})


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── state (store.ext["idp"], JSON-safe so the monitoring store persists it) ─────────────────────────
def _state(store) -> dict:
    if getattr(store, "ext", None) is None:
        store.ext = {}
    st = store.ext.setdefault("idp", {})
    st.setdefault("users", {})     # project -> localId -> user
    st.setdefault("refresh", {})   # refresh token -> [project, localId]
    return st


def _users(store, project) -> dict:
    return _state(store)["users"].setdefault(project, {})


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 20000).hex()


def _ms(t=None) -> str:
    return str(int((t if t is not None else time.time()) * 1000))


# ── tokens ──────────────────────────────────────────────────────────────────────────────────────────
def mint_id_token(project: str, user: dict, now=None, provider="password") -> str:
    now = int(now if now is not None else time.time())
    ident = {"email": [user["email"]]} if user.get("email") else {}
    claims = {"iss": "https://securetoken.google.com/" + project, "aud": project, "auth_time": now, "user_id": user["localId"],
              "sub": user["localId"], "iat": now, "exp": now + ID_TOKEN_TTL}
    if user.get("displayName"):
        claims["name"] = user["displayName"]
    if user.get("email"):
        claims["email"] = user["email"]
        claims["email_verified"] = bool(user.get("emailVerified"))
    for k, v in (user.get("claims") or {}).items():
        if k not in _RESERVED:
            claims[k] = v
    claims["firebase"] = {"identities": ident, "sign_in_provider": "anonymous" if provider == "anonymous" else provider}
    signing_input = (_b64u(json.dumps({"alg": "RS256", "kid": KID, "typ": "JWT"}, separators=(",", ":")).encode()) + "." +
                     _b64u(json.dumps(claims, separators=(",", ":")).encode()))
    return signing_input + "." + _b64u(iamc.rsa_sign(signing_input.encode()))


def verify_id_token(token: str, now=None):
    """-> (project, claims) for an unexpired token signed by this core's key, else None."""
    try:
        h, p, s = token.split(".")
        if not iamc.rsa_verify((h + "." + p).encode(), _b64u_dec(s)):
            return None
        claims = json.loads(_b64u_dec(p))
        if claims.get("exp", 0) < (now if now is not None else time.time()):
            return None
        return str(claims.get("aud")), claims
    except Exception:
        return None


def _session(store, project, user, returning=True, provider="password"):
    refresh = "AMf-vB" + secrets.token_urlsafe(48)
    _state(store)["refresh"][refresh] = [project, user["localId"]]
    user["lastLoginAt"] = _ms()
    return {"idToken": mint_id_token(project, user, provider=provider), "refreshToken": refresh, "expiresIn": str(ID_TOKEN_TTL)}


def _view(user: dict) -> dict:
    out = {"localId": user["localId"], "emailVerified": bool(user.get("emailVerified")), "validSince": user.get("validSince", "0"),
           "lastLoginAt": user.get("lastLoginAt", user["createdAt"]), "createdAt": user["createdAt"], "lastRefreshAt": _now_iso()}
    if user.get("email"):
        out["email"] = user["email"]
        out["passwordHash"] = user.get("pw", "")[:12]
        out["passwordUpdatedAt"] = float(user.get("pwAt") or 0)
        out["providerUserInfo"] = [{"providerId": "password", "federatedId": user["email"], "email": user["email"], "rawId": user["email"]}]
    for k in ("displayName", "photoUrl"):
        if user.get(k):
            out[k] = user[k]
    if user.get("disabled"):
        out["disabled"] = True
    if user.get("claims"):
        out["customAttributes"] = json.dumps(user["claims"])
    return out


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _find_email(store, project, email):
    e = (email or "").lower()
    return next((u for u in _users(store, project).values() if (u.get("email") or "").lower() == e), None)


def _new_user(store, project, email, password, extra=None):
    now = _ms()
    u = {"localId": secrets.token_hex(14)[:28], "createdAt": now, "lastLoginAt": now, "emailVerified": False, "claims": {}}
    if email:
        u["email"] = email
        u["salt"] = secrets.token_hex(8)
        u["pw"] = _hash(password, u["salt"])
        u["pwAt"] = time.time()
    u.update(extra or {})
    _users(store, project)[u["localId"]] = u
    return u


# ── dispatch ────────────────────────────────────────────────────────────────────────────────────────
def _certs_response(path, ctx):
    p = path.split("?", 1)[0]
    kids = [KID]
    try:   # service-account ID tokens (iamcredentials) carry a per-account kid; one key signs them all
        iss = ctx.get("iamc_store")
        for rec in (getattr(iss, "issued", None) or {}).values():
            kids.append(iamc.key_id(rec["serviceAccount"]))
    except Exception:
        pass
    kids = list(dict.fromkeys(kids))
    hdr = {"cache-control": "public, max-age=3600"}
    if "x509" in p or p.endswith("/oauth2/v1/certs"):
        return _json(200, {k: _CERT_PEM for k in kids}, hdr)
    jwk = iamc.public_jwk()
    return _json(200, {"keys": [dict(jwk, kid=k) for k in kids]}, hdr)


def dispatch(store, method, path, query=None, headers=None, body=b"", ctx=None):
    ctx, query, method = ctx or {}, dict(query or {}), method.upper()
    p = _norm(path.split("?", 1)[0])
    if "?" in path and not query:
        query = {k: v[0] for k, v in parse_qs(path.split("?", 1)[1]).items()}
    if _JWKS_PATHS.match(p):
        return _certs_response(p, ctx)
    m = _WELLKNOWN.match(p)
    if m:
        proj = unquote(m.group(1))
        base = ctx.get("base") or ""
        return _json(200, {"issuer": "https://securetoken.google.com/" + proj, "jwks_uri": base + "/service_accounts/v1/jwk/" + SECURETOKEN_SA,
                           "response_types_supported": ["id_token"], "subject_types_supported": ["public"], "id_token_signing_alg_values_supported": ["RS256"]})
    raw = bytes(body or b"")
    try:
        if p == "/v1/token":
            t = raw.decode("utf-8", "replace").strip()
            data = json.loads(t) if t.startswith("{") else {k: v[0] for k, v in parse_qs(t).items()}
        else:
            data = json.loads(raw.decode() or "{}") if raw else {}
        if not isinstance(data, dict):
            raise ValueError
    except Exception:
        return _err(400, "INVALID_JSON_PAYLOAD")
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    if p == "/v1/token":
        return _refresh(store, data)
    m = _ACCT.match(p)
    if not m or method not in ("POST", "GET"):
        return _err(404, "NOT_FOUND")
    proj_in_path, verb = m.group(1), m.group(2) or ""
    project = proj_in_path or _project_for(query, h, ctx)
    admin = bool(proj_in_path)
    try:
        if verb == "signUp" or (admin and not verb):
            return _sign_up(store, project, data, admin)
        if verb == "signInWithPassword":
            return _sign_in(store, project, data)
        if verb == "lookup":
            return _lookup(store, project, data, admin)
        if verb == "update":
            return _update(store, project, data, admin)
        if verb == "delete":
            return _delete(store, project, data, admin)
        if verb == "batchGet":
            us = list(_users(store, project).values())
            return _json(200, {"kind": "identitytoolkit#DownloadAccountResponse", "users": [_view(u) for u in us]})
        if verb == "sendOobCode":
            return _json(200, {"kind": "identitytoolkit#GetOobConfirmationCodeResponse", "email": data.get("email", "")})
    except _Err as e:
        return _err(400, e.args[0])
    return _err(404, "NOT_FOUND")


class _Err(Exception):
    pass


def _project_for(query, h, ctx):
    key = query.get("key") or h.get("x-goog-api-key")
    fn = ctx.get("project_for_key")
    if key and fn:
        try:
            pj = fn(key)
            if pj:
                return pj
        except Exception:
            pass
    return h.get("x-goog-user-project") or ctx.get("default_project") or "local-project"


def _sign_up(store, project, data, admin):
    email, password = (data.get("email") or "").strip(), data.get("password") or ""
    if email:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise _Err("INVALID_EMAIL")
        if len(password) < 6:
            raise _Err("WEAK_PASSWORD : Password should be at least 6 characters")
        if _find_email(store, project, email):
            raise _Err("EMAIL_EXISTS")
    extra = {k: data[k] for k in ("displayName", "photoUrl") if data.get(k)}
    if admin:
        if data.get("localId"):
            extra["localId"] = data["localId"]
        extra["emailVerified"] = bool(data.get("emailVerified"))
        if data.get("customAttributes"):
            extra["claims"] = _claims(data["customAttributes"])
        if data.get("disabled"):
            extra["disabled"] = True
    u = _new_user(store, project, email, password, extra)
    if admin:
        return _json(200, {"kind": "identitytoolkit#SignupNewUserResponse", "localId": u["localId"], "email": u.get("email", "")})
    sess = _session(store, project, u, provider="password" if email else "anonymous")
    return _json(200, {"kind": "identitytoolkit#SignupNewUserResponse", "email": u.get("email", ""), "localId": u["localId"], **sess})


def _sign_in(store, project, data):
    u = _find_email(store, project, data.get("email"))
    if not u or not hmac.compare_digest(u.get("pw", ""), _hash(data.get("password") or "", u.get("salt", ""))):
        raise _Err("INVALID_LOGIN_CREDENTIALS")
    if u.get("disabled"):
        raise _Err("USER_DISABLED")
    sess = _session(store, project, u)
    return _json(200, {"kind": "identitytoolkit#VerifyPasswordResponse", "localId": u["localId"], "email": u["email"], "displayName": u.get("displayName", ""),
                       "registered": True, **sess})


def _from_token(store, data):
    v = verify_id_token(data.get("idToken") or "")
    if not v:
        raise _Err("INVALID_ID_TOKEN")
    project, claims = v
    u = _users(store, project).get(claims.get("user_id") or claims.get("sub"))
    if not u:
        raise _Err("USER_NOT_FOUND")
    return project, u


def _lookup(store, project, data, admin):
    if data.get("idToken"):
        _p, u = _from_token(store, data)
        found = [u]
    else:
        us = _users(store, project)
        found = [us[i] for i in (data.get("localId") or []) if i in us]
        for e in data.get("email") or []:
            u = _find_email(store, project, e)
            if u and u not in found:
                found.append(u)
    if not found and not data.get("idToken"):
        return _json(200, {"kind": "identitytoolkit#GetAccountInfoResponse"})
    return _json(200, {"kind": "identitytoolkit#GetAccountInfoResponse", "users": [_view(u) for u in found]})


def _claims(raw):
    try:
        c = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        if not isinstance(c, dict):
            raise ValueError
    except Exception:
        raise _Err("INVALID_CLAIMS")
    bad = [k for k in c if k in _RESERVED]
    if bad:
        raise _Err("FORBIDDEN_CLAIM : " + bad[0])
    return c


def _update(store, project, data, admin):
    if data.get("idToken"):
        project, u = _from_token(store, data)
    else:
        u = _users(store, project).get(data.get("localId") or "")
        if not u:
            raise _Err("USER_NOT_FOUND")
    if data.get("email"):
        other = _find_email(store, project, data["email"])
        if other and other is not u:
            raise _Err("EMAIL_EXISTS")
        u["email"] = data["email"]
        u.setdefault("salt", secrets.token_hex(8))
    if data.get("password"):
        if len(data["password"]) < 6:
            raise _Err("WEAK_PASSWORD : Password should be at least 6 characters")
        u["salt"] = u.get("salt") or secrets.token_hex(8)
        u["pw"] = _hash(data["password"], u["salt"])
        u["pwAt"] = time.time()
    for k in ("displayName", "photoUrl"):
        if k in data:
            u[k] = data[k]
    if "emailVerified" in data:
        u["emailVerified"] = bool(data["emailVerified"])
    if "disableUser" in data:
        u["disabled"] = bool(data["disableUser"])
    if "customAttributes" in data:
        u["claims"] = _claims(data["customAttributes"] or "{}")
    for a in data.get("deleteAttribute") or []:
        u.pop({"DISPLAY_NAME": "displayName", "PHOTO_URL": "photoUrl"}.get(a, ""), None)
    out = {"kind": "identitytoolkit#SetAccountInfoResponse", "localId": u["localId"], "email": u.get("email", ""),
           "displayName": u.get("displayName", ""), "emailVerified": bool(u.get("emailVerified")),
           "providerUserInfo": _view(u).get("providerUserInfo", [])}
    if data.get("returnSecureToken") and data.get("idToken"):
        out.update(_session(store, project, u))
    return _json(200, out)


def _delete(store, project, data, admin):
    if data.get("idToken"):
        project, u = _from_token(store, data)
    else:
        u = _users(store, project).get(data.get("localId") or "")
        if not u:
            raise _Err("USER_NOT_FOUND")
    _users(store, project).pop(u["localId"], None)
    rt = _state(store)["refresh"]
    for k in [k for k, v in rt.items() if v[1] == u["localId"]]:
        rt.pop(k, None)
    return _json(200, {"kind": "identitytoolkit#DeleteAccountResponse"})


def _refresh(store, data):
    tok = data.get("refresh_token") or data.get("refreshToken") or ""
    ent = _state(store)["refresh"].get(tok)
    u = ent and _users(store, ent[0]).get(ent[1])
    if not u or u.get("disabled"):
        return _err(400, "INVALID_REFRESH_TOKEN")
    idt = mint_id_token(ent[0], u, provider="password" if u.get("email") else "anonymous")
    return _json(200, {"access_token": idt, "expires_in": str(ID_TOKEN_TTL), "token_type": "Bearer", "refresh_token": tok,
                       "id_token": idt, "user_id": u["localId"], "project_id": ent[0]})
