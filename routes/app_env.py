"""HTTP routes for app profile runtime and environment resolution.

Part of the app profile runtime (§4, §6, AE1, AE3, AE4).
Exposes:
  - GET  /api/runtime/endpoints (unauthenticated)
  - POST /api/runtime/apps/{name}/provision (admin key required)
  - POST /api/runtime/apps/{name}/resolve   (admin key required)
"""
from __future__ import annotations

import logging
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import JSONResponse
except ImportError:  # pragma: no cover — host conformance / Pyodide fallback
    FastAPI = Any  # type: ignore
    Request = Any  # type: ignore

    class HTTPException(Exception):  # type: ignore
        def __init__(self, status_code: int, detail: Any = None):
            self.status_code = status_code
            self.detail = detail

    class JSONResponse:  # type: ignore
        def __init__(self, content: Any = None, status_code: int = 200):
            self.content = content
            self.status_code = status_code

from core import admin_auth, app_provision

log = logging.getLogger("vyomi.routes.app_env")


def register(app: FastAPI) -> None:
    @app.get("/api/runtime/endpoints", include_in_schema=False)
    def api_runtime_endpoints() -> dict[str, Any]:
        """Discover running and network endpoints for backends (unauthenticated)."""
        try:
            return app_provision.discover_endpoints()
        except Exception as exc:
            log.warning("Endpoint discovery failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/runtime/apps/{name}/provision", include_in_schema=False)
    async def api_app_provision(name: str, request: Request) -> JSONResponse:
        """Create app resources (Postgres, Blob, Redis, Service Bus). Requires admin key."""
        # Enforce admin key in every mode (appliance and developer)
        if not admin_auth.verify_admin_key(request):
            return JSONResponse(
                status_code=403,
                content={
                    "ok": False,
                    "code": "admin_key_required",
                    "reason": "This endpoint requires the X-CloudLearn-Admin-Key header in every mode.",
                },
            )

        try:
            body = await request.json()
        except Exception:
            body = {}

        # Accept either { "resources": {...} } or bare {...}
        resources = body.get("resources", body) if isinstance(body, dict) else {}

        try:
            result = app_provision.provision_app_resources(name, resources)
            return JSONResponse(status_code=200, content=result)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
        except Exception as exc:
            log.exception("Unexpected error provisioning app %s: %s", name, exc)
            return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})

    @app.post("/api/runtime/apps/{name}/resolve", include_in_schema=False)
    async def api_app_resolve(name: str, request: Request) -> JSONResponse:
        """Resolve ${...} output expressions for an app profile. Requires admin key."""
        # Enforce admin key in every mode
        if not admin_auth.verify_admin_key(request):
            return JSONResponse(
                status_code=403,
                content={
                    "ok": False,
                    "code": "admin_key_required",
                    "reason": "This endpoint requires the X-CloudLearn-Admin-Key header in every mode.",
                },
            )

        try:
            body = await request.json()
        except Exception:
            body = {}

        outputs = body.get("outputs", {}) if isinstance(body, dict) else {}
        target = body.get("target", "host") if isinstance(body, dict) else "host"

        try:
            result = app_provision.resolve_app_outputs(name, outputs, target=target)
            return JSONResponse(status_code=200, content=result)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
        except Exception as exc:
            log.exception("Unexpected error resolving outputs for %s: %s", name, exc)
            return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
