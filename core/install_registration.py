"""Phone-home registration for the appliance install.

The appliance POSTs a small "I exist" payload to the Vyomi portal on
first boot + on state transitions (license activated, etc.). This gives
us visibility into the install funnel BEFORE the user picks a tier:

  INSTALLED  → multipass + simulator are up; no license yet.
               This is what the v2.0.6 / v2.0.7 "lightweight first-run"
               UX surfaces — user can browse consoles before backends
               finish pulling, and we know about them the moment the
               simulator's /healthz turns green.

  ACTIVATED  → user has applied a license JWT (via paste-key or device
               flow) or signed up in dev mode. License backend already
               had this event via the activation POST; the registration
               state is bumped so an admin viewing the install list sees
               the same status whether they look at /api/installs or
               /api/licenses.

  ACTIVE     → reserved for "has spun up at least one workspace." Not
               surfaced in v2.0.6; the hook below understands the value
               so the state machine is forward-compatible.

  DORMANT    → set by a portal-side cron after N days of no heartbeat.
               Appliance never reports this directly.

Design constraints:
  - **Fail-soft.** A registration error must never break the appliance
    boot, the activation flow, or any console action. Network failures,
    DNS failures, 5xx from the portal, all swallowed.
  - **Idempotent.** Same install_id reported twice = portal UPSERT,
    no duplicate row. Boot can call register() unconditionally on
    every restart.
  - **Throttled.** We don't want to hit the portal on every minute of
    `docker compose restart`. The last-success timestamp is cached on
    STATE['install_registration']['last_success_at']; we skip the POST
    if we registered the SAME state less than 24h ago.

Privacy:
  - install_id is a SHA-256-derived 24-char hex string (already used by
    license_remote). No PII unless the user activates a license.
  - host_os is the raw uname/sys.platform — no hostname / IP / MAC.

The portal endpoint (POST /api/install/register) is added in a matching
commit on the `vyomi-cloud/portal` repo. Until that ships, registration
calls 404 silently (caught by the fail-soft try/except).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Optional


DEFAULT_BACKEND_URL = os.environ.get(
    "CLOUDLEARN_LICENSE_BACKEND_URL"
) or os.environ.get(
    "VYOMI_LICENSE_BACKEND_URL"
) or "https://vyomi.cloud"


# State enum
INSTALLED = "INSTALLED"
ACTIVATED = "ACTIVATED"
ACTIVE = "ACTIVE"
DORMANT = "DORMANT"

_VALID_STATES = {INSTALLED, ACTIVATED, ACTIVE, DORMANT}

# Skip re-register if we successfully reported the same state in the
# last N seconds. 24h covers normal boot cycles and `docker compose
# restart` loops during dev/upgrade.
_DEFAULT_TTL_SECONDS = 24 * 3600


def _read_version() -> str:
    """Best-effort current appliance version. Prefers /app/VERSION
    (baked into the released image), falls back to the repo's VERSION
    file (dev runs)."""
    candidates = ["/app/VERSION"]
    try:
        from pathlib import Path as _P
        candidates.append(str(_P(__file__).resolve().parent.parent / "VERSION"))
    except Exception:
        pass
    for path in candidates:
        try:
            with open(path, "r", encoding="ascii") as f:
                v = f.read().strip()
                if v:
                    return v
        except Exception:
            continue
    return "unknown"


def _host_os() -> str:
    return f"{sys.platform}"  # 'linux' / 'darwin' / 'win32'


def _should_skip(state: dict, current_state: str, ttl_seconds: int) -> bool:
    """Throttle: skip if the last successful registration was for the
    SAME state and within the TTL window. State transitions always
    re-register (e.g. INSTALLED → ACTIVATED skips the TTL check)."""
    cache = state.get("install_registration") or {}
    last_state = cache.get("last_state")
    last_at = cache.get("last_success_at")
    if last_state != current_state:
        return False  # state transition: don't skip
    if not isinstance(last_at, (int, float)):
        return False
    return (time.time() - last_at) < ttl_seconds


def register_install(
    state: dict,
    backend_url: Optional[str] = None,
    *,
    current_state: str = INSTALLED,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """POST install metadata to the portal. Fail-soft; never raises.

    Returns the response dict on success, or `{"ok": False, "error": str}`
    on failure. Caller can inspect but should NOT treat failure as
    a blocker for anything user-facing.
    """
    if current_state not in _VALID_STATES:
        return {"ok": False, "error": f"invalid state: {current_state}"}
    if _should_skip(state, current_state, ttl_seconds):
        return {"ok": True, "skipped": "cached_within_ttl"}

    # Resolve install_id — keep the existing id stable across restarts;
    # license_remote.get_or_create_install_id() seeds it on first call.
    install_id = state.get("install_id")
    if not install_id:
        try:
            from . import license_remote as _lr
            install_id = _lr.get_or_create_install_id(state)
        except Exception:
            install_id = ""
    if not install_id:
        return {"ok": False, "error": "no install_id"}

    payload: dict[str, Any] = {
        "install_id":    install_id,
        "version":       _read_version(),
        "host_os":       _host_os(),
        "state":         current_state,
        "registered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    # Carry the license JTI when we have one — lets the portal link this
    # install to a specific user / subscription without us shipping
    # email / sub. JTI alone is opaque; the portal already knows the
    # mapping JTI → user from the JWT-issuance flow.
    lic = state.get("license_claims") or {}
    if isinstance(lic, dict) and lic.get("jti"):
        payload["license_jti"] = lic.get("jti")
        payload["license_tier"] = lic.get("tier")
    if extra and isinstance(extra, dict):
        # Merge caller-supplied fields (e.g. seats, workspace_count for
        # the ACTIVE bump). Never let `extra` clobber the canonical
        # install_id / state / version.
        for k, v in extra.items():
            if k not in payload:
                payload[k] = v

    url = (backend_url or DEFAULT_BACKEND_URL).rstrip("/") + "/api/install/register"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": f"vyomi-appliance/{payload['version']}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            try:
                response = json.loads(resp.read().decode("utf-8"))
            except Exception:
                response = {"ok": True, "status": resp.status}
        # Cache last-success so we throttle subsequent calls.
        cache = state.setdefault("install_registration", {})
        cache["last_state"]      = current_state
        cache["last_success_at"] = time.time()
        cache["last_response"]   = response if isinstance(response, dict) else {}
        return {"ok": True, **(response if isinstance(response, dict) else {})}
    except urllib.error.HTTPError as e:
        # 404 likely means the portal hasn't shipped the endpoint yet.
        # Note this in cache but don't keep retrying every minute.
        cache = state.setdefault("install_registration", {})
        cache["last_state"]     = current_state
        cache["last_error_at"]  = time.time()
        cache["last_error_status"] = e.code
        return {"ok": False, "error": f"http {e.code}", "skipped_until_next_state": True}
    except (urllib.error.URLError, OSError, ValueError) as e:
        cache = state.setdefault("install_registration", {})
        cache["last_state"]    = current_state
        cache["last_error_at"] = time.time()
        cache["last_error"]    = str(e)[:120]
        return {"ok": False, "error": str(e)}


def maybe_register_at_boot(state: dict, backend_url: Optional[str] = None) -> dict[str, Any]:
    """Convenience wrapper for the FastAPI startup hook. Picks
    INSTALLED vs ACTIVATED based on whether a license is currently
    applied, so the hook is correct on both first-ever boot AND on
    every subsequent restart of an already-activated appliance.

    Heuristic: anything tier != "free" counts as ACTIVATED. We check
    the tier instead of the `active` boolean because dev-mode signup
    (POST /api/license/signup) writes the payload directly into
    STATE["license"] without setting `active`, whereas the
    portal-activation path (`_apply_license_jwt`) does set it. Tier
    is the lowest-common-denominator field across both.
    """
    lic = state.get("license") or {}
    tier = str(lic.get("tier") or "free").strip().lower()
    s = ACTIVATED if tier and tier != "free" else INSTALLED
    return register_install(state, backend_url, current_state=s)
