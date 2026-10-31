"""v4 C0h — Microsoft Graph (Entra ID) + the Cosmos DB data plane on the offline appliance,
ONE engine.

Graph /v1.0/… and /beta/… (core/azure_graph_core.py) and Cosmos /dbs/… (core/azure_cosmos_core.py) (and the same under /_wire/, which routes/wire_prefix.py rewrites) are
served by the shared cores Nano uses, over the Azure space's persisted state
(core/appliance_stores.AppStateGraphStore / AppStateCosmosStore). Every path under those
prefixes is answered by the core — an unknown one with that API's JSON error, never the S3
catch-all.

Azure Table storage (core/azure_table_core.py) is served the same way (see AzureTableRewrite).
Opt-out: VYOMI_UNIFIED_INGRESS_SERVICES without azure_graph / azure_cosmos / azure_table (or VYOMI_LEGACY_WIRE=1).
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


# Azure Table storage: the table account's root wire (`/Tables`, `/Tables('t')`, `/{table}`,
# `/{table}(PartitionKey='p',RowKey='r')`). Claimed with the same signals as Nano's router
# (aws_wire_router: an `odata` Accept header, the "Tables" collection, or a parenthesised
# entity key — no S3 bucket / Blob container name can contain "(" or start "Tables"), never
# for AWS-signed requests or the appliance's own path families.
_NOT_TABLE = ("api", "azure-data", "v4", "nano", "static", "assets", "subscriptions", "providers",
              "v1.0", "beta", "dbs", "v1", "v2", "v1beta1", "storage", "upload", "download", "_vyomi")


def table_path(path: str, headers: dict) -> bool:
    auth = str(headers.get("authorization") or "")
    if auth.startswith("AWS4-") or any(k.startswith("x-amz-") for k in headers) or "X-Amz-" in path:
        return False
    segs = [x for x in path.split("?", 1)[0].split("/") if x]
    if not segs or segs[0] in _NOT_TABLE or segs[0].startswith("$"):
        return False
    if segs[0] == "Tables" or segs[0].startswith("Tables(") or "(" in segs[0]:
        return True
    return len(segs) == 1 and "odata" in str(headers.get("accept") or "").lower()


class AzureTableRewrite:
    """Table-shaped requests → `/azure-data/tableroot/…` (the native path is restored below)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path") or ""
            bare = path[len("/_wire"):] if path.startswith("/_wire/") else path
            hdrs = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
            if not bare.startswith("/azure-data/") and table_path(bare, hdrs):
                new = "/azure-data/tableroot" + bare
                scope = dict(scope, path=new, raw_path=new.encode("utf-8"))
        await self.app(scope, receive, send)


async def _table(request: Request):
    from urllib.parse import unquote
    body = await request.body()
    raw = request.scope.get("raw_path") or b""
    path = (raw.decode("utf-8", "replace") if raw else request.url.path).split("?", 1)[0]
    path = unquote(path[len("/azure-data/tableroot"):] or "/")
    out = _wi.dispatch_service("azure_table", request.method, path,
                               dict(request.query_params), dict(request.headers), body)
    hdrs = {k: v for k, v in out["headers"].items() if k.lower() != "content-length"}
    return Response(content=out["body"], status_code=out["status"], headers=hdrs)


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
    if _wi.is_unified("azure_table"):
        app.add_route("/azure-data/tableroot/{rest:path}", _table, methods=_METHODS + ["HEAD", "MERGE"])
        app.add_middleware(AzureTableRewrite)
        mounted.append("azure_table")
    return mounted
