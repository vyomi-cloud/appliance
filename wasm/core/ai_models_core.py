# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Model-inference wire adapters over the shared local-LLM seam (core/llm_core): Bedrock Runtime, Vertex AI Gemini, Azure OpenAI.

Each ``*_dispatch`` returns ``{"status", "headers", "body": bytes}`` (the AwsWireRouter result shape) and keeps its OWN cloud's
request/response/error shapes - nothing falls through to another cloud's handler.

Bedrock (signing name ``bedrock``): POST /model/{id}/invoke, /invoke-with-response-stream, /converse, /converse-stream
(real vnd.amazon.eventstream framing), GET /foundation-models[/{id}] (ListFoundationModels/GetFoundationModel). Body formats for the
Anthropic Claude Messages, Amazon Titan Text / Titan Embeddings, Amazon Nova, Meta Llama and Mistral families.
Vertex AI: POST .../publishers/google/models/{model}:generateContent | :streamGenerateContent | :countTokens | :embedContent | :predict.
Azure OpenAI: POST /openai/deployments/{deployment}/chat/completions | /completions | /embeddings (and /openai/v1/... with `model` in
the body); the deployment must exist under a Cognitive Services OpenAI/AIServices account (ARM state) - DeploymentNotFound otherwise.

Tool/function calling (Bedrock Converse + Claude/Nova InvokeModel toolConfig/toolUse/toolResult, Vertex functionDeclarations/
functionCall/functionResponse, Azure tools/tool_calls), structured output (Vertex responseSchema, Azure json_object/json_schema,
Bedrock Converse outputConfig.textFormat) and per-request model selection go through the seam (core/llm_core); plain chat streams
token-by-token from the backend when it can (set ``STREAM_OK`` so the HTTP layer receives ``stream`` generators).

Honest limit: one small local model answers for every model id/deployment (see core/llm_core.HONEST_LIMIT); tool calls from a
1-3B model are validated and retried by the seam but are weaker than the real models. Images, guardrails, prompt caching and
fine-tuned/provisioned throughput are not modelled; they are rejected with the cloud's validation error rather than ignored.
"""
from __future__ import annotations

import base64
import contextvars
import itertools
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


# True while the HTTP layer can forward a ``stream`` generator in the result (core/wire_ingress.serve sets it); otherwise the
# generator is drained into ``body`` (Nano relay, tests, ARM proxy) so every consumer of the result shape keeps working.
STREAM_OK = contextvars.ContextVar("vyomi_ai_stream_ok", default=False)


def _stream_out(status, headers, gen, ctype):
    if STREAM_OK.get():
        return {"status": status, "headers": {"content-type": ctype, **(headers or {})}, "body": b"", "stream": gen}
    return _bytes(status, b"".join(x if isinstance(x, bytes) else x.encode() for x in gen), ctype, headers)


def _prime(it):
    """Pull the first seam event so a dead/invalid model fails the request with a proper status, not mid-stream."""
    first = next(it)
    return itertools.chain([first], it)


def _llm_chat(req):
    """req = (messages, system, max_tokens, temperature, stop, extras) -> seam chat()."""
    return llm.chat(*req[:5], **req[5])


def _json_text(x):
    return x if isinstance(x, str) else json.dumps(x, separators=(",", ":"))


# ───────────────────────────── Bedrock ─────────────────────────────
def _b_err(code, msg, status):
    return _j(status, {"message": msg}, {"x-amzn-errortype": code})


def _resolve_model(mid):
    """Accept foundation-model ids, cross-Region inference profile ids (us./eu./apac. prefix) and their ARNs."""
    mid = re.sub(r"^arn:aws[a-z-]*:bedrock:[^:]*:[0-9]*:(foundation-model|inference-profile)/", "", mid)
    base = re.sub(r"^(us|eu|apac|us-gov|global)\.", "", mid)
    return _BM.get(base)


def _ll_err(e):
    if isinstance(e, llm.LlmStructuredError):
        return _b_err("ModelErrorException", str(e), 424)
    return _b_err("ModelNotReadyException", f"{e} (the local model has not been started)", 429)


_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _br_tool_result_text(content):
    """Converse toolResult.content blocks / Claude tool_result content -> text the model reads (or an error string)."""
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if not isinstance(b, dict):
            return "toolResult content must be a list of blocks"
        if "text" in b or b.get("type") == "text":
            out.append(b.get("text", ""))
        elif "json" in b:
            out.append(json.dumps(b["json"]))
        else:
            return "Only text and json toolResult content is supported by the local model (image/document are not)"
    return "\n".join(out)


def _converse_tools(tc):
    """toolConfig -> (tools, tool_choice) or an error string."""
    if not isinstance(tc, dict) or not isinstance(tc.get("tools"), list) or not tc["tools"]:
        return "toolConfig.tools: at least one tool is required"
    tools = []
    for t in tc["tools"]:
        if not isinstance(t, dict):
            return "toolConfig.tools: each tool must be an object"
        if "cachePoint" in t and "toolSpec" not in t:
            continue
        spec = t.get("toolSpec")
        if not isinstance(spec, dict) or not _TOOL_NAME.match(str(spec.get("name", ""))):
            return "toolConfig.tools.toolSpec.name must match [a-zA-Z0-9_-]{1,64}"
        sch = (spec.get("inputSchema") or {}).get("json")
        if not isinstance(sch, dict):
            return "toolConfig.tools.toolSpec.inputSchema.json is required"
        tools.append({"name": spec["name"], "description": spec.get("description", ""), "parameters": sch})
    if not tools:
        return "toolConfig.tools: at least one toolSpec is required"
    ch = tc.get("toolChoice")
    if not ch:
        return tools, "auto"
    if "auto" in ch:
        return tools, "auto"
    if "any" in ch:
        return tools, "required"
    if "tool" in ch and (ch["tool"] or {}).get("name") in [t["name"] for t in tools]:
        return tools, {"name": ch["tool"]["name"]}
    return "toolConfig.toolChoice must be auto, any, or tool with the name of a defined tool"


def _converse_messages(msgs_in):
    out, pending = [], {}
    if not isinstance(msgs_in, list) or not msgs_in:
        return "messages: at least one message is required"
    for mm in msgs_in:
        if not isinstance(mm, dict) or mm.get("role") not in ("user", "assistant") or not isinstance(mm.get("content"), list):
            return "Invalid message: role must be user/assistant and content a list of content blocks"
        texts, calls, results = [], [], []
        for blk in mm["content"]:
            if not isinstance(blk, dict):
                return "Invalid content block"
            keys = set(blk) - {"cachePoint"}
            if len(keys) != 1 or not keys <= {"text", "toolUse", "toolResult"}:
                return "Only text, toolUse and toolResult content blocks are supported by the local model (image/document/video are not)"
            if "text" in blk:
                texts.append(str(blk["text"]))
            elif "toolUse" in blk:
                tu = blk["toolUse"] or {}
                if mm["role"] != "assistant" or not tu.get("name") or not tu.get("toolUseId") or not isinstance(tu.get("input", {}), dict):
                    return "Invalid toolUse block: needs toolUseId, name and an object input, in an assistant message"
                calls.append({"id": tu["toolUseId"], "name": tu["name"], "arguments": tu.get("input") or {}})
                pending[tu["toolUseId"]] = tu["name"]
            else:
                tr = blk["toolResult"] or {}
                if mm["role"] != "user" or not tr.get("toolUseId"):
                    return "Invalid toolResult block: needs toolUseId, in a user message"
                txt = _br_tool_result_text(tr.get("content"))
                if txt in ("toolResult content must be a list of blocks",) or txt.startswith("Only text and json"):
                    return txt
                results.append({"role": "tool", "tool_call_id": tr["toolUseId"], "name": pending.get(tr["toolUseId"], ""),
                                "content": ("[tool error] " if tr.get("status") == "error" else "") + txt})
        out += results
        if mm["role"] == "assistant":
            m = {"role": "assistant", "content": "".join(texts)}
            if calls:
                m["tool_calls"] = calls
            out.append(m)
        elif texts:
            out.append({"role": "user", "content": "".join(texts)})
    return out


def _converse_request(p, mid, max_key="maxTokens"):
    """Converse (and Nova InvokeModel) body -> (messages, system, max_tokens, temperature, stop, extras) or an error string."""
    msgs = _converse_messages(p.get("messages"))
    if isinstance(msgs, str):
        return msgs
    if "guardrailConfig" in p:
        return "guardrailConfig is not supported by the local model (guardrails are not modelled)"
    ex = {"model": mid}
    ic = p.get("inferenceConfig") or {}
    if ic.get("topP") is not None:
        ex["top_p"] = ic["topP"]
    if "toolConfig" in p:
        tc = _converse_tools(p["toolConfig"])
        if isinstance(tc, str):
            return tc
        ex["tools"], ex["tool_choice"] = tc
    oc = ((p.get("outputConfig") or {}).get("textFormat") or {})
    if oc:
        if oc.get("type") != "json_schema":
            return "outputConfig.textFormat.type must be json_schema"
        js = ((oc.get("structure") or {}).get("jsonSchema") or {})
        try:
            sch = json.loads(js["schema"]) if isinstance(js.get("schema"), str) else js.get("schema")
        except ValueError:
            sch = None
        if not isinstance(sch, dict):
            return "outputConfig.textFormat.structure.jsonSchema.schema must be a JSON schema document"
        ex["response_format"] = {"type": "json_schema", "schema": sch, "name": js.get("name") or "response"}
    sysm = "".join(b.get("text", "") for b in p.get("system") or [] if isinstance(b, dict))
    return msgs, sysm, ic.get(max_key, ic.get("maxTokens", 512)), ic.get("temperature", 0.7), ic.get("stopSequences"), ex


def _claude_request(p, mid):
    """Anthropic Messages body (Bedrock InvokeModel) -> seam request, with tools / tool_use / tool_result blocks."""
    if "messages" not in p or not isinstance(p["messages"], list) or not p["messages"]:
        return "messages: field required"
    if "max_tokens" not in p:
        return "max_tokens: field required"
    out, pending = [], {}
    for mm in p["messages"]:
        c = mm.get("content") if isinstance(mm, dict) else None
        if mm.get("role") not in ("user", "assistant"):
            return "messages.role: must be user or assistant"
        if isinstance(c, str):
            out.append({"role": mm["role"], "content": c})
            continue
        if not isinstance(c, list):
            return "messages.content: must be a string or a list of content blocks"
        texts, calls, results = [], [], []
        for b in c:
            ty = b.get("type") if isinstance(b, dict) else None
            if ty == "text":
                texts.append(b.get("text", ""))
            elif ty == "tool_use" and mm["role"] == "assistant":
                calls.append({"id": b.get("id"), "name": b.get("name"), "arguments": b.get("input") or {}})
                pending[b.get("id")] = b.get("name")
            elif ty == "tool_result" and mm["role"] == "user":
                txt = _br_tool_result_text(b.get("content", ""))
                if txt.startswith("Only text") or txt.startswith("toolResult content"):
                    return txt
                results.append({"role": "tool", "tool_call_id": b.get("tool_use_id", ""), "name": pending.get(b.get("tool_use_id"), ""),
                                "content": ("[tool error] " if b.get("is_error") else "") + txt})
            else:
                return f"messages.content: block type {ty!r} is not supported by the local model (image/document/thinking are not)"
        out += results
        if mm["role"] == "assistant":
            m = {"role": "assistant", "content": "".join(texts)}
            if calls:
                m["tool_calls"] = calls
            out.append(m)
        elif texts:
            out.append({"role": "user", "content": "".join(texts)})
    ex = {"model": mid}
    if p.get("top_p") is not None:
        ex["top_p"] = p["top_p"]
    if p.get("tools"):
        ex["tools"] = []
        for t in p["tools"]:
            if not isinstance(t, dict) or not t.get("name") or not isinstance(t.get("input_schema"), dict):
                return "tools: each tool needs name and an input_schema object (server tools are not supported)"
            ex["tools"].append({"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]})
        tcx = p.get("tool_choice") or {"type": "auto"}
        ty = tcx.get("type")
        if ty == "any":
            ex["tool_choice"] = "required"
        elif ty == "tool" and tcx.get("name") in [t["name"] for t in ex["tools"]]:
            ex["tool_choice"] = {"name": tcx["name"]}
        elif ty == "none":
            ex["tool_choice"] = "none"
        elif ty in (None, "auto"):
            ex["tool_choice"] = "auto"
        else:
            return "tool_choice: must be auto, any, none, or tool with the name of a defined tool"
    sysm = p.get("system")
    if isinstance(sysm, list):
        sysm = "".join(b.get("text", "") for b in sysm)
    return out, sysm, p["max_tokens"], p.get("temperature", 1.0), p.get("stop_sequences"), ex


def _bedrock_text_request(m, p):
    """-> (messages, system, max_tokens, temperature, stop, extras) from the family-specific InvokeModel body, or an error string."""
    mid = m[0]
    if mid.startswith("anthropic."):
        return _claude_request(p, mid)
    if mid.startswith("amazon.titan-text"):
        if not p.get("inputText"):
            return "Malformed input request: required key [inputText] not found, please reformat your input and try again."
        c = p.get("textGenerationConfig") or {}
        return ([{"role": "user", "content": p["inputText"]}], None, c.get("maxTokenCount", 512), c.get("temperature", 0.7),
                c.get("stopSequences"), {"model": mid, **({"top_p": c["topP"]} if c.get("topP") is not None else {})})
    if mid.startswith("amazon.nova"):
        if not isinstance(p.get("messages"), list) or not p["messages"]:
            return "messages: field required"
        return _converse_request(p, mid, "max_new_tokens")
    if mid.startswith("meta."):
        if not p.get("prompt"):
            return "Malformed input request: required key [prompt] not found, please reformat your input and try again."
        return [{"role": "user", "content": p["prompt"]}], None, p.get("max_gen_len", 512), p.get("temperature", 0.5), None, {"model": mid}
    if mid.startswith("mistral."):
        if not p.get("prompt"):
            return "Malformed input request: required key [prompt] not found, please reformat your input and try again."
        return [{"role": "user", "content": p["prompt"]}], None, p.get("max_tokens", 512), p.get("temperature", 0.5), p.get("stop"), {"model": mid}
    return "this model does not support InvokeModel text generation"


def _stop_reason(fr):
    return "max_tokens" if fr == "length" else ("tool_use" if fr == "tool_calls" else "end_turn")


def _converse_content(r):
    content = [{"text": r["text"]}] if (r["text"] or not r.get("tool_calls")) else []
    content += [{"toolUse": {"toolUseId": c["id"], "name": c["name"], "input": c["arguments"]}} for c in r.get("tool_calls") or []]
    return content


def _bedrock_response(m, p, r):
    mid, txt = m[0], r["text"]
    if mid.startswith("anthropic."):
        content = [{"type": "text", "text": txt}] if (txt or not r.get("tool_calls")) else []
        content += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]} for c in r.get("tool_calls") or []]
        return {"id": "msg_bdrk_" + uuid.uuid4().hex[:24], "type": "message", "role": "assistant", "model": mid,
                "content": content, "stop_reason": "tool_use" if r.get("tool_calls") else ("max_tokens" if r["finish_reason"] == "length" else "end_turn"),
                "stop_sequence": None, "usage": {"input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"]}}
    if mid.startswith("amazon.titan-text"):
        return {"inputTextTokenCount": r["input_tokens"], "results": [{"tokenCount": r["output_tokens"], "outputText": txt,
                "completionReason": "LENGTH" if r["finish_reason"] == "length" else "FINISH"}]}
    if mid.startswith("amazon.nova"):
        return {"output": {"message": {"role": "assistant", "content": _converse_content(r)}}, "stopReason": _stop_reason(r["finish_reason"]),
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


def _converse_frames(it, t0):
    """Seam events -> Converse stream frames: text deltas as they arrive; toolUse blocks start/delta(input fragments)/stop."""
    yield eventstream_frame("messageStart", {"role": "assistant"})
    idx, text_idx, tool_open, tool_blk, got_args = -1, None, None, {}, set()
    try:
        for ev in it:
            ty = ev["type"]
            if ty == "text":
                if text_idx is None:
                    idx += 1
                    text_idx = idx
                yield eventstream_frame("contentBlockDelta", {"contentBlockIndex": text_idx, "delta": {"text": ev["text"]}})
            elif ty == "tool_start":
                if text_idx is not None:
                    yield eventstream_frame("contentBlockStop", {"contentBlockIndex": text_idx})
                    text_idx = None
                if tool_open is not None:
                    if tool_open not in got_args:
                        yield eventstream_frame("contentBlockDelta", {"contentBlockIndex": tool_blk[tool_open], "delta": {"toolUse": {"input": "{}"}}})
                    yield eventstream_frame("contentBlockStop", {"contentBlockIndex": tool_blk[tool_open]})
                idx += 1
                tool_blk[ev["index"]], tool_open = idx, ev["index"]
                yield eventstream_frame("contentBlockStart", {"contentBlockIndex": idx, "start": {"toolUse": {"toolUseId": ev["id"], "name": ev["name"]}}})
            elif ty == "tool_args":
                got_args.add(ev["index"])
                yield eventstream_frame("contentBlockDelta", {"contentBlockIndex": tool_blk[ev["index"]], "delta": {"toolUse": {"input": ev["fragment"]}}})
            else:
                if text_idx is not None:
                    yield eventstream_frame("contentBlockStop", {"contentBlockIndex": text_idx})
                if tool_open is not None:
                    if tool_open not in got_args:
                        yield eventstream_frame("contentBlockDelta", {"contentBlockIndex": tool_blk[tool_open], "delta": {"toolUse": {"input": "{}"}}})
                    yield eventstream_frame("contentBlockStop", {"contentBlockIndex": tool_blk[tool_open]})
                if idx < 0:
                    yield eventstream_frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": ""}})
                    yield eventstream_frame("contentBlockStop", {"contentBlockIndex": 0})
                yield eventstream_frame("messageStop", {"stopReason": _stop_reason(ev["finish_reason"])})
                yield eventstream_frame("metadata", {"usage": {"inputTokens": ev["input_tokens"], "outputTokens": ev["output_tokens"],
                                                                "totalTokens": ev["input_tokens"] + ev["output_tokens"]},
                                                      "metrics": {"latencyMs": int((time.time() - t0) * 1000)}})
    except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
        yield eventstream_frame("modelStreamErrorException", {"message": str(e)}, message_type="exception")



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
        req = _converse_request(p, m[0])
        if isinstance(req, str):
            return _b_err("ValidationException", req, 400)
        try:
            if op == "converse-stream":
                it = _prime(llm.chat_stream(*req[:5], **req[5]))
            else:
                r = _llm_chat(req)
        except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
            return _ll_err(e)
        except ValueError as e:
            return _b_err("ValidationException", str(e), 400)
        if op == "converse":
            usage = {"inputTokens": r["input_tokens"], "outputTokens": r["output_tokens"], "totalTokens": r["input_tokens"] + r["output_tokens"]}
            return _j(200, {"output": {"message": {"role": "assistant", "content": _converse_content(r)}},
                            "stopReason": _stop_reason(r["finish_reason"]), "usage": usage,
                            "metrics": {"latencyMs": int((time.time() - t0) * 1000)}}, {"x-vyomi-local-model": r["model"]})
        return _stream_out(200, {}, _converse_frames(it, t0), "application/vnd.amazon.eventstream")
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
        r = _llm_chat(req)
    except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
        return _ll_err(e)
    except ValueError as e:
        return _b_err("ValidationException", str(e), 400)
    resp = _bedrock_response(m, p, r)
    hh = {"x-amzn-bedrock-input-token-count": str(r["input_tokens"]), "x-amzn-bedrock-output-token-count": str(r["output_tokens"]),
          "x-amzn-bedrock-invocation-latency": str(int((time.time() - t0) * 1000)), "x-vyomi-local-model": r["model"]}
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


def _lower_types(sch):
    """Gemini's OpenAPI-style schema (types in CAPS, nullable) -> JSON Schema the seam validates/constrains with."""
    if isinstance(sch, list):
        return [_lower_types(x) for x in sch]
    if not isinstance(sch, dict):
        return sch
    out = {}
    for k, v in sch.items():
        if k == "type" and isinstance(v, str):
            out[k] = v.lower()
        elif k in ("properties",) and isinstance(v, dict):
            out[k] = {pk: _lower_types(pv) for pk, pv in v.items()}
        elif k in ("items", "anyOf", "oneOf", "allOf", "additionalProperties"):
            out[k] = _lower_types(v)
        elif k == "propertyOrdering" or k == "nullable":
            continue
        else:
            out[k] = v
    if sch.get("nullable") and isinstance(out.get("type"), str):
        out["type"] = [out["type"], "null"]
    return out


def _gem_request(p):
    """Gemini generateContent body -> (messages, system, max_tokens, temperature, stop, extras) or an error string."""
    contents = p.get("contents")
    msgs, pending = [], []
    for c in contents:
        if not isinstance(c, dict):
            return "contents: each content must be an object"
        texts, calls, results = [], [], []
        for pt in c.get("parts") or []:
            keys = set(pt) - {"thought", "thoughtSignature"}
            if keys == {"text"}:
                texts.append(pt["text"])
            elif keys == {"functionCall"}:
                fc = pt["functionCall"] or {}
                if not fc.get("name"):
                    return "functionCall.name is required"
                cid = fc.get("id") or "call_" + uuid.uuid4().hex[:24]
                calls.append({"id": cid, "name": fc["name"], "arguments": fc.get("args") or {}})
                pending.append((cid, fc["name"]))
            elif keys == {"functionResponse"}:
                fr = pt["functionResponse"] or {}
                name = fr.get("name")
                if not name:
                    return "functionResponse.name is required"
                hit = next((x for x in pending if x[1] == name), None)
                if hit:
                    pending.remove(hit)
                results.append({"role": "tool", "tool_call_id": (hit or (fr.get("id") or "call_" + uuid.uuid4().hex[:24],))[0], "name": name,
                                "content": json.dumps(fr.get("response", {}))})
            else:
                return "Only text, functionCall and functionResponse parts are supported by the local model (inlineData/fileData are not)."
        if calls or texts:
            if c.get("role") == "model" or calls:
                m = {"role": "assistant", "content": "".join(texts)}
                if calls:
                    m["tool_calls"] = calls
                msgs.append(m)
            else:
                msgs.append({"role": "user", "content": "".join(texts)})
        msgs += results
    ex = {}
    tools = []
    for t in p.get("tools") or []:
        unknown = set(t) - {"functionDeclarations"}
        if unknown:
            return f"tools.{sorted(unknown)[0]} is not supported by the local model (only functionDeclarations)."
        for fd in t.get("functionDeclarations") or []:
            if not fd.get("name"):
                return "functionDeclarations.name is required"
            sch = fd.get("parametersJsonSchema") or _lower_types(fd.get("parameters")) or {"type": "object", "properties": {}}
            tools.append({"name": fd["name"], "description": fd.get("description", ""), "parameters": sch})
    if p.get("tools") and not tools:
        return "tools: at least one functionDeclaration is required"
    if tools:
        fcc = ((p.get("toolConfig") or {}).get("functionCallingConfig") or {})
        mode = (fcc.get("mode") or "AUTO").upper()
        allowed = fcc.get("allowedFunctionNames") or []
        if allowed:
            if not set(allowed) <= {t["name"] for t in tools}:
                return "toolConfig.functionCallingConfig.allowedFunctionNames names an undeclared function"
            tools = [t for t in tools if t["name"] in allowed]
        if mode == "NONE":
            ex["tool_choice"] = "none"
        elif mode in ("ANY", "VALIDATED"):
            ex["tool_choice"] = {"name": tools[0]["name"]} if len(tools) == 1 else "required"
        elif mode == "AUTO":
            ex["tool_choice"] = "auto"
        else:
            return "toolConfig.functionCallingConfig.mode must be AUTO, ANY or NONE"
        ex["tools"] = tools
    elif p.get("toolConfig"):
        return "toolConfig requires tools"
    gc = p.get("generationConfig") or {}
    mime = gc.get("responseMimeType")
    if mime == "application/json":
        sch = gc.get("responseJsonSchema") or _lower_types(gc.get("responseSchema"))
        ex["response_format"] = {"type": "json_schema", "schema": sch, "name": "response"} if sch else {"type": "json_object"}
    elif gc.get("responseSchema") or gc.get("responseJsonSchema"):
        return "generationConfig.responseSchema requires responseMimeType application/json."
    elif mime == "text/x.enum":
        sch = _lower_types(gc.get("responseSchema")) or {}
        if not sch.get("enum"):
            return "responseMimeType text/x.enum requires a responseSchema with enum values."
    elif mime not in (None, "", "text/plain"):
        return f"responseMimeType {mime!r} is not supported."
    for k, e in (("topP", "top_p"), ("seed", "seed")):
        if gc.get(k) is not None:
            ex[e] = gc[k]
    if gc.get("candidateCount") not in (None, 1):
        return "generationConfig.candidateCount: only 1 is supported by the local model."
    si = "".join(pt.get("text", "") for pt in ((p.get("systemInstruction") or {}).get("parts") or []))
    return msgs, si or None, gc.get("maxOutputTokens", 512), gc.get("temperature", 1.0), gc.get("stopSequences"), ex


def _gem_parts(text, calls):
    parts = [{"text": text}] if (text or not calls) else []
    parts += [{"functionCall": {"name": c["name"], "args": c["arguments"]}} for c in calls or []]
    return parts


def _gem_usage(r):
    return {"promptTokenCount": r["input_tokens"], "candidatesTokenCount": r["output_tokens"],
            "totalTokenCount": r["input_tokens"] + r["output_tokens"]}


def _gem_stream(model, it, sse):
    """Seam events -> streamGenerateContent chunks, text forwarded as generated; function calls ride the last chunk."""
    first = True

    def enc(chunk):
        nonlocal first
        if sse:
            return "data: " + json.dumps(chunk) + "\r\n\r\n"
        s = ("[" if first else ",\r\n") + json.dumps(chunk)
        first = False
        return s
    try:
        for ev in it:
            if ev["type"] == "text":
                yield enc({"candidates": [{"content": {"role": "model", "parts": [{"text": ev["text"]}]}, "index": 0}], "modelVersion": model})
            elif ev["type"] == "done":
                fin = "MAX_TOKENS" if ev["finish_reason"] == "length" else "STOP"
                yield enc({"candidates": [{"content": {"role": "model", "parts": _gem_parts("", ev["tool_calls"]) if ev["tool_calls"] else [{"text": ""}]},
                                           "index": 0, "finishReason": fin}], "usageMetadata": _gem_usage(ev), "modelVersion": model})
    except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
        err = {"error": {"code": 503, "message": str(e), "status": "UNAVAILABLE"}}
        yield ("data: " + json.dumps(err) + "\r\n\r\n") if sse else ((",\r\n" if not first else "[") + json.dumps(err))
    if not sse:
        yield "[]" if first else "]"


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
        req = _gem_request(p)
        if isinstance(req, str):
            return _g_err(400, "INVALID_ARGUMENT", req)
        msgs, si = req[0], req[1]
        if op == "countTokens":
            n = sum(llm.estimate_tokens(m["content"]) for m in msgs) + llm.estimate_tokens(si or "")
            return _j(200, {"totalTokens": n, "totalBillableCharacters": sum(len(m["content"]) for m in msgs)})
        req = (req[0], req[1], req[2], req[3], req[4], dict(req[5], model=model))
        try:
            if op == "streamGenerateContent":
                it = _prime(llm.chat_stream(*req[:5], **req[5]))
            else:
                r = _llm_chat(req)
        except llm.LlmStructuredError as e:
            return _g_err(500, "INTERNAL", str(e))
        except llm.LlmUnavailable as e:
            return _g_err(503, "UNAVAILABLE", f"{e}")
        except ValueError as e:
            return _g_err(400, "INVALID_ARGUMENT", str(e))
        if op == "generateContent":
            fin = "MAX_TOKENS" if r["finish_reason"] == "length" else "STOP"
            return _j(200, {"candidates": [{"content": {"role": "model", "parts": _gem_parts(r["text"], r["tool_calls"])}, "index": 0, "finishReason": fin}],
                            "usageMetadata": _gem_usage(r), "modelVersion": model, "responseId": uuid.uuid4().hex[:20]},
                      {"x-vyomi-local-model": r["model"]})
        sse = (query or {}).get("alt") == "sse"
        return _stream_out(200, {}, _gem_stream(model, it, sse), "text/event-stream" if sse else "application/json")
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


def _az_chat_request(p):
    """OpenAI/Azure chat.completions body -> (messages, system, max_tokens, temperature, stop, extras) or (param, message)."""
    msgs_in = p.get("messages")
    if not isinstance(msgs_in, list) or not msgs_in:
        return ("messages", "'messages' is a required property.")
    out, pend = [], {}
    for m in msgs_in:
        role = m.get("role") if isinstance(m, dict) else None
        if role not in ("system", "developer", "user", "assistant", "tool"):
            return ("messages", "Invalid value for 'role' in messages.")
        c = m.get("content")
        if isinstance(c, list):
            if any(not isinstance(x, dict) or x.get("type") not in ("text",) for x in c):
                return ("messages", "Only text content parts are supported by the local model (image_url/input_audio are not).")
            c = "".join(x.get("text", "") for x in c)
        if role == "tool":
            if not m.get("tool_call_id"):
                return ("messages", "Missing required parameter: 'tool_call_id' for role 'tool'.")
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "name": pend.get(m["tool_call_id"], m.get("name", "")), "content": c if isinstance(c, str) else json.dumps(c)})
            continue
        nm = {"role": "system" if role == "developer" else role, "content": c or ""}
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                fn = (tc or {}).get("function") or {}
                if tc.get("type", "function") != "function" or not fn.get("name") or not tc.get("id"):
                    return ("messages", "Invalid tool_calls entry: needs id, type 'function' and function.name.")
                calls.append({"id": tc["id"], "name": fn["name"], "arguments": fn.get("arguments") or "{}"})
                pend[tc["id"]] = fn["name"]
            nm["tool_calls"] = calls
        elif role == "assistant" and m.get("function_call"):
            return ("messages", "The legacy 'function_call' message field is not supported; use tool_calls.")
        out.append(nm)
    if p.get("functions") or p.get("function_call"):
        return ("functions", "The legacy 'functions'/'function_call' parameters are not supported by the local model; use 'tools'/'tool_choice'.")
    if p.get("n") not in (None, 1):
        return ("n", "Only n=1 is supported by the local model.")
    ex = {}
    if p.get("tools"):
        ex["tools"] = []
        for t in p["tools"]:
            fn = (t or {}).get("function") or {}
            if (t or {}).get("type") != "function" or not fn.get("name"):
                return ("tools", "Invalid value for 'tools': every tool must be {type: 'function', function: {name, ...}}.")
            ex["tools"].append({"name": fn["name"], "description": fn.get("description", ""), "parameters": fn.get("parameters") or {"type": "object", "properties": {}}})
        tc = p.get("tool_choice", "auto")
        if isinstance(tc, dict):
            nme = (tc.get("function") or {}).get("name")
            if nme not in [t["name"] for t in ex["tools"]]:
                return ("tool_choice", "Invalid 'tool_choice': the named function was not found in 'tools'.")
            ex["tool_choice"] = {"name": nme}
        elif tc in ("auto", "none", "required"):
            ex["tool_choice"] = tc
        else:
            return ("tool_choice", "Invalid value for 'tool_choice'.")
    elif p.get("tool_choice") not in (None, "none", "auto"):
        return ("tool_choice", "'tool_choice' is only allowed when 'tools' are specified.")
    rf = p.get("response_format")
    if rf:
        ty = rf.get("type")
        if ty == "json_object":
            ex["response_format"] = {"type": "json_object"}
        elif ty == "json_schema":
            js = rf.get("json_schema") or {}
            if not isinstance(js.get("schema"), dict) or not js.get("name"):
                return ("response_format", "Invalid 'response_format': json_schema needs name and schema.")
            ex["response_format"] = {"type": "json_schema", "schema": js["schema"], "name": js["name"]}
        elif ty != "text":
            return ("response_format", f"Invalid value for 'response_format.type': {ty!r}.")
    for k in ("top_p", "seed"):
        if p.get(k) is not None:
            ex[k] = p[k]
    stop = [p["stop"]] if isinstance(p.get("stop"), str) else p.get("stop")
    return out, None, p.get("max_completion_tokens") or p.get("max_tokens") or 512, p.get("temperature", 1.0), stop, ex


def _az_msg(r):
    msg = {"role": "assistant", "content": r["text"] if (r["text"] or not r["tool_calls"]) else None}
    if r["tool_calls"]:
        msg["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for c in r["tool_calls"]]
    return msg


def _az_fin(r_or_ev):
    return "tool_calls" if r_or_ev["tool_calls"] else ("length" if r_or_ev["finish_reason"] == "length" else "stop")


def _az_stream(cid, now, model, it, include_usage):
    def chunk(delta, fin=None, usage=None):
        d = {"id": cid, "object": "chat.completion.chunk", "created": now, "model": model,
             "choices": [] if usage else [{"index": 0, "delta": delta, "finish_reason": fin}]}
        if usage:
            d["usage"] = usage
        return "data: " + json.dumps(d) + "\n\n"
    yield chunk({"role": "assistant", "content": ""})
    try:
        for ev in it:
            if ev["type"] == "text":
                yield chunk({"content": ev["text"]})
            elif ev["type"] == "tool_start":
                yield chunk({"tool_calls": [{"index": ev["index"], "id": ev["id"], "type": "function", "function": {"name": ev["name"], "arguments": ""}}]})
            elif ev["type"] == "tool_args":
                yield chunk({"tool_calls": [{"index": ev["index"], "function": {"arguments": ev["fragment"]}}]})
            else:
                yield chunk({}, _az_fin(ev))
                if include_usage:
                    yield chunk({}, usage={"prompt_tokens": ev["input_tokens"], "completion_tokens": ev["output_tokens"],
                                            "total_tokens": ev["input_tokens"] + ev["output_tokens"]})
    except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
        yield "data: " + json.dumps({"error": {"code": "ServiceUnavailable", "message": str(e)}}) + "\n\n"
    yield "data: [DONE]\n\n"


def _fit_dims(v, dims):
    if len(v) >= dims:
        return v[:dims]
    return v + [0.0] * (dims - len(v))


def azure_openai_dispatch(arm_state, method, path, query, headers, body, net_state=None):
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
    if acct is not None:      # azure.cognitiveservices.networking: the account's public access / firewall / PE, vs the declared caller
        try:
            from core import azure_netaccess as _na
        except ImportError:   # pragma: no cover - Pyodide flat layout
            import azure_netaccess as _na  # type: ignore
        _d = _na.cognitive_denied(net_state or arm_state, acct, lh, query)
        if _d:
            return _a_err(403, "Forbidden", _d[2])
        try:      # diagnostic settings (RequestResponse) on the account: real delivery (core/azure_diag_pipeline.py)
            from core import azure_diag_pipeline as _dp
        except ImportError:  # pragma: no cover
            import azure_diag_pipeline as _dp  # type: ignore
        _dp.emit_log(net_state or arm_state, acct.get("id", ""), "RequestResponse", f"{op}" if not dep_name else f"{op} ({dep_name})",
                     "Success", {"deployment": dep_name})
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
        e = llm.embed(inp if isinstance(inp, list) else [inp])
        native = 3072 if "large" in model else 1536
        dims = int(p.get("dimensions") or native)       # the real service returns its native width unless `dimensions` shortens it
        vecs = [llm._renorm(_fit_dims(v, dims)) for v in e["vectors"]]
        return _j(200, {"object": "list", "model": model, "usage": {"prompt_tokens": e["input_tokens"], "total_tokens": e["input_tokens"]},
                        "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)]})
    if "embedding" in model or (caps and "chatCompletion" not in caps):
        return _a_err(400, "OperationNotSupported", f"The {op} operation does not work with the specified model, {model}. "
                      "Please choose different model and try again.")
    if op == "completions":
        if not p.get("prompt"):
            return _a_err(400, "BadRequest", "'prompt' is a required property.", "prompt")
        if p.get("tools") or p.get("response_format"):
            return _a_err(400, "BadRequest", "tools/response_format are only supported on chat/completions.", "tools")
        req = ([{"role": "user", "content": p["prompt"] if isinstance(p["prompt"], str) else "\n".join(p["prompt"])}], None,
               p.get("max_tokens") or 512, p.get("temperature", 1.0), [p["stop"]] if isinstance(p.get("stop"), str) else p.get("stop"),
               {k: p[k] for k in ("top_p", "seed") if p.get(k) is not None})
    else:
        req = _az_chat_request(p)
        if len(req) == 2:
            return _a_err(400, "BadRequest", req[1], req[0])
    req = (req[0], req[1], req[2], req[3], req[4], dict(req[5], model=model))
    cid, now = ("chatcmpl-" if op == "chat/completions" else "cmpl-") + uuid.uuid4().hex[:29], int(time.time())
    stream = bool(p.get("stream")) and op == "chat/completions"
    try:
        if stream:
            it = _prime(llm.chat_stream(*req[:5], **req[5]))
        else:
            r = _llm_chat(req)
    except llm.LlmStructuredError as e:
        return _a_err(500, "model_error", str(e))
    except llm.LlmUnavailable as e:
        return _a_err(503, "ServiceUnavailable", f"{e}")
    except ValueError as e:
        return _a_err(400, "BadRequest", str(e))
    if stream:
        return _stream_out(200, {"x-vyomi-local-model": llm.resolve_model(model)},
                           _az_stream(cid, now, model, it, bool((p.get("stream_options") or {}).get("include_usage"))), "text/event-stream")
    fin = "length" if r["finish_reason"] == "length" else "stop"
    usage = {"prompt_tokens": r["input_tokens"], "completion_tokens": r["output_tokens"], "total_tokens": r["input_tokens"] + r["output_tokens"]}
    hh = {"x-vyomi-local-model": r["model"]}
    if op == "completions":
        return _j(200, {"id": cid, "object": "text_completion", "created": now, "model": model,
                        "choices": [{"text": r["text"], "index": 0, "finish_reason": fin, "logprobs": None}], "usage": usage}, hh)
    return _j(200, {"id": cid, "object": "chat.completion", "created": now, "model": model,
                    "choices": [{"index": 0, "finish_reason": _az_fin(r), "message": _az_msg(r)}],
                    "usage": usage, "system_fingerprint": "fp_vyomi_local"}, hh)
