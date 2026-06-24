"""GCP provider plugin (WASM substrate). Cloud Storage + Firestore -> the same
shared generic backends used by AWS. Note the SECOND arg differs (gcp vs aws),
so data is namespaced per provider but reuses one ObjectStore/NoSqlStore."""
from __future__ import annotations

from .registry import CloudProvider, register
from ..backends.store import Backends


class Gcp(CloudProvider):
    id = "gcp"
    label = "Google Cloud Platform"
    match_hosts = ("storage.googleapis.com", "firestore.googleapis.com")

    def handlers(self):
        return {
            ("storage", "insert"): _gcs_put,
            ("storage", "get"):    _gcs_get,
            ("firestore", "set"):  _fs_set,
            ("firestore", "get"):  _fs_get,
        }


def _gcs_put(b: Backends, acct: str, p: dict) -> dict:
    body = p.get("body", b"")
    b.objects.put("gcp", acct, p["bucket"], p["object"],
                  body.encode() if isinstance(body, str) else body)
    return {"name": p["object"], "bucket": p["bucket"]}


def _gcs_get(b: Backends, acct: str, p: dict) -> dict:
    o = b.objects.get("gcp", acct, p["bucket"], p["object"])
    if o is None:
        return {"ok": False, "code": "notFound"}
    body = o["body"]
    return {"body": body.decode(errors="replace") if isinstance(body, bytes) else body}


def _fs_set(b: Backends, acct: str, p: dict) -> dict:
    b.nosql.put_item("gcp", acct, p["collection"], p["doc"], p.get("fields", {}))
    return {"name": p["doc"]}


def _fs_get(b: Backends, acct: str, p: dict) -> dict:
    d = b.nosql.get_item("gcp", acct, p["collection"], p["doc"])
    return {"fields": d} if d else {"ok": False, "code": "NOT_FOUND"}


register(Gcp())
