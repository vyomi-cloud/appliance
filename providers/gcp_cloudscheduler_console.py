"""Cloud Scheduler on the offline appliance: the native `google-cloud-scheduler` /
`gcloud scheduler` REST wire (`/v1/projects/{p}/locations/{l}/jobs...`) and the console
REST (`/api/gcp/cloudscheduler/...`) the GCP console catalog drives. Both are thin
adapters over core/gcp_cloudscheduler_core.py on the SAME shared store, so a job created
in the console is visible to the SDK/CLI and vice-versa.

Pub/Sub targets are published into the appliance's Pub/Sub topic when a job fires
(`:run`, or when its schedule is due: a 15 s background ticker fires it)."""
from __future__ import annotations

import json

from fastapi import HTTPException, Request, Response

from core import gcp_cloudscheduler_core as core

DEFAULT_PROJECT = "demo"
DEFAULT_REGION = "us-central1"
TICK_SECONDS = 15


async def _json_body(request):
    """Console form body; a missing/invalid JSON body is a 400, not a 500."""
    try:
        b = await request.json()
    except ValueError:
        raise HTTPException(400, detail="Request body must be a JSON object.")
    if not isinstance(b, dict):
        raise HTTPException(400, detail="Request body must be a JSON object.")
    return b


class _Shim:
    """Minimal Request stand-in for providers.gcp_services.api_gcp_pubsub_publish."""

    def __init__(self, payload):
        self._p = payload

    async def json(self):
        return self._p


async def _drain(pending, store):
    """Deliver queued Pub/Sub publishes; a missing topic is recorded on the job."""
    if not pending:
        return
    from providers import gcp_services
    for job_name, topic_name, data, attrs in pending:
        project, topic = topic_name.split("/")[1], topic_name.split("/")[3]
        try:
            await gcp_services.api_gcp_pubsub_publish(
                project, topic, _Shim({"messages": [{"data": data, "attributes": attrs}]}))
        except HTTPException as e:
            job = store.jobs.get(job_name)
            if job is not None:
                job["status"] = {"code": 5, "message": f"Pub/Sub topic {topic_name} not found ({e.status_code})."}
        except Exception as e:   # noqa: BLE001 — never fail the request over a delivery error
            job = store.jobs.get(job_name)
            if job is not None:
                job["status"] = {"code": 13, "message": str(e)}


def _queue_invoker(pending):
    def invoke(kind, d):
        if kind == "pubsub":
            pending.append((d["job"], d["topicName"], d.get("data", ""), d.get("attributes") or {}))
        return True
    return invoke


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

    async def call(method, path, query=None, body=b"", headers=None):
        pending: list = []
        r = core.dispatch(store(), method, path, query or {}, headers or {}, body, invoker=_queue_invoker(pending))
        await _drain(pending, store())
        return r

    # ── background timer ─────────────────────────────────────────────────
    # Real Cloud Scheduler fires on time with nobody calling it; the core is lazy, so the
    # appliance drives it. Each tick fires a due ENABLED job at most once (_advance moves
    # scheduleTime forward) and missed ticks are not replayed.
    async def tick():
        # No request here, so bind the GCP provider like the alias middleware does: the
        # Pub/Sub state is space-scoped by REQUEST_PROVIDER (default "aws").
        from core.app_context import REQUEST_PROVIDER
        token = REQUEST_PROVIDER.set("gcp")
        try:
            pending: list = []
            core._advance(store(), invoker=_queue_invoker(pending))
            await _drain(pending, store())
        finally:
            REQUEST_PROVIDER.reset(token)

    async def _ticker():
        import asyncio
        while True:
            await asyncio.sleep(TICK_SECONDS)
            try:
                await tick()
            except Exception as e:   # noqa: BLE001 — a bad job must not stop the timer
                print(f"[cloudscheduler] tick failed: {e!r}")

    @app.on_event("startup")
    async def _start_scheduler_ticker():
        import asyncio
        app.state.cloudscheduler_ticker = asyncio.create_task(_ticker())

    # ── native wire ───────────────────────────────────────────────────────
    async def native(request: Request):
        body = await request.body()
        r = await call(request.method, request.url.path, dict(request.query_params), body, dict(request.headers))
        if request.method == "POST" and request.url.path.endswith("/jobs") and r.status == 200:
            changed("create", core.console_view(store().jobs[json.loads(r.body)["name"]]))
        elif request.method == "DELETE" and r.status == 200:
            changed("delete", request.url.path.rsplit("/", 1)[-1])
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    for pat in ("/v1/projects/{project}/locations", "/v1/projects/{project}/locations/{loc}",
                "/v1/projects/{project}/locations/{loc}/jobs", "/v1/projects/{project}/locations/{loc}/jobs/{job}"):
        app.add_api_route(pat, native, methods=["GET", "POST", "PATCH", "DELETE"], include_in_schema=False)

    # ── console REST ──────────────────────────────────────────────────────
    # The provider-alias middleware rewrites /api/gcp/<x> → /api/<x>, so the console's
    # /api/gcp/cloudscheduler/jobs (and /api/gcp/sub/cloudscheduler/…) land on these.
    def find(name):
        for n, j in store().jobs.items():
            if n.rsplit("/", 1)[-1] == name or n == name:
                return j
        raise HTTPException(404, detail=f"Job {name} not found.")

    def parts(name):
        p = find(name)["name"].split("/")
        return p[1], p[3], p[5]

    @app.get("/api/cloudscheduler/jobs")
    async def list_jobs():
        items = core.list_all(store())
        return {"items": items, "count": len(items)}

    @app.post("/api/cloudscheduler/jobs")
    async def create_job(request: Request):
        b = await _json_body(request)
        job = build_job(b)
        loc = str(b.get("region") or DEFAULT_REGION)
        r = await call("POST", f"/v1/projects/{DEFAULT_PROJECT}/locations/{loc}/jobs", body=json.dumps(job).encode())
        if r.status >= 300:
            raise _http_error(r)
        v = core.console_view(store().jobs[job["name"]])
        changed("create", v)
        return v

    @app.get("/api/cloudscheduler/jobs/{name}")
    async def get_job(name: str):
        p, l, j = parts(name)
        r = await call("GET", f"/v1/projects/{p}/locations/{l}/jobs/{j}")
        return core.console_view(store().jobs[json.loads(r.body)["name"]])

    @app.patch("/api/cloudscheduler/jobs/{name}")
    async def patch_job(name: str, request: Request):
        b = await _json_body(request)
        p, l, j = parts(name)
        upd = {k: b[k] for k in ("description", "schedule", "timeZone") if b.get(k)}
        r = await call("PATCH", f"/v1/projects/{p}/locations/{l}/jobs/{j}", {"updateMask": ",".join(upd)}, json.dumps(upd).encode())
        if r.status >= 300:
            raise _http_error(r)
        return core.console_view(store().jobs[json.loads(r.body)["name"]])

    @app.delete("/api/cloudscheduler/jobs/{name}")
    async def delete_job(name: str):
        p, l, j = parts(name)
        r = await call("DELETE", f"/v1/projects/{p}/locations/{l}/jobs/{j}")
        if r.status >= 300:
            raise _http_error(r)
        changed("delete", j)
        return {"message": "Job deleted", "name": j}

    @app.post("/api/sub/cloudscheduler/{action}/{name}")
    async def job_action(action: str, name: str):
        if action not in ("pause", "resume", "run"):
            raise HTTPException(404, detail=f"Unknown action {action}")
        p, l, j = parts(name)
        r = await call("POST", f"/v1/projects/{p}/locations/{l}/jobs/{j}:{action}")
        if r.status >= 300:
            raise _http_error(r)
        return core.console_view(store().jobs[json.loads(r.body)["name"]])


def build_job(b, project=DEFAULT_PROJECT):
    """Console create form → REST Job (shared with the Nano adapter's shape)."""
    return core.job_from_form(b, project)
