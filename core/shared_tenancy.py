"""Shared-instance multi-tenancy (Phase 3 of the Cloud Sandbox).

Binds each developer to a tenant via a signed cookie, so ONE running simulator
serves N developers with isolated resources. Reuses the existing tenant model
(`core.app_context` tenants/spaces) + the per-request `X-CloudLearn-Tenant`
routing already in `core.middleware.tenant_context_middleware`.

The mechanism, end to end:
  1. Admin provisions a developer  → a tenant is created + a signed join token.
  2. Developer opens `/shared/join?token=…` → the token is verified, a
     `vyomi_dev` cookie is set, they're redirected to the console.
  3. Every console API request carries that cookie → the tenant middleware
     resolves it to the developer's tenant → resources are isolated.
     (No SPA rewrite needed: the cookie rides along automatically.)

SAFETY: entirely OFF unless `VYOMI_SHARED_INSTANCE` is truthy. When off, none of
this runs and the appliance behaves exactly as before (single active tenant).
Tokens are HMAC-signed with `CLOUDLEARN_LICENSE_SECRET` (stdlib only — the
appliance has no itsdangerous).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
import uuid
from typing import Optional

COOKIE_NAME = "vyomi_dev"
COOKIE_MAX_AGE = 12 * 3600  # matches a typical session TTL


# Runtime override key in STATE — lets an admin toggle shared mode LIVE (no
# container restart). When set it WINS over the VYOMI_SHARED_INSTANCE env var;
# it persists across restarts (via _persist_state).
_STATE_KEY = "shared_instance"


def _env_shared() -> bool:
    return os.environ.get("VYOMI_SHARED_INSTANCE", "").strip().lower() in ("1", "true", "yes", "on")


def _shared_override():
    """The runtime override (True/False) if an admin has set one, else None."""
    try:
        from core import app_context as ctx
        cfg = ctx.STATE.get(_STATE_KEY)
        if isinstance(cfg, dict) and "enabled" in cfg:
            return bool(cfg["enabled"])
    except Exception:
        pass
    return None


def shared_enabled() -> bool:
    """Is shared-instance mode on? Runtime STATE override (set via /api/shared/mode)
    wins; otherwise the VYOMI_SHARED_INSTANCE env default. Read fresh every call →
    a toggle takes effect on the very next request, no restart."""
    override = _shared_override()
    return override if override is not None else _env_shared()


def set_shared_mode(enabled) -> dict:
    """Admin: toggle shared mode LIVE. enabled=None clears the override → falls back
    to the env default."""
    from core import app_context as ctx
    if enabled is None:
        ctx.STATE.pop(_STATE_KEY, None)
    else:
        ctx.STATE[_STATE_KEY] = {"enabled": bool(enabled),
                                 "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())}
    try:
        ctx._persist_state()
    except Exception:
        pass
    return shared_mode_status()


def shared_mode_status() -> dict:
    ov = _shared_override()
    return {"enabled": shared_enabled(), "override": ov, "env_default": _env_shared(),
            "source": "state_override" if ov is not None else "env"}


def _secret() -> bytes:
    return os.environ.get("CLOUDLEARN_LICENSE_SECRET", "cloudlearn-dev-secret").encode("utf-8")


def _sign(msg: str) -> str:
    return hmac.new(_secret(), msg.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def mint_dev_token(tenant_id: str) -> str:
    """Signed token binding a developer session to a tenant: `<tenant>.<sig>`."""
    return f"{tenant_id}.{_sign(tenant_id)}"


def resolve_dev_token(token: str) -> Optional[str]:
    """Return the tenant_id iff the token signature is valid, else None."""
    if not token or "." not in token:
        return None
    tid, sig = token.rsplit(".", 1)
    if tid and hmac.compare_digest(sig, _sign(tid)):
        return tid
    return None


# MVP: shared namespaces are UNLIMITED — no per-tenant space cap.
_UNLIMITED_SPACES = 9999


def provision_developer(name: str, *, tenant_id: str = "",
                        max_spaces: int = _UNLIMITED_SPACES,
                        license_tier: str = "free") -> dict:
    """Create a tenant for a developer (idempotent) + return its join token.
    Mirrors routes/tenants.api_create_tenant's tenant shape so the rest of the
    appliance treats it identically. MVP: unlimited spaces (no cap)."""
    from core import app_context as ctx
    ts = ctx._tenants_state()
    tenants = ts.setdefault("tenants", {})
    tid = (tenant_id or re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
           or uuid.uuid4().hex[:12])
    if tid not in tenants:
        tenants[tid] = {
            "tenant_id": tid, "name": name, "license_tier": license_tier,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "settings": {"max_spaces": int(max_spaces)},   # MVP: unlimited
        }
        try:
            ctx._persist_state()
        except Exception:
            pass
        try:
            from core import security_audit
            security_audit.append_event("shared.developer_provisioned",
                                        {"tenant_id": tid, "name": name})
        except Exception:
            pass
    return {"tenant_id": tid, "name": tenants[tid].get("name", name),
            "token": mint_dev_token(tid)}


def usage_by_tenant() -> dict:
    """Per-tenant, per-service resource counts (visibility only — §10.3.2). Walks
    every space's service_states and counts each resource collection, grouped by
    the space's tenant. Read-only; touches no resources."""
    from core import app_context as ctx
    out: dict = {}
    spaces = (ctx.STATE.get("spaces", {}) or {}).get("spaces", {}) or {}
    for _sid, sp in spaces.items():
        if not isinstance(sp, dict):
            continue
        tid = sp.get("tenant_id") or ctx.DEFAULT_TENANT_ID
        svc_states = sp.get("service_states", {}) or {}
        tenant = out.setdefault(tid, {})
        for skey, sstate in svc_states.items():
            if not isinstance(sstate, dict):
                continue
            for rk, rv in sstate.items():
                # a resource collection = a non-empty dict/list under the service
                if isinstance(rv, (dict, list)) and len(rv):
                    svc = tenant.setdefault(skey, {})
                    svc[rk] = svc.get(rk, 0) + len(rv)
    return out


# MVP scope: shared namespaces are UNCONDITIONAL / UNFILTERED / UNLIMITED — no
# per-tenant resource quotas or limits. (`usage_by_tenant` above stays for
# read-only visibility; quota enforcement + set/get_quota were intentionally
# removed for the MVP and can be reintroduced later behind an explicit flag.)


def is_disabled(tenant_id: str) -> bool:
    """True if the tenant has been offboarded (access severed). Resources remain
    in STATE keyed by this tenant; only NEW access via the cookie is refused."""
    if not tenant_id:
        return False
    from core import app_context as ctx
    t = ctx._tenants_state().get("tenants", {}).get(tenant_id)
    return bool(isinstance(t, dict) and t.get("disabled"))


def deactivate_developer(tenant_id: str, *, reason: str = "") -> dict:
    """Offboard a shared-mode developer: mark their tenant disabled so the
    `vyomi_dev` cookie stops resolving (see middleware). The tenant's spaces and
    resources are LEFT IN PLACE — they belong to the enterprise now. Idempotent."""
    from core import app_context as ctx
    tenants = ctx._tenants_state().get("tenants", {})
    t = tenants.get(tenant_id)
    if not isinstance(t, dict):
        return {"ok": False, "reason": "unknown_tenant", "tenant_id": tenant_id}
    already = bool(t.get("disabled"))
    t["disabled"] = True
    # Preserve the ORIGINAL offboard reason/timestamp on repeat calls (idempotent).
    if not already:
        t["disabled_reason"] = reason or "offboarded"
        t["disabled_at"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    try:
        ctx._persist_state()
    except Exception:
        pass
    try:
        from core import security_audit
        security_audit.append_event("shared.developer_offboarded",
                                    {"tenant_id": tenant_id, "reason": reason})
    except Exception:
        pass
    return {"ok": True, "tenant_id": tenant_id, "already_disabled": already}
