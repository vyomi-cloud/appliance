"""Console conformance signal (F5 seam) — the honest gate behind the console-next
rich-widget rendering (§14.5) and the status-bar conformance pill.

The console gates each service's RICH data-plane widget on this signal: a service
renders its rich widget only when its conformance mode is `full`; otherwise the UI
falls back to the generic-control-plane view. This module is the single source of
that per-service signal.

TODAY (P1a) this is a curated, deterministic map keyed off the KNOWN conformance
state of each service's core (the conformance suite in tests/conformance/*). It is
deliberately shaped like the eventual live source so F5 can swap the backing data
without touching the UI or the manifest contract:

    { service_id: {
        "mode":   "full" | "degraded" | "generic",   # gates the rich widget
        "status": "conformant" | "partial" | "unknown",
        "checks": {"passed": int, "total": int},      # from the suite (stubbed)
        "note":   "...",                              # human one-liner
    } }

`mode` vs `status`:
  - `mode` drives WHICH widget renders (the capability gate).
  - `status` drives the pill colour/label (a coarser rollup for the status bar).

When the live conformance runner lands (F5), replace `_SIGNAL` with a reader over
the suite's latest results; the shape and the two public functions stay stable.

Substrate note: this is the LOCAL/FastAPI substrate's view. Nano emits the same
shape from its own runner; the UI is identical either way (§15.1 #5).
"""

from __future__ import annotations

import os

# Curated per-service signal. Numbers reflect the conformance-suite check counts
# recorded for each core (see tests/conformance/* and the project conformance
# notes); they are a stub for the live F5 feed, not a live count.
_SIGNAL = {
    "s3": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 41, "total": 41},
        "note": "S3 object store — real MinIO; object-browser is conformance-gated green.",
    },
    "dynamodb": {
        # backend conformant AND the nosql-item-viewer widget now ships — the rich
        # data-plane view (list tables / browse+get/put items / key query) is wired
        # in center-canvas, so gate to "full".
        "mode": "full", "status": "conformant",
        "checks": {"passed": 45, "total": 45},
        "note": "DynamoDB core conformant; nosql-item-viewer widget is conformance-gated green.",
    },
    "rds": {
        "mode": "full", "status": "conformant",
        "checks": {"passed": 29, "total": 29},
        "note": "RDS Data API (ExecuteStatement) — relay-safe SQL over HTTP; real SQL engine.",
    },
    "sqs": {
        # backend conformant AND the queue-topic-viewer widget now ships — the rich
        # data-plane view (list queues+topics / send+peek+receive / SNS→SQS subscribe
        # + publish fan-out) is wired in center-canvas, so gate to "full".
        "mode": "full", "status": "conformant",
        "checks": {"passed": 32, "total": 32},
        "note": "SQS+SNS core conformant; queue-topic-viewer widget is conformance-gated green.",
    },
    "iam": {
        "mode": "generic", "status": "partial",
        "checks": {"passed": 20, "total": 28},
        "note": "IAM — control-plane + policy simulator; rich generic-control-plane view.",
    },
}

# The status precedence for the coarse status-bar rollup pill.
_STATUS_RANK = {"conformant": 0, "partial": 1, "unknown": 2}


def service_signal(service_id: str) -> dict:
    """Per-service conformance signal (see module docstring for the shape). Unknown
    services degrade honestly to a `generic`/`unknown` signal — never a false green."""
    sig = _SIGNAL.get(service_id)
    if sig:
        return dict(sig)
    return {
        "mode": "generic", "status": "unknown",
        "checks": {"passed": 0, "total": 0},
        "note": "No conformance signal for this service — generic control-plane only.",
    }


def all_signals() -> dict:
    """The full per-service signal map (service_id -> signal)."""
    return {sid: dict(sig) for sid, sig in _SIGNAL.items()}


def rollup() -> dict:
    """A coarse workspace-level rollup for the status-bar pill: the WORST status
    across all services + a passed/total sum. Deterministic and offline."""
    worst = "conformant"
    passed = total = 0
    for sig in _SIGNAL.values():
        st = sig.get("status", "unknown")
        if _STATUS_RANK.get(st, 2) > _STATUS_RANK.get(worst, 2):
            worst = st
        c = sig.get("checks", {})
        passed += int(c.get("passed", 0))
        total += int(c.get("total", 0))
    label = {"conformant": "conformant", "partial": "partial", "unknown": "unknown"}[worst]
    return {
        "status": worst,
        "label": label,
        "checks": {"passed": passed, "total": total},
        "services": len(_SIGNAL),
    }


def widget_modes() -> dict:
    """Map service_id -> widget `mode` (`full`/`degraded`/`generic`). This is what
    the capability manifest merges into `widgets` so the center-canvas gates on it.

    A per-widget override via env lets a demo force-degrade a service without code
    edits (e.g. VYOMI_CONSOLE_DEGRADE="rds,sqs")."""
    degraded = {
        s.strip() for s in os.environ.get("VYOMI_CONSOLE_DEGRADE", "").split(",") if s.strip()
    }
    out = {}
    for sid, sig in _SIGNAL.items():
        out[sid] = "degraded" if sid in degraded else sig.get("mode", "generic")
    return out
