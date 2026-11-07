"""Booster SESSION token + server-side enforcement (headless booster role, VYOMI_ROLE=booster).

The portal mints a short-lived signed *session token* for each booster session (design s6.3/s6.4). It carries the facts the
booster must not take from the client: tier, primary_cloud (Pro), account, session_id and `session_end` (epoch seconds).
The booster verifies it OFFLINE with a shared key (env VYOMI_BOOSTER_SESSION_KEY) and:

  * refuses every request once `session_end` has passed (the headless booster self-expires its API too);
  * Pro: serves ONE cloud only (token.primary_cloud, or the first cloud used when the token leaves it empty);
    Max: all clouds; anything else: refused;
  * fails closed: in the booster role, no key / no token / bad signature = nothing is served (except /healthz while valid,
    so the boot script's readiness probe works once a token is configured).

Token wire format (also verified by wasm/relay/booster-session.mjs, same HMAC):
    v1.<b64url(payload-json)>.<b64url(HMAC-SHA256(key, "v1." + b64url(payload-json)))>

This is a shared-key HMAC (portal and booster both hold the key). An asymmetric signature (Ed25519 public key on the
booster) would be stronger because a compromised Codespace could then not mint tokens - noted as a follow-up.
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

AUD = "vyomi-booster-session"
VERSION = "v1"
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


def role_is_booster() -> bool:
    return (os.environ.get("VYOMI_ROLE") or "").strip().lower() == "booster"


def _key(key: Optional[str] = None) -> bytes:
    k = key if key is not None else os.environ.get("VYOMI_BOOSTER_SESSION_KEY", "")
    if not k:
        raise SessionError("BoosterSessionKeyMissing", "VYOMI_BOOSTER_SESSION_KEY is not set on this booster", 503)
    return k.encode()


def mint(account: str, tier: str, session_end: float, *, primary_cloud: str = "", session_id: str = "",
         key: Optional[str] = None, now: Optional[float] = None, role: str = "") -> str:
    """Portal-side minting (also used by tests). `session_end` is epoch seconds."""
    now = time.time() if now is None else now
    payload = {"aud": AUD, "sub": account, "tier": tier, "primary_cloud": primary_cloud, "session_id": session_id,
               "iat": int(now), "session_end": int(session_end)}
    if role:                    # e.g. "llm-runner": a token that may ONLY dial the LLM plane of the relay (never drive a booster)
        payload["role"] = role
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = hmac.new(_key(key), f"{VERSION}.{body}".encode(), hashlib.sha256).digest()
    return f"{VERSION}.{body}.{_b64(sig)}"


def verify(token: str, *, key: Optional[str] = None, now: Optional[float] = None) -> dict:
    """Return the claims or raise SessionError. Expired (now >= session_end) is SessionExpired (410)."""
    now = time.time() if now is None else now
    try:
        ver, body, sig = (token or "").strip().split(".")
    except ValueError:
        raise SessionError("BoosterSessionMalformed", "malformed session token")
    if ver != VERSION:
        raise SessionError("BoosterSessionMalformed", "unsupported token version")
    want = hmac.new(_key(key), f"{ver}.{body}".encode(), hashlib.sha256).digest()
    try:
        got = _unb64(sig)
    except Exception:
        raise SessionError("BoosterSessionBadSignature", "bad signature")
    if not hmac.compare_digest(want, got):
        raise SessionError("BoosterSessionBadSignature", "bad signature")
    try:
        claims = json.loads(_unb64(body))
    except Exception:
        raise SessionError("BoosterSessionMalformed", "unreadable payload")
    if claims.get("aud") != AUD:
        raise SessionError("BoosterSessionBadAudience", "token is not for a booster session")
    try:
        end = float(claims["session_end"])
        iat = float(claims.get("iat", 0))
    except Exception:
        raise SessionError("BoosterSessionMalformed", "missing session_end")
    if iat > now + CLOCK_SKEW_S:
        raise SessionError("BoosterSessionNotYetValid", "token issued in the future")
    if now >= end:
        raise SessionError("BoosterSessionExpired", "the booster session has ended", 410)
    if str(claims.get("tier", "")).lower() not in ("pro", "max", "enterprise"):
        raise SessionError("BoosterTierNotEligible", "booster needs a Pro or Max licence", 403)
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
        return SessionError("BoosterSessionExpired", "the booster session has ended", 410)
    token = headers.get(HEADER) or os.environ.get("VYOMI_BOOSTER_SESSION_TOKEN", "")
    if not token:
        return SessionError("BoosterSessionRequired", "no session token (VYOMI_BOOSTER_SESSION_TOKEN / X-Vyomi-Session-Token)")
    try:
        claims = verify(token, now=now)
    except SessionError as e:
        if e.code == "BoosterSessionExpired":
            with _LOCK:
                _SESSION["end_mono"] = time.monotonic()      # latch: once ended, ended
        return e
    if claims.get("role"):       # runner-role tokens (remote LLM) never authorise booster API calls
        return SessionError("BoosterSessionWrongRole", "this token is for the LLM runner only", 403)
    _arm_expiry(claims, now)
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


class SessionMiddleware:
    """Pure ASGI; active ONLY when VYOMI_ROLE=booster. Outermost app middleware so nothing is served unauthenticated."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket") or not role_is_booster():
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
        if scope.get("method") == "OPTIONS" and (path == "/booster" or path.startswith("/booster/")):
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
                                (b"x-vyomi-booster-denied", err.code.encode())]})
        await send({"type": "http.response.body", "body": body})
