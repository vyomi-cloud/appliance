"""API Gateway V2 data plane, offline: the Vyomi integration handler behind the shared
Caddy gateway (`vyomi-gateway`).

Caddy owns the listener (TLS, host/path routing). Every change to an API, route, integration,
stage or deployment re-applies the route table to Caddy's admin API (`/load`, live — no
restart). Caddy reverse-proxies to `/_apigw/{api}/{stage}/{path}` here, which runs
`core.apigatewayv2_gateway.handle` with the real Lambda runtime, real HTTP for HTTP proxy
integrations and real JWKS signature checks for JWT authorizers.
"""

import base64
import json
import os
import threading
import time
import urllib.request

from core import apigatewayv2_core as core
from core import apigatewayv2_gateway as gw
from core import gateway_common as gc

ADMIN = os.environ.get("VYOMI_GATEWAY_ADMIN", "http://vyomi-gateway:2019")
HANDLER = os.environ.get("VYOMI_GATEWAY_HANDLER", "simulator:9000")


def push_config(store, admin=None, timeout: float = 5.0) -> bool:
    """POST the full route table to Caddy's admin API. False (never raises) if no gateway runs."""
    url = (admin or ADMIN).rstrip("/") + "/load"
    try:
        req = urllib.request.Request(url, data=json.dumps(gw.caddy_config(store, HANDLER)).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


class _Sync:
    """Coalesces bursts of control-plane calls into one Caddy reload, off the request path."""

    def __init__(self):
        self._lock, self._pending = threading.Lock(), False

    def __call__(self, store):
        with self._lock:
            if self._pending:
                return
            self._pending = True
        threading.Thread(target=self._run, args=(store,), daemon=True).start()

    def _run(self, store):
        time.sleep(0.05)
        with self._lock:
            self._pending = False
        push_config(store)


_http_fetch = gc.default_http_fetch()
# RS256 over the issuer's JWKS; with no `cryptography` installed it must still FAIL CLOSED (a None verifier would skip the check).
_verify_sig = gc.make_rs256_verifier() or (lambda token, header, cfg: False)


def register(app, lambda_invoke):
    """Mount `/_apigw/*` and keep Caddy in sync. `lambda_invoke(name, event)` runs the real
    Lambda runtime and returns its payload (or raises)."""
    from fastapi import Request, Response

    def invoker(fn, event):
        try:
            rec = lambda_invoke(fn, event)
        except Exception:
            return {"_error": True}
        if rec.get("status") != "success":
            return {"_error": True}
        return rec.get("response_payload")

    # Path-style invoke on the main port: http://<origin>/apigw/<id>[/<stage>]/<path> (what the API's
    # ApiEndpoint shows; the host-style https://<id>.execute-api.localhost:9443 name needs the Caddy gateway).
    @app.api_route("/apigw/{api_id}", include_in_schema=False,
                   methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    @app.api_route("/apigw/{api_id}/{path:path}", include_in_schema=False,
                   methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def _apigw_pathstyle(api_id: str, request: Request, path: str = ""):
        store = core.shared_store()
        api = store.apis.get(api_id)
        if not api:
            return Response(content=b'{"message":"Not Found"}', status_code=404, media_type="application/json")
        first = path.split("/", 1)[0]
        if first and first != "$default" and first in (api.get("stages") or {}):
            stage, path = first, path[len(first):].lstrip("/")
        else:
            stage = "$default"
        body = await request.body()
        res = gw.handle(store, api_id, stage, request.method, path, dict(request.headers),
                        dict(request.query_params), body, invoker=invoker, http_fetch=_http_fetch,
                        verify_sig=_verify_sig, source_ip=request.client.host if request.client else "127.0.0.1")
        return Response(content=res.body, status_code=res.status, headers=res.headers)

    @app.api_route("/_apigw/{api_id}/{stage}", include_in_schema=False,
                   methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    @app.api_route("/_apigw/{api_id}/{stage}/{path:path}", include_in_schema=False,
                   methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def _apigw_handle(api_id: str, stage: str, request: Request, path: str = ""):
        body = await request.body()
        res = gw.handle(core.shared_store(), api_id, stage, request.method, path, dict(request.headers),
                        dict(request.query_params), body, invoker=invoker, http_fetch=_http_fetch,
                        verify_sig=_verify_sig, source_ip=request.client.host if request.client else "127.0.0.1")
        return Response(content=res.body, status_code=res.status, headers=res.headers)

    sync = _Sync()
    core.CHANGE_LISTENERS.append(sync)
    sync(core.shared_store())   # initial route table (APIs restored from disk)
