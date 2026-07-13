"""Azure provider plugin (WASM substrate). Blob + Cosmos -> shared backends."""
from __future__ import annotations

from .registry import CloudProvider, register
from ..backends.store import Backends
from . import dataplane_adapter as D   # v2.9.0 net-new data planes (Service Bus/SQL/RBAC)


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
            # ── v2.9.0 net-new data planes (real cores via dataplane_adapter) ──
            # Service Bus — topics + subscriptions + send/receive (fan-out)
            ("servicebus", "ListTopics"):  lambda b, a, p: D.sb_list(p),
            ("servicebus", "CreateTopic"): lambda b, a, p: D.sb_create(p),
            ("servicebus", "CreateSubscription"): lambda b, a, p: D.sb_create_sub(p),
            ("servicebus", "DeleteTopic"): lambda b, a, p: D.sb_delete(p),
            ("servicebus", "Send"):        lambda b, a, p: D.sb_send(p),
            ("servicebus", "Receive"):     lambda b, a, p: D.sb_receive(p),
            # Azure SQL — servers + databases + real SQL query
            ("azuresql", "ListServers"):    lambda b, a, p: D.sql_list(p),
            ("azuresql", "CreateServer"):   lambda b, a, p: D.sql_create_server(p),
            ("azuresql", "CreateDatabase"): lambda b, a, p: D.sql_create_db(p),
            ("azuresql", "DeleteServer"):   lambda b, a, p: D.sql_delete_server(p),
            ("azuresql", "Query"):          lambda b, a, p: D.sql_query(p),
            # Azure RBAC — role assignments + checkAccess decision
            ("azurerbac", "ListAssignments"): lambda b, a, p: D.rbac_list(p),
            ("azurerbac", "CreateAssignment"): lambda b, a, p: D.rbac_create(p),
            ("azurerbac", "DeleteAssignment"): lambda b, a, p: D.rbac_delete(p),
            ("azurerbac", "CheckAccess"):   lambda b, a, p: D.rbac_check(p),
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
