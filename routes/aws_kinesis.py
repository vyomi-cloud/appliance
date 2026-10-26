"""AWS Kinesis Data Streams — native JSON wire + console REST for the offline appliance.

The engine is core/kinesis_core.py (the same code Nano runs). State lives in the
active space's `service_states["kinesis"]` (via core.app_context.kinesis_state), so it is
persisted with the platform, scoped per space, and counted by the space's cost-savings
metrics like every other service.
"""
from __future__ import annotations

import base64
import json

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse, Response

from core import app_context as ctx
from core import kinesis_core

OFFLINE_ACCOUNT_ID = "123456789012"


class SpaceKinesisStore:
    """kinesis_core store seam over the active space's persisted service state."""

    account_id = OFFLINE_ACCOUNT_ID

    @property
    def streams(self) -> dict:
        return ctx.kinesis_state.setdefault("streams", {})

    @property
    def policies(self) -> dict:
        return ctx.kinesis_state.setdefault("policies", {})

    @property
    def seq(self) -> dict:
        return ctx.kinesis_state.setdefault("seq", {"n": 0})

    def persist(self) -> None:
        ctx.persist_state()


STORE = SpaceKinesisStore()

# Control-plane writes move the space's resource graph + cost-savings metrics; the data
# plane (PutRecord/GetRecords) does not, so it skips the (heavier) inventory refresh.
_INVENTORY_OPS = {
    "CreateStream", "DeleteStream", "UpdateShardCount", "SplitShard", "MergeShards",
    "UpdateStreamMode", "RegisterStreamConsumer", "DeregisterStreamConsumer",
}


def _usage(op: str, name: str) -> None:
    try:
        ctx.record_usage("kinesis." + op, {"name": name, "resource_id": name, "service": "kinesis"})
    except Exception:
        pass


async def handle_wire(request: Request) -> Response:
    """X-Amz-Target `Kinesis_20131202.<Op>` (JSON 1.1) — what boto3 / Java v2 / Go v2 / aws-cli send."""
    target = request.headers.get("x-amz-target", "")
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except Exception:
        payload = {}
    r = kinesis_core.dispatch(STORE, target, payload)
    op = target.rsplit(".", 1)[-1]
    if r.status < 400 and op in _INVENTORY_OPS:
        _usage(op, str(payload.get("StreamName") or str(payload.get("StreamARN") or "").rsplit("/", 1)[-1]))
    headers = {}
    if r.status >= 400 and isinstance(r.body, dict) and r.body.get("__type"):
        headers["x-amzn-ErrorType"] = r.body["__type"]
    return Response(content=json.dumps(r.body), status_code=r.status,
                    media_type="application/x-amz-json-1.1", headers=headers)


def _fail(r: dict) -> JSONResponse:
    return JSONResponse({"detail": r.get("detail") or r.get("code") or "error", "code": r.get("code")},
                        status_code=int(r.get("status") or 400))


def register(app: FastAPI, **kwargs) -> None:
    @app.get("/api/kinesis/streams")
    def api_kinesis_list():
        return kinesis_core.console_list(STORE)

    @app.post("/api/kinesis/streams")
    def api_kinesis_create(payload: dict = Body(default=None)):
        r = kinesis_core.console_create(STORE, payload or {})
        if r.get("ok"):
            _usage("CreateStream", r["name"])
        return r if r.get("ok") else _fail(r)

    @app.get("/api/kinesis/streams/{name}")
    def api_kinesis_get(name: str):
        r = kinesis_core.console_get(STORE, name)
        return r if r.get("ok") else _fail(r)

    @app.api_route("/api/kinesis/streams/{name}", methods=["PUT", "PATCH"])
    def api_kinesis_update(name: str, payload: dict = Body(default=None)):
        r = kinesis_core.console_update(STORE, name, payload or {})
        return r if r.get("ok") else _fail(r)

    @app.delete("/api/kinesis/streams/{name}")
    def api_kinesis_delete(name: str):
        r = kinesis_core.console_delete(STORE, name)
        if r.get("ok"):
            _usage("DeleteStream", name)
        return r if r.get("ok") else _fail(r)

    @app.post("/api/kinesis/streams/{name}/put")
    def api_kinesis_put(name: str, payload: dict = Body(default=None)):
        p = payload or {}
        data = base64.b64encode(str(p.get("data") or "").encode()).decode()
        r = kinesis_core.dispatch(STORE, "Kinesis_20131202.PutRecord", {
            "StreamName": name, "PartitionKey": str(p.get("partition_key") or "pk"), "Data": data})
        return r.body if r.status < 400 else JSONResponse(r.body, status_code=r.status)
