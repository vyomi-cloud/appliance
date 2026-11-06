"""Offline wire for the Azure Event Hubs REST data plane (``{namespace}.servicebus.windows.net``).

core/azure_eventhub_core.py owns the semantics; this module only maps HTTP onto it:
``/azure-data/eventhub/{namespace}/{hub}/messages`` (+ ``partitions/{id}/messages``, ``publishers/{p}/messages``,
``partitions/{id}`` properties). The namespace's ARM ``properties.serviceBusEndpoint`` points here.
"""
from __future__ import annotations

import json

from fastapi import Request
from fastapi.responses import Response

from core import azure_eventhub_core as core

METHODS = ["GET", "POST"]


def _state():
    from providers import azure_services
    return azure_services._state


def register(app) -> None:
    async def dispatch(ns: str, request: Request, rest: str = ""):
        raw = await request.body() if request.method == "POST" else b""
        query = dict(request.query_params)
        r = core.data_dispatch(_state(), ns, request.method, "/" + rest, query, dict(request.headers), raw)
        body = r["body"]
        if body is None:
            return Response(status_code=r["status"], headers=dict(r["headers"]))
        return Response(content=json.dumps(body), status_code=r["status"], headers=dict(r["headers"]),
                        media_type=r.get("media") or "application/json")

    app.add_api_route("/azure-data/eventhub/{ns}", dispatch, methods=METHODS, include_in_schema=False)
    app.add_api_route("/azure-data/eventhub/{ns}/{rest:path}", dispatch, methods=METHODS, include_in_schema=False)
