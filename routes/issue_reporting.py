"""Issue-reporting settings + console error intake (offline appliance and sandboxes).

GET  /api/issue-reporting          -> {mode, consent_asked, enabled, queued}
PUT  /api/issue-reporting          -> {mode: "named" | "anonymous"}   (consent dialog / Settings)
POST /api/issue-reporting/report   -> a console-side failure (JS error, failed action); scrubbed
                                      again here before it is queued to the portal.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from core import issue_report as ir
from core import issue_report_runtime as rt


def register(app: FastAPI) -> None:
    @app.get("/api/issue-reporting")
    def get_issue_reporting():
        from core import app_context as ctx
        return {**rt.get_reporter().public_settings(), "signed_in": bool(ctx.STATE.get("license_jwt"))}

    @app.put("/api/issue-reporting")
    def put_issue_reporting(payload: dict):
        try:
            out = rt.get_reporter().set_mode(str(payload.get("mode", "")))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {**out, **rt.push_mode_to_portal(out["mode"])}

    @app.post("/api/issue-reporting/report")
    def post_issue_report(payload: dict):
        kind = payload.get("kind") if payload.get("kind") in ("console-action", "js-error") else "js-error"
        cloud = str(payload.get("cloud") or "unknown").lower()
        out = rt.get_reporter().report(
            cloud=cloud, service=str(payload.get("service") or "console"),
            action=str(payload.get("action") or kind), status=payload.get("status"),
            code=str(payload.get("code") or ""), message=str(payload.get("message") or ""),
            frames=[str(f) for f in (payload.get("frames") or [])][:20], kind=kind,
            cancelled=bool(payload.get("cancelled")))
        return {"reported": out is not None, "fingerprint": out["fingerprint"] if out else None}
