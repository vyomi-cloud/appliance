"""/_obs — OTLP/HTTP ingest (v1/traces|metrics|logs), Jaeger query, Prometheus/Grafana-compatible API and /_obs/metrics.

Thin glue over core/observability_core.py (the same file Nano runs). Point an OpenTelemetry SDK at
OTEL_EXPORTER_OTLP_ENDPOINT=http://<host>/_obs (JSON protocol) and a Grafana Prometheus data source at http://<host>/_obs/prom.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import Response

from core import observability_core as obs


def register(app: FastAPI) -> None:

    async def serve(request: Request, rest: str = "") -> Response:
        body = await request.body()
        r = obs.dispatch(obs.default_store(), request.method, request.url.path, dict(request.query_params),
                         dict(request.headers), body)
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    app.add_api_route("/_obs/{rest:path}", serve, methods=["GET", "POST"], include_in_schema=False)
