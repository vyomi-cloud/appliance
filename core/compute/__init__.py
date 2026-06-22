"""Vyomi compute backends — the ComputeBackend seam (ADR-001/002).

server.py's EC2-instance lifecycle talks only to `ComputeBackend`. Today the
host runs Docker, so `DockerComputeBackend` launches instances as sibling
Docker containers (the `vyomi/instance` image: SSH + docker-in-instance). LXD
remains the legacy backend; a future in-browser backend implements the same ABC.

Select via env: VYOMI_COMPUTE_BACKEND=docker|lxd (default below).
"""
from __future__ import annotations

import os

from .backend import (
    ComputeBackend,
    DockerComputeBackend,
    Instance,
    ensure_instance_ssh_key,
)

__all__ = [
    "ComputeBackend",
    "DockerComputeBackend",
    "Instance",
    "ensure_instance_ssh_key",
    "get_compute_backend",
]


def get_compute_backend(name: str | None = None) -> ComputeBackend:
    """Resolve the active compute backend. Defaults to Docker (CloudLite+ /
    the Docker-compute appliance); set VYOMI_COMPUTE_BACKEND=lxd to keep LXD."""
    name = (name or os.environ.get("VYOMI_COMPUTE_BACKEND")
            or os.environ.get("CLOUDLEARN_COMPUTE_BACKEND") or "docker").lower()
    if name == "docker":
        return DockerComputeBackend()
    raise ValueError(
        f"compute backend '{name}' has no in-process implementation here; "
        "LXD/multipass remain in server.py. Use VYOMI_COMPUTE_BACKEND=docker."
    )
