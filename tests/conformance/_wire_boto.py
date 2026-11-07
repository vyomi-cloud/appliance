"""Shared harness: a real boto3 client whose HTTP transport is the Nano/offline AwsWireRouter
(no sockets). Same request bytes the SDK/CLI would send, answered by the same router code."""
from urllib.parse import urlsplit, parse_qsl

import boto3
from botocore.awsrequest import AWSResponse
from botocore.config import Config

from core.aws_wire_router import AwsWireRouter


class _Raw:
    def __init__(self, b):
        self._b = b

    def stream(self, *a, **k):
        yield self._b

    def read(self, *a, **k):
        return self._b


def make_clients(router=None):
    router = router or AwsWireRouter()

    def send(request, **_kw):
        u = urlsplit(request.url)
        q = dict(parse_qsl(u.query, keep_blank_values=True))
        body = request.body
        if body is None:
            body = b""
        elif isinstance(body, str):
            body = body.encode()
        elif not isinstance(body, (bytes, bytearray)):
            body = body.read()
        h = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in request.headers.items()}
        h["host"] = u.netloc
        path = u.path + (("?" + u.query) if u.query else "")
        out = router.handle(request.method, path, q, h, bytes(body))
        resp = AWSResponse(request.url, out["status"], {k: str(v) for k, v in (out.get("headers") or {}).items()},
                           _Raw(out["body"] if isinstance(out["body"], bytes) else str(out["body"]).encode()))
        resp._content = out["body"] if isinstance(out["body"], bytes) else str(out["body"]).encode()
        return resp

    def client(name, **kw):
        c = boto3.client(name, region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test",
                         endpoint_url="http://localhost:1", config=Config(retries={"max_attempts": 0}), **kw)
        c.meta.events.register("before-send.*.*", send)
        return c
    return router, client
