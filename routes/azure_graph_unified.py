"""v4 C0h — Microsoft Graph (Entra ID) + the Cosmos DB data plane on the offline appliance,
ONE engine.

Graph /v1.0/… and /beta/… (core/azure_graph_core.py) and Cosmos /dbs/… (core/azure_cosmos_core.py) (and the same under /_wire/, which routes/wire_prefix.py rewrites) are
served by the shared cores Nano uses, over the Azure space's persisted state
(core/appliance_stores.AppStateGraphStore / AppStateCosmosStore). Every path under those
prefixes is answered by the core — an unknown one with that API's JSON error, never the S3
catch-all.

Opt-out: VYOMI_UNIFIED_INGRESS_SERVICES without azure_graph / azure_cosmos (or VYOMI_LEGACY_WIRE=1).
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from core import wire_ingress as _wi

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


async def _serve(service: str, request: Request):
    body = await request.body()
    out = _wi.dispatch_service(service, request.method, request.url.path,
                               dict(request.query_params), dict(request.headers), body)
    hdrs = {k: v for k, v in out["headers"].items() if k.lower() != "content-length"}
    return Response(content=out["body"], status_code=out["status"], headers=hdrs)


async def _graph(request: Request):
    return await _serve("azure_graph", request)


async def _cosmos(request: Request):
    return await _serve("azure_cosmos", request)


def register(app) -> list:
    """Mount the Graph + Cosmos routes (call BEFORE the provider routes so these win)."""
    mounted = []
    if _wi.is_unified("azure_graph"):
        for pre in ("/v1.0", "/beta"):
            app.add_route(pre, _graph, methods=_METHODS)
            app.add_route(f"{pre}/{{rest:path}}", _graph, methods=_METHODS)
        mounted.append("azure_graph")
    if _wi.is_unified("azure_cosmos"):
        app.add_route("/dbs", _cosmos, methods=_METHODS)
        app.add_route("/dbs/{rest:path}", _cosmos, methods=_METHODS)
        mounted.append("azure_cosmos")
    return mounted
