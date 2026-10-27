"""Cloud DNS on the offline appliance: the native `google-cloud-dns` / `gcloud dns` REST
wire (`/dns/v1/projects/{p}/managedZones...`) and the console REST (`/api/gcp/dns/...`)
the GCP console catalog drives. Both are thin adapters over core/gcp_dns_core.py on the
SAME shared store, so a zone created in the console is visible to the SDK/CLI and
vice-versa."""
from __future__ import annotations

import json

from fastapi import HTTPException, Request, Response

from core import gcp_dns_core as core

DEFAULT_PROJECT = "demo"


def _http_error(r):
    try:
        msg = json.loads(r.body)["error"]["message"]
    except Exception:
        msg = "error"
    return HTTPException(r.status, detail=msg)


def register(app, on_change=None):
    """`on_change(action, console_view_or_name)` lets the host sync CloudSim events/usage."""
    store = core.shared_store

    def changed(action, payload):
        if on_change:
            try:
                on_change(action, payload)
            except Exception:
                pass

    # ── native wire ───────────────────────────────────────────────────────
    async def native(request: Request):
        body = await request.body()
        path = request.url.path
        r = core.dispatch(store(), request.method, path, dict(request.query_params), dict(request.headers), body)
        segs = [s for s in path.split("/") if s]   # dns v1 projects {p} managedZones [{z}]
        if r.status < 300 and len(segs) >= 5 and segs[4] == "managedZones":
            if request.method == "POST" and len(segs) == 5:
                changed("create", core.console_view(store().zones["%s/%s" % (segs[3], json.loads(r.body)["name"])]))
            elif request.method == "DELETE" and len(segs) == 6:
                changed("delete", segs[5])
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    for pat in ("/dns/v1/projects/{project}", "/dns/v1/projects/{project}/{rest:path}",
                "/dns/v1beta2/projects/{project}", "/dns/v1beta2/projects/{project}/{rest:path}"):
        app.add_api_route(pat, native, methods=["GET", "POST", "PATCH", "PUT", "DELETE"], include_in_schema=False)

    # ── console REST ──────────────────────────────────────────────────────
    # The provider-alias middleware rewrites /api/gcp/<x> → /api/<x>, so the console's
    # /api/gcp/dns/zones land on these.
    def rec(name):
        r = store().zones.get("%s/%s" % (DEFAULT_PROJECT, name))
        if r is None:
            raise HTTPException(404, detail=f"Managed zone {name} not found.")
        return r

    @app.get("/api/dns/zones")
    async def list_zones():
        items = core.list_all(store(), DEFAULT_PROJECT)
        return {"items": items, "count": len(items)}

    @app.post("/api/dns/zones")
    async def create_zone(request: Request):
        z = core.zone_from_form(await request.json())
        r = core.dispatch(store(), "POST", f"/dns/v1/projects/{DEFAULT_PROJECT}/managedZones", {}, {}, json.dumps(z).encode())
        if r.status >= 300:
            raise _http_error(r)
        v = core.console_view(rec(z["name"]))
        changed("create", v)
        return v

    @app.get("/api/dns/zones/{name}")
    async def get_zone(name: str):
        return core.console_view(rec(name))

    @app.patch("/api/dns/zones/{name}")
    async def patch_zone(name: str, request: Request):
        b = await request.json()
        rec(name)
        upd = {k: b[k] for k in ("description", "labels") if k in b}
        r = core.dispatch(store(), "PATCH", f"/dns/v1/projects/{DEFAULT_PROJECT}/managedZones/{name}", {}, {}, json.dumps(upd).encode())
        if r.status >= 300:
            raise _http_error(r)
        return core.console_view(rec(name))

    @app.delete("/api/dns/zones/{name}")
    async def delete_zone(name: str):
        rec(name)
        core.delete_zone_with_records(store(), DEFAULT_PROJECT, name)
        changed("delete", name)
        return {"message": "Managed zone deleted", "name": name}
