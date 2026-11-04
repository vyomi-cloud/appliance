"""Offline wire for the Log Analytics data plane: native SDK endpoints without ARM paths.

core/azure_operationalinsights_core.py owns ingest + KQL; this maps the SDK URLs onto it:
  LogsQueryClient(endpoint=<base>/azure-data/loganalytics)  -> POST|GET  /v1/workspaces/{workspaceId}/query
  LogsIngestionClient(endpoint=<base>/azure-data/loganalytics/{workspace}) -> POST /dataCollectionRules/{dcr}/streams/{stream}
  HTTP Data Collector (Log-Type header)                      -> POST /azure-data/loganalytics/{workspace}/api/logs
{workspace} / {workspaceId} = the workspace name or its customerId.
"""
from __future__ import annotations

import json

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from core import azure_operationalinsights_core as oi


def _state():
    from providers import azure_services
    return azure_services._state


def _find(ws: str):
    for r in oi._workspaces(_state()):
        if ws.lower() in (r["name"].lower(), str((r.get("properties") or {}).get("customerId", "")).lower()):
            return r
    return None


def register(app) -> None:
    async def route(ws: str, rest: str, request: Request):
        parts = [p for p in rest.split("/") if p]
        if ws == "v1":                       # endpoint=<base>/azure-data/loganalytics -> /v1/workspaces/{id}/query
            parts = ["v1"] + parts
        elif ws == "workspaces":             # azquery (Go/.NET/JS) appends /workspaces/{id}/query with no /v1
            parts = ["workspaces"] + parts
        if parts[:2] == ["v1", "workspaces"] and len(parts) >= 4:       # LogsQueryClient: workspace id is in the path
            ws, parts = parts[2], parts[3:]
        elif parts[:1] == ["workspaces"] and len(parts) >= 3:
            ws, parts = parts[1], parts[2:]
        elif parts[:1] == ["v1"] and len(parts) >= 2:
            parts = parts[1:]
        rec = _find(ws)
        if rec is None:
            return JSONResponse(status_code=404, content={"error": {"code": "PathNotFoundError", "message": f"The requested path does not exist: workspace '{ws}'"}})
        q = dict(request.query_params)
        for hk, qk in (("log-type", "logType"), ("time-generated-field", "time-generated-field")):
            if request.headers.get(hk) and qk not in q:
                q[qk] = request.headers[hk]
        try:
            body = await request.json() if request.method == "POST" else {}
        except Exception:
            body = {}
        if parts == ["query"]:
            rest_tokens = ["query"]
        else:
            rest_tokens = parts
        body = {"_array": body} if isinstance(body, list) else body
        r = oi._data_plane(rec, rest_tokens, request.method, body, q)
        if r["body"] is None:
            return Response(status_code=r["status"])
        return JSONResponse(status_code=r["status"], content=r["body"])

    for m in (["GET", "POST"],):
        app.add_api_route("/azure-data/loganalytics/{ws}/{rest:path}", route, methods=m, include_in_schema=False)
