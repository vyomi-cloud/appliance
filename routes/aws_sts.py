"""AWS STS — console routes + the store seam for the native Query wire.

The engine is core/sts_core.py (shared with Nano). Here its state lives in the
active space's `service_states["sts"]` slot, so sessions survive restarts like every
other space-scoped resource. Served: /api/sts/sessions (console) and, via
`get_store()`, server.api_sts_query (the SigV4 Query wire real SDKs speak).
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core import app_context as ctx
from core import sts_core
from core.sts_core import StsStore

PLATFORM = ctx.PLATFORM


def _slot() -> dict | None:
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    if not active_id:
        return None
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    return space.setdefault("service_states", {}).setdefault("sts", {"sessions": {}, "access_keys": {}})


class SpaceStsStore(StsStore):
    """StsStore whose dicts are the active space's persisted slot."""

    def __init__(self) -> None:
        self._fallback = {"sessions": {}, "access_keys": {}}
        self.account_id = ctx.AWS_ACCOUNT_ID

    @property
    def sessions(self) -> dict:
        return (_slot() or self._fallback)["sessions"]

    @property
    def access_keys(self) -> dict:
        return (_slot() or self._fallback)["access_keys"]

    def persist(self) -> None:
        if _slot() is not None:
            ctx.persist_state()


_STORE = SpaceStsStore()


def get_store() -> SpaceStsStore:
    return _STORE


def register(app: FastAPI) -> None:
    @app.get("/api/sts/sessions")
    def api_sts_sessions():
        return {"ok": True, "items": sts_core.list_sessions(_STORE)}

    @app.post("/api/sts/sessions")
    async def api_sts_create_session(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        out = sts_core.console_create(_STORE, body if isinstance(body, dict) else {})
        return JSONResponse(out, status_code=200 if out.get("ok") else 400)

    @app.get("/api/sts/sessions/{access_key_id}")
    def api_sts_get_session(access_key_id: str):
        s = _STORE.sessions.get(access_key_id)
        if not s:
            return JSONResponse({"ok": False, "code": "NotFound", "name": access_key_id}, status_code=404)
        return {"ok": True, **sts_core.session_row(s)}

    @app.delete("/api/sts/sessions/{access_key_id}")
    def api_sts_delete_session(access_key_id: str):
        out = sts_core.console_delete(_STORE, access_key_id)
        return JSONResponse(out, status_code=200 if out.get("ok") else 404)
