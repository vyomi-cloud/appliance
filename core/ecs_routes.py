"""Offline-appliance HTTP surface for Amazon ECS (FastAPI side only).

* `root_dispatch(request)` — the native SDK/CLI wire: `POST /` with
  `X-Amz-Target: AmazonEC2ContainerServiceV20141113.*` (the server's AWS root
  dispatcher hands ECS requests here).
* `/api/ecs/...` — the console REST (core/console_ecs), the same facade Nano serves
  from the service worker.

State lives in a SQLite-backed `PersistentEcsStore` (survives restarts); the engine is
core/ecs_core.py — identical to what Nano runs. Tasks are control-plane objects; on
Pro/Max the Docker substrate can back them with real containers through the store's
`runtime` seam.
"""

import json
import os

from core import console_ecs as console
from core import ecs_core as ec

_STORE = None
_MIRROR = None   # callable(store) set by server.py: mirrors clusters into the space state (cost savings)


def store():
    global _STORE
    if _STORE is None:
        from core.persistent_store import PersistentEcsStore, SqliteStateBackend
        path = os.environ.get("VYOMI_ECS_DB", "/data/vyomi-ecs.sqlite")
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            backend = SqliteStateBackend(path)
        except Exception:
            backend = SqliteStateBackend(":memory:")
        st = PersistentEcsStore(backend)
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
    r = ec.dispatch(store(), request.headers.get("x-amz-target", ""), payload)
    return Response(content=json.dumps(r.body), status_code=r.status, media_type=r.media_type, headers=dict(r.headers or {}))


def register(app, mirror=None):
    """Mount the console REST routes. Call BEFORE the S3 catch-all."""
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

    app.add_api_route("/api/ecs/{rest:path}", _console, methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
