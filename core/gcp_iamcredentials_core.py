"""GCP IAM Service Account Credentials core — substrate-independent. Speaks the native
**IAM Credentials REST API v1** (`iamcredentials.googleapis.com`) so the native
`google-cloud-iamcredentials` SDKs and `gcloud --impersonate-service-account` work
unchanged against it (point them at the endpoint via api_endpoint /
api_endpoint_overrides/iamcredentials).

NO fastapi / google-cloud / socket / subprocess imports → loads under Pyodide, so the
SAME file runs offline and in Nano.

Resource (Discovery doc `iamcredentials/v1`): `projects/-/serviceAccounts/{email|uniqueId}`
Methods: generateAccessToken, generateIdToken, signBlob, signJwt (custom `:verb`
methods). Errors use the Google shape `{"error":{"code","message","status"}}`
(INVALID_ARGUMENT, PERMISSION_DENIED, NOT_FOUND).

The `-` project wildcard is mandatory, as in the real API. Whether a service account
exists is decided by the optional `resolver(email_or_unique_id) -> email | None` hook
the caller passes to `dispatch()` (the wire router / Nano adapter look it up in the IAM
core); without a resolver any well-formed service-account email is accepted. Unknown
accounts (and unknown delegates) answer 403 PERMISSION_DENIED exactly like Google,
which does not reveal whether the account exists.

Signing is real RS256 (PKCS#1 v1.5 / SHA-256) in pure Python with one fixed
emulator key, so ID tokens, signed JWTs and signed blobs verify against `public_jwk()`.
This key is public and for the emulator only. Every issued credential is also recorded
(never the secret token itself) in `store.issued`, which backs the console's
"Issued credentials" grid.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# ── emulator signing key (RSA-2048, public, not a secret) ────────────────────
_N = int(
    "b1098904c7dd44390b2cab78fcda0875c31379b36de8e65133b5cf08676d481f23bd298129a69882030d5b07d0546dd2"
    "4a8f7fb83d061da8f6dad79feefa592fb6a8618e570c5ccd47a88c71c85259b7483dea45abbf3372f0ecf898eb74738e"
    "c2e871f1c05de5fdf3af9ec3f256e9c0d53085ee156ba942a0348d0af4e0e11b4944442c0647aeaf4eac91c68104c7d9"
    "6eed2d1a7cdfd7d04692e446a6e0e2796b08d8bbe93a127c02c42df7fd45ccd096f492e504e282cc420e8020c4fd9dac"
    "99d2f2a125f68bb57c643409fd8ca7af7dbdf65921c356407d2f38eabf70e1f0d2e1b00a773667a9874ae1311cfc05ec"
    "0e43947a36172b0778eabb89c7962f2f", 16)
_D = int(
    "283171013bdb1965160b6336c9b93a9879dc8f11d48f3ed30ab969329040b852118c1dc32c509d694f061637b4eda62d"
    "4b2e3f21f600d0750eee6a6bee16ba6ee1ba62c3ad31aa5414c3c87700b2e99979f64c9cdabc4313026dda96e5460002"
    "566fed86a454ed2575d0d66bc8364145bd6111d716d7e58ab1d29c7ef34fa6eb68eb221a81e4814a8f080a677e60f217"
    "485ccdf04b71beba520535f6fad3076951dce0c4eed989d315e967c47c3a52c82683f893283a9aacd8459a336e8fd28b"
    "8b951e7f79075912440e181561437f91498f1b1968ce3cec4e56e0f6b7923dec5c7e6ecc8900b15b86ff991be98962b9"
    "3eda3d87ed1744bc2d125ec2f8fcca71", 16)
_EXP = 65537
_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")

DEFAULT_LIFETIME = 3600
MAX_LIFETIME = 43200          # 12h; longer needs an org-policy allowlist in real GCP
MAX_DELEGATES = 20
MAX_ISSUED = 500
TOKEN_TYPES = {
    "generateAccessToken": "Access token",
    "generateIdToken": "ID token",
    "signBlob": "Signed blob",
    "signJwt": "Signed JWT",
}
_EMAIL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9.-]*\.gserviceaccount\.com$")
_UNIQUE_ID = re.compile(r"^\d{15,25}$")


# ── store ──────────────────────────────────────────────────────────────────
class IamCredentialsStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.issued: dict = {}     # credential id -> issue record (no secret material)


_SHARED: IamCredentialsStore | None = None


def shared_store() -> IamCredentialsStore:
    """The appliance-wide store: the native wire and the console REST share it."""
    global _SHARED
    if _SHARED is None:
        _SHARED = IamCredentialsStore()
    return _SHARED


@dataclass
class CredResponse:
    status: int = 200
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    media_type: str | None = "application/json"


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _err(status, gcp_status, message):
    body = {"error": {"code": status, "message": message, "status": gcp_status}}
    return CredResponse(status=status, body=json.dumps(body).encode())


def _json(status, obj):
    return CredResponse(status=status, body=json.dumps(obj).encode())


def _now():
    return datetime.now(timezone.utc)


def _ts(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── RS256 ──────────────────────────────────────────────────────────────────
def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64u_json(obj):
    return _b64u(json.dumps(obj, separators=(",", ":")).encode())


def key_id(email):
    """Stable 40-hex key id per service account (Google's are 40-hex private key ids)."""
    return hashlib.sha1(("vyomi-iamcredentials/" + email).encode()).hexdigest()


def rsa_sign(data: bytes) -> bytes:
    """RSASSA-PKCS1-v1_5 / SHA-256 with the emulator key."""
    k = (_N.bit_length() + 7) // 8
    t = _SHA256_PREFIX + hashlib.sha256(data).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), _D, _N).to_bytes(k, "big")


def rsa_verify(data: bytes, sig: bytes) -> bool:
    k = (_N.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    em = pow(int.from_bytes(sig, "big"), _EXP, _N).to_bytes(k, "big")
    t = _SHA256_PREFIX + hashlib.sha256(data).digest()
    return em == b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t


def public_jwk(email=None):
    """The JWK that verifies every RS256 signature this core produces."""
    def i2b(n):
        return _b64u(n.to_bytes((n.bit_length() + 7) // 8, "big"))
    return {"kty": "RSA", "alg": "RS256", "use": "sig", "kid": key_id(email) if email else "",
            "n": i2b(_N), "e": i2b(_EXP)}


def _jwt(header, payload):
    signing_input = (_b64u_json(header) + "." + _b64u_json(payload)).encode()
    return signing_input.decode() + "." + _b64u(rsa_sign(signing_input))


# ── name handling ──────────────────────────────────────────────────────────
def _resolve(ident, resolver, what="the service account"):
    """Validate a `{email|uniqueId}` and resolve it to the account email. Mirrors Google:
    malformed -> 400, unknown/unauthorised -> 403 (existence is not revealed)."""
    if not (_EMAIL.match(ident) or _UNIQUE_ID.match(ident)):
        raise _E(400, "INVALID_ARGUMENT", "Request contains an invalid argument.")
    email = ident
    if resolver is not None:
        email = resolver(ident)
        if not email:
            raise _E(403, "PERMISSION_DENIED",
                     "Permission 'iam.serviceAccounts.getAccessToken' denied on resource (or it may not exist).")
    elif _UNIQUE_ID.match(ident):
        raise _E(403, "PERMISSION_DENIED",
                 "Permission 'iam.serviceAccounts.getAccessToken' denied on resource (or it may not exist).")
    return email


def _check_delegates(delegates, resolver):
    if delegates is None:
        return []
    if not isinstance(delegates, list) or not all(isinstance(d, str) for d in delegates):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value at 'delegates': expected a list of strings.")
    if len(delegates) > MAX_DELEGATES:
        raise _E(400, "INVALID_ARGUMENT", "Too many delegates: at most %d are allowed." % MAX_DELEGATES)
    out = []
    for d in delegates:
        m = re.match(r"^projects/-/serviceAccounts/([^/]+)$", d)
        if not m:
            raise _E(400, "INVALID_ARGUMENT", "Invalid delegate name '%s'; expected projects/-/serviceAccounts/{email}." % d)
        out.append(_resolve(m.group(1), resolver))
    return out


def _lifetime(v):
    if v in (None, ""):
        return DEFAULT_LIFETIME
    m = re.match(r"^(\d+)(?:\.\d+)?s$", str(v))
    if not m:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value at 'lifetime' (type google.protobuf.Duration), \"%s\"" % v)
    secs = int(m.group(1))
    if secs == 0:   # the proto3 default Duration means "unset"
        return DEFAULT_LIFETIME
    if secs < 1 or secs > MAX_LIFETIME:
        raise _E(400, "INVALID_ARGUMENT",
                 "The requested lifetime of %ds is invalid; it must be between 1s and %ds." % (secs, MAX_LIFETIME))
    return secs


# ── operations ─────────────────────────────────────────────────────────────
def _record(store, kind, email, delegates, detail, lifetime, now):
    cid = "cred-" + secrets.token_hex(6)
    store.issued[cid] = {
        "id": cid, "type": TOKEN_TYPES[kind], "method": kind, "serviceAccount": email,
        "detail": detail, "delegates": delegates, "issueTime": _ts(now),
        "expireTime": _ts(now + timedelta(seconds=lifetime)) if lifetime else "",
        "lifetimeSeconds": lifetime, "status": "ISSUED",
    }
    if len(store.issued) > MAX_ISSUED:
        for old in list(store.issued)[: len(store.issued) - MAX_ISSUED]:
            del store.issued[old]
    return cid


def generate_access_token(store, ident, body, resolver=None):
    email = _resolve(ident, resolver)
    delegates = _check_delegates(body.get("delegates"), resolver)
    scope = body.get("scope")
    if not scope or not isinstance(scope, list) or not all(isinstance(s, str) and s for s in scope):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value at 'scope': a non-empty list of OAuth scopes is required.")
    life = _lifetime(body.get("lifetime"))
    now = _now()
    _record(store, "generateAccessToken", email, delegates, " ".join(scope), life, now)
    return {"accessToken": "ya29.c." + secrets.token_urlsafe(96), "expireTime": _ts(now + timedelta(seconds=life))}


def generate_id_token(store, ident, body, resolver=None):
    email = _resolve(ident, resolver)
    delegates = _check_delegates(body.get("delegates"), resolver)
    aud = body.get("audience")
    if not aud or not isinstance(aud, str):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value at 'audience': an audience is required.")
    now = _now()
    iat = int(now.timestamp())
    payload = {"aud": aud, "azp": email, "exp": iat + DEFAULT_LIFETIME, "iat": iat,
               "iss": "https://accounts.google.com", "sub": hashlib.sha1(email.encode()).hexdigest()[:21]}
    if body.get("includeEmail"):
        payload["email"] = email
        payload["email_verified"] = True
    tok = _jwt({"alg": "RS256", "kid": key_id(email), "typ": "JWT"}, payload)
    _record(store, "generateIdToken", email, delegates, aud, DEFAULT_LIFETIME, now)
    return {"token": tok}


def sign_blob(store, ident, body, resolver=None):
    email = _resolve(ident, resolver)
    delegates = _check_delegates(body.get("delegates"), resolver)
    raw = body.get("payload")
    if not raw or not isinstance(raw, str):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value at 'payload': the bytes to sign are required.")
    try:
        data = base64.b64decode(raw + "=" * (-len(raw) % 4), validate=False)
    except Exception:
        raise _E(400, "INVALID_ARGUMENT", "Invalid value at 'payload' (TYPE_BYTES), base64 decoding failed.")
    _record(store, "signBlob", email, delegates, "%d bytes" % len(data), 0, _now())
    return {"keyId": key_id(email), "signedBlob": base64.b64encode(rsa_sign(data)).decode()}


def sign_jwt(store, ident, body, resolver=None):
    email = _resolve(ident, resolver)
    delegates = _check_delegates(body.get("delegates"), resolver)
    raw = body.get("payload")
    if not raw or not isinstance(raw, str):
        raise _E(400, "INVALID_ARGUMENT", "Invalid value at 'payload': a JSON claim set string is required.")
    try:
        claims = json.loads(raw)
    except Exception:
        claims = None
    if not isinstance(claims, dict):
        raise _E(400, "INVALID_ARGUMENT", "The JWT claim set is invalid: payload must be a JSON object.")
    kid = key_id(email)
    tok = _jwt({"alg": "RS256", "kid": kid, "typ": "JWT"}, claims)
    _record(store, "signJwt", email, delegates, str(claims.get("aud") or claims.get("sub") or "claim set"), 0, _now())
    return {"keyId": kid, "signedJwt": tok}


_VERBS = {"generateAccessToken": generate_access_token, "generateIdToken": generate_id_token,
          "signBlob": sign_blob, "signJwt": sign_jwt}


# ── views / console ────────────────────────────────────────────────────────
def console_view(rec):
    """Flat row for the console grid / detail: every column filled."""
    r = dict(rec)
    r.update({
        "name": rec["id"], "service_account": rec["serviceAccount"],
        "resourceName": "projects/-/serviceAccounts/" + rec["serviceAccount"],
        "issued": rec["issueTime"], "expires": rec["expireTime"] or "Does not expire (signature only)",
        "lifetime": ("%ds" % rec["lifetimeSeconds"]) if rec["lifetimeSeconds"] else "Not applicable",
        "scope_or_audience": rec["detail"] or "-",
        "delegation": " → ".join(rec["delegates"]) if rec["delegates"] else "None (direct)",
        "delegate_count": str(len(rec["delegates"])),
        "key_id": key_id(rec["serviceAccount"]),
        "signing_algorithm": "RS256 (RSASSA-PKCS1-v1_5, SHA-256)" if rec["method"] != "generateAccessToken" else "Opaque OAuth 2.0 bearer token",
        "api_method": "iamcredentials.projects.serviceAccounts." + rec["method"],
        "region": "global", "state": rec["status"],
    })
    return r


def list_all(store):
    return [console_view(r) for r in store.issued.values()]


def issue_from_form(store, b, resolver=None):
    """Console create form → issue a credential via the same code path as the API.
    Returns the new console row."""
    kind = {"access token": "generateAccessToken", "id token": "generateIdToken",
            "signed blob": "signBlob", "signed jwt": "signJwt"}.get(str(b.get("credentialType") or "Access token").strip().lower())
    if not kind:
        raise _E(400, "INVALID_ARGUMENT", "credentialType must be Access token, ID token, Signed blob or Signed JWT.")
    sa = str(b.get("serviceAccount") or "").strip()
    if sa.startswith("projects/-/serviceAccounts/"):
        sa = sa.rsplit("/", 1)[-1]
    delegates = [("projects/-/serviceAccounts/" + d.strip()) for d in str(b.get("delegates") or "").split(",") if d.strip()]
    detail = str(b.get("detail") or "").strip()
    life = str(b.get("lifetime") or "").strip()
    if kind == "generateAccessToken":
        req = {"scope": (detail or "https://www.googleapis.com/auth/cloud-platform").split(), "delegates": delegates}
        if life:
            req["lifetime"] = life if life.endswith("s") else life + "s"
    elif kind == "generateIdToken":
        req = {"audience": detail or "https://example.com", "includeEmail": True, "delegates": delegates}
    elif kind == "signBlob":
        req = {"payload": base64.b64encode((detail or "hello vyomi").encode()).decode(), "delegates": delegates}
    else:
        req = {"payload": json.dumps({"iss": sa, "sub": sa, "aud": detail or "https://example.com",
                                      "iat": int(_now().timestamp()), "exp": int(_now().timestamp()) + 3600}), "delegates": delegates}
    before = set(store.issued)
    _VERBS[kind](store, sa, req, resolver)
    new = [c for c in store.issued if c not in before]
    return console_view(store.issued[new[-1]])


# ── dispatch ───────────────────────────────────────────────────────────────
def dispatch(store, method, path, query=None, headers=None, body=b"", resolver=None):
    method = method.upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return _err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if not isinstance(payload, dict):
        payload = {}
    p = path.split("?", 1)[0]
    for pre in ("/v1",):
        if p.startswith(pre + "/"):
            p = p[len(pre):]
            break
    p = p.strip("/")
    verb = ""
    if ":" in p:
        p, verb = p.rsplit(":", 1)
    segs = [s for s in p.split("/") if s]
    if len(segs) != 4 or segs[0] != "projects" or segs[2] != "serviceAccounts" or verb not in _VERBS:
        return _err(404, "NOT_FOUND", "Method not found: %s" % path)
    if method != "POST":
        return _err(405, "UNIMPLEMENTED", "Method %s not allowed for :%s." % (method, verb))
    try:
        if segs[1] != "-":
            raise _E(400, "INVALID_ARGUMENT",
                     "The wildcard '-' is required as the project in the resource name projects/-/serviceAccounts/{account}.")
        return _json(200, _VERBS[verb](store, segs[3], payload, resolver))
    except _E as e:
        return _err(e.status, e.gcp_status, e.message)
