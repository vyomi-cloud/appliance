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
    from core import ai_model_catalog as CAT
except ImportError:  # Pyodide flat layout
    import llm_core as llm  # type: ignore
    import ai_model_catalog as CAT  # type: ignore

def _guardrails():
    try:
        from core import bedrock_guardrails_core as g
    except ImportError:  # Pyodide flat layout
        import bedrock_guardrails_core as g  # type: ignore
    return g


_ACCT = "123456789012"

# (model id, provider, name, input modalities, output modalities, streaming, catalogue id): the ten mesh-llm models only
# (core/ai_model_catalog.py). Legacy real-vendor ids resolve through the hidden alias map (see _resolve_model) but are never listed.
BEDROCK_MODELS = [(CAT.cloud_id("aws", m["id"]), m["vendor"], m["name"], ["TEXT"], ["EMBEDDING"] if m["kind"] == "embed" else ["TEXT"],
                   m["kind"] != "embed", m["id"]) for m in CAT.MODELS]
_BM = {m[0]: m for m in BEDROCK_MODELS}

# Standard Bedrock ids listed as ALIASES of the local model (v4 reference-app lane `models`). They are honest: same TEXT-only
# modalities the local model has (no vision/doc input), `vyomiBackedBy` says which catalogue model answers, and the lifecycle
# is ACTIVE only in the sense that the id is callable. Each row: (modelId, provider, display name, input, output, streaming).
_T, _E = ["TEXT"], ["EMBEDDING"]
def list_aliases():
    """Standard Bedrock ids (anthropic.claude-*, amazon.nova-*, ...) always RESOLVE for SDK compatibility, but are only LISTED
    when VYOMI_LIST_BEDROCK_ALIASES=1: by default consoles show only the models actually served (Nano WebLLM / Mesh open-source)."""
    import os
    return os.environ.get("VYOMI_LIST_BEDROCK_ALIASES") == "1"


BEDROCK_ALIASES = [
    ("anthropic.claude-3-haiku-20240307-v1:0", "Anthropic", "Claude 3 Haiku", _T, _T, True),
    ("anthropic.claude-3-5-haiku-20241022-v1:0", "Anthropic", "Claude 3.5 Haiku", _T, _T, True),
    ("anthropic.claude-3-5-sonnet-20241022-v2:0", "Anthropic", "Claude 3.5 Sonnet v2", _T, _T, True),
    ("anthropic.claude-3-7-sonnet-20250219-v1:0", "Anthropic", "Claude 3.7 Sonnet", _T, _T, True),
    ("anthropic.claude-sonnet-4-20250514-v1:0", "Anthropic", "Claude Sonnet 4", _T, _T, True),
    ("anthropic.claude-haiku-4-5-20251001-v1:0", "Anthropic", "Claude Haiku 4.5", _T, _T, True),
    ("amazon.titan-text-lite-v1", "Amazon", "Titan Text G1 - Lite", _T, _T, True),
    ("amazon.titan-text-express-v1", "Amazon", "Titan Text G1 - Express", _T, _T, True),
    ("amazon.titan-embed-text-v1", "Amazon", "Titan Embeddings G1 - Text", _T, _E, False),
    ("amazon.titan-embed-text-v2:0", "Amazon", "Titan Text Embeddings V2", _T, _E, False),
    ("amazon.nova-micro-v1:0", "Amazon", "Nova Micro", _T, _T, True),
    ("amazon.nova-lite-v1:0", "Amazon", "Nova Lite", _T, _T, True),
    ("amazon.nova-pro-v1:0", "Amazon", "Nova Pro", _T, _T, True),
    ("meta.llama3-1-8b-instruct-v1:0", "Meta", "Llama 3.1 8B Instruct", _T, _T, True),
    ("meta.llama3-1-70b-instruct-v1:0", "Meta", "Llama 3.1 70B Instruct", _T, _T, True),
    ("meta.llama3-2-3b-instruct-v1:0", "Meta", "Llama 3.2 3B Instruct", _T, _T, True),
    ("cohere.command-r-v1:0", "Cohere", "Command R", _T, _T, True),
    ("cohere.embed-english-v3", "Cohere", "Embed English", _T, _E, False),
    ("cohere.embed-multilingual-v3", "Cohere", "Embed Multilingual", _T, _E, False),
]
# standard ids the catalogue's hidden alias map does not cover (Titan Text, Cohere Command): resolved here, to the small local model
_EXTRA_ALIASES = {"amazon.titan-text": "qwen2.5-3b", "cohere.command": "qwen2.5-7b"}
_ALIAS_BY_ID = {a[0]: a for a in BEDROCK_ALIASES}
_INF_PROFILE_PREFIX = ("us", "eu", "apac")


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
    try:
        from core import bedrock_ctl_core as _ctl
    except ImportError:  # Pyodide flat layout
        import bedrock_ctl_core as _ctl  # type: ignore
    mid = _ctl.app_profile_model(mid) or mid    # application inference profile / prompt router ARN -> its model
    imp = _ctl.imported_model_id(mid)            # Custom Model Import (core/import_core): base GGUF + LoRA adapter, served by wllama on Nano
    if imp:
        return (imp, "Vyomi (imported)", _ctl._IMPORTED[imp]["modelName"], ["TEXT"], ["TEXT"], True, CAT.DEFAULT_CHAT, "vyomi.import")
    mid = re.sub(r"^arn:aws[a-z-]*:bedrock:[^:]*:[0-9]*:(foundation-model|inference-profile)/", "", mid)
    base = re.sub(r"^(us|eu|apac|us-gov|global)\.", "", mid)
    if base in _BM:
        return _BM[base]
    cid = CAT.resolve("aws", base)          # compat alias (anthropic.claude*, amazon.nova*, ...): resolves, and is listed via BEDROCK_ALIASES
    if cid is None:
        cid = next((v for k, v in _EXTRA_ALIASES.items() if base.startswith(k)), None)
        if cid is not None and cid not in CAT.BY_ID:
            cid = CAT.DEFAULT_CHAT
    if cid is None:
        return None
    return (base, CAT.BY_ID[cid]["vendor"], CAT.BY_ID[cid]["name"], ["TEXT"], ["EMBEDDING"] if CAT.BY_ID[cid]["kind"] == "embed" else ["TEXT"],
            CAT.BY_ID[cid]["kind"] != "embed", cid)


def _ll_err(e):
    if isinstance(e, llm.LlmStructuredError):
        return _b_err("ModelErrorException", str(e), 424)
    if "mported chat model" in str(e):
        return _b_err("ModelNotReadyException", f"{e}", 429)
    return _b_err("ModelNotReadyException", f"{e} (the local model has not been started)", 429)


# ───────────── document / image content blocks + prompt-cache accounting ─────────────
_DOC_FORMATS = ("pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md")
_IMG_FORMATS = ("png", "jpeg", "gif", "webp")
_NO_VISION = ("This model does not accept image content blocks: no vision-capable local model is running (the local llama.cpp/WebLLM "
              "model is text-only; serve a multimodal GGUF and set VYOMI_LLM_VISION=1 to enable images).")


def _kcore():
    try:
        from core import knowledge_core as kc
    except ImportError:  # Pyodide flat layout
        import knowledge_core as kc  # type: ignore
    return kc


def _document_text(name, fmt, raw):
    """A Converse document block / Claude document source -> '<document name=..>text</document>' text for the model, or an error string.
    PDF/DOCX/XLSX/PPTX/CSV/HTML/MD are really parsed (core/knowledge_core, the same parsers the Knowledge Base ingestion uses)."""
    kc = _kcore()
    if fmt not in _DOC_FORMATS:
        return f"document.format must be one of {', '.join(_DOC_FORMATS)}"
    if not isinstance(name, str) or not name.strip():
        return "document.name is required"
    try:
        data = raw if isinstance(raw, (bytes, bytearray)) else (base64.b64decode(raw, validate=True) if isinstance(raw, str) else None)
    except Exception:  # noqa: BLE001
        data = None
    if data is None:
        return "document.source must carry base64 bytes (s3Location sources are not supported)"
    try:
        txt = kc.parse_document(f"{name}.{fmt}", bytes(data), markdown_tables=True)
    except kc.ParseError as e:
        return f"Could not process the document {name}.{fmt}: {e}"
    return f'<document name="{name}" format="{fmt}">\n{txt}\n</document>'


def _image_part(fmt, raw):
    """-> content part for a vision-capable backend, or an error string when none is running."""
    if not llm.vision_available():
        return _NO_VISION
    if fmt not in _IMG_FORMATS:
        return f"image.format must be one of {', '.join(_IMG_FORMATS)}"
    b64 = raw if isinstance(raw, str) else base64.b64encode(bytes(raw)).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/{fmt};base64,{b64}"}}


_PCACHE: dict = {}                 # prefix hash -> {"tokens": int, "exp": float}   (in-process; per appliance, like a provider-side cache)
PCACHE_TTL = 300.0                 # seconds, refreshed on every hit (Bedrock's 5-minute ephemeral cache)
PCACHE_MIN_TOKENS = 1024           # a checkpoint shorter than this is not cacheable (Claude/Nova minimum)


def _cache_plan(p, style):
    """Serialise the request in cache order (tools, system, messages) -> [(segment_text, is_checkpoint)]. style = 'converse' | 'claude'."""
    segs = []

    def add(obj):
        segs.append((json.dumps(obj, sort_keys=True, separators=(",", ":")), False))

    def mark():
        segs.append(("", True))
    for t in (p.get("tools") or []):
        if isinstance(t, dict):
            if "cachePoint" in t:
                mark()
            else:
                add(t)
                if (t.get("cache_control") or {}).get("type") == "ephemeral":
                    mark()
    sysb = p.get("system")
    for b in (sysb if isinstance(sysb, list) else ([{"type": "text", "text": sysb}] if isinstance(sysb, str) else [])):
        if isinstance(b, dict):
            if "cachePoint" in b:
                mark()
            else:
                add({k: v for k, v in b.items() if k != "cache_control"})
                if (b.get("cache_control") or {}).get("type") == "ephemeral":
                    mark()
    for m in (p.get("messages") or []):
        if not isinstance(m, dict):
            continue
        cs = m.get("content")
        for b in (cs if isinstance(cs, list) else ([{"type": "text", "text": cs}] if isinstance(cs, str) else [])):
            if isinstance(b, dict):
                if "cachePoint" in b:
                    mark()
                else:
                    add([m.get("role"), {k: v for k, v in b.items() if k != "cache_control"}])
                    if (b.get("cache_control") or {}).get("type") == "ephemeral":
                        mark()
    return segs


def _cache_account(p, style, input_tokens, now=None):
    """Real prefix-cache accounting over the request's checkpoints. Returns {"read","write","uncached"} or None when the request has no
    checkpoint. A checkpoint's prefix (everything before it, in tools/system/messages order) is keyed by its SHA-256; a prefix seen within
    the TTL is a read (and its TTL refreshes), otherwise the longest checkpoint is written (when it holds >= PCACHE_MIN_TOKENS).
    Token counts are the model's own input_tokens apportioned by prefix length, so they sum to the real prompt size."""
    import hashlib
    segs = _cache_plan(p, style)
    if not any(m for _, m in segs):
        return None
    now = now if now is not None else time.time()
    for k in [k for k, v in _PCACHE.items() if v["exp"] < now]:
        del _PCACHE[k]
    total_chars = max(sum(len(t) for t, m in segs if not m), 1)
    pts, h, chars = [], hashlib.sha256(), 0
    for t, m in segs:
        if m:
            tok = int(round(input_tokens * chars / total_chars))
            pts.append((h.copy().hexdigest(), tok))
        else:
            h.update(t.encode())
            h.update(b"\x1f")
            chars += len(t)
    read = write = 0
    for key, tok in reversed(pts):             # longest cached prefix wins
        if key in _PCACHE and _PCACHE[key]["tokens"] <= input_tokens:
            read = _PCACHE[key]["tokens"]
            break
    for key, tok in pts:
        if key in _PCACHE:
            _PCACHE[key]["exp"] = now + PCACHE_TTL
    if pts:
        key, tok = pts[-1]
        if key not in _PCACHE and tok >= PCACHE_MIN_TOKENS:
            write = max(tok - read, 0)
            for k2, t2 in pts:
                if t2 >= PCACHE_MIN_TOKENS:
                    _PCACHE[k2] = {"tokens": t2, "exp": now + PCACHE_TTL}
    return {"read": read, "write": write, "uncached": max(input_tokens - read - write, 0)}


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
        texts, calls, results, images = [], [], [], []
        for blk in mm["content"]:
            if not isinstance(blk, dict):
                return "Invalid content block"
            keys = set(blk) - {"cachePoint"}
            if not keys:                      # a bare cachePoint marker: handled by _cache_account, carries no content
                continue
            if "reasoningContent" in keys:
                return "reasoningContent blocks are not supported: no served local model emits reasoning"
            if len(keys) != 1 or not keys <= {"text", "toolUse", "toolResult", "document", "image", "guardContent"}:
                return "Only text, document, image, guardContent, toolUse and toolResult content blocks are supported by the local model (video is not)"
            if "guardContent" in blk:       # Bedrock guardrails content block: the text reaches the model; qualifiers steer the guardrail
                gt = (blk["guardContent"] or {}).get("text")
                if not isinstance(gt, dict) or not isinstance(gt.get("text"), str):
                    return "Invalid guardContent block: needs text.text (guardContent images are not supported)"
                texts.append(gt["text"])
            elif "document" in blk:
                d = blk["document"] or {}
                src = d.get("source") or {}
                dt = _document_text(d.get("name"), d.get("format"), src.get("bytes")) if "bytes" in src else (
                    f'<document name="{d.get("name")}">\n{src["text"]}\n</document>' if isinstance(src.get("text"), str) else
                    "document.source must carry base64 bytes (s3Location sources are not supported)")
                if dt.startswith(("document.", "Could not process")):
                    return dt
                if mm["role"] != "user":
                    return "document blocks are only allowed in user messages"
                texts.append(dt + "\n")
            elif "image" in blk:
                im = blk["image"] or {}
                part = _image_part(im.get("format"), (im.get("source") or {}).get("bytes"))
                if isinstance(part, str):
                    return part
                images.append(part)
            elif "text" in blk:
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
        elif texts or images:
            out.append({"role": "user", "content": ([{"type": "text", "text": "".join(texts)}] + images) if images else "".join(texts)})
    return out


def _converse_request(p, mid, max_key="maxTokens"):
    """Converse (and Nova InvokeModel) body -> (messages, system, max_tokens, temperature, stop, extras) or an error string."""
    msgs = _converse_messages(p.get("messages"))
    if isinstance(msgs, str):
        return msgs
    if "guardrailConfig" in p and not isinstance(p["guardrailConfig"], dict):
        return "guardrailConfig must be a structure"
    amf = p.get("additionalModelRequestFields")
    if isinstance(amf, dict) and ({"thinking", "reasoning_config", "reasoningConfig"} & set(amf)):
        return "Reasoning/thinking is not supported: no served local model emits reasoning content (remove additionalModelRequestFields.thinking)"
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
    if isinstance(p.get("thinking"), dict) and p["thinking"].get("type") == "enabled":
        return "thinking is not supported: no served local model emits reasoning content"
    for mm in p["messages"]:
        c = mm.get("content") if isinstance(mm, dict) else None
        if mm.get("role") not in ("user", "assistant"):
            return "messages.role: must be user or assistant"
        if isinstance(c, str):
            out.append({"role": mm["role"], "content": c})
            continue
        if not isinstance(c, list):
            return "messages.content: must be a string or a list of content blocks"
        texts, calls, results, images = [], [], [], []
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
            elif ty == "document" and mm["role"] == "user":
                src = b.get("source") or {}
                if src.get("type") == "text":
                    texts.append(f'<document name="{b.get("title") or "document"}">\n{src.get("data", "")}\n</document>\n')
                elif src.get("type") == "base64":
                    ext = {"application/pdf": "pdf", "text/csv": "csv", "text/html": "html", "text/plain": "txt", "text/markdown": "md"}.get(src.get("media_type"))
                    dt = _document_text(b.get("title") or "document", ext, src.get("data")) if ext else "document.source.media_type must be application/pdf, text/csv, text/html, text/plain or text/markdown"
                    if dt.startswith(("document.", "Could not process")):
                        return dt
                    texts.append(dt + "\n")
                else:
                    return "document.source.type must be base64 or text"
            elif ty == "image" and mm["role"] == "user":
                src = b.get("source") or {}
                part = _image_part((src.get("media_type") or "").split("/")[-1], src.get("data")) if src.get("type") == "base64" else "image.source.type must be base64"
                if isinstance(part, str):
                    return part
                images.append(part)
            elif ty in ("thinking", "redacted_thinking"):
                return "thinking blocks are not supported: no served local model emits reasoning"
            else:
                return f"messages.content: block type {ty!r} is not supported by the local model (video/search results are not)"
        out += results
        if mm["role"] == "assistant":
            m = {"role": "assistant", "content": "".join(texts)}
            if calls:
                m["tool_calls"] = calls
            out.append(m)
        elif texts or images:
            out.append({"role": "user", "content": ([{"type": "text", "text": "".join(texts)}] + images) if images else "".join(texts)})
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


def _fam(m):
    """Wire family used to pick the InvokeModel body/response shape. Legacy alias ids keep their vendor family; the ten native
    ``vyomi.<id>`` models take a Converse-style body (messages) or a Llama-style one (prompt / inputText)."""
    return m[7] if len(m) > 7 else m[0]


def _bedrock_text_request(m, p):
    """-> (messages, system, max_tokens, temperature, stop, extras) from the family-specific InvokeModel body, or an error string."""
    mid, fam = m[0], _fam(m)
    if fam == "vyomi.import":        # Llama-style {"prompt"} (as real imported Llama models take) or OpenAI-style {"messages":[{"role","content"}]}
        msgs = p.get("messages")
        if isinstance(msgs, list) and msgs:
            if not all(isinstance(x, dict) and x.get("role") in ("system", "user", "assistant") and isinstance(x.get("content"), str) for x in msgs):
                return "messages: each item needs a role (system|user|assistant) and a string content"
        elif p.get("prompt"):
            msgs = [{"role": "user", "content": p["prompt"]}]
        else:
            return "Malformed input request: required key [prompt] (or [messages]) not found, please reformat your input and try again."
        return msgs, None, p.get("max_gen_len") or p.get("max_tokens") or 512, p.get("temperature", 0.5), p.get("stop"), {"model": mid}
    if fam.startswith("vyomi.") or fam == "vyomi-prompt":
        txt = p.get("prompt") or p.get("inputText")
        if not txt:
            return "Malformed input request: required key [prompt] not found, please reformat your input and try again."
        c = p.get("textGenerationConfig") or {}
        return ([{"role": "user", "content": txt}], None, p.get("max_gen_len") or p.get("max_tokens") or c.get("maxTokenCount", 512),
                p.get("temperature", c.get("temperature", 0.5)), p.get("stop") or c.get("stopSequences"), {"model": mid})
    if fam.startswith("anthropic."):
        return _claude_request(p, mid)
    if fam.startswith("amazon.titan-text"):
        if not p.get("inputText"):
            return "Malformed input request: required key [inputText] not found, please reformat your input and try again."
        c = p.get("textGenerationConfig") or {}
        return ([{"role": "user", "content": p["inputText"]}], None, c.get("maxTokenCount", 512), c.get("temperature", 0.7),
                c.get("stopSequences"), {"model": mid, **({"top_p": c["topP"]} if c.get("topP") is not None else {})})
    if fam.startswith("amazon.nova"):
        if not isinstance(p.get("messages"), list) or not p["messages"]:
            return "messages: field required"
        return _converse_request(p, mid, "max_new_tokens")
    if fam.startswith("meta."):
        if not p.get("prompt"):
            return "Malformed input request: required key [prompt] not found, please reformat your input and try again."
        return [{"role": "user", "content": p["prompt"]}], None, p.get("max_gen_len", 512), p.get("temperature", 0.5), None, {"model": mid}
    if fam.startswith("mistral."):
        if not p.get("prompt"):
            return "Malformed input request: required key [prompt] not found, please reformat your input and try again."
        return [{"role": "user", "content": p["prompt"]}], None, p.get("max_tokens", 512), p.get("temperature", 0.5), p.get("stop"), {"model": mid}
    return "this model does not support InvokeModel text generation"


def _stop_reason(fr):
    return "max_tokens" if fr == "length" else ("tool_use" if fr == "tool_calls" else ("guardrail_intervened" if fr == "guardrail_intervened" else "end_turn"))


def _usage(r, ca=None):
    """Converse usage block. With prompt-cache accounting (``ca`` from _cache_account) inputTokens counts only the uncached tokens and
    cacheRead/WriteInputTokens report the cached ones, as Bedrock does."""
    if not ca:
        return {"inputTokens": r["input_tokens"], "outputTokens": r["output_tokens"], "totalTokens": r["input_tokens"] + r["output_tokens"]}
    return {"inputTokens": ca["uncached"], "outputTokens": r["output_tokens"], "cacheReadInputTokens": ca["read"], "cacheWriteInputTokens": ca["write"],
            "totalTokens": r["input_tokens"] + r["output_tokens"]}


def _converse_content(r):
    content = [{"text": r["text"]}] if (r["text"] or not r.get("tool_calls")) else []
    content += [{"toolUse": {"toolUseId": c["id"], "name": c["name"], "input": c["arguments"]}} for c in r.get("tool_calls") or []]
    return content


def _bedrock_response(m, p, r):
    mid, txt, fam = m[0], r["text"], _fam(m)
    if fam.startswith("anthropic."):
        content = [{"type": "text", "text": txt}] if (txt or not r.get("tool_calls")) else []
        content += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]} for c in r.get("tool_calls") or []]
        return {"id": "msg_bdrk_" + uuid.uuid4().hex[:24], "type": "message", "role": "assistant", "model": mid,
                "content": content, "stop_reason": "tool_use" if r.get("tool_calls") else ("max_tokens" if r["finish_reason"] == "length" else "end_turn"),
                "stop_sequence": None, "usage": {"input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"]}}
    if fam.startswith("amazon.titan-text"):
        return {"inputTextTokenCount": r["input_tokens"], "results": [{"tokenCount": r["output_tokens"], "outputText": txt,
                "completionReason": "LENGTH" if r["finish_reason"] == "length" else "FINISH"}]}
    if fam.startswith("amazon.nova"):
        return {"output": {"message": {"role": "assistant", "content": _converse_content(r)}}, "stopReason": _stop_reason(r["finish_reason"]),
                "usage": {"inputTokens": r["input_tokens"], "outputTokens": r["output_tokens"],
                          "totalTokens": r["input_tokens"] + r["output_tokens"]}}
    if fam == "vyomi.import":
        return {"generation": txt, "prompt_token_count": r["input_tokens"], "generation_token_count": r["output_tokens"],
                "stop_reason": "length" if r["finish_reason"] == "length" else "stop", "vyomiImported": True, "vyomiTrained": True}
    if fam.startswith("meta.") or fam == "vyomi-prompt":
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


def _converse_events(it, t0, F, cache_fn=None):
    """Seam events -> Converse stream frames: text deltas as they arrive; toolUse blocks start/delta(input fragments)/stop."""
    yield F("messageStart", {"role": "assistant"})
    idx, text_idx, tool_open, tool_blk, got_args = -1, None, None, {}, set()
    try:
        for ev in it:
            ty = ev["type"]
            if ty == "text":
                if text_idx is None:
                    idx += 1
                    text_idx = idx
                yield F("contentBlockDelta", {"contentBlockIndex": text_idx, "delta": {"text": ev["text"]}})
            elif ty == "tool_start":
                if text_idx is not None:
                    yield F("contentBlockStop", {"contentBlockIndex": text_idx})
                    text_idx = None
                if tool_open is not None:
                    if tool_open not in got_args:
                        yield F("contentBlockDelta", {"contentBlockIndex": tool_blk[tool_open], "delta": {"toolUse": {"input": "{}"}}})
                    yield F("contentBlockStop", {"contentBlockIndex": tool_blk[tool_open]})
                idx += 1
                tool_blk[ev["index"]], tool_open = idx, ev["index"]
                yield F("contentBlockStart", {"contentBlockIndex": idx, "start": {"toolUse": {"toolUseId": ev["id"], "name": ev["name"]}}})
            elif ty == "tool_args":
                got_args.add(ev["index"])
                yield F("contentBlockDelta", {"contentBlockIndex": tool_blk[ev["index"]], "delta": {"toolUse": {"input": ev["fragment"]}}})
            else:
                if text_idx is not None:
                    yield F("contentBlockStop", {"contentBlockIndex": text_idx})
                if tool_open is not None:
                    if tool_open not in got_args:
                        yield F("contentBlockDelta", {"contentBlockIndex": tool_blk[tool_open], "delta": {"toolUse": {"input": "{}"}}})
                    yield F("contentBlockStop", {"contentBlockIndex": tool_blk[tool_open]})
                if idx < 0:
                    yield F("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": ""}})
                    yield F("contentBlockStop", {"contentBlockIndex": 0})
                yield F("messageStop", {"stopReason": _stop_reason(ev["finish_reason"])})
                yield F("metadata", {"usage": _usage(ev, cache_fn(ev["input_tokens"]) if cache_fn else None),
                                                      "metrics": {"latencyMs": int((time.time() - t0) * 1000)},
                                      **({"trace": ev["guardrail_trace"]} if ev.get("guardrail_trace") else {})})
    except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
        yield F("modelStreamErrorException", {"message": str(e)}, message_type="exception")


def _converse_frames(it, t0, cache_fn=None):
    return _converse_events(it, t0, eventstream_frame, cache_fn)


def _chunk_frame(obj):
    return eventstream_frame("chunk", {"bytes": base64.b64encode(json.dumps(obj).encode()).decode()})


def _invoke_frames(m, it, t0):
    """InvokeModelWithResponseStream: the model family's own streaming events, each wrapped in a base64 `chunk` frame, emitted as the
    seam generates them (Claude Messages events, Nova/Converse events, Titan/Llama/Mistral chunks)."""
    mid, fam = m[0], _fam(m)
    first = [None]

    def ga(ev):     # guardrail action/trace ride on the final chunk, as on real InvokeModelWithResponseStream
        return dict(({"amazon-bedrock-guardrailAction": ev["guardrail_action"]} if ev.get("guardrail_action") else {}),
                    **({"amazon-bedrock-trace": ev["guardrail_trace"]} if ev.get("guardrail_trace") else {}))

    def metrics(ev):
        return {"inputTokenCount": ev["input_tokens"], "outputTokenCount": ev["output_tokens"],
                "invocationLatency": int((time.time() - t0) * 1000), "firstByteLatency": int(((first[0] or time.time()) - t0) * 1000)}
    try:
        if fam.startswith("amazon.nova"):
            last = {}

            def tap(it2):
                for e in it2:
                    if e["type"] == "done":
                        last.update(ga(e))
                    yield e
            it = tap(it)

            def F(name, payload, message_type="event"):
                if message_type != "event":
                    return eventstream_frame(name, payload, message_type=message_type)
                if name == "metadata":
                    return b""
                if name == "messageStop":
                    payload = dict(payload, **{"amazon-bedrock-invocationMetrics": {"invocationLatency": int((time.time() - t0) * 1000)}}, **last)
                return _chunk_frame({name: payload})
            for fr in _converse_events(it, t0, F):
                if fr:
                    yield fr
            return
        if fam.startswith("anthropic."):
            yield _chunk_frame({"type": "message_start", "message": {"id": "msg_bdrk_" + uuid.uuid4().hex[:24], "type": "message", "role": "assistant",
                                                                    "model": mid, "content": [], "stop_reason": None, "stop_sequence": None,
                                                                    "usage": {"input_tokens": 0, "output_tokens": 0}}})
            idx, text_idx, tool_idx, nxt = None, None, {}, 0
            for ev in it:
                first[0] = first[0] or time.time()
                if ev["type"] == "text":
                    if text_idx is None:
                        text_idx, nxt = nxt, nxt + 1
                        yield _chunk_frame({"type": "content_block_start", "index": text_idx, "content_block": {"type": "text", "text": ""}})
                    yield _chunk_frame({"type": "content_block_delta", "index": text_idx, "delta": {"type": "text_delta", "text": ev["text"]}})
                elif ev["type"] == "tool_start":
                    if text_idx is not None:
                        yield _chunk_frame({"type": "content_block_stop", "index": text_idx})
                        text_idx = None
                    tool_idx[ev["index"]], nxt = nxt, nxt + 1
                    yield _chunk_frame({"type": "content_block_start", "index": tool_idx[ev["index"]],
                                        "content_block": {"type": "tool_use", "id": ev["id"], "name": ev["name"], "input": {}}})
                elif ev["type"] == "tool_args":
                    yield _chunk_frame({"type": "content_block_delta", "index": tool_idx[ev["index"]],
                                        "delta": {"type": "input_json_delta", "partial_json": ev["fragment"]}})
                else:
                    if text_idx is not None:
                        yield _chunk_frame({"type": "content_block_stop", "index": text_idx})
                    for k in tool_idx.values():
                        yield _chunk_frame({"type": "content_block_stop", "index": k})
                    yield _chunk_frame({"type": "message_delta", "delta": {"stop_reason": "tool_use" if ev["tool_calls"] else
                                                                        ("max_tokens" if ev["finish_reason"] == "length" else "end_turn"), "stop_sequence": None},
                                        "usage": {"output_tokens": ev["output_tokens"]}})
                    yield _chunk_frame({"type": "message_stop", "amazon-bedrock-invocationMetrics": metrics(ev), **ga(ev)})
            return
        n_out = 0
        for ev in it:
            first[0] = first[0] or time.time()
            if ev["type"] == "text":
                n_out += 1
                if fam.startswith("amazon.titan-text"):
                    yield _chunk_frame({"outputText": ev["text"], "index": 0, "totalOutputTextTokenCount": None, "completionReason": None, "inputTextTokenCount": None})
                elif fam.startswith("meta.") or fam == "vyomi-prompt":
                    yield _chunk_frame({"generation": ev["text"], "prompt_token_count": None, "generation_token_count": n_out, "stop_reason": None})
                else:
                    yield _chunk_frame({"outputs": [{"text": ev["text"], "stop_reason": None}]})
            elif ev["type"] == "done":
                lim = ev["finish_reason"] == "length"
                if fam.startswith("amazon.titan-text"):
                    yield _chunk_frame({"outputText": "", "index": 0, "totalOutputTextTokenCount": ev["output_tokens"], "completionReason": "LENGTH" if lim else "FINISH",
                                        "inputTextTokenCount": ev["input_tokens"], "amazon-bedrock-invocationMetrics": metrics(ev), **ga(ev)})
                elif fam.startswith("meta.") or fam == "vyomi-prompt":
                    yield _chunk_frame({"generation": "", "prompt_token_count": ev["input_tokens"], "generation_token_count": ev["output_tokens"],
                                        "stop_reason": "length" if lim else "stop", "amazon-bedrock-invocationMetrics": metrics(ev), **ga(ev)})
                else:
                    yield _chunk_frame({"outputs": [{"text": "", "stop_reason": "length" if lim else "stop"}], "amazon-bedrock-invocationMetrics": metrics(ev), **ga(ev)})
    except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
        yield eventstream_frame("modelStreamErrorException", {"message": str(e)}, message_type="exception")



def _guard_blocks(p):
    """guardContent blocks of the last user message -> [(text, qualifiers)] (empty when the caller sent none)."""
    users = [m for m in (p.get("messages") or []) if isinstance(m, dict) and m.get("role") == "user"]
    out = []
    for b in (users[-1].get("content") or []) if users else []:
        gt = ((b or {}).get("guardContent") or {}).get("text") if isinstance(b, dict) else None
        if isinstance(gt, dict) and isinstance(gt.get("text"), str):
            out.append((gt["text"], list(gt.get("qualifiers") or [])))
    return out


def _guard_input(gcfg, msgs, ctx=None):
    gr = _guardrails()
    user = [m for m in msgs if m["role"] == "user"]
    text = llm._ctext(user[-1]["content"]) if user else ""
    if ctx:    # guardContent present: only guard_content (or unqualified) text is judged, like real Converse; source/query are grounding context
        text = " ".join(t for t, q in ctx if not ({"grounding_source", "query"} & set(q)))
    try:
        r = gr.converse_check(gcfg, text if isinstance(text, str) else json.dumps(text), "INPUT")
    except gr.GErr as e:
        return _b_err(e.code, e.msg, e.status)
    return None if r is None else (r["text"], r["assessment"], "INPUT")


def _guard_trace(gcfg, assessment, kind):
    if (gcfg.get("trace") or "disabled") == "disabled":
        return None
    return {"guardrail": ({"inputAssessment": {gcfg["guardrailIdentifier"]: assessment}} if kind == "INPUT"
                          else {"outputAssessments": {gcfg["guardrailIdentifier"]: [assessment]}})}


def _guard_blocked(op, gi, gcfg, t0, usage=None):
    text, assessment, kind = gi
    usage = usage or {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
    trace = _guard_trace(gcfg, assessment, kind)
    lat = {"latencyMs": int((time.time() - t0) * 1000)}
    if op == "converse":
        doc = {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "stopReason": "guardrail_intervened",
               "usage": usage, "metrics": lat}
        if trace:
            doc["trace"] = trace
        return _j(200, doc)
    frames = [eventstream_frame("messageStart", {"role": "assistant"}),
              eventstream_frame("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": text}}),
              eventstream_frame("contentBlockStop", {"contentBlockIndex": 0}),
              eventstream_frame("messageStop", {"stopReason": "guardrail_intervened"}),
              eventstream_frame("metadata", dict({"usage": usage, "metrics": lat}, **({"trace": trace} if trace else {})))]
    return _bytes(200, b"".join(frames), "application/vnd.amazon.eventstream")


def _guard_output(gcfg, r, ctx=None):
    gr = _guardrails()
    if not r.get("text"):
        return None
    try:
        res = gr.converse_check(gcfg, r["text"], "OUTPUT", ctx)
    except gr.GErr as e:
        return _b_err(e.code, e.msg, e.status)
    if res is None:
        return None
    usage = {"inputTokens": r["input_tokens"], "outputTokens": r["output_tokens"], "totalTokens": r["input_tokens"] + r["output_tokens"]}
    return _guard_blocked("converse", (res["text"], res["assessment"], "OUTPUT"), gcfg, time.time(), usage)


def _invoke_guard_cfg(headers):
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    gid = h.get("x-amzn-bedrock-guardrailidentifier")
    if not gid:
        return None
    return {"guardrailIdentifier": gid, "guardrailVersion": h.get("x-amzn-bedrock-guardrailversion") or "",
            "trace": "enabled" if str(h.get("x-amzn-bedrock-trace", "")).upper() == "ENABLED" else "disabled"}


def _invoke_blocked(m, p, op, gi, gcfg, t0):
    """InvokeModel[WithResponseStream] intervened: the family's own response shape carrying the blocked message + guardrail action/trace."""
    text, assessment, kind = gi
    r = {"text": text, "finish_reason": "stop", "input_tokens": 0, "output_tokens": 0, "tool_calls": [], "model": llm.resolve_model(m[0])}
    tr = _guard_trace(gcfg, assessment, kind)
    if op == "invoke-with-response-stream":
        done = {"type": "done", "finish_reason": "stop", "input_tokens": 0, "output_tokens": 0, "tool_calls": [], "guardrail_action": "INTERVENED"}
        if tr:
            done["guardrail_trace"] = tr
        return _stream_out(200, {"x-amzn-bedrock-content-type": "application/json"},
                           _invoke_frames(m, iter([{"type": "text", "text": text}, done]), t0), "application/vnd.amazon.eventstream")
    resp = _bedrock_response(m, p, r)
    resp["amazon-bedrock-guardrailAction"] = "INTERVENED"
    if tr:
        resp["amazon-bedrock-trace"] = tr
    if op == "invoke":
        return _j(200, resp)
    return _bytes(200, eventstream_frame("chunk", {"bytes": base64.b64encode(json.dumps(resp).encode()).decode()}), "application/vnd.amazon.eventstream")


def _trained():
    try:
        from core import training_core as t
    except ImportError:  # Pyodide flat layout
        import training_core as t  # type: ignore
    return t


def _invoke_trained(cid, op, p):
    """InvokeModel / Converse on a custom model trained in core/training_core: {"task":"classify","text"} -> {label, scores}; {"task":"score",
    "query","document"} -> {score}. Converse classifies the last user message. Every answer carries vyomiTrained: it is a head, not an LLM."""
    t = _trained()
    if p is None:
        return _b_err("ValidationException", "Malformed input request, please reformat your input and try again.", 400)
    if op.endswith("stream") or op == "invoke-with-response-stream":
        return _b_err("ValidationException", "This trained model doesn't support streaming operations.", 400)
    t0 = time.time()
    if t.is_chat_model(cid):
        return _invoke_trained_chat(t, cid, op, p, t0)
    try:
        if op == "converse":
            msgs = p.get("messages") or []
            last = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
            txt = " ".join(b.get("text", "") for b in (last or {}).get("content", []) if isinstance(b, dict))
            r = t.invoke(cid, {"task": "classify", "text": txt})
            return _j(200, {"output": {"message": {"role": "assistant", "content": [{"text": r["label"]}]}}, "stopReason": "end_turn",
                            "usage": {"inputTokens": llm.estimate_tokens(txt), "outputTokens": 1, "totalTokens": llm.estimate_tokens(txt) + 1},
                            "metrics": {"latencyMs": int((time.time() - t0) * 1000)},
                            "additionalModelResponseFields": {"vyomiTrained": True, "scores": r["scores"], "embedder": r["embedder"]}},
                      {"x-vyomi-trained": "true"})
        return _j(200, t.invoke(cid, p), {"x-vyomi-trained": "true"})
    except t.TrainError as e:
        return _b_err("ResourceNotFoundException" if e.kind == "notfound" else "ValidationException", str(e), 404 if e.kind == "notfound" else 400)


def _invoke_trained_chat(t, cid, op, p, t0):
    """InvokeModel / Converse on a chat-model LoRA custom model: the base open model + this adapter on the local llama.cpp server.
    InvokeModel bodies: Nova-style {"messages":[{"role","content":[{"text"}]}],"inferenceConfig"} or Llama-style {"prompt","max_gen_len","temperature"}."""
    hdr = {"x-vyomi-trained": "true", "x-vyomi-adapter": cid}
    if op == "converse" or isinstance(p.get("messages"), list):
        req = _converse_request(p, cid)
        if isinstance(req, str):
            return _b_err("ValidationException", req, 400)
        msgs, system, mx, temp, stop, _ = req
    else:
        pr = p.get("prompt")
        if not isinstance(pr, str) or not pr.strip():
            return _b_err("ValidationException", "Malformed input request: provide messages (Converse/Nova style) or prompt (Llama style).", 400)
        msgs, system, mx, temp, stop = [{"role": "user", "content": pr}], None, int(p.get("max_gen_len") or p.get("max_tokens") or 256), float(p.get("temperature", 0.7)), None
    try:
        r = t.invoke_chat(cid, msgs, system, mx, temp, stop)
    except t.TrainError as e:
        return _b_err("ResourceNotFoundException" if e.kind == "notfound" else "ValidationException", str(e), 404 if e.kind == "notfound" else 400)
    except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
        return _ll_err(e)
    usage = {"inputTokens": r["input_tokens"], "outputTokens": r["output_tokens"], "totalTokens": r["input_tokens"] + r["output_tokens"]}
    extra = {"vyomiTrained": True, "adapterId": cid, "baseModel": r["baseModel"]}
    if op == "converse":
        return _j(200, {"output": {"message": {"role": "assistant", "content": [{"text": r["text"]}]}}, "stopReason": _stop_reason(r["finish_reason"]), "usage": usage,
                        "metrics": {"latencyMs": int((time.time() - t0) * 1000)}, "additionalModelResponseFields": extra}, hdr)
    if isinstance(p.get("messages"), list):
        return _j(200, {"output": {"message": {"role": "assistant", "content": [{"text": r["text"]}]}}, "stopReason": _stop_reason(r["finish_reason"]), "usage": usage, **extra}, hdr)
    return _j(200, {"generation": r["text"], "prompt_token_count": r["input_tokens"], "generation_token_count": r["output_tokens"],
                    "stop_reason": "length" if r["finish_reason"] == "length" else "stop", **extra}, hdr)


def bedrock_dispatch(method, path, query, headers, body):
    method, path = method.upper(), "/" + path.strip("/")
    path = re.sub(r"/{2,}", "/", path)
    if path in ("/foundation-models",) and method == "GET":
        outm = (query or {}).get("byOutputModality")
        prov = (query or {}).get("byProvider")
        ms = [m for m in BEDROCK_MODELS if (not outm or outm.upper() in m[4]) and (not prov or prov.lower() == m[1].lower())]
        al = [a for a in (BEDROCK_ALIASES if list_aliases() else []) if (not outm or outm.upper() in a[4]) and (not prov or prov.lower() == a[1].lower())]
        return _j(200, {"modelSummaries": [_summary(m) for m in ms] + [_alias_summary(a) for a in al]})
    if path == "/inference-profiles" and method == "GET":
        return _j(200, {"inferenceProfileSummaries": [_profile(a, pre) for a in (BEDROCK_ALIASES if list_aliases() else []) if "EMBEDDING" not in a[4] and not a[0].startswith(("amazon.titan", "cohere", "meta.llama3-2-3b"))
                                                      for pre in _INF_PROFILE_PREFIX[:1]]})
    mt = re.match(r"^/inference-profiles/(.+)$", path)
    if mt and method == "GET":
        from urllib.parse import unquote
        pid = re.sub(r"^arn:aws[a-z-]*:bedrock:[^:]*:[0-9]*:inference-profile/", "", unquote(mt.group(1)))
        pre, _, base = pid.partition(".")
        if pre in _INF_PROFILE_PREFIX and base in _ALIAS_BY_ID and "EMBEDDING" not in _ALIAS_BY_ID[base][4]:
            return _j(200, _profile(_ALIAS_BY_ID[base], pre))
        return _b_err("ResourceNotFoundException", "Could not find the inference profile from the provided identifier.", 404)
    _gr = _guardrails()
    if _gr.handles(path):
        return _gr.dispatch(method, path, query, body)
    mt = re.match(r"^/foundation-models/(.+)$", path)
    if mt and method == "GET":
        from urllib.parse import unquote
        mid = unquote(mt.group(1))
        if mid in _ALIAS_BY_ID:
            return _j(200, {"modelDetails": _alias_summary(_ALIAS_BY_ID[mid])})
        m = _BM.get(mid)
        if not m:
            return _b_err("ResourceNotFoundException", f"Could not resolve the foundation model from the provided model identifier.", 404)
        return _j(200, {"modelDetails": _summary(m)})
    mt = re.match(r"^/model/(.+?)/count-tokens$", path)
    if mt and method == "POST":   # Bedrock CountTokens: same ~4 chars/token estimate the local-LLM seam uses when no backend usage exists
        from urllib.parse import unquote
        if not _resolve_model(unquote(mt.group(1))):
            return _b_err("ValidationException", "The provided model identifier is invalid.", 400)
        p = _body(body)
        inp = (p or {}).get("input") if isinstance(p, dict) else None
        if not isinstance(inp, dict) or not ({"converse", "invokeModel"} & set(inp)):
            return _b_err("ValidationException", "Malformed input request: input must contain converse or invokeModel.", 400)
        if "converse" in inp:
            txt = " ".join(str(c.get("text", "")) for m_ in (inp["converse"].get("messages") or []) for c in (m_.get("content") or []) if isinstance(c, dict))
            txt += " ".join(str(c.get("text", "")) for c in (inp["converse"].get("system") or []) if isinstance(c, dict))
        else:
            txt = str(inp["invokeModel"].get("body", ""))
            try:
                txt = base64.b64decode(txt).decode("utf-8", "replace")
            except Exception:
                pass
        return _j(200, {"inputTokens": llm.estimate_tokens(txt)})
    mt = re.match(r"^/model/(.+?)/(invoke|invoke-with-response-stream|converse|converse-stream)$", path)
    if not mt:
        return _b_err("UnknownOperationException", f"Unsupported Bedrock operation: {method} {path}", 404)
    if method != "POST":
        return _b_err("UnknownOperationException", f"{method} is not supported for this operation", 405)
    from urllib.parse import unquote
    mid, op = unquote(mt.group(1)), mt.group(2)
    tm = re.match(r"^arn:aws[a-z-]*:bedrock:[^:]*:[0-9]*:custom-model/(.+)$", mid)
    if tm and _trained().has_model(tm.group(1)):      # a head trained by core/training_core: not an LLM, answered by the head itself
        return _invoke_trained(tm.group(1), op, _body(body))
    m = _resolve_model(mid)
    if not m:
        return _b_err("ValidationException", "The provided model identifier is invalid.", 400)
    p = _body(body)
    if p is None:
        return _b_err("ValidationException", "Malformed input request, please reformat your input and try again.", 400)
    if m[0] in CAT._BYNAME:     # native ids: Converse-style body -> nova family, else Llama-style
        m = m + ("amazon.nova-vyomi" if isinstance(p.get("messages"), list) else "vyomi-prompt",)
    t0 = time.time()
    if op.startswith("converse"):
        if m[5] is False and "TEXT" not in m[4]:
            return _b_err("ValidationException", f"This model doesn't support the {op} operation.", 400)
        req = _converse_request(p, m[0])
        if isinstance(req, str):
            return _b_err("ValidationException", req, 400)
        gcfg = p.get("guardrailConfig")
        gctx = _guard_blocks(p) if gcfg else []
        if gcfg:
            gi = _guard_input(gcfg, req[0], gctx)
            if isinstance(gi, tuple):
                return _guard_blocked(op, gi, gcfg, t0)
            if gi is not None:
                return gi
        try:
            if op == "converse-stream":
                it = _prime(llm.chat_stream(*req[:5], **req[5]))
                if gcfg:       # output guarding in buffered windows (streamProcessingMode sync|async)
                    gr = _guardrails()
                    it = gr.guard_events(it, gr.policy_of(gcfg), gcfg.get("streamProcessingMode") or "sync", gctx,
                                         gcfg["guardrailIdentifier"], (gcfg.get("trace") or "disabled") != "disabled")
            else:
                r = _llm_chat(req)
        except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
            return _ll_err(e)
        except ValueError as e:
            return _b_err("ValidationException", str(e), 400)
        except _guardrails().GErr as e:
            return _b_err(e.code, e.msg, e.status)
        if op == "converse" and gcfg:
            go = _guard_output(gcfg, r, gctx)
            if go is not None:
                return go
        if op == "converse":
            usage = _usage(r, _cache_account(p, "converse", r["input_tokens"]))
            return _j(200, {"output": {"message": {"role": "assistant", "content": _converse_content(r)}},
                            "stopReason": _stop_reason(r["finish_reason"]), "usage": usage,
                            "metrics": {"latencyMs": int((time.time() - t0) * 1000)},
                            **({"additionalModelResponseFields": {"vyomiImported": True, "vyomiTrained": True}} if _fam(m) == "vyomi.import" else {})},
                      {"x-vyomi-local-model": r["model"]})
        return _stream_out(200, {}, _converse_frames(it, t0, lambda n: _cache_account(p, "converse", n)), "application/vnd.amazon.eventstream")
    # InvokeModel[WithResponseStream]
    if m[6] == CAT.DEFAULT_EMBED and m[0] in CAT._BYNAME:      # native ids: 768-d nomic-style embedding, Titan-free body
        if op != "invoke":
            return _b_err("ValidationException", "This model doesn't support the InvokeModelWithResponseStream operation.", 400)
        txt = p.get("inputText") or p.get("prompt") or p.get("input")
        if not isinstance(txt, str) or not txt:
            return _b_err("ValidationException", "Malformed input request: required key [inputText] not found, please reformat your input and try again.", 400)
        e = llm.embed(txt)
        v = (e["vectors"][0] + [0.0] * 768)[:768]
        return _j(200, {"embedding": v, "inputTextTokenCount": e["input_tokens"]}, {"x-amzn-bedrock-input-token-count": str(e["input_tokens"])})
    if m[0].startswith("amazon.titan-embed") or m[6] == CAT.DEFAULT_EMBED:
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
    gcfg, gr = _invoke_guard_cfg(headers), _guardrails()
    if gcfg:     # X-Amzn-Bedrock-Guardrail* headers: input is judged first, output after (windowed for streams)
        gi = _guard_input(gcfg, req[0])
        if isinstance(gi, tuple):
            return _invoke_blocked(m, p, op, gi, gcfg, t0)
        if gi is not None:
            return gi
    if op == "invoke-with-response-stream":
        try:
            it = _prime(llm.chat_stream(*req[:5], **req[5]))
            if gcfg:
                it = gr.guard_events(it, gr.policy_of(gcfg), "sync", None, gcfg["guardrailIdentifier"], (gcfg.get("trace") or "disabled") != "disabled")
        except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
            return _ll_err(e)
        except ValueError as e:
            return _b_err("ValidationException", str(e), 400)
        except gr.GErr as e:
            return _b_err(e.code, e.msg, e.status)
        return _stream_out(200, {"x-amzn-bedrock-content-type": "application/json", "x-vyomi-local-model": llm.resolve_model(m[0])},
                           _invoke_frames(m, it, t0), "application/vnd.amazon.eventstream")
    try:
        r = _llm_chat(req)
    except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
        return _ll_err(e)
    except ValueError as e:
        return _b_err("ValidationException", str(e), 400)
    if gcfg:
        try:
            res = gr.converse_check(gcfg, r["text"], "OUTPUT") if r.get("text") else None
        except gr.GErr as e:
            return _b_err(e.code, e.msg, e.status)
        if res is not None:
            return _invoke_blocked(m, p, op, (res["text"], res["assessment"], "OUTPUT"), gcfg, t0)
    resp = _bedrock_response(m, p, r)
    if _fam(m).startswith("anthropic."):
        ca = _cache_account(p, "claude", r["input_tokens"])
        if ca:
            resp["usage"] = {"input_tokens": ca["uncached"], "output_tokens": r["output_tokens"],
                             "cache_read_input_tokens": ca["read"], "cache_creation_input_tokens": ca["write"]}
    if gcfg:
        resp["amazon-bedrock-guardrailAction"] = "NONE"
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
            "customizationsSupported": [], "inferenceTypesSupported": ["ON_DEMAND"], "modelLifecycle": {"status": "ACTIVE"},
            "vyomiAvailability": CAT.availability(m[6])}


def _backed_by(mid):
    m = _resolve_model(mid)
    cid = m[6] if m else CAT.DEFAULT_CHAT
    return {"catalogModelId": cid, "localModel": llm.resolve_model(mid), "availability": CAT.availability(cid),
            "note": "Vyomi alias: this standard Bedrock id is answered by the local open model above (Mesh: llama.cpp Qwen2.5 via the "
                    "core/llm_core seam; Nano: WebLLM), not by the original vendor model. Behaviour and quality are those of the local model."}


def _alias_summary(a):
    return {"modelArn": f"arn:aws:bedrock:us-east-1::foundation-model/{a[0]}", "modelId": a[0], "modelName": a[2],
            "providerName": a[1], "inputModalities": a[3], "outputModalities": a[4], "responseStreamingSupported": a[5],
            "customizationsSupported": [], "inferenceTypesSupported": ["ON_DEMAND"], "modelLifecycle": {"status": "ACTIVE"},
            "vyomiBackedBy": _backed_by(a[0])}


def _profile(a, pre):
    return {"inferenceProfileName": f"{pre.upper()} {a[2]}", "description": f"Vyomi system-defined cross-Region profile alias for {a[0]} (local model)",
            "createdAt": "2024-08-01T00:00:00Z", "updatedAt": "2024-08-01T00:00:00Z",
            "inferenceProfileArn": f"arn:aws:bedrock:us-east-1:000000000000:inference-profile/{pre}.{a[0]}",
            "models": [{"modelArn": f"arn:aws:bedrock:us-east-1::foundation-model/{a[0]}"}],
            "inferenceProfileId": f"{pre}.{a[0]}", "status": "ACTIVE", "type": "SYSTEM_DEFINED"}


# ───────────────────────────── Vertex AI ─────────────────────────────
# Vertex / Gemini-API model ids: the ten catalogue models by bare id (and ollama/vyomi by-name ids); legacy gemini-*/text-embedding-*
# ids still RESOLVE through the hidden alias map but are never listed (core/ai_model_catalog.py).
def _vx_known(model):
    return CAT.resolve("gcp", model) is not None


def _vx_embed(model):
    return CAT.resolve("gcp", model) == CAT.DEFAULT_EMBED


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


def _gdev_dispatch(method, path, query, headers, body):
    """Gemini Developer API (generativelanguage.googleapis.com /v1beta|/v1 /models/...) over the same seam as Vertex.
    Differences from Vertex handled here: API-key auth (x-goog-api-key / ?key=), models.list/get, batchEmbedContents,
    embedContent takes `model` in the body. Everything else is the Vertex publisher-model wire, which google-genai shares."""
    lh = {k.lower(): v for k, v in (headers or {}).items()}
    if not (lh.get("x-goog-api-key") or (query or {}).get("key") or lh.get("authorization")):
        return _g_err(403, "PERMISSION_DENIED", "Method doesn't allow unregistered callers (callers without established identity). "
                      "Please use API Key or other form of API consumer identity to call this API.")
    method = method.upper()
    mt = re.match(r"^/v1(?:beta)?/models/?$", path)
    if mt and method == "GET":
        return _j(200, {"models": [_gdev_model(m) for m in CAT.IDS]})
    mt = re.match(r"^/v1(?:beta)?/models/([^/:]+)$", path)
    if mt and method == "GET":
        m = mt.group(1)
        if not _vx_known(m):
            return _g_err(404, "NOT_FOUND", f"models/{m} is not found for API version v1beta, or is not supported for this method.")
        return _j(200, _gdev_model(m))
    mt = re.match(r"^/v1(?:beta)?/models/([^/:]+):([A-Za-z]+)$", path)
    if not mt or method != "POST":
        return _g_err(404, "NOT_FOUND", f"Unsupported Gemini API operation: {method} {path}")
    model, op = mt.groups()
    if not _vx_known(model):
        return _g_err(404, "NOT_FOUND", f"models/{model} is not found for API version v1beta, or is not supported for {op}. "
                      "Call ListModels to see the list of available models and their supported methods.")
    p = _body(body)
    if p is None:
        return _g_err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if op == "batchEmbedContents":
        reqs = p.get("requests")
        if not isinstance(reqs, list) or not reqs:
            return _g_err(400, "INVALID_ARGUMENT", "requests: at least one request is required.")
        texts = ["".join(x.get("text", "") for x in ((r.get("content") or {}).get("parts") or [])) for r in reqs]
        if not all(texts):
            return _g_err(400, "INVALID_ARGUMENT", "content.parts: at least one text part is required in every request.")
        return _j(200, {"embeddings": [{"values": v} for v in llm.embed(texts)["vectors"]]})
    if op == "embedContent" and not _vx_embed(model):
        return _g_err(400, "INVALID_ARGUMENT", f"models/{model} does not support embedContent.")
    if op == "generateContent" and _vx_embed(model):
        return _g_err(400, "INVALID_ARGUMENT", f"models/{model} does not support generateContent.")
    r = vertex_dispatch("POST", f"/v1/projects/gemini-api/locations/global/publishers/google/models/{model}:{op}", query, headers, body)
    return r


def _gdev_model(m):
    emb = _vx_embed(m)
    return {"name": f"models/{m}", "version": "001", "displayName": CAT.BY_ID[m]["name"] if m in CAT.BY_ID else m,
            "description": (CAT.BY_ID[m]["blurb"] if m in CAT.BY_ID else "Vyomi mesh-llm model") + f" ({CAT.availability(CAT.resolve('gcp', m) or m)['label']})",
            "inputTokenLimit": 8192, "outputTokenLimit": 1 if emb else 8192,
            "supportedGenerationMethods": ["embedContent", "batchEmbedContents"] if emb else ["generateContent", "streamGenerateContent", "countTokens"]}


def vertex_dispatch(method, path, query, headers, body):
    if re.match(r"^/v1(?:beta)?/models(?:[/:]|$)", path):
        return _gdev_dispatch(method, path, query, headers, body)
    mt = re.match(r"^/v1(?:beta1)?/projects/([^/]+)/locations/([^/]+)/publishers/([^/]+)/models/([^/:]+):([A-Za-z]+)$", path)
    if not mt or method.upper() != "POST":
        return _g_err(404, "NOT_FOUND", f"Unsupported Vertex AI operation: {method} {path}")
    proj, loc, pub, model, op = mt.groups()
    p = _body(body)
    if p is None:
        return _g_err(400, "INVALID_ARGUMENT", "Invalid JSON payload received.")
    if not _vx_known(model):
        return _g_err(404, "NOT_FOUND", f"Publisher Model `projects/{proj}/locations/{loc}/publishers/{pub}/models/{model}` was not found "
                                         "or your project does not have access to it.")
    if op in ("embedContent", "predict") or _vx_embed(model):
        if not _vx_embed(model):
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


def vertex_imported_call(model_id, op, p, query=None):
    """Endpoint :generateContent / :streamGenerateContent / :predict on a deployed IMPORTED chat model (core/import_core; wllama on Nano)."""
    ic = _imported()
    if not ic.has_model(model_id):
        return _g_err(404, "NOT_FOUND", f"Imported model {model_id} not found.")
    if op == "predict":      # vLLM-style custom-container instances: {"prompt" | "messages", "max_tokens", "temperature"}
        inst = p.get("instances")
        if not isinstance(inst, list) or not inst or not all(isinstance(i, dict) for i in inst):
            return _g_err(400, "INVALID_ARGUMENT", "instances: a non-empty list of objects is required.")
        preds = []
        for i in inst:
            msgs = i.get("messages") if isinstance(i.get("messages"), list) else ([{"role": "user", "content": i["prompt"]}] if isinstance(i.get("prompt"), str) and i["prompt"] else None)
            if not msgs or not all(isinstance(x, dict) and isinstance(x.get("content"), str) and x.get("role") in ("system", "user", "assistant") for x in msgs):
                return _g_err(400, "INVALID_ARGUMENT", "each instance needs a prompt string or messages [{role, content}].")
            try:
                r = llm.chat(msgs, None, i.get("max_tokens") or 256, i.get("temperature", 0.0), i.get("stop"), model=model_id)
            except llm.LlmUnavailable as e:
                return _g_err(503, "UNAVAILABLE", f"{e}")
            preds.append({"content": r["text"], "finishReason": "length" if r["finish_reason"] == "length" else "stop",
                          "usage": {"promptTokens": r["input_tokens"], "completionTokens": r["output_tokens"]}, "vyomiImported": True, "vyomiTrained": True})
        return _j(200, {"predictions": preds, "model": model_id, "vyomiImported": True, "vyomiTrained": True})
    req = _gem_request(p)
    if isinstance(req, str):
        return _g_err(400, "INVALID_ARGUMENT", req)
    req = (req[0], req[1], req[2], req[3], req[4], dict(req[5], model=model_id))
    try:
        r = _llm_chat(req)
    except llm.LlmStructuredError as e:
        return _g_err(500, "INTERNAL", str(e))
    except llm.LlmUnavailable as e:
        return _g_err(503, "UNAVAILABLE", f"{e}")
    except ValueError as e:
        return _g_err(400, "INVALID_ARGUMENT", str(e))
    out = {"candidates": [{"content": {"role": "model", "parts": _gem_parts(r["text"], r["tool_calls"])}, "index": 0,
                           "finishReason": "MAX_TOKENS" if r["finish_reason"] == "length" else "STOP"}],
           "usageMetadata": _gem_usage(r), "modelVersion": model_id, "responseId": uuid.uuid4().hex[:20], "vyomiImported": True, "vyomiTrained": True}
    if op == "streamGenerateContent":      # buffered: one chunk with the finished answer (the wllama path answers whole)
        sse = (query or {}).get("alt") == "sse"
        return _stream_out(200, {}, iter([("data: " + json.dumps(out) + "\n\n") if sse else json.dumps([out])]), "text/event-stream" if sse else "application/json")
    return _j(200, out, {"x-vyomi-local-model": r["model"]})



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


def _azure_agents():
    try:
        from core import azure_openai_agents_core as a
    except ImportError:  # Pyodide flat layout
        import azure_openai_agents_core as a  # type: ignore
    return a


# ───────── Azure OpenAI fine-tuning + files (a trainable base runs a REAL head-training job in core/training_core) ─────────
_AZ_FILES: dict[str, dict] = {}
_AZ_FT: dict[str, dict] = {}


def _ft_status(v):
    return {"Queued": "queued", "Completed": "succeeded", "Failed": "failed", "Stopped": "cancelled"}.get(v["status"], "running")


def _ft_view(j):
    """OpenAI fine_tuning.job object, kept in step with the live training job (+ the Vyomi extension vyomiTraining)."""
    t = _trained()
    try:
        v = t.view(j["model_id"])
    except t.TrainError:
        v = {"status": "Failed", "metrics": []}
    st = _ft_status(v)
    if st == "succeeded" and not j.get("fine_tuned_model"):
        j["fine_tuned_model"] = f"ft:{j['model']}:{j['suffix'] or 'vyomi'}:{j['id'][len('ftjob-'):]}"
    if st in ("succeeded", "failed", "cancelled") and not j.get("finished_at"):
        j["finished_at"] = int(time.time())
    out = {k: v2 for k, v2 in j.items() if k not in ("model_id", "suffix")}
    out.update(status=st, vyomiTraining=v, trained_tokens=(sum(1 for _ in v.get("metrics", [])) * v.get("rows", 0) or None) if st == "succeeded" else None,
               error=({"code": "training_failed", "message": v.get("note", "Training failed.")} if st == "failed" else {}))
    return out


def _ft_events(j):
    v = _ft_view(j)
    ev, base = [], j["created_at"]
    ev.append({"object": "fine_tuning.job.event", "id": "ftevent-0", "created_at": base, "level": "info", "message": "Job enqueued. Waiting for jobs ahead to complete.", "data": None, "type": "message"})
    for st in (v["vyomiTraining"].get("steps") or []):      # chat LoRA: one event per optimiser step like the real service
        ev.append({"object": "fine_tuning.job.event", "id": f"ftevent-s{st['step']}", "created_at": base + st["step"], "level": "info",
                   "message": f"Step {st['step']}: training loss={st['loss']}", "type": "metrics", "data": {"step": st["step"], "train_loss": st["loss"]}})
    for m in ([] if v["vyomiTraining"].get("steps") else (v["vyomiTraining"].get("metrics") or [])):
        ev.append({"object": "fine_tuning.job.event", "id": f"ftevent-{m['epoch']}", "created_at": base + m["epoch"], "level": "info",
                   "message": f"Epoch {m['epoch']}/{v['vyomiTraining'].get('epochs')}: loss={m['loss']} accuracy={m['accuracy']}", "type": "metrics",
                   "data": {"step": m["epoch"], "train_loss": m["loss"], "train_mean_token_accuracy": m["accuracy"], "valid_mean_token_accuracy": m.get("valAccuracy")}})
    if v["status"] == "succeeded":
        ev.append({"object": "fine_tuning.job.event", "id": "ftevent-done", "created_at": v.get("finished_at") or int(time.time()), "level": "info",
                   "message": f"New fine-tuned model created: {v['fine_tuned_model']}", "data": None, "type": "message"})
    return list(reversed(ev))


def _multipart(headers, body):
    from email.parser import BytesParser
    from email.policy import default
    msg = BytesParser(policy=default).parsebytes(b"Content-Type: " + headers.get("content-type", "").encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    out = {}
    for part in msg.iter_parts() if msg.is_multipart() else []:
        out[part.get_param("name", header="content-disposition")] = (part.get_filename(), part.get_payload(decode=True) or b"")
    return out


def _azure_files_ft(method, path, query, lh, body):
    """/openai/files + /openai/fine_tuning/jobs[/{id}[/cancel|/events]] (also under /openai/v1)."""
    t = _trained()
    if not (lh.get("api-key") or lh.get("authorization")):
        return _j(401, {"error": {"code": "401", "message": "Access denied due to missing subscription key. Make sure to include subscription key when making requests to an API."}})
    path = re.sub(r"^/openai(/v1)?", "", path).rstrip("/")
    method = method.upper()
    now = int(time.time())

    def bad(msg, param=None, code="invalid_request_error", status=400):
        return _j(status, {"error": {"code": code, "message": msg, "param": param, "type": "invalid_request_error"}})
    if path == "/files" and method == "POST":
        parts = _multipart(lh, body) if "multipart/form-data" in lh.get("content-type", "") else {}
        if "file" not in parts:
            return bad("Missing required parameter: 'file'.", "file")
        purpose = parts.get("purpose", (None, b""))[1].decode() or "fine-tune"
        fid = "file-" + uuid.uuid4().hex[:24]
        t.put_file(fid, parts["file"][1])
        _AZ_FILES[fid] = {"id": fid, "object": "file", "bytes": len(parts["file"][1]), "created_at": now, "filename": parts["file"][0] or "file.jsonl", "purpose": purpose, "status": "processed", "status_details": None}
        return _j(200, _AZ_FILES[fid])
    if path == "/files" and method == "GET":
        return _j(200, {"object": "list", "data": list(_AZ_FILES.values()), "has_more": False})
    mf = re.match(r"^/files/([^/]+)(/content)?$", path)
    if mf:
        f = _AZ_FILES.get(mf.group(1))
        if not f:
            return bad(f"File {mf.group(1)} not found.", None, "NotFound", 404)
        if method == "DELETE":
            del _AZ_FILES[f["id"]]
            return _j(200, {"object": "file", "id": f["id"], "deleted": True})
        if mf.group(2):
            return _bytes(200, t.get_file(f["id"]) or b"", "application/octet-stream")
        return _j(200, f)
    if path == "/fine_tuning/jobs" and method == "POST":
        p = _body(body)
        if p is None:
            return bad("Invalid JSON body.")
        model, tf = p.get("model"), p.get("training_file")
        if not model:
            return bad("Missing required parameter: 'model'.", "model")
        if not tf:
            return bad("Missing required parameter: 'training_file'.", "training_file")
        if not t.is_trainable(model):
            return bad(f"The model {model} cannot be fine-tuned by Vyomi (trainable: {', '.join(t.TRAINABLE_EMBEDDERS)} or {t.HEAD_PREFIX}*); real model customization is metadata-only here.", "model", "model_not_trainable")
        if tf not in _AZ_FILES:
            return bad(f"No such File object: {tf}", "training_file", "invalid_request_error", 404)
        jid = "ftjob-" + uuid.uuid4().hex[:24]
        hpr = dict(p.get("hyperparameters") or {})
        try:
            _hy = {"epochs": hpr.get("n_epochs"), "batchSize": hpr.get("batch_size"), "learningRateMultiplier": hpr.get("learning_rate_multiplier")}
            t.start("azft-" + jid[6:], "azft-" + jid[6:], t.get_file(tf) or b"", {k: v for k, v in _hy.items() if v not in (None, "auto")}, None, model, p.get("suffix") or "")
        except t.TrainError as e:
            return bad(str(e), "training_file")
        j = {"id": jid, "object": "fine_tuning.job", "model": model, "created_at": now, "finished_at": None, "fine_tuned_model": None, "organization_id": "org-vyomi",
             "result_files": [], "training_file": tf, "validation_file": p.get("validation_file"), "seed": p.get("seed") or 7, "suffix": p.get("suffix"),
             "hyperparameters": {"n_epochs": int(hpr.get("n_epochs") or 10) if str(hpr.get("n_epochs", "")).isdigit() or hpr.get("n_epochs") is None else 10,
                                 "batch_size": hpr.get("batch_size") or "auto", "learning_rate_multiplier": hpr.get("learning_rate_multiplier") or "auto"},
             "model_id": "azft-" + jid[6:]}
        _AZ_FT[jid] = j
        return _j(200, _ft_view(j))
    if path == "/fine_tuning/jobs" and method == "GET":
        return _j(200, {"object": "list", "data": [_ft_view(j) for j in reversed(list(_AZ_FT.values()))], "has_more": False})
    mj = re.match(r"^/fine_tuning/jobs/([^/]+)(?:/(cancel|events))?$", path)
    if mj:
        j = _AZ_FT.get(mj.group(1))
        if not j:
            return bad(f"Fine-tuning job {mj.group(1)} not found.", None, "NotFound", 404)
        if mj.group(2) == "cancel" and method == "POST":
            try:
                t.stop(j["model_id"])
            except t.TrainError as e:
                return bad(str(e), None, "conflict", 409)
            return _j(200, _ft_view(j))
        if mj.group(2) == "events" and method == "GET":
            return _j(200, {"object": "list", "data": _ft_events(j), "has_more": False})
        if not mj.group(2) and method == "GET":
            return _j(200, _ft_view(j))
    return _a_err(404, "404", "Resource not found")


def _azure_lora_chat(t, mid, model, p):
    """chat/completions on a deployment of a LoRA-tuned chat model (ft:): base open model + adapter on the local llama.cpp server."""
    if p.get("stream"):
        return _a_err(400, "BadRequest", "This fine-tuned model does not support streaming in Vyomi.", "stream")
    req = _az_chat_request(p)
    if isinstance(req[0], str) and not isinstance(req[0], list):
        return _a_err(400, "BadRequest", req[1], req[0])
    msgs, system, mx, temp, stop = req[:5]
    try:
        r = t.invoke_chat(mid, msgs, system, mx, temp, stop)
    except t.TrainError as e:
        return _a_err(404 if e.kind == "notfound" else 400, "NotFound" if e.kind == "notfound" else "BadRequest", str(e))
    except llm.LlmUnavailable as e:
        return _a_err(503, "ServiceUnavailable", f"{e}")
    u = {"prompt_tokens": r["input_tokens"], "completion_tokens": r["output_tokens"], "total_tokens": r["input_tokens"] + r["output_tokens"]}
    return _j(200, {"id": "chatcmpl-" + uuid.uuid4().hex[:29], "object": "chat.completion", "created": int(time.time()), "model": model,
                    "choices": [{"index": 0, "finish_reason": "length" if r["finish_reason"] == "length" else "stop", "message": {"role": "assistant", "content": r["text"]}}],
                    "usage": u, "vyomiTrained": True, "vyomiAdapter": mid, "vyomiBaseModel": r["baseModel"],
                    "vyomiNote": "Vyomi extension: the open base model plus your LoRA adapter answered; this is not a vendor model."}, {"x-vyomi-trained": "true"})


def _azure_trained_chat(model, p):
    """chat/completions on a deployment of a fine-tuned head (Vyomi extension: the head classifies the last user message)."""
    t = _trained()
    mid = "azft-" + model.rsplit(":", 1)[-1]
    if not t.has_model(mid):
        return None
    if t.is_chat_model(mid):
        return _azure_lora_chat(t, mid, model, p)
    msgs = p.get("messages") or []
    last = next((m for m in reversed(msgs) if isinstance(m, dict) and m.get("role") == "user"), None)
    c = (last or {}).get("content")
    txt = c if isinstance(c, str) else " ".join(b.get("text", "") for b in (c or []) if isinstance(b, dict))
    if not txt.strip():
        return _a_err(400, "BadRequest", "'messages' must contain a user message to classify.", "messages")
    try:
        r = t.invoke(mid, {"task": "classify", "text": txt})
    except t.TrainError as e:
        return _a_err(404 if e.kind == "notfound" else 400, "BadRequest" if e.kind != "notfound" else "NotFound", str(e))
    n = llm.estimate_tokens(txt)
    return _j(200, {"id": "chatcmpl-" + uuid.uuid4().hex[:29], "object": "chat.completion", "created": int(time.time()), "model": model,
                    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": r["label"]}}],
                    "usage": {"prompt_tokens": n, "completion_tokens": 1, "total_tokens": n + 1},
                    "vyomiTrained": True, "vyomiScores": r["scores"],
                    "vyomiNote": "Vyomi extension: a trained classifier head answered (label as assistant content); this is not an LLM."})


# ───────── Imported chat models (LoRA adapter GGUF + base, served by wllama on Nano): Azure registration is a VYOMI EXTENSION (no real API fits) ─────────
def _imported():
    try:
        from core import import_core as m
    except ImportError:  # Pyodide flat layout
        import import_core as m  # type: ignore
    return m


def _az_cm_view(r):
    return {"id": r["modelId"], "object": "vyomi.custom_model", "name": r["name"], "status": "succeeded", "created_at": r["createdAt"], "base_model": r["base"],
            "vyomiImported": True, "vyomiTrained": True,
            "vyomiImport": {"engine": r.get("engine"), "rank": r.get("rank"), "alpha": r.get("alpha"), "adapterBytes": r.get("adapterBytes"), "adapterSha256": r.get("adapterSha256")},
            "vyomiNote": "Vyomi extension (no real Azure API registers a custom LoRA model this way): base GGUF + your adapter, served in the browser. Deploy it with an ARM "
                         "deployment whose model.name is this id (format Vyomi)."}


def _azure_custom_models(method, path, lh, body):
    """POST /openai/vyomi/custom-models (multipart: name, adapter, meta  |  JSON: {name, adapter_file, meta_file} with ids from /openai/files); GET list/one; DELETE."""
    ic, t = _imported(), _trained()
    if not (lh.get("api-key") or lh.get("authorization")):
        return _j(401, {"error": {"code": "401", "message": "Access denied due to missing subscription key. Make sure to include subscription key when making requests to an API."}})
    path = re.sub(r"^/openai(/v1)?/vyomi/custom-models", "", path).rstrip("/")
    method = method.upper()

    def bad(msg, param=None, code="invalid_request_error", status=400):
        return _j(status, {"error": {"code": code, "message": msg, "param": param, "type": "invalid_request_error"}})
    mine = lambda: [r for r in ic.persisted_models() if r.get("cloud") == "azure"]
    if path == "" and method == "GET":
        return _j(200, {"object": "list", "data": [_az_cm_view(r) for r in mine()], "has_more": False})
    if path == "" and method == "POST":
        try:
            if "multipart/form-data" in lh.get("content-type", ""):
                parts = _multipart(lh, body)
                name = (parts.get("name") or (None, b""))[1].decode() or None
                if "adapter" not in parts or "meta" not in parts:
                    return bad("Both 'adapter' (adapter.gguf) and 'meta' (adapter_meta.json) files are required.", "adapter")
                adapter, meta, src = parts["adapter"][1], parts["meta"][1], "upload"
            else:
                p = _body(body)
                if p is None:
                    return bad("Invalid JSON body.")
                name = p.get("name")
                fa, fm = p.get("adapter_file"), p.get("meta_file")
                if not fa or not fm:
                    return bad("Missing 'adapter_file' and 'meta_file' (ids from POST /openai/files holding adapter.gguf and adapter_meta.json), or upload both files as multipart.", "adapter_file")
                adapter, meta, src = t.get_file(fa), t.get_file(fm), f"files:{fa},{fm}"
                if adapter is None or meta is None:
                    return bad(f"No such File object: {fa if adapter is None else fm}", "adapter_file", "invalid_request_error", 404)
            if not name or not re.match(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,63}$", name):
                return bad("'name' is required (letters, digits, . _ ~ -).", "name")
            if any(r["name"] == name for r in mine()):
                return bad(f"A custom model named {name} already exists.", "name", "Conflict", 409)
            mid = ic.ID_PREFIX + uuid.uuid4().hex[:8]
            r = ic.register(mid, name, adapter, meta, src, extra={"cloud": "azure"})
        except ic.ImportErr as e:
            return bad(str(e), "adapter")
        return _j(200, _az_cm_view(r))
    mm = re.match(r"^/([^/]+)$", path)
    if mm:
        r = next((x for x in mine() if x["modelId"] == mm.group(1) or x["name"] == mm.group(1)), None)
        if not r:
            return bad(f"Custom model {mm.group(1)} not found.", None, "NotFound", 404)
        if method == "GET":
            return _j(200, _az_cm_view(r))
        if method == "DELETE":
            ic.delete_model(r["modelId"])
            return _j(200, {"object": "vyomi.custom_model", "id": r["modelId"], "deleted": True})
    return _a_err(404, "404", "Resource not found")



def _az_rai_policy(acct, dep, source):
    """Azure OpenAI content filter (a user-managed raiPolicy on the deployment) -> a bedrock_guardrails_core policy dict, or None.
    Hate/Sexual/Violence map to the guardrail content filters and Jailbreak to PROMPT_ATTACK (input only); a severity threshold of
    Low/Medium/High blocks at filter strength HIGH/MEDIUM/LOW. SelfHarm is not modelled by the engine. Built-in policies do not block."""
    name = str((dep.get("properties") or {}).get("raiPolicyName") or "")
    pol = ((acct or {}).get("_rai") or {}).get(name.lower())
    if not pol:
        return None
    kinds = {"hate": "HATE", "sexual": "SEXUAL", "violence": "VIOLENCE", "jailbreak": "PROMPT_ATTACK"}
    strength = {"low": "HIGH", "medium": "MEDIUM", "high": "LOW"}
    flt = []
    for f in (pol.get("properties") or {}).get("contentFilters") or []:
        t = kinds.get(str(f.get("name", "")).lower())
        if not t or not f.get("enabled", True) or not f.get("blocking", True):
            continue
        if (t == "PROMPT_ATTACK" and source != "Prompt") or (t != "PROMPT_ATTACK" and str(f.get("source", "Prompt")).lower() != source.lower()):
            continue
        st = strength.get(str(f.get("severityThreshold", "Medium")).lower(), "MEDIUM")
        flt.append({"type": t, "inputStrength": st, "outputStrength": "NONE" if t == "PROMPT_ATTACK" else st})
    return {"contentPolicyConfig": {"filtersConfig": flt}, "blockedInputMessaging": "", "blockedOutputsMessaging": ""} if flt else None


def _az_filtered(assess):
    return {k: {"filtered": True, "severity": str(v.get("confidence", "medium")).lower()} for k, v in
            ((str(f["type"]).lower().replace("prompt_attack", "jailbreak"), f) for f in (assess.get("contentPolicy") or {}).get("filters", []))}


def _az_block_input(acct, dep, req):
    pol = _az_rai_policy(acct, dep, "Prompt")
    if not pol:
        return None
    text = "\n".join(str(m.get("content") or "") if isinstance(m, dict) else str(m) for m in req[0])
    r = _guardrails().evaluate(pol, text, "INPUT")
    if not r["blocked"]:
        return None
    return _j(400, {"error": {"message": "The response was filtered due to the prompt triggering Azure OpenAI's content management policy. "
                                         "Please modify your prompt and retry.", "type": None, "param": "prompt", "code": "content_filter", "status": 400,
                              "innererror": {"code": "ResponsibleAIPolicyViolation", "content_filter_result": _az_filtered(r["assessment"])}}})


def _az_block_output(acct, dep, text):
    pol = _az_rai_policy(acct, dep, "Completion")
    if not pol:
        return None
    r = _guardrails().evaluate(pol, text, "OUTPUT")
    return _az_filtered(r["assessment"]) if r["blocked"] else None


def azure_openai_dispatch(arm_state, method, path, query, headers, body, net_state=None):
    if re.match(r"^/openai(/v1)?/(files|fine_tuning)(/|$)", path):
        return _azure_files_ft(method, path, query, {k.lower(): v for k, v in (headers or {}).items()}, body)
    if re.match(r"^/openai(/v1)?/vyomi/custom-models(/|$)", path):
        return _azure_custom_models(method, path, {k.lower(): v for k, v in (headers or {}).items()}, body)
    ag = _azure_agents()
    mt = re.match(r"^/openai/(?:deployments/([^/]+)/)?(chat/completions|completions|embeddings)$", path) \
        or re.match(r"^/openai/(?:v1/)?()(chat/completions|completions|embeddings|responses)$", path)
    if mt is None and ag.handles(path):      # Responses get/delete + Assistants/threads/runs (Dev Simplified)
        lh0 = {k.lower(): v for k, v in (headers or {}).items()}
        if not (lh0.get("api-key") or lh0.get("authorization")):
            return _j(401, {"error": {"code": "401", "message": "Access denied due to missing subscription key. Make sure to include "
                                                              "subscription key when making requests to an API."}})
        p0 = _body(body)
        if p0 is None:
            return _a_err(400, "BadRequest", "Invalid JSON body.")
        rm = re.match(r"^/openai/(?:v1/)?responses/([^/]+)$", path)
        if rm:
            return ag.responses_other(method.upper(), rm.group(1))
        r0 = ag.assistants_dispatch(lambda n: _find_deployment(arm_state, n), method, path, query or {}, p0)
        return r0 or _a_err(404, "404", "Resource not found")
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
    if model.startswith("ft:") and op == "chat/completions":
        r = _azure_trained_chat(model, p)
        if r is not None:
            return r
    if op == "embeddings":
        if "embeddings" not in caps and "embedding" not in model:
            return _a_err(400, "OperationNotSupported", f"The embeddings operation does not work with the specified model, {model}. "
                          "Please choose different model and try again.")
        inp = p.get("input")
        if inp in (None, "", []):
            return _a_err(400, "BadRequest", "'input' is a required property.", "input")
        e = llm.embed(inp if isinstance(inp, list) else [inp])
        native = 768 if model in CAT._BYNAME and CAT.resolve("azure", model) == CAT.DEFAULT_EMBED else (3072 if "large" in model else 1536)
        dims = int(p.get("dimensions") or native)       # the real service returns its native width unless `dimensions` shortens it
        vecs = [llm._renorm(_fit_dims(v, dims)) for v in e["vectors"]]
        return _j(200, {"object": "list", "model": model, "usage": {"prompt_tokens": e["input_tokens"], "total_tokens": e["input_tokens"]},
                        "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)]})
    if op == "responses":
        if "embedding" in model or CAT.resolve("azure", model) == CAT.DEFAULT_EMBED:
            return _a_err(400, "OperationNotSupported", f"The responses operation does not work with the specified model, {model}.")
        try:
            return ag.responses_create(None, p, model)
        except ag.Bad as e:
            return ag._err(e)
    if "embedding" in model or CAT.resolve("azure", model) == CAT.DEFAULT_EMBED or (caps and "chatCompletion" not in caps):
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
    blocked_in = _az_block_input(acct, dep, req)      # a user-managed content filter on the deployment (Foundry > Guardrails + controls)
    if blocked_in is not None:
        return blocked_in
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
    cf = _az_block_output(acct, dep, r.get("text") or "")
    if cf:      # output filtered: empty content, finish_reason content_filter (what Azure returns)
        ch = {"index": 0, "finish_reason": "content_filter", "content_filter_results": cf}
        ch.update({"text": ""} if op == "completions" else {"message": {"role": "assistant", "content": None}})
        return _j(200, {"id": cid, "object": "text_completion" if op == "completions" else "chat.completion", "created": now, "model": model,
                        "choices": [ch], "usage": usage}, hh)
    if op == "completions":
        return _j(200, {"id": cid, "object": "text_completion", "created": now, "model": model,
                        "choices": [{"text": r["text"], "index": 0, "finish_reason": fin, "logprobs": None}], "usage": usage}, hh)
    return _j(200, {"id": cid, "object": "chat.completion", "created": now, "model": model,
                    "choices": [{"index": 0, "finish_reason": _az_fin(r), "message": _az_msg(r)}],
                    "usage": usage, "system_fingerprint": "fp_vyomi_local",
                    **({"vyomiImported": True, "vyomiTrained": True} if _imported().is_import_id(model) else {})}, hh)
