"""Cross-cloud gateway primitives — ONE implementation shared by every cloud's gateway data plane.

Used by AWS API Gateway v2 (core/apigatewayv2_gateway.py + providers/aws_apigatewayv2_gateway.py), AWS API Gateway v1 REST
(core/apigateway_core.py invoke), GCP API Gateway (core/gcp_apigateway_gateway.py) and Azure APIM (core/azure_apim_gateway_core.py).

  Throttle            token bucket (rate tokens/s, capacity burst) per key
  window_take         fixed-window quota counter (used by GCP quota, APIM rate-limit/quota policies, REST usage plans)
  hget / b64u         case-insensitive header lookup, unpadded base64url decode
  jwt_validate        structure + (injected) signature + exp/nbf/iss/aud/client_id; -> (claims|None, scopes)
  make_rs256_verifier RS256 verifier over a JWKS (explicit jwks_uri, else OIDC discovery of the issuer); fails closed
  strip_hop           drop hop-by-hop / host headers before forwarding
  build_backend_url   backend base + path (+ query) with APPEND_PATH / CONSTANT_ADDRESS semantics
  default_http_fetch  urllib-based `fetch(method, url, headers, body, timeout) -> (status, headers, bytes)`; None on Nano (emscripten)

Substrate-free: no fastapi / socket at import time (urllib and `cryptography` are imported lazily inside the factories).
"""
from __future__ import annotations

import base64
import json
import sys
import time
from urllib.parse import urlencode, urlsplit

HOP_HEADERS = ("host", "content-length", "connection", "transfer-encoding", "keep-alive", "te", "upgrade")
RESP_HOP_HEADERS = ("transfer-encoding", "connection", "content-length")


def hget(headers, name, default=None):
    n = name.lower()
    for k, v in (headers or {}).items():
        if k.lower() == n:
            return v
    return default


def b64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── throttling / quota ───────────────────────────────────────────────────────
class Throttle:
    """Token bucket per key: `rate` tokens/s, capacity `burst`."""

    def __init__(self, clock=time.monotonic):
        self._b: dict = {}
        self._clock = clock

    def allow(self, key, rate, burst) -> bool:
        if rate is None and burst is None:
            return True
        rate = float(rate if rate is not None else burst)
        cap = float(burst if burst is not None else max(1.0, rate))
        now = self._clock()
        tokens, last = self._b.get(key, (cap, now))
        tokens = min(cap, tokens + (now - last) * rate)
        if tokens < 1.0:
            self._b[key] = (tokens, now)
            return False
        self._b[key] = (tokens - 1.0, now)
        return True


def window_take(bag: dict, key, now: float, period: float, cost: int = 1, cap=None, count_rejected: bool = False):
    """Fixed-window counter. `bag[key] = [window_start, used]`. -> (allowed, wait_seconds).

    The window restarts once `period` seconds have elapsed. A request is refused when it would push `used` over `cap`
    (`cap=None` never refuses). `count_rejected=True` counts the refused request too (APIM's rate-limit policy counts every call);
    the default leaves the counter untouched on refusal (GCP quota)."""
    w = bag.get(key)
    if not w or now - w[0] >= period:
        w = [now, 0]
    over = cap is not None and w[1] + cost > cap
    if not over or count_rejected:
        w[1] += cost
    bag[key] = w
    return (not over), (max(1, int(period - (now - w[0]))) if over else 0)


# ── JWT ──────────────────────────────────────────────────────────────────────
def jwt_validate(token, cfg, verify_sig=None, now=None):
    """-> (claims | None, scopes). Checks structure, signature (if a verifier is injected),
    exp/nbf, issuer, and audience / client_id."""
    try:
        h, p, _ = token.split(".")
        header, claims = json.loads(b64u(h)), json.loads(b64u(p))
    except Exception:
        return None, []
    now = now if now is not None else time.time()
    if verify_sig is not None and not verify_sig(token, header, cfg):
        return None, []
    if "exp" in claims and now >= float(claims["exp"]):
        return None, []
    if "nbf" in claims and now < float(claims["nbf"]):
        return None, []
    if cfg.get("issuer") and claims.get("iss") != cfg["issuer"]:
        return None, []
    aud = cfg.get("audience") or []
    if aud:
        got = claims.get("aud")
        got = got if isinstance(got, list) else [got] if got is not None else []
        if claims.get("client_id") is not None:
            got.append(claims["client_id"])
        if not set(aud) & set(got):
            return None, []
    scopes = claims.get("scope", claims.get("scp", []))
    scopes = scopes.split() if isinstance(scopes, str) else list(scopes or [])
    return claims, scopes


_JWKS: dict = {}


def reset_jwks_cache():
    _JWKS.clear()


def make_rs256_verifier(ttl: float = 300.0, timeout: float = 5.0, fetch_json=None):
    """-> `verify(token, header, cfg) -> bool` (RS256 only), or None when it cannot run here (Nano / no `cryptography`).

    Keys come from `cfg["jwks_uri"]` when set, else OIDC discovery of `cfg["issuer"]`; cached `ttl` seconds. Anything else — another
    alg, an unknown kid, an unreachable issuer, a bad signature — returns False: a token we could not verify is never admitted.
    `fetch_json(url) -> dict` is injectable for tests."""
    if sys.platform == "emscripten":
        return None
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
    except ImportError:
        return None

    def get_json(url):
        if fetch_json is not None:
            return fetch_json(url)
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)

    def keys(cfg):
        ck = cfg.get("jwks_uri") or cfg["issuer"]
        hit = _JWKS.get(ck)
        if hit and hit[0] > time.time():
            return hit[1]
        uri = cfg.get("jwks_uri")
        if not uri:
            uri = get_json(cfg["issuer"].rstrip("/") + "/.well-known/openid-configuration")["jwks_uri"]
        ks = get_json(uri)["keys"]
        _JWKS[ck] = (time.time() + ttl, ks)
        return ks

    def verify(token, header, cfg):
        try:
            if header.get("alg") != "RS256":
                return False
            h, p, sig = token.split(".")
            key = next((k for k in keys(cfg) if k.get("kid") == header.get("kid") and k.get("kty") == "RSA"), None)
            if key is None:
                return False
            n, e = (int.from_bytes(b64u(key[x]), "big") for x in ("n", "e"))
            rsa.RSAPublicNumbers(e, n).public_key().verify(b64u(sig), ("%s.%s" % (h, p)).encode(), padding.PKCS1v15(), hashes.SHA256())
            return True
        except Exception:
            return False
    return verify


# ── forwarding ───────────────────────────────────────────────────────────────
def strip_hop(headers, extra=()):
    """Request headers minus hop-by-hop / host / content-length (and `extra`, lower-case names)."""
    drop = set(HOP_HEADERS) | set(extra)
    return {k: v for k, v in (headers or {}).items() if k.lower() not in drop}


def strip_resp_hop(headers):
    return {k: v for k, v in (headers or {}).items() if k.lower() not in RESP_HOP_HEADERS}


def build_backend_url(address: str, path: str, params=None, query=None, mode=None) -> str:
    """Backend URL for one request. `mode` CONSTANT_ADDRESS: the address as-is, path params go to the query string;
    APPEND_PATH_TO_ADDRESS: address + "/" + path. Default: CONSTANT when the address already carries a path, else APPEND."""
    has_path = bool(urlsplit(address).path.strip("/"))
    mode = mode or ("CONSTANT_ADDRESS" if has_path else "APPEND_PATH_TO_ADDRESS")
    q = dict(query or {})
    if mode == "CONSTANT_ADDRESS":
        q.update(params or {})
        url = address
    else:
        url = address.rstrip("/") + "/" + path.strip("/") if path.strip("/") else address
    return url + (("&" if "?" in url else "?") + urlencode(q) if q else "")


def default_http_fetch():
    """`fetch(method, url, headers, body, timeout) -> (status, headers, bytes)`; 4xx/5xx are returned, not raised. None on Nano."""
    if sys.platform == "emscripten":
        return None
    import urllib.error
    import urllib.request

    def fetch(method, url, headers, body, timeout):
        req = urllib.request.Request(url, data=body or None, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()
    return fetch
