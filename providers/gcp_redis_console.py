"""Memorystore for Redis on the offline appliance: the native `google-cloud-redis` /
`gcloud redis instances` REST wire (`/v1/projects/{p}/locations/{l}/instances...`) and the
console REST (`/api/gcp/redis/...`) the GCP console catalog drives. Both are thin adapters over
core/gcp_redis_core.py on the SAME shared store, so an instance created in the console is
visible to the SDK/CLI and vice-versa.

The data plane is the shared Valkey container (CLOUDLEARN_VALKEY_HOST/PORT, set by the compose
files); without it the service is control plane only."""
from __future__ import annotations

import json
import os

from fastapi import HTTPException, Request, Response

from core import gcp_container_core as gke
from core import gcp_redis_core as core

def _project():
    """The GCP space's project ID — the project the console creates in."""
    from core.app_context import gcp_project_name
    return gcp_project_name(None)


async def _json_body(request):
    """Console form body; a missing/invalid JSON body is a 400, not a 500."""
    try:
        b = await request.json()
    except ValueError:
        raise HTTPException(400, detail="Request body must be a JSON object.")
    if not isinstance(b, dict):
        raise HTTPException(400, detail="Request body must be a JSON object.")
    return b


def _http_error(r):
    try:
        msg = json.loads(r.body)["error"]["message"]
    except Exception:
        msg = "error"
    return HTTPException(r.status, detail=msg)


def register(app, on_change=None):
    """`on_change(action, console_view_or_name)` lets the host sync CloudSim events/usage."""
    store = core.shared_store
    host = os.environ.get("CLOUDLEARN_VALKEY_HOST", "").strip()
    if host:
        core.configure_data_plane(host, os.environ.get("CLOUDLEARN_VALKEY_PORT", "6379"))

    def changed(action, payload):
        if on_change:
            try:
                on_change(action, payload)
            except Exception:
                pass

    def call(method, path, query=None, body=b"", headers=None):
        return core.dispatch(store(), method, path, query or {}, headers or {}, body)

    # ── native wire ───────────────────────────────────────────────────────
    async def native(request: Request):
        body = await request.body()
        path = request.url.path
        r = call(request.method, path, dict(request.query_params), body, dict(request.headers))
        if r.status == 200 and request.method in ("POST", "DELETE") and "/instances" in path:
            parts = path.strip("/").split("/")
            if request.method == "POST" and path.rstrip("/").endswith("/instances"):
                full = core.instance_name(parts[2], parts[4], request.query_params.get("instanceId", ""))
                if full in store().instances:
                    changed("create", core.view_by_name(store(), full))
            elif request.method == "DELETE" and len(parts) == 7:
                changed("delete", parts[6])
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    base = "/v1/projects/{project}/locations/{loc}"
    for tail in ("/instances", "/instances/{instance}", "/instances/{instance}/authString"):
        app.add_api_route(base + tail, native, methods=methods, include_in_schema=False)

    # Operations share one URL family with Kubernetes Engine: a single-operation GET/DELETE/cancel
    # goes to whichever service owns the id; the collection merges both.
    async def operations(request: Request):
        body = await request.body()
        r = core.dispatch_shared_operations(
            store(), lambda *a: gke.dispatch(gke.shared_store(), *a), request.method, request.url.path,
            dict(request.query_params), dict(request.headers), body)
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)
    app.add_api_route(base + "/operations/{op}", operations, methods=["GET", "DELETE"], include_in_schema=False)
    app.add_api_route(base + "/operations/{op}:cancel", operations, methods=["POST"], include_in_schema=False)

    # ── console REST ──────────────────────────────────────────────────────
    # The provider-alias middleware rewrites /api/gcp/<x> → /api/<x>, so the console's
    # /api/gcp/redis/instances lands on these.
    def find(name):
        for n in store().instances:
            if n.rsplit("/", 1)[-1] == name or n == name:
                return n
        raise HTTPException(404, detail=f"Instance {name} not found.")

    def loc(full):
        p = full.split("/")
        return p[1], p[3], p[5]

    @app.get("/api/redis/instances")
    async def list_instances():
        items = core.list_all(store())
        return {"items": items, "count": len(items)}

    @app.post("/api/redis/instances")
    async def create_instance(request: Request):
        form = await _json_body(request)
        req = core.job_from_form(form, _project())
        r = call("POST", f"/v1/{req['parent']}/instances", {"instanceId": req["instanceId"]},
                 json.dumps(req["instance"]).encode())
        if r.status >= 300:
            raise _http_error(r)
        v = core.view_by_name(store(), core.instance_name(_project(), req["location"], req["instanceId"]))
        changed("create", v)
        return v

    @app.get("/api/redis/instances/{name}")
    async def get_instance(name: str):
        return core.view_by_name(store(), find(name))

    @app.delete("/api/redis/instances/{name}")
    async def delete_instance(name: str):
        p, l, i = loc(find(name))
        r = call("DELETE", f"/v1/projects/{p}/locations/{l}/instances/{i}")
        if r.status >= 300:
            raise _http_error(r)
        changed("delete", i)
        return {"message": "Instance deleted", "name": i}

    @app.post("/api/sub/redis/{action}/{name}")
    async def instance_action(action: str, name: str, request: Request):
        full = find(name)
        p, l, i = loc(full)
        try:
            b = await _json_body(request)
        except Exception:
            b = {}
        path = f"/v1/projects/{p}/locations/{l}/instances/{i}"
        if action == "resize":
            r = call("PATCH", path, {"updateMask": "memorySizeGb"}, json.dumps({"memorySizeGb": int(b.get("memorySizeGb", 1))}).encode())
        elif action == "failover":
            r = call("POST", path + ":failover", body=json.dumps({"dataProtectionMode": "LIMITED_DATA_LOSS"}).encode())
        else:
            raise HTTPException(404, detail=f"Unknown action {action}")
        if r.status >= 300:
            raise _http_error(r)
        return core.view_by_name(store(), full)
