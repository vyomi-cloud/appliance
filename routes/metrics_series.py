"""GET /api/metrics/series — measured request series for the console Metrics tabs.

Backed by core/request_metrics.py (a ring buffer fed by the request-recorder
middleware): requests, errors (4xx/5xx) and latency p50/p95 per step, zero-filled.
"""
from __future__ import annotations

from fastapi import FastAPI

from core import request_metrics


def register(app: FastAPI) -> None:

    @app.get("/api/metrics/series")
    def metrics_series(provider: str = "", service: str = "", resource: str = "",
                       minutes: int = 60, step: int = 60):
        return request_metrics.series(provider, service, resource, minutes, step)
