"""Vyomi agent spec runtime (Dev Simplified): a JSON-declared agent executed in-process over the shared llm_core seam.

Both agent-hosting lanes use it, so one spec runs on either cloud's wire:
  * Vertex AI Agent Engine  (aiplatform v1 reasoningEngines :query / :streamQuery)  -> core/gcp_agentengine_core
  * Bedrock AgentCore Runtime (bedrock-agentcore InvokeAgentRuntime)                -> core/bedrock_agents_core

Substrate-independent, Pyodide-loadable, no fastapi/boto3. The real services run a user container / pickled Python class; the
simulator does NOT. Instead the "agent" is data:

  {"instructions": "You are a weather bot.",          # system prompt
   "model": "gemini-2.5-flash",                       # optional; llm_core.resolve_model maps it onto the local model
   "max_steps": 5, "max_tokens": 256, "temperature": 0.2,
   "tools": [
     {"name": "get_weather", "description": "...", "parameters": {JSON schema},
      "type": "static",   "result": {"temp_c": 21}},                       # fixed value, or "cases":[{"match":{"city":"Paris"},"result":...}]
     {"name": "greet",       "type": "template", "template": "Hello {name}!"},  # str.format over the call arguments
     {"name": "calc",        "type": "builtin",  "builtin": "calculator"},       # calculator | current_time | echo
     {"name": "lookup",      "type": "webhook",  "url": "http://host/hook", "headers": {...}},  # POST arguments as JSON (offline substrate only)
     {"name": "fn1",         "type": "function"}]}                              # in-process Python function from register_function()

``run`` is a real tool-calling loop: the model is asked with the tool schemas, every tool call it emits is executed, the result is
fed back as a tool message and the model is called again until it answers in text (or ``max_steps`` is hit). With no model
backend llm_core raises LlmUnavailable (callers map it to 503) - there is no canned answer.

Honest limits: not the Google ADK / LangChain / Strands / any framework, no container or pickled class, no memory service, tools
are the declarative kinds above (webhook needs network egress, so it is unavailable inside Nano's browser sandbox), quality is
the small local model's. On Nano's async model bridge the loop is re-run to resume after each model await, so webhook / function
tools may execute more than once there - keep them idempotent.
"""
from __future__ import annotations

import ast
import json
import operator
import re
import time
import urllib.request
from datetime import datetime, timezone

try:
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import llm_core as llm  # type: ignore

SPEC_ENV = "VYOMI_AGENT_SPEC"
HONEST_LIMIT = ("Vyomi agent spec runtime (Dev Simplified): a JSON spec of instructions + declarative tools executed in-process over "
                "the local model - not a container / pickled class / agent framework.")
_FUNCS: dict = {}
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]{0,63}$")
_KINDS = ("static", "template", "builtin", "webhook", "function")
_BUILTINS = ("calculator", "current_time", "echo")


class SpecError(ValueError):
    pass


def register_function(name: str, fn) -> None:
    """Register an in-process Python function usable by ``{"type":"function","name":name}`` tools (called with the arguments dict)."""
    _FUNCS[name] = fn


# ───────────────────────────── spec ─────────────────────────────
def parse_spec(spec) -> dict:
    if isinstance(spec, (str, bytes)):
        try:
            spec = json.loads(spec)
        except ValueError:
            raise SpecError("agent spec is not valid JSON")
    if not isinstance(spec, dict):
        raise SpecError("agent spec must be a JSON object")
    tools = spec.get("tools") or []
    if not isinstance(tools, list):
        raise SpecError("tools must be a list")
    seen = set()
    for t in tools:
        if not isinstance(t, dict) or not _NAME.match(str(t.get("name", ""))):
            raise SpecError("every tool needs a name matching [A-Za-z_][A-Za-z0-9_-]{0,63}")
        if t["name"] in seen:
            raise SpecError(f"duplicate tool name {t['name']}")
        seen.add(t["name"])
        kind = t.get("type", "static")
        if kind not in _KINDS:
            raise SpecError(f"tool {t['name']}: type must be one of {', '.join(_KINDS)}")
        if kind == "builtin" and t.get("builtin") not in _BUILTINS:
            raise SpecError(f"tool {t['name']}: builtin must be one of {', '.join(_BUILTINS)}")
        if kind == "webhook" and not str(t.get("url", "")).startswith(("http://", "https://")):
            raise SpecError(f"tool {t['name']}: webhook needs an http(s) url")
        if kind == "template" and not isinstance(t.get("template"), str):
            raise SpecError(f"tool {t['name']}: template tools need a 'template' string")
        if kind == "static" and "result" not in t and "cases" not in t:
            raise SpecError(f"tool {t['name']}: static tools need 'result' or 'cases'")
    if "instructions" in spec and not isinstance(spec["instructions"], str):
        raise SpecError("instructions must be a string")
    ms = spec.get("max_steps", 5)
    if not isinstance(ms, int) or not 1 <= ms <= 20:
        raise SpecError("max_steps must be an integer 1..20")
    return spec


def _schemas(spec):
    return [{"name": t["name"], "description": t.get("description", ""),
             "parameters": t.get("parameters") or {"type": "object", "properties": {}}} for t in spec.get("tools") or []]


# ───────────────────────────── tools ─────────────────────────────
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow,
        ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv}


def _calc(node):
    if isinstance(node, ast.Expression):
        return _calc(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        a, b = _calc(node.left), _calc(node.right)
        if isinstance(node.op, ast.Pow) and abs(b) > 64:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_calc(node.operand))
    raise ValueError("unsupported expression")


class _Fmt(dict):
    def __missing__(self, k):
        return "{" + k + "}"


def exec_tool(tool: dict, args: dict):
    """Run one declarative tool; returns (result, is_error)."""
    kind = tool.get("type", "static")
    try:
        if kind == "static":
            for c in tool.get("cases") or []:
                if all(args.get(k) == v for k, v in (c.get("match") or {}).items()):
                    return c.get("result"), False
            if "result" in tool:
                return tool["result"], False
            return {"error": "no case matched"}, True
        if kind == "template":
            return tool["template"].format_map(_Fmt(args)), False
        if kind == "builtin":
            b = tool["builtin"]
            if b == "calculator":
                return _calc(ast.parse(str(args.get("expression", "")), mode="eval")), False
            if b == "current_time":
                return datetime.now(timezone.utc).isoformat(), False
            return args, False
        if kind == "function":
            fn = _FUNCS.get(tool["name"])
            if fn is None:
                return {"error": f"no in-process function registered for {tool['name']}"}, True
            return fn(dict(args)), False
        if kind == "webhook":
            req = urllib.request.Request(tool["url"], data=json.dumps(args).encode(), method="POST",
                                         headers=dict({"content-type": "application/json"}, **(tool.get("headers") or {})))
            with urllib.request.urlopen(req, timeout=float(tool.get("timeout", 10))) as r:  # noqa: S310 - user-declared hook
                raw = r.read().decode("utf-8", "replace")
            try:
                return json.loads(raw), False
            except ValueError:
                return raw, False
    except (ValueError, ZeroDivisionError, OverflowError, SyntaxError, KeyError, TypeError) as e:
        return {"error": str(e) or e.__class__.__name__}, True
    except llm.NeedAsync:
        raise
    except Exception as e:  # webhook/function failures are tool errors the model sees, not crashes
        return {"error": f"{e.__class__.__name__}: {e}"}, True
    return {"error": "unsupported tool"}, True


def _as_text(v):
    return v if isinstance(v, str) else json.dumps(v, default=str)


# ───────────────────────────── the loop ─────────────────────────────
def run(spec, message: str, history: list | None = None) -> dict:
    """Run the agent on ``message`` (optionally after prior ``history`` [{role,content}]).
    -> {text, steps:[{type: model|tool_call|tool_result, ...}], messages(new turn, for session memory), usage, model, truncated}."""
    final = None
    for ev in run_events(spec, message, history):
        if ev["type"] == "final":
            final = ev
    return final


def run_events(spec, message: str, history: list | None = None):
    """Generator: model / tool_call / tool_result step events then one ``final`` event (same dict ``run`` returns)."""
    spec = parse_spec(spec)
    tools = _by_name(spec)
    schemas = _schemas(spec)
    turn = [{"role": "user", "content": message}]
    msgs = list(history or []) + turn
    steps, usage, model = [], {"input_tokens": 0, "output_tokens": 0}, None
    text, truncated = "", True
    for i in range(spec.get("max_steps", 5)):
        r = llm.chat(msgs, system=spec.get("instructions"), max_tokens=spec.get("max_tokens", 256),
                     temperature=spec.get("temperature", 0.7), model=spec.get("model"), tools=schemas or None)
        usage["input_tokens"] += r["input_tokens"]
        usage["output_tokens"] += r["output_tokens"]
        model = r["model"]
        ev = {"type": "model", "step": i, "text": r["text"], "tool_calls": [{"id": c["id"], "name": c["name"], "arguments": c["arguments"]} for c in r["tool_calls"]]}
        steps.append(ev)
        yield ev
        if not r["tool_calls"]:
            text, truncated = r["text"], False
            turn.append({"role": "assistant", "content": text})
            msgs.append(turn[-1])
            break
        am = {"role": "assistant", "content": r["text"], "tool_calls": r["tool_calls"]}
        turn.append(am)
        msgs.append(am)
        for c in r["tool_calls"]:
            tl = tools.get(c["name"])
            res, err = exec_tool(tl, c["arguments"]) if tl else ({"error": f"unknown tool {c['name']}"}, True)
            sev = {"type": "tool_result", "step": i, "id": c["id"], "name": c["name"], "arguments": c["arguments"], "result": res, "isError": err}
            steps.append(sev)
            yield sev
            tm = {"role": "tool", "content": _as_text(res), "tool_call_id": c["id"], "name": c["name"]}
            turn.append(tm)
            msgs.append(tm)
    if truncated:
        text = text or "(agent stopped: max_steps reached before a final answer)"
    yield {"type": "final", "text": text, "steps": steps, "messages": turn, "usage": usage, "model": model or llm.model_name(), "truncated": truncated}


def _by_name(spec):
    return {t["name"]: t for t in spec.get("tools") or []}


def now_ms():
    return int(time.time() * 1000)
