"""Workflows on the offline appliance: the native `google-cloud-workflows` / `gcloud workflows`
REST wire (`/v1/projects/{p}/locations/{l}/workflows...`, plus the sibling Workflow Executions
`.../executions...`) and the console REST (`/api/gcp/workflows/...`) the GCP console catalog
drives. Both are thin adapters over core/gcp_workflows_core.py on the SAME shared store, so a
workflow created in the console is visible to the SDK/CLI and vice-versa."""
from __future__ import annotations

import json

from fastapi import HTTPException, Request, Response

from core import gcp_container_core as gke
from core import gcp_redis_core as redis
from core import gcp_workflows_core as core

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

    def call(method, path, query=None, body=b"", headers=None):
        return core.dispatch(store(), method, path, query or {}, headers or {}, body)

    # ── native wire ───────────────────────────────────────────────────────
    async def native(request: Request):
        body = await request.body()
        path = request.url.path
        r = call(request.method, path, dict(request.query_params), body, dict(request.headers))
        if r.status == 200 and "/executions" not in path:
            parts = path.strip("/").split("/")
            if request.method == "POST" and path.rstrip("/").endswith("/workflows"):
                full = core.workflow_name(parts[2], parts[4], request.query_params.get("workflowId", ""))
                if full in store().workflows:
                    changed("create", core.view_by_name(store(), full))
            elif request.method == "DELETE" and len(parts) == 6:
                changed("delete", parts[5])
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    base = "/v1/projects/{project}/locations/{loc}"
    for tail in ("/workflows", "/workflows/{workflow}", "/workflows/{workflow}/executions",
                 "/workflows/{workflow}/executions/{execution}"):
        app.add_api_route(base + tail, native, methods=methods, include_in_schema=False)

    # Operations share one URL family with Kubernetes Engine and Memorystore: a single-operation
    # GET/DELETE goes to whichever service owns the id; the collection merges all three.
    async def operations(request: Request):
        body = await request.body()
        r = core.dispatch_operations_chain(
            [lambda *a: gke.dispatch(gke.shared_store(), *a), lambda *a: redis.dispatch(redis.shared_store(), *a),
             lambda *a: core.dispatch(store(), *a)],
            request.method, request.url.path, dict(request.query_params), dict(request.headers), body)
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)
    app.add_api_route(base + "/operations/{op}", operations, methods=["GET", "DELETE"], include_in_schema=False)
    app.add_api_route(base + "/operations/{op}:cancel", operations, methods=["POST"], include_in_schema=False)

    # ── console REST ──────────────────────────────────────────────────────
    # The provider-alias middleware rewrites /api/gcp/<x> → /api/<x>, so the console's
    # /api/gcp/workflows/workflows lands on these.
    def find(name):
        for n in store().workflows:
            if n.rsplit("/", 1)[-1] == name or n == name:
                return n
        raise HTTPException(404, detail=f"Workflow {name} not found.")

    def loc(full):
        p = full.split("/")
        return p[1], p[3], p[5]

    @app.get("/api/workflows/workflows")
    async def list_workflows():
        items = core.list_all(store())
        return {"items": items, "count": len(items)}

    @app.post("/api/workflows/workflows")
    async def create_workflow(request: Request):
        form = await request.json()
        req = core.workflow_from_form(form, DEFAULT_PROJECT)
        r = call("POST", f"/v1/{req['parent']}/workflows", {"workflowId": req["workflowId"]},
                 json.dumps(req["workflow"]).encode())
        if r.status >= 300:
            raise _http_error(r)
        v = core.view_by_name(store(), core.workflow_name(DEFAULT_PROJECT, req["location"], req["workflowId"]))
        changed("create", v)
        return v

    @app.get("/api/workflows/workflows/{name}")
    async def get_workflow(name: str):
        return core.view_by_name(store(), find(name))

    @app.delete("/api/workflows/workflows/{name}")
    async def delete_workflow(name: str):
        p, l, w = loc(find(name))
        r = call("DELETE", f"/v1/projects/{p}/locations/{l}/workflows/{w}")
        if r.status >= 300:
            raise _http_error(r)
        changed("delete", w)
        return {"message": "Workflow deleted", "name": w}

    @app.post("/api/sub/workflows/{action}/{name}")
    async def workflow_action(action: str, name: str, request: Request):
        full = find(name)
        p, l, w = loc(full)
        try:
            b = await request.json()
        except Exception:
            b = {}
        if action != "execute":
            raise HTTPException(404, detail=f"Unknown action {action}")
        arg = b.get("argument")
        r = call("POST", f"/v1/projects/{p}/locations/{l}/workflows/{w}/executions",
                 body=json.dumps({"argument": arg} if arg else {}).encode())
        if r.status >= 300:
            raise _http_error(r)
        return core.view_by_name(store(), full)
