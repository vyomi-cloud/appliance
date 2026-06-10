"""HTTP surface for the lazy backend provisioner.

Exposes three endpoints:

    GET  /api/runtime/backends/{name}/status
        Cheap, idempotent. Returns current provision state.

    POST /api/runtime/backends/{name}/provision
        Kicks off pulling + starting the backend in a background thread.
        Returns 202 Accepted with the initial state immediately. Caller
        polls /status until state == "ready" or "failed".

    POST /api/runtime/backends/{name}/stop
        Stops the backend container without removing it. Subsequent
        provision skips the pull. State flips to "stopped".

These endpoints don't need auth gating right now — anyone hitting the
appliance is on the same laptop. When we add multi-user appliances,
gate behind require_user / admin.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from core import backend_provisioner as _bp


def register(app: FastAPI) -> None:
    @app.get(
        "/api/runtime/backends/{name}/status",
        include_in_schema=False,
    )
    def lazy_backend_status(name: str) -> dict:
        if not _bp.available():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Lazy backend provisioning is unavailable on this appliance "
                    "(Docker daemon unreachable from inside the simulator "
                    "container). Make sure /var/run/docker.sock is mounted "
                    "and the 'docker' Python SDK is installed."
                ),
            )
        st = _bp.status(name)
        if st is None:
            raise HTTPException(
                status_code=404,
                detail=f"unknown backend '{name}'. known: {_bp.recipes()}",
            )
        meta = _bp.recipe_metadata(name) or {}
        return {**meta, "provisioning": st}

    @app.post(
        "/api/runtime/backends/{name}/provision",
        include_in_schema=False,
    )
    def lazy_backend_provision(name: str) -> JSONResponse:
        if not _bp.available():
            raise HTTPException(
                status_code=503,
                detail="Lazy backend provisioning is unavailable.",
            )
        try:
            st = _bp.provision_async(name)
        except KeyError as e:
            raise HTTPException(
                status_code=404,
                detail=f"unknown backend '{name}'. known: {_bp.recipes()}",
            ) from e
        meta = _bp.recipe_metadata(name) or {}
        body = {**meta, "provisioning": st}
        # 202 means "accepted, processing in background"; client polls /status.
        return JSONResponse(status_code=202, content=body)

    @app.post(
        "/api/runtime/backends/{name}/stop",
        include_in_schema=False,
    )
    def lazy_backend_stop(name: str) -> dict:
        if not _bp.available():
            raise HTTPException(
                status_code=503,
                detail="Lazy backend provisioning is unavailable.",
            )
        try:
            st = _bp.stop(name)
        except KeyError as e:
            raise HTTPException(
                status_code=404,
                detail=f"unknown backend '{name}'. known: {_bp.recipes()}",
            ) from e
        meta = _bp.recipe_metadata(name) or {}
        return {**meta, "provisioning": st}
