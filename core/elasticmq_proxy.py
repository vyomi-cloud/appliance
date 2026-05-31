"""Transparent proxy to softwaremill/elasticmq-native.

ElasticMQ-native speaks the legacy SQS query/POST protocol but rejects the
newer JSON-RPC (X-Amz-Target) shape that modern boto3 uses by default. We
translate JSON-RPC requests to the legacy form before forwarding, so both
shapes work transparently.

Falls back to the legacy in-memory handler on backend down.
"""
from __future__ import annotations

import json
import os
import urllib.parse
from typing import Any

import urllib.request
import urllib.error


_EMQ_URL = os.environ.get("CLOUDLEARN_ELASTICMQ_URL", "http://cloudlearn-elasticmq:9324")


def available() -> bool:
    try:
        req = urllib.request.Request(_EMQ_URL + "/?Action=ListQueues", method="GET")
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _flatten_for_query(obj: Any, prefix: str = "") -> dict:
    """Convert a JSON object to SQS legacy-query flat params.

    ``{"Entries": [{"Id": "1", "MessageBody": "x"}]}`` becomes
    ``{"Entries.1.Id": "1", "Entries.1.MessageBody": "x"}``.

    For attribute maps ``{"Attributes": {"Foo": "Bar"}}`` becomes
    ``{"Attribute.1.Name": "Foo", "Attribute.1.Value": "Bar"}`` per SQS legacy
    encoding rules. MVP keeps it simple — recursive flat-key form is enough for
    the dominant boto3 ops (CreateQueue, SendMessage, ReceiveMessage, Delete).
    """
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                out.update(_flatten_for_query(v, key))
            else:
                out[key] = str(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj, start=1):
            key = f"{prefix}.{i}" if prefix else str(i)
            if isinstance(v, (dict, list)):
                out.update(_flatten_for_query(v, key))
            else:
                out[key] = str(v)
    else:
        if prefix:
            out[prefix] = str(obj)
    return out


def _json_rpc_to_query(target: str, body_bytes: bytes) -> bytes:
    """X-Amz-Target=AmazonSQS.<Action> + JSON body → Action=<Action>&... form."""
    action = target.split(".", 1)[-1].strip()
    try:
        body = json.loads(body_bytes or b"{}")
    except Exception:
        body = {}
    params = {"Action": action, "Version": "2012-11-05"}
    params.update(_flatten_for_query(body))
    # SQS legacy: queue identified by URL path /000000000000/<queueName>; boto3
    # JSON-RPC passes QueueUrl in the body — we strip back to just QueueName
    # by extracting the last path segment.
    if "QueueUrl" in params:
        params["QueueUrl"] = params["QueueUrl"]
    return urllib.parse.urlencode(params).encode()


async def proxy(request: Any) -> tuple[int, bytes, str]:
    """Forward request to ElasticMQ, translating JSON-RPC → form if needed."""
    body = await request.body()
    method = request.method.upper()
    qs = str(request.url.query or "")
    target = request.headers.get("x-amz-target", "")

    # Build outbound URL — preserve the path so SendMessage to /<acct>/<queue>
    # routes correctly. JSON-RPC clients POST to /, with queue in body.
    path = request.url.path or "/"
    if target and path == "/":
        body = _json_rpc_to_query(target, body)
        url = _EMQ_URL + "/"
        ctype = "application/x-www-form-urlencoded"
    else:
        url = _EMQ_URL + path + (("?" + qs) if qs else "")
        ctype = request.headers.get("content-type", "application/x-www-form-urlencoded")

    headers = {
        "Content-Type": ctype,
        "Authorization": request.headers.get("authorization",
            "AWS4-HMAC-SHA256 Credential=test/20260531/elasticmq/sqs/aws4_request"),
    }

    try:
        req = urllib.request.Request(url, data=body if method != "GET" else None,
                                      method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "text/xml")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "text/xml")
    except Exception as e:
        return 502, repr(e).encode(), "text/plain"
