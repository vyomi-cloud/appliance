"""AWS CloudWatch Logs — offline appliance wiring.

The engine is core/logs_core.py (the same file Nano runs). This module only
adapts it to the appliance: a space-scoped store (state lives in the active
space's service_states["logs"], so it persists with the platform state and feeds
the cost-savings collector), the native `Logs_20140328.*` JSON wire used by AWS
SDKs / CLI, and the console REST under /api/logs/*.
"""
from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import Response

from core import app_context as ctx
from core import logs_core


class SpaceLogsStore(logs_core.LogsStore):
    """LogsStore whose state dicts are the active space's `logs` service state."""

    def __init__(self) -> None:  # no own state: everything lives in ctx.logs_state
        self.account_id = ctx.AWS_ACCOUNT_ID
        self.region = "us-east-1"
        self._clock = None

    def _slot(self, key: str) -> dict:
        st = ctx.logs_state
        return st.setdefault(key, {})

    log_groups = property(lambda self: self._slot("log_groups"))
    resource_policies = property(lambda self: self._slot("resource_policies"))
    query_definitions = property(lambda self: self._slot("query_definitions"))
    queries = property(lambda self: self._slot("queries"))

    def persist(self) -> None:
        ctx.persist_state()


STORE = SpaceLogsStore()


async def wire(request: Request) -> Response:
    """Native CloudWatch Logs JSON protocol (X-Amz-Target: Logs_20140328.<Op>)."""
    target = request.headers.get("x-amz-target", "") or ""
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except Exception:
        payload = {}
    r = logs_core.dispatch(STORE, target, payload)
    headers = dict(r.headers or {})
    if r.status != 200 and isinstance(r.body, dict) and "__type" in r.body:
        headers["x-amzn-errortype"] = r.body["__type"]
    return Response(content=json.dumps(r.body), status_code=r.status,
                    media_type="application/x-amz-json-1.1", headers=headers)


def register(app: FastAPI) -> None:
    @app.api_route("/api/logs/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def api_logs_console(rest: str, request: Request):
        try:
            body = json.loads(await request.body() or b"{}")
        except Exception:
            body = {}
        status, payload = logs_core.console_dispatch(
            STORE, request.method, rest, dict(request.query_params), body)
        return Response(content=json.dumps(payload), status_code=status, media_type="application/json")
