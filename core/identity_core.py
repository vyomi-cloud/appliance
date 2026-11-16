"""Access + perimeter security (AI reference lane C1): Amazon Cognito user pools, Cognito Identity, WAFv2.

OSS engine: moto (Apache-2.0) cognitoidp / cognitoidentity / wafv2 backends (real RS256 JWTs via joserfc, JWKS, groups,
app clients, auth flows, WebACL/RuleGroup/IPSet/RegexPatternSet CRUD). We hand-write ONLY the wire adapter (this file routes the
AWS request into moto's own per-service WSGI app, in process, no sockets) and the two things moto does not do:
  * `local_jwks(issuer)`   -> the public JWKS of the pool an issuer URL names, so the API Gateway JWT / COGNITO_USER_POOLS
                              authorizers verify real RS256 signatures with no network hop (hooked into gateway_common).
  * `waf_check(...)`       -> OWASP-lite enforcement of an associated web ACL on API Gateway requests (see below).

WAF enforcement is a SMALL SUBSET, not Coraza/OWASP CRS: ByteMatch, IPSetReference (+ForwardedIP), SizeConstraint,
RegexMatch / RegexPatternSetReference, SqliMatch/XssMatch (tiny signature lists), Rate-based (per source IP, 5 min window),
And/Or/Not, rule actions Allow/Block/Count, ACL default action. Managed rule groups are not evaluated. Coraza as a Caddy module
is the Mesh follow-up (needs an xcaddy build).
Declared limits: moto state is process-local (Nano persistence/restore is not wired); the signing key is moto's static JWKS key
(shared by every pool, fine for a dev simulator, not a secret); moto + flask + joserfc must be installed (Mesh: requirements.txt;
Nano/Pyodide: loadable through micropip but NOT yet verified in the browser).
"""
from __future__ import annotations

import base64
import json
import re
import time

ACCOUNT = "123456789012"
_APPS: dict = {}
_TARGETS = {"AWSCognitoIdentityProviderService.": ("cognito-idp", "cognito-idp"),
            "AWSCognitoIdentityService.": ("cognito-identity", "cognito-identity"),
            "AWSWAF_20190729.": ("wafv2", "wafv2")}
_POOL_PATH = re.compile(r"^/([a-z0-9-]+_[A-Za-z0-9]+)/(?:\.well-known/(?:jwks\.json|openid-configuration)|login|oauth2/(?:authorize|token|userInfo))$")


def available() -> bool:
    try:
        import moto.cognitoidp.models  # noqa: F401
        import flask  # noqa: F401
        return True
    except Exception:
        return False


def service_for(path, lheaders):
    """-> router service name, or None. Cognito/WAF JSON-1.1 calls are routed by X-Amz-Target (InitiateAuth/SignUp are unsigned)."""
    t = lheaders.get("x-amz-target", "") or ""
    for pre, (svc, _) in _TARGETS.items():
        if t.startswith(pre):
            return svc
    if _POOL_PATH.match(path.split("?", 1)[0]):
        return "cognito-idp"
    return None


def _app(name):
    if name not in _APPS:
        from moto.moto_server.werkzeug_app import create_backend_app
        _APPS[name] = create_backend_app(name)
    return _APPS[name]


def _err(status, code, msg):
    return {"status": status, "headers": {"content-type": "application/x-amz-json-1.1", "x-amzn-errortype": code},
            "body": json.dumps({"__type": code, "message": msg}).encode()}


def dispatch(svc, method, path, query, lheaders, body):
    if not available():
        return _err(501, "NotImplementedException", "identity services need moto + flask + joserfc (pip install 'moto[cognitoidp,server]')")
    if svc == "cognito-idp" and _POOL_PATH.match(path.split("?", 1)[0]):
        hosted = _hosted_dispatch(method, path.split("?", 1)[0], query or {}, lheaders, body)
        if hosted is not None:
            return hosted
    h = {k: v for k, v in lheaders.items() if k not in ("content-length", "host", "transfer-encoding")}
    if "authorization" not in h and svc != "cognito-idp":
        h["authorization"] = f"AWS4-HMAC-SHA256 Credential=AKIAVYOMI/20260101/us-east-1/{svc}/aws4_request, SignedHeaders=host, Signature=0"
    r = _app(svc).test_client().open(path.split("?", 1)[0], method=method, query_string=query or None, data=bytes(body or b""), headers=h)
    if r.status_code == 500 and b"has not been implemented" in r.data:   # an operation moto does not implement: a modeled error, never a bare 500
        return _err(501, "NotImplementedException", r.data.decode("utf-8", "replace")[:300])
    hdrs = {k.lower(): v for k, v in r.headers.items() if k.lower() in ("content-type", "x-amzn-errortype", "x-amzn-requestid")}
    return {"status": r.status_code, "headers": hdrs, "body": r.data}


# ── Cognito hosted UI: OAuth 2.0 authorization-code + PKCE on the moto user pool ───────────────────────────────────
# moto has no /oauth2 endpoints. This is a thin adapter over moto's own InitiateAuth (USER_PASSWORD_AUTH), the app client and its
# CallbackURLs: it adds only the one-time code store and the PKCE (S256) check. Real Cognito serves these on the pool DOMAIN
# (https://<domain>.auth.<region>.amazoncognito.com/oauth2/authorize); locally they live under the pool id, and the pool's
# openid-configuration advertises them, so a discovery-based client (AgentCore credential provider) finds them.
# Declared limits: one pool per code, S256 only, no scopes enforcement, no social/SAML federation, no MFA/NEW_PASSWORD challenge in the login form.
_CODES: dict = {}


def _moto(target, payload):
    r = _app("cognito-idp").test_client().post("/", data=json.dumps(payload), headers={
        "x-amz-target": "AWSCognitoIdentityProviderService." + target, "content-type": "application/x-amz-json-1.1",
        "authorization": "AWS4-HMAC-SHA256 Credential=AKIAVYOMI/20260101/us-east-1/cognito-idp/aws4_request, SignedHeaders=host, Signature=0"})
    try:
        return r.status_code, json.loads(r.data or b"{}")
    except ValueError:
        return r.status_code, {}


def _client(pool, client_id):
    st, d = _moto("DescribeUserPoolClient", {"UserPoolId": pool, "ClientId": client_id})
    return d.get("UserPoolClient") if st == 200 else None


def _html(status, title, inner, headers=None):
    import html as _h
    page = ("<!doctype html><html><head><meta charset=utf-8><title>" + _h.escape(title) + "</title><style>body{font:14px system-ui;max-width:360px;margin:60px auto}"
            "input{display:block;width:100%;margin:6px 0 12px;padding:8px;box-sizing:border-box}button{padding:8px 16px}.e{color:#b00020}</style></head><body>" + inner + "</body></html>")
    return {"status": status, "headers": {"content-type": "text/html; charset=utf-8", **(headers or {})}, "body": page.encode()}


def _redir(uri, params):
    import urllib.parse as up
    sep = "&" if "?" in uri else "?"
    return {"status": 302, "headers": {"location": uri + sep + up.urlencode({k: v for k, v in params.items() if v is not None}), "content-type": "text/plain"}, "body": b""}


def _oauth_err(status, code, desc):
    return {"status": status, "headers": {"content-type": "application/json"}, "body": json.dumps({"error": code, "error_description": desc}).encode()}


def _hosted_dispatch(method, path, query, lheaders, body):
    import base64
    import hashlib
    import html as _h
    import secrets
    import urllib.parse as up
    m = re.match(r"^/([^/]+)/(.*)$", path)
    pool, tail = m.group(1), m.group(2)
    q = {k: (v[0] if isinstance(v, list) else v) for k, v in (query or {}).items()}
    host = lheaders.get("host", "localhost")
    base = f"{'https' if lheaders.get('x-forwarded-proto') == 'https' else 'http'}://{host}/{pool}"
    if tail == ".well-known/openid-configuration" and method == "GET":
        r = _app("cognito-idp").test_client().get(path, headers={"host": host})
        if r.status_code != 200:
            return None
        doc = json.loads(r.data)
        doc.update(authorization_endpoint=f"{base}/oauth2/authorize", token_endpoint=f"{base}/oauth2/token", userinfo_endpoint=f"{base}/oauth2/userInfo",
                   grant_types_supported=["authorization_code", "refresh_token"], code_challenge_methods_supported=["S256"],
                   token_endpoint_auth_methods_supported=["client_secret_basic", "client_secret_post", "none"])
        return {"status": 200, "headers": {"content-type": "application/json"}, "body": json.dumps(doc).encode()}
    if tail == "oauth2/authorize" and method == "GET" or tail == "login" and method == "POST":
        f = q if method == "GET" else {k: v[0] for k, v in up.parse_qs((body or b"").decode("utf-8", "replace")).items()}
        cid, ru, state = f.get("client_id", ""), f.get("redirect_uri", ""), f.get("state")
        c = _client(pool, cid)
        if not c:
            return _html(400, "Error", "<p class=e>Error: invalid client_id for this user pool</p>")
        if not ru or ru not in (c.get("CallbackURLs") or []):
            return _html(400, "Error", "<p class=e>Error: redirect_mismatch - redirect_uri is not one of the app client's CallbackURLs</p>")
        if f.get("response_type") != "code":
            return _redir(ru, {"error": "unsupported_response_type", "error_description": "only response_type=code is supported", "state": state})
        if f.get("code_challenge") and f.get("code_challenge_method", "S256") != "S256":
            return _redir(ru, {"error": "invalid_request", "error_description": "code_challenge_method must be S256", "state": state})
        if not c.get("ClientSecret") and not f.get("code_challenge"):
            return _redir(ru, {"error": "invalid_request", "error_description": "PKCE code_challenge is required for a public client", "state": state})
        hidden = "".join(f'<input type=hidden name="{_h.escape(k)}" value="{_h.escape(f.get(k, ""))}">' for k in ("client_id", "redirect_uri", "response_type", "scope", "state", "code_challenge", "code_challenge_method"))
        form = lambda err="": _html(200 if not err else 401, "Sign in", f'<h3>Sign in</h3>{err}<form method=post action="{base}/login">{hidden}'   # noqa: E731
                                    '<label>Username<input name=username autofocus></label><label>Password<input name=password type=password></label><button>Sign in</button></form>')
        if method == "GET":
            return form()
        st, d = _moto("InitiateAuth", {"ClientId": cid, "AuthFlow": "USER_PASSWORD_AUTH", "AuthParameters": {"USERNAME": f.get("username", ""), "PASSWORD": f.get("password", "")}})
        res = d.get("AuthenticationResult")
        if st != 200 or not res:
            return form('<p class=e>Incorrect username or password.</p>')
        code = secrets.token_urlsafe(24)
        _CODES[code] = {"client_id": cid, "redirect_uri": ru, "challenge": f.get("code_challenge"), "tokens": res, "exp": time.time() + 300, "pool": pool}
        return _redir(ru, {"code": code, "state": state})
    if tail == "oauth2/token" and method == "POST":
        f = {k: v[0] for k, v in up.parse_qs((body or b"").decode("utf-8", "replace")).items()}
        cid, secret = f.get("client_id"), f.get("client_secret")
        auth = lheaders.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                cid, _, secret = base64.b64decode(auth[6:]).decode().partition(":")
                cid, secret = up.unquote(cid), up.unquote(secret)
            except Exception:
                return _oauth_err(401, "invalid_client", "malformed Basic authorization")
        c = _client(pool, cid or "")
        if not c:
            return _oauth_err(400, "invalid_client", "unknown client")
        if c.get("ClientSecret") and secret != c["ClientSecret"]:
            return _oauth_err(401, "invalid_client", "client authentication failed")
        gt = f.get("grant_type")
        if gt == "refresh_token":
            st, d = _moto("InitiateAuth", {"ClientId": cid, "AuthFlow": "REFRESH_TOKEN_AUTH", "AuthParameters": {"REFRESH_TOKEN": f.get("refresh_token", "")}})
            res = d.get("AuthenticationResult")
            if st != 200 or not res:
                return _oauth_err(400, "invalid_grant", "refresh token is invalid")
            tokens = dict(res, RefreshToken=f.get("refresh_token"))
        elif gt == "authorization_code":
            rec = _CODES.pop(f.get("code", ""), None)
            if not rec or rec["exp"] < time.time() or rec["client_id"] != cid or rec["pool"] != pool:
                return _oauth_err(400, "invalid_grant", "authorization code is invalid, expired or already used")
            if f.get("redirect_uri") != rec["redirect_uri"]:
                return _oauth_err(400, "invalid_grant", "redirect_uri does not match the authorization request")
            if rec["challenge"]:
                v = f.get("code_verifier") or ""
                chk = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
                if not v or chk != rec["challenge"]:
                    return _oauth_err(400, "invalid_grant", "PKCE code_verifier does not match the code_challenge")
            tokens = rec["tokens"]
        else:
            return _oauth_err(400, "unsupported_grant_type", "supported: authorization_code, refresh_token")
        out = {"access_token": tokens.get("AccessToken"), "id_token": tokens.get("IdToken"), "token_type": "Bearer", "expires_in": tokens.get("ExpiresIn", 3600)}
        if tokens.get("RefreshToken"):
            out["refresh_token"] = tokens["RefreshToken"]
        return {"status": 200, "headers": {"content-type": "application/json", "cache-control": "no-store"}, "body": json.dumps(out).encode()}
    if tail == "oauth2/userInfo":
        a = lheaders.get("authorization", "")
        st, d = _moto("GetUser", {"AccessToken": a[7:] if a.lower().startswith("bearer ") else ""})
        if st != 200:
            return _oauth_err(401, "invalid_token", "access token is invalid")
        claims = {x["Name"]: x["Value"] for x in d.get("UserAttributes", [])}
        claims["username"] = d.get("Username")
        return {"status": 200, "headers": {"content-type": "application/json"}, "body": json.dumps(claims).encode()}
    return None


# ── Cognito issuer -> JWKS (consumed by core/gateway_common.make_rs256_verifier) ───────────────────────────────────
_ISS = re.compile(r"^https?://cognito-idp\.([a-z0-9-]+)\.amazonaws\.com/([a-z0-9-]+_[A-Za-z0-9]+)/?$")


def local_jwks(issuer):
    """-> list of JWK dicts when `issuer` is a Cognito user pool that EXISTS in this simulator, else None (unknown pool: fail closed)."""
    m = _ISS.match(issuer or "")
    if not m or not available():
        return None
    try:
        from moto.cognitoidp.models import cognitoidp_backends
        pool = cognitoidp_backends[ACCOUNT][m.group(1)].user_pools.get(m.group(2))
        if pool is None:
            return None
        from moto.utilities.utils import load_resource
        return load_resource("cognitoidp/resources/jwks-public.json")["keys"]
    except Exception:
        return None


# ── WAFv2 enforcement (OWASP-lite) ────────────────────────────────────────────────────────────────────────────────
_RATE: dict = {}
_SQLI = re.compile(r"('|%27)\s*(or|and)\s+['\"\d]|union\s+(all\s+)?select|;\s*drop\s+table|--\s*$|/\*.*\*/", re.I)
_XSS = re.compile(r"<\s*script|javascript:|on(error|load|click)\s*=|<\s*img[^>]+src\s*=", re.I)
_ARN = re.compile(r"/(?:restapis|apis)/([A-Za-z0-9]+)/stages/([^/]+)$")


def _wacl_for(api_id, stage):
    from moto.wafv2.models import wafv2_backends
    for region in ("us-east-1",) + tuple(wafv2_backends[ACCOUNT].keys()):
        be = wafv2_backends[ACCOUNT][region]
        for w in be.wacls.values():
            for ra in w.associated_resources:
                m = _ARN.search(ra)
                if m and m.group(1) == api_id and m.group(2) == stage:
                    return be, w
    return None, None


def _field(sel, req):
    """FieldToMatch -> list of strings."""
    sel = sel or {}
    if "UriPath" in sel:
        return [req["path"]]
    if "QueryString" in sel:
        return [req["qs"]]
    if "Method" in sel:
        return [req["method"]]
    if "Body" in sel or "JsonBody" in sel:
        return [req["body"].decode("utf-8", "replace")]
    if "SingleHeader" in sel:
        return [req["headers"].get(sel["SingleHeader"].get("Name", "").lower(), "")]
    if "SingleQueryArgument" in sel:
        return [req["query"].get(sel["SingleQueryArgument"].get("Name", "").lower(), "")]
    if "AllQueryArguments" in sel:
        return list(req["query"].values())
    if "Headers" in sel:
        return list(req["headers"].values())
    return [req["path"]]


def _xform(vals, transforms):
    out = []
    for v in vals:
        for t in sorted(transforms or [], key=lambda t: t.get("Priority", 0)):
            ty = t.get("Type")
            if ty == "LOWERCASE":
                v = v.lower()
            elif ty == "URL_DECODE":
                from urllib.parse import unquote
                v = unquote(v)
            elif ty == "COMPRESS_WHITE_SPACE":
                v = re.sub(r"\s+", " ", v)
            elif ty == "HTML_ENTITY_DECODE":
                import html
                v = html.unescape(v)
        out.append(v)
    return out


def _cidr_match(ip, cidrs):
    import ipaddress
    try:
        a = ipaddress.ip_address(ip)
        return any(a in ipaddress.ip_network(c, strict=False) for c in cidrs)
    except ValueError:
        return False


def _eval(st, req, be, rule_key, now):
    if "NotStatement" in st:
        return not _eval(st["NotStatement"]["Statement"], req, be, rule_key, now)
    if "AndStatement" in st:
        return all(_eval(s, req, be, rule_key, now) for s in st["AndStatement"]["Statements"])
    if "OrStatement" in st:
        return any(_eval(s, req, be, rule_key, now) for s in st["OrStatement"]["Statements"])
    if "ByteMatchStatement" in st:
        b = st["ByteMatchStatement"]
        needle = b["SearchString"]
        if isinstance(needle, str):   # blob members travel base64 on the JSON wire
            try:
                needle = base64.b64decode(needle, validate=True).decode("utf-8", "replace")
            except Exception:
                pass
        elif isinstance(needle, bytes):
            needle = needle.decode("utf-8", "replace")
        pc = b.get("PositionalConstraint", "CONTAINS")
        for v in _xform(_field(b.get("FieldToMatch"), req), b.get("TextTransformations")):
            if (pc == "CONTAINS" and needle in v) or (pc == "EXACTLY" and v == needle) or (pc == "STARTS_WITH" and v.startswith(needle)) \
               or (pc == "ENDS_WITH" and v.endswith(needle)) or (pc == "CONTAINS_WORD" and re.search(r"\b" + re.escape(needle) + r"\b", v)):
                return True
        return False
    if "IPSetReferenceStatement" in st:
        s = st["IPSetReferenceStatement"]
        ipset = be.ip_sets.get(s["ARN"])
        if ipset is None:
            return False
        ip = req["ip"]
        fw = s.get("IPSetForwardedIPConfig")
        if fw:
            ip = (req["headers"].get(fw.get("HeaderName", "x-forwarded-for").lower(), "") or ip).split(",")[0].strip()
        return _cidr_match(ip, ipset.addresses)
    if "SizeConstraintStatement" in st:
        s = st["SizeConstraintStatement"]
        f = s.get("FieldToMatch") or {}
        n = len(req["body"]) if "Body" in f else (len(_field(f, req)[0].encode()))
        op, sz = s["ComparisonOperator"], int(s["Size"])
        return {"EQ": n == sz, "NE": n != sz, "LE": n <= sz, "LT": n < sz, "GE": n >= sz, "GT": n > sz}[op]
    if "RegexMatchStatement" in st:
        s = st["RegexMatchStatement"]
        return any(re.search(s["RegexString"], v) for v in _xform(_field(s.get("FieldToMatch"), req), s.get("TextTransformations")))
    if "RegexPatternSetReferenceStatement" in st:
        s = st["RegexPatternSetReferenceStatement"]
        ps = be.regex_pattern_sets.get(s["ARN"])
        pats = [(r.get("RegexString") if isinstance(r, dict) else r) for r in (getattr(ps, "regular_expressions", None) or [])]
        vals = _xform(_field(s.get("FieldToMatch"), req), s.get("TextTransformations"))
        return any(re.search(p, v) for p in pats if p for v in vals)
    if "SqliMatchStatement" in st:
        s = st["SqliMatchStatement"]
        return any(_SQLI.search(v) for v in _xform(_field(s.get("FieldToMatch"), req), s.get("TextTransformations") or [{"Priority": 0, "Type": "URL_DECODE"}]))
    if "XssMatchStatement" in st:
        s = st["XssMatchStatement"]
        return any(_XSS.search(v) for v in _xform(_field(s.get("FieldToMatch"), req), s.get("TextTransformations") or [{"Priority": 0, "Type": "URL_DECODE"}]))
    if "RateBasedStatement" in st:
        s = st["RateBasedStatement"]
        win = int(s.get("EvaluationWindowSec", 300))
        key = (rule_key, req["ip"])
        hits = [t for t in _RATE.get(key, []) if now - t < win] + [now]
        _RATE[key] = hits
        over = len(hits) > int(s["Limit"])
        sc = s.get("ScopeDownStatement")
        return over and (_eval(sc, req, be, rule_key, now) if sc else True)
    return False   # managed rule groups, geo, label, asn ... not evaluated


def reset_rate():
    _RATE.clear()


def waf_check(api_id, stage, method, path, query, headers, body, source_ip="127.0.0.1", now=None):
    """-> None to let the request through, else a router response dict (403 like real WAF) for a blocking rule."""
    if not available():
        return None
    try:
        be, w = _wacl_for(api_id, stage)
    except Exception:
        return None
    if w is None:
        return None
    now = now if now is not None else time.time()
    qd = {k.lower(): (v[0] if isinstance(v, list) else v) for k, v in (query or {}).items()}
    req = {"method": method.upper(), "path": "/" + path.lstrip("/") if not path.startswith("/") else path,
           "qs": "&".join(f"{k}={v}" for k, v in qd.items()), "query": qd,
           "headers": {k.lower(): str(v) for k, v in (headers or {}).items()}, "body": bytes(body or b""), "ip": source_ip}
    for r in sorted(w.rules, key=lambda r: getattr(r, "priority", 0)):
        d = r if isinstance(r, dict) else {"Name": r.name, "Statement": r.statement, "Action": r.action}
        act = d.get("Action") or d.get("action") or {}
        if not _eval(d.get("Statement") or {}, req, be, (w.arn, d.get("Name")), now):
            continue
        if "Count" in act:
            continue
        if "Allow" in act:
            return None
        if "Block" in act:
            return {"status": 403, "headers": {"content-type": "text/html", "x-amzn-waf-action": "block"},
                    "body": b"<html><head><title>403 Forbidden</title></head><body><center><h1>403 Forbidden</h1></center></body></html>"}
    if "Block" in (w.default_action or {}):
        return {"status": 403, "headers": {"content-type": "text/html"}, "body": b"Forbidden"}
    return None
