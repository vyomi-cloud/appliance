"""Amazon SES v2 — native REST-JSON wire (`/v2/email/*`) and the console REST
(`/api/aws/sesv2/*`), both on the shared engine in core/sesv2_core.py.

State is space-scoped (`ctx.sesv2_state`), so identities, templates and the sent
mailbox follow the active space, show up in its cost-savings metrics and survive
restarts with it. SendEmail really delivers: to Mailpit (the local inbox) over SMTP, optionally
also to the user's own SMTP relay; the SES SMTP interface (:2587) and the inbound listener
(:2525) live in core/ses_mail.py.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from core import app_context as ctx
from core import sesv2_core as ses
from core.ses_mail import SesMail


class SpaceSesV2Store(ses.SesV2Store):
    """SesV2Store whose dicts live in the active space's service state."""

    _KEYS = ("identities", "config_sets", "templates", "contact_lists", "suppression", "ip_pools", "tenants", "tags",
             "smtp_credentials", "receipt", "mail_settings")

    def __init__(self) -> None:
        self.account_id = ctx.AWS_ACCOUNT_ID
        self.region = "us-east-1"

    def _s(self) -> dict:
        return ctx.sesv2_state

    @property
    def messages(self):
        return self._s().setdefault("messages", [])

    @messages.setter
    def messages(self, v):
        self._s()["messages"] = v

    @property
    def account(self):
        a = self._s().setdefault("account", {})
        for k, v in ses.ACCOUNT_DEFAULTS.items():
            a.setdefault(k, v)
        return a

    def persist(self) -> None:
        ctx.persist_state()
        # Activity log + space cost-savings refresh (same hook SQS/RDS use).
        ctx.record_usage("sesv2.change", {"resource_id": "sesv2", "name": "sesv2"})


def _prop(key):
    return property(lambda self: self._s().setdefault(key, {}))


for _k in SpaceSesV2Store._KEYS:
    setattr(SpaceSesV2Store, _k, _prop(_k))

STORE = SpaceSesV2Store()
MAIL = SesMail(STORE)
STORE.mailer = MAIL


def _query(request: Request) -> dict:
    q: dict[str, Any] = {}
    for k, v in request.query_params.multi_items():
        if k in q:
            q[k] = (q[k] if isinstance(q[k], list) else [q[k]]) + [v]
        else:
            q[k] = v
    return q


def register(app: FastAPI) -> None:
    app.on_event("startup")(MAIL.start)   # SES SMTP interface (:2587) + inbound listener (:2525) + IMAP poll

    # Console REST (flat view used by the web console + Playwright tests).
    @app.api_route("/api/aws/sesv2/{rest:path}", methods=["GET", "POST", "DELETE"], include_in_schema=False)
    async def sesv2_console(rest: str, request: Request) -> JSONResponse:
        body: dict = {}
        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:
                body = {}
        status, out = ses.console_dispatch(STORE, request.method, "/api/aws/sesv2/" + rest, _query(request), body)
        if status >= 400:
            return JSONResponse({"detail": f"{out.get('code', 'Error')}: {out.get('error', '')}"}, status_code=status)
        return JSONResponse(out)

    # Native wire: aws sesv2 / SDK clients (endpoint override only).
    @app.api_route("/v2/email", methods=["GET", "POST", "DELETE", "PUT"], include_in_schema=False)
    @app.api_route("/v2/email/{rest:path}", methods=["GET", "POST", "DELETE", "PUT"], include_in_schema=False)
    async def sesv2_wire(request: Request, rest: str = "") -> Response:
        body = await request.body()
        r = ses.dispatch(STORE, request.method, request.url.path, _query(request), dict(request.headers), body)
        return Response(content=r.body, status_code=r.status, headers=dict(r.headers), media_type=r.media_type)
