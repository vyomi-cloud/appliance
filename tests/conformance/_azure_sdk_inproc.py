"""Run the REAL Azure management SDKs (azure-mgmt-*) against the in-process wire router (no socket): a custom azure-core
transport hands each pipeline request to AwsWireRouter.handle() -- the exact code the offline relay and Nano run."""
import json
from urllib.parse import urlsplit, parse_qsl

import requests
from azure.core.credentials import AccessToken
from azure.core.pipeline.transport import HttpTransport
from azure.core.rest._requests_basic import RestRequestsTransportResponse

from core.aws_wire_router import AwsWireRouter
import core.azure_arm_core as _a

_a.AzureArm.STRICT_SUBSCRIPTION = False
SUB = "00000000-0000-0000-0000-cloudlearn01"
BASE = "https://management.azure.com"


class Cred:
    def get_token(self, *scopes, **kw):
        return AccessToken("vyomi-test-token", 4102444800)


class RouterTransport(HttpTransport):
    def __init__(self, router):
        self.router = router

    def open(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def send(self, request, **kw):
        u = urlsplit(request.url)
        q = {k: v for k, v in parse_qsl(u.query)}
        h = {k.lower(): v for k, v in request.headers.items()}
        h.setdefault("host", "management.azure.com")
        h["x-forwarded-proto"] = "https"
        body = request.body
        if body is None:
            body = b""
        elif isinstance(body, str):
            body = body.encode()
        out = self.router.handle(request.method, u.path, q, h, body)
        resp = requests.Response()
        resp.status_code = out["status"]
        resp._content = out.get("body") or b""
        resp._content_consumed = True
        import io
        resp.raw = io.BytesIO(resp._content)
        for k, v in (out.get("headers") or {}).items():
            resp.headers[k] = str(v)
        resp.headers.setdefault("content-type", "application/json")
        resp.request = requests.Request(request.method, request.url).prepare()
        resp.url = request.url
        return RestRequestsTransportResponse(request=request, internal_response=resp)


def make(client_cls, router, **kw):
    return client_cls(Cred(), SUB, base_url=BASE, transport=RouterTransport(router), credential_scopes=[BASE + "/.default"], polling_interval=0, **kw)
