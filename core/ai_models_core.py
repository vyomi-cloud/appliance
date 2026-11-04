"""Model-inference wire adapters over the shared local-LLM seam (core/llm_core): Bedrock Runtime, Vertex AI Gemini, Azure OpenAI.

Each ``*_dispatch`` returns ``{"status", "headers", "body": bytes}`` (the AwsWireRouter result shape) and keeps its OWN cloud's
request/response/error shapes - nothing falls through to another cloud's handler.

Bedrock (signing name ``bedrock``): POST /model/{id}/invoke, /invoke-with-response-stream, /converse, /converse-stream
(real vnd.amazon.eventstream framing), GET /foundation-models[/{id}] (ListFoundationModels/GetFoundationModel). Body formats for the
Anthropic Claude Messages, Amazon Titan Text / Titan Embeddings, Amazon Nova, Meta Llama and Mistral families.
Vertex AI: POST .../publishers/google/models/{model}:generateContent | :streamGenerateContent | :countTokens | :embedContent | :predict.
Azure OpenAI: POST /openai/deployments/{deployment}/chat/completions | /completions | /embeddings (and /openai/v1/... with `model` in
the body); the deployment must exist under a Cognitive Services OpenAI/AIServices account (ARM state) - DeploymentNotFound otherwise.

Honest limit: one small local model answers for every model id/deployment (see core/llm_core.HONEST_LIMIT). Streaming is real
event framing but the text is generated whole and then chunked. Tool/function calling, images, guardrails, prompt caching and
fine-tuned/provisioned throughput are not modelled; they are rejected with the cloud's validation error rather than ignored.
"""
from __future__ import annotations

import base64
import json
import re
import struct
import time
import uuid
import zlib

try:
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import llm_core as llm  # type: ignore

_ACCT = "123456789012"

# (model id, provider, name, input modalities, output modalities, streaming, customizations)
BEDROCK_MODELS = [
    ("anthropic.claude-3-haiku-20240307-v1:0", "Anthropic", "Claude 3 Haiku", ["TEXT", "IMAGE"], ["TEXT"], True),
    ("anthropic.claude-3-5-sonnet-20241022-v2:0", "Anthropic", "Claude 3.5 Sonnet v2", ["TEXT", "IMAGE"], ["TEXT"], True),
    ("anthropic.claude-sonnet-4-20250514-v1:0", "Anthropic", "Claude Sonnet 4", ["TEXT", "IMAGE"], ["TEXT"], True),
    ("amazon.titan-text-express-v1", "Amazon", "Titan Text G1 - Express", ["TEXT"], ["TEXT"], True),
    ("amazon.titan-text-lite-v1", "Amazon", "Titan Text G1 - Lite", ["TEXT"], ["TEXT"], True),
    ("amazon.titan-embed-text-v2:0", "Amazon", "Titan Text Embeddings V2", ["TEXT"], ["EMBEDDING"], False),
    ("amazon.nova-micro-v1:0", "Amazon", "Nova Micro", ["TEXT"], ["TEXT"], True),
    ("amazon.nova-lite-v1:0", "Amazon", "Nova Lite", ["TEXT", "IMAGE"], ["TEXT"], True),
    ("amazon.nova-pro-v1:0", "Amazon", "Nova Pro", ["TEXT", "IMAGE"], ["TEXT"], True),
    ("meta.llama3-8b-instruct-v1:0", "Meta", "Llama 3 8B Instruct", ["TEXT"], ["TEXT"], True),
    ("meta.llama3-1-8b-instruct-v1:0", "Meta", "Llama 3.1 8B Instruct", ["TEXT"], ["TEXT"], True),
    ("mistral.mistral-7b-instruct-v0:2", "Mistral AI", "Mistral 7B Instruct", ["TEXT"], ["TEXT"], True),
]
_BM = {m[0]: m for m in BEDROCK_MODELS}


def _j(status, doc, headers=None):
    h = {"content-type": "application/json"}
    h.update(headers or {})
    return {"status": status, "headers": h, "body": json.dumps(doc).encode()}


def _bytes(status, body: bytes, ctype, headers=None):
    return {"status": status, "headers": {"content-type": ctype, **(headers or {})}, "body": body}


def _body(raw):
    try:
        p = json.loads(raw) if raw else {}
    except ValueError:
        return None
    return p if isinstance(p, dict) else None


# ───────────────────────────── Bedrock ─────────────────────────────
def _b_err(code, msg, status):
    return _j(status, {"message": msg}, {"x-amzn-errortype": code})


def _resolve_model(mid):
    """Accept foundation-model ids, cross-Region inference profile ids (us./eu./apac. prefix) and their ARNs."""
    mid = re.sub(r"^arn:aws[a-z-]*:bedrock:[^:]*:[0-9]*:(foundation-model|inference-profile)/", "", mid)
    base = re.sub(r"^(us|eu|apac|us-gov|global)\.", "", mid)
    return _BM.get(base)


def _ll_err(e):
    return _b_err("ModelNotReadyException", f"{e} (the local model has not been started)", 429)


def _bedrock_text_request(m, p):
    """-> (messages, system, max_tokens, temperature, stop) from the family-specific InvokeModel body, or an error string."""
    mid = m[0]
    if mid.startswith("anthropic."):
        if "messages" not in p or not isinstance(p["messages"], list) or not p["messages"]:
            return "messages: field required"
        if "max_tokens" not in p:
            return "max_tokens: field required"
        if p.get("tools"):
            return "tools: tool use is not available on the local model"
        sysm = p.get("system")
        if isinstance(sysm, list):
            sysm = "".join(b.get("text", "") for b in sysm)
        return p["messages"], sysm, p["max_tokens"], p.get("temperature", 1.0), p.get("stop_sequences")
    if mid.startswith("amazon.titan-text"):
        if not p.get("inputText"):
            return "Malformed input request: required key [inputText] not found, please reformat your input and try again."
        c = p.get("textGenerationConfig") or {}
        return ([{"role": "user", "content": p["inputText"]}], None, c.get("maxTokenCount", 512), c.get("temperature", 0.7),
                c.get("stopSequences"))
    if mid.startswith("amazon.nova"):
        if not isinstance(p.get("messages"), list) or not p["messages"]:
            return "messages: field required"
        c = p.get("inferenceConfig") or {}
        sysm = "".join(b.get("text", "") for b in p.get("system") or [])
        return p["messages"], sysm, c.get("max_new_tokens", c.get("maxTokens", 512)), c.get("temperature", 0.7), c.get("stopSequences")
    if mid.startswith("meta."):
        if not p.get("prompt"):
            return "Malformed input request: required key [prompt] not found, please reformat your input and try again."
        return [{"role": "user", "content": p["prompt"]}], None, p.get("max_gen_len", 512), p.get("temperature", 0.5), None
    if mid.startswith("mistral."):
        if not p.get("prompt"):
            return "Malformed input request: required key [prompt] not found, please reformat your input and try again."
        return [{"role": "user", "content": p["prompt"]}], None, p.get("max_tokens", 512), p.get("temperature", 0.5), p.get("stop")
    return "this model does not support InvokeModel text generation"


def _stop_reason(fr):
    return "max_tokens" if fr == "length" else "end_turn"


def _bedrock_response(m, p, r):
    mid, txt = m[0], r["text"]
    if mid.startswith("anthropic."):
        return {"id": "msg_bdrk_" + uuid.uuid4().hex[:24], "type": "message", "role": "assistant", "model": mid,
                "content": [{"type": "text", "text": txt}], "stop_reason": _stop_reason(r["finish_reason"]),
                "stop_sequence": None, "usage": {"input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"]}}
    if mid.startswith("amazon.titan-text"):
        return {"inputTextTokenCount": r["input_tokens"], "results": [{"tokenCount": r["output_tokens"], "outputText": txt,
                "completionReason": "LENGTH" if r["finish_reason"] == "length" else "FINISH"}]}
    if mid.startswith("amazon.nova"):
        return {"output": {"message": {"role": "assistant", "content": [{"text": txt}]}}, "stopReason": _stop_reason(r["finish_reason"]),
                "usage": {"inputTokens": r["input_tokens"], "outputTokens": r["output_tokens"],
                          "totalTokens": r["input_tokens"] + r["output_tokens"]}}
    if mid.startswith("meta."):
        return {"generation": txt, "prompt_token_count": r["input_tokens"], "generation_token_count": r["output_tokens"],
                "stop_reason": "length" if r["finish_reason"] == "length" else "stop"}
    return {"outputs": [{"text": txt, "stop_reason": "length" if r["finish_reason"] == "length" else "stop"}]}


def _crc(b):
    return zlib.crc32(b) & 0xFFFFFFFF


def _evt_header(name, val):
    n, v = name.encode(), val.encode()
    return bytes([len(n)]) + n + b"\x07" + struct.pack(">H", len(v)) + v


def eventstream_frame(event_type: str, payload: dict | bytes, message_type="event", content_type="application/json") -> bytes:
    """One application/vnd.amazon.eventstream message (prelude + CRCs) as botocore/Java/Go parse it."""
    body = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode()
    hdrs = _evt_header(":event-type" if message_type == "event" else ":exception-type", event_type) \
        + _evt_header(":content-type", content_type) + _evt_header(":message-type", message_type)
    total = 12 + len(hdrs) + len(body) + 4
    prelude = struct.pack(">II", total, len(hdrs))
    head = prelude + struct.pack(">I", _crc(prelude)) + hdrs + body
    return head + struct.pack(">I", _crc(head))


def _chunks(text, n=12):
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]


def _converse_parts(p):
    msgs = p.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return "messages: at least one message is required"
    for mm in msgs:
        if mm.get("role") not in ("user", "assistant") or not isinstance(mm.get("content"), list):
            return "Invalid message: role must be user/assistant and content a list of content blocks"
        for blk in mm["content"]:
            if not isinstance(blk, dict) or set(blk) - {"text"}:
                return "Only text content blocks are supported by the local model (image/document/toolUse/toolResult are not)"
    if "toolConfig" in p:
        return "toolConfig is not supported by the local model"
    sysm = "".join(b.get("text", "") for b in p.get("system") or [])
    ic = p.get("inferenceConfig") or {}
    return msgs, sysm, ic.get("maxTokens", 512), ic.get("temperature", 0.7), ic.get("stopSequences")


def bedrock_dispatch(method, path, query, headers, body):
    method, path = method.upper(), "/" + path.strip("/")
    path = re.sub(r"/{2,}", "/", path)
    if path in ("/foundation-models",) and method == "GET":
        outm = (query or {}).get("byOutputModality")
        prov = (query or {}).get("byProvider")
        ms = [m for m in BEDROCK_MODELS if (not outm or outm.upper() in m[4]) and (not prov or prov.lower() == m[1].lower())]
        return _j(200, {"modelSummaries": [_summary(m) for m in ms]})
    mt = re.match(r"^/foundation-models/(.+)$", path)
    if mt and method == "GET":
        m = _BM.get(mt.group(1))
        if not m:
            return _b_err("ResourceNotFoundException", f"Could not resolve the foundation model from the provided model identifier.", 404)
        return _j(200, {"modelDetails": _summary(m)})
    mt = re.match(r"^/model/(.+?)/(invoke|invoke-with-response-stream|converse|converse-stream)$", path)
    if not mt:
        return _b_err("UnknownOperationException", f"Unsupported Bedrock operation: {method} {path}", 404)
    if method != "POST":
        return _b_err("UnknownOperationException", f"{method} is not supported for this operation", 405)
    from urllib.parse import unquote
    mid, op = unquote(mt.group(1)), mt.group(2)
    m = _resolve_model(mid)
    if not m:
        return _b_err("ValidationException", "The provided model identifier is invalid.", 400)
    p = _body(body)
    if p is None:
        return _b_err("ValidationException", "Malformed input request, please reformat your input and try again.", 400)
    t0 = time.time()
    if op.startswith("converse"):
        if m[5] is False and "TEXT" not in m[4]:
            return _b_err("ValidationException", f"This model doesn't support the {op} operation.", 400)
        parts = _converse_parts(p)
        if isinstance(parts, str):
            return _b_err("ValidationException", parts, 400)
        try:
            r = llm.chat(*parts)
        except llm.LlmUnavailable as e:
            return _ll_err(e)
        usage = {"inputTokens": r["input_tokens"], "outputTokens": r["output_tokens"], "totalTokens": r["input_tokens"] + r["output_tokens"]}
        lat = int((time.time() - t0) * 1000)
        if op == "converse":
            return _j(200, {"output": {"message": {"role": "assistant", "content": [{"text": r["text"]}]}},
                            "stopReason": _stop_reason(r["finish_reason"]), "usage": usage, "metrics": {"latencyMs": lat}})
        frames = [eventstream_frame("messageStart", {"role": "assistant"})]
        frames += [eventstream_frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": c}}) for c in _chunks(r["text"])]
        frames += [eventstream_frame("contentBlockStop", {"contentBlockIndex": 0}),
                   eventstream_frame("messageStop", {"stopReason": _stop_reason(r["finish_reason"])}),
                   eventstream_frame("metadata", {"usage": usage, "metrics": {"latencyMs": lat}})]
        return _bytes(200, b"".join(frames), "application/vnd.amazon.eventstream")
    # InvokeModel[WithResponseStream]
    if m[0].startswith("amazon.titan-embed"):
        if op != "invoke":
            return _b_err("ValidationException", "This model doesn't support the InvokeModelWithResponseStream operation.", 400)
        if not isinstance(p.get("inputText"), str) or not p["inputText"]:
            return _b_err("ValidationException", "Malformed input request: required key [inputText] not found, please reformat your input and try again.", 400)
        dim = int(p.get("dimensions") or 1024)
        if dim not in (256, 512, 1024):
            return _b_err("ValidationException", "dimensions must be one of 256, 512 or 1024.", 400)
        e = llm.embed(p["inputText"])
        v = (e["vectors"][0] + [0.0] * dim)[:dim]
        return _j(200, {"embedding": v, "inputTextTokenCount": e["input_tokens"]},
                  {"x-amzn-bedrock-input-token-count": str(e["input_tokens"])})
    req = _bedrock_text_request(m, p)
    if isinstance(req, str):
        return _b_err("ValidationException", req, 400)
    try:
        r = llm.chat(*req)
    except llm.LlmUnavailable as e:
        return _ll_err(e)
    resp = _bedrock_response(m, p, r)
    hh = {"x-amzn-bedrock-input-token-count": str(r["input_tokens"]), "x-amzn-bedrock-output-token-count": str(r["output_tokens"]),
          "x-amzn-bedrock-invocation-latency": str(int((time.time() - t0) * 1000))}
    if op == "invoke":
        return _j(200, resp, hh)
    frames = []
    for c in _chunks(json.dumps(resp), 4096):
        frames.append(eventstream_frame("chunk", {"bytes": base64.b64encode(c.encode()).decode()}))
    return _bytes(200, b"".join(frames), "application/vnd.amazon.eventstream", hh)


def _summary(m):
    return {"modelArn": f"arn:aws:bedrock:us-east-1::foundation-model/{m[0]}", "modelId": m[0], "modelName": m[2],
            "providerName": m[1], "inputModalities": m[3], "outputModalities": m[4], "responseStreamingSupported": m[5],
            "customizationsSupported": [], "inferenceTypesSupported": ["ON_DEMAND"], "modelLifecycle": {"status": "ACTIVE"}}


# ───────────────────────────── Vertex AI ─────────────────────────────
GEMINI_MODELS = ("gemini-2.0-flash", "gemini-2.0-flash-001", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro")
GEMINI_EMBED = ("text-embedding-004", "text-embedding-005", "gemini-embedding-001", "textembedding-gecko@003")


def _g_err(status, st, msg):
    return _j(status, {"error": {"code": status, "message": msg, "status": st}})


def vertex_dispatch(method, path, query, headers, body):
    mt = re.match(r"^/v1(?:beta1)?/projects/([^/]+)/locations/([^/]+)/publishers/([^/]+)/models/([^/:]+):([A-Za-z]+)$", path)
    if not mt or method.upper() != "POST":
        return _g_err(404, "NOT_FOUND", f"Unsupported Vertex AI operation: {method} {path}")
    proj, loc, pub, model, op = mt.groups()
    p = _body(body)
    if p is None:
        return _g_err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if pub != "google" or (model not in GEMINI_MODELS and model not in GEMINI_EMBED):
        return _g_err(404, "NOT_FOUND", f"Publisher Model `projects/{proj}/locations/{loc}/publishers/{pub}/models/{model}` was not found "
                                         "or your project does not have access to it.")
    if op in ("embedContent", "predict") or model in GEMINI_EMBED:
        if model not in GEMINI_EMBED:
            return _g_err(400, "FAILED_PRECONDITION", f"{model} does not support {op}.")
        if op == "predict":
            insts = [i.get("content", "") for i in p.get("instances") or []]
            if not insts:
                return _g_err(400, "INVALID_ARGUMENT", "instances: at least one instance is required.")
            e = llm.embed(insts)
            return _j(200, {"predictions": [{"embeddings": {"values": v, "statistics": {"token_count": llm.estimate_tokens(t), "truncated": False}}}
                                            for v, t in zip(e["vectors"], insts)]})
        txt = "".join(x.get("text", "") for x in ((p.get("content") or {}).get("parts") or []))
        if not txt:
            return _g_err(400, "INVALID_ARGUMENT", "content.parts: at least one text part is required.")
        return _j(200, {"embedding": {"values": llm.embed(txt)["vectors"][0]}})
    contents = p.get("contents")
    if op in ("generateContent", "streamGenerateContent", "countTokens"):
        if not isinstance(contents, list) or not contents:
            return _g_err(400, "INVALID_ARGUMENT", "Unable to submit request because at least one contents field is required.")
        msgs = []
        for c in contents:
            parts = c.get("parts") or []
            if any(set(pt) - {"text"} for pt in parts):
                return _g_err(400, "INVALID_ARGUMENT", "Only text parts are supported by the local model (inlineData/fileData/functionCall are not).")
            msgs.append({"role": "assistant" if c.get("role") == "model" else "user", "content": "".join(pt.get("text", "") for pt in parts)})
        if p.get("tools"):
            return _g_err(400, "INVALID_ARGUMENT", "tools are not supported by the local model.")
        si = "".join(pt.get("text", "") for pt in ((p.get("systemInstruction") or {}).get("parts") or []))
        if op == "countTokens":
            n = sum(llm.estimate_tokens(m["content"]) for m in msgs) + llm.estimate_tokens(si)
            return _j(200, {"totalTokens": n, "totalBillableCharacters": sum(len(m["content"]) for m in msgs)})
        gc = p.get("generationConfig") or {}
        try:
            r = llm.chat(msgs, si or None, gc.get("maxOutputTokens", 512), gc.get("temperature", 1.0), gc.get("stopSequences"))
        except llm.LlmUnavailable as e:
            return _g_err(503, "UNAVAILABLE", f"{e}")
        fin = "MAX_TOKENS" if r["finish_reason"] == "length" else "STOP"
        usage = {"promptTokenCount": r["input_tokens"], "candidatesTokenCount": r["output_tokens"],
                 "totalTokenCount": r["input_tokens"] + r["output_tokens"]}

        def cand(text, last):
            c = {"content": {"role": "model", "parts": [{"text": text}]}, "index": 0}
            if last:
                c["finishReason"] = fin
            return c
        if op == "generateContent":
            return _j(200, {"candidates": [cand(r["text"], True)], "usageMetadata": usage, "modelVersion": model,
                            "responseId": uuid.uuid4().hex[:20]})
        cs = _chunks(r["text"], 24)
        arr = [{"candidates": [cand(c, i == len(cs) - 1)], "modelVersion": model, **({"usageMetadata": usage} if i == len(cs) - 1 else {})}
               for i, c in enumerate(cs)]
        if (query or {}).get("alt") == "sse":
            return _bytes(200, "".join("data: " + json.dumps(a) + "\r\n\r\n" for a in arr).encode(), "text/event-stream")
        return _j(200, arr)
    return _g_err(404, "NOT_FOUND", f"Unsupported Vertex AI method :{op}")


# ───────────────────────────── Azure OpenAI ─────────────────────────────
def _a_err(status, code, msg, param=None):
    return _j(status, {"error": {"code": code, "message": msg, "param": param, "type": None, "inner_error": None}})


def _find_deployment(arm_state, name):
    for rec in (arm_state or {}).values():
        if str(rec.get("_type", "")).lower() != "microsoft.cognitiveservices/accounts":
            continue
        if rec.get("kind") not in ("OpenAI", "AIServices"):
            continue
        d = (rec.get("_deployments") or {}).get(str(name).lower())
        if d:
            return rec, d
    return None, None


def azure_openai_dispatch(arm_state, method, path, query, headers, body):
    mt = re.match(r"^/openai/(?:deployments/([^/]+)/)?(chat/completions|completions|embeddings)$", path) \
        or re.match(r"^/openai/v1/()(chat/completions|completions|embeddings|responses)$", path)
    if not mt or method.upper() != "POST":
        return _a_err(404, "404", "Resource not found")
    p = _body(body)
    if p is None:
        return _a_err(400, "BadRequest", "Invalid JSON body.")
    dep_name, op = mt.group(1) or p.get("model"), mt.group(2)
    if not dep_name:
        return _a_err(400, "BadRequest", "Missing required parameter: 'model'.", "model")
    lh = {k.lower(): v for k, v in (headers or {}).items()}
    if not (lh.get("api-key") or lh.get("authorization")):
        return _j(401, {"error": {"code": "401", "message": "Access denied due to missing subscription key. Make sure to include "
                                                          "subscription key when making requests to an API."}})
    acct, dep = _find_deployment(arm_state, dep_name)
    if not dep:
        return _a_err(404, "DeploymentNotFound", "The API deployment for this resource does not exist. If you created the deployment "
                      "within the last 5 minutes, please wait a moment and try again.")
    model = dep["properties"]["model"]["name"]
    caps = dep["properties"].get("capabilities") or {}
    if op == "embeddings":
        if "embeddings" not in caps and "embedding" not in model:
            return _a_err(400, "OperationNotSupported", f"The embeddings operation does not work with the specified model, {model}. "
                          "Please choose different model and try again.")
        inp = p.get("input")
        if inp in (None, "", []):
            return _a_err(400, "BadRequest", "'input' is a required property.", "input")
        e = llm.embed(inp if isinstance(inp, list) else [inp], p.get("dimensions"))
        return _j(200, {"object": "list", "model": model, "usage": {"prompt_tokens": e["input_tokens"], "total_tokens": e["input_tokens"]},
                        "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(e["vectors"])]})
    if "embedding" in model:
        return _a_err(400, "OperationNotSupported", f"The {op} operation does not work with the specified model, {model}. "
                      "Please choose different model and try again.")
    if p.get("tools") or p.get("functions") or p.get("response_format", {}).get("type") == "json_schema":
        return _a_err(400, "BadRequest", "tools/functions/structured outputs are not supported by the local model.", "tools")
    if op == "completions":
        if not p.get("prompt"):
            return _a_err(400, "BadRequest", "'prompt' is a required property.", "prompt")
        msgs = [{"role": "user", "content": p["prompt"] if isinstance(p["prompt"], str) else "\n".join(p["prompt"])}]
    else:
        msgs = p.get("messages")
        if not isinstance(msgs, list) or not msgs:
            return _a_err(400, "BadRequest", "'messages' is a required property.", "messages")
        if any(m.get("role") not in ("system", "developer", "user", "assistant") for m in msgs):
            return _a_err(400, "BadRequest", "Invalid value for 'role' in messages.", "messages")
        msgs = [{**m, "role": "system" if m["role"] == "developer" else m["role"]} for m in msgs]
    mx = p.get("max_completion_tokens") or p.get("max_tokens") or 512
    try:
        r = llm.chat(msgs, None, mx, p.get("temperature", 1.0), [p["stop"]] if isinstance(p.get("stop"), str) else p.get("stop"))
    except llm.LlmUnavailable as e:
        return _a_err(503, "ServiceUnavailable", f"{e}")
    fin = "length" if r["finish_reason"] == "length" else "stop"
    cid, now = ("chatcmpl-" if op == "chat/completions" else "cmpl-") + uuid.uuid4().hex[:29], int(time.time())
    usage = {"prompt_tokens": r["input_tokens"], "completion_tokens": r["output_tokens"], "total_tokens": r["input_tokens"] + r["output_tokens"]}
    if p.get("stream") and op == "chat/completions":
        parts = _chunks(r["text"], 12)
        evs = [{"id": cid, "object": "chat.completion.chunk", "created": now, "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]}]
        evs += [{"id": cid, "object": "chat.completion.chunk", "created": now, "model": model,
                 "choices": [{"index": 0, "delta": {"content": c}, "finish_reason": None}]} for c in parts]
        evs.append({"id": cid, "object": "chat.completion.chunk", "created": now, "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": fin}]})
        return _bytes(200, ("".join("data: " + json.dumps(e) + "\n\n" for e in evs) + "data: [DONE]\n\n").encode(), "text/event-stream")
    if op == "completions":
        return _j(200, {"id": cid, "object": "text_completion", "created": now, "model": model,
                        "choices": [{"text": r["text"], "index": 0, "finish_reason": fin, "logprobs": None}], "usage": usage})
    return _j(200, {"id": cid, "object": "chat.completion", "created": now, "model": model,
                    "choices": [{"index": 0, "finish_reason": fin, "message": {"role": "assistant", "content": r["text"]}}],
                    "usage": usage, "system_fingerprint": "fp_vyomi_local"})
