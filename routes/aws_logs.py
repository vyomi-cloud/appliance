"""AWS CloudWatch Logs — offline appliance wiring.

The engine is core/logs_core.py (the same file Nano runs). This module only
adapts it to the appliance: a space-scoped store (state lives in the active
space's service_states["logs"], so it persists with the platform state and feeds
the cost-savings collector), the native `Logs_20140328.*` JSON wire used by AWS
SDKs / CLI, and the console REST under /api/logs/*.
"""
from __future__ import annotations

import json
from collections.abc import MutableMapping

from fastapi import FastAPI, Request
from fastapi.responses import Response

from core import app_context as ctx
from core import logs_core


class _AnomalySlot(MutableMapping):
    """logs_core keys anomalies by (detectorArn, pattern) tuples; the persisted state is JSON, so
    the slot keeps them under "arn\x1fpattern" string keys and this view hands tuples back."""

    _SEP = "\x1f"

    def __init__(self, backing: dict) -> None:
        self._d = backing

    def _k(self, key) -> str:
        return self._SEP.join(key) if isinstance(key, tuple) else str(key)

    def __getitem__(self, key):
        return self._d[self._k(key)]

    def __setitem__(self, key, value):
        self._d[self._k(key)] = value

    def __delitem__(self, key):
        del self._d[self._k(key)]

    def __iter__(self):
        return (tuple(k.split(self._SEP, 1)) for k in list(self._d))

    def __len__(self):
        return len(self._d)


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
    anomaly_detectors = property(lambda self: self._slot("anomaly_detectors"))
    lam_store = None       # runtime links set by the wire router (subscription-filter delivery) — never persisted
    kinesis_store = None

    @property
    def anomalies(self):
        return _AnomalySlot(self._slot("anomalies"))

    @anomalies.setter
    def anomalies(self, value):
        d = self._slot("anomalies")
        d.clear()
        d.update({_AnomalySlot._SEP.join(k) if isinstance(k, tuple) else str(k): v for k, v in dict(value).items()})

    def persist(self) -> None:
        ctx.persist_state()


STORE = SpaceLogsStore()

_READ_ONLY = ("Describe", "Get", "List", "Filter", "Test")


def _record(op: str, payload: dict) -> None:
    """Mutations feed the cloudsim inventory so the space's resource count and
    cost-savings metrics follow log groups as they are created / used / deleted."""
    if op.startswith(_READ_ONLY):
        return
    ctx.record_usage("logs." + op, {"name": payload.get("logGroupName") or "",
                                    "resource_id": payload.get("logGroupName") or ""})


async def wire(request: Request) -> Response:
    """Native CloudWatch Logs JSON protocol (X-Amz-Target: Logs_20140328.<Op>)."""
    target = request.headers.get("x-amz-target", "") or ""
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except Exception:
        payload = {}
    r = logs_core.dispatch(STORE, target, payload)
    if r.status == 200:
        _record(target.rsplit(".", 1)[-1], payload)
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
        if request.method != "GET" and status < 400:
            _record(request.method, {"logGroupName": rest.replace("log-groups/", "").split("/")[0]})
        return Response(content=json.dumps(payload), status_code=status, media_type="application/json")
