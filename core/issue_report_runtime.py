"""Appliance-side wiring for automatic issue reporting (offline + sandboxes).

* ``IssueReportMiddleware`` — pure ASGI tap: a 5xx response or an unhandled
  exception is scrubbed and reported; the response itself is never altered.
* ``get_reporter()`` — process-wide ``IssueReporter`` whose consent mode lives in
  ``STATE["issue_reporting"]`` (synced from the portal account on licence refresh).
* ``routes/issue_reporting.py`` exposes the settings + console-error intake.

Reports go to the portal (``POST /api/issues/report``, licence as bearer). The
portal files them under the user's GitHub App token (mode ``named``) or the Vyomi
bot (mode ``anonymous``). ``VYOMI_NO_TELEMETRY=1`` disables everything.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Optional

from . import issue_report as ir

_REPORTER: Optional[ir.IssueReporter] = None
_LOCK = threading.Lock()
_BODY_PEEK = 4096


def surface() -> str:
    s = (os.environ.get("VYOMI_SURFACE") or "").strip().lower()
    if s in ir.SURFACES:
        return s
    return "sandbox" if (os.environ.get("CODESPACES") or os.environ.get("VYOMI_SANDBOX")) else "offline"


def _backend_url() -> str:
    from . import install_registration as reg
    return os.environ.get("VYOMI_ISSUE_REPORT_URL") or reg.DEFAULT_BACKEND_URL


def _version() -> str:
    try:
        from . import install_registration as reg
        return reg._read_version()
    except Exception:
        return ""


def get_reporter() -> ir.IssueReporter:
    global _REPORTER
    with _LOCK:
        if _REPORTER is None:
            from . import app_context as ctx
            settings = ctx.STATE.setdefault("issue_reporting", {})

            def tier() -> str:
                return str((ctx.STATE.get("license") or {}).get("tier") or "free")

            _REPORTER = ir.IssueReporter(
                ir.http_sender(_backend_url(), lambda: ctx.STATE.get("license_jwt", "")),
                surface=surface(), version=_version(), tier_fn=tier, settings=settings,
                persist=lambda _s: ctx.persist_state())
        return _REPORTER


def reset_reporter(reporter: Optional[ir.IssueReporter] = None) -> None:
    """Test seam: install (or clear) the process reporter."""
    global _REPORTER
    with _LOCK:
        _REPORTER = reporter


def apply_account_mode(state: dict, mode: Optional[str]) -> None:
    """Licence refresh carries the portal account's choice; mirror it locally."""
    if mode in ir.MODES:
        state.setdefault("issue_reporting", {})["mode"] = mode


def _code_message(body: bytes) -> tuple:
    try:
        d = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return "", body[:200].decode("utf-8", "replace")
    if isinstance(d, dict):
        err = d.get("error") if isinstance(d.get("error"), dict) else {}
        code = d.get("code") or d.get("__type") or d.get("Code") or err.get("code") or err.get("Code") or ""
        msg = d.get("detail") or d.get("message") or d.get("Message") or err.get("message") or ""
        return str(code).split("#")[-1], msg if isinstance(msg, str) else json.dumps(msg)[:200]
    return "", ""


class IssueReportMiddleware:
    def __init__(self, app, reporter_fn=get_reporter):
        self.app = app
        self._reporter_fn = reporter_fn

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or ir.telemetry_disabled() \
                or scope["path"].startswith("/api/issue-reporting"):
            return await self.app(scope, receive, send)
        state = {"status": None, "body": b""}

        async def tap(msg):
            if msg["type"] == "http.response.start":
                state["status"] = msg["status"]
            elif msg["type"] == "http.response.body" and (state["status"] or 0) >= 500 \
                    and len(state["body"]) < _BODY_PEEK:
                state["body"] += msg.get("body", b"")[:_BODY_PEEK]
            await send(msg)

        try:
            await self.app(scope, receive, tap)
        except Exception as exc:  # unhandled -> report, then let the server answer 500
            self._report(scope, 500, "", f"{type(exc).__name__}: {exc}",
                         ir.frames_from_traceback(exc.__traceback__), "exception")
            raise
        if (state["status"] or 0) >= 500:
            code, msg = _code_message(state["body"])
            self._report(scope, state["status"], code, msg, [], "http")

    def _report(self, scope, status, code, message, frames, kind):
        try:
            headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
            cloud, service, action = ir.derive_route(
                scope.get("method", "GET"), scope.get("path", "/"), headers,
                (scope.get("query_string") or b"").decode("latin-1"))
            self._reporter_fn().report(cloud=cloud, service=service, action=action, status=status,
                                       code=code, message=message, frames=frames, kind=kind)
        except Exception:
            pass  # reporting must never break a request


def push_mode_to_portal(mode: str) -> dict:
    """Best effort: the portal account owns the choice, so tell it (licence as bearer).
    Returns {"authorize_url": <absolute portal URL>} when the user still has to authorise the
    Vyomi GitHub App for named reports; {} otherwise or when offline / opted out."""
    if ir.telemetry_disabled():
        return {}
    import urllib.request
    from . import app_context as ctx
    tok = ctx.STATE.get("license_jwt", "")
    if not tok:
        return {}
    base = _backend_url().rstrip("/")
    req = urllib.request.Request(base + "/api/issues/settings", data=json.dumps({"mode": mode}).encode(),
                                 method="PUT", headers={"Content-Type": "application/json",
                                                        "Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            d = json.loads(r.read() or b"{}")
    except Exception:
        return {}
    return {"authorize_url": base + d["authorize_url"]} if d.get("authorize_url") else {}
