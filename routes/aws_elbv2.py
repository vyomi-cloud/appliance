"""AWS Elastic Load Balancing v2 — console REST (`/api/aws/elbv2/*`) and the native
Query-protocol store, both on the shared engine in core/elbv2_core.py.

State is space-scoped (`ctx.elbv2_state`), so load balancers follow the active
space, show up in its cost-savings metrics and survive restarts with it.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from core import app_context as ctx
from core import elbv2_core as elb


class SpaceElbv2Store(elb.Elbv2Store):
    """Elbv2Store whose dicts live in the active space's service state."""

    _KEYS = ("load_balancers", "target_groups", "listeners", "rules", "tags")

    def __init__(self) -> None:
        self.account_id = ctx.AWS_ACCOUNT_ID
        self.region = "us-east-1"

    def _s(self) -> dict:
        return ctx.elbv2_state

    def persist(self) -> None:
        ctx.persist_state()
        # Activity log + space cost-savings refresh (same hook SQS/RDS use).
        ctx.record_usage("elbv2.change", {"resource_id": "elbv2", "name": "elbv2"})


def _prop(key):
    return property(lambda self: self._s().setdefault(key, {}))


for _k in SpaceElbv2Store._KEYS:
    setattr(SpaceElbv2Store, _k, _prop(_k))

STORE = SpaceElbv2Store()


def _call(fn, *a):
    try:
        return fn(STORE, *a)
    except elb.Elbv2Error as e:
        raise HTTPException(status_code=e.status, detail=f"{e.code}: {e.message}")


def register(app: FastAPI) -> None:
    base = "/api/aws/elbv2"

    @app.get(base + "/load-balancers", include_in_schema=False)
    def elb_list():
        return elb.console_list(STORE)

    @app.post(base + "/load-balancers", include_in_schema=False)
    def elb_create(payload: dict[str, Any] | None = None):
        return _call(elb.console_create, payload or {})

    @app.get(base + "/load-balancers/{name}", include_in_schema=False)
    def elb_get(name: str):
        return _call(elb.console_get, name)

    @app.patch(base + "/load-balancers/{name}", include_in_schema=False)
    def elb_patch(name: str, payload: dict[str, Any] | None = None):
        return _call(elb.console_set_tags, name, (payload or {}).get("tags") or {})

    @app.delete(base + "/load-balancers/{name}", include_in_schema=False)
    def elb_delete(name: str):
        return _call(elb.console_delete, name)

    @app.get(base + "/{kind}", include_in_schema=False)
    def elb_children(kind: str):
        return _call(elb.console_children, kind)

    @app.post(base + "/{kind}", include_in_schema=False)
    def elb_child_create(kind: str, payload: dict[str, Any] | None = None):
        return _call(elb.console_child_create, kind, payload or {})

    @app.delete(base + "/{kind}/{name}", include_in_schema=False)
    def elb_child_delete(kind: str, name: str):
        return _call(elb.console_child_delete, kind, name)
