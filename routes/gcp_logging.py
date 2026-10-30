"""Cloud Logging v2 native wire on the offline appliance.

The engine is core/gcp_logging_core.py (shared with Nano and the dev server). Its state lives
in the active space's `service_states["gcp_logging"]` slot, so log entries, sinks, log-based
metrics, log buckets and views persist with the appliance state and follow space switches.
Mounted on the Logging resource paths only — `/v2/projects/...` is shared with other GCP v2
APIs (Cloud Run, Cloud Functions), so there is no catch-all.
"""
from __future__ import annotations

from fastapi import FastAPI, Request, Response

from core import app_context as ctx
from core import gcp_logging_core as lg

PLATFORM = ctx.PLATFORM
_KEYS = {"entries": list, "sinks": dict, "metrics": dict, "buckets": dict, "views": dict}


def _slot() -> dict | None:
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    if not active_id:
        return None
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    slot = space.setdefault("service_states", {}).setdefault("gcp_logging", {})
    for k, t in _KEYS.items():
        slot.setdefault(k, t())
    return slot


class SpaceLoggingStore(lg.LoggingStore):
    """LoggingStore whose state is the active space's persisted slot."""

    def __init__(self) -> None:           # no super().__init__: the state attrs are properties
        self._fallback = {k: t() for k, t in _KEYS.items()}
        self._clock = None

    def _s(self) -> dict:
        return _slot() or self._fallback

    entries = property(lambda self: self._s()["entries"])
    sinks = property(lambda self: self._s()["sinks"])
    metrics = property(lambda self: self._s()["metrics"])
    buckets = property(lambda self: self._s()["buckets"])
    views = property(lambda self: self._s()["views"])

    def persist(self) -> None:
        if _slot() is not None:
            ctx.persist_state()


_STORE = SpaceLoggingStore()


def register(app: FastAPI) -> None:
    async def _wire(request: Request):
        r = lg.dispatch(_STORE, request.method, request.url.path, dict(request.query_params),
                        dict(request.headers), await request.body())
        if request.method != "GET" and r.status < 300:
            _STORE.persist()
        return Response(content=r.body, status_code=r.status, media_type=r.media_type, headers=r.headers)

    rw = ["GET", "POST", "PATCH", "PUT", "DELETE"]
    app.add_route("/v2/entries:write", _wire, methods=["POST"])
    app.add_route("/v2/entries:list", _wire, methods=["POST"])
    for tail in ("logs", "logs/{log}", "sinks", "sinks/{sink}", "metrics", "metrics/{metric}",
                 "locations/{loc}/buckets", "locations/{loc}/buckets/{rest:path}"):
        app.add_route("/v2/projects/{project}/" + tail, _wire, methods=rw)
