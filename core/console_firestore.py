"""console-next NoSQL facade (GCP Firestore) — the GCP lens's nosql-item-viewer
data plane.

The SAME nosql-item-viewer widget renders under lens=gcp; the ONLY difference is the
manifest `api` block pointing at /api/console/firestore/* instead of /api/dynamodb/*
(§15.2 — no if(cloud) branching in the widget). This module is the Firestore sibling
of the AWS DynamoDB console REST API (routes/aws_dynamodb.py): it returns the SAME
JSON response shapes the widget consumes (list tables/collections, get table,
list/put/delete items, key query), so the widget stays cloud-agnostic.

Firestore is a document DB — a "table" here is a COLLECTION and an "item" is a
DOCUMENT. The document id plays the role of the DynamoDB partition key, so the
partition-key name is fixed to `__name__` (Firestore's document-id field) and the
partition-key VALUE the widget queries by is the document id. This keeps the same
key-query UX (list all / query by id / begins_with on id) with no widget changes.

Purely additive + substrate-free (no fastapi / google-cloud / socket imports): it
holds its OWN module-level in-memory doc store so the GCP lens's NoSQL state is
independent of the AWS lens's, exactly like core/console_cloudsql mirrors
core/console_sql. It never touches the appliance's native Firestore core
(core/gcp_firestore_core.py) or its routes.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

# Firestore's document id is the natural key; it surfaces to the widget as the
# partition key so the "query by partition-key value" UX works unchanged.
_ID_FIELD = "__name__"

# In-memory store: { collection_name: {"created": iso, "docs": { doc_id: {
#   "item": {...native...}, "created": iso, "updated": iso } } } }
_STORE: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FirestoreError(Exception):
    """Facade error carrying an HTTP status + message (mapped to HTTPException)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _collection(name: str) -> dict:
    coll = _STORE.get(name)
    if coll is None:
        raise FirestoreError(404, "CollectionNotFound")
    return coll


def _fmt_size(n: int) -> str:
    size = float(int(n or 0))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{int(size)} B"


def _doc_id(item: dict) -> str:
    """The document id for an item: the caller's `__name__`/`id` field, else a
    stable synthesized id from the item content."""
    if not isinstance(item, dict):
        raise FirestoreError(400, "ValidationError: document must be an object.")
    for key in (_ID_FIELD, "id", "name"):
        if key in item and item[key] not in (None, ""):
            return str(item[key])
    # No explicit id — synthesize a short deterministic one so puts are idempotent.
    import hashlib
    blob = json.dumps(item, sort_keys=True, default=str).encode("utf-8")
    return "doc-" + hashlib.sha1(blob).hexdigest()[:12]


def _size_bytes(item: dict) -> int:
    try:
        return len(json.dumps(item, sort_keys=True, default=str).encode("utf-8"))
    except Exception:
        return 0


def _table_view(name: str, coll: dict, include_count: bool = True) -> dict:
    view = {
        "table_name": name,
        "table_arn": f"projects/cloudlearn/databases/(default)/documents/{name}",
        "table_status": "ACTIVE",
        # The document id is the collection's single key — surfaced as the partition
        # key so the widget's key-query UX works with no branching.
        "partition_key_name": _ID_FIELD,
        "partition_key_type": "S",
        "sort_key_name": "",
        "sort_key_type": "S",
        "billing_mode": "PAY_PER_REQUEST",
        "created": coll.get("created", ""),
        "last_modified": coll.get("last_modified", coll.get("created", "")),
    }
    if include_count:
        view["item_count"] = len(coll.get("docs", {}))
    return view


def _item_view(doc_id: str, record: dict) -> dict:
    native = copy.deepcopy(record.get("item", {}))
    # Ensure the id field is present so the key label + query round-trips.
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


# ── public API (mirrors the DynamoDB console REST surface) ──────────────────

def list_collections() -> dict:
    tables = [_table_view(n, c) for n, c in sorted(_STORE.items())]
    return {
        "table_names": [t["table_name"] for t in tables],
        "tables": tables,
        "count": len(tables),
    }


def create_collection(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise FirestoreError(400, "ValidationError: collection name is required.")
    if name in _STORE:
        raise FirestoreError(409, "Conflict: collection already exists.")
    _STORE[name] = {"created": _now(), "last_modified": _now(), "docs": {}}
    return {"table": _table_view(name, _STORE[name])}


def get_collection(name: str) -> dict:
    coll = _collection(name)
    return {"table": _table_view(name, coll)}


def delete_collection(name: str) -> dict:
    if name not in _STORE:
        raise FirestoreError(404, "CollectionNotFound")
    _STORE.pop(name, None)
    return {"deleted": True, "table_name": name}


def list_documents(name: str) -> dict:
    coll = _collection(name)
    rows = [_item_view(doc_id, rec) for doc_id, rec in sorted(coll.get("docs", {}).items())]
    return {"table_name": name, "items": rows, "count": len(rows)}


def put_document(name: str, item: dict) -> dict:
    coll = _collection(name)
    if not isinstance(item, dict):
        raise FirestoreError(400, "ValidationError: document must be an object.")
    doc_id = _doc_id(item)
    native = copy.deepcopy(item)
    native.setdefault(_ID_FIELD, doc_id)
    docs = coll.setdefault("docs", {})
    existing = docs.get(doc_id)
    docs[doc_id] = {
        "item": native,
        "created": existing.get("created", _now()) if existing else _now(),
        "updated": _now(),
        "size_bytes": _size_bytes(native),
    }
    coll["last_modified"] = _now()
    return {"table_name": name, "item": _item_view(doc_id, docs[doc_id])}


def delete_document(name: str, key: dict) -> dict:
    coll = _collection(name)
    if not isinstance(key, dict):
        raise FirestoreError(400, "ValidationError: key must be an object.")
    doc_id = None
    for k in (_ID_FIELD, "id", "name"):
        if k in key and key[k] not in (None, ""):
            doc_id = str(key[k])
            break
    if doc_id is None:
        raise FirestoreError(400, f"ValidationError: key must include '{_ID_FIELD}'.")
    removed = coll.get("docs", {}).pop(doc_id, None)
    coll["last_modified"] = _now()
    return {"table_name": name, "deleted": True,
            "item": (removed or {}).get("item", {})}


def query_documents(name: str, partition_key_value: Any = None,
                    sort_key_begins_with: str = "") -> dict:
    """Key query: match on the document id (the partition key). An empty value lists
    everything; `sort_key_begins_with` applies a begins_with over the document id so
    the widget's begins_with control also works with no branching."""
    coll = _collection(name)
    docs = coll.get("docs", {})
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
