"""Mesh SESSION token + server-side enforcement (headless mesh role, VYOMI_ROLE=mesh).

The portal mints a short-lived signed *session token* for each mesh session (design s6.3/s6.4). It carries the facts the
mesh must not take from the client: tier, primary_cloud (Pro), account, session_id and `session_end` (epoch seconds).
The mesh verifies it OFFLINE with a shared key (env VYOMI_MESH_SESSION_KEY) and:

  * refuses every request once `session_end` has passed (the headless mesh self-expires its API too);
  * Pro: serves ONE cloud only (token.primary_cloud, or the first cloud used when the token leaves it empty);
    Max: all clouds; anything else: refused;
  * fails closed: in the mesh role, no key / no token / bad signature = nothing is served (except /healthz while valid,
    so the boot script's readiness probe works once a token is configured).

Token wire format v1 (also verified by wasm/relay/mesh-session.mjs, which handles v2 the same way):
    v1.<b64url(payload-json)>.<b64url(HMAC-SHA256(key, "v1." + b64url(payload-json)))>

v1 is a shared-key HMAC: the portal hands the Codespace the (per-session) key, so the Codespace owner can mint their
own tokens - any tier, any session_end - for their own Mesh (MCP-GUARDRAILS-INCIDENT-DESIGN.md, finding F2).

v2 fixes that with Ed25519: the portal signs with a private key the Mesh never sees, and the Mesh verifies with a public
key PINNED IN THIS FILE (TRUSTED_KEYS), never one read from the environment or a file, which the Codespace owner controls:
    v2.<b64url(payload-json, incl. "kid")>.<b64url(Ed25519 signature over "v2." + b64url(payload-json))>
Rollout (docs/architecture/v4.0/MESH-SESSION-ED25519.md): the portal has minted v2 since 2026-11-22 12:02 IST, every live
session is v2, so V1_ACCEPTED = False here and in wasm/relay/mesh-session.mjs: v1 tokens are refused (MeshSessionV1Retired)
and F2 is closed. The v1 code stays until phase 4 removes it. Tests sign v2 with the public test vector: tests/mesh_testkey.py.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
from typing import Any, Optional

AUD = "vyomi-mesh-session"
VERSION = "v1"
VERSION_V2 = "v2"

# Ed25519 public keys of the portal's session signer: key id -> base64url raw 32-byte public key. PINNED IN CODE on
# purpose (see the module docstring). Add a key with `python3 scripts/mesh-session-keygen.py`; keep the old one until no
# live session uses it. wasm/relay/mesh-session.mjs carries the same set (tests/test_mesh_session_v2.py checks they match).
TRUSTED_KEYS: dict[str, str] = {
    "portal-2026-11": "gFxVrZy9w3W4r-qhGzAW-nkN0vUrUF6tnzSeAqCovrM",   # generated 2026-11-21 (owner); private seed only in the portal secret store
}

# HMAC (v1) tokens: retired 2026-11-22 (the portal mints v2 for every session). A code constant, not an env switch: an env
# switch is under the Codespace owner's control and would reopen F2. Tests that exercise the v1 code opt in explicitly.
V1_ACCEPTED = False
HEADER = "x-vyomi-session-token"
CLOCK_SKEW_S = 30
_EXEMPT_PATHS = ("/healthz",)


class SessionError(Exception):
    def __init__(self, code: str, message: str, status: int = 401):
        self.code, self.message, self.status = code, message, status
        super().__init__(f"{code}: {message}")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def role_is_mesh() -> bool:
    return (os.environ.get("VYOMI_ROLE") or "").strip().lower() == "mesh"


def _key(key: Optional[str] = None) -> bytes:
    k = key if key is not None else os.environ.get("VYOMI_MESH_SESSION_KEY", "")
    if not k:
        raise SessionError("MeshSessionKeyMissing", "VYOMI_MESH_SESSION_KEY is not set on this mesh", 503)
    return k.encode()


def mint(account: str, tier: str, session_end: float, *, primary_cloud: str = "", session_id: str = "",
         key: Optional[str] = None, now: Optional[float] = None, role: str = "", model: str = "") -> str:
    """Portal-side minting (also used by tests). `session_end` is epoch seconds."""
    now = time.time() if now is None else now
    payload = {"aud": AUD, "sub": account, "tier": tier, "primary_cloud": primary_cloud, "session_id": session_id,
               "iat": int(now), "session_end": int(session_end)}
    if role:                    # e.g. "llm-runner": a token that may ONLY dial the LLM plane of the relay (never drive a mesh)
        payload["role"] = role
    if model:                   # runner pool: the catalogue model this runner serves
        payload["model"] = model
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = hmac.new(_key(key), f"{VERSION}.{body}".encode(), hashlib.sha256).digest()
    return f"{VERSION}.{body}.{_b64(sig)}"


def mint_v2(account: str, tier: str, session_end: float, *, private_key: bytes, kid: str, primary_cloud: str = "",
            session_id: str = "", now: Optional[float] = None, role: str = "", model: str = "") -> str:
    """Ed25519 (v2) minting: the portal's reference (docs/architecture/v4.0/MESH-SESSION-ED25519.md) and tests.
    `private_key` is the raw 32-byte Ed25519 seed. The Mesh never holds it."""
    now = time.time() if now is None else now
    payload = {"aud": AUD, "kid": kid, "sub": account, "tier": tier, "primary_cloud": primary_cloud, "session_id": session_id,
               "iat": int(now), "session_end": int(session_end)}
    if role:
        payload["role"] = role
    if model:
        payload["model"] = model
    return sign_v2(payload, private_key=private_key, kid=kid)


def sign_v2(payload: dict, *, private_key: bytes, kid: str) -> str:
    """Ed25519-sign an arbitrary claims dict (adds "kid"). Used by mint_v2 and by core/mesh_llm.py node tokens."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    body = _b64(json.dumps({**payload, "kid": kid}, separators=(",", ":"), sort_keys=True).encode())
    sig = Ed25519PrivateKey.from_private_bytes(private_key).sign(f"{VERSION_V2}.{body}".encode())
    return f"{VERSION_V2}.{body}.{_b64(sig)}"


def _payload(body: str) -> dict:
    try:
        claims = json.loads(_unb64(body))
    except Exception:
        raise SessionError("MeshSessionMalformed", "unreadable payload")
    if not isinstance(claims, dict):
        raise SessionError("MeshSessionMalformed", "unreadable payload")
    return claims


def _verify_v1(body: str, sig: str, key: Optional[str]) -> dict:
    if not V1_ACCEPTED:
        raise SessionError("MeshSessionV1Retired", "HMAC (v1) session tokens are no longer accepted; the portal must issue a v2 token")
    want = hmac.new(_key(key), f"{VERSION}.{body}".encode(), hashlib.sha256).digest()
    try:
        got = _unb64(sig)
    except Exception:
        raise SessionError("MeshSessionBadSignature", "bad signature")
    if not hmac.compare_digest(want, got):
        raise SessionError("MeshSessionBadSignature", "bad signature")
    return _payload(body)


def _verify_v2(body: str, sig: str) -> dict:
    claims = _payload(body)                      # read first only to pick the key; nothing is trusted before the check
    pub = TRUSTED_KEYS.get(str(claims.get("kid") or ""))
    if not pub:
        raise SessionError("MeshSessionUnknownKey", "token signed with a key this mesh does not trust")
    try:   # imported here: the Ed25519 path needs `cryptography`, and nothing else in this module does
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception:
        raise SessionError("MeshSessionUnsupported", "Ed25519 verification is not available on this mesh", 503)
    try:
        Ed25519PublicKey.from_public_bytes(_unb64(pub)).verify(_unb64(sig), f"{VERSION_V2}.{body}".encode())
    except (InvalidSignature, ValueError, TypeError):
        raise SessionError("MeshSessionBadSignature", "bad signature")
    return claims


def verify(token: str, *, key: Optional[str] = None, now: Optional[float] = None) -> dict:
    """Return the claims or raise SessionError. Expired (now >= session_end) is SessionExpired (410).
    v2 (Ed25519, pinned keys) needs no key; v1 (HMAC) uses `key` or VYOMI_MESH_SESSION_KEY while V1_ACCEPTED."""
    now = time.time() if now is None else now
    try:
        ver, body, sig = (token or "").strip().split(".")
    except ValueError:
        raise SessionError("MeshSessionMalformed", "malformed session token")
    if ver == VERSION_V2:
        claims = _verify_v2(body, sig)
    elif ver == VERSION:
        claims = _verify_v1(body, sig, key)
    else:
        raise SessionError("MeshSessionMalformed", "unsupported token version")
    if claims.get("aud") != AUD:
        raise SessionError("MeshSessionBadAudience", "token is not for a mesh session")
    try:
        end = float(claims["session_end"])
        iat = float(claims.get("iat", 0))
    except Exception:
        raise SessionError("MeshSessionMalformed", "missing session_end")
    if iat > now + CLOCK_SKEW_S:
        raise SessionError("MeshSessionNotYetValid", "token issued in the future")
    if now >= end:
        raise SessionError("MeshSessionExpired", "the mesh session has ended", 410)
    if str(claims.get("tier", "")).lower() not in ("pro", "max", "enterprise"):
        raise SessionError("MeshTierNotEligible", "mesh needs a Pro or Max licence", 403)
    return claims


# ------------------------------------------------------------------ the process-wide session (monotonic expiry)
_LOCK = threading.Lock()
_SESSION: dict[str, Any] = {"end_mono": None, "pinned": ""}


def _arm_expiry(claims: dict, now: float) -> None:
    """Remember the session end on the MONOTONIC clock the first time a token verifies, so setting the wall clock back
    cannot extend the session."""
    with _LOCK:
        end_mono = time.monotonic() + max(0.0, float(claims["session_end"]) - now)
        cur = _SESSION["end_mono"]
        _SESSION["end_mono"] = end_mono if cur is None else min(cur, end_mono)


def session_ended() -> bool:
    with _LOCK:
        e = _SESSION["end_mono"]
    return e is not None and time.monotonic() >= e


def reset_for_tests() -> None:
    with _LOCK:
        _SESSION.update(end_mono=None, pinned="")


def authorise(headers: dict, path: str, provider: str, *, now: Optional[float] = None) -> Optional[SessionError]:
    """None = allowed. Otherwise the SessionError to answer with. `provider` is aws|gcp|azure|'' for the request."""
    now = time.time() if now is None else now
    if session_ended():
        return SessionError("MeshSessionExpired", "the mesh session has ended", 410)
    token = headers.get(HEADER) or os.environ.get("VYOMI_MESH_SESSION_TOKEN", "")
    if not token:
        return SessionError("MeshSessionRequired", "no session token (VYOMI_MESH_SESSION_TOKEN / X-Vyomi-Session-Token)")
    try:
        claims = verify(token, now=now)
    except SessionError as e:
        if e.code == "MeshSessionExpired":
            with _LOCK:
                _SESSION["end_mono"] = time.monotonic()      # latch: once ended, ended
        return e
    if claims.get("role"):       # runner-role tokens (remote LLM) never authorise mesh API calls
        return SessionError("MeshSessionWrongRole", "this token is for the LLM runner only", 403)
    _arm_expiry(claims, now)
    _apply_tier(claims)
    if path in _EXEMPT_PATHS or not provider:
        return None
    tier = str(claims.get("tier", "")).lower()
    if tier in ("max", "enterprise"):
        return None
    primary = str(claims.get("primary_cloud") or "")
    with _LOCK:
        if not primary:                       # Pro with no cloud chosen: first cloud used pins it for the session
            primary = _SESSION["pinned"] or provider
            _SESSION["pinned"] = primary
    if provider != primary:
        return SessionError("tier_provider_locked", f"Pro tier is locked to {primary}; {provider} needs Max", 403)
    return None


def _apply_tier(claims: dict) -> None:
    """The mesh has no licence JWT, so tier_policy (which reads the tenant / STATE licence tier) would treat it as Free and 403
    every Pro/Max service (dynamodb, eventbridge, ...). Mirror the verified session tier into the licence state (idempotent, cheap)."""
    tier = str(claims.get("tier", "")).lower()
    if not tier:
        return
    try:
        from core import app_context as ctx
        lic = ctx.STATE.setdefault("license", {})
        if lic.get("tier") != tier:
            lic["tier"] = tier
        for t in (ctx.tenants_state().get("tenants") or {}).values():
            if isinstance(t, dict) and t.get("license_tier") != tier:
                t["license_tier"] = tier
    except Exception:
        pass


def effective_tier() -> Optional[str]:
    """Mesh role only: the tier the appliance itself must run at, taken from the verified session token (the mesh has no
    licence JWT of its own - boot-mesh.sh never provides one - so without this every tier-gated route answers as Free).
    None = not a mesh / no valid token (fail closed upstream: SessionMiddleware refuses the request anyway)."""
    if not role_is_mesh():
        return None
    token = os.environ.get("VYOMI_MESH_SESSION_TOKEN", "")
    if not token:
        return None
    try:
        return str(verify(token).get("tier", "")).lower() or None
    except SessionError:
        return None


class SessionMiddleware:
    """Pure ASGI; active ONLY when VYOMI_ROLE=mesh. Outermost app middleware so nothing is served unauthenticated."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket") or not role_is_mesh():
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        path = scope.get("path", "")
        provider = ""
        try:
            from starlette.requests import Request
            from core.app_context import resolve_provider_service
            provider, _svc = resolve_provider_service(Request({**scope, "type": "http"}))
        except Exception:
            provider = ""
        if scope.get("method") == "OPTIONS" and (path == "/mesh" or path.startswith("/mesh/")):
            return await self.app(scope, receive, send)       # CORS preflight for the pairing API (no data)
        err = authorise(headers, path, provider)
        if err is None:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"error": {"ok": False, "code": err.code, "reason": err.message}}).encode()
        await send({"type": "http.response.start", "status": err.status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"x-vyomi-mesh-denied", err.code.encode())]})
        await send({"type": "http.response.body", "body": body})
