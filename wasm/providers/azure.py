"""Azure provider plugin (WASM substrate). Blob + Cosmos -> shared backends."""
from __future__ import annotations

from .registry import CloudProvider, register
from ..backends.store import Backends


class Azure(CloudProvider):
    id = "azure"
    label = "Microsoft Azure"
    match_hosts = (".blob.core.windows.net", ".documents.azure.com")

    def handlers(self):
        return {
            ("blob", "PutBlob"):   _blob_put,
            ("blob", "GetBlob"):   _blob_get,
            ("cosmos", "Upsert"):  _cosmos_put,
            ("cosmos", "Read"):    _cosmos_get,
        }


def _blob_put(b: Backends, acct: str, p: dict) -> dict:
    body = p.get("body", b"")
    b.objects.put("azure", acct, p["container"], p["blob"],
                  body.encode() if isinstance(body, str) else body)
    return {"blob": p["blob"]}


def _blob_get(b: Backends, acct: str, p: dict) -> dict:
    o = b.objects.get("azure", acct, p["container"], p["blob"])
    if o is None:
        return {"ok": False, "code": "BlobNotFound"}
    body = o["body"]
    return {"body": body.decode(errors="replace") if isinstance(body, bytes) else body}


def _cosmos_put(b: Backends, acct: str, p: dict) -> dict:
    b.nosql.put_item("azure", acct, p["container"], p["id"], p.get("doc", {}))
    return {"id": p["id"]}


def _cosmos_get(b: Backends, acct: str, p: dict) -> dict:
    d = b.nosql.get_item("azure", acct, p["container"], p["id"])
    return {"doc": d} if d else {"ok": False, "code": "NotFound"}


register(Azure())
