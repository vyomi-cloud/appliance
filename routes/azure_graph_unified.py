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

from starlette.convertors import Convertor, register_url_convertor
from starlette.requests import Request
from starlette.responses import Response

from core import wire_ingress as _wi

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


class _EntraTenant(Convertor):
    """A tenant path segment that is not a Cognito user-pool id (``us-east-1_AbC123``)."""
    regex = r"(?![a-z0-9-]+_[A-Za-z0-9]+$)(?!v1\.0$|beta$|azure-data$|api$)[^/]+"

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


async def _serve(service: str, request: Request):
    body = await request.body()
    hdrs_in = dict(request.headers)
    hdrs_in.setdefault("x-forwarded-proto", request.url.scheme)   # the OIDC discovery document must advertise https on the TLS front
    out = _wi.dispatch_service(service, request.method, request.url.path,
                               dict(request.query_params), hdrs_in, body)
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
    if "api-key" in headers and segs[0].split("(", 1)[0] in ("indexes", "datasources", "indexers", "skillsets", "synonymmaps", "aliases", "servicestats"):
        return False       # Azure AI Search OData (`indexes('kb')`): core/azure_search_core.wire_dispatch via routes/azure_dataplane_unified
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
    if path.startswith("/azure-data/table/"):     # the ARM primaryEndpoints.table form: /azure-data/table/{account}/... (endurance F404)
        tail = path[len("/azure-data/table/"):]
        path = "/" + (tail.split("/", 1)[1] if "/" in tail else "")
    else:
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
        # Entra sign-in (client_credentials grant against a REAL app secret — core/azure_graph_core
        # validates it and logs the sign-in), the endpoint Nano's router claims by path shape too.
        for tok in ("/{tenant}/oauth2/v2.0/token", "/{tenant}/oauth2/token", "/{tenant}/oauth2/v2.0/authorize"):
            app.add_route(tok, _graph, methods=["POST"])
        # Entra OIDC discovery + JWKS (core/azure_entra_tokens_core): what msal / PyJWT.PyJWKClient / APIM validate-jwt fetch. The v1-style
        # `/{tenant}/.well-known/openid-configuration` uses a convertor that skips Cognito pool ids (`us-east-1_abc`), which the AWS router serves.
        try:
            register_url_convertor("entra", _EntraTenant())
        except Exception:
            pass
        for tok in ("/{tenant:entra}/v2.0/.well-known/openid-configuration", "/{tenant:entra}/.well-known/openid-configuration",
                    "/{tenant:entra}/discovery/v2.0/keys", "/{tenant:entra}/discovery/keys", "/discovery/v2.0/keys", "/discovery/keys",
                    "/{tenant:entra}/discovery/instance", "/common/userrealm/{upn}"):
            app.add_route(tok, _graph, methods=["GET"])
        mounted.append("azure_graph")
    if _wi.is_unified("azure_cosmos"):
        app.add_route("/dbs", _cosmos, methods=_METHODS + ["OPTIONS"])   # OPTIONS: the CORS preflight (account properties.cors)
        app.add_route("/dbs/{rest:path}", _cosmos, methods=_METHODS + ["OPTIONS"])
        mounted.append("azure_cosmos")
    if _wi.is_unified("azure_table"):
        app.add_route("/azure-data/tableroot/{rest:path}", _table, methods=_METHODS + ["HEAD", "MERGE", "OPTIONS"])
        app.add_route("/azure-data/table/{rest:path}", _table, methods=_METHODS + ["HEAD", "MERGE", "OPTIONS"])
        app.add_middleware(AzureTableRewrite)
        mounted.append("azure_table")
    return mounted
