"""Offline wire for the (SIMULATED) Azure OpenAI inference data plane.

core/azure_cognitiveservices_core.inference owns the behaviour (deterministic, labelled output; no real model).
``AzureOpenAI(azure_endpoint=<base>/azure-data/openai/<account>, api_key=<account key>, api_version=...)`` works:
  POST /azure-data/openai/{account}/openai/deployments/{dep}/chat/completions | completions | embeddings
"""
from __future__ import annotations

import json

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from core import azure_cognitiveservices_core as cs

OPS = {"chat/completions": "chat", "completions": "completions", "embeddings": "embeddings"}


def _state():
    from providers import azure_services
    return azure_services._state


def _account(name: str):
    for r in _state().values():
        if str(r.get("_type", "")).lower() == "microsoft.cognitiveservices/accounts" and r.get("name", "").lower() == name.lower():
            return r
    return None


def register(app) -> None:
    async def infer(account: str, dep: str, op: str, request: Request):
        rec = _account(account)
        if rec is None:
            return JSONResponse(status_code=404, content={"error": {"code": "ResourceNotFound", "message": f"Resource '{account}' was not found."}})
        key = request.headers.get("api-key")
        if key and key not in (rec.get("_keys") or {}).values():
            return JSONResponse(status_code=401, content={"error": {"code": "401", "message": "Access denied due to invalid subscription key or wrong API endpoint."}})
        if rec["properties"].get("disableLocalAuth") and key:
            return JSONResponse(status_code=403, content={"error": {"code": "AuthenticationTypeDisabled", "message": "Key based authentication is disabled for this resource."}})
        try:
            body = await request.json()
        except Exception:
            body = {}
        kind = OPS.get(op)
        if kind is None:
            return JSONResponse(status_code=404, content={"error": {"code": "404", "message": "Resource not found"}})
        status, out = cs.inference(rec, dep, kind, body)
        if status == 200 and kind == "chat" and isinstance(body, dict) and body.get("stream"):
            text = out["choices"][0]["message"]["content"]

            def gen():
                base = {"id": out["id"], "object": "chat.completion.chunk", "created": out["created"], "model": out["model"]}
                yield "data: " + json.dumps(dict(base, choices=[{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}])) + "\n\n"
                for w in text.split(" "):
                    yield "data: " + json.dumps(dict(base, choices=[{"index": 0, "delta": {"content": w + " "}, "finish_reason": None}])) + "\n\n"
                yield "data: " + json.dumps(dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}])) + "\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")
        return JSONResponse(status_code=status, content=out)

    async def route(account: str, dep: str, op: str, request: Request):
        return await infer(account, dep, op, request)

    app.add_api_route("/azure-data/openai/{account}/openai/deployments/{dep}/{op:path}", route, methods=["POST"], include_in_schema=False)
