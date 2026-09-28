"""console-next NoSQL facade (Azure Cosmos DB) — the Azure lens's nosql-item-viewer
data plane.

The SAME nosql-item-viewer widget renders under lens=azure; the ONLY difference is
the manifest `api` block pointing at /api/console/azure-cosmos/* instead of
/api/dynamodb/* or /api/console/firestore/* (§15.2 — no if(cloud) branching in the
widget). This module is the Cosmos DB sibling of the Firestore console facade
(core/console_firestore.py): it returns the SAME JSON response shapes the widget
consumes (list tables/containers, get table, list/put/delete items, key query), so
the widget stays cloud-agnostic.

Cosmos DB (Core/SQL API) is a document DB — a "table" here is a CONTAINER and an
"item" is a DOCUMENT. Every Cosmos document carries a required `id` field which is
the item's natural key, so `id` plays the role of the DynamoDB partition key: the
partition-key name is fixed to `id` and the partition-key VALUE the widget queries
by is the document id. This keeps the same key-query UX (list all / query by id /
begins_with on id) with no widget changes.

Purely additive + substrate-free (no fastapi / azure-sdk / socket imports): it holds
its OWN module-level in-memory doc store so the Azure lens's NoSQL state is
independent of the AWS/GCP lenses', exactly like core/console_firestore mirrors the
DynamoDB console surface. It never touches any native Cosmos core or its routes.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

# Cosmos documents carry a required `id` — the natural key; it surfaces to the widget
# as the partition key so the "query by partition-key value" UX works unchanged.
_ID_FIELD = "id"

# In-memory store: { container_name: {"created": iso, "docs": { doc_id: {
#   "item": {...native...}, "created": iso, "updated": iso } } } }
_STORE: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CosmosError(Exception):
    """Facade error carrying an HTTP status + message (mapped to HTTPException)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _container(name: str) -> dict:
    c = _STORE.get(name)
    if c is None:
        raise CosmosError(404, "ContainerNotFound")
    return c


def _fmt_size(n: int) -> str:
    size = float(int(n or 0))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{int(size)} B"


def _doc_id(item: dict) -> str:
    """The document id for an item: the caller's `id` field, else a stable
    synthesized id from the item content."""
    if not isinstance(item, dict):
        raise CosmosError(400, "ValidationError: document must be an object.")
    for key in (_ID_FIELD, "name"):
        if key in item and item[key] not in (None, ""):
            return str(item[key])
    import hashlib
    blob = json.dumps(item, sort_keys=True, default=str).encode("utf-8")
    return "doc-" + hashlib.sha1(blob).hexdigest()[:12]


def _size_bytes(item: dict) -> int:
    try:
        return len(json.dumps(item, sort_keys=True, default=str).encode("utf-8"))
    except Exception:
        return 0


def _table_view(name: str, cont: dict, include_count: bool = True) -> dict:
    view = {
        "table_name": name,
        "table_arn": f"dbs/vyomi-cosmos/colls/{name}",
        "table_status": "ACTIVE",
        # The document id is the container's single key — surfaced as the partition
        # key so the widget's key-query UX works with no branching.
        "partition_key_name": _ID_FIELD,
        "partition_key_type": "S",
        "sort_key_name": "",
        "sort_key_type": "S",
        "billing_mode": "PAY_PER_REQUEST",
        "created": cont.get("created", ""),
        "last_modified": cont.get("last_modified", cont.get("created", "")),
    }
    if include_count:
        view["item_count"] = len(cont.get("docs", {}))
    return view


def _item_view(doc_id: str, record: dict) -> dict:
    native = copy.deepcopy(record.get("item", {}))
    native.setdefault(_ID_FIELD, doc_id)
    size = int(record.get("size_bytes", _size_bytes(native)) or 0)
    return {
        "key": {_ID_FIELD: doc_id},
        "item": native,
        "created": record.get("created", ""),
        "updated": record.get("updated", ""),
        "size_bytes": size,
        "size_human": _fmt_size(size),
    }


# ── public API (mirrors the DynamoDB/Firestore console REST surface) ─────────

def list_containers() -> dict:
    tables = [_table_view(n, c) for n, c in sorted(_STORE.items())]
    return {
        "table_names": [t["table_name"] for t in tables],
        "tables": tables,
        "count": len(tables),
    }


def create_container(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise CosmosError(400, "ValidationError: container name is required.")
    if name in _STORE:
        raise CosmosError(409, "Conflict: container already exists.")
    _STORE[name] = {"created": _now(), "last_modified": _now(), "docs": {}}
    return {"table": _table_view(name, _STORE[name])}


def get_container(name: str) -> dict:
    cont = _container(name)
    return {"table": _table_view(name, cont)}


def delete_container(name: str) -> dict:
    if name not in _STORE:
        raise CosmosError(404, "ContainerNotFound")
    _STORE.pop(name, None)
    return {"deleted": True, "table_name": name}


def list_documents(name: str) -> dict:
    cont = _container(name)
    rows = [_item_view(doc_id, rec) for doc_id, rec in sorted(cont.get("docs", {}).items())]
    return {"table_name": name, "items": rows, "count": len(rows)}


def put_document(name: str, item: dict) -> dict:
    cont = _container(name)
    if not isinstance(item, dict):
        raise CosmosError(400, "ValidationError: document must be an object.")
    doc_id = _doc_id(item)
    native = copy.deepcopy(item)
    native.setdefault(_ID_FIELD, doc_id)
    docs = cont.setdefault("docs", {})
    existing = docs.get(doc_id)
    docs[doc_id] = {
        "item": native,
        "created": existing.get("created", _now()) if existing else _now(),
        "updated": _now(),
        "size_bytes": _size_bytes(native),
    }
    cont["last_modified"] = _now()
    return {"table_name": name, "item": _item_view(doc_id, docs[doc_id])}


def delete_document(name: str, key: dict) -> dict:
    cont = _container(name)
    if not isinstance(key, dict):
        raise CosmosError(400, "ValidationError: key must be an object.")
    doc_id = None
    for k in (_ID_FIELD, "name"):
        if k in key and key[k] not in (None, ""):
            doc_id = str(key[k])
            break
    if doc_id is None:
        raise CosmosError(400, f"ValidationError: key must include '{_ID_FIELD}'.")
    removed = cont.get("docs", {}).pop(doc_id, None)
    cont["last_modified"] = _now()
    return {"table_name": name, "deleted": True,
            "item": (removed or {}).get("item", {})}


def query_documents(name: str, partition_key_value: Any = None,
                    sort_key_begins_with: str = "") -> dict:
    """Key query: match on the document id (the partition key). An empty value lists
    everything; `sort_key_begins_with` applies a begins_with over the document id so
    the widget's begins_with control also works with no branching."""
    cont = _container(name)
    docs = cont.get("docs", {})
    scanned = len(docs)
    pk = None if partition_key_value in (None, "") else str(partition_key_value)
    begins = str(sort_key_begins_with or "")
    matched = []
    for doc_id in sorted(docs):
        if pk is not None and doc_id != pk:
            continue
        if begins and not doc_id.startswith(begins):
            continue
        matched.append(_item_view(doc_id, docs[doc_id]))
    return {"table_name": name, "items": matched,
            "count": len(matched), "scanned_count": scanned}
