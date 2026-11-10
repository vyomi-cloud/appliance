"""Amazon SNS — native Query-protocol wire (root `Action=…` requests signed for `sns`)
and the console REST (`/api/aws/sns/*`), both on the shared engine in core/sns_core.py.

State is space-scoped (`ctx.sns_state`): topics, subscriptions, platform applications and
the delivery log follow the active space, show up in its cost-savings metrics and
survive restarts with it. SQS subscriptions fan out into the appliance's own SQS queues.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from core import app_context as ctx
from core import sns_core as sns
from core import sns_delivery
from core.messaging_store import MessagingStore


def _srv():
    import server as _s
    return _s


class SpaceSnsStore(MessagingStore):
    """MessagingStore whose topics + SNS state live in the active space."""

    def __init__(self) -> None:
        self.account_id = ctx.AWS_ACCOUNT_ID
        self._clock = None

    @property
    def topics(self):
        return ctx.sns_state.setdefault("topics", {})

    @topics.setter
    def topics(self, v):
        ctx.sns_state["topics"] = v

    @property
    def sns(self):
        return ctx.sns_state.setdefault("extra", {})

    @sns.setter
    def sns(self, v):
        ctx.sns_state["extra"] = v

    @property
    def queues(self):
        return {}

    def deliver_sqs(self, endpoint_arn, body, attrs, group, dedup) -> bool:
        """Fan an SNS notification into one of the appliance's SQS queues."""
        s = _srv()
        queue = next((q for q in s._sqs_list_queues() if q.get("queue_arn") == endpoint_arn
                      or s._sqs_queue_arn(q.get("queue_name", "")) == endpoint_arn), None)
        if queue is None:
            return False
        s._sqs_enqueue_message(queue, body, None, {}, group or "", dedup or "", source="sns")
        return True

    def enqueue_delivery(self, job: dict) -> bool:
        """Push deliveries (HTTP/S, Lambda, email) go to the JetStream-backed workers."""
        return DELIVERY.enqueue(job)

    def persist(self) -> None:
        ctx.persist_state()
        ctx.record_usage("sns.change", {"resource_id": "sns", "name": "sns"})


STORE = SpaceSnsStore()


def _invoke_lambda(function_name: str, event: dict):
    return _srv()._lambda_invoke_function(function_name, event, invocation_type="Event", source="sns")


DELIVERY = sns_delivery.Delivery(
    STORE, base_url=lambda: os.environ.get("VYOMI_PUBLIC_URL", "http://localhost:9000"),
    invoke_lambda=_invoke_lambda, deliver_sqs=STORE.deliver_sqs)


async def sns_query(request: Request) -> Response:
    """Root-dispatched native SNS request (SDK / `aws sns`)."""
    params = await _srv()._ec2_query_params(request)
    r = sns.dispatch(STORE, params)
    return Response(content=r.body, status_code=r.status, headers=dict(r.headers), media_type=r.media_type)


def register(app: FastAPI) -> None:
    @app.on_event("startup")
    async def _sns_delivery_start() -> None:
        DELIVERY.start()      # resumes the durable per-subscription consumers after a restart

    @app.get("/SimpleNotificationService-vyomi.pem", include_in_schema=False)
    async def sns_signing_cert() -> Response:
        return Response(content=sns_delivery.signing_cert_pem(), media_type="application/x-pem-file")

    @app.api_route("/api/aws/sns/{rest:path}", methods=["GET", "POST", "DELETE", "PATCH"], include_in_schema=False)
    async def sns_console(rest: str, request: Request) -> JSONResponse:
        body: dict = {}
        if request.method in ("POST", "PATCH"):
            try:
                body = await request.json()
            except Exception:
                body = {}
        status, out = sns.console_dispatch(STORE, request.method, "/api/aws/sns/" + rest,
                                           dict(request.query_params), body)
        if status >= 400:
            return JSONResponse({"detail": f"{out.get('code', 'Error')}: {out.get('error', '')}"}, status_code=status)
        return JSONResponse(out)
