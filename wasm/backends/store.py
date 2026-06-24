"""Generic in-memory backend primitives for the WASM (Nano) substrate.

These are the SHARED, cloud-agnostic stores every cloud provider maps onto.
Write them once; a new cloud joins by mapping its API to these primitives —
NOT by adding new storage logic. In the browser these are backed by:

    ObjectStore  -> OPFS / IndexedDB        (here: dict, for the POC/tests)
    NoSqlStore   -> SQLite-WASM / IndexedDB
    KvStore      -> SQLite-WASM
    SqlStore     -> PGlite / SQLite-WASM
    QueueStore   -> in-process deque

The same primitive is shared across clouds but NAMESPACED by (provider,
account) so AWS S3, GCP GCS and Azure Blob don't collide while reusing one
implementation. This is what keeps "add a cloud" additive.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any


def _ns(provider: str, account: str, name: str) -> str:
    return f"{provider}/{account}/{name}"


class ObjectStore:
    """S3 / GCS / Azure Blob / OCI Object Storage — all map here."""
    def __init__(self) -> None:
        self._b: dict[str, dict[str, dict[str, Any]]] = {}

    def create_bucket(self, provider: str, account: str, bucket: str) -> None:
        self._b.setdefault(_ns(provider, account, bucket), {})

    def put(self, provider: str, account: str, bucket: str, key: str,
            body: bytes, content_type: str = "application/octet-stream") -> dict:
        b = self._b.setdefault(_ns(provider, account, bucket), {})
        b[key] = {"body": body, "content_type": content_type, "updated": time.time()}
        return {"etag": str(hash(body) & 0xffffffff), "size": len(body)}

    def get(self, provider: str, account: str, bucket: str, key: str) -> dict | None:
        return self._b.get(_ns(provider, account, bucket), {}).get(key)

    def list(self, provider: str, account: str, bucket: str) -> list[str]:
        return sorted(self._b.get(_ns(provider, account, bucket), {}).keys())

    def delete(self, provider: str, account: str, bucket: str, key: str) -> bool:
        return self._b.get(_ns(provider, account, bucket), {}).pop(key, None) is not None


class NoSqlStore:
    """DynamoDB / Firestore / Cosmos / (future) OCI NoSQL — all map here."""
    def __init__(self) -> None:
        self._t: dict[str, dict[str, dict[str, Any]]] = {}

    def put_item(self, provider: str, account: str, table: str, key: str, item: dict) -> None:
        self._t.setdefault(_ns(provider, account, table), {})[key] = dict(item)

    def get_item(self, provider: str, account: str, table: str, key: str) -> dict | None:
        return self._t.get(_ns(provider, account, table), {}).get(key)

    def query(self, provider: str, account: str, table: str) -> list[dict]:
        return list(self._t.get(_ns(provider, account, table), {}).values())


class QueueStore:
    """SQS / Pub/Sub / Storage Queue / (future) OCI Queue — all map here."""
    def __init__(self) -> None:
        self._q: dict[str, deque] = {}

    def send(self, provider: str, account: str, queue: str, body: str) -> str:
        self._q.setdefault(_ns(provider, account, queue), deque()).append(body)
        return str(int(time.time() * 1000))

    def receive(self, provider: str, account: str, queue: str) -> str | None:
        q = self._q.get(_ns(provider, account, queue))
        return q.popleft() if q else None


class ResourceStore:
    """Generic named-resource collections — the backing store for the
    console's catalog-driven CRUD. The console renders every service from its
    `collection_path` (GET=list, POST=create) and `resource_path` (GET/PUT/
    PATCH/DELETE on one named item), so ONE generic store serves all of them:
    EC2 instances, S3 buckets, IAM users, RDS databases, SQS queues, …

    Namespaced by (provider, account, service) so e.g. aws `ec2` and aws `rds`
    are independent collections. Each item is a free-form dict keyed by a name
    derived from common id fields (Name/name/id/key/bucket/…)."""
    _NAME_FIELDS = ("name", "Name", "id", "Id", "key", "Key", "bucket",
                    "Bucket", "table", "TableName", "queue", "QueueName",
                    "user", "UserName", "function", "FunctionName")

    def __init__(self) -> None:
        self._c: dict[str, dict[str, dict[str, Any]]] = {}

    @classmethod
    def name_of(cls, item: dict, fallback: str = "") -> str:
        for f in cls._NAME_FIELDS:
            v = item.get(f)
            if v:
                return str(v)
        return fallback

    def list(self, provider: str, account: str, service: str) -> list[dict]:
        return list(self._c.get(_ns(provider, account, service), {}).values())

    def create(self, provider: str, account: str, service: str, item: dict) -> dict:
        coll = self._c.setdefault(_ns(provider, account, service), {})
        name = self.name_of(item, fallback=f"{service}-{len(coll) + 1}")
        rec = dict(item)
        rec.setdefault("name", name)
        rec.setdefault("status", "available")
        coll[name] = rec
        return rec

    def get(self, provider: str, account: str, service: str, name: str) -> dict | None:
        return self._c.get(_ns(provider, account, service), {}).get(name)

    def update(self, provider: str, account: str, service: str, name: str, patch: dict) -> dict | None:
        coll = self._c.get(_ns(provider, account, service), {})
        rec = coll.get(name)
        if rec is None:
            return None
        rec.update(patch)
        return rec

    def delete(self, provider: str, account: str, service: str, name: str) -> bool:
        return self._c.get(_ns(provider, account, service), {}).pop(name, None) is not None


class Backends:
    """The bundle of primitives handed to every provider plugin."""
    def __init__(self) -> None:
        self.objects = ObjectStore()
        self.nosql = NoSqlStore()
        self.queues = QueueStore()
        self.resources = ResourceStore()
        # SqlStore / KvStore / SecretStore / KmsEngine slot in here the same way.
