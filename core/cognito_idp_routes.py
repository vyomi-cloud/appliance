"""Offline-appliance HTTP surface for Amazon Cognito user pools (FastAPI side only).

* `root_dispatch(request)` — the native SDK/CLI wire: `POST /` with
  `X-Amz-Target: AWSCognitoIdentityProviderService.*` (the server's AWS root
  dispatcher hands Cognito requests here).
* `/<poolId>/.well-known/{jwks.json,openid-configuration}` — OIDC discovery.
* `/api/cognito-idp/...` — the console REST (core/console_cognito_idp), the same
  facade Nano serves from the service worker.

State lives in a SQLite-backed `PersistentCognitoIdpStore` (survives restarts); no
containers. The engine is core/cognito_idp_core.py — identical to what Nano runs.
"""

import json
import os

from core import cognito_idp_core as cg
from core import console_cognito_idp as console

_STORE = None
_MIRROR = None   # callable(store) set by server.py: mirrors pools into the space state (cost savings)


def store():
    global _STORE
    if _STORE is None:
        from core.persistent_store import PersistentCognitoIdpStore, SqliteStateBackend
        path = os.environ.get("VYOMI_COGNITO_DB", "/data/vyomi-cognito-idp.sqlite")
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            backend = SqliteStateBackend(path)
        except Exception:
            backend = SqliteStateBackend(":memory:")
        st = PersistentCognitoIdpStore(backend)
        base_persist = st.persist

        def persist():
            base_persist()
            if _MIRROR:
                try:
                    _MIRROR(st)
                except Exception:
                    pass
        st.persist = persist
        _STORE = st
        if _MIRROR:
            try:
                _MIRROR(st)
            except Exception:
                pass
    return _STORE


async def root_dispatch(request):
    from fastapi import Response
    try:
        payload = json.loads(await request.body() or b"{}")
    except Exception:
        payload = {}
    r = cg.dispatch(store(), request.headers.get("x-amz-target", ""), payload)
    headers = dict(r.headers or {})
    return Response(content=json.dumps(r.body), status_code=r.status, media_type=r.media_type, headers=headers)


def register(app, mirror=None):
    """Mount the console REST + OIDC discovery routes. Call BEFORE the S3 catch-all."""
    global _MIRROR
    from fastapi import Request, Response
    _MIRROR = mirror

    async def _console(rest: str, request: Request):
        body = {}
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                body = json.loads(await request.body() or b"{}")
            except Exception:
                body = {}
        status, obj = console.handle(store(), request.method, "/" + rest, dict(request.query_params), body)
        return Response(content=json.dumps(obj), status_code=status, media_type="application/json")

    async def _wellknown(pool_id: str, doc: str):
        d = (cg.jwks if doc == "jwks.json" else cg.openid_configuration)(store(), pool_id)
        if d is None:
            return Response(content=b'{"message":"Not Found"}', status_code=404, media_type="application/json")
        return Response(content=json.dumps(d), media_type="application/json")

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    app.add_api_route("/api/cognito-idp/{rest:path}", _console, methods=methods, include_in_schema=False)
    app.add_api_route("/{pool_id}/.well-known/{doc}", _wellknown, methods=["GET"], include_in_schema=False)
