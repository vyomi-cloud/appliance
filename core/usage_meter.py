"""Usage meter: data written through a cloud's data plane, priced like the real cloud.

Real clouds bill stored bytes and write requests on top of the resource itself, so a
simulator that saves you that bill must count them. The middleware feeds ``record``
for every successful data-plane write; ``usage_cost`` prices what has accumulated for
one (space, provider) using public list prices (Standard storage, per-GB-month, and
per-1,000 class-A/write requests).
"""
from __future__ import annotations

import threading

_LOCK = threading.Lock()
_USAGE: dict[tuple[str, str], dict[str, float]] = {}

# provider -> (USD per GB-month stored, USD per 1,000 write requests)
USAGE_RATES: dict[str, tuple[float, float]] = {
    "aws": (0.023, 0.005),     # S3 Standard, PUT/COPY/POST/LIST
    "gcp": (0.020, 0.005),     # Cloud Storage Standard (regional), class A operations
    "azure": (0.018, 0.0065),  # Blob hot LRS, write operations ($0.065 per 10K)
}


def record(space_id: str, provider: str, nbytes: int) -> None:
    with _LOCK:
        u = _USAGE.setdefault((space_id, provider), {"bytes": 0.0, "writes": 0.0})
        u["bytes"] += max(int(nbytes), 0)
        u["writes"] += 1


def snapshot(space_id: str) -> dict[str, dict[str, float]]:
    with _LOCK:
        return {p: dict(u) for (s, p), u in _USAGE.items() if s == space_id}


def usage_cost(provider: str, usage: dict[str, float]) -> float:
    per_gb, per_k = USAGE_RATES.get(provider, (0.0, 0.0))
    return (usage.get("bytes", 0.0) / 1024 ** 3) * per_gb + (usage.get("writes", 0.0) / 1000.0) * per_k
