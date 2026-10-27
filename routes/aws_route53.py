"""AWS Route 53 — native REST-XML wire (`/2013-04-01/*`) and the console REST
(`/api/aws/route53/*`), both on the shared engine in core/route53_core.py.

State is space-scoped (`ctx.route53_state`), so zones follow the active space, show up
in its cost-savings metrics and survive restarts with it. After every change the
hosted zones are rendered as zone files into `VYOMI_DNS_ZONES_DIR` (default
`/zones`) where the shared CoreDNS container (`vyomi-coredns`, `auto` plugin) picks
them up — `dig @<host> -p 1053 www.example.com` then answers from the same records.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response

from core import app_context as ctx
from core import route53_core as r53

ZONES_DIR = os.environ.get("VYOMI_DNS_ZONES_DIR", "/zones")


class SpaceRoute53Store(r53.Route53Store):
    """Route53Store whose dicts live in the active space's service state."""

    _KEYS = ("hosted_zones", "changes", "health_checks", "delegation_sets", "query_logging", "tags")

    def __init__(self) -> None:
        self.account_id = ctx.AWS_ACCOUNT_ID
        self.region = "us-east-1"

    def _s(self) -> dict:
        return ctx.route53_state

    def persist(self) -> None:
        ctx.persist_state()
        _write_zone_files(self)
        # Activity log + space cost-savings refresh (same hook SQS/RDS use).
        ctx.record_usage("route53.change", {"resource_id": "route53", "name": "route53"})


def _prop(key):
    return property(lambda self: self._s().setdefault(key, {}))


for _k in SpaceRoute53Store._KEYS:
    setattr(SpaceRoute53Store, _k, _prop(_k))

STORE = SpaceRoute53Store()


def _write_zone_files(store: r53.Route53Store) -> None:
    """Mirror the zones into the CoreDNS directory (best effort — no CoreDNS, no-op)."""
    try:
        if not os.path.isdir(ZONES_DIR):
            return
        files = r53.zone_files(store)
        for name, text in files.items():
            path = os.path.join(ZONES_DIR, f"db.{name}")
            if not os.path.exists(path) or open(path).read() != text:
                with open(path + ".tmp", "w") as f:
                    f.write(text)
                os.replace(path + ".tmp", path)
        for fn in os.listdir(ZONES_DIR):
            if fn.startswith("db.") and fn[3:] not in files:
                os.remove(os.path.join(ZONES_DIR, fn))
    except Exception:
        pass


def _call(fn, *a):
    try:
        out = fn(STORE, *a)
        STORE.persist()
        return out
    except r53.Route53Error as e:
        raise HTTPException(status_code=e.status, detail=f"{e.code}: {e.message}")


def register(app: FastAPI) -> None:
    base = "/api/aws/route53"

    @app.get(base + "/hosted-zones", include_in_schema=False)
    def r53_list():
        return r53.console_list(STORE)

    @app.post(base + "/hosted-zones", include_in_schema=False)
    def r53_create(payload: dict[str, Any] | None = None):
        return _call(r53.console_create, payload or {})

    @app.get(base + "/hosted-zones/{zone}", include_in_schema=False)
    def r53_get(zone: str):
        try:
            return r53.console_get(STORE, zone)
        except r53.Route53Error as e:
            raise HTTPException(status_code=e.status, detail=f"{e.code}: {e.message}")

    @app.patch(base + "/hosted-zones/{zone}", include_in_schema=False)
    def r53_patch(zone: str, payload: dict[str, Any] | None = None):
        return _call(r53.console_set_tags, zone, (payload or {}).get("tags") or {})

    @app.delete(base + "/hosted-zones/{zone}", include_in_schema=False)
    def r53_delete(zone: str):
        return _call(r53.console_delete, zone)

    @app.post(base + "/hosted-zones/{zone}/records", include_in_schema=False)
    def r53_record_upsert(zone: str, payload: dict[str, Any] | None = None):
        return _call(r53.console_record_upsert, zone, payload or {})

    @app.delete(base + "/hosted-zones/{zone}/records", include_in_schema=False)
    def r53_record_delete(zone: str, name: str, type: str = "A"):
        return _call(r53.console_record_delete, zone, name, type)

    @app.get(base + "/{kind}", include_in_schema=False)
    def r53_children(kind: str):
        try:
            return r53.console_children(STORE, kind)
        except r53.Route53Error as e:
            raise HTTPException(status_code=e.status, detail=f"{e.code}: {e.message}")

    @app.post(base + "/{kind}", include_in_schema=False)
    def r53_child_create(kind: str, payload: dict[str, Any] | None = None):
        return _call(r53.console_child_create, kind, payload or {})

    @app.delete(base + "/{kind}/{name}", include_in_schema=False)
    def r53_child_delete(kind: str, name: str):
        return _call(r53.console_child_delete, kind, name)

    # Native wire: aws route53 / SDK clients (endpoint override only).
    @app.api_route("/2013-04-01/{rest:path}", methods=["GET", "POST", "DELETE", "PUT"], include_in_schema=False)
    async def r53_wire(rest: str, request: Request) -> Response:
        body = await request.body()
        r = r53.dispatch(STORE, request.method, "/2013-04-01/" + rest, dict(request.query_params),
                         dict(request.headers), body)
        return Response(content=r.body, status_code=r.status, headers=dict(r.headers), media_type=r.media_type)
