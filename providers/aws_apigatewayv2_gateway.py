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

ADMIN = os.environ.get("VYOMI_GATEWAY_ADMIN", "http://vyomi-gateway:2019")
HANDLER = os.environ.get("VYOMI_GATEWAY_HANDLER", "simulator:9000")
_JWKS: dict = {}


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


def _http_fetch(method, url, headers, body, timeout):
    req = urllib.request.Request(url, data=body or None, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _jwks(issuer: str):
    hit = _JWKS.get(issuer)
    if hit and hit[0] > time.time():
        return hit[1]
    base = issuer.rstrip("/")
    with urllib.request.urlopen(base + "/.well-known/openid-configuration", timeout=5) as r:
        uri = json.load(r)["jwks_uri"]
    with urllib.request.urlopen(uri, timeout=5) as r:
        keys = json.load(r)["keys"]
    _JWKS[issuer] = (time.time() + 300, keys)
    return keys


def _verify_sig(token, header, cfg) -> bool:
    """RS256 against the issuer's JWKS (OIDC discovery). Anything else, or an unreachable
    issuer, fails closed — a JWT authorizer must never admit a token it couldn't verify."""
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa

        if header.get("alg") != "RS256":
            return False
        h, p, sig = token.split(".")
        key = next((k for k in _jwks(cfg["issuer"]) if k.get("kid") == header.get("kid") and k.get("kty") == "RSA"), None)
        if key is None:
            return False
        n, e = (int.from_bytes(gw._b64u(key[x]), "big") for x in ("n", "e"))
        rsa.RSAPublicNumbers(e, n).public_key().verify(
            gw._b64u(sig), f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False


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
