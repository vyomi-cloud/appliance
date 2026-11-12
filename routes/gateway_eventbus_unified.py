"""v4.0.0 — the shared gateway + event-bus backends on the REAL appliance (what Mesh/Codespace runs).

Until this module the appliance served these through pre-v4 handlers (providers/gcp_services.py API Gateway, a Vyomi-own
Eventarc, azure_dataplane._apim_handle) and nothing served `/gcpgw/<id>` or a `*.gateway.dev` Host, so the shared engines
(core/gateway_common, gcp_apigateway_gateway, azure_apim_gateway_core, event_bus_engine) were reachable only on Nano. Registered
BEFORE the provider routes (first match wins), these paths go to the SAME router Nano uses, over the appliance's durable stores:

  * GCP API Gateway control plane  /v1/projects/{p}/locations/{l}/apis|apiConfigs|gateways[/...]   (core/gcp_apigateway_core)
  * GCP API Keys v2                /v2/projects/{p}/locations/global/keys[/...]
  * GCP Eventarc                   /v1/projects/{p}/locations/{l}/triggers|providers[/...]         (core/gcp_eventarc_core + event bus)
  * GCP gateway data plane         /gcpgw/{gateway}/<path>   and any request whose Host ends `.gateway.dev` (rewritten to
                                   /__gcpgw_host__/<path>; the Host header is kept, the router resolves the gateway from it)
  * Azure APIM data plane          /azure-data/apim/{service}/<path>  (routing, policies, subscription keys, quotas)

(and the same under /_wire/, stripped by routes/wire_prefix.py). Opt-out: VYOMI_LEGACY_WIRE=1 mounts nothing.
"""
from __future__ import annotations

import os

from fastapi import Request, Response

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
_HOST_PREFIX = "/__gcpgw_host__"


def _router():
    from core import wire_ingress as _wi
    return _wi.new_services_router() or _wi.appliance_router()


def _json_err(status: int, msg: str) -> Response:
    return Response(content=('{"code":%d,"message":"%s"}' % (status, msg)).encode(), status_code=status, media_type="application/json")


async def _serve(request: Request, path: str | None = None, provider: str | None = None) -> Response:
    from core import app_context as _ctx
    body = await request.body()
    tok = _ctx.REQUEST_PROVIDER.set(provider) if provider else None
    try:
        out = await _router().ahandle(request.method, path or request.url.path, dict(request.query_params), dict(request.headers), body)
    finally:
        if tok is not None:
            _ctx.REQUEST_PROVIDER.reset(tok)
    return Response(content=out["body"], status_code=out["status"], headers={k: v for k, v in (out["headers"] or {}).items()})


async def _gcp_control(request: Request):
    from core import gcp_apigateway_core as _agw, gcp_eventarc_core as _arc
    p = request.url.path.split("?", 1)[0]
    if p.endswith(":fire"):   # the demo `triggers/{t}:fire` helper stays on core/nats_routes (the native API has no such verb)
        for r in request.app.router.routes:
            if getattr(r, "name", "") == "gcp_eventarc_trigger_fire":
                return await r.endpoint(request.path_params["project"], request.path_params["location"], request.path_params["rest"].split(":")[0].split("/")[0], request)
    if not (_agw.is_apigateway_path(p) or _agw.is_apikeys_path(p) or _arc.is_eventarc_path(p)):
        return _json_err(404, "Unknown path: " + p)
    # under the GCP provider: retries / dead-letter publishes this call runs reach the SAME Pub/Sub space the native Pub/Sub routes write
    # (the Cloud Run slot is pinned to its own provider in routes/gcp_run._slot, so this does not change what Eventarc sees of Cloud Run)
    return await _serve(request, provider="gcp")


async def _gcp_data(request: Request):
    return await _serve(request)


async def _gcp_host(request: Request):
    p = request.url.path
    return await _serve(request, path=(p[len(_HOST_PREFIX):] or "/"))


async def _azure_apim(request: Request):
    return await _serve(request, provider="azure")


class GatewayHostMiddleware:
    """Pure ASGI: a request addressed to `<gateway>.<region>.gateway.dev` (Host header) is rewritten to `/__gcpgw_host__<path>`."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            host = ""
            for k, v in scope.get("headers") or []:
                if k == b"host":
                    host = v.decode("latin-1").split(":", 1)[0].lower()
                    break
            p = scope.get("path") or ""
            if ".execute-api." in host and not p.startswith(("/apigw/", "/restapis/", "/_apigw/", "/api/", "/_wire/")):
                # {id}.execute-api.<anything>[/{stage}]/path (the host-style invoke URL) -> the path-style route the router serves
                scope = dict(scope)
                scope["path"] = "/apigw/" + host.split(".", 1)[0] + (p if p.startswith("/") else "/" + p)
                raw = scope.get("raw_path")
                if isinstance(raw, (bytes, bytearray)):
                    scope["raw_path"] = ("/apigw/" + host.split(".", 1)[0]).encode() + bytes(raw)
            elif host.endswith(".gateway.dev") and not p.startswith(_HOST_PREFIX):
                scope = dict(scope)
                scope["path"] = _HOST_PREFIX + (p if p.startswith("/") else "/" + p)
                raw = scope.get("raw_path")
                if isinstance(raw, (bytes, bytearray)):
                    scope["raw_path"] = _HOST_PREFIX.encode() + bytes(raw)
        await self.app(scope, receive, send)


def register(app) -> None:
    if os.environ.get("VYOMI_LEGACY_WIRE", "").strip().lower() in ("1", "true", "yes"):
        return
    v1 = "/v1/projects/{project}/locations/{location}"
    for coll in ("apis", "apiConfigs", "gateways", "triggers", "providers"):
        app.add_api_route(f"{v1}/{coll}", _gcp_control, methods=_METHODS, include_in_schema=False)
        app.add_api_route(f"{v1}/{coll}" + "/{rest:path}", _gcp_control, methods=_METHODS, include_in_schema=False)
    k = "/v2/projects/{project}/locations/global/keys"
    app.add_api_route(k, _gcp_control, methods=_METHODS, include_in_schema=False)
    app.add_api_route(k + "/{rest:path}", _gcp_control, methods=_METHODS, include_in_schema=False)
    app.add_api_route("/gcpgw/{gateway}", _gcp_data, methods=_METHODS, include_in_schema=False)
    app.add_api_route("/gcpgw/{gateway}/{rest:path}", _gcp_data, methods=_METHODS, include_in_schema=False)
    app.add_api_route(_HOST_PREFIX, _gcp_host, methods=_METHODS, include_in_schema=False)
    app.add_api_route(_HOST_PREFIX + "/{rest:path}", _gcp_host, methods=_METHODS, include_in_schema=False)
    app.add_api_route("/azure-data/apim/{service}", _azure_apim, methods=_METHODS, include_in_schema=False)
    app.add_api_route("/azure-data/apim/{service}/{rest:path}", _azure_apim, methods=_METHODS, include_in_schema=False)
    app.add_middleware(GatewayHostMiddleware)
