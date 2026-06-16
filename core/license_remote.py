"""Phase 1 license-key implementation for the CloudLearn appliance.

Validates JWTs issued by the cloudlearn-license-backend (hosted SaaS) and
exposes a device-authorization client so users can log in without copy-
pasting keys.

Verification reuses the RS256/ES256 path from core/sso_config.py to avoid
duplicating crypto code. The license backend's signing key is fetched from
its JWKS endpoint at boot (cached) — OR baked into the appliance image as
core/license_pubkey.pem for air-gapped deployments.

Wire-up:
  - server.py imports verify_license_jwt, device_flow_start, device_flow_poll
  - STATE["license_jwt"]      — the cached active JWT string
  - STATE["license_claims"]   — parsed claims (cached for fast access)
  - STATE["license_revoked_jtis"] — set of revoked JTIs (polled daily)
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional


# Default backend URL — override via env in production
# Was https://license.cloudlearn.io (a placeholder host that never had DNS).
# The live portal lives at https://vyomi.cloud and serves /api/oauth/device,
# /api/license/revocation, and /.well-known/jwks.json. Users hit the old
# default and got `portal_unreachable: URLError: Name or service not known`.
DEFAULT_BACKEND_URL = os.environ.get(
    "CLOUDLEARN_LICENSE_BACKEND_URL",
    "https://vyomi.cloud",
)

# Local pubkey fallback (air-gapped). If present, used WITHOUT fetching JWKS.
LOCAL_PUBKEY_FILE = Path(__file__).parent / "license_pubkey.pem"

EXPECTED_AUDIENCE = "cloudlearn-simulator"

# Cached JWKS — fetched once, refreshed when signature verify fails
_jwks_cache: dict = {"keys": [], "fetched_at": 0.0, "backend_url": ""}
_JWKS_TTL_SECONDS = 6 * 3600  # 6h


# ── JWKS fetch + caching ────────────────────────────────────────────────────

def _fetch_jwks(backend_url: str) -> dict:
    """Fetch /.well-known/jwks.json from the license backend. Cached."""
    now = time.time()
    if (_jwks_cache["keys"]
            and _jwks_cache["backend_url"] == backend_url
            and now - _jwks_cache["fetched_at"] < _JWKS_TTL_SECONDS):
        return _jwks_cache
    try:
        with urllib.request.urlopen(f"{backend_url}/.well-known/jwks.json", timeout=5) as r:
            data = json.load(r)
        _jwks_cache.update({"keys": data.get("keys") or [], "fetched_at": now, "backend_url": backend_url})
    except Exception:
        # Network failure — keep stale cache or fall back to local pubkey
        pass
    return _jwks_cache


def _load_local_pubkey_as_jwks() -> dict | None:
    """If LOCAL_PUBKEY_FILE exists, convert it to a single-entry JWKS dict.
    Returns None if the file is absent (force fetch from network)."""
    if not LOCAL_PUBKEY_FILE.exists():
        return None
    try:
        from cryptography.hazmat.primitives import serialization
        import base64, hashlib
        pub = serialization.load_pem_public_key(LOCAL_PUBKEY_FILE.read_bytes())
        nums = pub.public_numbers()
        n_bytes = nums.n.to_bytes((nums.n.bit_length() + 7) // 8, "big")
        e_bytes = nums.e.to_bytes((nums.e.bit_length() + 7) // 8, "big")
        b64 = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")
        kid = b64(hashlib.sha256(LOCAL_PUBKEY_FILE.read_bytes()).digest())[:16]
        return {"keys": [{
            "kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
            "n": b64(n_bytes), "e": b64(e_bytes),
        }]}
    except Exception:
        return None


# ── JWT verification — reuses crypto from sso_config.py ─────────────────────

def verify_license_jwt(
    token: str,
    *,
    backend_url: Optional[str] = None,
    expected_audience: str = EXPECTED_AUDIENCE,
    install_id: Optional[str] = None,
) -> dict:
    """Verify a license JWT against the configured public key.

    Returns parsed claims on success. Raises ValueError with a short reason
    on failure (caller maps to 400/401).
    """
    from core import sso_config  # reuse _verify_signature + b64 helpers
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise ValueError("malformed_jwt")
    try:
        header = json.loads(sso_config._b64url_decode(parts[0]))
        claims = json.loads(sso_config._b64url_decode(parts[1]))
        signature = sso_config._b64url_decode(parts[2])
    except Exception as e:
        raise ValueError(f"decode_failed: {e}")

    # Pick a JWKS source — NETWORK FIRST, local fallback for air-gap.
    #
    # The previous order (local-first) was a landmine: an appliance image
    # built against a dev backend would ship with a pubkey that doesn't
    # match the live portal's signing key. verify_license_jwt would then
    # raise signature_invalid 401 on every real activation — and because
    # the portal nulls `issued_jwt` after one read, the JWT was lost
    # forever. User-visible symptom: modal stuck on "Waiting…" with no
    # way to recover.
    #
    # Network-first means an online appliance always picks up the current
    # portal key, even if a stale baked key is sitting on disk. The local
    # fallback still keeps air-gap installs working.
    jwks = _fetch_jwks(backend_url or DEFAULT_BACKEND_URL)
    if not jwks.get("keys"):
        jwks = _load_local_pubkey_as_jwks() or {"keys": []}
    if not jwks.get("keys"):
        raise ValueError("no_signing_keys_available")

    signing_input = (parts[0] + "." + parts[1]).encode("ascii")
    if not sso_config._verify_signature(header, signing_input, signature, jwks):
        raise ValueError("signature_invalid")

    now = time.time()
    if int(claims.get("exp") or 0) < now - 30:
        raise ValueError("token_expired")
    if int(claims.get("nbf") or 0) > now + 30:
        raise ValueError("token_not_yet_valid")

    aud = claims.get("aud") or ""
    if isinstance(aud, list):
        if expected_audience not in aud:
            raise ValueError(f"audience_mismatch (got {aud!r})")
    elif aud != expected_audience:
        raise ValueError(f"audience_mismatch (got {aud!r})")

    if install_id and claims.get("install_id") and claims["install_id"] != install_id:
        raise ValueError(f"install_id_mismatch (claim={claims['install_id']!r}, this={install_id!r})")

    # Accept both new canonical names (Pro/Max) and legacy names (Student/
    # Developer) so JWTs minted before the 2026-06-17 rename still validate.
    # The tier_policy.normalize_tier() at the consumption boundary maps
    # the legacy names to canonical ones — see core/tier_policy.py.
    if claims.get("tier") not in ("free", "pro", "max", "enterprise",
                                  "student", "developer"):
        raise ValueError(f"invalid_tier_claim ({claims.get('tier')!r})")

    # Subscription-level hard expiry. Independent of JWT exp — the JWT could
    # be cryptographically valid for hours after the paid period ended.
    # `sub_expires_at` is the billing cutoff baked into the JWT at mint time.
    # When it passes, the appliance must self-downgrade to Free even without
    # network reachability to the portal. This is what makes appliance
    # entitlement actually coupled to the subscription period.
    sub_exp = claims.get("sub_expires_at")
    if sub_exp:
        try:
            # tolerate trailing 'Z' or '+00:00'
            iso = sub_exp.rstrip("Z").split("+")[0].split(".")[0]
            sub_exp_ts = time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%S"))
            # Use timegm semantics — strptime gives local-tz naive; convert
            # via calendar.timegm for true UTC.
            import calendar
            sub_exp_ts = calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%S"))
            if sub_exp_ts < now - 30:
                raise ValueError(f"subscription_expired (sub_expires_at={sub_exp})")
        except ValueError:
            raise
        except Exception:
            # malformed claim value — refuse rather than ignore
            raise ValueError(f"invalid_sub_expires_at_claim ({sub_exp!r})")

    return claims


# ── Device authorization flow client (RFC 8628) ─────────────────────────────

def device_flow_start(backend_url: Optional[str], install_id: str,
                      client_name: str = "CloudLearn Appliance") -> dict:
    """Step 1 — POST to backend /api/oauth/device. Returns the device_code
    + user_code + verification_uri for the SPA to display."""
    url = (backend_url or DEFAULT_BACKEND_URL).rstrip("/") + "/api/oauth/device"
    data = json.dumps({"install_id": install_id, "client_name": client_name}).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"device_start failed HTTP {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        raise RuntimeError(f"device_start failed: {type(e).__name__}: {e}")


def device_flow_poll(backend_url: Optional[str], device_code: str) -> dict:
    """Step 4 — POST grant_type=device_code, polling until approved.
    Returns:
      {"status":"pending"}     while user hasn't approved
      {"status":"expired"}     if code expired
      {"status":"approved", "access_token": <JWT>, ...}  on success
    """
    url = (backend_url or DEFAULT_BACKEND_URL).rstrip("/") + "/api/oauth/token"
    form = f"grant_type=device_code&device_code={device_code}".encode()
    req = urllib.request.Request(url, data=form, method="POST",
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.load(r)
            return {"status": "approved", **body}
    except urllib.error.HTTPError as e:
        # The backend returns 400 + JSON {"error": "authorization_pending"|"expired_token"|...}
        try:
            data = json.loads(e.read())
            detail = data.get("detail") if isinstance(data.get("detail"), dict) else data
            err = detail.get("error") if isinstance(detail, dict) else str(detail)
        except Exception:
            err = f"http_{e.code}"
        if err == "authorization_pending":
            return {"status": "pending"}
        if err in ("expired_token", "expired"):
            return {"status": "expired"}
        return {"status": "error", "error": err}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


# ── Revocation list polling ─────────────────────────────────────────────────

def fetch_revocation_list(backend_url: Optional[str]) -> list[str]:
    """GET /api/license/revocation → list of revoked JTIs.
    Best-effort — returns [] on network failure."""
    url = (backend_url or DEFAULT_BACKEND_URL).rstrip("/") + "/api/license/revocation"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.load(r)
            return list(data.get("revoked_jtis") or [])
    except Exception:
        return []


# ── Background poll (daemon thread) ─────────────────────────────────────────

_POLL_THREAD: Optional["threading.Thread"] = None


def start_revocation_poll(state: dict, *, interval_seconds: int = 24 * 3600,
                         on_revoked=None) -> None:
    """Spawn a daemon thread that polls the backend's revocation list every
    `interval_seconds` (default 24h). If the currently-active JWT's jti
    appears in the list, calls `on_revoked(claims)` so the caller can
    auto-downgrade the tier.

    Safe to call repeatedly — only spawns one thread per process. No-op on
    subsequent calls if a thread is already running."""
    global _POLL_THREAD
    import threading
    if _POLL_THREAD and _POLL_THREAD.is_alive():
        return

    def _loop():
        # First poll happens immediately at startup (catches revocations
        # that happened while the appliance was offline)
        while True:
            try:
                _poll_once(state, on_revoked)
            except Exception:
                pass  # never crash the daemon
            time.sleep(interval_seconds)

    _POLL_THREAD = threading.Thread(target=_loop, name="license-revocation-poll", daemon=True)
    _POLL_THREAD.start()


def _poll_once(state: dict, on_revoked) -> None:
    claims = state.get("license_claims") or {}
    if not claims:
        return  # no license active → nothing to check
    jti = claims.get("jti")
    if not jti:
        return
    backend_url = os.environ.get("CLOUDLEARN_LICENSE_BACKEND_URL")
    revoked = set(fetch_revocation_list(backend_url))
    state["license_revoked_jtis"] = sorted(revoked)
    state["license_last_revocation_check_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if jti in revoked and on_revoked:
        on_revoked(claims)


# ── Identity-first refresh — Phase 4 ────────────────────────────────────────

_REFRESH_THREAD: Optional["threading.Thread"] = None


def refresh_token(state: dict, *, backend_url: Optional[str] = None,
                  ttl_hours: int = 24) -> dict | None:
    """Hit POST /api/identity/refresh on the portal with our current JWT.
    Backend re-derives tier from CURRENT subscription state → mints fresh
    JWT (different JTI, possibly different tier if user upgraded/cancelled).

    Returns the new claims dict on success (caller is expected to apply
    them). Returns None on auth failure (caller should prompt re-login)
    or network error (caller keeps existing JWT for now).
    """
    token = state.get("license_jwt", "")
    if not token:
        return None
    url = (backend_url or DEFAULT_BACKEND_URL).rstrip("/") + "/api/identity/refresh"
    body = json.dumps({"install_id": state.get("install_id"), "ttl_hours": ttl_hours}).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        # 401 → JWT no longer valid (revoked or expired); caller handles
        state["license_last_refresh_attempted_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if e.code == 401:
            state["license_last_refresh_status"] = "auth_required"
            return {"_error": "auth_required",
                    "_status": 401,
                    "_detail": e.read().decode()[:200]}
        state["license_last_refresh_status"] = f"http_{e.code}"
        return None
    except Exception as ex:
        state["license_last_refresh_attempted_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state["license_last_refresh_status"] = f"network_error: {type(ex).__name__}"
        return None  # network — keep cached JWT, try again later
    new_jwt = data.get("access_token", "")
    if not new_jwt:
        state["license_last_refresh_attempted_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state["license_last_refresh_status"] = "empty_token"
        return None
    # Verify the new JWT signature locally before applying (defense in depth)
    try:
        claims = verify_license_jwt(new_jwt, backend_url=backend_url)
    except ValueError as ve:
        state["license_last_refresh_attempted_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state["license_last_refresh_status"] = f"verify_failed: {ve}"
        return None  # backend returned something we can't verify — keep cached
    state["license_jwt"] = new_jwt
    state["license_claims"] = dict(claims)
    state["license_last_refresh_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state["license_last_refresh_attempted_at"] = state["license_last_refresh_at"]
    state["license_last_refresh_status"] = "ok"
    state["license_refresh_source"] = data.get("source")
    return claims


def start_refresh_loop(state: dict, *, interval_seconds: int = 24 * 3600,
                       on_tier_changed=None, on_auth_failed=None) -> None:
    """Background daemon that refreshes the license JWT every
    `interval_seconds` (default 24h) while the appliance is online.

    24h cadence: matches the JWT TTL — the JWT is essentially a 1-day
    cache of "the portal said you're Student". Smaller intervals add
    network traffic without improving enforcement (the JWT's
    sub_expires_at claim is the real hard expiry, not the refresh
    cadence). Failed refreshes are surfaced via STATE['license_last_*']
    fields so the SPA pill can flip from green to yellow.

    Subscription changes on the portal propagate to the appliance within
    `interval_seconds`. On revoked/expired auth: calls `on_auth_failed()`
    so the SPA can prompt the user to re-sign-in.
    """
    global _REFRESH_THREAD
    import threading
    if _REFRESH_THREAD and _REFRESH_THREAD.is_alive():
        return

    def _loop():
        # First refresh: 30s after boot (gives the startup sequence room)
        time.sleep(30)
        while True:
            try:
                prev_tier = (state.get("license_claims") or {}).get("tier")
                result = refresh_token(state)
                if result and result.get("_error") == "auth_required":
                    if on_auth_failed:
                        on_auth_failed(result.get("_detail", ""))
                elif result and isinstance(result, dict):
                    new_tier = result.get("tier")
                    if new_tier and new_tier != prev_tier and on_tier_changed:
                        on_tier_changed(prev_tier, new_tier, result)
            except Exception:
                pass
            time.sleep(interval_seconds)

    _REFRESH_THREAD = threading.Thread(target=_loop, name="license-refresh-loop", daemon=True)
    _REFRESH_THREAD.start()


# ── Tier extraction (what callers actually want) ────────────────────────────

def claims_to_tier_payload(claims: dict) -> dict:
    """Map JWT claims → the same shape `/api/license/signup` produces, so
    the caller can drop it into STATE["license"] without translation."""
    return {
        "tier": claims.get("tier"),
        "seats": int(claims.get("seats") or 1),
        "primary_cloud": claims.get("primary_cloud") or "",
        "period": "issued-by-license-backend",
        "expires_at": _exp_iso(claims),
        "jti": claims.get("jti"),
        "sub": claims.get("sub"),
        "iss": claims.get("iss"),
        "install_id": claims.get("install_id"),
        "sub_expires_at": claims.get("sub_expires_at"),
        "cancel_at_period_end": bool(claims.get("cancel_at_period_end")),
        "issued_via": "license_remote_jwt",
    }


def is_sub_expired(claims: dict, now_ts: Optional[float] = None) -> bool:
    """True iff the subscription cutoff baked into the JWT has passed.

    Cheap one-claim check used at runtime by the appliance — every tier
    read goes through this so an expired sub immediately reads as Free,
    even before the next refresh cycle fires.
    """
    if not claims:
        return False
    sub_exp = claims.get("sub_expires_at")
    if not sub_exp:
        return False
    try:
        import calendar
        iso = sub_exp.rstrip("Z").split("+")[0].split(".")[0]
        sub_exp_ts = calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return False
    return (now_ts or time.time()) > sub_exp_ts


def days_until_sub_expiry(claims: dict, now_ts: Optional[float] = None) -> Optional[int]:
    """Whole days remaining until sub_expires_at, or None if no claim. Used
    by the SPA pill to show '✓ STUDENT · 23 days left'."""
    if not claims:
        return None
    sub_exp = claims.get("sub_expires_at")
    if not sub_exp:
        return None
    try:
        import calendar
        iso = sub_exp.rstrip("Z").split("+")[0].split(".")[0]
        sub_exp_ts = calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return None
    delta = sub_exp_ts - (now_ts or time.time())
    return max(0, int(delta // 86400))


def _exp_iso(claims: dict) -> str:
    exp = int(claims.get("exp") or 0)
    if not exp:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp))


# ── Install ID generator (stable, per-machine) ──────────────────────────────

def get_or_create_install_id(state: dict) -> str:
    """Hardware-bound install identifier. Deterministic per container+volume."""
    existing = state.get("install_id")
    if existing:
        return str(existing)

    import hashlib, socket, os
    # Collect hardware-bound inputs
    components = []
    # 1. Container hostname (unique per container instance)
    components.append(socket.gethostname())
    # 2. Volume identity (inode of data directory)
    try:
        data_dir = os.environ.get("CLOUDLEARN_STATE_DIR", "/data")
        stat = os.stat(data_dir)
        components.append(f"vol:{stat.st_dev}:{stat.st_ino}")
    except Exception:
        components.append("vol:local")
    # 3. MAC address of primary interface
    try:
        import uuid as _uuid
        components.append(f"mac:{_uuid.getnode()}")
    except Exception:
        pass

    # Derive deterministic ID
    raw = "|".join(components).encode()
    install_id = hashlib.sha256(raw).hexdigest()[:24]
    state["install_id"] = install_id
    return install_id
