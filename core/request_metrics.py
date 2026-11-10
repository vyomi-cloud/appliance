"""Request recorder behind the console Metrics / Monitoring tabs.

Every API request the simulator serves is recorded as
(time, provider, service, method, path, status, latency_ms) in a bounded ring
buffer; series() turns it into zero-filled per-step buckets for one
provider/service (optionally narrowed to one resource by name). Nothing here is
synthesized: an idle resource has an all-zero series.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from urllib.parse import unquote

_MAX = 50000
_LOCK = threading.Lock()
_BUF: deque = deque(maxlen=_MAX)


def record(provider: str, service: str, method: str, path: str, status: int,
           latency_ms: float, ts: float | None = None, query: str = "", host: str = "") -> None:
    """Append one request. `host` contributes its first label (virtual-hosted S3 buckets)."""
    segs = {unquote(s).lower() for s in path.split("/") if s}
    if query:
        for kv in query.split("&"):
            if "=" in kv:
                segs.add(unquote(kv.split("=", 1)[1]).lower())
    first = host.split(":", 1)[0].split(".", 1)[0].lower() if host else ""
    if first:
        segs.add(first)
    with _LOCK:
        _BUF.append((ts if ts is not None else time.time(), provider or "", service or "",
                     method, path, int(status), float(latency_ms), frozenset(segs)))


_AWS_API = {"ec2", "vpc", "lambda", "rds", "dynamodb", "sqs", "sns", "s3", "apigateway", "eventbridge",
            "iam", "kms", "secretsmanager", "ssm", "stepfunctions", "logs", "elbv2", "cloudwatch"}


def classify(path: str, resolved: tuple = ("", "")) -> tuple:
    """(provider, service) for a request: console /api/... routes by their path, the rest as
    resolved from the wire protocol (X-Amz-Target / SigV4 scope / ARM / GCP paths)."""
    segs = [s for s in path.split("/") if s]
    if len(segs) >= 3 and segs[0] == "api" and segs[1] in ("aws", "gcp", "azure"):
        return segs[1], segs[2].lower()
    if len(segs) >= 2 and segs[0] == "api" and segs[1].lower() in _AWS_API:
        return "aws", segs[1].lower()
    return resolved if resolved and resolved[0] and resolved[1] else ("", "")


def clear() -> None:
    with _LOCK:
        _BUF.clear()


def _pct(vals: list, q: float) -> float:
    if not vals:
        return 0.0
    vals = sorted(vals)
    return round(vals[min(len(vals) - 1, int(q * len(vals)))], 2)


def series(provider: str = "", service: str = "", resource: str = "",
           minutes: int = 60, step: int = 60, now: float | None = None) -> dict:
    minutes = max(1, min(int(minutes), 1440))
    step = max(10, min(int(step), 3600))
    now = now if now is not None else time.time()
    n = max(1, (minutes * 60) // step)
    end = int(now // step) * step + step            # exclusive end of the current bucket
    start = end - n * step
    res = (resource or "").lower()
    buckets = [{"t": start + i * step, "requests": 0, "errors": 0, "_lat": []} for i in range(n)]
    with _LOCK:
        rows = list(_BUF)
    for ts, prov, svc, method, path, status, lat, segs in rows:
        if ts < start or ts >= end:
            continue
        if provider and prov != provider:
            continue
        if service and svc != service:
            continue
        if res and res not in segs:
            continue
        b = buckets[int((ts - start) // step)]
        b["requests"] += 1
        if status >= 400:
            b["errors"] += 1
        b["_lat"].append(lat)
    points = []
    for b in buckets:
        lat = b.pop("_lat")
        b["latency_p50"] = _pct(lat, 0.5)
        b["latency_p95"] = _pct(lat, 0.95)
        points.append(b)
    return {"provider": provider, "service": service, "resource": resource, "minutes": minutes,
            "step": step, "points": points,
            "total_requests": sum(p["requests"] for p in points),
            "total_errors": sum(p["errors"] for p in points)}
