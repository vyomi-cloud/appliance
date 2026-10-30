"""v4 C0h — Microsoft Graph (Entra ID) on the offline appliance, ONE engine.

/v1.0/… and /beta/… (and the same under /_wire/, which routes/wire_prefix.py rewrites) are
served by the shared core Nano uses (core/azure_graph_core.py) over the space's persisted
directory (core/appliance_stores.AppStateGraphStore). Every path under those prefixes is
answered by the core — an unknown one with a Graph-style JSON error, never the S3 catch-all.

Opt-out: VYOMI_UNIFIED_INGRESS_SERVICES without azure_graph (or VYOMI_LEGACY_WIRE=1).
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response

from core import wire_ingress as _wi

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


async def _graph(request: Request):
    body = await request.body()
    out = _wi.dispatch_service("azure_graph", request.method, request.url.path,
                               dict(request.query_params), dict(request.headers), body)
    hdrs = {k: v for k, v in out["headers"].items() if k.lower() != "content-length"}
    return Response(content=out["body"], status_code=out["status"], headers=hdrs)


def register(app) -> list:
    """Mount the Graph routes (call BEFORE the provider routes so these win)."""
    if not _wi.is_unified("azure_graph"):
        return []
    for pre in ("/v1.0", "/beta"):
        app.add_route(pre, _graph, methods=_METHODS)
        app.add_route(f"{pre}/{{rest:path}}", _graph, methods=_METHODS)
    return ["azure_graph"]
