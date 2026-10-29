"""Offline wire for Azure App Configuration's data plane (``{store}.azconfig.io``).

core/azure_appconfiguration_core.py owns the semantics; this module only maps HTTP onto it:
``/azure-data/appconfig/{store}/{kv|keys|labels|locks|revisions|snapshots|operations…}``. The store's
ARM ``properties.endpoint`` points here, so ``azure-data-appconfiguration`` / ``azappconfig`` /
``az appconfig kv`` work with only the endpoint (connection string) changed. A request whose Host is
``{store}.azconfig.*`` is rewritten onto the same path by core.middleware.
"""
from __future__ import annotations

import json

from fastapi import Request
from fastapi.responses import Response

from core import azure_appconfiguration_core as core

METHODS = ["GET", "HEAD", "PUT", "PATCH", "DELETE"]


def _state():
    from providers import azure_services
    return azure_services._state


def register(app) -> None:
    async def dispatch(store: str, request: Request, rest: str = ""):
        host = request.headers.get("host") or "localhost:9000"
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
        base = f"{scheme}://{host}/azure-data/appconfig/{store}"
        raw = await request.body() if request.method in ("PUT", "PATCH") else b""
        query: dict = {}
        for k, v in request.query_params.multi_items():     # repeated params (tags=a=b&tags=c=d) → list
            query[k] = v if k not in query else (query[k] if isinstance(query[k], list) else [query[k]]) + [v]
        r = core.data_dispatch(_state(), store, request.method, "/" + rest, query,
                               dict(request.headers), raw, base=base)
        body = r["body"]
        headers = dict(r["headers"])
        headers.setdefault("Sync-Token", "zAJw6V16=Njo4NDk6;sn=849")
        if body is None:
            return Response(status_code=r["status"], headers=headers)
        return Response(content=json.dumps(body), status_code=r["status"], headers=headers,
                        media_type=r.get("media") or "application/json")

    app.add_api_route("/azure-data/appconfig/{store}", dispatch, methods=METHODS, include_in_schema=False)
    app.add_api_route("/azure-data/appconfig/{store}/{rest:path}", dispatch, methods=METHODS, include_in_schema=False)
