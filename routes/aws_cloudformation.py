"""AWS CloudFormation — native Query-protocol wire on the appliance's root `/`.

Thin glue: the engine is core/cloudformation_core.py (the same file Nano runs); this
module owns the durable store for the offline appliance and adapts the request.
"""
from __future__ import annotations

import os
import urllib.request
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from core import app_context as ctx
from core import cloudformation_core as cfn
from core.persistent_store import PersistentCfnStore, SqliteStateBackend

_store: PersistentCfnStore | None = None


def _fetch_url(url: str) -> str:
    with urllib.request.urlopen(url, timeout=20) as r:   # TemplateURL → the appliance's own S3
        return r.read().decode("utf-8")


def get_store() -> PersistentCfnStore:
    global _store
    if _store is None:
        _store = PersistentCfnStore(SqliteStateBackend(os.environ.get("VYOMI_CFN_DB", "/tmp/vyomi-cfn.sqlite")))
        _store.fetch_url = _fetch_url
    return _store


async def handle(request: Request) -> Response:
    params = dict(request.query_params)
    raw = await request.body()
    if raw:
        params.update(dict(parse_qsl(raw.decode("utf-8", errors="ignore"), keep_blank_values=True)))
    r = cfn.dispatch(get_store(), params)
    action = params.get("Action", "")
    if r.status < 300 and action.startswith(("Create", "Update", "Delete", "Execute")):
        ctx.record_usage("cloudformation." + action, {"name": params.get("StackName", "")})   # refreshes cost savings
    return Response(content=r.body, status_code=r.status, media_type="text/xml")


def console_rows() -> list[dict]:
    return cfn.console_list(get_store())["items"]


def register(app: FastAPI) -> None:
    """Console REST for the /console/aws CloudFormation page (same shapes as the Nano adapter)."""
    base = "/api/aws/cloudformation/stacks"

    @app.get(base)
    async def cfn_list() -> dict:
        return cfn.console_list(get_store())

    @app.post(base)
    async def cfn_create(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        r = cfn.console_create(get_store(), body if isinstance(body, dict) else {})
        if r.get("ok"):
            ctx.record_usage("cloudformation.create_stack", {"name": (body or {}).get("name", "")})
        return JSONResponse(r, status_code=200 if r.get("ok") else 400)

    @app.get(base + "/{name}")
    async def cfn_get(name: str) -> Response:
        r = cfn.console_get(get_store(), name)
        return JSONResponse(r, status_code=200 if r.get("ok") else 404)

    @app.delete(base + "/{name}")
    async def cfn_delete(name: str) -> Response:
        r = cfn.console_delete(get_store(), name)
        if r.get("ok"):
            ctx.record_usage("cloudformation.delete_stack", {"name": name})
        return JSONResponse(r, status_code=200 if r.get("ok") else 400)
