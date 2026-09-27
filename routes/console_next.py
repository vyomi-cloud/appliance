"""console-next (P0) — the fidelity-first console redesign vertical.

Additive routes for the new Lit-based console engine. Coexists with the existing
static/*-console.html consoles; touches none of them.

Endpoints added here:
  GET  /api/console/capabilities        — the capability manifest (§15.1). The UI
                                           reads it and gates on it — NO substrate/
                                           cloud branching in components (§15.2).
  GET  /api/console/calls               — one-shot ring-buffer snapshot (newest-first)
  GET  /api/console/calls/stream        — SSE stream of captured calls (§12.3)
  POST /api/console/calls/clear         — clear the ring buffer (dev convenience)
  GET  /console-next[/...]              — the SPA shell (index.html)

Static assets for the SPA are served from the /console-next-assets mount so that
asset refs are base-path-relative and the same bundle can be served under a subpath
(Nano's /nano/ scope) — §15.1 guarantee #6.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

_HERE = os.path.dirname(__file__)
_ASSETS_DIR = os.path.join(_HERE, "..", "static", "console-next")
_INDEX = os.path.join(_ASSETS_DIR, "index.html")


def _capabilities() -> dict:
    """Return the runtime capability manifest for THIS substrate (§15.1).

    On the local FastAPI substrate S3 is backed by real MinIO, so object-browser is
    "full"; there is a real endpoint (not a relay); SSH exists on real compute. The
    other widgets are declared per their conformance/backing status. The UI degrades
    purely from these flags — it never checks the substrate name.
    """
    substrate = os.environ.get("VYOMI_SUBSTRATE", "local")  # local | codespaces | nano
    connect_mode = os.environ.get("VYOMI_CONNECT_MODE", "endpoint")  # endpoint | ssh | relay

    return {
        "substrate": substrate,
        "cloud_lenses": ["aws"],  # lenses with a rich data-plane in this P0 vertical
        "widgets": {
            "object-browser": "full",       # S3 → real MinIO (wired in P0)
            "sql-console": "generic",       # RDS widget lands in P1
            "compute-terminal": "generic",  # EC2 widget lands in P1
            "serverless-invoke": "generic",
            "nosql-item-viewer": "generic",
            "kv-secret-viewer": "generic",
            "kms-crypto-view": "generic",
            "queue-topic-viewer": "generic",
            "generic-control-plane": "full",
        },
        "features": {
            "glassbox": True,      # Calls tab is live in P0
            "snapshot": False,     # P2
            "fork": False,         # P2
            "replay": False,       # P2
            "relay": substrate == "nano",
            "ssh": substrate == "local" and connect_mode == "ssh",
        },
        "connect": {"mode": connect_mode},
        # The service rail is generated from this catalog — the shell renders only
        # these services, each mapped to a widget the manifest above gates.
        "services": [
            {"id": "s3", "label": "S3", "icon": "▤", "widget": "object-browser",
             "terminology": "bucket", "backed_by": "MinIO"},
            {"id": "dynamodb", "label": "DynamoDB", "icon": "⊞", "widget": "nosql-item-viewer",
             "terminology": "table", "backed_by": "DynamoDB-Local"},
            {"id": "rds", "label": "RDS", "icon": "◫", "widget": "sql-console",
             "terminology": "db instance", "backed_by": "MySQL/Postgres"},
            {"id": "iam", "label": "IAM", "icon": "⚿", "widget": "generic-control-plane",
             "terminology": "policy", "backed_by": "in-proc"},
        ],
        "workspace": {
            "name": os.environ.get("VYOMI_WORKSPACE_NAME", "vyomi-dev-01"),
            "endpoint": os.environ.get("VYOMI_S3_ENDPOINT", ""),
        },
        "glassbox": {
            "event_schema_version": 1,
            "ring_max": int(os.environ.get("VYOMI_GLASSBOX_RING", "500") or "500"),
        },
    }


def register(app: FastAPI) -> None:
    # ── Static assets for the SPA ──
    if os.path.isdir(_ASSETS_DIR):
        app.mount("/console-next-assets",
                  StaticFiles(directory=_ASSETS_DIR),
                  name="console-next-assets")

    # ── Capability manifest (§15.1) ──
    @app.get("/api/console/capabilities", include_in_schema=False)
    def api_console_capabilities():
        return JSONResponse(_capabilities())

    # ── Glass-box: one-shot buffer snapshot ──
    @app.get("/api/console/calls", include_in_schema=False)
    def api_console_calls(limit: int = Query(default=200, ge=1, le=2000)):
        from core.glassbox import RING
        return JSONResponse({"calls": RING.snapshot(limit=limit)})

    # ── Glass-box: SSE stream (§12.3) ──
    @app.get("/api/console/calls/stream", include_in_schema=False)
    async def api_console_calls_stream(replay: int = Query(default=50, ge=0, le=500)):
        from core.glassbox import sse_stream
        return StreamingResponse(
            sse_stream(replay=replay),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.post("/api/console/calls/clear", include_in_schema=False)
    def api_console_calls_clear():
        from core.glassbox import RING
        RING.clear()
        return {"ok": True}

    # ── The SPA shell — serves index.html at /console-next and any sub-path so the
    #    client-side router can own deep-links. Asset refs inside index.html are
    #    relative to /console-next-assets/, base-path-friendly. ──
    @app.get("/console-next", include_in_schema=False)
    @app.get("/console-next/", include_in_schema=False)
    @app.get("/console-next/{path:path}", include_in_schema=False)
    def console_next_spa(path: str = ""):
        try:
            with open(_INDEX, "rb") as f:
                html = f.read().decode("utf-8")
        except FileNotFoundError:
            return HTMLResponse("<h1>console-next not built</h1>", status_code=500)
        return HTMLResponse(content=html, headers={"Cache-Control": "no-store, max-age=0"})
