"""Kubernetes Engine on the offline appliance: the native `google-cloud-container` /
`gcloud container` REST wire (`/v1/projects/{p}/locations/{l}/clusters...`) and the console
REST (`/api/gcp/container/...`) the GCP console catalog drives. Both are thin adapters over
core/gcp_container_core.py on the SAME shared store, so a cluster created in the console is
visible to the SDK/CLI and vice-versa.

Control plane only: no Kubernetes API server runs behind a cluster's endpoint."""
from __future__ import annotations

import json

from fastapi import HTTPException, Request, Response

from core import gcp_container_core as core

DEFAULT_PROJECT = "demo"


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
        if r.status == 200 and request.method in ("POST", "DELETE", "PUT") and "/clusters" in path:
            segs = path.split("/clusters", 1)[1].strip("/").split("/")
            parts = path.strip("/").split("/")
            if request.method == "POST" and path.rstrip("/").endswith("/clusters"):
                name = json.loads(body).get("cluster", {}).get("name", "")
                full = core.cluster_name(parts[2], parts[4], name)
                if full in store().clusters:
                    changed("create", core.view_by_name(store(), full))
            elif request.method == "DELETE" and len(segs) == 1 and segs[0]:
                changed("delete", segs[0].split(":")[0])
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    for base in ("/v1/projects/{project}/locations/{loc}", "/v1/projects/{project}/zones/{loc}"):
        for tail in ("/clusters", "/clusters/{cluster}", "/clusters/{cluster}/nodePools",
                     "/clusters/{cluster}/nodePools/{pool}", "/operations", "/operations/{op}", "/serverConfig"):
            app.add_api_route(base + tail, native, methods=methods, include_in_schema=False)

    # ── console REST ──────────────────────────────────────────────────────
    # The provider-alias middleware rewrites /api/gcp/<x> → /api/<x>, so the console's
    # /api/gcp/container/clusters lands on these.
    def find(name):
        for n in store().clusters:
            if n.rsplit("/", 1)[-1] == name or n == name:
                return n
        raise HTTPException(404, detail=f"Cluster {name} not found.")

    def loc(full):
        p = full.split("/")
        return p[1], p[3], p[5]

    @app.get("/api/container/clusters")
    async def list_clusters():
        items = core.list_all(store())
        return {"items": items, "count": len(items)}

    @app.post("/api/container/clusters")
    async def create_cluster(request: Request):
        form = await _json_body(request)
        req = core.job_from_form(form, DEFAULT_PROJECT)
        r = call("POST", f"/v1/{req['parent']}/clusters", body=json.dumps({"cluster": req["cluster"]}).encode())
        if r.status >= 300:
            raise _http_error(r)
        v = core.view_by_name(store(), core.cluster_name(DEFAULT_PROJECT, req["location"], req["cluster"]["name"]))
        changed("create", v)
        return v

    @app.get("/api/container/clusters/{name}")
    async def get_cluster(name: str):
        return core.view_by_name(store(), find(name))

    @app.delete("/api/container/clusters/{name}")
    async def delete_cluster(name: str):
        p, l, c = loc(find(name))
        r = call("DELETE", f"/v1/projects/{p}/locations/{l}/clusters/{c}")
        if r.status >= 300:
            raise _http_error(r)
        changed("delete", c)
        return {"message": "Cluster deleted", "name": c}

    @app.post("/api/sub/container/{action}/{name}")
    async def cluster_action(action: str, name: str, request: Request):
        full = find(name)
        p, l, c = loc(full)
        try:
            b = await _json_body(request)
        except Exception:
            b = {}
        if action == "resize":
            pool = (store().clusters[full]["nodePools"] or [{"name": "default-pool"}])[0]["name"]
            r = call("POST", f"/v1/projects/{p}/locations/{l}/clusters/{c}/nodePools/{pool}:setSize",
                     body=json.dumps({"nodeCount": int(b.get("nodeCount", 3))}).encode())
        elif action == "upgrade":
            r = call("PUT", f"/v1/projects/{p}/locations/{l}/clusters/{c}",
                     body=json.dumps({"update": {"desiredMasterVersion": b.get("version") or "latest"}}).encode())
        else:
            raise HTTPException(404, detail=f"Unknown action {action}")
        if r.status >= 300:
            raise _http_error(r)
        return core.view_by_name(store(), full)
