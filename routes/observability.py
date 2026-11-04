"""/_obs — OTLP/HTTP ingest (v1/traces|metrics|logs), Jaeger query, Prometheus/Grafana-compatible API and /_obs/metrics.

Thin glue over core/observability_core.py (the same file Nano runs). Point an OpenTelemetry SDK at
OTEL_EXPORTER_OTLP_ENDPOINT=http://<host>/_obs (JSON protocol) and a Grafana Prometheus data source at http://<host>/_obs/prom.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import Response

from core import observability_core as obs
from routes.aws_cloudwatch import get_store


def register(app: FastAPI) -> None:
    try:   # Azure storage Availability / SuccessE2ELatency come from the requests this process measured
        from core import azure_monitor_core
        azure_monitor_core.request_telemetry = lambda acct: obs.azure_storage_request_metrics(obs.default_store(), acct)
        azure_monitor_core.resource_metric_defs = obs.azure_metric_defs
        azure_monitor_core.resource_series = lambda *a: obs.azure_series(obs.default_store(), *a)
    except Exception:
        pass

    def _mon_store():
        try:
            from core.gcp_monitoring_core import shared_store as _gm
            return _gm()
        except Exception:
            return None

    async def serve(request: Request, rest: str = "") -> Response:
        body = await request.body()
        r = obs.dispatch(obs.default_store(), request.method, request.url.path, dict(request.query_params),
                         dict(request.headers), body, cw_store=get_store(), mon_store=_mon_store())
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    app.add_api_route("/_obs/{rest:path}", serve, methods=["GET", "POST"], include_in_schema=False)
    start_collectors()


# ───────────── offline runtime collectors (timer) ─────────────
# Every 30 s: (1) RDS - pg_stat_* from the Postgres engine behind each DB instance (+ `docker stats` of the container named by
# VYOMI_RDS_CONTAINER when set) -> CloudWatch AWS/RDS + Database Insights; (2) Memorystore - INFO from the shared Valkey data plane
# (core/gcp_redis_core.DATA_PLANE) -> redis.googleapis.com series for every READY instance. Both skip silently when their runtime is
# absent (LXD-only / in-memory sqlite / no Valkey): no runtime -> no datapoints.
import os as _os
import socket as _socket
import subprocess as _sp
import threading as _th
import time as _time

_COLLECT = {"started": False}


def _docker_stats_line(container: str) -> str:
    try:
        cp = _sp.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", container], capture_output=True, timeout=20)
        return cp.stdout.decode(errors="replace").strip().splitlines()[0] if cp.returncode == 0 and cp.stdout.strip() else ""
    except Exception:
        return ""


def valkey_info(host: str, port: int, timeout: float = 3.0) -> str:
    """RESP `INFO` over a plain socket (no client library)."""
    with _socket.create_connection((host, int(port)), timeout=timeout) as c:
        c.sendall(b"*1\r\n$4\r\nINFO\r\n")
        buf = b""
        while b"\r\n\r\n" not in buf and len(buf) < 1 << 20:
            chunk = c.recv(65536)
            if not chunk:
                break
            buf += chunk
            if buf.startswith(b"$") and b"\r\n" in buf:
                n = int(buf[1:buf.index(b"\r\n")])
                if len(buf) >= buf.index(b"\r\n") + 2 + n:
                    break
    return buf.decode(errors="replace").split("\r\n", 1)[-1] if buf.startswith(b"$") else buf.decode(errors="replace")


def collect_once() -> dict:
    out = {"rds": {}, "redis": []}
    try:
        from core.appliance_stores import rds_store
        out["rds"] = obs.collect_rds_stats(rds_store(), get_store(), _docker_stats_line(_os.environ.get("VYOMI_RDS_CONTAINER", "")) if _os.environ.get("VYOMI_RDS_CONTAINER") else "")
    except Exception:
        pass
    try:
        from core import gcp_redis_core as rc
        host, port = rc.DATA_PLANE.get("host"), rc.DATA_PLANE.get("port")
        if host:
            info = obs.parse_redis_info(valkey_info(host, port))
            from core.gcp_monitoring_core import shared_store as _gm
            for full, inst in list(rc.shared_store().instances.items()):
                if inst.get("state") == "READY":
                    parts = full.split("/")
                    out["redis"] += obs.publish_redis_info(_gm(), parts[1], parts[-1], parts[3], info)
    except Exception:
        pass
    return out


def start_collectors(interval: float = 30.0) -> None:
    if _COLLECT["started"] or _os.environ.get("VYOMI_OBS_COLLECT", "1") == "0":
        return
    _COLLECT["started"] = True

    def loop():
        while True:
            _time.sleep(interval)
            collect_once()
    _th.Thread(target=loop, daemon=True, name="obs-collectors").start()
