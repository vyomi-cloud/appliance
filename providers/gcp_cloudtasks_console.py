"""Cloud Tasks routes for the offline appliance: the native `/v2/projects/...` REST wire
(official google-cloud-tasks clients / `gcloud tasks`) and the console REST the GCP
catalog drives (`/api/gcp/cloudtasks/...`). Both are thin adapters over
core/gcp_cloudtasks_core.py on the SAME shared store, so a queue created in the console
is visible to SDK/CLI and vice-versa."""
from __future__ import annotations

import json

from fastapi import HTTPException, Request, Response

from core import gcp_cloudtasks_core as core

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def _is_tasks_path(path: str) -> bool:
    rest = path.split("/", 4)   # '', v2, projects, {p}, ...
    tail = rest[4] if len(rest) > 4 else ""
    return tail == "locations" or tail.startswith("locations/") and (
        tail.count("/") == 1 or "/queues" in tail)


def _call(method, path, body=None, query=None):
    r = core.dispatch(core.shared_store(), method, path, query or {}, {},
                      json.dumps(body).encode() if body is not None else b"")
    if r.status >= 400:
        err = json.loads(r.body or b"{}").get("error", {})
        raise HTTPException(r.status, detail=f"{err.get('status', 'Error')}: {err.get('message', '')}")
    return json.loads(r.body or b"{}")


def _find(name: str) -> dict:
    """Resolve a console short name to its queue record (first match across projects)."""
    for q in core.shared_store().queues.values():
        if q["name"].rsplit("/", 1)[-1] == name:
            return q
    raise HTTPException(404, detail=f"NOT_FOUND: Queue {name} does not exist.")


def register(app, on_change=None):
    """`on_change(action, queue_view_or_name)` lets the host sync CloudSim events/usage."""
    def changed(action, payload):
        if on_change:
            try:
                on_change(action, payload)
            except Exception:
                pass

    store = core.shared_store
    view = lambda q: core.queue_console_view(store(), q)  # noqa: E731

    # ── native wire: /v2/projects/{p}/locations[/...] ──────────────────────
    async def wire(request: Request, rest: str = ""):
        path = request.url.path
        if not _is_tasks_path(path):
            raise HTTPException(404, detail="Not Found")
        body = await request.body()
        before = set(store().queues)
        r = core.dispatch(store(), request.method, path, dict(request.query_params),
                          dict(request.headers), body)
        for n in set(store().queues) - before:
            changed("create", view(store().queues[n]))
        for n in before - set(store().queues):
            changed("delete", n.rsplit("/", 1)[-1])
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    app.add_api_route("/v2/projects/{rest:path}", wire, methods=_METHODS, include_in_schema=False)

    # ── console REST ───────────────────────────────────────────────────────
    @app.get("/api/gcp/cloudtasks/queues")
    def list_queues():
        items = core.console_list(store())
        return {"items": items, "count": len(items)}

    @app.post("/api/gcp/cloudtasks/queues")
    async def create_queue(request: Request):
        b = await request.json()
        qid = str(b.get("name") or "").strip()
        project = str(b.get("project") or core.DEFAULT_PROJECT).strip()
        loc = str(b.get("location") or "us-central1").strip()
        rl, rc = {}, {}
        if b.get("max_dispatches_per_second") not in (None, ""):
            rl["maxDispatchesPerSecond"] = float(b["max_dispatches_per_second"])
        if b.get("max_concurrent_dispatches") not in (None, ""):
            rl["maxConcurrentDispatches"] = int(b["max_concurrent_dispatches"])
        if b.get("max_attempts") not in (None, ""):
            rc["maxAttempts"] = int(b["max_attempts"])
        _call("POST", f"/v2/projects/{project}/locations/{loc}/queues",
              {"name": f"projects/{project}/locations/{loc}/queues/{qid}", "rateLimits": rl, "retryConfig": rc})
        v = view(_find(qid))
        changed("create", v)
        return v

    @app.get("/api/gcp/cloudtasks/queues/{name}")
    def get_queue(name: str):
        return view(_find(name))

    @app.patch("/api/gcp/cloudtasks/queues/{name}")
    async def patch_queue(name: str, request: Request):
        b = await request.json()
        q = _find(name)
        upd = {}
        if b.get("max_dispatches_per_second") not in (None, ""):
            upd.setdefault("rateLimits", {})["maxDispatchesPerSecond"] = float(b["max_dispatches_per_second"])
        if b.get("max_concurrent_dispatches") not in (None, ""):
            upd.setdefault("rateLimits", {})["maxConcurrentDispatches"] = int(b["max_concurrent_dispatches"])
        if b.get("max_attempts") not in (None, ""):
            upd.setdefault("retryConfig", {})["maxAttempts"] = int(b["max_attempts"])
        if upd:
            _call("PATCH", "/v2/" + q["name"], upd)
        return view(q)

    @app.delete("/api/gcp/cloudtasks/queues/{name}")
    def delete_queue(name: str):
        q = _find(name)
        _call("DELETE", "/v2/" + q["name"])
        changed("delete", name)
        return {"message": "Queue deleted", "name": name}

    @app.post("/api/gcp/cloudtasks/queues/{name}/{action}")
    async def queue_action(name: str, action: str, request: Request):
        q = _find(name)
        if action in ("pause", "resume", "purge"):
            _call("POST", f"/v2/{q['name']}:{action}", {})
            return view(q)
        if action == "tasks":
            b = await request.json() if (await request.body()) else {}
            url = b.get("url") or "https://example.com/handler"
            t = _call("POST", f"/v2/{q['name']}/tasks",
                      {"task": {"httpRequest": {"url": url, "httpMethod": b.get("method") or "POST"}}})
            return core.task_console_view(store().tasks[t["name"]])
        raise HTTPException(404, detail="Unknown action")

    @app.get("/api/gcp/cloudtasks/queues/{name}/{kind}")
    def queue_children(name: str, kind: str):
        return core.children(store(), _find(name), kind)
