"""Failure injection for the failure labs: make the next N calls to an operation fail the way the real service does."""
import json

from botocore.awsrequest import AWSResponse


class _Raw:
    def __init__(self, body):
        self._b = body

    def stream(self, *a, **k):
        yield self._b

    def read(self, *a, **k):
        return self._b


def inject(client, operation, times, status=429, code="ThrottlingException", message="Too many requests"):
    """Fail the next `times` calls of `operation` (e.g. "Converse") on `client`. Returns a counter dict {'left','seen'}; call .remove() to stop."""
    service = client.meta.service_model.endpoint_prefix
    event = "before-send.%s.%s" % (client.meta.service_model.service_id.hyphenize(), operation)
    state = {"left": times, "seen": 0}

    def handler(request, **kw):
        state["seen"] += 1
        if state["left"] > 0:
            state["left"] -= 1
            body = json.dumps({"__type": code, "message": message}).encode()
            return AWSResponse(request.url, status, {"x-amzn-ErrorType": code, "content-type": "application/json"}, _Raw(body))

    client.meta.events.register(event, handler)
    state["remove"] = lambda: client.meta.events.unregister(event, handler)
    return state
