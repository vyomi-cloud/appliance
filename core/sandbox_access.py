"""Sandbox console access gate (appliance side).

In a Codespace the console is reachable at the forwarded URL
`https://<CODESPACE_NAME>-<port>.<forwarding domain>`, and the appliance has no
login of its own. This module makes that URL private: only someone holding a
`vy_sbx` cookie, which is obtained by presenting a short-lived RS256 token
minted by the Vyomi portal (`GET /sandbox/open/<grant>` -> `/_vy/access?token=`),
gets through. Everyone else (including other GitHub org members) gets 401/403.

Scope / safety
  * ON only when CODESPACE_NAME is set and VYOMI_SANDBOX_ACCESS != off.
  * Enforced only for requests whose Host (or X-Forwarded-Host) is the forwarded
    public host. localhost / 127.0.0.1 / container hostnames (the dev's own
    terminal, internal stack calls, SSH-pull readiness) stay open.
    VYOMI_SANDBOX_ACCESS_STRICT=1 flips this: everything but loopback hosts is
    gated (use if GitHub's proxy turns out to rewrite Host).
  * Exempt even on the public host: /healthz, /_vy/access, /api/sandbox/whoami
    (whoami answers {"authenticated": false} without a cookie).
  * Pure ASGI middleware, registered outermost, so HTTP *and* WebSocket upgrades
    and CORS preflights are all gated before any other layer sees them.
Crypto is reused from core.sso_config (RS256 JWKS verify); the portal public key
comes from the license backend's /.well-known/jwks.json (network first, cached by
core.license_remote) with the baked core/license_pubkey.pem as the air-gap fallback.
The cookie is HMAC-SHA256 signed with a per-boot random secret (override with
VYOMI_SBX_SECRET for multi-worker deployments); a restart simply asks the user to
re-open from the portal. Shared-instance mode (vyomi_dev cookie) is untouched.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

COOKIE_NAME = "vy_sbx"
COOKIE_MAX_AGE = 10 * 3600
TOKEN_AUD = "vyomi-sandbox-access"
CLOCK_SKEW = 30
MAX_TOKEN_LIFETIME = 300          # portal mints <=120s; refuse anything absurd
EXEMPT_PATHS = ("/healthz", "/_vy/access")
WHOAMI_PATH = "/api/sandbox/whoami"
_AVATAR_HOSTS = ("github.com", "avatars.githubusercontent.com")

_SECRET = os.environ.get("VYOMI_SBX_SECRET", "").encode() or secrets.token_bytes(32)
_used_jti: dict[str, float] = {}


# ── config helpers (read env fresh so tests/ops can toggle) ───────────────────
def codespace_name() -> str:
    return (os.environ.get("CODESPACE_NAME") or "").strip()


def enabled() -> bool:
    return bool(codespace_name()) and os.environ.get("VYOMI_SANDBOX_ACCESS", "").strip().lower() != "off"


def _domain() -> str:
    return (os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN") or "app.github.dev").strip().lower()


def portal_url() -> str:
    return (os.environ.get("VYOMI_LICENSE_BACKEND_URL") or os.environ.get("CLOUDLEARN_LICENSE_BACKEND_URL")
            or "https://vyomi.cloud").rstrip("/")


def _is_public_host(host: str) -> bool:
    """`<CODESPACE_NAME>-<port>.<domain>` (any port)."""
    h = host.split(":")[0].strip().lower()
    return bool(re.fullmatch(re.escape(codespace_name().lower()) + r"-\d+\." + re.escape(_domain()), h))


def _is_local_host(host: str) -> bool:
    return host.split(":")[0].strip().lower() in ("localhost", "127.0.0.1", "::1", "[::1]", "")


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── identity sanitising ───────────────────────────────────────────────────────
def _clean(v, n: int = 128) -> str:
    return re.sub(r"[\x00-\x1f\x7f<>\"'`]", "", str(v or "")).strip()[:n]


def _clean_avatar(v) -> str:
    u = urlparse(_clean(v, 300))
    return u.geturl() if u.scheme == "https" and (u.hostname or "") in _AVATAR_HOSTS else ""


def identity_from_claims(c: dict) -> dict:
    return {"sub": _clean(c.get("sub")), "name": _clean(c.get("name")), "login": _clean(c.get("login")),
            "email": _clean(c.get("email"), 200), "avatar": _clean_avatar(c.get("avatar")),
            "edition": c.get("edition") if c.get("edition") in ("enterprise", "personal") else "",
            "role": c.get("role") if c.get("role") in ("admin", "developer") else "developer"}


# ── cookie ────────────────────────────────────────────────────────────────────
def make_cookie(ident: dict, ttl: int = COOKIE_MAX_AGE) -> str:
    body = _b64e(json.dumps(dict(ident, exp=int(time.time()) + ttl), separators=(",", ":")).encode())
    return body + "." + _b64e(hmac.new(_SECRET, body.encode(), hashlib.sha256).digest())


def read_cookie(value: str) -> Optional[dict]:
    try:
        body, sig = value.split(".", 1)
        if not hmac.compare_digest(_b64e(hmac.new(_SECRET, body.encode(), hashlib.sha256).digest()), sig):
            return None
        d = json.loads(_b64d(body))
        return d if int(d.get("exp", 0)) > time.time() else None
    except Exception:
        return None


# ── token verification ────────────────────────────────────────────────────────
def _default_jwks() -> dict:
    from core import license_remote as lr
    j = lr._fetch_jwks(portal_url())
    if not j.get("keys"):
        j = lr._load_local_pubkey_as_jwks() or {"keys": []}
    return j


# Hook: tests replace this to inject a throwaway public key (JWKS dict).
JWKS_PROVIDER: Callable[[], dict] = _default_jwks


def verify_token(token: str) -> dict:
    """Return claims or raise ValueError(reason). Consumes the jti (single use)."""
    from core import sso_config
    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        raise ValueError("malformed")
    try:
        header = json.loads(sso_config._b64url_decode(parts[0]))
        claims = json.loads(sso_config._b64url_decode(parts[1]))
        sig = sso_config._b64url_decode(parts[2])
    except Exception:
        raise ValueError("malformed")
    if header.get("alg") != "RS256":
        raise ValueError("bad_alg")
    if not sso_config._verify_signature(header, f"{parts[0]}.{parts[1]}".encode("ascii"), sig, JWKS_PROVIDER()):
        raise ValueError("bad_signature")
    now = time.time()
    exp, iat = int(claims.get("exp") or 0), int(claims.get("iat") or 0)
    if exp < now - CLOCK_SKEW:
        raise ValueError("expired")
    if iat > now + CLOCK_SKEW or exp - iat > MAX_TOKEN_LIFETIME:
        raise ValueError("bad_lifetime")
    if claims.get("aud") != TOKEN_AUD:
        raise ValueError("bad_audience")
    if claims.get("cs") != codespace_name():
        raise ValueError("wrong_codespace")
    jti = str(claims.get("jti") or "")
    if not jti:
        raise ValueError("no_jti")
    for k in [k for k, t in _used_jti.items() if t < now]:     # purge
        _used_jti.pop(k, None)
    if jti in _used_jti:
        raise ValueError("replayed")
    _used_jti[jti] = exp + CLOCK_SKEW
    return claims


# ── ASGI plumbing ─────────────────────────────────────────────────────────────
def _hdr(scope, name: bytes) -> str:
    for k, v in scope.get("headers") or []:
        if k == name:
            return v.decode("latin-1")
    return ""


def _cookie_from(scope) -> Optional[dict]:
    for part in _hdr(scope, b"cookie").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE_NAME:
            return read_cookie(v)
    return None


def _is_browser_nav(scope) -> bool:
    if scope.get("method") != "GET" or scope.get("path", "").startswith("/api"):
        return False
    if _hdr(scope, b"x-requested-with"):
        return False
    mode = _hdr(scope, b"sec-fetch-mode")
    return (mode == "navigate") if mode else ("text/html" in _hdr(scope, b"accept"))


_PAGE = """<!doctype html><meta charset=utf-8><title>Private sandbox</title>
<body style="font-family:system-ui;background:#0b0d12;color:#e5e7eb;display:grid;place-items:center;height:100vh;margin:0">
<div style="max-width:460px;text-align:center"><h2>{title}</h2><p style="color:#9ca3af">{msg}</p>
<p><a style="color:#818cf8" href="{url}/dashboard">Go to the Vyomi portal</a></p></div>"""


async def _send(send, status: int, body: bytes, ctype: str, extra=()):
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", ctype.encode()), (b"content-length", str(len(body)).encode()),
                            (b"cache-control", b"no-store"), *extra]})
    await send({"type": "http.response.body", "body": body})


async def _deny(scope, send, status: int, code: str, html_title: str, html_msg: str):
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    if _is_browser_nav(scope) or scope.get("path") == "/_vy/access":
        page = _PAGE.format(title=html_title, msg=html_msg, url=portal_url())
        await _send(send, status, page.encode(), "text/html; charset=utf-8")
    else:
        await _send(send, status, json.dumps({"error": code, "message": html_msg, "portal": portal_url()}).encode(),
                    "application/json")


class SandboxAccessMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        path = scope.get("path", "")

        if scope["type"] == "http" and path == WHOAMI_PATH:
            ident = _cookie_from(scope) if enabled() else None
            out = {"authenticated": False}
            if ident:
                out = {"authenticated": True, **{k: ident.get(k, "") for k in
                       ("name", "login", "email", "avatar", "edition", "role")}}
            return await _send(send, 200, json.dumps(out).encode(), "application/json")

        if not enabled():
            return await self.app(scope, receive, send)
        host = _hdr(scope, b"host")
        fwd = _hdr(scope, b"x-forwarded-host").split(",")[0]
        strict = os.environ.get("VYOMI_SANDBOX_ACCESS_STRICT", "").strip().lower() in ("1", "true", "on", "yes")
        external = _is_public_host(host) or (bool(fwd) and _is_public_host(fwd)) or \
            (strict and not _is_local_host(host))
        if not external:
            return await self.app(scope, receive, send)

        if scope["type"] == "http" and path == "/_vy/access":
            return await self._access(scope, send)
        if path == "/healthz" and scope["type"] == "http":
            return await self.app(scope, receive, send)
        if _cookie_from(scope):
            return await self.app(scope, receive, send)
        await _deny(scope, send, 401, "sandbox_private", "This sandbox is private",
                    "Open it from the Vyomi portal (sign in, then use Open console).")

    async def _access(self, scope, send):
        token = (parse_qs(scope.get("query_string", b"").decode("latin-1")).get("token") or [""])[0]
        try:
            # JWKS fetch may hit the network -> keep it off the event loop.
            claims = await asyncio.get_running_loop().run_in_executor(None, verify_token, token)
        except Exception as e:
            reason = str(e) if isinstance(e, ValueError) else "error"
            return await _deny(scope, send, 403, "access_denied", "Access link not valid",
                               f"This sign-in link is invalid, expired or already used ({reason}). "
                               "Open the sandbox again from the Vyomi portal.")
        cookie = (f"{COOKIE_NAME}={make_cookie(identity_from_claims(claims))}; Path=/; Max-Age={COOKIE_MAX_AGE}; "
                  "HttpOnly; Secure; SameSite=Lax")
        await _send(send, 302, b"", "text/plain", [(b"location", b"/"), (b"set-cookie", cookie.encode())])


def register(app) -> None:
    """Add as the OUTERMOST layer (call after every other add_middleware)."""
    app.add_middleware(SandboxAccessMiddleware)
