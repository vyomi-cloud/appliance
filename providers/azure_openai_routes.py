"""Offline wire for the Azure OpenAI inference data plane.

One implementation: ``core.ai_models_core.azure_openai_dispatch`` - the same code the unified router serves at ``/openai/...`` - so
``AzureOpenAI(azure_endpoint=<base>/azure-data/openai/<account>, api_key=<account key>, api_version=...)`` and an SDK pointed at
the wire root get the SAME answer from the SAME local model (tools, json_object/json_schema, token streaming, embeddings), or a
503 when the model is not running. Never a canned reply.
  POST /azure-data/openai/{account}/openai/deployments/{dep}/chat/completions | completions | embeddings
"""
from __future__ import annotations

import json

from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from core import ai_models_core

OPS = ("chat/completions", "completions", "embeddings")


def _state():
    from providers import azure_services
    return azure_services._state


def _account(name: str):
    for r in _state().values():
        if str(r.get("_type", "")).lower() == "microsoft.cognitiveservices/accounts" and r.get("name", "").lower() == name.lower():
            return r
    return None


def register(app) -> None:
    async def route(account: str, dep: str, op: str, request: Request):
        rec = _account(account)
        if rec is None:
            return JSONResponse(status_code=404, content={"error": {"code": "ResourceNotFound", "message": f"Resource '{account}' was not found."}})
        key = request.headers.get("api-key")
        if key and key not in (rec.get("_keys") or {}).values():
            return JSONResponse(status_code=401, content={"error": {"code": "401", "message": "Access denied due to invalid subscription key or wrong API endpoint."}})
        if rec["properties"].get("disableLocalAuth") and key:
            return JSONResponse(status_code=403, content={"error": {"code": "AuthenticationTypeDisabled", "message": "Key based authentication is disabled for this resource."}})
        if op not in OPS:
            return JSONResponse(status_code=404, content={"error": {"code": "404", "message": "Resource not found"}})
        body = await request.body()
        hdrs = dict(request.headers)
        if not (key or hdrs.get("authorization")):
            hdrs["api-key"] = "none"      # the data-plane gate (key / bearer) is enforced above for supplied keys; keep prior leniency
        tok = ai_models_core.STREAM_OK.set(True)
        try:
            out = ai_models_core.azure_openai_dispatch({rec.get("id", account): rec}, "POST", f"/openai/deployments/{dep}/{op}",
                                                       dict(request.query_params), hdrs, body)
        finally:
            ai_models_core.STREAM_OK.reset(tok)
        h = dict(out.get("headers") or {})
        ct = h.pop("content-type", None)
        if out.get("stream") is not None:
            return StreamingResponse(out["stream"], status_code=out["status"], headers=h, media_type=ct)
        return Response(content=out.get("body") or b"", status_code=out["status"], headers=h, media_type=ct)

    app.add_api_route("/azure-data/openai/{account}/openai/deployments/{dep}/{op:path}", route, methods=["POST"], include_in_schema=False)
