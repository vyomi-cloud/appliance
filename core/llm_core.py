"""Shared lightweight local-LLM seam (decision family 11). Substrate-independent: no fastapi/boto3 imports, Pyodide-loadable.

One tiny API that every AI surface (Bedrock InvokeModel/Converse, Vertex AI Gemini endpoints, Azure OpenAI deployments,
AI Search vectorization, Document AI enrichment, AgentCore targets, the Copilot) calls:

    chat(messages, system=None, max_tokens=256, temperature=0.7, stop=None, model=None, tools=None, tool_choice=None,
         response_format=None, top_p=None, seed=None) -> {text, tool_calls, input_tokens, output_tokens, finish_reason, backend, model}
    chat_stream(...same args) -> events {text | tool_start | tool_args | done}   (real upstream streaming on HTTP backends)
    embed(texts) -> {vectors, dimensions, input_tokens, backend, model}
    status() -> {available, backend, model, endpoint, honest_limit}

Backends (first that is configured wins):
  1. a Python callable registered with ``set_backend(fn)``  (tests; Nano's WebLLM bridge when the page provides one),
  2. an OpenAI-compatible HTTP endpoint (``VYOMI_LLM_ENDPOINT``, default offline ``http://vyomi-llm:8080``): llama.cpp
     ``llama-server`` (SmolLM2-360M-Instruct GGUF, ~270 MB) or Ollama's ``/v1`` shim - both speak ``/v1/chat/completions``
     and ``/v1/embeddings``. Reached with urllib (offline substrate only).
No backend -> ``LlmUnavailable`` (callers translate it to the cloud's own ServiceUnavailable/ModelNotReady error). There is
NO canned/echo fallback: a model that is not running never pretends to answer. ``embed`` has one declared exception: when the
backend has no embedding model it returns a deterministic feature-hash embedding (stable, normalised, cosine-comparable,
labelled backend ``vyomi-hash-embed``) so vector search / vectorization keep working without the LLM container.

Honest limit: a <1 GB model is a toy next to the production models these services name; answers are for exercising code
paths (prompting, tool loops, streaming, token accounting), not for quality.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid

DEFAULT_ENDPOINT = "http://vyomi-llm:8080"
DEFAULT_MODEL = "smollm2-360m-instruct"
HASH_DIM = 256
HONEST_LIMIT = ("Answers come from a small (<1 GB) local model - llama.cpp on the offline appliance, WebLLM on Nano when the "
                "browser provides it - so quality is toy-grade; use it to exercise prompts, tool loops, streaming and token accounting.")


class LlmUnavailable(Exception):
    """No local model is reachable (container not started / WebLLM not loaded)."""


_state = {"fn": None, "embed_fn": None, "endpoint": None, "model": None, "afn": None, "acache": {}, "in_arun": False,
          "stream_fn": None, "no_rf": False, "no_native": False}


class NeedAsync(BaseException):
    """Raised by chat() on a substrate whose only backend is async (Nano's WebLLM bridge): the async front door
    (``arun``) awaits the engine, caches the answer and replays the request. BaseException so no ``except Exception``
    in a core can swallow it."""

    def __init__(self, key, args):
        super().__init__(key)
        self.key, self.args_ = key, args


def set_async_backend(afn=None, model: str | None = None) -> None:
    """Register an awaitable backend ``afn(messages, system, max_tokens, temperature, stop) -> dict|str`` (Nano: WebLLM in
    the page). Used only through ``arun`` (the async router path); the synchronous router path reports it unavailable."""
    _state["afn"], _state["acache"] = afn, {}
    if model:
        _state["model"] = model


async def arun(handler, max_rounds: int = 16):
    """Run the synchronous ``handler()`` (a whole wire request); every chat() it makes is answered by the async backend
    (awaited here, cached, request replayed) so cores stay synchronous. A request that makes several model calls (tool
    retries) replays once per call. Without an async backend this is just handler()."""
    if not _state["afn"]:
        return handler()
    _state["acache"] = {}
    try:
        for _ in range(max_rounds):
            try:
                _state["in_arun"] = True
                return handler()
            except NeedAsync as n:
                msgs, system, max_tokens, temperature, stop = n.args_
                try:
                    r = await _state["afn"](msgs, system, max_tokens, temperature, stop)
                except Exception as e:
                    _state["acache"][n.key] = e
                else:
                    _state["acache"][n.key] = r if isinstance(r, dict) else {"text": str(r)}
            finally:
                _state["in_arun"] = False
        return handler()
    finally:
        _state["acache"] = {}


def _akey(args) -> str:
    return hashlib.md5(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()


def set_backend(fn=None, embed_fn=None, model: str | None = None, endpoint: str | None = None, stream_fn=None) -> None:
    """Register a Python backend. ``fn(messages, system, max_tokens, temperature, stop[, **extras]) -> str | dict`` (dict may carry
    input_tokens/output_tokens/finish_reason/tool_calls). A fn that declares ``tools`` (or **kwargs) receives tools/tool_choice/
    response_format/model/top_p/seed and is used for native tool calling; otherwise tools are prompt-translated.
    ``stream_fn(messages, system, max_tokens, temperature, stop)`` -> iterator of text pieces (incremental streaming).
    ``embed_fn(texts) -> list[list[float]]``. Pass nothing to clear."""
    _state.update(fn=fn, embed_fn=embed_fn, model=model, endpoint=endpoint, stream_fn=stream_fn, no_rf=False, no_native=False)


def _endpoint() -> str | None:
    if _state["endpoint"]:
        return _state["endpoint"]
    ep = os.environ.get("VYOMI_LLM_ENDPOINT") if hasattr(os, "environ") else None
    if ep:
        return ep.rstrip("/")
    if os.environ.get("VYOMI_LLM_DISABLE") == "1":
        return None
    try:
        import js  # noqa: F401  (Pyodide / Nano: no urllib network path - needs a registered backend)
        return None
    except ImportError:
        return DEFAULT_ENDPOINT


def model_name() -> str:
    return _state["model"] or os.environ.get("VYOMI_LLM_MODEL") or DEFAULT_MODEL


def _http(path: str, payload: dict | None, timeout: float = 120.0):
    import urllib.error
    import urllib.request
    ep = _endpoint()
    if not ep:
        raise LlmUnavailable("No local LLM backend is available on this substrate.")
    req = urllib.request.Request(ep + path, data=None if payload is None else json.dumps(payload).encode(),
                                 headers={"content-type": "application/json"}, method="GET" if payload is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            eb = e.read().decode("utf-8", "replace")[:2000]
        except Exception:
            eb = ""
        raise LlmHttpError(f"Local LLM endpoint {ep} answered HTTP {e.code}: {eb[:300]}", e.code, eb) from e
    except Exception as e:  # URLError, timeout, refused, bad JSON
        raise LlmUnavailable(f"Local LLM endpoint {ep} is not reachable ({type(e).__name__}). Start it from the appliance "
                             f"(core/llm_runtime: `vyomi llm start`) or set VYOMI_LLM_ENDPOINT.") from e


def _http_open(path: str, payload: dict, timeout: float = 120.0):
    """POST and return the open response (iterate it for SSE lines); the caller closes it."""
    import urllib.error
    import urllib.request
    ep = _endpoint()
    if not ep:
        raise LlmUnavailable("No local LLM backend is available on this substrate.")
    req = urllib.request.Request(ep + path, data=json.dumps(payload).encode(), headers={"content-type": "application/json"}, method="POST")
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            eb = e.read().decode("utf-8", "replace")[:2000]
        except Exception:
            eb = ""
        raise LlmHttpError(f"Local LLM endpoint {ep} answered HTTP {e.code}: {eb[:300]}", e.code, eb) from e
    except Exception as e:
        raise LlmUnavailable(f"Local LLM endpoint {ep} is not reachable ({type(e).__name__}). Start it from the appliance "
                             f"(core/llm_runtime: `vyomi llm start`) or set VYOMI_LLM_ENDPOINT.") from e


def estimate_tokens(text: str) -> int:
    """~4 chars/token fallback when the backend reports no usage (same heuristic Bedrock's own console uses)."""
    return max(1, math.ceil(len(text or "") / 4)) if text else 0


def status(probe: bool = True) -> dict:
    st = {"available": False, "backend": None, "model": model_name(), "endpoint": None, "honest_limit": HONEST_LIMIT}
    if _state["fn"]:
        st.update(available=True, backend="registered", endpoint="in-process")
        return st
    if _state["afn"]:
        st.update(available=True, backend="webllm", endpoint="in-page")
        return st
    ep = _endpoint()
    st["endpoint"] = ep
    if ep:
        st["backend"] = "openai-compatible"
        if probe:
            try:
                _http("/v1/models", None, timeout=2.0)
                st["available"] = True
            except LlmUnavailable:
                pass
    return st


# ───────────────────────── seam v2: tools, streaming, structured output, per-request model ─────────────────────────
#
# Neutral shapes every cloud adapter translates to/from (OpenAI-ish, but cloud-agnostic):
#   messages: {"role": user|assistant|system|tool, "content": str,
#              "tool_calls": [{"id","name","arguments": dict}]   (assistant turns that called tools),
#              "tool_call_id", "name"                            (role "tool": the result of that call)}
#   tools:    [{"name", "description", "parameters": <JSON schema>}]
#   tool_choice: None | "auto" | "none" | "required" | {"name": <tool>}
#   response_format: None | {"type": "json_object"} | {"type": "json_schema", "schema": {...}, "name": "..."}
# chat() returns the v1 dict plus ``tool_calls`` ([{id,name,arguments(dict)}]); finish_reason is "tool_calls" when it called.
#
# Tools: a backend that speaks tools natively (an OpenAI-compatible server, or a registered fn that accepts ``tools``) is
# used natively; small models that don't (or that return a malformed call) are driven by prompt translation: the tool
# schemas go into the system prompt, the model must answer with a JSON envelope, decoding is grammar-constrained
# (``response_format`` json_schema, which llama.cpp/Ollama compile to a grammar) where the server supports it, and the
# reply is parsed robustly, validated against the tool's own schema and retried with a corrective turn otherwise.
# Structured output is the same machinery: honoured (constrained when possible, always validated) or a clear
# ``LlmStructuredError`` - never silently ignored.

class LlmHttpError(LlmUnavailable):
    """The endpoint answered with an HTTP error (status/body kept so the seam can fall back, e.g. no tool support)."""

    def __init__(self, msg, status=0, body=""):
        super().__init__(msg)
        self.status, self.body = status, body


class LlmStructuredError(Exception):
    """The model could not produce a valid tool call / JSON document after retries (callers map to the cloud's model error)."""


MAX_RETRIES = 2


def resolve_model(requested: str | None = None) -> str:
    """Cloud model id -> local model name. ``VYOMI_LLM_MODEL_MAP`` (JSON {cloud id or prefix*: local}) selects per request;
    otherwise the configured model answers (documented honest limit)."""
    raw = os.environ.get("VYOMI_LLM_MODEL_MAP") if hasattr(os, "environ") else None
    if raw and requested:
        try:
            mp = json.loads(raw)
        except ValueError:
            mp = {}
        if requested in mp:
            return mp[requested]
        for k, v in mp.items():
            if k.endswith("*") and requested.startswith(k[:-1]):
                return v
    return model_name()


def _norm_calls(calls):
    out = []
    for c in calls or []:
        a = c.get("arguments", c.get("input", c.get("args", {})))
        if isinstance(a, str):
            a, ok = extract_json(a)
            a = a if ok and isinstance(a, dict) else {}
        out.append({"id": c.get("id") or "call_" + uuid.uuid4().hex[:24], "name": c.get("name", ""), "arguments": a or {}})
    return out


def _norm_messages(messages, system):
    out = []
    if system:
        out.append({"role": "system", "content": str(system)})
    for m in messages or []:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
        nm = {"role": "assistant" if role in ("assistant", "model") else ("system" if role == "system" else ("tool" if role == "tool" else "user")),
              "content": "" if content is None else str(content)}
        if m.get("tool_calls"):
            nm["tool_calls"] = _norm_calls(m["tool_calls"])
        if nm["role"] == "tool":
            nm["tool_call_id"], nm["name"] = m.get("tool_call_id", ""), m.get("name", "")
        out.append(nm)
    return out


def _norm_tools(tools):
    out = []
    for t in tools or []:
        if "function" in t:
            t = t["function"]
        if not t.get("name"):
            raise ValueError("every tool needs a name")
        out.append({"name": t["name"], "description": t.get("description", ""),
                    "parameters": t.get("parameters") or t.get("input_schema") or {"type": "object", "properties": {}}})
    return out


def _norm_choice(tool_choice, tools):
    if not tools or tool_choice in (None, "auto"):
        return "auto" if tools else "none"
    if tool_choice in ("none", "required"):
        return tool_choice
    name = tool_choice.get("name") if isinstance(tool_choice, dict) else None
    if name not in [t["name"] for t in tools]:
        raise ValueError(f"tool_choice names an unknown tool: {name!r}")
    return {"name": name}


# ── JSON helpers: robust extraction + a small JSON-Schema validator (no jsonschema dependency; Pyodide-safe)
def extract_json(text):
    """Best-effort JSON from model output: plain, ```fenced```, prose-wrapped, trailing commas, truncated closers.
    -> (value, ok)."""
    t = (text or "").strip()
    cands = [t]
    m = re.search(r"```(?:json|JSON)?\s*(.*?)```", t, re.S)
    if m:
        cands.insert(0, m.group(1).strip())
    dec = json.JSONDecoder()
    for c in cands:
        try:
            return json.loads(c), True
        except ValueError:
            pass
        for st in [i for i, ch in enumerate(c) if ch in "{["][:8]:
            try:
                return dec.raw_decode(c[st:])[0], True
            except ValueError:
                pass
            frag = re.sub(r",\s*([}\]])", r"\1", c[st:])
            try:
                return dec.raw_decode(frag)[0], True
            except ValueError:
                pass
            stack, instr, esc = [], False, False       # truncated output: close what is open
            for ch in c[st:]:
                if instr:
                    esc = (ch == "\\" and not esc)
                    if ch == '"' and not esc:
                        instr = False
                    continue
                if ch == '"':
                    instr = True
                elif ch in "{[":
                    stack.append("}" if ch == "{" else "]")
                elif ch in "}]" and stack:
                    stack.pop()
            if stack:
                try:
                    return json.loads(re.sub(r",\s*$", "", c[st:].rstrip()) + ('"' if instr else "") + "".join(reversed(stack))), True
                except ValueError:
                    pass
    return None, False


_JT = {"string": str, "boolean": bool, "array": (list, tuple), "object": dict, "null": type(None)}


def validate(schema, value, path="$") -> list:
    """Errors (empty = valid) for the JSON-Schema subset tool/response schemas use: type, enum, const, properties, required,
    additionalProperties=false, items, min/max items/length/imum, pattern, anyOf/oneOf/allOf. Unknown keywords pass."""
    errs = []
    if not isinstance(schema, dict):
        return errs
    t = schema.get("type")
    if isinstance(t, str):
        t = [t.lower()]
    elif isinstance(t, list):
        t = [x.lower() for x in t]
    if t:
        def ok_type(x):
            for ty in t:
                if ty == "integer" and isinstance(x, int) and not isinstance(x, bool):
                    return True
                if ty == "number" and isinstance(x, (int, float)) and not isinstance(x, bool):
                    return True
                if ty in _JT and isinstance(x, _JT[ty]) and not (ty != "boolean" and isinstance(x, bool) and ty in ("string", "array", "object")):
                    return True
            return False
        if not ok_type(value):
            return [f"{path}: expected {'/'.join(t)}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: must be one of {schema['enum']}")
    if isinstance(value, dict):
        for k in schema.get("required") or []:
            if k not in value:
                errs.append(f"{path}: missing required property '{k}'")
        props = schema.get("properties") or {}
        for k, v in value.items():
            if k in props:
                errs += validate(props[k], v, f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unexpected property '{k}'")
            elif isinstance(schema.get("additionalProperties"), dict):
                errs += validate(schema["additionalProperties"], v, f"{path}.{k}")
    if isinstance(value, (list, tuple)):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: allows at most {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for i, v in enumerate(value):
                errs += validate(schema["items"], v, f"{path}[{i}]")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: longer than {schema['maxLength']}")
        if schema.get("pattern") and not re.search(schema["pattern"], value):
            errs.append(f"{path}: does not match pattern {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: above maximum {schema['maximum']}")
    for kw in ("anyOf", "oneOf"):
        if schema.get(kw):
            if not any(not validate(s, value, path) for s in schema[kw]):
                errs.append(f"{path}: matches none of the {kw} alternatives")
    for s in schema.get("allOf") or []:
        errs += validate(s, value, path)
    return errs


# ── prompt translation (tools -> small-model JSON envelope) ──
def _envelope_schema(tools, choice):
    branches = [{"type": "object", "properties": {"name": {"const": t["name"]}, "arguments": t["parameters"]},
                 "required": ["name", "arguments"]} for t in tools if choice in ("auto", "required") or t["name"] == choice.get("name")]
    call = {"type": "object", "properties": {"tool_calls": {"type": "array", "minItems": 1,
            "items": branches[0] if len(branches) == 1 else {"anyOf": branches}}}, "required": ["tool_calls"]}
    if choice != "auto":
        return call
    return {"anyOf": [call, {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}]}


def _tool_prompt(tools, choice):
    lines = ["You can call tools. Available tools:"]
    for t in tools:
        lines.append(f"- {t['name']}: {t['description']}\n  parameters (JSON schema): {json.dumps(t['parameters'], separators=(',', ':'))}")
    lines.append("Reply with ONLY one JSON object and no other text.")
    if choice == "auto":
        lines.append('To call tool(s): {"tool_calls":[{"name":"<tool name>","arguments":{...}}]}\n'
                     'To answer without a tool: {"content":"<your answer>"}')
    else:
        pick = f" You MUST call the tool '{choice['name']}'." if isinstance(choice, dict) else " You MUST call at least one tool."
        lines.append('Format: {"tool_calls":[{"name":"<tool name>","arguments":{...}}]}.' + pick)
    lines.append("Use the tool results already in the conversation instead of calling a tool again for the same thing.")
    return "\n".join(lines)


def _flatten_for_prompt(msgs, tools, choice):
    """Neutral messages -> plain system/user/assistant turns (roles alternate; tool turns become JSON/user text)."""
    out, sysparts = [], []
    for m in msgs:
        if m["role"] == "system":
            sysparts.append(m["content"])
            continue
        if m["role"] == "assistant" and m.get("tool_calls"):
            body = json.dumps({"tool_calls": [{"name": c["name"], "arguments": c["arguments"]} for c in m["tool_calls"]]})
            m = {"role": "assistant", "content": (m["content"] + "\n" if m["content"] else "") + body}
        elif m["role"] == "tool":
            m = {"role": "user", "content": f"Tool result for {m.get('name') or m.get('tool_call_id') or 'tool'}: {m['content']}"}
        if out and out[-1]["role"] == m["role"]:
            out[-1] = {"role": m["role"], "content": out[-1]["content"] + "\n" + m["content"]}
        else:
            out.append({"role": m["role"], "content": m["content"]})
    if tools:
        sysparts.append(_tool_prompt(tools, choice))
    return ([{"role": "system", "content": "\n\n".join(sysparts)}] if sysparts else []) + out


def _calls_from_value(v, tools):
    """Parsed JSON -> ([calls], text|None, error|None) for the envelope or the usual near-misses small models emit."""
    names = {t["name"]: t for t in tools}
    if isinstance(v, dict) and isinstance(v.get("content"), str) and "tool_calls" not in v and "name" not in v:
        return [], v["content"], None
    raw = None
    if isinstance(v, dict):
        raw = v.get("tool_calls") or v.get("tool_call") or v.get("function_call") or ([v] if ("name" in v or "function" in v) else None)
    elif isinstance(v, list):
        raw = v
    if raw is None:
        return [], None, "reply is neither a tool call nor a content object"
    if isinstance(raw, dict):
        raw = [raw]
    calls = []
    for c in raw:
        if not isinstance(c, dict):
            return [], None, "tool call is not an object"
        c = c.get("function") if isinstance(c.get("function"), dict) else c
        name = c.get("name")
        if name not in names:
            return [], None, f"unknown tool {name!r}; use one of {sorted(names)}"
        args = c.get("arguments", c.get("parameters", c.get("input", {})))
        if isinstance(args, str):
            args, ok = extract_json(args)
            if not ok:
                return [], None, f"arguments of {name} are not valid JSON"
        errs = validate(names[name]["parameters"], args if args is not None else {})
        if errs:
            return [], None, f"arguments of {name} are invalid: " + "; ".join(errs[:3])
        calls.append({"id": c.get("id") or "call_" + uuid.uuid4().hex[:24], "name": name, "arguments": args or {}})
    return calls, None, None


# ── raw generation over the configured backend ──
def _fn_extras(fn, o):
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return {}
    allp = any(p.kind == p.VAR_KEYWORD for p in params.values())
    cand = {"model": o.get("model"), "top_p": o.get("top_p"), "seed": o.get("seed"), "response_format": o.get("response_format"),
            "tools": o.get("tools"), "tool_choice": o.get("tool_choice")}
    return {k: v for k, v in cand.items() if v is not None and (allp or k in params)}


def _fn_native_tools(fn) -> bool:
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "tools" in params


def _oa_messages(msgs):
    out = []
    for m in msgs:
        if m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id", ""), "content": m["content"]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m["content"] or "", "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for c in m["tool_calls"]]})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def _oa_rf(rf):
    if rf.get("type") == "json_schema" and rf.get("schema"):
        return {"type": "json_schema", "json_schema": {"name": rf.get("name") or "response", "schema": rf["schema"], "strict": True}}
    return {"type": "json_object"}


def _http_body(msgs, o, stream, native_tools):
    body = {"model": resolve_model(o.get("model")), "messages": _oa_messages(msgs), "max_tokens": o["max_tokens"],
            "temperature": float(o["temperature"]), "stream": stream}
    if o.get("stop"):
        body["stop"] = list(o["stop"])[:4]
    if o.get("top_p") is not None:
        body["top_p"] = float(o["top_p"])
    if o.get("seed") is not None:
        body["seed"] = int(o["seed"])
    if o.get("response_format") and not _state["no_rf"]:
        body["response_format"] = _oa_rf(o["response_format"])
    if native_tools and o.get("tools"):
        body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
                         for t in o["tools"]]
        ch = o.get("tool_choice") or "auto"
        body["tool_choice"] = ch if isinstance(ch, str) else {"type": "function", "function": {"name": ch["name"]}}
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


def _oa_calls(msg):
    return _norm_calls([{"id": c.get("id"), "name": (c.get("function") or {}).get("name", ""),
                         "arguments": (c.get("function") or {}).get("arguments", {})} for c in (msg.get("tool_calls") or [])])


def _generate(msgs, o, native_tools=False) -> dict:
    """One model call. ``msgs``: neutral messages (native_tools) or plain turns. Returns the chat() dict (tool_calls only when native)."""
    prompt_text = "\n".join(m["content"] for m in msgs)
    fin = lambda f: "length" if f == "length" else ("tool_calls" if f in ("tool_calls", "tool_use", "function_call") else "stop")
    if _state["fn"]:
        fn = _state["fn"]
        sysm = next((m["content"] for m in msgs if m["role"] == "system"), None)
        ex = _fn_extras(fn, dict(o, tools=o.get("tools") if native_tools else None))
        r = fn(msgs, sysm, o["max_tokens"], o["temperature"], o.get("stop"), **ex)
        info = r if isinstance(r, dict) else {"text": str(r)}
        text = info.get("text", "")
        calls = _norm_calls(info.get("tool_calls"))
        return {"text": text, "tool_calls": calls, "input_tokens": info.get("input_tokens") or estimate_tokens(prompt_text),
                "output_tokens": info.get("output_tokens") or estimate_tokens(text + json.dumps(calls) if calls else text),
                "finish_reason": "tool_calls" if calls else fin(info.get("finish_reason")), "backend": "registered", "model": info.get("model") or model_name()}
    if _state["afn"]:
        args = (msgs, None, o["max_tokens"], o["temperature"], list(o["stop"]) if o.get("stop") else None)
        key = _akey(args)
        hit = _state["acache"].get(key)
        if hit is None:
            if not _state["in_arun"]:
                raise LlmUnavailable("The in-browser model is only reachable through the async request path.")
            raise NeedAsync(key, args)
        if isinstance(hit, Exception):
            raise LlmUnavailable(f"In-browser model failed ({type(hit).__name__}: {hit}).") from hit
        text = hit.get("text", "")
        return {"text": text, "tool_calls": [], "input_tokens": hit.get("input_tokens") or estimate_tokens(prompt_text),
                "output_tokens": hit.get("output_tokens") or estimate_tokens(text),
                "finish_reason": fin(hit.get("finish_reason")), "backend": "webllm", "model": model_name()}
    body = _http_body(msgs, o, False, native_tools)
    try:
        r = _http("/v1/chat/completions", body)
    except LlmHttpError as e:
        if "response_format" in body and e.status in (400, 422, 500, 501):   # server can't constrain: remember, validate instead
            _state["no_rf"] = True
            body.pop("response_format")
            r = _http("/v1/chat/completions", body)
        else:
            raise
    try:
        ch = r["choices"][0]
        message = ch.get("message") or {}
        text = message.get("content") or ""
    except (KeyError, IndexError, TypeError) as e:
        raise LlmUnavailable("Local LLM endpoint returned an unexpected response.") from e
    calls = _oa_calls(message)
    u = r.get("usage") or {}
    return {"text": text, "tool_calls": calls, "input_tokens": u.get("prompt_tokens") or estimate_tokens(prompt_text),
            "output_tokens": u.get("completion_tokens") or estimate_tokens(text),
            "finish_reason": "tool_calls" if calls else fin(ch.get("finish_reason")), "backend": "llama.cpp", "model": r.get("model") or model_name()}


def _add(a, b):
    return dict(b, input_tokens=a["input_tokens"] + b["input_tokens"], output_tokens=a["output_tokens"] + b["output_tokens"])


def _zero():
    return {"input_tokens": 0, "output_tokens": 0}


def _rf_instruction(rf):
    if rf.get("type") == "json_schema" and rf.get("schema"):
        return "Respond with ONLY a JSON document valid for this JSON schema, no prose, no code fences: " + json.dumps(rf["schema"], separators=(",", ":"))
    return "Respond with ONLY a valid JSON object, no prose, no code fences."


def _structured(msgs, o) -> dict:
    """response_format honoured: constrained where the server can, always validated, retried, else LlmStructuredError."""
    rf = o["response_format"]
    plain = _flatten_for_prompt(msgs, None, "none")
    if plain and plain[0]["role"] == "system":
        plain[0] = {"role": "system", "content": plain[0]["content"] + "\n\n" + _rf_instruction(rf)}
    else:
        plain.insert(0, {"role": "system", "content": _rf_instruction(rf)})
    acc, last_err, r = _zero(), "", None
    for attempt in range(MAX_RETRIES + 1):
        r = _generate(plain, o)
        acc = {"input_tokens": acc["input_tokens"] + r["input_tokens"], "output_tokens": acc["output_tokens"] + r["output_tokens"]}
        v, ok = extract_json(r["text"])
        errs = [] if not ok else (validate(rf["schema"], v) if rf.get("type") == "json_schema" and rf.get("schema") else ([] if isinstance(v, dict) else ["$: expected a JSON object"]))
        if ok and not errs and r["finish_reason"] != "length":
            return dict(r, text=json.dumps(v, separators=(",", ":")), tool_calls=[], **acc)
        last_err = "not valid JSON" if not ok else "; ".join(errs[:3])
        if r["finish_reason"] == "length":
            last_err = "output was cut off by max_tokens"
        plain = plain + [{"role": "assistant", "content": r["text"]}, {"role": "user", "content": f"That reply was rejected: {last_err}. " + _rf_instruction(rf)}]
    raise LlmStructuredError(f"The model did not produce valid structured output after {MAX_RETRIES + 1} attempts ({last_err}).")


def _tool_mode() -> str:
    m = (os.environ.get("VYOMI_LLM_TOOL_MODE") or "auto").lower() if hasattr(os, "environ") else "auto"
    return m if m in ("native", "prompt", "auto") else "auto"


def _backend_native_tools() -> bool:
    if _state["fn"]:
        return _fn_native_tools(_state["fn"])
    if _state["afn"]:
        return False
    return _tool_mode() != "prompt" and not _state["no_native"]


def _tools_prompted(msgs, o) -> dict:
    tools, choice = o["tools"], o["tool_choice"]
    flat = _flatten_for_prompt(msgs, tools, choice)
    oo = dict(o, response_format={"type": "json_schema", "schema": _envelope_schema(tools, choice), "name": "tool_envelope"})
    acc, err, r = _zero(), "", None
    for attempt in range(MAX_RETRIES + 1):
        r = _generate(flat, oo)
        acc = {"input_tokens": acc["input_tokens"] + r["input_tokens"], "output_tokens": acc["output_tokens"] + r["output_tokens"]}
        v, ok = extract_json(r["text"])
        if ok:
            calls, text, err = _calls_from_value(v, tools)
            if not err:
                return dict(r, text=text or "", tool_calls=calls, finish_reason="tool_calls" if calls else r["finish_reason"], **acc)
        else:
            err = "reply is not valid JSON"
            if choice == "auto" and r["text"].strip() and attempt == MAX_RETRIES:
                return dict(r, tool_calls=[], **acc)    # prose answer from a model that ignored the envelope: honest plain text
        flat = flat + [{"role": "assistant", "content": r["text"]}, {"role": "user", "content": f"That reply was rejected: {err}. Reply again with ONLY the JSON object."}]
    raise LlmStructuredError(f"The model did not produce a valid tool call after {MAX_RETRIES + 1} attempts ({err}).")


def _tools_native(msgs, o) -> dict:
    """Backend tools first; a refusal, malformed/unknown call, or a forced call that never came falls back to prompt translation."""
    tools, choice = o["tools"], o["tool_choice"]
    try:
        r = _generate(msgs, o, native_tools=True)
    except LlmHttpError as e:
        if e.status in (400, 404, 422, 500, 501) and "tool" in (e.body or str(e)).lower():
            _state["no_native"] = True               # e.g. Ollama: "<model> does not support tools"
            return _tools_prompted(msgs, o)
        raise
    if r["tool_calls"]:
        names = {t["name"]: t for t in tools}
        bad = [c for c in r["tool_calls"] if c["name"] not in names or validate(names[c["name"]]["parameters"], c["arguments"])]
        if not bad:
            return dict(r, finish_reason="tool_calls")
        return _add(r, _tools_prompted(msgs, o))
    if choice != "auto":
        return _add(r, _tools_prompted(msgs, o))
    v, ok = extract_json(r["text"])                  # small models often print the call as text
    if ok and isinstance(v, (dict, list)) and not (isinstance(v, dict) and "content" in v and "name" not in v):
        calls, _, err = _calls_from_value(v, tools)
        if calls and not err:
            return dict(r, text="", tool_calls=calls, finish_reason="tool_calls")
    return r


def chat(messages, system=None, max_tokens=256, temperature=0.7, stop=None, model=None, tools=None, tool_choice=None,
         response_format=None, top_p=None, seed=None) -> dict:
    msgs = _norm_messages(messages, system)
    if not any(m["role"] == "user" for m in msgs):
        raise ValueError("at least one user message is required")
    tools = _norm_tools(tools)
    choice = _norm_choice(tool_choice, tools)
    if choice == "none":
        tools = []
    o = {"max_tokens": max(1, int(max_tokens or 256)), "temperature": temperature, "stop": list(stop) if stop else None, "model": model,
         "top_p": top_p, "seed": seed, "tools": tools or None, "tool_choice": choice if tools else None,
         "response_format": response_format or None}
    if tools:
        r = _tools_native(msgs, o) if _backend_native_tools() else _tools_prompted(msgs, o)
        if response_format and not r["tool_calls"]:
            r = _add(r, _structured(msgs, dict(o, tools=None, tool_choice=None)))
        return r
    if response_format:
        return _structured(msgs, o)
    r = _generate(_flatten_for_prompt(msgs, None, "none") if any(m["role"] == "tool" or m.get("tool_calls") for m in msgs) else msgs, o)
    return r


def _http_stream(msgs, o, native_tools):
    """Yield events straight off the backend's SSE stream (llama.cpp / Ollama ``stream: true``)."""
    body = _http_body(msgs, o, True, native_tools)
    resp = _http_open("/v1/chat/completions", body)
    prompt_text = "\n".join(m["content"] for m in msgs)
    text, calls, usage, finish, mdl = [], {}, {}, None, None
    try:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                ev = json.loads(data)
            except ValueError:
                continue
            mdl = ev.get("model") or mdl
            if ev.get("usage"):
                usage = ev["usage"]
            for ch in ev.get("choices") or []:
                d = ch.get("delta") or {}
                if d.get("content"):
                    text.append(d["content"])
                    yield {"type": "text", "text": d["content"]}
                for tc in d.get("tool_calls") or []:
                    i = tc.get("index", len(calls))
                    f = tc.get("function") or {}
                    c = calls.get(i)
                    if c is None:
                        c = calls[i] = {"id": tc.get("id") or "call_" + uuid.uuid4().hex[:24], "name": f.get("name", ""), "args": ""}
                        yield {"type": "tool_start", "index": i, "id": c["id"], "name": c["name"]}
                    elif f.get("name") and not c["name"]:
                        c["name"] = f["name"]
                    frag = f.get("arguments")
                    if frag is not None and frag != "":
                        frag = frag if isinstance(frag, str) else json.dumps(frag)
                        c["args"] += frag
                        yield {"type": "tool_args", "index": i, "fragment": frag}
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
    finally:
        try:
            resp.close()
        except Exception:
            pass
    final_calls = _norm_calls([{"id": c["id"], "name": c["name"], "arguments": c["args"] or "{}"} for _, c in sorted(calls.items())])
    full = "".join(text)
    yield {"type": "done", "text": full, "tool_calls": final_calls,
           "finish_reason": "tool_calls" if final_calls else ("length" if finish == "length" else "stop"),
           "input_tokens": usage.get("prompt_tokens") or estimate_tokens(prompt_text),
           "output_tokens": usage.get("completion_tokens") or estimate_tokens(full), "backend": "llama.cpp", "model": mdl or model_name()}


def _replay(r):
    """Events for an already-complete result (buffered paths: prompt-translated tools, structured output, non-streaming backends)."""
    if r["text"]:
        for i in range(0, len(r["text"]), 12):
            yield {"type": "text", "text": r["text"][i:i + 12]}
    for i, c in enumerate(r.get("tool_calls") or []):
        yield {"type": "tool_start", "index": i, "id": c["id"], "name": c["name"]}
        js = json.dumps(c["arguments"], separators=(",", ":"))
        for k in range(0, len(js), 16):
            yield {"type": "tool_args", "index": i, "fragment": js[k:k + 16]}
    yield dict(r, type="done")


def chat_stream(messages, system=None, max_tokens=256, temperature=0.7, stop=None, model=None, tools=None, tool_choice=None,
                response_format=None, top_p=None, seed=None):
    """Generator of events {type: text|tool_start|tool_args|done}. Plain chat (and native tool calls on a server that has them)
    stream token-by-token from the backend as it generates; backends/paths that cannot (prompt-translated tools and
    structured output - both must be validated whole - or a non-streaming registered/WebLLM backend) emit the finished answer
    as events. Errors surface on the first ``next()``."""
    msgs = _norm_messages(messages, system)
    if not any(m["role"] == "user" for m in msgs):
        raise ValueError("at least one user message is required")
    tools = _norm_tools(tools)
    choice = _norm_choice(tool_choice, tools)
    if choice == "none":
        tools = []
    o = {"max_tokens": max(1, int(max_tokens or 256)), "temperature": temperature, "stop": list(stop) if stop else None, "model": model,
         "top_p": top_p, "seed": seed, "tools": tools or None, "tool_choice": choice if tools else None, "response_format": response_format or None}
    kw = dict(system=None, max_tokens=o["max_tokens"], temperature=temperature, stop=stop, model=model, tools=tools or None,
              tool_choice=choice if tools else None, response_format=response_format, top_p=top_p, seed=seed)
    if _state["fn"] and _state["stream_fn"] and not tools and not response_format:
        sysm = next((m["content"] for m in msgs if m["role"] == "system"), None)
        parts, ptxt = [], "\n".join(m["content"] for m in msgs)
        for piece in _state["stream_fn"](_flatten_for_prompt(msgs, None, "none"), sysm, o["max_tokens"], temperature, o["stop"]):
            if isinstance(piece, dict):
                piece = piece.get("text", "")
            parts.append(piece)
            yield {"type": "text", "text": piece}
        full = "".join(parts)
        yield {"type": "done", "text": full, "tool_calls": [], "finish_reason": "stop", "input_tokens": estimate_tokens(ptxt),
               "output_tokens": estimate_tokens(full), "backend": "registered", "model": model_name()}
        return
    http = not _state["fn"] and not _state["afn"] and _endpoint()
    if http and not response_format and (not tools or (_backend_native_tools() and choice == "auto")):
        try:
            yield from _http_stream(msgs if tools else _flatten_for_prompt(msgs, None, "none"), o, bool(tools))
            return
        except LlmHttpError as e:
            if not tools or e.status not in (400, 404, 422, 500, 501) or "tool" not in (e.body or str(e)).lower():
                raise
            _state["no_native"] = True
    yield from _replay(chat(msgs, **kw))


def hash_embed(text: str, dim: int = HASH_DIM) -> list[float]:
    """Deterministic feature-hash bag-of-words(+bigram) embedding, L2-normalised."""
    v = [0.0] * dim
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    for feat in toks + [a + "_" + b for a, b in zip(toks, toks[1:])]:
        h = int(hashlib.md5(feat.encode()).hexdigest(), 16)
        v[h % dim] += 1.0 if (h >> 64) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [round(x / n, 6) for x in v]


def embed(texts, dimensions: int | None = None) -> dict:
    texts = [texts] if isinstance(texts, str) else list(texts)
    toks = sum(estimate_tokens(t) for t in texts)
    vecs = backend = None
    try:
        if _state["embed_fn"]:
            vecs, backend = _state["embed_fn"](texts), "registered"
        elif not _state["fn"] and not _state["afn"] and _endpoint():
            r = _http("/v1/embeddings", {"model": model_name(), "input": texts}, timeout=30.0)
            vecs, backend = [d["embedding"] for d in r["data"]], "llama.cpp"
    except (LlmUnavailable, KeyError, TypeError):
        vecs = None
    if vecs is None:
        vecs, backend = [hash_embed(t) for t in texts], "vyomi-hash-embed"
    if dimensions and vecs and dimensions < len(vecs[0]):
        vecs = [_renorm(v[:dimensions]) for v in vecs]
    return {"vectors": vecs, "dimensions": len(vecs[0]) if vecs else 0, "input_tokens": toks, "backend": backend,
            "model": model_name() if backend != "vyomi-hash-embed" else "vyomi-hash-embed"}


def _renorm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b)) / ((math.sqrt(sum(x * x for x in a)) or 1) * (math.sqrt(sum(y * y for y in b)) or 1))
