"""Shared-instance developer routes (Phase 3).

  POST /api/shared/provision   admin: create a developer's tenant + join link
  GET  /shared/join?token=…    developer: bind the vyomi_dev cookie, open console
  GET  /api/shared/whoami      developer: which tenant am I bound to?

All no-ops unless VYOMI_SHARED_INSTANCE is enabled. See core/shared_tenancy.py.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from core import shared_tenancy as sh


def register(app: FastAPI) -> None:

    @app.post("/api/shared/provision")
    def shared_provision(payload: dict, request: Request):
        """Admin: provision a developer on the shared instance → tenant + join link."""
        from core.admin_auth import require_admin_key
        require_admin_key(request)
        spec = dict(payload or {})
        name = str(spec.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        dev = sh.provision_developer(
            name, tenant_id=str(spec.get("tenant_id") or ""),
            max_spaces=int(spec.get("max_spaces", 6)),
            license_tier=str(spec.get("license_tier", "free")))
        base = str(request.base_url).rstrip("/")
        dev["join_url"] = f"{base}/shared/join?token={dev['token']}"
        dev["shared_enabled"] = sh.shared_enabled()
        dev["ok"] = True
        return dev

    @app.get("/shared/join")
    def shared_join(token: str = ""):
        """Developer: verify the join token, set the tenant cookie, open the console."""
        tid = sh.resolve_dev_token(token)
        if not tid:
            return JSONResponse(status_code=403,
                                content={"ok": False, "code": "invalid_join_token",
                                         "reason": "Invalid or expired join link."})
        resp = RedirectResponse("/", status_code=303)  # → the console SPA
        resp.set_cookie(sh.COOKIE_NAME, token, max_age=sh.COOKIE_MAX_AGE,
                        httponly=True, samesite="lax", path="/")
        return resp

    @app.post("/api/shared/offboard")
    def shared_offboard(payload: dict, request: Request):
        """Admin/control-plane: sever a shared-mode developer's access (Phase 6).
        Marks their tenant disabled so the `vyomi_dev` cookie stops resolving;
        the tenant's resources are LEFT IN PLACE for the enterprise."""
        from core.admin_auth import require_admin_key
        require_admin_key(request)
        spec = dict(payload or {})
        tid = str(spec.get("tenant_id") or "").strip()
        if not tid:
            raise HTTPException(status_code=400, detail="tenant_id required")
        result = sh.deactivate_developer(tid, reason=str(spec.get("reason") or ""))
        result["shared_enabled"] = sh.shared_enabled()
        return result

    @app.get("/api/shared/mode")
    def shared_get_mode(request: Request):
        """Current shared-instance mode + whether it's from a live override or env."""
        return sh.shared_mode_status()

    @app.post("/api/shared/mode")
    def shared_set_mode(payload: dict, request: Request):
        """Admin: toggle shared-instance mode LIVE (no restart). Body: {"enabled": true|false}
        or {"enabled": null} to clear the override and fall back to the env default.
        Takes effect on the next request — the middleware reads shared_enabled() fresh."""
        from core.admin_auth import require_admin_key
        require_admin_key(request)
        spec = dict(payload or {})
        if "enabled" not in spec:
            raise HTTPException(status_code=400, detail="enabled (true|false|null) required")
        return sh.set_shared_mode(spec.get("enabled"))

    # MVP: no quota endpoint — shared namespaces are unlimited.

    @app.get("/api/shared/usage")
    def shared_usage(request: Request):
        """Admin/control-plane: per-tenant per-service resource counts (§10.3.2,
        visibility only) for the shared-instance dashboard. Read-only — no quotas."""
        from core.admin_auth import require_admin_key
        require_admin_key(request)
        return {"ok": True, "shared_enabled": sh.shared_enabled(),
                "usage": sh.usage_by_tenant()}

    @app.get("/api/shared/whoami")
    def shared_whoami(request: Request):
        """Which tenant is this browser bound to (via the vyomi_dev cookie)?"""
        token = request.cookies.get(sh.COOKIE_NAME, "")
        # Reflect the EFFECTIVE binding: when shared mode is off the middleware
        # ignores the cookie, so whoami reports no tenant (matches enforcement).
        tid = sh.resolve_dev_token(token) if sh.shared_enabled() else None
        tenant = None
        if tid:
            try:
                from core import app_context as ctx
                tenant = ctx._tenant_dict(tid)
            except Exception:
                pass
        return {"shared_enabled": sh.shared_enabled(), "tenant_id": tid, "tenant": tenant}
