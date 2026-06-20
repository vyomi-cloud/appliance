"""Appliance backend-readiness probing.

Powers `GET /api/runtime/readiness` (added in routes/runtime.py) which
the SPA's "Appliance is getting ready" banner polls every few seconds
on first launch. The user sees the simulator UI immediately while the
heavier backend containers (Postgres, MySQL, Vault, fake-gcs, the
pubsub/firestore emulator) are still cold-starting in parallel.

Design constraints:
  - No docker.sock dependency. The simulator container doesn't have it
    mounted today and we don't want to add a security surface just for
    a progress bar. Probe the *known* backend ports via tcp connect
    instead — they're all on the same `vyomi_default` docker network.
  - Stateless. Each probe is a 200ms tcp connect; we run them on every
    /api/runtime/readiness call rather than caching, because the user
    is actively watching the banner refresh.
  - Robust to missing backends. A backend that isn't in this list
    simply isn't tracked; a backend that IS listed but unreachable
    counts as "loading" (not "error") because the most common cause
    is "image still being pulled" — which is the whole point of this
    feature.

Service category (cloud-provider grouping) is surfaced in the response
so the banner can show "AWS backends: 4/5 ready" rather than a flat
list. The SPA also uses it to gate per-provider tile interactions —
clicking the AWS card while AWS backends are <100% loads a softer
warning.
"""
from __future__ import annotations

import os
import socket
import time
from typing import Any
from urllib.parse import urlparse


# Each entry: (key, friendly_label, host, port, category, weight_mb)
# `weight_mb` is the rough image size in MB — used to compute a
# pull-progress percentage that's proportional to bytes downloaded,
# not just container count (which would weight a 40MB nats the same
# as a 1500MB google-cloud-sdk emulator).
#
# Hosts default to the docker-compose service name. Override via the
# matching env var (already set by docker-compose.appliance.yml) so
# we honour whatever the user changed locally.
_BACKENDS: list[tuple[str, str, str, int, str, int]] = [
    # name              label                  default_host                 port  category   weight_mb
    ("simulator",       "Vyomi simulator",     "127.0.0.1",                 9000, "core",     627),
    ("postgres",        "PostgreSQL",          "cloudlearn-sql-postgres",   5432, "core",      80),
    ("mysql",           "MySQL",               "vyomi-sql-mysql",           3306, "aws",      580),
    ("vault",           "Vault (KMS / secrets)", "cloudlearn-vault",        8200, "aws",      150),
    ("minio",           "MinIO (S3)",          "vyomi-minio",               9000, "aws",      228),
    ("dynamodb",        "DynamoDB",            "vyomi-dynamodb",            8000, "aws",      250),
    ("nats",            "NATS (EventBridge)",  "vyomi-nats",                4222, "aws",       40),
    ("elasticmq",       "ElasticMQ (SQS)",     "cloudlearn-elasticmq",      9324, "aws",      130),
    ("fake-gcs",        "fake-gcs-server",     "vyomi-gcs",                 4443, "gcp",       80),
    ("pubsub",          "Pub/Sub emulator",    "cloudlearn-pubsub",         8085, "gcp",      750),
    ("firestore",       "Firestore emulator",  "cloudlearn-firestore",      8080, "gcp",      750),
    ("cloudsim",        "CloudSim Plus",       "cloudsim",                  9010, "core",     250),
]


def _probe_one(host: str, port: int, timeout: float = 0.25) -> bool:
    """Open + immediately close a TCP socket; True if the backend is
    accepting connections. 250ms timeout is enough for in-network
    docker services and short enough that polling 12 of them stays
    under the SPA's 3s poll budget."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def probe_all() -> dict[str, Any]:
    """Probe every tracked backend; return a SPA-shaped dict.

    Shape:
      {
        "ready": bool,                          # all backends green
        "overall_pct": int,                     # 0..100, weight-aware
        "ready_count": int,
        "total_count": int,
        "by_category": {                        # for per-cloud progress
          "aws":   { "ready": int, "total": int, "pct": int },
          "gcp":   { "ready": int, "total": int, "pct": int },
          "core":  { "ready": int, "total": int, "pct": int },
        },
        "services": [
          { "name": "postgres", "label": "PostgreSQL",
            "host": "cloudlearn-sql-postgres", "port": 5432,
            "category": "core", "status": "ready" | "loading",
            "weight_mb": 80 }, ...
        ],
        "checked_at": "2026-06-19T00:00:00Z",
      }
    """
    services: list[dict[str, Any]] = []
    ready_weight = 0
    total_weight = 0
    by_cat: dict[str, dict[str, int]] = {}

    for name, label, default_host, port, category, weight in _BACKENDS:
        # Honour env-var override; lets a customer point at an external
        # backend (eg. a managed Postgres) without us caring whether
        # the docker container is up.
        env_key = "VYOMI_BACKEND_HOST_" + name.upper().replace("-", "_")
        host = os.environ.get(env_key, default_host)
        up = _probe_one(host, port)
        services.append({
            "name":      name,
            "label":     label,
            "host":      host,
            "port":      port,
            "category":  category,
            "status":    "ready" if up else "loading",
            "weight_mb": weight,
        })
        total_weight += weight
        if up:
            ready_weight += weight
        cat = by_cat.setdefault(category, {"ready": 0, "total": 0, "weight_ready": 0, "weight_total": 0})
        cat["total"] += 1
        cat["weight_total"] += weight
        if up:
            cat["ready"] += 1
            cat["weight_ready"] += weight

    # Add a per-category pct field for the SPA
    for cat in by_cat.values():
        wt = cat.pop("weight_total")
        wr = cat.pop("weight_ready")
        cat["pct"] = int(round(100.0 * wr / wt)) if wt else 0

    overall = int(round(100.0 * ready_weight / total_weight)) if total_weight else 0
    ready_count = sum(1 for s in services if s["status"] == "ready")
    return {
        "ready":        ready_count == len(services),
        "overall_pct":  overall,
        "ready_count":  ready_count,
        "total_count":  len(services),
        "by_category":  by_cat,
        "services":     services,
        "checked_at":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# ── Cached gate (v2.0.8 progressive startup) ────────────────────────────────
# The service-launch gate runs on every create; re-probing 12 sockets per
# request would add latency, so cache the result for a few seconds. The SPA
# readiness poll (every ~3s) and the gate share this.
_READY_CACHE: dict[str, Any] = {"at": 0.0, "payload": None}


def probe_all_cached(ttl: float = 5.0) -> dict[str, Any]:
    """probe_all() with a short in-memory TTL — used by the gate + can back the
    /api/runtime/readiness endpoint."""
    now = time.time()
    payload = _READY_CACHE.get("payload")
    if payload is not None and (now - float(_READY_CACHE.get("at") or 0)) < ttl:
        return payload  # type: ignore[return-value]
    payload = probe_all()
    _READY_CACHE["at"] = now
    _READY_CACHE["payload"] = payload
    return payload


def is_ready(ttl: float = 5.0) -> bool:
    """Cheap boolean: is the whole appliance ready? Fail-OPEN (returns True) on
    any probe error, so a probing bug can never permanently block launches."""
    try:
        return bool(probe_all_cached(ttl).get("ready"))
    except Exception:
        return True
