"""AWS CloudWatch — native wire on the appliance (rpc-v2-cbor, JSON 1.0 and Query).

Thin glue: the engine is core/cloudwatch_core.py (the same file Nano runs); this module
owns the durable store for the offline appliance and adapts the HTTP request.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from core import app_context as ctx
from core import cloudwatch_core as cw
from core.persistent_store import PersistentCloudWatchStore, SqliteStateBackend

_store: PersistentCloudWatchStore | None = None
VM_URL = os.environ.get("CLOUDLEARN_VICTORIAMETRICS_URL", "").strip().rstrip("/")   # shared VictoriaMetrics (compose profile `full`)
_USAGE_ACTIONS = ("PutMetricAlarm", "PutCompositeAlarm", "DeleteAlarms", "PutDashboard", "DeleteDashboards")


def _vm_sink(ns: str, name: str, dims: list, pt: list) -> None:
    """Mirror each PutMetricData sample into VictoriaMetrics (Prometheus text import), so
    PromQL / MetricsQL / Grafana see the same series. Best effort: the engine stays the API."""
    import re
    import urllib.request
    lab = lambda k: re.sub(r"[^a-zA-Z0-9_]", "_", k)   # noqa: E731
    esc = lambda v: str(v).replace("\\", "\\\\").replace('"', '\\"')   # noqa: E731
    labels = {"namespace": ns, **{lab(d.get("Name", "")): d.get("Value", "") for d in dims}}
    lbl = ",".join(f'{k}="{esc(v)}"' for k, v in labels.items())
    ts = int(pt[0] * 1000)
    base = "cloudwatch_" + lab(name)
    # point = [ts, sum, count, min, max, unit, values]
    lines = [f"{base}_{suf}{{{lbl}}} {val} {ts}" for suf, val in
             (("sum", pt[1]), ("count", pt[2]), ("min", pt[3]), ("max", pt[4]))]
    req = urllib.request.Request(VM_URL + "/api/v1/import/prometheus", data="\n".join(lines).encode(), method="POST")
    urllib.request.urlopen(req, timeout=2).close()


def get_store() -> PersistentCloudWatchStore:
    global _store
    if _store is None:
        _store = PersistentCloudWatchStore(SqliteStateBackend(os.environ.get("VYOMI_CW_DB", "/tmp/vyomi-cw.sqlite")))
        if VM_URL:
            _store.metric_sink = _vm_sink
    return _store


def _action_of(request: Request, raw: bytes) -> str:
    m = request.url.path.rsplit("/", 1)[-1] if request.url.path.startswith("/service/") else ""
    if m:
        return m
    target = request.headers.get("x-amz-target", "")
    if "." in target:
        return target.split(".", 1)[1]
    return dict(request.query_params).get("Action", "") or _form_action(raw)


def _form_action(raw: bytes) -> str:
    from urllib.parse import parse_qsl
    return dict(parse_qsl(raw.decode("utf-8", "ignore"))).get("Action", "")


async def handle(request: Request) -> Response:
    raw = await request.body()
    out = cw.wire(get_store(), request.method, request.url.path, dict(request.headers), raw, dict(request.query_params))
    action = _action_of(request, raw)
    if out["status"] < 300 and action in _USAGE_ACTIONS:
        ctx.record_usage("cloudwatch." + action)   # refreshes cost savings
    h = {k: v for k, v in out["headers"].items() if k.lower() != "content-type"}
    return Response(content=out["body"], status_code=out["status"], headers=h,
                    media_type=out["headers"].get("content-type", "application/octet-stream"))


def console_rows() -> list[dict]:
    return cw.console_list(get_store())["items"]


def register(app: FastAPI) -> None:
    """Native CBOR route + console REST for the /console/aws CloudWatch page."""

    @app.post("/service/" + cw.TARGET_PREFIX + "/operation/{op}")
    async def cw_cbor(op: str, request: Request) -> Response:
        return await handle(request)

    base = "/api/aws/cloudwatch/alarms"

    @app.get(base)
    async def cw_list() -> dict:
        return cw.console_list(get_store())

    @app.post(base)
    async def cw_create(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            body = {}
        r = cw.console_create(get_store(), body if isinstance(body, dict) else {})
        if r.get("ok"):
            ctx.record_usage("cloudwatch.PutMetricAlarm", {"name": (body or {}).get("name", "")})
        return JSONResponse(r, status_code=200 if r.get("ok") else 400)

    @app.get(base + "/{name}")
    async def cw_get(name: str) -> Response:
        r = cw.console_get(get_store(), name)
        return JSONResponse(r, status_code=200 if r.get("ok") else 404)

    @app.delete(base + "/{name}")
    async def cw_delete(name: str) -> Response:
        r = cw.console_delete(get_store(), name)
        if r.get("ok"):
            ctx.record_usage("cloudwatch.DeleteAlarms", {"name": name})
        return JSONResponse(r, status_code=200 if r.get("ok") else 400)
