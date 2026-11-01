"""Cloud Run Admin API v2 native wire on the offline appliance (backs the v4 Cloud Run and
Cloud Functions consoles — the real console folds functions into Cloud Run).

The engine is core/gcp_run_core.py (shared with Nano and the dev server). Its state lives in
the active space's `service_states["gcp_run"]` slot, so services, revisions, jobs, executions,
worker pools and domain mappings persist with the appliance state and follow space switches.
These routes are put at the FRONT of the routing table: an older GET-only handler already
matches `/v2/projects/.../services`, and Starlette uses the first path match.
"""
from __future__ import annotations

from fastapi import FastAPI, Request, Response

from core import app_context as ctx
from core import gcp_run_core as run

PLATFORM = ctx.PLATFORM
_KEYS = ("services", "revisions", "jobs", "executions", "tasks", "operations", "policies",
         "worker_pools", "domain_mappings", "event_triggers", "triggers", "builds")


def _slot() -> dict | None:
    spaces_state = PLATFORM.kernel.state.setdefault("spaces", {"spaces": {}, "active_space_id": "", "settings": {}})
    active_id = spaces_state.get("active_space_id", "")
    if not active_id:
        return None
    space = spaces_state.setdefault("spaces", {}).setdefault(active_id, {})
    slot = space.setdefault("service_states", {}).setdefault("gcp_run", {})
    for k in _KEYS:
        slot.setdefault(k, {})
    slot.setdefault("seq", {"op": 0, "uid": 0})
    return slot


class SpaceRunStore(run.RunStore):
    """RunStore whose state is the active space's persisted slot."""

    def __init__(self) -> None:           # no super().__init__: the state attrs are properties
        self._fallback = {k: {} for k in _KEYS} | {"seq": {"op": 0, "uid": 0}}

    def _s(self) -> dict:
        return _slot() or self._fallback


for _k in _KEYS + ("seq",):
    setattr(SpaceRunStore, _k, property(lambda self, k=_k: self._s()[k]))

_STORE = SpaceRunStore()


def store() -> SpaceRunStore:
    """The offline appliance's one Cloud Run store — routes/gcp_pubsub_unified.py reaches in
    here to deliver Eventarc-style trigger events on a real Pub/Sub publish."""
    return _STORE


def _log_fn(kind, project, location, rid, message, severity="INFO"):
    """A real Cloud Run mutation (or Eventarc delivery) -> a real Cloud Logging entry (the
    Observability tab's Logs section reads these back via entries:list)."""
    from core import gcp_logging_core as lg
    from routes import gcp_logging as lg_routes
    restype = "cloud_run_revision" if kind == "service" else "cloud_run_job"
    label_key = "service_name" if kind == "service" else "job_name"
    entry = {
        "logName": "projects/%s/logs/run.googleapis.com%%2F%s" % (project, "requests" if kind == "service" else "executions"),
        "resource": {"type": restype, "labels": {"project_id": project, "location": location, label_key: rid}},
        "severity": severity,
        "textPayload": message,
    }
    try:
        lg.write_entries(lg_routes.store(), None, {"entries": [entry]})
    except Exception:
        pass   # never fail the Cloud Run call over a logging hiccup


def _topic_exists(topic_full):
    from routes import gcp_pubsub_unified as ps
    with ps._gcp():
        return ps._store().get_topic(topic_full) is not None


def register(app: FastAPI) -> None:
    async def _wire(request: Request):
        r = run.dispatch(_STORE, request.method, request.url.path, dict(request.query_params),
                         dict(request.headers), await request.body(), log_fn=_log_fn, topic_exists=_topic_exists)
        status, headers, body = (r.status, getattr(r, "headers", {}) or {}, r.body) if hasattr(r, "status") \
            else (r["status"], r.get("headers") or {}, r.get("body", b""))
        if request.method != "GET" and status < 300 and _slot() is not None:
            ctx.persist_state()
        if not isinstance(body, (bytes, bytearray)):
            import json
            body = json.dumps(body).encode()
        return Response(content=body, status_code=status, headers=headers,
                        media_type=getattr(r, "media_type", None) or "application/json")

    before = len(app.router.routes)
    methods = ["GET", "POST", "PATCH", "PUT", "DELETE"]
    for kind in ("services", "jobs", "workerPools", "operations"):
        app.add_route(f"/v2/projects/{{project}}/locations/{{loc}}/{kind}", _wire, methods=methods)
        app.add_route(f"/v2/projects/{{project}}/locations/{{loc}}/{kind}/{{rest:path}}", _wire, methods=methods)
    for prefix in ("/apis/serving.knative.dev/{rest:path}", "/apis/domains.cloudrun.com/{rest:path}"):
        app.add_route(prefix, _wire, methods=methods)
    ours = app.router.routes[before:]
    del app.router.routes[before:]
    app.router.routes[0:0] = ours           # ahead of the legacy GET-only handler
