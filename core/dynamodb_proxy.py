"""Transparent proxy to amazon/dynamodb-local.

boto3's DynamoDB client uses ``X-Amz-Target: DynamoDB_20120810.<Op>`` + a JSON
body. DynamoDB Local speaks the identical wire protocol, so this is a literal
pass-through — we forward the request bytes + the X-Amz-Target header.

Replaces the in-memory ``provider_aws_services._ddb_api_aws`` for ALL boto3
traffic. Falls back to a 502 if DDB Local is unreachable (the simulator never
hangs; it surfaces the backend down).
"""
from __future__ import annotations

import json
import os
from typing import Any

try:
    import urllib.request
    import urllib.error
except ImportError:
    urllib = None  # type: ignore[assignment]


_DDB_URL = os.environ.get("CLOUDLEARN_DYNAMODB_URL", "http://cloudlearn-dynamodb:8000")


def available() -> bool:
    """Best-effort: do a ListTables and see if we get a 200."""
    try:
        req = urllib.request.Request(
            _DDB_URL,
            data=b"{}",
            method="POST",
            headers={
                "X-Amz-Target": "DynamoDB_20120810.ListTables",
                "Content-Type": "application/x-amz-json-1.0",
                "Authorization": "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request",
            },
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


# DynamoDB Local rejects TagResource/UntagResource/ListTagsOfResource ("Tagging is
# not currently supported"), real DynamoDB supports them: keep tags per table ARN here.
_TAGS: dict[str, dict[str, str]] = {}


def _tagging(op: str, body: bytes) -> bytes | None:
    if op not in ("TagResource", "UntagResource", "ListTagsOfResource"):
        return None
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        payload = {}
    tags = _TAGS.setdefault(str(payload.get("ResourceArn", "")), {})
    if op == "TagResource":
        tags.update({str(t.get("Key", "")): str(t.get("Value", "")) for t in payload.get("Tags") or []})
        return b"{}"
    if op == "UntagResource":
        for k in payload.get("TagKeys") or []:
            tags.pop(str(k), None)
        return b"{}"
    return json.dumps({"Tags": [{"Key": k, "Value": v} for k, v in tags.items()]}).encode()


async def proxy(request: Any) -> tuple[int, bytes, str]:
    """Forward the request body + X-Amz-Target to DDB Local. Returns (status,
    body, content_type)."""
    body = await request.body()
    target = request.headers.get("x-amz-target", "DynamoDB_20120810.ListTables")
    content_type = request.headers.get("content-type", "application/x-amz-json-1.0")
    tagged = _tagging(target.rsplit(".", 1)[-1], body)
    if tagged is not None:
        return 200, tagged, content_type
    try:
        req = urllib.request.Request(
            _DDB_URL,
            data=body,
            method="POST",
            headers={
                "X-Amz-Target": target,
                "Content-Type": content_type,
                # DDB Local requires SOME auth header even though it doesn't
                # verify; just pass through whatever the client sent.
                "Authorization": request.headers.get("authorization", "AWS4-HMAC-SHA256 Credential=test/20260531/us-east-1/dynamodb/aws4_request"),
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers.get("Content-Type", content_type)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", content_type)
    except Exception as e:
        err = json.dumps({"__type": "InternalServerError", "message": f"dynamodb-local unreachable: {e!r}"}).encode()
        return 502, err, "application/x-amz-json-1.0"
