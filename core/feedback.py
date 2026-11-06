"""POST /api/feedback — the console's "Share feedback" box on the offline appliance / booster.

Notes are appended to <state dir>/feedback.jsonl (one JSON per line); nothing leaves the machine from here. Size-limited, rate-limited,
and only the fields the widget sends are kept."""
from __future__ import annotations

import json
import os
import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse

_LOCK = threading.Lock()
_HITS: dict[str, list[float]] = {}
MAX_TEXT = 2000
FIELDS = ("cloud", "substrate", "page", "ua")


def _path() -> str:
    d = os.environ.get("CLOUDLEARN_STATE_DIR", "/data")
    if not os.path.isdir(d):
        d = "."
    return os.path.join(d, "feedback.jsonl")


def _limited(key: str, limit: int = 10, window: float = 600.0) -> bool:
    now = time.time()
    with _LOCK:
        h = [t for t in _HITS.get(key, []) if now - t < window]
        h.append(now)
        _HITS[key] = h
        return len(h) > limit


def record(body: dict, client: str = "") -> dict:
    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise ValueError("text_required")
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "text": text[:MAX_TEXT]}
    for k in FIELDS:
        v = (body or {}).get(k)
        if isinstance(v, str):
            rec[k] = v[:200]
    try:
        rec["version"] = open(os.path.join(os.path.dirname(__file__), "..", "VERSION")).read().strip()
    except Exception:
        pass
    with _LOCK:
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    return rec


def register(app) -> None:
    @app.post("/api/feedback", include_in_schema=False)
    async def _feedback(request: Request):
        client = request.client.host if request.client else ""
        if _limited(client):
            return JSONResponse({"error": "rate_limited"}, status_code=429)
        try:
            body = await request.json()
        except Exception:
            body = {}
        try:
            record(body if isinstance(body, dict) else {}, client)
        except ValueError:
            return JSONResponse({"error": "text_required"}, status_code=400)
        return JSONResponse({"ok": True})
