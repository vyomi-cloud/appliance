"""AWS provider plugin (WASM substrate). Maps S3 + DynamoDB to the shared
generic backends. Adding more AWS services = more entries in handlers()."""
from __future__ import annotations

from .registry import CloudProvider, register
from ..backends.store import Backends


class Aws(CloudProvider):
    id = "aws"
    label = "Amazon Web Services"
    match_hosts = (".amazonaws.com",)

    def handlers(self):
        return {
            ("s3", "PutObject"):   _s3_put,
            ("s3", "GetObject"):   _s3_get,
            ("s3", "ListObjects"): _s3_list,
            ("dynamodb", "PutItem"): _ddb_put,
            ("dynamodb", "GetItem"): _ddb_get,
        }


def _s3_put(b: Backends, acct: str, p: dict) -> dict:
    r = b.objects.put("aws", acct, p["bucket"], p["key"],
                      p.get("body", b"").encode() if isinstance(p.get("body"), str) else p.get("body", b""),
                      p.get("content_type", "application/octet-stream"))
    return {"ETag": r["etag"]}


def _s3_get(b: Backends, acct: str, p: dict) -> dict:
    o = b.objects.get("aws", acct, p["bucket"], p["key"])
    if o is None:
        return {"ok": False, "code": "NoSuchKey"}
    body = o["body"]
    return {"Body": body.decode(errors="replace") if isinstance(body, bytes) else body,
            "ContentType": o["content_type"]}


def _s3_list(b: Backends, acct: str, p: dict) -> dict:
    return {"Contents": b.objects.list("aws", acct, p["bucket"])}


def _ddb_put(b: Backends, acct: str, p: dict) -> dict:
    b.nosql.put_item("aws", acct, p["table"], p["key"], p.get("item", {}))
    return {}


def _ddb_get(b: Backends, acct: str, p: dict) -> dict:
    item = b.nosql.get_item("aws", acct, p["table"], p["key"])
    return {"Item": item} if item else {"ok": False, "code": "ItemNotFound"}


register(Aws())
