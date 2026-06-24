"""Oracle Cloud (OCI) provider plugin — the PROOF that 'a few more clouds will
join in coming days' is additive. Adding a whole new cloud is just this file:
declare the id + match rules, map its API operations to the SAME shared generic
backends, and register(). No core change, no new storage, no fork.

Drop-in template for the next cloud (IBM, Alibaba, DigitalOcean, ...): copy
this, rename, remap the operations."""
from __future__ import annotations

from .registry import CloudProvider, register
from ..backends.store import Backends


class Oracle(CloudProvider):
    id = "oci"
    label = "Oracle Cloud Infrastructure"
    match_hosts = (".oraclecloud.com",)

    def handlers(self):
        return {
            ("objectstorage", "PutObject"): _oci_put,
            ("objectstorage", "GetObject"): _oci_get,
            ("nosql", "PutRow"):            _oci_nosql_put,
            ("nosql", "GetRow"):            _oci_nosql_get,
        }


def _oci_put(b: Backends, acct: str, p: dict) -> dict:
    body = p.get("body", b"")
    b.objects.put("oci", acct, p["bucket"], p["name"],
                  body.encode() if isinstance(body, str) else body)
    return {"name": p["name"]}


def _oci_get(b: Backends, acct: str, p: dict) -> dict:
    o = b.objects.get("oci", acct, p["bucket"], p["name"])
    if o is None:
        return {"ok": False, "code": "ObjectNotFound"}
    body = o["body"]
    return {"body": body.decode(errors="replace") if isinstance(body, bytes) else body}


def _oci_nosql_put(b: Backends, acct: str, p: dict) -> dict:
    b.nosql.put_item("oci", acct, p["table"], p["key"], p.get("row", {}))
    return {}


def _oci_nosql_get(b: Backends, acct: str, p: dict) -> dict:
    r = b.nosql.get_item("oci", acct, p["table"], p["key"])
    return {"row": r} if r else {"ok": False, "code": "RowNotFound"}


register(Oracle())
