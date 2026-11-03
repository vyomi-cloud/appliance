# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Workload / Workforce Identity Federation engine: provider validation, attribute mapping, attribute
conditions and RS256 subject-token verification (substrate-independent, stdlib only).

Shared by core/gcp_iam_core.py (workload identity pool providers) and core/gcp_resourcemanager_core.py
(workforce pool providers). Real behaviour implemented:
  * provider config validation (OIDC issuer/audiences/JWKS, AWS account, SAML metadata, display name, id rules)
  * attributeMapping: `assertion.<claim path>`, string literals, `+` concatenation, `.lowerAscii()`; google.subject
    is required and <=127 chars; attribute.* keys are limited to 50 and valid identifiers
  * attributeCondition: a CEL subset — `==`, `!=`, `in [..]`, `.startsWith/.endsWith/.contains(..)`, `has(..)`-free,
    `&&`, `||`, `!`, parentheses, over `assertion.*` and `attribute.*`
  * OIDC subject-token verification: structure, `iss` == issuerUri, `aud` in allowedAudiences, exp/nbf, and the
    RS256 signature against the provider's `jwksJson` (Vyomi has no network egress, so it cannot fetch the issuer's
    JWKS URL — a provider without jwksJson cannot verify tokens, as in an air-gapped deployment).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time

_ID = re.compile(r"^[a-z]([a-z0-9-]{2,30})[a-z0-9]$")
_ATTR_KEY = re.compile(r"^attribute\.[A-Za-z_][A-Za-z0-9_]{0,99}$")
_ANY = object()


class WifError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


# ── validation ─────────────────────────────────────────────────────────────
def valid_provider_id(pid):
    if not _ID.match(pid or "") or pid.startswith("gcp-"):
        raise WifError("Provider ID must be 4-32 characters (lowercase letters, digits, hyphens), start with a letter, and must not start with 'gcp-'.")


def validate_provider(body):
    """Validate + normalise a provider body. Exactly one of oidc / saml / aws."""
    kinds = [k for k in ("oidc", "saml", "aws") if body.get(k)]
    if len(kinds) != 1:
        raise WifError("Exactly one of oidc, saml or aws must be set on a provider.")
    kind = kinds[0]
    cfg = dict(body[kind])
    if kind == "oidc":
        iss = str(cfg.get("issuerUri") or "")
        if not iss.startswith("https://") or len(iss) < 12:
            raise WifError("oidc.issuerUri must be an https:// URL.")
        if cfg.get("allowedAudiences") is not None and not isinstance(cfg["allowedAudiences"], list):
            raise WifError("oidc.allowedAudiences must be a list.")
        if cfg.get("jwksJson"):
            try:
                keys = json.loads(cfg["jwksJson"]).get("keys")
                assert isinstance(keys, list) and keys
            except Exception:
                raise WifError("oidc.jwksJson must be a JWKS document: {\"keys\": [ ... ]}.")
    elif kind == "aws":
        if not re.match(r"^\d{12}$", str(cfg.get("accountId") or "")):
            raise WifError("aws.accountId must be a 12-digit AWS account ID.")
    else:
        xml = str(cfg.get("idpMetadataXml") or "")
        if "EntityDescriptor" not in xml:
            raise WifError("saml.idpMetadataXml must be SAML IdP metadata (an EntityDescriptor document).")
    mapping = dict(body.get("attributeMapping") or {})
    if kind != "aws" and "google.subject" not in mapping:
        raise WifError("attributeMapping must map google.subject (e.g. \"assertion.sub\").")
    if len([k for k in mapping if k.startswith("attribute.")]) > 50:
        raise WifError("At most 50 custom attributes may be mapped.")
    for k, expr in mapping.items():
        if k not in ("google.subject", "google.groups") and not _ATTR_KEY.match(k):
            raise WifError("Invalid attributeMapping key %r (use google.subject, google.groups or attribute.NAME)." % k)
        try:
            _compile_value(str(expr))
        except WifError as e:
            raise WifError("attributeMapping[%s]: %s" % (k, e.message))
    cond = str(body.get("attributeCondition") or "")
    if cond:
        try:
            _compile_cond(cond)
        except WifError as e:
            raise WifError("attributeCondition: %s" % e.message)
    return kind


# ── tiny expression engine ───────────────────────────────────────────────
_TOK = re.compile(r'\s*(?:(&&|\|\||==|!=|[()!\[\],+.])|"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|([A-Za-z_][A-Za-z0-9_]*)|(\d+))')


def _tokens(src):
    out, pos = [], 0
    src = src.rstrip()
    while pos < len(src):
        m = _TOK.match(src, pos)
        if not m or m.end() == pos:
            raise WifError("unexpected character at %r" % src[pos:pos + 10])
        pos = m.end()
        op, dq, sq, ident, num = m.groups()
        if op:
            out.append(("op", op))
        elif dq is not None:
            out.append(("str", dq.encode().decode("unicode_escape")))
        elif sq is not None:
            out.append(("str", sq))
        elif ident:
            out.append(("id", ident))
        else:
            out.append(("num", int(num)))
    return out


class _P:
    def __init__(self, src, mapping_mode):
        self.t, self.i, self.mapping = _tokens(src), 0, mapping_mode

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def eat(self, kind=None, val=None):
        k, v = self.peek()
        if k is None or (kind and k != kind) or (val is not None and v != val):
            raise WifError("expected %s" % (val or kind or "more input"))
        self.i += 1
        return v

    def parse(self):
        node = self.or_()
        if self.i != len(self.t):
            raise WifError("unexpected %r" % (self.peek()[1],))
        return node

    def or_(self):
        n = self.and_()
        while self.peek() == ("op", "||"):
            self.eat(); n = ("or", n, self.and_())
        return n

    def and_(self):
        n = self.not_()
        while self.peek() == ("op", "&&"):
            self.eat(); n = ("and", n, self.not_())
        return n

    def not_(self):
        if self.peek() == ("op", "!"):
            self.eat(); return ("not", self.not_())
        return self.cmp_()

    def cmp_(self):
        n = self.add_()
        k, v = self.peek()
        if (k, v) in (("op", "=="), ("op", "!=")):
            self.eat(); return ("cmp", v, n, self.add_())
        if (k, v) == ("id", "in"):
            self.eat(); return ("in", n, self.add_())
        return n

    def add_(self):
        n = self.post_()
        while self.peek() == ("op", "+"):
            self.eat(); n = ("add", n, self.post_())
        return n

    def post_(self):
        n = self.atom()
        while self.peek() == ("op", "."):
            self.eat(); name = self.eat("id")
            if self.peek() == ("op", "("):
                self.eat(); args = []
                if self.peek() != ("op", ")"):
                    args.append(self.or_())
                    while self.peek() == ("op", ","):
                        self.eat(); args.append(self.or_())
                self.eat("op", ")")
                if name not in ("startsWith", "endsWith", "contains", "lowerAscii", "upperAscii"):
                    raise WifError("unsupported function .%s()" % name)
                n = ("call", name, n, args)
            else:
                n = ("attr", n, name)
        return n

    def atom(self):
        k, v = self.peek()
        if k == "str" or k == "num":
            self.eat(); return ("lit", v)
        if (k, v) == ("op", "("):
            self.eat(); n = self.or_(); self.eat("op", ")"); return n
        if (k, v) == ("op", "["):
            self.eat(); items = []
            if self.peek() != ("op", "]"):
                items.append(self.or_())
                while self.peek() == ("op", ","):
                    self.eat(); items.append(self.or_())
            self.eat("op", "]"); return ("list", items)
        if k == "id":
            self.eat()
            if v in ("true", "false"):
                return ("lit", v == "true")
            if v not in ("assertion", "attribute") and not (v == "google"):
                raise WifError("unknown identifier %r (use assertion.* or attribute.*)" % v)
            return ("var", v)
        raise WifError("unexpected %r" % (v,))


def _compile_value(src):
    return _P(src, True).parse()


def _compile_cond(src):
    return _P(src, False).parse()


def _ev(n, env):
    t = n[0]
    if t == "lit":
        return n[1]
    if t == "list":
        return [_ev(x, env) for x in n[1]]
    if t == "var":
        return env.get(n[1], {})
    if t == "attr":
        base = _ev(n[1], env)
        return base.get(n[2]) if isinstance(base, dict) else None
    if t == "add":
        a, b = _ev(n[1], env), _ev(n[2], env)
        if a is None or b is None:
            raise WifError("a referenced claim is missing")
        return str(a) + str(b)
    if t == "cmp":
        a, b = _ev(n[2], env), _ev(n[3], env)
        return (a == b) if n[1] == "==" else (a != b)
    if t == "in":
        return _ev(n[1], env) in (_ev(n[2], env) or [])
    if t == "and":
        return bool(_ev(n[1], env)) and bool(_ev(n[2], env))
    if t == "or":
        return bool(_ev(n[1], env)) or bool(_ev(n[2], env))
    if t == "not":
        return not _ev(n[1], env)
    if t == "call":
        s = _ev(n[2], env)
        if s is None:
            raise WifError("a referenced claim is missing")
        s = str(s)
        args = [_ev(a, env) for a in n[3]]
        return {"startsWith": lambda: s.startswith(str(args[0])), "endsWith": lambda: s.endswith(str(args[0])),
                "contains": lambda: str(args[0]) in s, "lowerAscii": lambda: s.lower(), "upperAscii": lambda: s.upper()}[n[1]]()
    raise WifError("bad expression")


def map_attributes(provider, claims):
    """Apply the provider's attributeMapping to the external token's claims -> {google.subject, attribute.*}."""
    out = {}
    for k, expr in (provider.get("attributeMapping") or {}).items():
        try:
            v = _ev(_compile_value(str(expr)), {"assertion": claims})
        except WifError:
            v = None
        if v is not None:
            out[k] = v
    sub = out.get("google.subject")
    if sub is not None and len(str(sub)) > 127:
        raise WifError("google.subject exceeds 127 characters.")
    return out


def check_condition(provider, claims, attributes):
    cond = str(provider.get("attributeCondition") or "")
    if not cond:
        return True
    attr = {k.split(".", 1)[1]: v for k, v in attributes.items() if k.startswith("attribute.")}
    try:
        return bool(_ev(_compile_cond(cond), {"assertion": claims, "attribute": attr}))
    except WifError:
        return False


# ── OIDC subject token ───────────────────────────────────────────────────
def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _rs256_ok(signing_input, sig, jwk):
    n, e = int.from_bytes(_b64d(jwk["n"]), "big"), int.from_bytes(_b64d(jwk["e"]), "big")
    k = (n.bit_length() + 7) // 8
    em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    digest = hashlib.sha256(signing_input).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(_SHA256_PREFIX) - len(digest) - 3) + b"\x00" + _SHA256_PREFIX + digest
    return em == expected


def verify_subject_token(provider, token, now=None):
    """-> claims dict, or raises WifError (maps to 400 invalid_grant)."""
    oidc = provider.get("oidc")
    if not oidc:
        raise WifError("Only OIDC providers can verify a JWT subject token in Vyomi.")
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise WifError("The subject token is not a JWT.")
    try:
        header, claims = json.loads(_b64d(parts[0])), json.loads(_b64d(parts[1]))
    except Exception:
        raise WifError("The subject token is not a well-formed JWT.")
    if claims.get("iss") != oidc.get("issuerUri"):
        raise WifError("The token issuer %r does not match the provider's issuerUri." % claims.get("iss"))
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    allowed = oidc.get("allowedAudiences") or [provider.get("_defaultAudience", "")]
    if not any(a in allowed for a in auds if a):
        raise WifError("The token audience is not in the provider's allowedAudiences.")
    t = now if now is not None else time.time()
    if "exp" in claims and t > float(claims["exp"]) + 60:
        raise WifError("The subject token has expired.")
    if "nbf" in claims and t + 60 < float(claims["nbf"]):
        raise WifError("The subject token is not yet valid.")
    if not oidc.get("jwksJson"):
        raise WifError("This provider has no jwksJson: Vyomi cannot fetch the issuer's JWKS (no network egress), so it cannot verify the signature.")
    if header.get("alg") != "RS256":
        raise WifError("Only RS256 subject tokens are supported.")
    keys = json.loads(oidc["jwksJson"]).get("keys") or []
    key = next((k for k in keys if k.get("kid") == header.get("kid")), None) or (keys[0] if len(keys) == 1 else None)
    if not key or key.get("kty") != "RSA":
        raise WifError("No matching RSA key in the provider's jwksJson for kid %r." % header.get("kid"))
    if not _rs256_ok((parts[0] + "." + parts[1]).encode(), _b64d(parts[2]), key):
        raise WifError("The subject token signature is invalid.")
    return claims


# ── provider resources (shared CRUD) ─────────────────────────────────────
def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _view(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}


def dispatch_providers(providers, pool_name, rest, method, query, body):
    """CRUD for `{pool_name}/providers[/{id}]` over the dict `providers` (full provider name -> provider).
    `rest` is the path after `.../providers` (e.g. [] or ["my-idp"]). -> (status, json-able)."""
    prefix = pool_name + "/providers/"
    try:
        if not rest:
            if method == "POST":
                pid = str(query.get("workloadIdentityPoolProviderId") or query.get("workforcePoolProviderId") or "").strip()
                valid_provider_id(pid)
                name = prefix + pid
                if name in providers and providers[name].get("state") != "DELETED":
                    return 409, ("ALREADY_EXISTS", "Provider %s already exists." % pid)
                kind = validate_provider(body)
                p = {"name": name, "displayName": body.get("displayName", pid), "description": body.get("description", ""),
                     "state": "ACTIVE", "disabled": bool(body.get("disabled", False)), kind: dict(body[kind]),
                     "attributeMapping": dict(body.get("attributeMapping") or {}),
                     "attributeCondition": str(body.get("attributeCondition") or ""), "createTime": _now()}
                if kind == "oidc" and not p["oidc"].get("allowedAudiences"):
                    p["_defaultAudience"] = "//iam.googleapis.com/" + name
                providers[name] = p
                return 200, _view(p)
            if method == "GET":
                items = [_view(p) for n, p in sorted(providers.items()) if n.startswith(prefix) and p.get("state") != "DELETED"]
                return 200, {"providers" if "workforcePools" in pool_name else "workloadIdentityPoolProviders": items}
            return 400, ("INVALID_ARGUMENT", "Unsupported method %s on providers." % method)
        name = prefix + rest[0]
        p = providers.get(name)
        if p is None or p.get("state") == "DELETED":
            return 404, ("NOT_FOUND", "Provider not found: %s" % name)
        if method == "GET":
            return 200, _view(p)
        if method == "DELETE":
            p["state"] = "DELETED"
            return 200, _view(p)
        if method == "PATCH":
            merged = dict(_view(p)); merged.update({k: v for k, v in body.items() if k in ("displayName", "description", "disabled", "attributeMapping", "attributeCondition", "oidc", "saml", "aws")})
            kind = validate_provider(merged)
            for k in ("displayName", "description", "disabled", "attributeMapping", "attributeCondition", kind):
                if k in merged:
                    p[k] = merged[k]
            return 200, _view(p)
        return 400, ("INVALID_ARGUMENT", "Unsupported method %s on provider." % method)
    except WifError as e:
        return 400, ("INVALID_ARGUMENT", e.message)


# ── STS (sts.googleapis.com): token exchange + introspection ─────────────────
_AUD = re.compile(r"^//iam\.googleapis\.com/(?:projects/[^/]+/)?locations/global/(workloadIdentityPools|workforcePools)/([^/]+)/providers/([^/]+)$")


def find_provider(pool_providers, audience):
    """Resolve an STS `audience` to a stored provider (project id or number both accepted)."""
    m = _AUD.match(audience or "")
    if not m:
        return None
    kind, pool, prov = m.groups()
    tail = "/locations/global/%s/%s/providers/%s" % (kind, pool, prov)
    for name, p in pool_providers.items():
        if name.endswith(tail) and p.get("state") != "DELETED":
            return p
    return None


def exchange(providers, tokens, params):
    """RFC 8693 token exchange. -> (status, body). Mints a federated access token bound to the mapped identity."""
    if params.get("grant_type") != "urn:ietf:params:oauth:grant-type:token-exchange":
        return 400, {"error": "unsupported_grant_type", "error_description": "grant_type must be urn:ietf:params:oauth:grant-type:token-exchange."}
    if params.get("subject_token_type") not in ("urn:ietf:params:oauth:token-type:jwt", "urn:ietf:params:oauth:token-type:id_token", None, ""):
        return 400, {"error": "invalid_request", "error_description": "Unsupported subject_token_type (use a JWT)."}
    prov = find_provider(providers, params.get("audience"))
    if prov is None:
        return 400, {"error": "invalid_target", "error_description": "The audience does not name an existing workload/workforce identity pool provider."}
    if prov.get("disabled"):
        return 400, {"error": "invalid_grant", "error_description": "The provider is disabled."}
    try:
        claims = verify_subject_token(prov, params.get("subject_token"))
        attrs = map_attributes(prov, claims)
    except WifError as e:
        return 400, {"error": "invalid_grant", "error_description": e.message}
    if "google.subject" not in attrs:
        return 400, {"error": "invalid_grant", "error_description": "google.subject could not be mapped from the token."}
    if not check_condition(prov, claims, attrs):
        return 403, {"error": "access_denied", "error_description": "The attribute condition was not satisfied by the subject token."}
    pool_name = prov["name"].rsplit("/providers/", 1)[0]
    tok = "ya29.vyomi-" + hashlib.sha256((prov["name"] + str(attrs) + str(time.time())).encode()).hexdigest()[:40]
    principal = ("principal://iam.googleapis.com/%s/subject/%s" % (pool_name, attrs["google.subject"]))
    tokens[tok] = {"principal": principal, "attributes": attrs, "provider": prov["name"], "exp": int(time.time()) + 3600}
    return 200, {"access_token": tok, "issued_token_type": "urn:ietf:params:oauth:token-type:access_token", "token_type": "Bearer", "expires_in": 3600}


def introspect(tokens, params):
    t = tokens.get(params.get("token", ""))
    if not t or t["exp"] < time.time():
        return 200, {"active": False}
    return 200, {"active": True, "sub": t["principal"], "exp": t["exp"], "scope": "https://www.googleapis.com/auth/cloud-platform", "attributes": t["attributes"]}
