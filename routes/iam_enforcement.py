"""Mesh-only FastAPI wrapper over core.iam_engine.api.IamApi (/api/iam/<cloud>/enforcement|audit|evaluate|catalog/<service>)."""
from __future__ import annotations

import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _catalog(cloud, service):
    import re
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", service or ""):
        return None
    p = os.path.join(_ROOT, "core", "iam_catalog", cloud, service + ".json")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _inventory():
    p = os.path.join(_ROOT, "wasm", "service-inventory.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def build_api():
    from core import app_context as ctx
    from core.iam_engine import modes
    from core.iam_engine.api import IamApi
    from core import iam_state_adapters as ad

    def holder():
        sp = ctx.gcp_active_space_dict()
        return sp if sp else ctx.STATE

    store = modes.HolderSettingsStore(holder, persist=ctx.persist_state)
    return IamApi(store, state_fn=lambda cloud: ad.state_and_principal(cloud, {}, "", holder())[0],
                  catalog_fn=_catalog, inventory_fn=_inventory)


def register(app: FastAPI, api=None):
    holder = {"api": api}

    async def _go(request: Request, cloud: str, what: str, service: str = ""):
        if holder["api"] is None:
            holder["api"] = build_api()
        body = None
        if request.method in ("PUT", "POST"):
            try:
                body = await request.json()
            except Exception:
                return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        path = f"/api/iam/{cloud}/{what}" + (f"/{service}" if service else "")
        status, out = holder["api"].handle(request.method, path, dict(request.query_params), body)
        return JSONResponse(out, status_code=status)

    @app.api_route("/api/iam/{cloud}/enforcement", methods=["GET", "PUT"])
    @app.api_route("/_wire/api/iam/{cloud}/enforcement", methods=["GET", "PUT"])
    async def _enf(request: Request, cloud: str):
        return await _go(request, cloud, "enforcement")

    @app.api_route("/api/iam/{cloud}/audit", methods=["GET", "DELETE"])
    @app.api_route("/_wire/api/iam/{cloud}/audit", methods=["GET", "DELETE"])
    async def _aud(request: Request, cloud: str):
        return await _go(request, cloud, "audit")

    @app.post("/api/iam/{cloud}/evaluate")
    @app.post("/_wire/api/iam/{cloud}/evaluate")
    async def _ev(request: Request, cloud: str):
        return await _go(request, cloud, "evaluate")

    @app.get("/api/iam/{cloud}/catalog/{service}")
    @app.get("/_wire/api/iam/{cloud}/catalog/{service}")
    async def _cat(request: Request, cloud: str, service: str):
        return await _go(request, cloud, "catalog", service)
