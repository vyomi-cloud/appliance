"""Azure Container Apps ingress on the offline appliance: a request to the app's URL reaches the replica that is really running.

A Container App's `ingress.fqdn` (`<app>.<env-domain>.azurecontainerapps.io`) does not resolve on a developer machine, so the simulator serves
the same ingress three ways, all landing here:
  * path form   `<simulator>/azure-data/containerapps/<app>/<path>`      (ARM returns it as `properties.vyomiIngressUrl`)
  * revision    `<simulator>/azure-data/containerapps/<app>--<revision>/<path>` (like the revision FQDN)
  * Host header `Host: <app>.<anything>.azurecontainerapps.io` on any simulator URL (core/middleware.py rewrites it onto the path form)
The replica is a Docker container (any image, Pro/Max + Docker) or a sandboxed Python process (`vyomi/python-app`, see
providers/azure_app_runtime.py). In multiple-revision mode the revision is chosen by the ingress traffic weights; `app--revision` pins one.
Not simulated: TLS termination on the app FQDN, custom domains/certificates, IP restrictions, CORS policy, Easy Auth (authConfigs), session affinity,
scale-to-zero cold start (a replica runs from creation until the app is stopped or deleted) and HTTP/2 / TCP transports. An internal-only ingress
is served like an external one (one machine).
"""
from __future__ import annotations

import asyncio
import http.client
import random
import time

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length"}
_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


def _err(status: int, code: str, message: str):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _find_app(label: str):
    """(record, pinned revision | None) for `<app>` or `<app>--<revision-suffix>`."""
    from providers import azure_services as svc
    name, _, suffix = label.partition("--")
    hits = [r for r in list(svc._state.values()) if isinstance(r, dict) and str(r.get("_type", "")).lower() == "microsoft.app/containerapps"
            and str(r.get("name", "")).lower() == name.lower()]
    if not hits:
        return None, None
    return hits[-1], (f"{hits[-1]['name']}--{suffix}" if suffix else None)


def _pick(rec, pinned):
    hs = rec.get("_runtime") or {}
    if pinned:
        return pinned, hs.get(pinned)
    revs = rec.get("_revisions") or {}
    live = [(n, revs[n]["properties"].get("trafficWeight", 0)) for n in hs if n in revs]
    if not live:
        return None, None
    weighted = [(n, w) for n, w in live if w > 0] or [(live[0][0], 1)]
    n = random.choices([x[0] for x in weighted], weights=[x[1] for x in weighted])[0]
    return n, hs[n]


def _forward(handle, method, path, query, headers, body, host):
    conn = http.client.HTTPConnection(handle.get("host", "127.0.0.1"), int(handle["port"]), timeout=120)
    try:
        conn.request(method, path + (("?" + query) if query else ""), body=body or None, headers=headers)
        r = conn.getresponse()
        data = r.read()
        return r.status, [(k, v) for k, v in r.getheaders()], data
    finally:
        conn.close()


async def _wait_listening(handle, seconds=30.0) -> bool:
    from providers import azure_app_runtime as rt
    t0 = time.time()
    while time.time() - t0 < seconds:
        if await run_in_threadpool(rt._port_open, handle):
            return True
        if handle.get("kind") == "sandbox" and not rt._sandbox_alive(handle):
            return False
        await asyncio.sleep(0.25)
    return False


async def _ingress(request: Request):
    label = request.path_params["app"]
    rest = request.path_params.get("rest", "")
    rec, pinned = _find_app(label)
    if rec is None:
        return _err(404, "ContainerAppNotFound", f"No container app '{label.partition('--')[0]}' exists in this space.")
    ing = (rec["properties"].get("configuration") or {}).get("ingress")
    if not ing:
        return _err(404, "IngressNotEnabled", f"Container app '{rec['name']}' has no ingress configured.")
    if rec["properties"].get("runningStatus") == "Stopped":
        return _err(503, "ContainerAppStopped", f"Container app '{rec['name']}' is stopped.")
    rev, handle = _pick(rec, pinned)
    if not handle:
        note = (rec["properties"].get("vyomiRuntime") or {}).get("error") or (rec["properties"].get("vyomiRuntime") or {}).get("note") \
            or "no replica is running (the image is not runnable here: use image vyomi/python-app with a source bundle, or a Docker-capable appliance)"
        return _err(503, "NoRunningReplica", f"Container app '{rec['name']}': {note}")
    if not await _wait_listening(handle):
        from providers import azure_app_runtime as rt
        tail = rt._logs(handle, 15)[-400:] if handle.get("kind") == "sandbox" else ""
        return _err(503, "ReplicaNotReady", f"The replica of revision '{rev}' is not listening on its port. {tail}".strip())
    body = await request.body()
    fqdn = (ing.get("fqdn") or "")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP}
    headers["host"] = fqdn or request.headers.get("host", "")
    headers.setdefault("x-forwarded-host", request.headers.get("host", ""))
    headers.setdefault("x-forwarded-proto", request.url.scheme)
    headers.setdefault("x-forwarded-for", request.client.host if request.client else "127.0.0.1")
    if body:
        headers["content-length"] = str(len(body))
    try:
        status, hdrs, data = await run_in_threadpool(_forward, handle, request.method, "/" + rest, request.scope.get("query_string", b"").decode("latin-1"),
                                                     headers, body, fqdn)
    except Exception as exc:  # noqa: BLE001
        return _err(502, "BadGateway", f"The replica did not answer: {type(exc).__name__}: {str(exc)[:160]}")
    out = Response(content=data, status_code=status)
    for k, v in hdrs:
        if k.lower() not in _HOP:
            out.headers.append(k, v)
    out.headers["x-vyomi-revision"] = rev
    return out


def register(app) -> None:
    app.add_route("/azure-data/containerapps/{app}/{rest:path}", _ingress, methods=_METHODS)
    app.add_route("/azure-data/containerapps/{app}", _ingress, methods=_METHODS)
