"""AWS ElastiCache — console REST (`/api/aws/elasticache/*`) and the native
Query-protocol store, both on the shared engine in core/elasticache_core.py.

State is space-scoped (`ctx.elasticache_state`), so caches follow the active
space, show up in its cost-savings metrics and survive restarts with it. The
cache nodes' endpoint is the shared Valkey container (`vyomi-valkey`).
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException

from core import app_context as ctx
from core import elasticache_core as ec


class SpaceElastiCacheStore(ec.ElastiCacheStore):
    """ElastiCacheStore whose dicts live in the active space's service state."""

    _KEYS = ("clusters", "replication_groups", "subnet_groups", "parameter_groups", "snapshots", "tags")

    def __init__(self) -> None:
        self.account_id = ctx.AWS_ACCOUNT_ID
        self.region = "us-east-1"
        self.endpoint_host = os.environ.get("VYOMI_VALKEY_HOST", "localhost")
        self.endpoint_port = int(os.environ.get("VYOMI_VALKEY_PORT", "6379"))

    def _s(self) -> dict:
        return ctx.elasticache_state

    def persist(self) -> None:
        ctx.persist_state()
        # Activity log + space cost-savings refresh (same hook SQS/RDS use).
        last = (self.events or [{}])[0]
        rid = last.get("SourceIdentifier", "")
        ctx.record_usage("elasticache." + str(last.get("Message", "change")).lower().replace(" ", "_"),
                         {"resource_id": rid, "name": rid, "source_type": last.get("SourceType", "")})


def _prop(key):
    return property(lambda self: self._s().setdefault(key, [] if key == "events" else {}))


for _k in SpaceElastiCacheStore._KEYS + ("events",):
    setattr(SpaceElastiCacheStore, _k, _prop(_k))

STORE = SpaceElastiCacheStore()


def _call(fn, *a):
    try:
        return fn(STORE, *a)
    except ec.ElastiCacheError as e:
        raise HTTPException(status_code=e.status, detail=f"{e.code}: {e.message}")


def register(app: FastAPI) -> None:
    base = "/api/aws/elasticache"

    @app.get(base + "/clusters", include_in_schema=False)
    def ec_list():
        ec._ensure_defaults(STORE)
        return ec.console_list(STORE)

    @app.post(base + "/clusters", include_in_schema=False)
    def ec_create(payload: dict[str, Any] | None = None):
        ec._ensure_defaults(STORE)
        return _call(ec.console_create, payload or {})

    @app.get(base + "/clusters/{name}", include_in_schema=False)
    def ec_get(name: str):
        return _call(ec.console_get, name)

    @app.patch(base + "/clusters/{name}", include_in_schema=False)
    def ec_patch(name: str, payload: dict[str, Any] | None = None):
        return _call(ec.console_set_tags, name, (payload or {}).get("tags") or {})

    @app.delete(base + "/clusters/{name}", include_in_schema=False)
    def ec_delete(name: str):
        return _call(ec.console_delete, name)

    @app.get(base + "/{kind}", include_in_schema=False)
    def ec_children(kind: str):
        return _call(ec.console_children, kind)

    @app.post(base + "/{kind}", include_in_schema=False)
    def ec_child_create(kind: str, payload: dict[str, Any] | None = None):
        return _call(ec.console_child_create, kind, payload or {})

    @app.delete(base + "/{kind}/{name}", include_in_schema=False)
    def ec_child_delete(kind: str, name: str):
        return _call(ec.console_child_delete, kind, name)
