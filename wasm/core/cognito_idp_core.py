"""Amazon Cognito Identity Provider (user pools) core — substrate-independent.

Speaks the NATIVE Cognito IDP wire: JSON 1.1 over `POST /` with
`X-Amz-Target: AWSCognitoIdentityProviderService.<Operation>` (botocore model
`cognito-idp`, 2016-04-18), plus the public OIDC documents
`/<poolId>/.well-known/jwks.json` and `/<poolId>/.well-known/openid-configuration`.
So an unmodified aws-sdk / aws-cli / Amplify client works against it. No fastapi /
boto3 / socket imports -> loads under Pyodide (this exact file runs offline and
in Nano). State lives in a `CognitoIdpStore` (plain JSON-safe dicts) and persists
through the store seam (`persist()` hook -> SQLite offline, IndexedDB in Nano).

What is real: user-pool / app-client / group / domain / IdP / resource-server
lifecycles; sign-up, confirmation, admin user management, password policy,
USER_PASSWORD_AUTH / ADMIN_*_PASSWORD_AUTH / REFRESH_TOKEN_AUTH, the
NEW_PASSWORD_REQUIRED challenge, token revocation (GlobalSignOut / RevokeToken),
forgot-password, ListUsers filters, pagination. Tokens are genuine RS256 JWTs
(claims as in the real service) verifiable against the pool's JWKS.

Local-emulator conventions: confirmation / reset codes are not e-mailed; the code is
always `123456` (CodeDeliveryDetails still reports the masked destination).
Not implemented (returns UnsupportedOperationException): SRP, MFA challenges,
hosted-UI OAuth, Lambda triggers, devices, import jobs, risk config.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets as _secrets
import time
import uuid
from dataclasses import dataclass, field

REGION = "us-east-1"
ACCOUNT_ID = "123456789012"
TARGET_PREFIX = "AWSCognitoIdentityProviderService."
FIXED_CODE = "123456"

# Fixed RSA-2048 signing key (a local-emulator key, NOT a secret): tokens are real RS256 JWTs
# verifiable against /<poolId>/.well-known/jwks.json, like the real service.
_RSA_N = int("0xa05dd916e0f00d7459398778ea4d73b48010ac04076893d359fe30cad81d1fcc4c603ec88dd6044139dcb156114b3c87d120d30985f4ab051ec8b0671859fc263d13494c4c4985287f886ae27073dee15e3038b682dd12665850b5e09ed02cc7f9c2179b0d7be9914db5279be8397497a98f528b03100663023cf64c367762d5fec2d6e6aa0892146aea1902497e0f6a844c3447ea518bde85215fd39310b4a8f41df935e81d6e224e3688852ca32a97edaac60f7d7df09856777d7b7e275a8fe2deaa96fc6dda0450a9d6a2f311590515146e6545d8796b71648fec579ce984baf8f1fc8d5cdd3babc242d221d6f2f1f335fb9d0836e440df043208679f077f", 16)
_RSA_D = int("0x3094fdc54e93aa9fcac000e882a2c020b88354794bfd447b4cd212da00aaa20d743ddc0749e0c21d38784148ffa8394833f4abba40d8a44ec2caad962dec64d4f8bfb4fee645878f8343428e22df177052e66ce7edb12777d5dd6d9c04c0b0304cdb9de71d28a2d3a024f740e61331dd1843111087f6fcd855bf3e264c81d270e2af5b3ff08712e168ef97e931ef56a850dbd089ffceac53ff4fa2fc1d790c73a0592c108fc52f94d383d832d9da615357c183b8e6a3baea5d3e664eea64f1dad638aa81693e88db1cde8f0024f0417884f573293566c477520866c050d1b4447e979ad2337596446829f6369fe828fd926aebef14e0ac33270b8edd68099a91", 16)
_RSA_E = 65537


@dataclass
class CognitoResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)
    media_type: str = "application/x-amz-json-1.1"


class CognitoError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status


def _err(code, msg, status=400):
    return CognitoError(code, msg, status)


class CognitoIdpStore:
    """The seam. Every attribute is plain JSON data (nano_persist / SQLite friendly)."""

    def __init__(self, account_id: str = ACCOUNT_ID, region: str = REGION) -> None:
        self.account_id, self.region = account_id, region
        self.pools: dict = {}      # poolId -> pool description
        self.clients: dict = {}    # poolId -> {clientId -> client}
        self.users: dict = {}      # poolId -> {username -> user}
        self.groups: dict = {}     # poolId -> {groupName -> group}
        self.idps: dict = {}       # poolId -> {providerName -> idp}
        self.servers: dict = {}    # poolId -> {identifier -> resource server}
        self.domains: dict = {}    # domain -> {UserPoolId, ...}
        self.tokens: dict = {}     # refresh token -> {pool, username, client, ...}
        self.sessions: dict = {}   # challenge session -> {...}
        self.ui: dict = {}         # poolId -> {clientId|ALL -> {CSS, ImageUrl}}

    def persist(self) -> None:
        """Flush hook (no-op in memory)."""


class InMemoryCognitoIdpStore(CognitoIdpStore):
    pass


# ── helpers ──────────────────────────────────────────────────────────────────
def _now() -> float:
    return round(time.time(), 3)


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _rand(n: int, alphabet: str) -> str:
    return "".join(_secrets.choice(alphabet) for _ in range(n))


def _pool_arn(store, pid):
    return f"arn:aws:cognito-idp:{store.region}:{store.account_id}:userpool/{pid}"


_KID = hashlib.sha256(str(_RSA_N).encode()).hexdigest()[:16]
_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _rs256(msg: bytes) -> bytes:
    k = (_RSA_N.bit_length() + 7) // 8
    t = _SHA256_PREFIX + hashlib.sha256(msg).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), _RSA_D, _RSA_N).to_bytes(k, "big")


def _jwt(claims: dict) -> str:
    h = _b64u(json.dumps({"kid": _KID, "alg": "RS256"}, separators=(",", ":")).encode())
    p = _b64u(json.dumps(claims, separators=(",", ":")).encode())
    return f"{h}.{p}.{_b64u(_rs256((h + '.' + p).encode()))}"


def _jwt_verify(token: str) -> dict:
    try:
        h, p, s = token.split(".")
        k = (_RSA_N.bit_length() + 7) // 8
        em = pow(int.from_bytes(_b64u_dec(s), "big"), _RSA_E, _RSA_N).to_bytes(k, "big")
        t = _SHA256_PREFIX + hashlib.sha256((h + "." + p).encode()).digest()
        if em != b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t:
            raise ValueError("bad signature")
        return json.loads(_b64u_dec(p))
    except Exception:
        raise _err("NotAuthorizedException", "Invalid Access Token")


def jwks(store, pool_id: str) -> dict | None:
    if pool_id not in store.pools:
        return None
    return {"keys": [{"alg": "RS256", "e": _b64u(_RSA_E.to_bytes(3, "big")), "kid": _KID, "kty": "RSA",
                      "n": _b64u(_RSA_N.to_bytes((_RSA_N.bit_length() + 7) // 8, "big")), "use": "sig"}]}


def openid_configuration(store, pool_id: str, host: str = "") -> dict | None:
    if pool_id not in store.pools:
        return None
    iss = f"https://cognito-idp.{store.region}.amazonaws.com/{pool_id}"
    return {"issuer": iss, "jwks_uri": iss + "/.well-known/jwks.json",
            "subject_types_supported": ["public"], "id_token_signing_alg_values_supported": ["RS256"],
            "response_types_supported": ["code", "token"], "scopes_supported": ["openid", "email", "phone", "profile"]}


def _req(p: dict, *names):
    for n in names:
        if p.get(n) in (None, "", [], {}):
            raise _err("InvalidParameterException",
                       f"1 validation error detected: Value null at '{n[0].lower() + n[1:]}' failed to satisfy constraint: Member must not be null")
    return [p[n] for n in names]


def _page(items: list, limit, token, default=60, maxn=60):
    n = int(limit) if limit else default
    if n < 1 or n > maxn:
        raise _err("InvalidParameterException", f"1 validation error detected: Value '{n}' at 'limit' failed to satisfy constraint: Member must have value less than or equal to {maxn}")
    start = 0
    if token:
        try:
            start = int(_b64u_dec(token).decode())
        except Exception:
            raise _err("InvalidParameterException", "Invalid pagination token")
    chunk = items[start:start + n]
    nxt = _b64u(str(start + n).encode()) if start + n < len(items) else None
    return chunk, nxt


def _pool(store, pid):
    if not pid or pid not in store.pools:
        raise _err("ResourceNotFoundException", f"User pool {pid} does not exist.")
    return store.pools[pid]


def _client(store, pid, cid):
    _pool(store, pid)
    c = store.clients.get(pid, {}).get(cid)
    if not c:
        raise _err("ResourceNotFoundException", f"User pool client {cid} does not exist.")
    return c


def _find_client(store, cid):
    for pid, cs in store.clients.items():
        if cid in cs:
            return pid, cs[cid]
    raise _err("ResourceNotFoundException", f"User pool client {cid} does not exist.")


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


# ── attributes / schema ──────────────────────────────────────────────────────
_STD_ATTRS = [  # name, type, mutable, required
    ("sub", "String", False, True), ("name", "String", True, False), ("given_name", "String", True, False),
    ("family_name", "String", True, False), ("middle_name", "String", True, False),
    ("nickname", "String", True, False), ("preferred_username", "String", True, False),
    ("profile", "String", True, False), ("picture", "String", True, False), ("website", "String", True, False),
    ("email", "String", True, False), ("email_verified", "Boolean", True, False),
    ("gender", "String", True, False), ("birthdate", "String", True, False),
    ("zoneinfo", "String", True, False), ("locale", "String", True, False),
    ("phone_number", "String", True, False), ("phone_number_verified", "Boolean", True, False),
    ("address", "String", True, False), ("updated_at", "Number", True, False),
]


def _std_schema() -> list:
    out = []
    for n, t, m, r in _STD_ATTRS:
        a = {"Name": n, "AttributeDataType": t, "DeveloperOnlyAttribute": False, "Mutable": m, "Required": r}
        if t == "String":
            a["StringAttributeConstraints"] = {"MinLength": "1", "MaxLength": "2048"} if n != "sub" else {"MinLength": "1", "MaxLength": "2048"}
        if t == "Number":
            a["NumberAttributeConstraints"] = {"MinValue": "0"}
        out.append(a)
    return out


def _custom_attr(a: dict) -> dict:
    name = a.get("Name", "")
    if not name:
        raise _err("InvalidParameterException", "Attribute name is required")
    full = name if name.startswith("custom:") else f"custom:{name}"
    out = {"Name": full, "AttributeDataType": a.get("AttributeDataType", "String"),
           "DeveloperOnlyAttribute": bool(a.get("DeveloperOnlyAttribute", False)),
           "Mutable": bool(a.get("Mutable", True)), "Required": False}
    if a.get("StringAttributeConstraints") is not None:
        out["StringAttributeConstraints"] = a["StringAttributeConstraints"]
    elif out["AttributeDataType"] == "String":
        out["StringAttributeConstraints"] = {"MinLength": "0", "MaxLength": "2048"}
    if a.get("NumberAttributeConstraints") is not None:
        out["NumberAttributeConstraints"] = a["NumberAttributeConstraints"]
    return out


def _attr_map(user) -> dict:
    return {a["Name"]: a["Value"] for a in user["Attributes"]}


def _set_attrs(user, attrs: list, schema: list | None = None, creating=False) -> None:
    known = {a["Name"]: a for a in (schema or _std_schema())}
    cur = _attr_map(user)
    for a in attrs or []:
        n, v = a.get("Name"), a.get("Value", "")
        if not n:
            raise _err("InvalidParameterException", "Attribute name is required")
        if n not in known:
            raise _err("InvalidParameterException", f"Attribute does not exist in the schema: {n}")
        if not creating and not known[n].get("Mutable", True):
            raise _err("InvalidParameterException", f"user.{n} is not mutable")
        if known[n]["AttributeDataType"] == "Boolean" and str(v).lower() not in ("true", "false"):
            raise _err("InvalidParameterException", f"Attribute {n} must be a boolean")
        cur[n] = str(v)
    user["Attributes"] = [{"Name": k, "Value": v} for k, v in
                          sorted(cur.items(), key=lambda kv: (kv[0] != "sub", kv[0]))]
    user["UserLastModifiedDate"] = _now()


def _user_view(u: dict, key="Attributes") -> dict:
    return {"Username": u["Username"], key: list(u["Attributes"]), "UserCreateDate": u["UserCreateDate"],
            "UserLastModifiedDate": u["UserLastModifiedDate"], "Enabled": u["Enabled"], "UserStatus": u["UserStatus"]}


def _mask(dest: str, kind: str) -> str:
    if kind == "EMAIL" and "@" in dest:
        local, dom = dest.split("@", 1)
        return f"{local[:1]}***@{dom[:1]}***"
    return "+" + "*" * 9 + dest[-4:] if dest else ""


# ── password policy ──────────────────────────────────────────────────────────
def _check_password(pool: dict, pw: str) -> None:
    pol = (pool.get("Policies") or {}).get("PasswordPolicy") or {}
    n = int(pol.get("MinimumLength", 8))
    if not isinstance(pw, str) or len(pw) < 6:
        raise _err("InvalidParameterException", "1 validation error detected: Value at 'password' failed to satisfy constraint: Member must have length greater than or equal to 6")
    why = []
    if len(pw) < n:
        why.append("Password not long enough")
    elif pol.get("RequireUppercase", True) and not re.search(r"[A-Z]", pw):
        why.append("Password must have uppercase characters")
    elif pol.get("RequireLowercase", True) and not re.search(r"[a-z]", pw):
        why.append("Password must have lowercase characters")
    elif pol.get("RequireNumbers", True) and not re.search(r"\d", pw):
        why.append("Password must have numeric characters")
    elif pol.get("RequireSymbols", True) and not re.search(r"[^\w\s]|_", pw):
        why.append("Password must have symbol characters")
    if why:
        raise _err("InvalidPasswordException", f"Password did not conform with policy: {why[0]}")


def _hash(pw: str, salt: str) -> str:
    return hashlib.sha256((salt + pw).encode()).hexdigest()


def _set_password(u, pw):
    salt = _rand(8, "abcdef0123456789")
    u["_salt"], u["_pw"] = salt, _hash(pw, salt)


def _pw_ok(u, pw) -> bool:
    return bool(u.get("_pw")) and hmac.compare_digest(u["_pw"], _hash(pw, u.get("_salt", "")))


_OPS: dict = {}


def op(fn):
    name = "".join(w.capitalize() for w in fn.__name__.split("_"))
    _OPS[_ALIAS.get(name, name)] = fn
    return fn


_ALIAS = {"AdminSetUserMfaPreference": "AdminSetUserMFAPreference", "SetUserMfaPreference": "SetUserMFAPreference",
          "SetUiCustomization": "SetUICustomization", "GetUiCustomization": "GetUICustomization",
          "GetCsvHeader": "GetCSVHeader"}


# ══ user pools ═══════════════════════════════════════════════════════════════
_POOL_PASSTHROUGH = ("Policies", "DeletionProtection", "LambdaConfig", "AutoVerifiedAttributes", "AliasAttributes",
                     "UsernameAttributes", "SmsVerificationMessage", "EmailVerificationMessage",
                     "EmailVerificationSubject", "VerificationMessageTemplate", "SmsAuthenticationMessage",
                     "MfaConfiguration", "UserAttributeUpdateSettings", "DeviceConfiguration", "EmailConfiguration",
                     "SmsConfiguration", "AdminCreateUserConfig", "UserPoolAddOns", "UsernameConfiguration",
                     "AccountRecoverySetting", "UserPoolTier")


def _default_policies(p):
    pol = dict((p or {}).get("PasswordPolicy") or {})
    for k, v in (("MinimumLength", 8), ("RequireUppercase", True), ("RequireLowercase", True),
                 ("RequireNumbers", True), ("RequireSymbols", True), ("TemporaryPasswordValidityDays", 7)):
        pol.setdefault(k, v)
    pol.setdefault("PasswordHistorySize", 0)
    out = dict(p or {})
    out["PasswordPolicy"] = pol
    return out


def _pool_view(store, pool: dict) -> dict:
    v = _clean(pool)
    v["EstimatedNumberOfUsers"] = len(store.users.get(pool["Id"], {}))
    return v


@op
def create_user_pool(store, p):
    (name,) = _req(p, "PoolName")
    if not 1 <= len(name) <= 128:
        raise _err("InvalidParameterException", "1 validation error detected: Value at 'poolName' failed to satisfy constraint: Member must have length less than or equal to 128")
    if any(x["Name"] == name for x in store.pools.values()) and False:
        pass
    pid = f"{store.region}_{_rand(9, 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789')}"
    now = _now()
    pool = {"Id": pid, "Name": name, "Arn": _pool_arn(store, pid), "CreationDate": now, "LastModifiedDate": now,
            "Policies": _default_policies(p.get("Policies")), "DeletionProtection": "INACTIVE",
            "LambdaConfig": {}, "AutoVerifiedAttributes": [], "MfaConfiguration": "OFF",
            "EmailConfiguration": {"EmailSendingAccount": "COGNITO_DEFAULT"},
            "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": False,
                                      "UnusedAccountValidityDays": 7},
            "UsernameConfiguration": {"CaseSensitive": False}, "UserPoolTier": "ESSENTIALS",
            "AccountRecoverySetting": {"RecoveryMechanisms": [{"Priority": 1, "Name": "verified_email"},
                                                               {"Priority": 2, "Name": "verified_phone_number"}]},
            "VerificationMessageTemplate": {"DefaultEmailOption": "CONFIRM_WITH_CODE"},
            "UserPoolTags": dict(p.get("UserPoolTags") or {}),
            "SchemaAttributes": _std_schema()}
    for k in _POOL_PASSTHROUGH:
        if k in p and k != "Policies" and p[k] is not None:
            pool[k] = p[k]
    for a in p.get("Schema") or []:
        if not a.get("Name", "").startswith("custom:") and any(s["Name"] == a["Name"] for s in pool["SchemaAttributes"]):
            for s in pool["SchemaAttributes"]:
                if s["Name"] == a["Name"]:
                    s.update({k: v for k, v in a.items() if k in ("Mutable", "Required", "StringAttributeConstraints",
                                                                  "NumberAttributeConstraints")})
        else:
            pool["SchemaAttributes"].append(_custom_attr(a))
    if pool.get("UsernameAttributes") and pool.get("AliasAttributes"):
        raise _err("InvalidParameterException", "You can't specify both UsernameAttributes and AliasAttributes")
    store.pools[pid] = pool
    for d in (store.clients, store.users, store.groups, store.idps, store.servers):
        d[pid] = {}
    store.persist()
    return {"UserPool": _pool_view(store, pool)}


@op
def describe_user_pool(store, p):
    (pid,) = _req(p, "UserPoolId")
    return {"UserPool": _pool_view(store, _pool(store, pid))}


@op
def list_user_pools(store, p):
    _req(p, "MaxResults")
    items = [{"Id": x["Id"], "Name": x["Name"], "LambdaConfig": x.get("LambdaConfig", {}),
              "LastModifiedDate": x["LastModifiedDate"], "CreationDate": x["CreationDate"]}
             for x in sorted(store.pools.values(), key=lambda x: x["CreationDate"])]
    chunk, nxt = _page(items, p.get("MaxResults"), p.get("NextToken"), 60)
    out = {"UserPools": chunk}
    if nxt:
        out["NextToken"] = nxt
    return out


@op
def update_user_pool(store, p):
    (pid,) = _req(p, "UserPoolId")
    pool = _pool(store, pid)
    for k in _POOL_PASSTHROUGH:
        if k in p and p[k] is not None:
            pool[k] = _default_policies(p[k]) if k == "Policies" else p[k]
    if "UserPoolTags" in p:
        pool["UserPoolTags"] = dict(p["UserPoolTags"] or {})
    pool["LastModifiedDate"] = _now()
    store.persist()
    return {}


@op
def delete_user_pool(store, p):
    (pid,) = _req(p, "UserPoolId")
    pool = _pool(store, pid)
    if pool.get("DeletionProtection") == "ACTIVE":
        raise _err("InvalidParameterException", "User pool cannot be deleted because deletion protection is active.")
    for d in (store.pools, store.clients, store.users, store.groups, store.idps, store.servers, store.ui):
        d.pop(pid, None)
    for dom in [d for d, v in store.domains.items() if v["UserPoolId"] == pid]:
        store.domains.pop(dom)
    for t in [t for t, v in store.tokens.items() if v["pool"] == pid]:
        store.tokens.pop(t)
    store.persist()
    return {}


@op
def add_custom_attributes(store, p):
    pid, attrs = _req(p, "UserPoolId", "CustomAttributes")
    pool = _pool(store, pid)
    have = {a["Name"] for a in pool["SchemaAttributes"]}
    new = [_custom_attr(a) for a in attrs]
    for a in new:
        if a["Name"] in have:
            raise _err("InvalidParameterException", f"You can not add duplicate attribute: {a['Name']}")
    pool["SchemaAttributes"].extend(new)
    store.persist()
    return {}


@op
def get_csv_header(store, p):
    (pid,) = _req(p, "UserPoolId")
    pool = _pool(store, pid)
    hdr = ["cognito:username"] + [a["Name"] for a in pool["SchemaAttributes"] if a["Name"] != "sub"] + \
          ["cognito:mfa_enabled"]
    return {"UserPoolId": pid, "CSVHeader": hdr}


@op
def get_user_pool_mfa_config(store, p):
    (pid,) = _req(p, "UserPoolId")
    pool = _pool(store, pid)
    out = {"MfaConfiguration": pool.get("MfaConfiguration", "OFF")}
    out["SoftwareTokenMfaConfiguration"] = pool.get("SoftwareTokenMfaConfiguration", {"Enabled": False})
    if pool.get("SmsMfaConfiguration"):
        out["SmsMfaConfiguration"] = pool["SmsMfaConfiguration"]
    return out


@op
def set_user_pool_mfa_config(store, p):
    (pid,) = _req(p, "UserPoolId")
    pool = _pool(store, pid)
    mode = p.get("MfaConfiguration", "OFF")
    if mode not in ("OFF", "ON", "OPTIONAL"):
        raise _err("InvalidParameterException", f"Invalid MfaConfiguration: {mode}")
    pool["MfaConfiguration"] = mode
    for k in ("SoftwareTokenMfaConfiguration", "SmsMfaConfiguration"):
        if p.get(k) is not None:
            pool[k] = p[k]
    store.persist()
    return get_user_pool_mfa_config(store, p)


# ══ app clients ══════════════════════════════════════════════════════════════
_CLIENT_FIELDS = ("RefreshTokenValidity", "AccessTokenValidity", "IdTokenValidity", "TokenValidityUnits",
                  "ReadAttributes", "WriteAttributes", "ExplicitAuthFlows", "SupportedIdentityProviders",
                  "CallbackURLs", "LogoutURLs", "DefaultRedirectURI", "AllowedOAuthFlows", "AllowedOAuthScopes",
                  "AllowedOAuthFlowsUserPoolClient", "AnalyticsConfiguration", "PreventUserExistenceErrors",
                  "EnableTokenRevocation", "EnablePropagateAdditionalUserContextData", "AuthSessionValidity")


def _client_view(c):
    return _clean(c)


@op
def create_user_pool_client(store, p):
    pid, name = _req(p, "UserPoolId", "ClientName")
    _pool(store, pid)
    cid = _rand(26, "abcdefghijklmnopqrstuvwxyz0123456789")
    now = _now()
    c = {"UserPoolId": pid, "ClientName": name, "ClientId": cid, "LastModifiedDate": now, "CreationDate": now,
         "RefreshTokenValidity": 30, "AccessTokenValidity": 60, "IdTokenValidity": 60,
         "TokenValidityUnits": {"AccessToken": "minutes", "IdToken": "minutes", "RefreshToken": "days"},
         "ExplicitAuthFlows": ["ALLOW_USER_SRP_AUTH", "ALLOW_CUSTOM_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
         "AllowedOAuthFlowsUserPoolClient": False, "EnableTokenRevocation": True,
         "EnablePropagateAdditionalUserContextData": False, "AuthSessionValidity": 3}
    for k in _CLIENT_FIELDS:
        if p.get(k) is not None:
            c[k] = p[k]
    if p.get("GenerateSecret"):
        c["ClientSecret"] = _rand(51, "abcdefghijklmnopqrstuvwxyz0123456789")
    for f in c.get("ExplicitAuthFlows", []):
        if f not in ("ADMIN_NO_SRP_AUTH", "CUSTOM_AUTH_FLOW_ONLY", "USER_PASSWORD_AUTH", "ALLOW_ADMIN_USER_PASSWORD_AUTH",
                     "ALLOW_CUSTOM_AUTH", "ALLOW_USER_PASSWORD_AUTH", "ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH",
                     "ALLOW_USER_AUTH"):
            raise _err("InvalidParameterException", f"Invalid explicit auth flow: {f}")
    store.clients[pid][cid] = c
    store.persist()
    return {"UserPoolClient": _client_view(c)}


@op
def describe_user_pool_client(store, p):
    pid, cid = _req(p, "UserPoolId", "ClientId")
    return {"UserPoolClient": _client_view(_client(store, pid, cid))}


@op
def list_user_pool_clients(store, p):
    (pid,) = _req(p, "UserPoolId")
    _pool(store, pid)
    items = [{"ClientId": c["ClientId"], "UserPoolId": pid, "ClientName": c["ClientName"]}
             for c in sorted(store.clients[pid].values(), key=lambda c: c["CreationDate"])]
    chunk, nxt = _page(items, p.get("MaxResults"), p.get("NextToken"), 60)
    out = {"UserPoolClients": chunk}
    if nxt:
        out["NextToken"] = nxt
    return out


@op
def update_user_pool_client(store, p):
    pid, cid = _req(p, "UserPoolId", "ClientId")
    c = _client(store, pid, cid)
    if p.get("ClientName"):
        c["ClientName"] = p["ClientName"]
    for k in _CLIENT_FIELDS:
        if p.get(k) is not None:
            c[k] = p[k]
    c["LastModifiedDate"] = _now()
    store.persist()
    return {"UserPoolClient": _client_view(c)}


@op
def delete_user_pool_client(store, p):
    pid, cid = _req(p, "UserPoolId", "ClientId")
    _client(store, pid, cid)
    del store.clients[pid][cid]
    for t in [t for t, v in store.tokens.items() if v["client"] == cid]:
        store.tokens.pop(t)
    store.persist()
    return {}


# ══ groups ═══════════════════════════════════════════════════════════════════
def _group(store, pid, name):
    _pool(store, pid)
    g = store.groups[pid].get(name)
    if not g:
        raise _err("ResourceNotFoundException", "Group not found.")
    return g


@op
def create_group(store, p):
    name, pid = _req(p, "GroupName", "UserPoolId")
    _pool(store, pid)
    if name in store.groups[pid]:
        raise _err("GroupExistsException", "A group with the name already exists.")
    now = _now()
    g = {"GroupName": name, "UserPoolId": pid, "Description": p.get("Description", ""),
         "RoleArn": p.get("RoleArn", ""), "LastModifiedDate": now, "CreationDate": now}
    if p.get("Precedence") is not None:
        g["Precedence"] = int(p["Precedence"])
    store.groups[pid][name] = g
    store.persist()
    return {"Group": {k: v for k, v in g.items() if v != ""}}


@op
def get_group(store, p):
    name, pid = _req(p, "GroupName", "UserPoolId")
    return {"Group": {k: v for k, v in _group(store, pid, name).items() if v != ""}}


@op
def list_groups(store, p):
    (pid,) = _req(p, "UserPoolId")
    _pool(store, pid)
    items = [{k: v for k, v in g.items() if v != ""} for g in sorted(store.groups[pid].values(), key=lambda g: g["GroupName"])]
    chunk, nxt = _page(items, p.get("Limit"), p.get("NextToken"), 60)
    out = {"Groups": chunk}
    if nxt:
        out["NextToken"] = nxt
    return out


@op
def update_group(store, p):
    name, pid = _req(p, "GroupName", "UserPoolId")
    g = _group(store, pid, name)
    for k in ("Description", "RoleArn"):
        if k in p:
            g[k] = p[k]
    if p.get("Precedence") is not None:
        g["Precedence"] = int(p["Precedence"])
    g["LastModifiedDate"] = _now()
    store.persist()
    return {"Group": {k: v for k, v in g.items() if v != ""}}


@op
def delete_group(store, p):
    name, pid = _req(p, "GroupName", "UserPoolId")
    _group(store, pid, name)
    del store.groups[pid][name]
    for u in store.users[pid].values():
        if name in u["_groups"]:
            u["_groups"].remove(name)
    store.persist()
    return {}


@op
def admin_add_user_to_group(store, p):
    pid, uname, gname = _req(p, "UserPoolId", "Username", "GroupName")
    u = _find_user(store, pid, uname)
    _group(store, pid, gname)
    if gname not in u["_groups"]:
        u["_groups"].append(gname)
    store.persist()
    return {}


@op
def admin_remove_user_from_group(store, p):
    pid, uname, gname = _req(p, "UserPoolId", "Username", "GroupName")
    u = _find_user(store, pid, uname)
    _group(store, pid, gname)
    if gname in u["_groups"]:
        u["_groups"].remove(gname)
    store.persist()
    return {}


@op
def admin_list_groups_for_user(store, p):
    pid, uname = _req(p, "UserPoolId", "Username")
    u = _find_user(store, pid, uname)
    items = [{k: v for k, v in store.groups[pid][g].items() if v != ""} for g in u["_groups"] if g in store.groups[pid]]
    chunk, nxt = _page(items, p.get("Limit"), p.get("NextToken"), 60)
    out = {"Groups": chunk}
    if nxt:
        out["NextToken"] = nxt
    return out


@op
def list_users_in_group(store, p):
    pid, gname = _req(p, "UserPoolId", "GroupName")
    _group(store, pid, gname)
    items = [_user_view(u) for u in store.users[pid].values() if gname in u["_groups"]]
    chunk, nxt = _page(items, p.get("Limit"), p.get("NextToken"), 60)
    out = {"Users": chunk}
    if nxt:
        out["NextToken"] = nxt
    return out


# ══ domain / IdP / resource servers / tags / UI ═════════════════════════════
@op
def create_user_pool_domain(store, p):
    dom, pid = _req(p, "Domain", "UserPoolId")
    pool = _pool(store, pid)
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?", dom):
        raise _err("InvalidParameterException", "Invalid domain name: use lowercase letters, digits and hyphens")
    if dom in store.domains or pool.get("Domain"):
        raise _err("InvalidParameterException", "This domain name is not available or the pool already has a domain.")
    store.domains[dom] = {"UserPoolId": pid, "AWSAccountId": store.account_id, "Domain": dom, "Version": "1",
                          "S3Bucket": "", "Status": "ACTIVE",
                          "CloudFrontDistribution": f"d{_rand(13, 'abcdefghijklmnopqrstuvwxyz0123456789')}.cloudfront.net"}
    if p.get("CustomDomainConfig"):
        store.domains[dom]["CustomDomainConfig"] = p["CustomDomainConfig"]
    pool["Domain"] = dom
    store.persist()
    return {"CloudFrontDomain": store.domains[dom]["CloudFrontDistribution"]}


@op
def describe_user_pool_domain(store, p):
    (dom,) = _req(p, "Domain")
    d = store.domains.get(dom)
    return {"DomainDescription": dict(d) if d else {}}


@op
def update_user_pool_domain(store, p):
    dom, pid = _req(p, "Domain", "UserPoolId")
    d = store.domains.get(dom)
    if not d or d["UserPoolId"] != pid:
        raise _err("ResourceNotFoundException", "Domain not found.")
    d["CustomDomainConfig"] = p.get("CustomDomainConfig", {})
    d["Version"] = str(int(d["Version"]) + 1)
    store.persist()
    return {"CloudFrontDomain": d["CloudFrontDistribution"]}


@op
def delete_user_pool_domain(store, p):
    dom, pid = _req(p, "Domain", "UserPoolId")
    d = store.domains.get(dom)
    if not d or d["UserPoolId"] != pid:
        raise _err("ResourceNotFoundException", "Domain not found.")
    del store.domains[dom]
    store.pools[pid].pop("Domain", None)
    store.persist()
    return {}


_IDP_TYPES = ("SAML", "Facebook", "Google", "LoginWithAmazon", "SignInWithApple", "OIDC")


@op
def create_identity_provider(store, p):
    pid, name, typ = _req(p, "UserPoolId", "ProviderName", "ProviderType")
    _pool(store, pid)
    if typ not in _IDP_TYPES:
        raise _err("InvalidParameterException", f"Invalid ProviderType: {typ}")
    if name in store.idps[pid]:
        raise _err("DuplicateProviderException", "A provider with the name already exists.")
    now = _now()
    d = {"UserPoolId": pid, "ProviderName": name, "ProviderType": typ,
         "ProviderDetails": p.get("ProviderDetails") or {}, "AttributeMapping": p.get("AttributeMapping") or {},
         "IdpIdentifiers": p.get("IdpIdentifiers") or [], "LastModifiedDate": now, "CreationDate": now}
    store.idps[pid][name] = d
    store.persist()
    return {"IdentityProvider": d}


def _idp(store, pid, name):
    _pool(store, pid)
    d = store.idps[pid].get(name)
    if not d:
        raise _err("ResourceNotFoundException", f"Identity provider {name} does not exist.")
    return d


@op
def describe_identity_provider(store, p):
    pid, name = _req(p, "UserPoolId", "ProviderName")
    return {"IdentityProvider": _idp(store, pid, name)}


@op
def get_identity_provider_by_identifier(store, p):
    pid, ident = _req(p, "UserPoolId", "IdpIdentifier")
    _pool(store, pid)
    for d in store.idps[pid].values():
        if ident in d["IdpIdentifiers"]:
            return {"IdentityProvider": d}
    raise _err("ResourceNotFoundException", f"Identity provider {ident} does not exist.")


@op
def update_identity_provider(store, p):
    pid, name = _req(p, "UserPoolId", "ProviderName")
    d = _idp(store, pid, name)
    for k in ("ProviderDetails", "AttributeMapping", "IdpIdentifiers"):
        if p.get(k) is not None:
            d[k] = p[k]
    d["LastModifiedDate"] = _now()
    store.persist()
    return {"IdentityProvider": d}


@op
def delete_identity_provider(store, p):
    pid, name = _req(p, "UserPoolId", "ProviderName")
    _idp(store, pid, name)
    del store.idps[pid][name]
    store.persist()
    return {}


@op
def list_identity_providers(store, p):
    (pid,) = _req(p, "UserPoolId")
    _pool(store, pid)
    items = [{"ProviderName": d["ProviderName"], "ProviderType": d["ProviderType"],
              "LastModifiedDate": d["LastModifiedDate"], "CreationDate": d["CreationDate"]}
             for d in sorted(store.idps[pid].values(), key=lambda d: d["ProviderName"])]
    chunk, nxt = _page(items, p.get("MaxResults"), p.get("NextToken"), 60)
    out = {"Providers": chunk}
    if nxt:
        out["NextToken"] = nxt
    return out


@op
def create_resource_server(store, p):
    pid, ident, name = _req(p, "UserPoolId", "Identifier", "Name")
    _pool(store, pid)
    if ident in store.servers[pid]:
        raise _err("InvalidParameterException", "A resource server with the identifier already exists.")
    d = {"UserPoolId": pid, "Identifier": ident, "Name": name, "Scopes": p.get("Scopes") or []}
    store.servers[pid][ident] = d
    store.persist()
    return {"ResourceServer": d}


def _server(store, pid, ident):
    _pool(store, pid)
    d = store.servers[pid].get(ident)
    if not d:
        raise _err("ResourceNotFoundException", f"Resource server {ident} does not exist.")
    return d


@op
def describe_resource_server(store, p):
    pid, ident = _req(p, "UserPoolId", "Identifier")
    return {"ResourceServer": _server(store, pid, ident)}


@op
def update_resource_server(store, p):
    pid, ident, name = _req(p, "UserPoolId", "Identifier", "Name")
    d = _server(store, pid, ident)
    d["Name"] = name
    d["Scopes"] = p.get("Scopes") or []
    store.persist()
    return {"ResourceServer": d}


@op
def delete_resource_server(store, p):
    pid, ident = _req(p, "UserPoolId", "Identifier")
    _server(store, pid, ident)
    del store.servers[pid][ident]
    store.persist()
    return {}


@op
def list_resource_servers(store, p):
    (pid,) = _req(p, "UserPoolId")
    _pool(store, pid)
    items = sorted(store.servers[pid].values(), key=lambda d: d["Identifier"])
    chunk, nxt = _page(items, p.get("MaxResults"), p.get("NextToken"), 50, 50)
    out = {"ResourceServers": chunk}
    if nxt:
        out["NextToken"] = nxt
    return out


def _arn_pool(store, arn):
    m = re.fullmatch(r"arn:aws:cognito-idp:[^:]+:\d+:userpool/(.+)", arn or "")
    if not m or m.group(1) not in store.pools:
        raise _err("ResourceNotFoundException", f"Resource {arn} not found.")
    return store.pools[m.group(1)]


@op
def tag_resource(store, p):
    arn, tags = _req(p, "ResourceArn", "Tags")
    _arn_pool(store, arn).setdefault("UserPoolTags", {}).update({str(k): str(v) for k, v in tags.items()})
    store.persist()
    return {}


@op
def untag_resource(store, p):
    arn, keys = _req(p, "ResourceArn", "TagKeys")
    pool = _arn_pool(store, arn)
    for k in keys:
        pool.get("UserPoolTags", {}).pop(k, None)
    store.persist()
    return {}


@op
def list_tags_for_resource(store, p):
    (arn,) = _req(p, "ResourceArn")
    return {"Tags": dict(_arn_pool(store, arn).get("UserPoolTags", {}))}


@op
def set_ui_customization(store, p):
    (pid,) = _req(p, "UserPoolId")
    _pool(store, pid)
    cid = p.get("ClientId") or "ALL"
    now = _now()
    d = {"UserPoolId": pid, "ClientId": cid, "CSS": p.get("CSS", ""), "CSSVersion": "1", "ImageUrl": "",
         "LastModifiedDate": now, "CreationDate": now}
    store.ui.setdefault(pid, {})[cid] = d
    store.persist()
    return {"UICustomization": d}


@op
def get_ui_customization(store, p):
    (pid,) = _req(p, "UserPoolId")
    _pool(store, pid)
    cid = p.get("ClientId") or "ALL"
    d = store.ui.get(pid, {}).get(cid) or {"UserPoolId": pid, "ClientId": cid}
    return {"UICustomization": d}


# ══ users ════════════════════════════════════════════════════════════════════
def _case(pool, s):
    return s if (pool.get("UsernameConfiguration") or {}).get("CaseSensitive") else s.lower()


def _find_user(store, pid, uname, must=True):
    pool = _pool(store, pid)
    users = store.users[pid]
    if uname in users:
        return users[uname]
    key = _case(pool, uname)
    for u in users.values():
        if _case(pool, u["Username"]) == key or _attr_map(u).get("sub") == uname:
            return u
    aliases = set(pool.get("UsernameAttributes") or []) | set(pool.get("AliasAttributes") or [])
    for u in users.values():
        am = _attr_map(u)
        for a in aliases:
            if a == "preferred_username" or a in ("email", "phone_number") and \
                    (am.get(a + "_verified") == "true" or a in (pool.get("UsernameAttributes") or [])):
                if am.get(a) and _case(pool, am[a]) == key:
                    return u
    if must:
        raise _err("UserNotFoundException", "User does not exist.")
    return None


def _create_user(store, pid, username, attrs, status, creating=True):
    pool = store.pools[pid]
    uattrs = pool.get("UsernameAttributes") or []
    sub = str(uuid.uuid4())
    stored = username
    if uattrs:  # email/phone usernames: the stored Username is the sub, like the real service
        if "@" in username and "email" in uattrs:
            attrs = [a for a in attrs if a.get("Name") != "email"] + [{"Name": "email", "Value": username}]
        elif username.startswith("+") and "phone_number" in uattrs:
            attrs = [a for a in attrs if a.get("Name") != "phone_number"] + [{"Name": "phone_number", "Value": username}]
        else:
            raise _err("InvalidParameterException", "Username should be an email." if uattrs == ["email"]
                       else "Username should be either an email or a phone number.")
        stored = sub
    if _find_user(store, pid, stored, must=False) or _find_user(store, pid, username, must=False):
        raise _err("UsernameExistsException", "User account already exists")
    now = _now()
    u = {"Username": stored, "Attributes": [{"Name": "sub", "Value": sub}], "UserCreateDate": now,
         "UserLastModifiedDate": now, "Enabled": True, "UserStatus": status, "_groups": [], "_pw": "", "_salt": ""}
    _set_attrs(u, attrs, pool["SchemaAttributes"], creating=True)
    store.users[pid][stored] = u
    return u


def _delivery(pool, u, preferred=None):
    am = _attr_map(u)
    for attr, medium in ((("email", "EMAIL"), ("phone_number", "SMS")) if preferred != "SMS" else (("phone_number", "SMS"), ("email", "EMAIL"))):
        if am.get(attr):
            return {"Destination": _mask(am[attr], medium), "DeliveryMedium": medium, "AttributeName": attr}
    return None


def _secret_hash_ok(c, username, given):
    if not c.get("ClientSecret"):
        return True
    if not given:
        raise _err("NotAuthorizedException", f"Unable to verify secret hash for client {c['ClientId']}")
    want = base64.b64encode(hmac.new(c["ClientSecret"].encode(), (username + c["ClientId"]).encode(), hashlib.sha256).digest()).decode()
    if not hmac.compare_digest(want, given):
        raise _err("NotAuthorizedException", f"Unable to verify secret hash for client {c['ClientId']}")
    return True


@op
def admin_create_user(store, p):
    pid, uname = _req(p, "UserPoolId", "Username")
    pool = _pool(store, pid)
    attrs = list(p.get("UserAttributes") or [])
    u = _create_user(store, pid, uname, attrs, "FORCE_CHANGE_PASSWORD")
    tmp = p.get("TemporaryPassword") or (_rand(4, "ABCDEFGH") + _rand(4, "abcdefgh") + _rand(2, "23456789") + "!")
    _check_password(pool, tmp)
    _set_password(u, tmp)
    store.persist()
    return {"User": _user_view(u, "Attributes")}


@op
def admin_get_user(store, p):
    pid, uname = _req(p, "UserPoolId", "Username")
    u = _find_user(store, pid, uname)
    v = _user_view(u, "UserAttributes")
    v["MFAOptions"] = []
    return v


@op
def admin_delete_user(store, p):
    pid, uname = _req(p, "UserPoolId", "Username")
    u = _find_user(store, pid, uname)
    _drop_user(store, pid, u)
    return {}


def _drop_user(store, pid, u):
    store.users[pid].pop(u["Username"], None)
    for t in [t for t, v in store.tokens.items() if v["pool"] == pid and v["username"] == u["Username"]]:
        store.tokens.pop(t)
    store.persist()


@op
def admin_disable_user(store, p):
    pid, uname = _req(p, "UserPoolId", "Username")
    u = _find_user(store, pid, uname)
    u["Enabled"] = False
    u["UserLastModifiedDate"] = _now()
    store.persist()
    return {}


@op
def admin_enable_user(store, p):
    pid, uname = _req(p, "UserPoolId", "Username")
    u = _find_user(store, pid, uname)
    u["Enabled"] = True
    u["UserLastModifiedDate"] = _now()
    store.persist()
    return {}


@op
def admin_confirm_sign_up(store, p):
    pid, uname = _req(p, "UserPoolId", "Username")
    u = _find_user(store, pid, uname)
    if u["UserStatus"] != "UNCONFIRMED":
        raise _err("NotAuthorizedException", f"User cannot be confirmed. Current status is {u['UserStatus']}")
    u["UserStatus"] = "CONFIRMED"
    _auto_verify(store.pools[pid], u)
    store.persist()
    return {}


def _auto_verify(pool, u):
    am = _attr_map(u)
    for a in pool.get("AutoVerifiedAttributes") or []:
        if am.get(a):
            _set_attrs(u, [{"Name": a + "_verified", "Value": "true"}], pool["SchemaAttributes"])


@op
def admin_update_user_attributes(store, p):
    pid, uname, attrs = _req(p, "UserPoolId", "Username", "UserAttributes")
    u = _find_user(store, pid, uname)
    _set_attrs(u, attrs, store.pools[pid]["SchemaAttributes"])
    store.persist()
    return {}


def _delete_attrs(store, pid, u, names):
    sch = {a["Name"]: a for a in store.pools[pid]["SchemaAttributes"]}
    am = _attr_map(u)
    for n in names:
        if n not in sch:
            raise _err("InvalidParameterException", f"Attribute does not exist in the schema: {n}")
        if sch[n].get("Required") or not sch[n].get("Mutable", True):
            raise _err("InvalidParameterException", f"user.{n} is a required attribute and cannot be deleted" if sch[n].get("Required") else f"user.{n} is not mutable")
        am.pop(n, None)
    u["Attributes"] = [{"Name": k, "Value": v} for k, v in am.items()]
    u["UserLastModifiedDate"] = _now()
    store.persist()


@op
def admin_delete_user_attributes(store, p):
    pid, uname, names = _req(p, "UserPoolId", "Username", "UserAttributeNames")
    _delete_attrs(store, pid, _find_user(store, pid, uname), names)
    return {}


@op
def admin_set_user_password(store, p):
    pid, uname, pw = _req(p, "UserPoolId", "Username", "Password")
    u = _find_user(store, pid, uname)
    _check_password(store.pools[pid], pw)
    _set_password(u, pw)
    u["UserStatus"] = "CONFIRMED" if p.get("Permanent") else "FORCE_CHANGE_PASSWORD"
    u["UserLastModifiedDate"] = _now()
    store.persist()
    return {}


@op
def admin_reset_user_password(store, p):
    pid, uname = _req(p, "UserPoolId", "Username")
    u = _find_user(store, pid, uname)
    if u["UserStatus"] == "UNCONFIRMED":
        raise _err("InvalidParameterException", "Cannot reset password for the user as there is no registered/verified email or phone_number")
    u["UserStatus"] = "RESET_REQUIRED"
    store.persist()
    return {}


@op
def admin_user_global_sign_out(store, p):
    pid, uname = _req(p, "UserPoolId", "Username")
    _sign_out(store, pid, _find_user(store, pid, uname))
    return {}


def _sign_out(store, pid, u):
    u["_sessions"] = []
    for t in [t for t, v in store.tokens.items() if v["pool"] == pid and v["username"] == u["Username"]]:
        store.tokens.pop(t)
    store.persist()


@op
def admin_set_user_mfa_preference(store, p):
    pid, uname = _req(p, "UserPoolId", "Username")
    _find_user(store, pid, uname)
    return {}


@op
def admin_set_user_settings(store, p):
    pid, uname = _req(p, "UserPoolId", "Username")
    _find_user(store, pid, uname)
    return {}


@op
def list_users(store, p):
    (pid,) = _req(p, "UserPoolId")
    pool = _pool(store, pid)
    users = sorted(store.users[pid].values(), key=lambda u: u["UserCreateDate"])
    flt = (p.get("Filter") or "").strip()
    if flt:
        m = re.fullmatch(r'\s*([\w:]+)\s*(=|\^=)\s*"(.*)"\s*', flt)
        if not m:
            raise _err("InvalidParameterException", f"Error while parsing filter: {flt}")
        attr, opr, val = m.groups()
        okattrs = {"username", "email", "phone_number", "name", "given_name", "family_name", "preferred_username",
                   "cognito:user_status", "status", "sub"}
        if attr not in okattrs:
            raise _err("InvalidParameterException", f"Invalid search attribute: {attr}")

        def get(u):
            if attr == "username":
                return u["Username"]
            if attr in ("cognito:user_status", "status"):
                return {"cognito:user_status": u["UserStatus"], "status": "Enabled" if u["Enabled"] else "Disabled"}[attr]
            return _attr_map(u).get(attr, "")
        users = [u for u in users if (get(u) == val if opr == "=" else get(u).startswith(val))]
    want = p.get("AttributesToGet")
    views = []
    for u in users:
        v = _user_view(u, "Attributes")
        if want is not None:
            v["Attributes"] = [a for a in v["Attributes"] if a["Name"] in want]
        views.append(v)
    chunk, nxt = _page(views, p.get("Limit"), p.get("PaginationToken"), 60)
    out = {"Users": chunk}
    if nxt:
        out["PaginationToken"] = nxt
    return out


# ══ self-service sign-up / account ═══════════════════════════════════════════
@op
def sign_up(store, p):
    cid, uname, pw = _req(p, "ClientId", "Username", "Password")
    pid, c = _find_client(store, cid)
    pool = store.pools[pid]
    _secret_hash_ok(c, uname, p.get("SecretHash"))
    if (pool.get("AdminCreateUserConfig") or {}).get("AllowAdminCreateUserOnly"):
        raise _err("NotAuthorizedException", "SignUp is not permitted for this user pool")
    _check_password(pool, pw)
    u = _create_user(store, pid, uname, list(p.get("UserAttributes") or []), "UNCONFIRMED")
    _set_password(u, pw)
    u["_code"] = FIXED_CODE
    store.persist()
    out = {"UserConfirmed": False, "UserSub": _attr_map(u)["sub"]}
    d = _delivery(pool, u) if pool.get("AutoVerifiedAttributes") else None
    if d:
        out["CodeDeliveryDetails"] = d
    return out


@op
def confirm_sign_up(store, p):
    cid, uname, code = _req(p, "ClientId", "Username", "ConfirmationCode")
    pid, c = _find_client(store, cid)
    _secret_hash_ok(c, uname, p.get("SecretHash"))
    u = _find_user(store, pid, uname)
    if u["UserStatus"] != "UNCONFIRMED":
        raise _err("NotAuthorizedException", f"User cannot be confirmed. Current status is {u['UserStatus']}")
    if code != u.get("_code", FIXED_CODE):
        raise _err("CodeMismatchException", "Invalid verification code provided, please try again.")
    u["UserStatus"] = "CONFIRMED"
    u.pop("_code", None)
    _auto_verify(store.pools[pid], u)
    store.persist()
    return {}


@op
def resend_confirmation_code(store, p):
    cid, uname = _req(p, "ClientId", "Username")
    pid, c = _find_client(store, cid)
    _secret_hash_ok(c, uname, p.get("SecretHash"))
    u = _find_user(store, pid, uname)
    if u["UserStatus"] != "UNCONFIRMED":
        raise _err("InvalidParameterException", "User is already confirmed.")
    d = _delivery(store.pools[pid], u)
    if not d:
        raise _err("InvalidParameterException", "Cannot resend codes. Auto verification not turned on.")
    u["_code"] = FIXED_CODE
    return {"CodeDeliveryDetails": d}


@op
def forgot_password(store, p):
    cid, uname = _req(p, "ClientId", "Username")
    pid, c = _find_client(store, cid)
    _secret_hash_ok(c, uname, p.get("SecretHash"))
    u = _find_user(store, pid, uname)
    am = _attr_map(u)
    if u["UserStatus"] == "UNCONFIRMED" or not (am.get("email_verified") == "true" or am.get("phone_number_verified") == "true"):
        raise _err("InvalidParameterException", "Cannot reset password for the user as there is no registered/verified email or phone_number")
    d = _delivery(store.pools[pid], u)
    u["_reset_code"] = FIXED_CODE
    store.persist()
    return {"CodeDeliveryDetails": d}


@op
def confirm_forgot_password(store, p):
    cid, uname, code, pw = _req(p, "ClientId", "Username", "ConfirmationCode", "Password")
    pid, c = _find_client(store, cid)
    _secret_hash_ok(c, uname, p.get("SecretHash"))
    u = _find_user(store, pid, uname)
    _check_password(store.pools[pid], pw)
    if code != u.get("_reset_code"):
        raise _err("CodeMismatchException", "Invalid verification code provided, please try again.")
    _set_password(u, pw)
    u["UserStatus"] = "CONFIRMED"
    u.pop("_reset_code", None)
    _sign_out(store, pid, u)
    return {}


# access-token based (self) operations ------------------------------------------------
def _from_access_token(store, tok):
    claims = _jwt_verify(tok or "")
    if claims.get("token_use") != "access" or claims.get("exp", 0) < time.time():
        raise _err("NotAuthorizedException", "Access Token has expired" if claims.get("exp", 0) < time.time() else "Invalid Access Token")
    pid = claims["iss"].rsplit("/", 1)[-1]
    if pid not in store.pools:
        raise _err("NotAuthorizedException", "Invalid Access Token")
    u = _find_user(store, pid, claims.get("username", ""), must=False)
    if not u:
        raise _err("UserNotFoundException", "User does not exist.")
    if claims.get("origin_jti") not in u.get("_sessions", []):
        raise _err("NotAuthorizedException", "Access Token has been revoked")
    if not u["Enabled"]:
        raise _err("NotAuthorizedException", "User is disabled.")
    return pid, u


@op
def get_user(store, p):
    (tok,) = _req(p, "AccessToken")
    pid, u = _from_access_token(store, tok)
    v = _user_view(u, "UserAttributes")
    return {"Username": v["Username"], "UserAttributes": v["UserAttributes"], "MFAOptions": []}


@op
def update_user_attributes(store, p):
    tok, attrs = _req(p, "AccessToken", "UserAttributes")
    pid, u = _from_access_token(store, tok)
    _set_attrs(u, attrs, store.pools[pid]["SchemaAttributes"])
    out = []
    for a in attrs:
        if a["Name"] in ("email", "phone_number") and a["Name"] in (store.pools[pid].get("AutoVerifiedAttributes") or []):
            _set_attrs(u, [{"Name": a["Name"] + "_verified", "Value": "false"}], store.pools[pid]["SchemaAttributes"])
            out.append({"Destination": _mask(a["Value"], "EMAIL" if a["Name"] == "email" else "SMS"),
                        "DeliveryMedium": "EMAIL" if a["Name"] == "email" else "SMS", "AttributeName": a["Name"]})
            u["_verify_" + a["Name"]] = FIXED_CODE
    store.persist()
    return {"CodeDeliveryDetailsList": out}


@op
def delete_user_attributes(store, p):
    tok, names = _req(p, "AccessToken", "UserAttributeNames")
    pid, u = _from_access_token(store, tok)
    _delete_attrs(store, pid, u, names)
    return {}


@op
def get_user_attribute_verification_code(store, p):
    tok, name = _req(p, "AccessToken", "AttributeName")
    pid, u = _from_access_token(store, tok)
    if name not in ("email", "phone_number") or not _attr_map(u).get(name):
        raise _err("InvalidParameterException", f"No {name} to verify")
    u["_verify_" + name] = FIXED_CODE
    medium = "EMAIL" if name == "email" else "SMS"
    return {"CodeDeliveryDetails": {"Destination": _mask(_attr_map(u)[name], medium), "DeliveryMedium": medium, "AttributeName": name}}


@op
def verify_user_attribute(store, p):
    tok, name, code = _req(p, "AccessToken", "AttributeName", "Code")
    pid, u = _from_access_token(store, tok)
    if code != u.get("_verify_" + name):
        raise _err("CodeMismatchException", "Invalid verification code provided, please try again.")
    _set_attrs(u, [{"Name": name + "_verified", "Value": "true"}], store.pools[pid]["SchemaAttributes"])
    u.pop("_verify_" + name, None)
    store.persist()
    return {}


@op
def change_password(store, p):
    old, new, tok = _req(p, "PreviousPassword", "ProposedPassword", "AccessToken")
    pid, u = _from_access_token(store, tok)
    if not _pw_ok(u, old):
        raise _err("NotAuthorizedException", "Incorrect username or password.")
    _check_password(store.pools[pid], new)
    _set_password(u, new)
    store.persist()
    return {}


@op
def delete_user(store, p):
    (tok,) = _req(p, "AccessToken")
    pid, u = _from_access_token(store, tok)
    _drop_user(store, pid, u)
    return {}


@op
def global_sign_out(store, p):
    (tok,) = _req(p, "AccessToken")
    pid, u = _from_access_token(store, tok)
    _sign_out(store, pid, u)
    return {}


@op
def set_user_mfa_preference(store, p):
    (tok,) = _req(p, "AccessToken")
    _from_access_token(store, tok)
    return {}


@op
def set_user_settings(store, p):
    (tok,) = _req(p, "AccessToken")
    _from_access_token(store, tok)
    return {}


@op
def revoke_token(store, p):
    tok, cid = _req(p, "Token", "ClientId")
    pid, c = _find_client(store, cid)
    if c.get("ClientSecret") and p.get("ClientSecret") != c["ClientSecret"]:
        raise _err("UnauthorizedException", "Unauthorized")
    if tok not in store.tokens or store.tokens[tok]["client"] != cid:
        raise _err("InvalidParameterException", "Invalid refresh token")
    rec = store.tokens.pop(tok)
    u = _find_user(store, pid, rec["username"], must=False)
    if u and rec["origin_jti"] in u.get("_sessions", []):
        u["_sessions"].remove(rec["origin_jti"])
    store.persist()
    return {}


# ══ authentication ═══════════════════════════════════════════════════════════
_UNIT = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}


def _validity(c, kind):
    units = (c.get("TokenValidityUnits") or {})
    default_u = {"AccessToken": "minutes", "IdToken": "minutes", "RefreshToken": "days"}[kind]
    n = c.get({"AccessToken": "AccessTokenValidity", "IdToken": "IdTokenValidity", "RefreshToken": "RefreshTokenValidity"}[kind])
    n = n if n is not None else (30 if kind == "RefreshToken" else 60)
    return int(n) * _UNIT[units.get(kind, default_u)]


def _issue(store, pid, u, c, origin_jti=None, refresh=None):
    now = int(time.time())
    origin_jti = origin_jti or str(uuid.uuid4())
    sess = u.setdefault("_sessions", [])
    if origin_jti not in sess:
        sess.append(origin_jti)
        del sess[:-100]
    iss = f"https://cognito-idp.{store.region}.amazonaws.com/{pid}"
    am = _attr_map(u)
    groups = [g for g in u["_groups"] if g in store.groups[pid]]
    base = {"sub": am["sub"], "iss": iss, "origin_jti": origin_jti, "event_id": str(uuid.uuid4()),
            "auth_time": now, "iat": now}
    if groups:
        base["cognito:groups"] = groups
    idc = dict(base, aud=c["ClientId"], token_use="id", jti=str(uuid.uuid4()),
               exp=now + _validity(c, "IdToken")); idc["cognito:username"] = u["Username"]
    for k in ("email", "email_verified", "phone_number", "phone_number_verified", "name", "given_name", "family_name",
              "preferred_username"):
        if k in am:
            idc[k] = (am[k] == "true") if k.endswith("_verified") else am[k]
    for k, v in am.items():
        if k.startswith("custom:"):
            idc[k] = v
    acc = dict(base, client_id=c["ClientId"], token_use="access", scope="aws.cognito.signin.user.admin",
               jti=str(uuid.uuid4()), exp=now + _validity(c, "AccessToken"), username=u["Username"], version=2)
    if refresh is None:
        refresh = _b64u(_secrets.token_bytes(48))
        store.tokens[refresh] = {"pool": pid, "username": u["Username"], "client": c["ClientId"],
                                 "origin_jti": origin_jti, "exp": now + _validity(c, "RefreshToken")}
    res = {"AccessToken": _jwt(acc), "ExpiresIn": _validity(c, "AccessToken"), "TokenType": "Bearer",
           "IdToken": _jwt(idc)}
    if refresh:
        res["RefreshToken"] = refresh
    store.persist()
    return res


def _flow_enabled(c, *names):
    flows = c.get("ExplicitAuthFlows") or []
    return any(n in flows for n in names)


def _login(store, pid, c, params, admin=False):
    uname = params.get("USERNAME")
    pw = params.get("PASSWORD")
    if not uname or pw is None:
        raise _err("InvalidParameterException", "Missing required parameter USERNAME" if not uname else "Missing required parameter PASSWORD")
    legacy = c.get("PreventUserExistenceErrors") == "ENABLED"
    u = _find_user(store, pid, uname, must=False)
    if not u:
        if legacy:
            raise _err("NotAuthorizedException", "Incorrect username or password.")
        raise _err("UserNotFoundException", "User does not exist.")
    _secret_hash_ok(c, uname, params.get("SECRET_HASH"))
    if not _pw_ok(u, pw):
        raise _err("NotAuthorizedException", "Incorrect username or password.")
    if not u["Enabled"]:
        raise _err("NotAuthorizedException", "User is disabled.")
    if u["UserStatus"] == "UNCONFIRMED":
        raise _err("UserNotConfirmedException", "User is not confirmed.")
    if u["UserStatus"] == "RESET_REQUIRED":
        raise _err("PasswordResetRequiredException", "Password reset required for the user")
    if u["UserStatus"] == "FORCE_CHANGE_PASSWORD":
        sess = _b64u(_secrets.token_bytes(40))
        store.sessions[sess] = {"pool": pid, "username": u["Username"], "client": c["ClientId"], "exp": time.time() + 180}
        am = {k: v for k, v in _attr_map(u).items() if k not in ("sub", "email_verified", "phone_number_verified")}
        return {"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": sess,
                "ChallengeParameters": {"USER_ID_FOR_SRP": u["Username"], "requiredAttributes": "[]",
                                        "userAttributes": json.dumps(am)}}
    u["_last_login"] = _now()
    return {"AuthenticationResult": _issue(store, pid, u, c), "ChallengeParameters": {}}


def _refresh(store, pid, c, params):
    tok = params.get("REFRESH_TOKEN")
    rec = store.tokens.get(tok or "")
    if not rec or rec["client"] != c["ClientId"] or rec["exp"] < time.time():
        raise _err("NotAuthorizedException", "Invalid Refresh Token")
    u = _find_user(store, pid, rec["username"], must=False)
    if not u or not u["Enabled"]:
        raise _err("NotAuthorizedException", "Invalid Refresh Token")
    _secret_hash_ok(c, rec["username"], params.get("SECRET_HASH"))
    r = _issue(store, pid, u, c, origin_jti=rec["origin_jti"], refresh=False)
    return {"AuthenticationResult": r, "ChallengeParameters": {}}


def _auth(store, pid, c, flow, params, admin):
    if flow == "USER_SRP_AUTH" or flow == "CUSTOM_AUTH" or flow == "USER_AUTH":
        raise _err("UnsupportedOperationException", f"{flow} is not supported by this emulator (use USER_PASSWORD_AUTH).")
    if flow in ("REFRESH_TOKEN_AUTH", "REFRESH_TOKEN"):
        if not _flow_enabled(c, "ALLOW_REFRESH_TOKEN_AUTH", "CUSTOM_AUTH_FLOW_ONLY", "ADMIN_NO_SRP_AUTH", "USER_PASSWORD_AUTH"):
            raise _err("InvalidParameterException", f"{flow} flow not enabled for this client")
        return _refresh(store, pid, c, params)
    if flow == "USER_PASSWORD_AUTH" and not admin:
        if not _flow_enabled(c, "ALLOW_USER_PASSWORD_AUTH", "USER_PASSWORD_AUTH"):
            raise _err("InvalidParameterException", "USER_PASSWORD_AUTH flow not enabled for this client")
        return _login(store, pid, c, params)
    if flow in ("ADMIN_USER_PASSWORD_AUTH", "ADMIN_NO_SRP_AUTH") and admin:
        if not _flow_enabled(c, "ALLOW_ADMIN_USER_PASSWORD_AUTH", "ADMIN_NO_SRP_AUTH"):
            raise _err("InvalidParameterException", f"{flow} flow not enabled for this client")
        return _login(store, pid, c, params, admin=True)
    raise _err("InvalidParameterException", "Initiate Auth method not supported")


@op
def initiate_auth(store, p):
    flow, cid = _req(p, "AuthFlow", "ClientId")
    pid, c = _find_client(store, cid)
    return _auth(store, pid, c, flow, p.get("AuthParameters") or {}, admin=False)


@op
def admin_initiate_auth(store, p):
    pid, cid, flow = _req(p, "UserPoolId", "ClientId", "AuthFlow")
    c = _client(store, pid, cid)
    return _auth(store, pid, c, flow, p.get("AuthParameters") or {}, admin=True)


def _respond(store, c, p, pid=None):
    name, = _req(p, "ChallengeName")
    sess = store.sessions.get(p.get("Session") or "")
    resp = p.get("ChallengeResponses") or {}
    if name != "NEW_PASSWORD_REQUIRED":
        raise _err("UnsupportedOperationException", f"Challenge {name} is not supported by this emulator.")
    if not sess or sess["exp"] < time.time() or sess["client"] != c["ClientId"]:
        raise _err("NotAuthorizedException", "Invalid session for the user, session is expired.")
    u = _find_user(store, sess["pool"], sess["username"])
    pw = resp.get("NEW_PASSWORD")
    if not pw:
        raise _err("InvalidParameterException", "Missing required parameter NEW_PASSWORD")
    _secret_hash_ok(c, resp.get("USERNAME", sess["username"]), resp.get("SECRET_HASH"))
    _check_password(store.pools[sess["pool"]], pw)
    _set_password(u, pw)
    u["UserStatus"] = "CONFIRMED"
    for k, v in resp.items():
        if k.startswith("userAttributes."):
            _set_attrs(u, [{"Name": k[len("userAttributes."):], "Value": v}], store.pools[sess["pool"]]["SchemaAttributes"])
    store.sessions.pop(p["Session"], None)
    return {"ChallengeParameters": {}, "AuthenticationResult": _issue(store, sess["pool"], u, c)}


@op
def respond_to_auth_challenge(store, p):
    (cid,) = _req(p, "ClientId")
    _, c = _find_client(store, cid)
    return _respond(store, c, p)


@op
def admin_respond_to_auth_challenge(store, p):
    pid, cid = _req(p, "UserPoolId", "ClientId")
    return _respond(store, _client(store, pid, cid), p)


# ══ dispatch ═════════════════════════════════════════════════════════════════
def operations() -> list:
    return sorted(_OPS)


def _result(status, body, code=None):
    h = {"x-amzn-requestid": str(uuid.uuid4())}
    if code:
        h["x-amzn-errortype"] = code
    return CognitoResponse(status=status, body=body, headers=h)


def dispatch(store: CognitoIdpStore, target: str, payload: dict | None = None) -> CognitoResponse:
    """Native Cognito IDP JSON-1.1 router. `target` is the X-Amz-Target header
    value (`AWSCognitoIdentityProviderService.CreateUserPool`)."""
    payload = payload if isinstance(payload, dict) else {}
    action = (target or "").split(".", 1)[-1].strip()
    fn = _OPS.get(action)
    if fn is None:
        if action and re.fullmatch(r"[A-Z][A-Za-z]+", action) and action in _MODEL_OPS:
            return _result(400, {"__type": "UnsupportedOperationException",
                                 "message": f"{action} is not implemented by this emulator."}, "UnsupportedOperationException")
        return _result(400, {"__type": "com.amazon.coral.service#UnknownOperationException", "message": ""},
                       "com.amazon.coral.service#UnknownOperationException")
    try:
        return _result(200, fn(store, payload))
    except CognitoError as e:
        return _result(e.status, {"__type": e.code, "message": e.message}, e.code)


_MODEL_OPS = set("""AddUserPoolClientSecret AdminDeleteSoftwareToken AdminDisableProviderForUser AdminForgetDevice AdminGetDevice
AdminGetUserAuthFactors AdminLinkProviderForUser AdminListDevices AdminListUserAuthEvents AdminUpdateAuthEventFeedback
AdminUpdateDeviceStatus AssociateSoftwareToken CompleteWebAuthnRegistration ConfirmDevice CreateManagedLoginBranding CreateTerms
CreateUserImportJob CreateUserPoolReplica DeleteManagedLoginBranding DeleteTerms DeleteUserPoolClientSecret DeleteUserPoolReplica
DeleteWebAuthnCredential DescribeManagedLoginBranding DescribeManagedLoginBrandingByClient DescribeRiskConfiguration DescribeTerms
DescribeTermsByClient DescribeUserImportJob ForgetDevice GetClientToken GetDevice GetLogDeliveryConfiguration GetProvisionedLimit
GetSigningCertificate GetTokensFromRefreshToken GetUserAuthFactors ListDevices ListTerms ListUserImportJobs
ListUserPoolClientSecrets ListUserPoolReplicas ListWebAuthnCredentials SetLogDeliveryConfiguration SetRiskConfiguration
StartUserImportJob StartWebAuthnRegistration StopUserImportJob UpdateAuthEventFeedback UpdateDeviceStatus
UpdateManagedLoginBranding UpdateProvisionedLimit UpdateTerms UpdateUserPoolReplica VerifySoftwareToken""".split())
