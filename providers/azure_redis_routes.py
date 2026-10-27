"""Offline data plane for Azure Cache for Redis: the shared Valkey container (BSD-3, Redis protocol).

core/azure_redis_core.py owns the ARM control plane (``Microsoft.Cache/redis``). Offline, the appliance
points the engine at the shared ``vyomi-valkey`` container (CLOUDLEARN_VALKEY_HOST/PORT, set by the compose
files), and ``GET /azure-data/redis/ping`` sends a real ``PING`` over the Redis protocol so the console and
tests can prove the data plane answers. Without a Valkey container (Free tier) it reports control plane only.
"""
from __future__ import annotations

import os
import socket

from fastapi.responses import JSONResponse

from core import azure_redis_core as core


def _configure() -> None:
    host = os.environ.get("CLOUDLEARN_VALKEY_HOST", "").strip()
    if host:
        core.configure_data_plane(host, os.environ.get("CLOUDLEARN_VALKEY_PORT", "6379"))


def _ping(host: str, port: int) -> str:
    with socket.create_connection((host, port), timeout=2) as s:
        s.sendall(b"*1\r\n$4\r\nPING\r\n")
        return s.recv(64).decode("utf-8", "replace").strip()


def register(app) -> None:
    _configure()

    async def ping():
        host, port = core.DATA_PLANE["host"], core.DATA_PLANE["port"]
        if not host:
            return JSONResponse({"dataPlane": False, "message": "Control plane only (no Valkey container on this tier)."})
        try:
            reply = _ping(host, port)
        except OSError as e:
            return JSONResponse({"dataPlane": False, "host": host, "port": port, "message": f"Valkey unreachable: {e}"}, status_code=503)
        return JSONResponse({"dataPlane": True, "host": host, "port": port, "reply": reply})

    app.add_api_route("/azure-data/redis/ping", ping, methods=["GET"], include_in_schema=False)
