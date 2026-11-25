# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Pure-Python Cognito user pools + WAFv2 engine (no moto / flask / joserfc / cryptography): the Nano (Pyodide) backend.

core/identity_core.py is the wire adapter the router already calls. On the appliance it drives moto when moto is installed; where moto is
absent (Nano in the browser) it drives THIS module instead, so boto3 works unmodified against both. The module has no sockets and no
third-party imports, so it loads in Pyodide.

Cognito (JSON 1.1, X-Amz-Target AWSCognitoIdentityProviderService.*):
  pools / app clients (secret + SECRET_HASH), AdminCreateUser / AdminSetUserPassword / SignUp / ConfirmSignUp / AdminConfirmSignUp,
  InitiateAuth + AdminInitiateAuth (USER_PASSWORD_AUTH, ADMIN_USER_PASSWORD_AUTH, REFRESH_TOKEN_AUTH) returning RS256 id/access/refresh tokens,
  NEW_PASSWORD_REQUIRED challenge, GetUser, GlobalSignOut, ChangePassword, groups, ListUsers filters, the pool JWKS + OIDC discovery.
WAFv2 (JSON 1.1, X-Amz-Target AWSWAF_20190729.*):
  web ACL / IP set / regex pattern set CRUD with lock tokens, Associate/Disassociate/GetWebACLForResource, CheckCapacity, managed rule group listing.
  Enforcement (waf_check in identity_core) understands byte match, IP set, size, regex, SQLi/XSS, rate-based, And/Or/Not and a signature-subset STUB
  of the AWS managed rule groups (Common, SQLi, KnownBadInputs, AdminProtection; IpReputation/AnonymousIp never match).
Declared limits: state is process-local (a page reload starts empty); one static RSA signing key shared by every pool (a simulator key, not a
secret); no SRP / MFA / federation / email or SMS delivery (ConfirmSignUp accepts any non-empty code, as moto does); managed rule groups are
signature stubs, not the AWS rule sets.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid

ACCOUNT = "123456789012"
DEFAULT_REGION = "us-east-1"
_N = 17279139731159838914213605647222369863946098281741445353762454191602282831969419520595485684134895991646743008755991440214805409819182896950485389320894917683704533238456630334850047935260569544082932753035568070915033103930000120666853302317296089606100237038499966300807320195753279992790810700705422533950697041626005451040528190695227506941201430462094812633919507718731230833212191129691994452202183235473909114763512372114307720875948025657672925326169213046168753236314437306605645345661717648442915408869754908998495426849326306311089296515714222896253231420231663200482242457375873229090665623234042168092049
_E = 65537
_D = 2059187346948749590203406152846197502160047280113233417058715854841983855910704304831939857495881108037083439210711798627508115796005131284609446645829726560508003448655762277088789783619038480566372969315042788478644038948135495100908424757238435425870025603504246763462196498906964650355702835156112336958388117366478506795543043177151643033565665498783206616077615851011128215143035786141151413627607257138494212210285837656217754211596150110279915442450571561543093070756444219332607419555622642379913461135451403726884832393261062665036584975406790334388187576981642072416256118060837837574658431853983529340423
KID = "vyomi-cognito-key-1"
_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


# ───────────────────────────── RS256 in pure Python ─────────────────────────────
def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _emsa(msg, k):
    t = _SHA256_PREFIX + hashlib.sha256(msg).digest()
    return b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t


def rs256_sign(msg: bytes) -> bytes:
    k = (_N.bit_length() + 7) // 8
    return pow(int.from_bytes(_emsa(msg, k), "big"), _D, _N).to_bytes(k, "big")


def rs256_verify(msg: bytes, sig: bytes, n: int, e: int) -> bool:
    """PKCS#1 v1.5 / SHA-256 verify with the public numbers only (used by gateway_common when `cryptography` is not installed)."""
    k = (n.bit_length() + 7) // 8
    if len(sig) != k:
        return False
    return hmac.compare_digest(pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big"), _emsa(msg, k))


def jwk():
    return {"alg": "RS256", "e": _b64u(_E.to_bytes(3, "big")), "kid": KID, "kty": "RSA", "n": _b64u(_N.to_bytes((_N.bit_length() + 7) // 8, "big")), "use": "sig"}


def jwt_encode(claims):
    h = _b64u(json.dumps({"kid": KID, "alg": "RS256"}, separators=(",", ":")).encode())
    p = _b64u(json.dumps(claims, separators=(",", ":")).encode())
    return "%s.%s.%s" % (h, p, _b64u(rs256_sign(("%s.%s" % (h, p)).encode())))


def jwt_decode(tok):
    """-> claims dict when the signature verifies, else None (expiry is the caller's business)."""
    try:
        h, p, s = tok.split(".")
        if json.loads(_b64d(h)).get("alg") != "RS256" or not rs256_verify(("%s.%s" % (h, p)).encode(), _b64d(s), _N, _E):
            return None
        return json.loads(_b64d(p))
    except Exception:
        return None


# ───────────────────────────── shared helpers ─────────────────────────────
class Err(Exception):
    def __init__(self, code, msg, status=400):
        super().__init__(msg)
        self.code, self.msg, self.status = code, msg, status


def _resp(status, doc, extra=None):
    h = {"content-type": "application/x-amz-json-1.1"}
    h.update(extra or {})
    return {"status": status, "headers": h, "body": json.dumps(doc).encode()}


def _error(e):
    return _resp(e.status, {"__type": e.code, "message": e.msg}, {"x-amzn-errortype": e.code})


def region_of(lheaders):
    m = re.search(r"Credential=[^/]+/\d+/([a-z0-9-]+)/", (lheaders or {}).get("authorization", "") or "")
    return m.group(1) if m else DEFAULT_REGION


def _rid(n=9):
    return "".join(secrets.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(n))


def _need(d, *names):
    for n in names:
        if d.get(n) in (None, ""):
            raise Err("InvalidParameterException", "1 validation error detected: Value null at '%s' failed to satisfy constraint: Member must not be null" % (n[0].lower() + n[1:]))


# ───────────────────────────── Cognito user pools ─────────────────────────────
POOLS: dict = {}      # pool id -> pool dict
CLIENTS: dict = {}    # client id -> client dict
_REFRESH: dict = {}   # refresh token -> {pool, user, client}
_SESSIONS: dict = {}  # challenge session -> {pool, user, client}
_DOMAINS: dict = {}


def reset():
    for d in (POOLS, CLIENTS, _REFRESH, _SESSIONS, _DOMAINS, _WACLS, _IPSETS, _REGEXSETS, _TAGS, _IDPOOLS):
        d.clear()


def _pool(pid):
    p = POOLS.get(pid)
    if not p:
        raise Err("ResourceNotFoundException", "User pool %s does not exist." % pid)
    return p


def _client(cid, pid=None):
    c = CLIENTS.get(cid)
    if not c or (pid and c["UserPoolId"] != pid):
        raise Err("ResourceNotFoundException", "User pool client %s does not exist." % cid)
    return c


def _pool_view(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}


_DEFAULT_POLICY = {"PasswordPolicy": {"MinimumLength": 8, "RequireUppercase": True, "RequireLowercase": True, "RequireNumbers": True, "RequireSymbols": True,
                                      "TemporaryPasswordValidityDays": 7}}


def _create_pool(r, region):
    _need(r, "PoolName")
    pid = "%s_%s" % (region, _rid(9))
    now = time.time()
    pol = json.loads(json.dumps(r.get("Policies") or _DEFAULT_POLICY))
    pol.setdefault("PasswordPolicy", {}).update({**_DEFAULT_POLICY["PasswordPolicy"], **pol.get("PasswordPolicy", {})})
    p = {"Id": pid, "Name": r["PoolName"], "Policies": pol, "DeletionProtection": r.get("DeletionProtection", "INACTIVE"), "LambdaConfig": r.get("LambdaConfig") or {},
         "LastModifiedDate": now, "CreationDate": now, "SchemaAttributes": r.get("Schema") or [], "AutoVerifiedAttributes": r.get("AutoVerifiedAttributes") or [],
         "UsernameAttributes": r.get("UsernameAttributes") or [], "AliasAttributes": r.get("AliasAttributes") or [], "MfaConfiguration": r.get("MfaConfiguration", "OFF"),
         "EstimatedNumberOfUsers": 0, "AdminCreateUserConfig": r.get("AdminCreateUserConfig") or {"AllowAdminCreateUserOnly": False, "UnusedAccountValidityDays": 7},
         "UserPoolTags": r.get("UserPoolTags") or {}, "Arn": "arn:aws:cognito-idp:%s:%s:userpool/%s" % (region, ACCOUNT, pid),
         "AccountRecoverySetting": r.get("AccountRecoverySetting") or {"RecoveryMechanisms": [{"Priority": 1, "Name": "verified_email"}, {"Priority": 2, "Name": "verified_phone_number"}]},
         "UserPoolTier": r.get("UserPoolTier", "ESSENTIALS"), "_users": {}, "_groups": {}, "_region": region}
    POOLS[pid] = p
    return {"UserPool": _pool_view(p)}


def _flows(fl):
    out = []
    for f in fl or []:
        f = {"ADMIN_NO_SRP_AUTH": "ALLOW_ADMIN_USER_PASSWORD_AUTH", "CUSTOM_FLOW_ONLY": "ALLOW_CUSTOM_AUTH", "USER_PASSWORD_AUTH": "ALLOW_USER_PASSWORD_AUTH"}.get(f, f)
        out.append(f)
    return out


def _create_client(r):
    p = _pool(r.get("UserPoolId"))
    _need(r, "ClientName")
    cid = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(26))
    now = time.time()
    c = {"UserPoolId": p["Id"], "ClientName": r["ClientName"], "ClientId": cid,
         "ExplicitAuthFlows": _flows(r.get("ExplicitAuthFlows")) or ["ALLOW_CUSTOM_AUTH", "ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
         "RefreshTokenValidity": r.get("RefreshTokenValidity", 30), "AccessTokenValidity": r.get("AccessTokenValidity", 60), "IdTokenValidity": r.get("IdTokenValidity", 60),
         "TokenValidityUnits": r.get("TokenValidityUnits") or {"AccessToken": "minutes", "IdToken": "minutes", "RefreshToken": "days"},
         "CallbackURLs": r.get("CallbackURLs") or [], "LogoutURLs": r.get("LogoutURLs") or [], "AllowedOAuthFlows": r.get("AllowedOAuthFlows") or [],
         "AllowedOAuthScopes": r.get("AllowedOAuthScopes") or [], "AllowedOAuthFlowsUserPoolClient": bool(r.get("AllowedOAuthFlowsUserPoolClient")),
         "SupportedIdentityProviders": r.get("SupportedIdentityProviders") or [], "PreventUserExistenceErrors": r.get("PreventUserExistenceErrors", "ENABLED"),
         "EnableTokenRevocation": r.get("EnableTokenRevocation", True), "ReadAttributes": r.get("ReadAttributes") or [], "WriteAttributes": r.get("WriteAttributes") or [],
         "CreationDate": now, "LastModifiedDate": now}
    if r.get("GenerateSecret"):
        c["ClientSecret"] = secrets.token_hex(26)
    CLIENTS[cid] = c
    return {"UserPoolClient": dict(c)}


def _unit_secs(v, unit):
    return int(v) * {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}.get(unit, 60)


def _attrs_list(u):
    return [{"Name": k, "Value": v} for k, v in u["attrs"].items()]


def _user_view(u, key="Attributes"):
    return {"Username": u["Username"], key: _attrs_list(u), "UserCreateDate": u["created"], "UserLastModifiedDate": u["modified"], "Enabled": u["enabled"], "UserStatus": u["status"]}


def _find_user(p, name, must=True):
    users = p["_users"]
    if name in users:
        return users[name]
    for u in users.values():
        if u["attrs"].get("sub") == name:
            return u
        for a in set(p["UsernameAttributes"] + p["AliasAttributes"]):
            if a in ("email", "phone_number") and u["attrs"].get(a, "").lower() == str(name).lower():
                return u
    if must:
        raise Err("UserNotFoundException", "User does not exist.")
    return None


def _check_password(p, pw):
    pol = p["Policies"]["PasswordPolicy"]
    bad = (len(pw or "") < pol["MinimumLength"] or (pol["RequireUppercase"] and not re.search(r"[A-Z]", pw)) or (pol["RequireLowercase"] and not re.search(r"[a-z]", pw))
           or (pol["RequireNumbers"] and not re.search(r"\d", pw)) or (pol["RequireSymbols"] and not re.search(r"[^\w\s]|_", pw)))
    if bad:
        raise Err("InvalidPasswordException", "Password did not conform with policy: Password not long enough" if len(pw or "") < pol["MinimumLength"]
                  else "Password did not conform with policy")


def _hash(pw, salt):
    return hashlib.sha256((salt + pw).encode()).hexdigest()


def _set_password(u, pw):
    u["salt"] = secrets.token_hex(8)
    u["pw"] = _hash(pw, u["salt"])


def _new_user(p, username, attrs, status, password=None):
    if _find_user(p, username, must=False):
        raise Err("UsernameExistsException", "User account already exists")
    now = time.time()
    sub = str(uuid.uuid4())
    a = {"sub": sub}
    for x in attrs or []:
        a[x["Name"]] = x.get("Value", "")
    uname = sub if (set(p["UsernameAttributes"]) & {"email", "phone_number"}) else username
    u = {"Username": uname, "attrs": a, "status": status, "enabled": True, "created": now, "modified": now, "groups": [], "pw": None, "salt": "", "signout": 0}
    if password is not None:
        _set_password(u, password)
    p["_users"][uname] = u
    p["EstimatedNumberOfUsers"] = len(p["_users"])
    return u


def _secret_hash_ok(c, username, given):
    if not c.get("ClientSecret"):
        return True
    want = base64.b64encode(hmac.new(c["ClientSecret"].encode(), (username + c["ClientId"]).encode(), hashlib.sha256).digest()).decode()
    return bool(given) and hmac.compare_digest(want, given)


def _issue(p, u, c, region, refresh=True):
    now = int(time.time())
    iss = "https://cognito-idp.%s.amazonaws.com/%s" % (p["_region"], p["Id"])
    tu = c["TokenValidityUnits"]
    groups = list(u["groups"])
    common = {"sub": u["attrs"]["sub"], "iss": iss, "auth_time": now, "iat": now}
    idc = dict(common, **{"cognito:username": u["Username"], "aud": c["ClientId"], "token_use": "id", "event_id": str(uuid.uuid4()), "jti": str(uuid.uuid4()),
                          "origin_jti": str(uuid.uuid4()), "exp": now + _unit_secs(c["IdTokenValidity"], tu.get("IdToken", "minutes"))})
    for k, v in u["attrs"].items():
        if k != "sub":
            idc[k] = (v.lower() == "true") if k in ("email_verified", "phone_number_verified") else v
    acc = dict(common, **{"client_id": c["ClientId"], "token_use": "access", "scope": "aws.cognito.signin.user.admin", "username": u["Username"], "version": 2,
                          "event_id": str(uuid.uuid4()), "jti": str(uuid.uuid4()), "origin_jti": str(uuid.uuid4()),
                          "exp": now + _unit_secs(c["AccessTokenValidity"], tu.get("AccessToken", "minutes"))})
    if groups:
        idc["cognito:groups"] = groups
        acc["cognito:groups"] = groups
    res = {"AccessToken": jwt_encode(acc), "ExpiresIn": acc["exp"] - now, "TokenType": "Bearer", "IdToken": jwt_encode(idc)}
    if refresh:
        rt = "vyomi." + secrets.token_urlsafe(48)
        _REFRESH[rt] = {"pool": p["Id"], "user": u["Username"], "client": c["ClientId"], "exp": now + _unit_secs(c["RefreshTokenValidity"], tu.get("RefreshToken", "days"))}
        res["RefreshToken"] = rt
    return res


def _challenge_or_tokens(p, u, c, region):
    if u["status"] == "FORCE_CHANGE_PASSWORD":
        sid = secrets.token_urlsafe(32)
        _SESSIONS[sid] = {"pool": p["Id"], "user": u["Username"], "client": c["ClientId"]}
        return {"ChallengeName": "NEW_PASSWORD_REQUIRED", "Session": sid,
                "ChallengeParameters": {"USER_ID_FOR_SRP": u["Username"], "requiredAttributes": "[]", "userAttributes": json.dumps(u["attrs"])}}
    return {"AuthenticationResult": _issue(p, u, c, region), "ChallengeParameters": {}}


def _initiate_auth(r, region, admin):
    flow = r.get("AuthFlow")
    params = r.get("AuthParameters") or {}
    if admin:
        _need(r, "UserPoolId", "ClientId")
        c = _client(r["ClientId"], r["UserPoolId"])
    else:
        _need(r, "ClientId")
        c = _client(r["ClientId"])
    p = _pool(c["UserPoolId"])
    allowed = c["ExplicitAuthFlows"]
    if flow == "REFRESH_TOKEN_AUTH" or flow == "REFRESH_TOKEN":
        if "ALLOW_REFRESH_TOKEN_AUTH" not in allowed:
            raise Err("InvalidParameterException", "REFRESH_TOKEN_AUTH flow not enabled for this client")
        rec = _REFRESH.get(params.get("REFRESH_TOKEN", ""))
        if not rec or rec["client"] != c["ClientId"] or rec["exp"] < time.time():
            raise Err("NotAuthorizedException", "Invalid Refresh Token")
        u = p["_users"].get(rec["user"])
        if not u or not u["enabled"]:
            raise Err("NotAuthorizedException", "Invalid Refresh Token")
        return {"AuthenticationResult": _issue(p, u, c, region, refresh=False), "ChallengeParameters": {}}
    need = {"USER_PASSWORD_AUTH": "ALLOW_USER_PASSWORD_AUTH", "ADMIN_USER_PASSWORD_AUTH": "ALLOW_ADMIN_USER_PASSWORD_AUTH", "ADMIN_NO_SRP_AUTH": "ALLOW_ADMIN_USER_PASSWORD_AUTH"}.get(flow)
    if flow in ("USER_SRP_AUTH", "CUSTOM_AUTH"):
        raise Err("InvalidParameterException", "%s is not supported by this simulator (use USER_PASSWORD_AUTH)" % flow)
    if not need:
        raise Err("InvalidParameterException", "Unknown AuthFlow %s" % flow)
    if admin != flow.startswith("ADMIN"):
        raise Err("InvalidParameterException", "%s flow not supported for this call" % flow)
    if need not in allowed:
        raise Err("InvalidParameterException", "%s flow not enabled for this client" % flow)
    uname = params.get("USERNAME", "")
    if not _secret_hash_ok(c, uname, params.get("SECRET_HASH")):
        raise Err("NotAuthorizedException", "Unable to verify secret hash for client %s" % c["ClientId"])
    u = _find_user(p, uname, must=False)
    if u is None or not u["pw"] or not hmac.compare_digest(u["pw"], _hash(params.get("PASSWORD", ""), u["salt"])):
        raise Err("NotAuthorizedException", "Incorrect username or password.")
    if not u["enabled"]:
        raise Err("NotAuthorizedException", "User is disabled.")
    if u["status"] == "UNCONFIRMED":
        raise Err("UserNotConfirmedException", "User is not confirmed.")
    return _challenge_or_tokens(p, u, c, region)


def _respond(r, region, admin):
    c = _client(r.get("ClientId"), r.get("UserPoolId") if admin else None)
    sess = _SESSIONS.get(r.get("Session", ""))
    cr = r.get("ChallengeResponses") or {}
    if r.get("ChallengeName") != "NEW_PASSWORD_REQUIRED" or not sess or sess["client"] != c["ClientId"]:
        raise Err("NotAuthorizedException", "Invalid session for the user.")
    p = _pool(c["UserPoolId"])
    u = p["_users"][sess["user"]]
    _check_password(p, cr.get("NEW_PASSWORD", ""))
    _set_password(u, cr["NEW_PASSWORD"])
    u["status"] = "CONFIRMED"
    u["modified"] = time.time()
    _SESSIONS.pop(r["Session"], None)
    return {"AuthenticationResult": _issue(p, u, c, region), "ChallengeParameters": {}}


def _token_user(tok):
    claims = jwt_decode(tok or "")
    if not claims or claims.get("token_use") != "access":
        raise Err("NotAuthorizedException", "Invalid Access Token")
    if claims.get("exp", 0) < time.time():
        raise Err("NotAuthorizedException", "Access Token has expired")
    pid = claims["iss"].rsplit("/", 1)[-1]
    p = POOLS.get(pid)
    u = p and p["_users"].get(claims.get("username"))
    if not u:
        raise Err("NotAuthorizedException", "Invalid Access Token")
    if claims.get("iat", 0) <= u["signout"]:
        raise Err("NotAuthorizedException", "Access Token has been revoked")
    return p, u


def _filter_ok(u, flt):
    if not flt:
        return True
    m = re.match(r'^\s*([\w:]+)\s*(=|\^=)\s*"(.*)"\s*$', flt)
    if not m:
        raise Err("InvalidParameterException", "Error while parsing filter")
    k, op, v = m.groups()
    val = {"username": u["Username"], "status": u["status"], "enabled": str(u["enabled"]).lower(), "cognito:user_status": u["status"]}.get(k, u["attrs"].get(k))
    if val is None:
        return False
    return val == v if op == "=" else val.startswith(v)


def _page(items, r, key, default=60):
    n = int(r.get("MaxResults") or r.get("Limit") or default)
    start = int(r["NextToken"]) if str(r.get("NextToken") or "").isdigit() else 0
    out = {key: items[start:start + n]}
    if start + n < len(items):
        out["NextToken"] = str(start + n)
    return out


def cognito_call(op, r, region):
    """-> response doc (a dict). Raises Err for a modeled service error."""
    if op == "CreateUserPool":
        return _create_pool(r, region)
    if op == "ListUserPools":
        if not r.get("MaxResults"):
            raise Err("InvalidParameterException", "1 validation error detected: Value null at 'maxResults' failed to satisfy constraint: Member must not be null")
        items = [{"Id": p["Id"], "Name": p["Name"], "LambdaConfig": p["LambdaConfig"], "LastModifiedDate": p["LastModifiedDate"], "CreationDate": p["CreationDate"]}
                 for p in POOLS.values() if p["_region"] == region]
        return _page(items, r, "UserPools")
    if op == "DescribeUserPool":
        return {"UserPool": _pool_view(_pool(r.get("UserPoolId")))}
    if op == "UpdateUserPool":
        p = _pool(r.get("UserPoolId"))
        for k in ("Policies", "LambdaConfig", "AutoVerifiedAttributes", "MfaConfiguration", "AdminCreateUserConfig", "AccountRecoverySetting", "DeletionProtection"):
            if k in r:
                p[k] = r[k]
        p["LastModifiedDate"] = time.time()
        return {}
    if op == "DeleteUserPool":
        p = _pool(r.get("UserPoolId"))
        for cid in [k for k, c in CLIENTS.items() if c["UserPoolId"] == p["Id"]]:
            CLIENTS.pop(cid)
        POOLS.pop(p["Id"])
        return {}
    if op == "CreateUserPoolClient":
        return _create_client(r)
    if op == "DescribeUserPoolClient":
        return {"UserPoolClient": dict(_client(r.get("ClientId"), r.get("UserPoolId")))}
    if op == "ListUserPoolClients":
        _pool(r.get("UserPoolId"))
        items = [{"ClientId": c["ClientId"], "UserPoolId": c["UserPoolId"], "ClientName": c["ClientName"]} for c in CLIENTS.values() if c["UserPoolId"] == r["UserPoolId"]]
        return _page(items, r, "UserPoolClients", 60)
    if op == "UpdateUserPoolClient":
        c = _client(r.get("ClientId"), r.get("UserPoolId"))
        for k, v in r.items():
            if k not in ("UserPoolId", "ClientId", "GenerateSecret"):
                c[k] = _flows(v) if k == "ExplicitAuthFlows" else v
        c["LastModifiedDate"] = time.time()
        return {"UserPoolClient": dict(c)}
    if op == "DeleteUserPoolClient":
        _client(r.get("ClientId"), r.get("UserPoolId"))
        CLIENTS.pop(r["ClientId"])
        return {}
    if op == "CreateUserPoolDomain":
        _pool(r.get("UserPoolId"))
        _DOMAINS[r["Domain"]] = r["UserPoolId"]
        return {"CloudFrontDomain": "%s.cloudfront.net" % _rid(14).lower()}
    if op == "DeleteUserPoolDomain":
        _DOMAINS.pop(r.get("Domain"), None)
        return {}
    if op == "DescribeUserPoolDomain":
        pid = _DOMAINS.get(r.get("Domain"))
        return {"DomainDescription": ({"UserPoolId": pid, "AWSAccountId": ACCOUNT, "Domain": r["Domain"], "Status": "ACTIVE"} if pid else {})}
    if op in ("InitiateAuth", "AdminInitiateAuth"):
        return _initiate_auth(r, region, op == "AdminInitiateAuth")
    if op in ("RespondToAuthChallenge", "AdminRespondToAuthChallenge"):
        return _respond(r, region, op.startswith("Admin"))
    if op == "SignUp":
        _need(r, "ClientId", "Username", "Password")
        c = _client(r["ClientId"])
        p = _pool(c["UserPoolId"])
        if not _secret_hash_ok(c, r["Username"], r.get("SecretHash")):
            raise Err("NotAuthorizedException", "Unable to verify secret hash for client %s" % c["ClientId"])
        _check_password(p, r["Password"])
        attrs = list(r.get("UserAttributes") or [])
        if set(p["UsernameAttributes"]) & {"email", "phone_number"} and not any(a["Name"] in p["UsernameAttributes"] for a in attrs):
            attrs.append({"Name": "email" if "email" in p["UsernameAttributes"] else "phone_number", "Value": r["Username"]})
        u = _new_user(p, r["Username"], attrs, "UNCONFIRMED", r["Password"])
        out = {"UserConfirmed": False, "UserSub": u["attrs"]["sub"]}
        for a in p["AutoVerifiedAttributes"]:
            if a in u["attrs"]:
                out["CodeDeliveryDetails"] = {"Destination": re.sub(r"^(.).*(@.*)$", r"\1***\2", u["attrs"][a]), "DeliveryMedium": "EMAIL" if a == "email" else "SMS", "AttributeName": a}
                break
        return out
    if op == "ConfirmSignUp":
        _need(r, "ClientId", "Username", "ConfirmationCode")
        c = _client(r["ClientId"])
        p = _pool(c["UserPoolId"])
        u = _find_user(p, r["Username"])
        if u["status"] != "UNCONFIRMED":
            raise Err("NotAuthorizedException", "User cannot be confirmed. Current status is %s" % u["status"])
        u["status"] = "CONFIRMED"
        for a in p["AutoVerifiedAttributes"]:
            if a in u["attrs"]:
                u["attrs"][a + "_verified"] = "true"
        u["modified"] = time.time()
        return {}
    if op == "ResendConfirmationCode":
        c = _client(r.get("ClientId"))
        u = _find_user(_pool(c["UserPoolId"]), r.get("Username"))
        return {"CodeDeliveryDetails": {"Destination": "***", "DeliveryMedium": "EMAIL", "AttributeName": "email"}} if u else {}
    if op == "AdminCreateUser":
        _need(r, "UserPoolId", "Username")
        p = _pool(r["UserPoolId"])
        temp = r.get("TemporaryPassword") or "Tmp!" + secrets.token_hex(6) + "A1"
        if r.get("TemporaryPassword"):
            _check_password(p, temp)
        attrs = list(r.get("UserAttributes") or [])
        if set(p["UsernameAttributes"]) & {"email", "phone_number"} and not any(a["Name"] in p["UsernameAttributes"] for a in attrs):
            attrs.append({"Name": "email" if "email" in p["UsernameAttributes"] else "phone_number", "Value": r["Username"]})
        u = _new_user(p, r["Username"], attrs, "FORCE_CHANGE_PASSWORD", temp)
        if any(a["Name"] == "email" for a in attrs) and "email" in p["AutoVerifiedAttributes"]:
            u["attrs"]["email_verified"] = u["attrs"].get("email_verified", "false")
        return {"User": _user_view(u)}
    if op == "AdminConfirmSignUp":
        u = _find_user(_pool(r.get("UserPoolId")), r.get("Username"))
        u["status"], u["modified"] = "CONFIRMED", time.time()
        return {}
    if op == "AdminSetUserPassword":
        p = _pool(r.get("UserPoolId"))
        u = _find_user(p, r.get("Username"))
        _check_password(p, r.get("Password", ""))
        _set_password(u, r["Password"])
        u["status"] = "CONFIRMED" if r.get("Permanent") else "FORCE_CHANGE_PASSWORD"
        u["modified"] = time.time()
        return {}
    if op == "AdminGetUser":
        return _user_view(_find_user(_pool(r.get("UserPoolId")), r.get("Username")), "UserAttributes")
    if op == "AdminDeleteUser":
        p = _pool(r.get("UserPoolId"))
        u = _find_user(p, r.get("Username"))
        p["_users"].pop(u["Username"])
        for g in p["_groups"].values():
            g["members"].discard(u["Username"])
        p["EstimatedNumberOfUsers"] = len(p["_users"])
        return {}
    if op in ("AdminDisableUser", "AdminEnableUser"):
        u = _find_user(_pool(r.get("UserPoolId")), r.get("Username"))
        u["enabled"] = op == "AdminEnableUser"
        return {}
    if op == "AdminUpdateUserAttributes":
        u = _find_user(_pool(r.get("UserPoolId")), r.get("Username"))
        for a in r.get("UserAttributes") or []:
            u["attrs"][a["Name"]] = a.get("Value", "")
        u["modified"] = time.time()
        return {}
    if op == "AdminUserGlobalSignOut":
        u = _find_user(_pool(r.get("UserPoolId")), r.get("Username"))
        u["signout"] = int(time.time())
        for k in [k for k, v in _REFRESH.items() if v["pool"] == r["UserPoolId"] and v["user"] == u["Username"]]:
            _REFRESH.pop(k)
        return {}
    if op == "ListUsers":
        p = _pool(r.get("UserPoolId"))
        items = [_user_view(u) for u in p["_users"].values() if _filter_ok(u, r.get("Filter"))]
        return _page(items, r, "Users", 60)
    if op == "GetUser":
        _, u = _token_user(r.get("AccessToken"))
        return {"Username": u["Username"], "UserAttributes": _attrs_list(u)}
    if op == "GlobalSignOut":
        _, u = _token_user(r.get("AccessToken"))
        u["signout"] = int(time.time())
        for k in [k for k, v in _REFRESH.items() if v["user"] == u["Username"]]:
            _REFRESH.pop(k)
        return {}
    if op == "ChangePassword":
        p, u = _token_user(r.get("AccessToken"))
        if not hmac.compare_digest(u["pw"] or "", _hash(r.get("PreviousPassword", ""), u["salt"])):
            raise Err("NotAuthorizedException", "Incorrect username or password.")
        _check_password(p, r.get("ProposedPassword", ""))
        _set_password(u, r["ProposedPassword"])
        return {}
    if op == "UpdateUserAttributes":
        _, u = _token_user(r.get("AccessToken"))
        for a in r.get("UserAttributes") or []:
            u["attrs"][a["Name"]] = a.get("Value", "")
        return {}
    if op == "CreateGroup":
        p = _pool(r.get("UserPoolId"))
        if r["GroupName"] in p["_groups"]:
            raise Err("GroupExistsException", "A group with the name %s already exists." % r["GroupName"])
        now = time.time()
        g = {"GroupName": r["GroupName"], "UserPoolId": p["Id"], "Description": r.get("Description", ""), "RoleArn": r.get("RoleArn"), "Precedence": r.get("Precedence"),
             "LastModifiedDate": now, "CreationDate": now, "members": set()}
        p["_groups"][r["GroupName"]] = g
        return {"Group": {k: v for k, v in g.items() if k != "members" and v is not None}}
    if op in ("GetGroup", "DeleteGroup", "ListGroups", "ListUsersInGroup"):
        p = _pool(r.get("UserPoolId"))
        if op == "ListGroups":
            return _page([{k: v for k, v in g.items() if k != "members" and v is not None} for g in p["_groups"].values()], r, "Groups", 60)
        g = p["_groups"].get(r.get("GroupName"))
        if not g:
            raise Err("ResourceNotFoundException", "Group not found.")
        if op == "DeleteGroup":
            for n in g["members"]:
                if n in p["_users"] and g["GroupName"] in p["_users"][n]["groups"]:
                    p["_users"][n]["groups"].remove(g["GroupName"])
            p["_groups"].pop(g["GroupName"])
            return {}
        if op == "ListUsersInGroup":
            return _page([_user_view(p["_users"][n]) for n in sorted(g["members"]) if n in p["_users"]], r, "Users", 60)
        return {"Group": {k: v for k, v in g.items() if k != "members" and v is not None}}
    if op in ("AdminAddUserToGroup", "AdminRemoveUserFromGroup"):
        p = _pool(r.get("UserPoolId"))
        u = _find_user(p, r.get("Username"))
        g = p["_groups"].get(r.get("GroupName"))
        if not g:
            raise Err("ResourceNotFoundException", "Group not found.")
        if op == "AdminAddUserToGroup":
            g["members"].add(u["Username"])
            if g["GroupName"] not in u["groups"]:
                u["groups"].append(g["GroupName"])
        else:
            g["members"].discard(u["Username"])
            if g["GroupName"] in u["groups"]:
                u["groups"].remove(g["GroupName"])
        return {}
    if op == "AdminListGroupsForUser":
        p = _pool(r.get("UserPoolId"))
        u = _find_user(p, r.get("Username"))
        return _page([{k: v for k, v in p["_groups"][n].items() if k != "members" and v is not None} for n in u["groups"] if n in p["_groups"]], r, "Groups", 60)
    if op in ("TagResource", "UntagResource", "ListTagsForResource"):
        return _tags(op, r)
    if op == "GetUserPoolMfaConfig":
        _pool(r.get("UserPoolId"))
        return {"MfaConfiguration": "OFF"}
    raise Err("NotImplementedException", "cognito-idp %s is not implemented by this simulator" % op, 501)


def _tags(op, r):
    arn = r.get("ResourceArn", "")
    t = _TAGS.setdefault(arn, {})
    if op == "TagResource":
        t.update(r.get("Tags") or {})
        return {}
    if op == "UntagResource":
        for k in r.get("TagKeys") or []:
            t.pop(k, None)
        return {}
    return {"Tags": dict(t)}


_TAGS: dict = {}


def issuer_pool(issuer):
    m = re.match(r"^https?://cognito-idp\.([a-z0-9-]+)\.amazonaws\.com/([a-z0-9-]+_[A-Za-z0-9]+)/?$", issuer or "")
    return POOLS.get(m.group(2)) if m else None


def pool_jwks(pool_id):
    return {"keys": [jwk()]} if pool_id in POOLS else None


def openid_config(pool_id, host, proto="http"):
    p = POOLS.get(pool_id)
    if not p:
        return None
    iss = "https://cognito-idp.%s.amazonaws.com/%s" % (p["_region"], pool_id)
    return {"authorization_endpoint": "https://%s/oauth2/authorize" % host, "id_token_signing_alg_values_supported": ["RS256"], "issuer": iss,
            "jwks_uri": "%s://%s/%s/.well-known/jwks.json" % (proto, host, pool_id), "response_types_supported": ["code", "token"],
            "scopes_supported": ["openid", "email", "phone", "profile"], "subject_types_supported": ["public"],
            "token_endpoint": "https://%s/oauth2/token" % host, "userinfo_endpoint": "https://%s/oauth2/userInfo" % host}


def call_json(op, payload, region=DEFAULT_REGION):
    """In-process call used by the hosted-UI adapter: -> (status, dict)."""
    try:
        return 200, cognito_call(op, payload, region)
    except Err as e:
        return e.status, {"__type": e.code, "message": e.msg}


# ───────────────────────────── WAFv2 ─────────────────────────────
_WACLS: dict = {}       # arn -> acl
_IPSETS: dict = {}
_REGEXSETS: dict = {}
_ACL_RES = r"^arn:aws:apigateway:[a-z0-9-]+::/(?:restapis|apis)/[A-Za-z0-9]+/stages/[^/]+$"


def _scope(r):
    s = r.get("Scope")
    if s not in ("REGIONAL", "CLOUDFRONT"):
        raise Err("WAFInvalidParameterException", "Error reason: The scope is not valid., field: SCOPE_VALUE, parameter: %s" % s)
    return s


def _arn(region, scope, kind, name, id_):
    return "arn:aws:wafv2:%s:%s:%s/%s/%s/%s" % ("us-east-1" if scope == "CLOUDFRONT" else region, ACCOUNT, "global" if scope == "CLOUDFRONT" else "regional", kind, name, id_)


def _summary(o):
    return {"Name": o["Name"], "Id": o["Id"], "Description": o.get("Description", ""), "LockToken": o["LockToken"], "ARN": o["ARN"]}


def _find(store, r, what):
    scope = _scope(r)
    for o in store.values():
        if o["Id"] == r.get("Id") and o["Name"] == r.get("Name") and o["_scope"] == scope:
            return o
    raise Err("WAFNonexistentItemException", "AWS WAF couldn't perform the operation because your resource doesn't exist.")


def _lock(o, r):
    if r.get("LockToken") != o["LockToken"]:
        raise Err("WAFOptimisticLockException", "AWS WAF couldn't save your changes because someone changed the resource after you started to edit it. Reapply your changes.")


_RULE_SIZE = {"RateBasedStatement": 2, "SqliMatchStatement": 20, "XssMatchStatement": 40, "RegexMatchStatement": 3, "RegexPatternSetReferenceStatement": 25, "ManagedRuleGroupStatement": 25}


def _capacity(st):
    if not isinstance(st, dict):
        return 1
    n = 0
    for k, v in st.items():
        if k in ("AndStatement", "OrStatement"):
            n += 1 + sum(_capacity(s) for s in v.get("Statements", []))
        elif k == "NotStatement":
            n += 1 + _capacity(v.get("Statement"))
        else:
            n += _RULE_SIZE.get(k, 1)
            if k == "RateBasedStatement" and v.get("ScopeDownStatement"):
                n += _capacity(v["ScopeDownStatement"])
    return n or 1


def _validate_rules(rules):
    seen, prios = set(), set()
    for ru in rules or []:
        for k in ("Name", "Priority", "Statement", "VisibilityConfig"):
            if ru.get(k) is None:
                raise Err("WAFInvalidParameterException", "Error reason: Rule is missing %s, field: RULE, parameter: %s" % (k, ru.get("Name")))
        if ru["Name"] in seen or ru["Priority"] in prios:
            raise Err("WAFInvalidParameterException", "Error reason: Duplicate rule name or priority, field: RULE, parameter: %s" % ru["Name"])
        seen.add(ru["Name"])
        prios.add(ru["Priority"])
        if "Action" not in ru and "OverrideAction" not in ru:
            raise Err("WAFInvalidParameterException", "Error reason: A rule must have Action or OverrideAction, field: RULE, parameter: %s" % ru["Name"])
        rb = ru["Statement"].get("RateBasedStatement")
        if rb is not None and not (10 <= int(rb.get("Limit", 0)) <= 2000000000):
            raise Err("WAFInvalidParameterException", "Error reason: The rate limit must be between 10 and 2000000000, field: RATE_BASED_STATEMENT, parameter: %s" % rb.get("Limit"))


def _acl_view(a):
    return {k: v for k, v in a.items() if not k.startswith("_") and k != "LockToken"}


def wafv2_call(op, r, region):
    if op == "CreateWebACL":
        scope = _scope(r)
        for k in ("Name", "DefaultAction", "VisibilityConfig"):
            if not r.get(k):
                raise Err("WAFInvalidParameterException", "Error reason: %s is required, field: %s, parameter: null" % (k, k.upper()))
        if any(a["Name"] == r["Name"] and a["_scope"] == scope for a in _WACLS.values()):
            raise Err("WAFDuplicateItemException", "AWS WAF couldn't perform the operation because the resource that you tried to save is a duplicate of an existing one.")
        _validate_rules(r.get("Rules"))
        i = str(uuid.uuid4())
        a = {"Name": r["Name"], "Id": i, "ARN": _arn(region, scope, "webacl", r["Name"], i), "DefaultAction": r["DefaultAction"], "Description": r.get("Description", ""),
             "Rules": r.get("Rules") or [], "VisibilityConfig": r["VisibilityConfig"], "Capacity": sum(_capacity(x["Statement"]) for x in r.get("Rules") or []),
             "ManagedByFirewallManager": False, "LabelNamespace": "awswaf:%s:webacl:%s:" % (ACCOUNT, r["Name"]), "CustomResponseBodies": r.get("CustomResponseBodies") or {},
             "LockToken": str(uuid.uuid4()), "_scope": scope, "_assoc": set()}
        if not a["CustomResponseBodies"]:
            a.pop("CustomResponseBodies")
        _WACLS[a["ARN"]] = a
        _TAGS[a["ARN"]] = {t["Key"]: t["Value"] for t in r.get("Tags") or []}
        return {"Summary": _summary(a)}
    if op == "GetWebACL":
        a = _find(_WACLS, r, "WebACL")
        return {"WebACL": _acl_view(a), "LockToken": a["LockToken"], "ApplicationIntegrationURL": "https://%s.vyomi.local/sdk" % a["Id"][:8]}
    if op == "ListWebACLs":
        scope = _scope(r)
        items = [_summary(a) for a in _WACLS.values() if a["_scope"] == scope and (scope == "CLOUDFRONT" or ":%s:" % region in a["ARN"])]
        return _wpage(items, r, "WebACLs")
    if op == "UpdateWebACL":
        a = _find(_WACLS, r, "WebACL")
        _lock(a, r)
        for k in ("DefaultAction", "VisibilityConfig"):
            if not r.get(k):
                raise Err("WAFInvalidParameterException", "Error reason: %s is required, field: %s, parameter: null" % (k, k.upper()))
        _validate_rules(r.get("Rules"))
        a.update(DefaultAction=r["DefaultAction"], VisibilityConfig=r["VisibilityConfig"], Rules=r.get("Rules") or [], Description=r.get("Description", a.get("Description", "")),
                 Capacity=sum(_capacity(x["Statement"]) for x in r.get("Rules") or []), LockToken=str(uuid.uuid4()))
        return {"NextLockToken": a["LockToken"]}
    if op == "DeleteWebACL":
        a = _find(_WACLS, r, "WebACL")
        _lock(a, r)
        if a["_assoc"]:
            raise Err("WAFAssociatedItemException", "AWS WAF couldn't perform the operation because your resource is being used by another resource or it's associated with another resource.")
        _WACLS.pop(a["ARN"])
        return {}
    if op == "AssociateWebACL":
        acl = _WACLS.get(r.get("WebACLArn"))
        if not acl:
            raise Err("WAFNonexistentItemException", "AWS WAF couldn't perform the operation because your resource doesn't exist.")
        res = r.get("ResourceArn", "")
        if not re.match(_ACL_RES, res):
            raise Err("WAFInvalidParameterException", "Error reason: The ARN isn't valid. A valid ARN begins with arn: and includes other information separated by colons or slashes., field: RESOURCE_ARN, parameter: %s" % res)
        for o in _WACLS.values():
            o["_assoc"].discard(res)
        acl["_assoc"].add(res)
        return {}
    if op == "DisassociateWebACL":
        for o in _WACLS.values():
            o["_assoc"].discard(r.get("ResourceArn"))
        return {}
    if op == "GetWebACLForResource":
        for o in _WACLS.values():
            if r.get("ResourceArn") in o["_assoc"]:
                return {"WebACL": _acl_view(o)}
        return {}
    if op == "ListResourcesForWebACL":
        a = _WACLS.get(r.get("WebACLArn"))
        if not a:
            raise Err("WAFNonexistentItemException", "AWS WAF couldn't perform the operation because your resource doesn't exist.")
        return {"ResourceArns": sorted(a["_assoc"])}
    if op == "CheckCapacity":
        _scope(r)
        _validate_rules(r.get("Rules"))
        return {"Capacity": sum(_capacity(x["Statement"]) for x in r.get("Rules") or [])}
    if op == "CreateIPSet":
        scope = _scope(r)
        _need(r, "Name", "IPAddressVersion")
        if any(s["Name"] == r["Name"] and s["_scope"] == scope for s in _IPSETS.values()):
            raise Err("WAFDuplicateItemException", "AWS WAF couldn't perform the operation because the resource that you tried to save is a duplicate of an existing one.")
        i = str(uuid.uuid4())
        s = {"Name": r["Name"], "Id": i, "ARN": _arn(region, scope, "ipset", r["Name"], i), "Description": r.get("Description", ""), "IPAddressVersion": r["IPAddressVersion"],
             "Addresses": list(r.get("Addresses") or []), "LockToken": str(uuid.uuid4()), "_scope": scope}
        _IPSETS[s["ARN"]] = s
        return {"Summary": _summary(s)}
    if op == "GetIPSet":
        s = _find(_IPSETS, r, "IPSet")
        return {"IPSet": {k: v for k, v in s.items() if k not in ("LockToken",) and not k.startswith("_")}, "LockToken": s["LockToken"]}
    if op == "ListIPSets":
        scope = _scope(r)
        return _wpage([_summary(s) for s in _IPSETS.values() if s["_scope"] == scope], r, "IPSets")
    if op == "UpdateIPSet":
        s = _find(_IPSETS, r, "IPSet")
        _lock(s, r)
        s.update(Addresses=list(r.get("Addresses") or []), Description=r.get("Description", s["Description"]), LockToken=str(uuid.uuid4()))
        return {"NextLockToken": s["LockToken"]}
    if op == "DeleteIPSet":
        s = _find(_IPSETS, r, "IPSet")
        _lock(s, r)
        if any(s["ARN"] in json.dumps(a["Rules"]) for a in _WACLS.values()):
            raise Err("WAFAssociatedItemException", "AWS WAF couldn't perform the operation because your resource is being used by another resource or it's associated with another resource.")
        _IPSETS.pop(s["ARN"])
        return {}
    if op == "CreateRegexPatternSet":
        scope = _scope(r)
        _need(r, "Name")
        if any(s["Name"] == r["Name"] and s["_scope"] == scope for s in _REGEXSETS.values()):
            raise Err("WAFDuplicateItemException", "AWS WAF couldn't perform the operation because the resource that you tried to save is a duplicate of an existing one.")
        i = str(uuid.uuid4())
        s = {"Name": r["Name"], "Id": i, "ARN": _arn(region, scope, "regexpatternset", r["Name"], i), "Description": r.get("Description", ""),
             "RegularExpressionList": list(r.get("RegularExpressionList") or []), "LockToken": str(uuid.uuid4()), "_scope": scope}
        _REGEXSETS[s["ARN"]] = s
        return {"Summary": _summary(s)}
    if op == "GetRegexPatternSet":
        s = _find(_REGEXSETS, r, "RegexPatternSet")
        return {"RegexPatternSet": {k: v for k, v in s.items() if k != "LockToken" and not k.startswith("_")}, "LockToken": s["LockToken"]}
    if op == "ListRegexPatternSets":
        scope = _scope(r)
        return _wpage([_summary(s) for s in _REGEXSETS.values() if s["_scope"] == scope], r, "RegexPatternSets")
    if op == "UpdateRegexPatternSet":
        s = _find(_REGEXSETS, r, "RegexPatternSet")
        _lock(s, r)
        s.update(RegularExpressionList=list(r.get("RegularExpressionList") or []), LockToken=str(uuid.uuid4()))
        return {"NextLockToken": s["LockToken"]}
    if op == "DeleteRegexPatternSet":
        s = _find(_REGEXSETS, r, "RegexPatternSet")
        _lock(s, r)
        _REGEXSETS.pop(s["ARN"])
        return {}
    if op == "ListAvailableManagedRuleGroups":
        _scope(r)
        return {"ManagedRuleGroups": [{"VendorName": "AWS", "Name": n, "Description": d} for n, d in MANAGED_GROUPS.items()]}
    if op == "DescribeManagedRuleGroup":
        _scope(r)
        if r.get("VendorName") != "AWS" or r.get("Name") not in MANAGED_GROUPS:
            raise Err("WAFNonexistentItemException", "AWS WAF couldn't perform the operation because your resource doesn't exist.")
        return {"Capacity": 700, "Rules": [{"Name": n, "Action": {"Block": {}}} for n, _ in _MANAGED_SIGS.get(r["Name"], [])], "LabelNamespace": "awswaf:managed:aws:%s:" % r["Name"].lower()}
    if op in ("TagResource", "UntagResource", "ListTagsForResource"):
        arn = r.get("ResourceARN", "")
        t = _TAGS.setdefault(arn, {})
        if op == "TagResource":
            t.update({x["Key"]: x["Value"] for x in r.get("Tags") or []})
            return {}
        if op == "UntagResource":
            for k in r.get("TagKeys") or []:
                t.pop(k, None)
            return {}
        return {"TagInfoForResource": {"ResourceARN": arn, "TagList": [{"Key": k, "Value": v} for k, v in t.items()]}}
    if op in ("GetLoggingConfiguration", "PutLoggingConfiguration", "DeleteLoggingConfiguration"):
        return {"LoggingConfiguration": r.get("LoggingConfiguration") or {}} if op == "PutLoggingConfiguration" else {}
    raise Err("NotImplementedException", "wafv2 %s is not implemented by this simulator" % op, 501)


def _wpage(items, r, key):
    n = int(r.get("Limit") or 100)
    start = int(r["NextMarker"]) if str(r.get("NextMarker") or "").isdigit() else 0
    out = {key: items[start:start + n]}
    if start + n < len(items):
        out["NextMarker"] = str(start + n)
    return out


MANAGED_GROUPS = {
    "AWSManagedRulesCommonRuleSet": "Contains rules that are generally applicable to web applications (signature subset in this simulator).",
    "AWSManagedRulesSQLiRuleSet": "Contains rules that allow you to block request patterns associated with SQL injection.",
    "AWSManagedRulesKnownBadInputsRuleSet": "Contains rules that block request patterns known to be invalid and associated with exploitation (Log4j, Java deserialization).",
    "AWSManagedRulesAdminProtectionRuleSet": "Contains rules that allow you to block external access to exposed admin pages.",
    "AWSManagedRulesAmazonIpReputationList": "Contains rules based on Amazon threat intelligence (never matches in this simulator).",
    "AWSManagedRulesAnonymousIpList": "Contains rules that block requests from services that allow obfuscation of viewer identity (never matches in this simulator).",
    "AWSManagedRulesLinuxRuleSet": "Contains rules that block request patterns associated with Linux-specific local file inclusion.",
}
# (rule name, field, regex) signature stubs; fields: uri, query, body, header:<name>, any
_MANAGED_SIGS = {
    "AWSManagedRulesCommonRuleSet": [
        ("CrossSiteScripting_QUERYARGUMENTS", "query", r"<\s*script|javascript:|on(error|load|click)\s*="),
        ("CrossSiteScripting_BODY", "body", r"<\s*script|javascript:|on(error|load|click)\s*="),
        ("CrossSiteScripting_URIPATH", "uri", r"<\s*script"),
        ("GenericLFI_QUERYARGUMENTS", "query", r"\.\./|\.\.%2f|/etc/passwd"),
        ("GenericLFI_URIPATH", "uri", r"\.\./|/etc/passwd"),
        ("UserAgent_BadBots_HEADER", "header:user-agent", r"(?i)sqlmap|nikto|masscan|nmap"),
        ("NoUserAgent_HEADER", "nouseragent", r""),
    ],
    "AWSManagedRulesSQLiRuleSet": [
        ("SQLi_QUERYARGUMENTS", "query", r"(?i)('|%27)\s*(or|and)\s+['\"\d]|union\s+(all\s+)?select|;\s*drop\s+table|--\s*$"),
        ("SQLi_BODY", "body", r"(?i)('|%27)\s*(or|and)\s+['\"\d]|union\s+(all\s+)?select|;\s*drop\s+table"),
        ("SQLi_URIPATH", "uri", r"(?i)union\s+(all\s+)?select|;\s*drop\s+table"),
    ],
    "AWSManagedRulesKnownBadInputsRuleSet": [
        ("Log4JRCE_QUERYSTRING", "query", r"(?i)\$\{(jndi|lower|upper|env|sys):"),
        ("Log4JRCE_BODY", "body", r"(?i)\$\{(jndi|lower|upper|env|sys):"),
        ("Log4JRCE_HEADER", "header:*", r"(?i)\$\{(jndi|lower|upper|env|sys):"),
        ("JavaDeserializationRCE_BODY", "body", r"(?i)java\.lang\.(runtime|processbuilder)|ognl\."),
    ],
    "AWSManagedRulesAdminProtectionRuleSet": [("AdminProtection_URIPATH", "uri", r"(?i)^/(admin|manager/html|phpmyadmin|wp-admin|server-status)(/|$)")],
    "AWSManagedRulesLinuxRuleSet": [("LFI_URIPATH", "uri", r"\.\./|/etc/(passwd|shadow)|/proc/self"), ("LFI_QUERYARGUMENTS", "query", r"\.\./|/etc/(passwd|shadow)|/proc/self")],
    "AWSManagedRulesAmazonIpReputationList": [],
    "AWSManagedRulesAnonymousIpList": [],
}


def managed_match(group, req, excluded=()):
    """-> the matching managed rule's name (a stub signature hit) or None."""
    from urllib.parse import unquote
    for name, field, rx in _MANAGED_SIGS.get(group, []):
        if name in excluded:
            continue
        if field == "nouseragent":
            if not req["headers"].get("user-agent"):
                return name
            continue
        if field == "uri":
            vals = [req["path"], unquote(req["path"])]
        elif field == "query":
            vals = [req["qs"], unquote(req["qs"])]
        elif field == "body":
            vals = [req["body"].decode("utf-8", "replace")]
        elif field == "header:*":
            vals = list(req["headers"].values())
        else:
            vals = [req["headers"].get(field.split(":", 1)[1], "")]
        if any(re.search(rx, v) for v in vals):
            return name
    return None


class _NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def waf_view(api_id, stage):
    """-> (backend-like namespace with ip_sets / regex_pattern_sets, web-ACL namespace) for the ACL associated with this API stage, else (None, None)."""
    suffix = re.compile(r"/(?:restapis|apis)/%s/stages/%s$" % (re.escape(api_id), re.escape(stage)))
    for a in _WACLS.values():
        if any(suffix.search(x) for x in a["_assoc"]):
            be = _NS(ip_sets={k: _NS(addresses=v["Addresses"]) for k, v in _IPSETS.items()},
                     regex_pattern_sets={k: _NS(regular_expressions=[{"RegexString": x.get("RegexString") if isinstance(x, dict) else x} for x in v["RegularExpressionList"]])
                                         for k, v in _REGEXSETS.items()})
            return be, _NS(arn=a["ARN"], rules=a["Rules"], default_action=a["DefaultAction"], name=a["Name"])
    return None, None


_IDPOOLS: dict = {}


def identity_call(op, r, region):
    """Cognito Identity (federated identities): pool CRUD + GetId / GetCredentialsForIdentity with simulator credentials."""
    if op == "CreateIdentityPool":
        _need(r, "IdentityPoolName", "AllowUnauthenticatedIdentities")
        pid = "%s:%s" % (region, uuid.uuid4())
        _IDPOOLS[pid] = {"IdentityPoolId": pid, "IdentityPoolName": r["IdentityPoolName"], "AllowUnauthenticatedIdentities": bool(r["AllowUnauthenticatedIdentities"]),
                         "SupportedLoginProviders": r.get("SupportedLoginProviders") or {}, "CognitoIdentityProviders": r.get("CognitoIdentityProviders") or [],
                         "IdentityPoolTags": r.get("IdentityPoolTags") or {}}
        return dict(_IDPOOLS[pid])
    if op == "DescribeIdentityPool":
        if r.get("IdentityPoolId") not in _IDPOOLS:
            raise Err("ResourceNotFoundException", "IdentityPool '%s' not found" % r.get("IdentityPoolId"))
        return dict(_IDPOOLS[r["IdentityPoolId"]])
    if op == "ListIdentityPools":
        return {"IdentityPools": [{"IdentityPoolId": k, "IdentityPoolName": v["IdentityPoolName"]} for k, v in _IDPOOLS.items()][:int(r.get("MaxResults") or 60)]}
    if op == "DeleteIdentityPool":
        _IDPOOLS.pop(r.get("IdentityPoolId"), None)
        return {}
    if op == "GetId":
        if r.get("IdentityPoolId") not in _IDPOOLS:
            raise Err("ResourceNotFoundException", "IdentityPool '%s' not found" % r.get("IdentityPoolId"))
        return {"IdentityId": "%s:%s" % (region, uuid.uuid5(uuid.NAMESPACE_URL, r["IdentityPoolId"] + json.dumps(r.get("Logins") or {}, sort_keys=True)))}
    if op == "GetCredentialsForIdentity":
        return {"IdentityId": r.get("IdentityId"), "Credentials": {"AccessKeyId": "ASIA" + _rid(16).upper(), "SecretKey": secrets.token_urlsafe(30), "SessionToken": secrets.token_urlsafe(60),
                                                                    "Expiration": time.time() + 3600}}
    raise Err("NotImplementedException", "cognito-identity %s is not implemented by this simulator" % op, 501)


def dispatch(svc, lheaders, body):
    target = (lheaders.get("x-amz-target", "") or "").rsplit(".", 1)[-1]
    region = region_of(lheaders)
    try:
        req = json.loads(body or b"{}") if body else {}
    except ValueError:
        return _error(Err("SerializationException", "Start of structure or map found where not expected."))
    try:
        if svc == "cognito-idp":
            return _resp(200, cognito_call(target, req, region))
        if svc == "wafv2":
            return _resp(200, wafv2_call(target, req, region))
        if svc == "cognito-identity":
            return _resp(200, identity_call(target, req, region))
        raise Err("NotImplementedException", "%s is not implemented by this simulator" % svc, 501)
    except Err as e:
        return _error(e)
