"""Cloud Monitoring on the offline appliance: the native `google-cloud-monitoring` /
`gcloud monitoring` REST wire (`/v3/projects/{p}/...`) and the console REST
(`/api/gcp/monitoring/...`) the GCP console catalog drives. Both are thin adapters over
core/gcp_monitoring_core.py on the SAME shared store, so a policy created in the console
is visible to the SDK/CLI and vice-versa. The console grid lists alert policies; channels,
custom metrics, time series, uptime checks and groups are served by the native wire."""
from __future__ import annotations

import json
import os
import re
import urllib.request

from fastapi import HTTPException, Request, Response

from core import gcp_monitoring_core as core

DEFAULT_PROJECT = "demo"


def _http_error(r_or_e):
    if hasattr(r_or_e, "body"):
        try:
            return HTTPException(r_or_e.status, detail=json.loads(r_or_e.body)["error"]["message"])
        except Exception:
            return HTTPException(r_or_e.status, detail="error")
    return HTTPException(r_or_e.status, detail=r_or_e.message)


VM_URL = os.environ.get("CLOUDLEARN_VICTORIAMETRICS_URL", "").strip().rstrip("/")   # shared VictoriaMetrics (compose profile `full`)


def _vm_sink(project, meta, point):
    """Mirror each written sample into VictoriaMetrics (Prometheus text import), so PromQL /
    MetricsQL / Grafana see the same series. Best effort: the engine stays the API."""
    kind, val = next(iter(point["value"].items()))
    if kind not in ("boolValue", "int64Value", "doubleValue"):
        return
    val = float(1 if val is True else 0 if val is False else val)
    lab = lambda k: re.sub(r"[^a-zA-Z0-9_]", "_", k)   # noqa: E731
    esc = lambda v: str(v).replace("\\", "\\\\").replace('"', '\\"')   # noqa: E731
    labels = {"project": project, "resource_type": meta["resource"]["type"],
              **{"metric_" + lab(k): v for k, v in meta["metric"]["labels"].items()},
              **{"resource_" + lab(k): v for k, v in meta["resource"]["labels"].items()}}
    ts = int(core.parse_ts(point["interval"]["endTime"]).timestamp() * 1000)
    line = "gcp_monitoring_%s{%s} %s %d" % (lab(meta["metric"]["type"]),
                                            ",".join('%s="%s"' % (k, esc(v)) for k, v in labels.items()), val, ts)
    urllib.request.urlopen(urllib.request.Request(VM_URL + "/api/v1/import/prometheus",
                                                  data=line.encode(), method="POST"), timeout=2).close()


def register(app, on_change=None):
    """`on_change(action, console_view_or_name)` lets the host sync CloudSim events/usage."""
    if VM_URL:
        core.metric_sink = _vm_sink
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
        before = set(store().alert_policies)
        r = core.dispatch(store(), request.method, request.url.path, dict(request.query_params),
                          dict(request.headers), body)
        for n in set(store().alert_policies) - before:
            changed("create", core.console_view(store(), store().alert_policies[n]))
        for n in before - set(store().alert_policies):
            changed("delete", n.rsplit("/", 1)[-1])
        return Response(content=r.body, status_code=r.status, media_type=r.media_type)

    app.add_api_route("/v3/uptimeCheckIps", native, methods=["GET"], include_in_schema=False)
    # metricDescriptors ids carry slashes (custom.googleapis.com/a/b) → path converter
    for pat in ("/v3/projects/{project}/{collection}", "/v3/projects/{project}/{collection}/{rest:path}"):
        app.add_api_route(pat, native, methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)

    # ── console REST ──────────────────────────────────────────────────────
    # The provider-alias middleware rewrites /api/gcp/<x> → /api/<x>, so the console's
    # /api/gcp/monitoring/policies (and /api/gcp/sub/monitoring/…) land on these.
    def find(pid):
        for n, p in store().alert_policies.items():
            if n.rsplit("/", 1)[-1] == pid or n == pid:
                return p
        raise HTTPException(404, detail=f"Alert policy {pid} not found.")

    @app.get("/api/monitoring/policies")
    async def list_policies():
        items = core.list_all(store())
        return {"items": items, "count": len(items)}

    @app.post("/api/monitoring/policies")
    async def create_policy(request: Request):
        b = await request.json()
        try:
            v = core.create_from_form(store(), b, DEFAULT_PROJECT)
        except core._E as e:
            raise _http_error(e)
        changed("create", v)
        return v

    @app.get("/api/monitoring/policies/{pid}")
    async def get_policy(pid: str):
        return core.console_view(store(), find(pid))

    @app.patch("/api/monitoring/policies/{pid}")
    async def patch_policy(pid: str, request: Request):
        b = await request.json()
        p = find(pid)
        upd = {k: b[k] for k in ("displayName", "enabled", "documentation", "severity") if k in b}
        try:
            core.patch_policy(store(), p["name"].split("/")[1], p["name"].rsplit("/", 1)[-1], upd, ",".join(upd))
        except core._E as e:
            raise _http_error(e)
        return core.console_view(store(), find(pid))

    @app.delete("/api/monitoring/policies/{pid}")
    async def delete_policy(pid: str):
        p = find(pid)
        del store().alert_policies[p["name"]]
        short = p["name"].rsplit("/", 1)[-1]
        changed("delete", short)
        return {"message": "Alert policy deleted", "name": short}

    # "/api/gcp/sub/" is exempt from the provider-alias rewrite (Artifact Registry serves it
    # natively), so the console's enable/disable call needs the un-rewritten path as well.
    @app.post("/api/gcp/sub/monitoring/{action}/{pid}")
    @app.post("/api/sub/monitoring/{action}/{pid}")
    async def policy_action(action: str, pid: str):
        if action not in ("enable", "disable"):
            raise HTTPException(404, detail=f"Unknown action {action}")
        p = find(pid)
        try:
            core.patch_policy(store(), p["name"].split("/")[1], p["name"].rsplit("/", 1)[-1],
                              {"enabled": action == "enable"}, "enabled")
        except core._E as e:
            raise _http_error(e)
        return core.console_view(store(), find(pid))
