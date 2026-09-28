"""Nano (Pyodide) adapter for the console-next SPA's capability manifest.

SLICE 1 SCOPE: serve **GET /api/console/capabilities** in-browser, using the SAME
manifest-building logic as the appliance's FastAPI route
(routes/console_next.py::_capabilities) — vendored into wasm/console_next_manifest.py
so it runs in Pyodide with NO FastAPI import (§15 commonality: one manifest, two
substrates). On Nano we force substrate="nano", which the manifest already handles
(connect.mode=relay, features.relay=true, features.ssh=false, compute-terminal→
"degraded", serverless-invoke→"partial") — as capability DATA, never forked UI.

The other /api/console/* endpoints (the facade DATA plane: /api/console/gcs/*,
/api/console/azure-blob/*, and the AWS-lens data paths the widgets read) are NOT
served here yet.

# TODO slice 2: dispatch the console facade data endpoints
#   (/api/console/gcs/*, /api/console/azure-blob/*, and the shared /api/s3, /api/dynamodb,
#    /api/rds, /api/sqs, /api/aws/secrets, /api/aws/kms, /api/lambda, /api/iam paths the
#    console-next widgets read) to the proven cores in Pyodide — the in-browser analogue
#    of the appliance's console_<svc> facades. Until then the SW returns a clear 501 stub
#    for every /api/console/* path other than /capabilities so the SPA loads without
#    crashing.

This module has NO import-time dependency on the WASM `Backends` (the manifest is
static/pure), so nano-boot can call it directly for the capabilities tuple.
"""
from __future__ import annotations

# Vendored pure manifest builder (see wasm/console_next_manifest.py). It imports
# `from core import console_conformance` lazily inside _capabilities(); in Pyodide
# the vendored core lives under /core, so that resolves without FastAPI.
try:
    from .. import console_next_manifest as _manifest  # package import (wasm.*)
except Exception:  # pragma: no cover — flat layout fallback
    import console_next_manifest as _manifest  # type: ignore


def capabilities(lens: str = "aws", substrate: str | None = None) -> dict:
    """GET /api/console/capabilities?lens=&substrate= for the Nano substrate.

    On Nano we ALWAYS resolve substrate to "nano" (the browser tab IS the nano
    substrate) — ignoring any inbound ?substrate= so the SPA can't be tricked into
    declaring a substrate it isn't. lens is honoured (aws|gcp|azure); an unknown
    lens falls back to aws inside the manifest builder.
    """
    return _manifest._capabilities(lens=(lens or "aws"), substrate="nano")


def handle(op: str, params: dict | None = None) -> dict:
    """Dispatch entry used by nano-boot's `_console` provider hook.

    op == "capabilities" → the manifest. Every other console op is a slice-2 facade
    data endpoint; we return a clear 501-shaped stub the SW forwards verbatim so the
    SPA renders (empty/degraded) instead of crashing.
    """
    params = params or {}
    if op == "capabilities":
        return capabilities(lens=params.get("lens") or "aws",
                            substrate=params.get("substrate"))
    # TODO slice 2: dispatch <op>/<path> to the console_<svc> facade in Pyodide.
    return {
        "ok": False,
        "code": "NotImplementedYet",
        "detail": "console-next facade data plane is slice 2 (not yet wired in Nano)",
        "op": op,
        "params": params,
        "__status": 501,
    }
