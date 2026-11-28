# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Azure OpenAI Responses API + Assistants API (threads / messages / runs), Dev Simplified, over the shared llm_core seam.

Honest scope (dev-testing of agent loops with the NATIVE openai SDK, not model quality):
  Responses : create (string or item input, instructions, function tools, tool_choice, text.format json_schema/json_object,
              previous_response_id chaining, stream=true with the real event sequence), get, delete. Built-in tools
              (web_search, file_search, code_interpreter, computer_use, mcp) and reasoning items are rejected with 400.
  Assistants: assistants CRUD, threads CRUD, messages create/list/get, runs create/get/list/cancel/submit_tool_outputs and
              create-thread-and-run. Runs execute synchronously inside the create call (so the status is already terminal:
              completed | requires_action | failed), which is what create_and_poll / polling loops converge on.
              Tools: function, code_interpreter (REAL sandboxed Python via core/code_sandbox_core: stdout logs, input files from tool_resources /
              attachments, output files saved to /files with file_path annotations) and file_search (REAL retrieval: vector stores chunk each file
              with core/knowledge_core, embed with the llm_core embedder and rank by cosine; the top passages are given to the model and returned
              as file_citation annotations). Vector stores: create/list/get/delete, files, file_batches. Run steps are recorded and listed.
              Not implemented: image outputs of code interpreter (matplotlib needs a Mesh Python with it installed), expiry policies,
              chunking_strategy other than the default, file_search ranking_options, attachments file_search on Responses API (still rejected).
State is process-local (module dicts); a restart clears it.
"""
from __future__ import annotations

import json
import re
import sys
import time
import uuid

try:
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import llm_core as llm  # type: ignore

_RESP: dict[str, dict] = {}
_ASST: dict[str, dict] = {}
_THR: dict[str, dict] = {}
_VS: dict[str, dict] = {}
_MAX_CI_STEPS = 5


def _po_origin():
    from core import public_origin as _po
    return _po.origin()


def _am():
    try:
        from core import ai_models_core as m
    except ImportError:  # pragma: no cover
        import ai_models_core as m  # type: ignore
    return m


def _id(prefix, n=24):
    return prefix + uuid.uuid4().hex[:n]


class Bad(Exception):
    def __init__(self, msg, param=None, status=400, code="BadRequest"):
        super().__init__(msg)
        self.msg, self.param, self.status, self.code = msg, param, status, code


def _err(e):
    return _am()._a_err(e.status, e.code, e.msg, e.param)


# ───────────────────────────── shared model call ─────────────────────────────
def _call(req, model, stream=False):
    am = _am()
    req = (req[0], req[1], req[2], req[3], req[4], dict(req[5], model=model))
    try:
        if stream:
            return am._prime(llm.chat_stream(*req[:5], **req[5]))
        return am._llm_chat(req)
    except llm.LlmStructuredError as e:
        raise Bad(str(e), status=500, code="model_error")
    except llm.LlmUnavailable as e:
        raise Bad(f"{e}", status=503, code="ServiceUnavailable")
    except ValueError as e:
        raise Bad(str(e))


def _chat_req(body):
    r = _am()._az_chat_request(body)
    if len(r) == 2:
        raise Bad(r[1], r[0])
    return r


def _usage(r):
    return {"input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"], "total_tokens": r["input_tokens"] + r["output_tokens"]}


# ───────────────────────────── Responses API ─────────────────────────────
def _text_of(content, param="input"):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            t = (c or {}).get("type")
            if t in ("input_text", "output_text", "text"):
                out.append(c.get("text", ""))
            elif t == "refusal":
                out.append(c.get("refusal", ""))
            else:
                raise Bad(f"Content part type {t!r} is not supported by the local model (only input_text/output_text).", param)
        return "".join(out)
    raise Bad("Invalid content.", param)


def _to_chat(p, hist):
    """Responses body -> chat.completions-shaped body (+ history messages prepended)."""
    msgs = list(hist)
    if p.get("instructions"):
        msgs = [{"role": "system", "content": p["instructions"]}] + [m for m in msgs if m["role"] != "system"]
    inp = p.get("input")
    if isinstance(inp, str):
        msgs.append({"role": "user", "content": inp})
    elif isinstance(inp, list) and inp:
        for it in inp:
            if not isinstance(it, dict):
                raise Bad("Each input item must be an object.", "input")
            ty = it.get("type", "message")
            if ty == "message" or (ty is None and "role" in it):
                role = it.get("role")
                if role not in ("user", "system", "developer", "assistant"):
                    raise Bad("Invalid value for 'role' in input.", "input")
                msgs.append({"role": "system" if role == "developer" else role, "content": _text_of(it.get("content"))})
            elif ty == "function_call":
                if not it.get("call_id") or not it.get("name"):
                    raise Bad("function_call items need call_id and name.", "input")
                call = {"id": it["call_id"], "type": "function", "function": {"name": it["name"], "arguments": it.get("arguments") or "{}"}}
                if msgs and msgs[-1]["role"] == "assistant" and msgs[-1].get("tool_calls") is not None:
                    msgs[-1]["tool_calls"].append(call)
                else:
                    msgs.append({"role": "assistant", "content": "", "tool_calls": [call]})
            elif ty == "function_call_output":
                if not it.get("call_id"):
                    raise Bad("function_call_output items need call_id.", "input")
                out = it.get("output")
                msgs.append({"role": "tool", "tool_call_id": it["call_id"], "content": out if isinstance(out, str) else json.dumps(out)})
            elif ty == "item_reference":
                raise Bad("item_reference is not supported.", "input")
            else:
                raise Bad(f"Input item type {ty!r} is not supported by the local model.", "input")
    else:
        raise Bad("Missing required parameter: 'input'.", "input")
    body = {"messages": msgs}
    if p.get("tools"):
        body["tools"] = []
        for t in p["tools"]:
            if (t or {}).get("type") != "function" or not t.get("name"):
                raise Bad(f"Tool type {(t or {}).get('type')!r} is not supported by the local model (only function tools).", "tools")
            body["tools"].append({"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                                                    "parameters": t.get("parameters") or {"type": "object", "properties": {}}}})
        tc = p.get("tool_choice")
        if isinstance(tc, dict):
            if tc.get("type") != "function":
                raise Bad("tool_choice type not supported.", "tool_choice")
            body["tool_choice"] = {"type": "function", "function": {"name": tc.get("name")}}
        elif tc is not None:
            body["tool_choice"] = tc
    fmt = ((p.get("text") or {}).get("format") or {})
    if fmt.get("type") == "json_schema":
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": fmt.get("name"), "schema": fmt.get("schema")}}
    elif fmt.get("type") == "json_object":
        body["response_format"] = {"type": "json_object"}
    if p.get("reasoning"):
        raise Bad("reasoning is not supported by the local model.", "reasoning")
    for k in ("temperature", "top_p", "seed"):
        if p.get(k) is not None:
            body[k] = p[k]
    if p.get("max_output_tokens"):
        body["max_completion_tokens"] = p["max_output_tokens"]
    return body


def _resp_doc(rid, model, p, r, status="completed"):
    out = []
    if r["text"] or not r["tool_calls"]:
        out.append({"id": _id("msg_"), "type": "message", "status": "completed", "role": "assistant",
                    "content": [{"type": "output_text", "text": r["text"], "annotations": []}]})
    for c in r["tool_calls"]:
        out.append({"id": _id("fc_"), "type": "function_call", "status": "completed", "call_id": c["id"], "name": c["name"],
                    "arguments": json.dumps(c["arguments"])})
    incomplete = r["finish_reason"] == "length"
    return {"id": rid, "object": "response", "created_at": int(time.time()), "status": "incomplete" if incomplete else status,
            "error": None, "incomplete_details": {"reason": "max_output_tokens"} if incomplete else None,
            "instructions": p.get("instructions"), "max_output_tokens": p.get("max_output_tokens"), "model": model, "output": out,
            "parallel_tool_calls": True, "previous_response_id": p.get("previous_response_id"), "store": p.get("store", True),
            "temperature": p.get("temperature", 1.0), "tool_choice": p.get("tool_choice", "auto"), "tools": p.get("tools") or [],
            "top_p": p.get("top_p", 1.0), "text": p.get("text") or {"format": {"type": "text"}}, "truncation": "disabled",
            "usage": dict(_usage(r), input_tokens_details={"cached_tokens": 0}, output_tokens_details={"reasoning_tokens": 0}),
            "metadata": p.get("metadata") or {}, "user": p.get("user")}


def _hist_msg(r):
    m = {"role": "assistant", "content": r["text"]}
    if r["tool_calls"]:
        m["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for c in r["tool_calls"]]
    return m


def _sse(seq, typ, **kw):
    return f"event: {typ}\ndata: " + json.dumps(dict(kw, type=typ, sequence_number=next(seq))) + "\n\n"


def _resp_stream(rid, model, p, it, chat_msgs, store):
    import itertools
    seq = itertools.count()
    base = _resp_doc(rid, model, p, {"text": "", "tool_calls": [], "finish_reason": "stop", "input_tokens": 0, "output_tokens": 0})
    base.update(status="in_progress", output=[], usage=None)
    yield _sse(seq, "response.created", response=base)
    yield _sse(seq, "response.in_progress", response=base)
    msg_id, msg_open, text_idx = _id("msg_"), False, None
    calls = {}      # index -> {id, item_id, out_idx}
    nxt = 0
    items = []
    try:
        for ev in it:
            if ev["type"] == "text":
                if not msg_open:
                    msg_open, text_idx, nxt = True, nxt, nxt + 1
                    yield _sse(seq, "response.output_item.added", output_index=text_idx,
                               item={"id": msg_id, "type": "message", "status": "in_progress", "role": "assistant", "content": []})
                    yield _sse(seq, "response.content_part.added", item_id=msg_id, output_index=text_idx, content_index=0,
                               part={"type": "output_text", "text": "", "annotations": []})
                    acc = []
                acc.append(ev["text"])
                yield _sse(seq, "response.output_text.delta", item_id=msg_id, output_index=text_idx, content_index=0, delta=ev["text"])
            elif ev["type"] == "tool_start":
                calls[ev["index"]] = {"call_id": ev["id"], "name": ev["name"], "item_id": _id("fc_"), "out": nxt, "args": []}
                nxt += 1
                c = calls[ev["index"]]
                yield _sse(seq, "response.output_item.added", output_index=c["out"],
                           item={"id": c["item_id"], "type": "function_call", "status": "in_progress", "call_id": c["call_id"], "name": c["name"], "arguments": ""})
            elif ev["type"] == "tool_args":
                c = calls[ev["index"]]
                c["args"].append(ev["fragment"])
                yield _sse(seq, "response.function_call_arguments.delta", item_id=c["item_id"], output_index=c["out"], delta=ev["fragment"])
            else:
                final = ev
        if msg_open:
            txt = "".join(acc)
            part = {"type": "output_text", "text": txt, "annotations": []}
            yield _sse(seq, "response.output_text.done", item_id=msg_id, output_index=text_idx, content_index=0, text=txt)
            yield _sse(seq, "response.content_part.done", item_id=msg_id, output_index=text_idx, content_index=0, part=part)
            item = {"id": msg_id, "type": "message", "status": "completed", "role": "assistant", "content": [part]}
            yield _sse(seq, "response.output_item.done", output_index=text_idx, item=item)
            items.append((text_idx, item))
        for c in calls.values():
            args = "".join(c["args"]) or "{}"
            yield _sse(seq, "response.function_call_arguments.done", item_id=c["item_id"], output_index=c["out"], arguments=args)
            item = {"id": c["item_id"], "type": "function_call", "status": "completed", "call_id": c["call_id"], "name": c["name"], "arguments": args}
            yield _sse(seq, "response.output_item.done", output_index=c["out"], item=item)
            items.append((c["out"], item))
        doc = _resp_doc(rid, model, p, final)
        if not items:      # empty completion still yields a message item, as the non-stream path does
            items = [(0, doc["output"][0])]
        doc["output"] = [i for _, i in sorted(items, key=lambda x: x[0])]
        if store:
            _RESP[rid] = {"doc": doc, "messages": chat_msgs + [_hist_msg(final)]}
        yield _sse(seq, "response.completed" if doc["status"] == "completed" else "response.incomplete", response=doc)
    except (llm.LlmUnavailable, llm.LlmStructuredError) as e:
        yield _sse(seq, "error", code="ServiceUnavailable", message=str(e), param=None)


def responses_create(arm_find, p, model, stream_ok=True):
    am = _am()
    hist = []
    cid = (p.get("conversation") if isinstance(p.get("conversation"), str) else (p.get("conversation") or {}).get("id")) if p.get("conversation") else None
    if cid:
        if cid not in _CONV:
            raise Bad(f"Conversation with id '{cid}' not found.", "conversation", 404, "invalid_value")
        hist = [dict(m) for m in _CONV[cid]["messages"]]
    if p.get("previous_response_id"):
        prev = _RESP.get(p["previous_response_id"])
        if not prev:
            raise Bad(f"Previous response with id '{p['previous_response_id']}' not found.", "previous_response_id", 404, "invalid_value")
        hist = [dict(m) for m in prev["messages"]]
    body = _to_chat(p, hist)
    req = _chat_req(body)
    rid, store = _id("resp_", 40), p.get("store", True) is not False
    if p.get("stream"):
        it = _call(req, model, stream=True)
        return am._stream_out(200, {"x-vyomi-local-model": llm.resolve_model(model)}, _resp_stream(rid, model, p, it, body["messages"], store), "text/event-stream")
    r = _call(req, model)
    doc = _resp_doc(rid, model, p, r)
    if store:
        _RESP[rid] = {"doc": doc, "messages": body["messages"] + [_hist_msg(r)]}
    if cid:
        _conv_append(cid, p, body["messages"] + [_hist_msg(r)], doc)
        doc["conversation"] = {"id": cid}
    return am._j(200, doc, {"x-vyomi-local-model": r["model"]})


def responses_other(method, rid):
    am = _am()
    rec = _RESP.get(rid)
    if not rec:
        return am._a_err(404, "invalid_request_error", f"Response with id '{rid}' not found.")
    if method == "GET":
        return am._j(200, rec["doc"])
    if method == "DELETE":
        del _RESP[rid]
        return am._j(200, {"id": rid, "object": "response", "deleted": True})
    return am._a_err(405, "MethodNotAllowed", "Method not allowed.")


# ───────────────────────────── Foundry project surface (azure-ai-projects / azure-ai-agents) ─────────────────────────────
# `https://<acct>.services.ai.azure.com/api/projects/<project>/...` is served by the SAME state as /openai/*: the classic agents surface
# (assistants/threads/runs/files/vector_stores, azure-ai-agents AgentsClient) is the Assistants core under another prefix; the v2 surface
# (agents + versions, conversations, connections, deployments) is the thin layer below. No new backend.
_AGENTS: dict[str, dict] = {}     # name -> {"name", "versions": [AgentVersionDetails...]}
_CONV: dict[str, dict] = {}       # conversation id -> {"obj", "items", "messages"}


def _conv_view(c):
    return dict(c["obj"])


def _in_items(p):
    inp = p.get("input")
    if isinstance(inp, str):
        return [{"type": "message", "id": _id("msg_"), "status": "completed", "role": "user", "content": [{"type": "input_text", "text": inp}]}]
    out = []
    for it in inp or []:
        if isinstance(it, dict):
            it = dict(it)
            it.setdefault("type", "message")
            it.setdefault("id", _id("msg_"))
            if it["type"] == "message" and isinstance(it.get("content"), str):
                it["content"] = [{"type": "input_text" if it.get("role") != "assistant" else "output_text", "text": it["content"]}]
            out.append(it)
    return out


def _conv_append(cid, p, messages, doc):
    c = _CONV[cid]
    c["items"] += _in_items(p) + [dict(o) for o in doc.get("output", [])]
    c["messages"] = messages


def _conv_dispatch(method, path, query, p):
    am = _am()
    J = am._j
    if path == "/conversations" and method == "POST":
        cid = _id("conv_", 40)
        c = {"obj": {"id": cid, "object": "conversation", "created_at": int(time.time()), "metadata": p.get("metadata") or {}}, "items": [], "messages": []}
        for it in p.get("items") or []:
            c["items"] += _in_items({"input": [it]})
            c["messages"].append({"role": it.get("role", "user"), "content": _text_of(it.get("content"))})
        _CONV[cid] = c
        return J(200, _conv_view(c))
    m = re.match(r"^/conversations/([^/]+)(?:/items(?:/([^/]+))?)?$", path)
    if not m:
        return None
    c = _CONV.get(m.group(1))
    if not c:
        return am._a_err(404, "not_found", f"Conversation with id '{m.group(1)}' not found.")
    sub = path.split(m.group(1), 1)[1]
    if sub == "":
        if method == "GET":
            return J(200, _conv_view(c))
        if method == "POST":
            c["obj"]["metadata"] = p.get("metadata", c["obj"]["metadata"])
            return J(200, _conv_view(c))
        if method == "DELETE":
            del _CONV[c["obj"]["id"]]
            return J(200, {"id": c["obj"]["id"], "object": "conversation.deleted", "deleted": True})
    elif m.group(2) is None and sub == "/items":
        if method == "POST":
            new = []
            for it in p.get("items") or []:
                new += _in_items({"input": [it]})
                c["messages"].append({"role": it.get("role", "user"), "content": _text_of(it.get("content"))})
            c["items"] += new
            return J(200, {"object": "list", "data": new, "first_id": new[0]["id"] if new else None, "last_id": new[-1]["id"] if new else None, "has_more": False})
        if method == "GET":
            items = list(c["items"])
            if (query or {}).get("order", "desc") == "desc":
                items = items[::-1]
            lim = int((query or {}).get("limit") or 20)
            return J(200, {"object": "list", "data": items[:lim], "first_id": items[0]["id"] if items else None,
                           "last_id": items[:lim][-1]["id"] if items else None, "has_more": len(items) > lim})
    elif m.group(2):
        it = next((x for x in c["items"] if x["id"] == m.group(2)), None)
        if not it:
            return am._a_err(404, "not_found", f"Item with id '{m.group(2)}' not found.")
        if method == "GET":
            return J(200, it)
        if method == "DELETE":
            c["items"].remove(it)
            return J(200, c["obj"])
    return None


def _agent_ver(name, definition, p, n):
    return {"object": "agent.version", "id": f"{name}:{n}", "name": name, "version": str(n), "description": p.get("description"),
            "created_at": int(time.time()), "metadata": p.get("metadata") or {}, "definition": definition, "status": "active"}


def _agent_view(a):
    v = a["versions"][-1]
    return {"object": "agent", "id": a["name"], "name": a["name"], "versions": {"latest": v}}


def resolve_agent_ref(p):
    """A Responses body naming a v2 agent (`agent_reference` / `agent` -> {name, version}): fold the agent definition into the body."""
    ref = p.get("agent_reference") or p.get("agent")
    if not isinstance(ref, dict) or not ref.get("name"):
        return p
    a = _AGENTS.get(ref["name"])
    if not a:
        raise Bad(f"Agent '{ref['name']}' not found.", "agent_reference", 404, "not_found")
    v = next((x for x in a["versions"] if x["version"] == str(ref.get("version"))), None) if ref.get("version") else a["versions"][-1]
    if not v:
        raise Bad(f"Agent '{ref['name']}' version '{ref.get('version')}' not found.", "agent_reference", 404, "not_found")
    d = v["definition"]
    q = dict(p)
    q.setdefault("model", d.get("model"))
    if d.get("instructions") and not q.get("instructions"):
        q["instructions"] = d["instructions"]
    if d.get("tools") and not q.get("tools"):
        q["tools"] = [t_ for t_ in d["tools"] if isinstance(t_, dict) and t_.get("type") == "function"]
    return q


def _connections(arm_state):
    out = []
    for rid, rec in (arm_state or {}).items():
        ty = str(rec.get("_type", "")).lower()
        if ty == "microsoft.cognitiveservices/accounts" and rec.get("kind") in ("OpenAI", "AIServices"):
            nm = rec.get("name") or rid.rsplit("/", 1)[-1]
            out.append({"name": nm, "id": rid, "type": "AzureOpenAI", "target": (f"{_po_origin()}/azure-data/openai/{nm}/" if _po_origin() else f"https://{nm}.openai.azure.com/"), "isDefault": not out,
                        "credentials": {"type": "ApiKey", "key": "vyomi-local-key"}, "metadata": {}})
        elif ty == "microsoft.search/searchservices":
            nm = rec.get("name") or rid.rsplit("/", 1)[-1]
            out.append({"name": nm, "id": rid, "type": "CognitiveSearch", "target": f"https://{nm}.search.windows.net/", "isDefault": True,
                        "credentials": {"type": "ApiKey", "key": "vyomi-local-key"}, "metadata": {}})
    return out


def _deployments(arm_state):
    out = []
    for rec in (arm_state or {}).values():
        if str(rec.get("_type", "")).lower() == "microsoft.cognitiveservices/accounts" and rec.get("kind") in ("OpenAI", "AIServices"):
            for nm, d in (rec.get("_deployments") or {}).items():
                pr = d.get("properties") or {}
                mo = pr.get("model") or {}
                sku = d.get("sku") or {}
                out.append({"type": "ModelDeployment", "name": d.get("name") or nm, "modelName": mo.get("name", ""), "modelVersion": mo.get("version", ""),
                            "modelPublisher": mo.get("format", "OpenAI"), "capabilities": pr.get("capabilities") or {},
                            "sku": {"name": sku.get("name", "Standard"), "capacity": sku.get("capacity", 1), "family": "", "size": "", "tier": ""},
                            "connectionName": rec.get("name", "")})
    return out


def _plist(items):
    return {"data": items, "first_id": (items[0].get("id") or items[0].get("name")) if items else None,
            "last_id": None, "has_more": False}   # azure-ai-projects pages on last_id: null ends the listing


def project_dispatch(arm_state, method, path, query, p):
    """Project-only routes (path is relative to /api/projects/<p>): agents v2, connections, deployments, datasets, indexes, conversations."""
    am = _am()
    J = am._j
    method = method.upper()

    def nf(what, i):
        return am._a_err(404, "not_found", f"{what} '{i}' not found.")
    try:
        r = _conv_dispatch(method, re.sub(r"^/openai/v1", "", path), query, p) if re.match(r"^/openai/v1/conversations", path) else None
        if r is not None:
            return r
        if path == "/connections" and method == "GET":
            cs = _connections(arm_state)
            if (query or {}).get("connectionType"):
                cs = [c for c in cs if c["type"] == query["connectionType"]]
            if str((query or {}).get("defaultConnection", "")).lower() == "true":
                cs = [c for c in cs if c["isDefault"]]
            return J(200, {"value": [{k: v for k, v in c.items() if k != "credentials"} for c in cs]})
        m = re.match(r"^/connections/([^/]+)(/getConnectionWithCredentials)?$", path)
        if m:
            c = next((x for x in _connections(arm_state) if x["name"] == m.group(1)), None)
            if not c:
                return nf("Connection", m.group(1))
            if m.group(2) and method in ("GET", "POST"):
                return J(200, c)
            if method == "GET":
                return J(200, {k: v for k, v in c.items() if k != "credentials"})
        if path == "/deployments" and method == "GET":
            ds = _deployments(arm_state)
            return J(200, {"value": ds})
        m = re.match(r"^/deployments/([^/]+)$", path)
        if m and method == "GET":
            d = next((x for x in _deployments(arm_state) if x["name"] == m.group(1)), None)
            return J(200, d) if d else nf("Deployment", m.group(1))
        if path in ("/datasets", "/indexes", "/evaluators", "/redTeams", "/memory_stores") and method == "GET":
            return J(200, {"value": [], "data": [], "has_more": False})
        if path == "/agents" and method == "GET":
            return J(200, _plist([_agent_view(a) for a in _AGENTS.values()]))
        if path == "/agents" and method == "POST":           # preview shape: create agent + first version in one call
            nm = p.get("name")
            if not nm:
                raise Bad("Missing required parameter: 'name'.", "name")
            if nm in _AGENTS:
                raise Bad(f"Agent '{nm}' already exists.", "name", 409, "conflict")
            _AGENTS[nm] = {"name": nm, "versions": [_agent_ver(nm, p.get("definition") or {}, p, 1)]}
            return J(200, _agent_view(_AGENTS[nm]))
        m = re.match(r"^/agents/([^/]+)(?:/versions(?:/([^/]+))?)?$", path)
        if m:
            nm, ver = m.group(1), m.group(2)
            sub = path[len("/agents/" + nm):]
            a = _AGENTS.get(nm)
            if sub == "/versions" and method == "POST":
                d = p.get("definition")
                if not isinstance(d, dict) or not d.get("model") and d.get("kind", "prompt") == "prompt":
                    raise Bad("definition.model is required for a prompt agent.", "definition")
                if a is None:
                    a = _AGENTS[nm] = {"name": nm, "versions": []}
                v = _agent_ver(nm, d, p, len(a["versions"]) + 1)
                a["versions"].append(v)
                return J(200, v)
            if a is None:
                return nf("Agent", nm)
            if sub == "" and method == "GET":
                return J(200, _agent_view(a))
            if sub == "" and method == "DELETE":
                del _AGENTS[nm]
                return J(200, {"object": "agent.deleted", "name": nm, "deleted": True})
            if sub == "/versions" and method == "GET":
                return J(200, _plist(list(reversed(a["versions"]))))
            if ver:
                v = next((x for x in a["versions"] if x["version"] == ver), None)
                if not v:
                    return nf("Agent version", ver)
                if method == "GET":
                    return J(200, v)
                if method == "DELETE":
                    a["versions"].remove(v)
                    if not a["versions"]:
                        del _AGENTS[nm]
                    return J(200, {"object": "agent.version.deleted", "name": nm, "version": ver, "deleted": True})
        return None
    except Bad as e:
        return _err(e)


# ───────────────────────────── Assistants API ─────────────────────────────
def _page(items, query, key="created_at"):
    order = (query or {}).get("order", "desc")
    items = list(items)[::-1] if order == "desc" else list(items)      # insertion order breaks created_at (1 s resolution) ties
    items = sorted(items, key=lambda x: x[key], reverse=(order == "desc"))
    lim = int((query or {}).get("limit") or 20)
    after = (query or {}).get("after")
    if after:
        ids = [i["id"] for i in items]
        items = items[ids.index(after) + 1:] if after in ids else items
    more = len(items) > lim
    items = items[:lim]
    return {"object": "list", "data": items, "first_id": items[0]["id"] if items else None, "last_id": items[-1]["id"] if items else None, "has_more": more}


def _asst_tools(tools):
    for t in tools or []:
        ty = (t or {}).get("type")
        if ty not in ("function", "code_interpreter", "file_search"):
            raise Bad(f"Tool type {ty!r} is not supported (function, code_interpreter and file_search are).", "tools")
        if ty == "function" and not (t.get("function") or {}).get("name"):
            raise Bad("function tools need function.name.", "tools")
    return tools or []


# ───────────────────────────── files, vector stores (file_search), code interpreter ─────────────────────────────
def _tr():
    try:
        from core import training_core as t
    except ImportError:  # pragma: no cover
        import training_core as t  # type: ignore
    return t


def _kc():
    try:
        from core import knowledge_core as k
    except ImportError:  # pragma: no cover
        import knowledge_core as k  # type: ignore
    return k


def _file_meta(fid):
    m = _am()._AZ_FILES.get(fid)
    if not m:
        raise Bad(f"No such File object: {fid}", "file_id", 404, "invalid_request_error")
    return m


def _file_bytes(fid):
    _file_meta(fid)
    return _tr().get_file(fid) or b""


def _check_resources(tr_):
    """Validate tool_resources {file_search:{vector_store_ids}, code_interpreter:{file_ids}} (existence)."""
    tr_ = tr_ or {}
    for vid in (tr_.get("file_search") or {}).get("vector_store_ids") or []:
        if vid not in _VS:
            raise Bad(f"No vector store found with id '{vid}'.", "tool_resources", 404, "invalid_request_error")
    for fid in (tr_.get("code_interpreter") or {}).get("file_ids") or []:
        _file_meta(fid)
    if (tr_.get("file_search") or {}).get("vector_stores"):
        raise Bad("tool_resources.file_search.vector_stores (inline creation) is not supported: create the vector store first and pass vector_store_ids.", "tool_resources")
    return tr_


def _vs_view(v):
    return {k: x for k, x in v.items() if not k.startswith("_")}


def _vs_counts(v):
    c = {"in_progress": 0, "completed": 0, "failed": 0, "cancelled": 0}
    for f in v["_files"].values():
        c[f["status"]] = c.get(f["status"], 0) + 1
    c["total"] = sum(c.values())
    v["file_counts"] = c
    v["usage_bytes"] = sum(f["usage_bytes"] for f in v["_files"].values())
    v["status"] = "completed"
    v["last_active_at"] = int(time.time())


def _index_file(vid, fid):
    """-> (vector_store.file object, chunks). Parse + chunk + embed; failures are modeled as status=failed with last_error."""
    meta = _file_meta(fid)
    base = {"id": fid, "object": "vector_store.file", "usage_bytes": meta["bytes"], "created_at": int(time.time()), "vector_store_id": vid,
            "chunking_strategy": {"type": "static", "static": {"max_chunk_size_tokens": 300, "chunk_overlap_tokens": 60}}}
    kc = _kc()
    try:
        text = kc.parse_document(meta["filename"], _file_bytes(fid))
    except Exception as e:  # noqa: BLE001
        return dict(base, status="failed", last_error={"code": "unsupported_file", "message": str(e)}), []
    pieces = [c for c, _h in kc.split_text(text, 300, 20, "FIXED_SIZE") if c.strip()]
    if not pieces:
        return dict(base, status="failed", last_error={"code": "invalid_file", "message": "the file has no extractable text"}), []
    vecs = llm.embed(pieces)["vectors"]
    return dict(base, status="completed", last_error=None), [{"file_id": fid, "filename": meta["filename"], "text": t_, "vec": v} for t_, v in zip(pieces, vecs)]


def _new_vs(name, file_ids, metadata=None):
    indexed = [(fid,) + _index_file("vs_pending", fid) for fid in file_ids]       # embed first: a replayed request must not leave a half-built store
    vid = _id("vs_", 24)
    v = {"id": vid, "object": "vector_store", "created_at": int(time.time()), "name": name, "usage_bytes": 0, "last_active_at": int(time.time()),
         "file_counts": {}, "status": "completed", "expires_after": None, "expires_at": None, "metadata": metadata or {}, "_files": {}, "_chunks": []}
    for fid, fo, ch in indexed:
        fo["vector_store_id"] = vid
        v["_files"][fid] = fo
        v["_chunks"] += ch
    _vs_counts(v)
    _VS[vid] = v
    return v


def _vs_add(v, fid):
    if fid in v["_files"]:
        raise Bad(f"File {fid} is already attached to this vector store.", "file_id", 400, "invalid_request_error")
    fo, ch = _index_file(v["id"], fid)
    v["_files"][fid] = fo
    v["_chunks"] += ch
    _vs_counts(v)
    return fo


def _retrieve(vids, query, k=5):
    hits = []
    qv = None
    for vid in vids:
        v = _VS.get(vid)
        if not v or not v["_chunks"]:
            continue
        if qv is None:
            qv = llm.embed([query])["vectors"][0]
        for c in v["_chunks"]:
            hits.append((llm.cosine(qv, c["vec"]), c))
    hits.sort(key=lambda x: -x[0])
    return [dict(c, score=round(sc, 4)) for sc, c in hits[:k]]


def _vector_stores_dispatch(method, path, query, p):
    am = _am()
    J = am._j

    def nf(what, i):
        return am._a_err(404, "invalid_request_error", f"No {what} found with id '{i}'.")
    if path == "/vector_stores":
        if method == "POST":
            for fid in p.get("file_ids") or []:
                _file_meta(fid)
            return J(200, _vs_view(_new_vs(p.get("name"), p.get("file_ids") or [], p.get("metadata"))))
        if method == "GET":
            return J(200, _page([_vs_view(v) for v in _VS.values()], query))
    ex = _vs_extra(method, path, query, p)
    if ex is not None:
        return ex
    m = re.match(r"^/vector_stores/([^/]+)(?:/(files|file_batches)(?:/([^/]+))?)?$", path)
    if not m:
        return None
    v = _VS.get(m.group(1))
    if not v:
        return nf("vector store", m.group(1))
    sub, oid = m.group(2), m.group(3)
    if sub is None:
        if method == "GET":
            return J(200, _vs_view(v))
        if method == "POST":
            if "name" in p:
                v["name"] = p["name"]
            if "metadata" in p:
                v["metadata"] = p["metadata"]
            return J(200, _vs_view(v))
        if method == "DELETE":
            del _VS[v["id"]]
            return J(200, {"id": v["id"], "object": "vector_store.deleted", "deleted": True})
    elif sub == "files":
        if oid is None and method == "POST":
            if not p.get("file_id"):
                raise Bad("Missing required parameter: 'file_id'.", "file_id")
            return J(200, _vs_add(v, p["file_id"]))
        if oid is None and method == "GET":
            return J(200, _page(list(v["_files"].values()), query))
        if oid:
            f = v["_files"].get(oid)
            if not f:
                return nf("vector store file", oid)
            if method == "GET":
                return J(200, f)
            if method == "POST":                          # update attributes
                if "attributes" in p:
                    f["attributes"] = p["attributes"]
                return J(200, f)
            if method == "DELETE":
                del v["_files"][oid]
                v["_chunks"] = [c for c in v["_chunks"] if c["file_id"] != oid]
                _vs_counts(v)
                return J(200, {"id": oid, "object": "vector_store.file.deleted", "deleted": True})
    elif sub == "file_batches":
        if oid is None and method == "POST":
            ids = p.get("file_ids") or []
            if not ids:
                raise Bad("Missing required parameter: 'file_ids'.", "file_ids")
            for fid in ids:
                if fid not in v["_files"]:
                    _vs_add(v, fid)
            bid = _id("vsfb_", 24)
            b = {"_file_ids": list(ids), "id": bid, "object": "vector_store.files_batch", "created_at": int(time.time()), "vector_store_id": v["id"], "status": "completed",
                 "file_counts": dict(v["file_counts"])}
            v.setdefault("_batches", {})[bid] = b
            return J(200, _vs_view(b))
        b = (v.get("_batches") or {}).get(oid or "")
        if oid and not b:
            return nf("file batch", oid)
        if oid and method == "GET":
            return J(200, _vs_view(b))
    return None


def _vs_extra(method, path, query, p):
    """/vector_stores/{id}/file_batches/{b}/(files|cancel), /vector_stores/{id}/search, /vector_stores/{id}/files/{f}/content."""
    am = _am()
    J = am._j
    m = re.match(r"^/vector_stores/([^/]+)/file_batches/([^/]+)/(files|cancel)$", path)
    if m:
        v = _VS.get(m.group(1))
        b = ((v or {}).get("_batches") or {}).get(m.group(2))
        if not b:
            return am._a_err(404, "invalid_request_error", f"No file batch found with id '{m.group(2)}'.")
        if m.group(3) == "cancel" and method == "POST":
            return J(200, b)
        if m.group(3) == "files" and method == "GET":
            return J(200, _page([f for f in v["_files"].values() if f["id"] in (b.get("_file_ids") or v["_files"])], query))
    m = re.match(r"^/vector_stores/([^/]+)/search$", path)
    if m and method == "POST":
        v = _VS.get(m.group(1))
        if not v:
            return am._a_err(404, "invalid_request_error", f"No vector store found with id '{m.group(1)}'.")
        q = p.get("query") or ""
        q = " ".join(q) if isinstance(q, list) else q
        hits = _retrieve([v["id"]], q, int(p.get("max_num_results") or 10))
        data = [{"file_id": h["file_id"], "filename": h["filename"], "score": h["score"], "attributes": {}, "content": [{"type": "text", "text": h["text"]}]} for h in hits]
        return J(200, {"object": "vector_store.search_results.page", "search_query": [q], "data": data, "has_more": False, "next_page": None})
    return None


_CI_TOOL = {"type": "function", "function": {"name": "code_interpreter", "description": "Run Python code in a sandbox and return what it printed; files written to the working directory are returned to the user.",
                                             "parameters": {"type": "object", "properties": {"input": {"type": "string", "description": "the Python source code to run"}}, "required": ["input"]}}}


def _resources(t, asst, kind, key):
    out = []
    for src in (asst.get("tool_resources") or {}, t.get("tool_resources") or {}):
        out += list((src.get(kind) or {}).get(key) or [])
    if kind == "code_interpreter":
        out += list(t.get("_ci_files") or [])
    if kind == "file_search" and t.get("_vs"):
        out.append(t["_vs"])
    return list(dict.fromkeys(out))


def _run_ci(code, t, asst):
    try:
        from core import code_sandbox_core as cs
    except ImportError:  # pragma: no cover
        import code_sandbox_core as cs  # type: ignore
    files = {}
    for fid in _resources(t, asst, "code_interpreter", "file_ids"):
        try:
            files[_file_meta(fid)["filename"]] = _file_bytes(fid)
        except Bad:
            continue
    res = cs.run(code, files=files, timeout=10.0)
    saved = []
    for n, b in res["files"].items():
        fid = _id("assistant-", 24)
        _tr().put_file(fid, b)
        _am()._AZ_FILES[fid] = {"id": fid, "object": "file", "bytes": len(b), "created_at": int(time.time()), "filename": n, "purpose": "assistants_output", "status": "processed", "status_details": None}
        saved.append({"file_id": fid, "filename": n})
    return res, saved


def _asst_view(a):
    return {k: v for k, v in a.items() if not k.startswith("_")}


def _msg_obj(thread_id, role, text, run_id=None, asst_id=None, annotations=None, attachments=None):
    return {"id": _id("msg_"), "object": "thread.message", "created_at": int(time.time()), "assistant_id": asst_id, "thread_id": thread_id,
            "run_id": run_id, "role": role, "content": [{"type": "text", "text": {"value": text, "annotations": annotations or []}}], "attachments": attachments or [],
            "metadata": {}, "status": "completed", "completed_at": int(time.time()), "incomplete_at": None, "incomplete_details": None}


def _thread_chat(t, asst, extra_instr=None):
    sysm = "\n".join(x for x in (asst.get("instructions"), extra_instr) if x)
    msgs = ([{"role": "system", "content": sysm}] if sysm else []) + [dict(m) for m in t["_chat"]]
    return msgs


def _step(run, kind, details, usage=None):
    st_ = {"id": _id("step_"), "object": "thread.run.step", "created_at": int(time.time()), "run_id": run["id"], "assistant_id": run["assistant_id"], "thread_id": run["thread_id"],
           "type": kind, "status": "completed", "cancelled_at": None, "completed_at": int(time.time()), "expired_at": None, "failed_at": None, "last_error": None,
           "step_details": details, "usage": usage, "metadata": None}
    run.setdefault("_steps", []).append(st_)
    return st_


def _execute_run(arm_find, t, run, asst):
    """Run the model over the thread (looping through code_interpreter calls); mutate run + thread. Terminal status on return."""
    dep = run["model"]
    if arm_find is not None and not arm_find(dep)[1]:
        raise Bad("The API deployment for this resource does not exist.", None, 404, "DeploymentNotFound")
    ci_on = any(x.get("type") == "code_interpreter" for x in run["tools"])
    fs_on = any(x.get("type") == "file_search" for x in run["tools"])
    ftools = [{"type": "function", "function": t_["function"]} for t_ in run["tools"] if t_.get("type") == "function"] + ([_CI_TOOL] if ci_on else [])
    passages, cites = "", []
    if fs_on:
        vids = _resources(t, asst, "file_search", "vector_store_ids")
        q = next((m["content"] for m in reversed(t["_chat"]) if m["role"] == "user"), "")
        k = int(((next((x for x in run["tools"] if x.get("type") == "file_search"), {}).get("file_search") or {}).get("max_num_results")) or 5)
        hits = _retrieve(vids, q, k) if vids and q else []
        if hits:
            passages = "Answer from these file excerpts when relevant and cite them as 【n†filename】:\n" + "\n".join(f"[{i}] ({h['filename']}) {h['text']}" for i, h in enumerate(hits))
            seen = {}
            for h in hits:
                seen.setdefault(h["file_id"], h["filename"])
            cites = list(seen.items())
            _step(run, "tool_calls", {"type": "tool_calls", "tool_calls": [{"id": _id("call_"), "type": "file_search", "file_search": {
                "ranking_options": {"ranker": "auto", "score_threshold": 0.0},
                "results": [{"file_id": h["file_id"], "file_name": h["filename"], "score": h["score"], "content": [{"type": "text", "text": h["text"]}]} for h in hits]}}]})
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    saved_all = []
    for _round in range(_MAX_CI_STEPS + 1):
        body = {"messages": _thread_chat(t, asst, "\n\n".join(x for x in (run.get("additional_instructions"), passages) if x) or None), "tools": ftools}
        if not body["tools"]:
            del body["tools"]
        if run.get("tool_choice") not in (None, "auto") and not ci_on:
            body["tool_choice"] = run["tool_choice"]
        for k_ in ("temperature", "top_p"):
            if run.get(k_) is not None:
                body[k_] = run[k_]
        if run.get("max_completion_tokens"):
            body["max_completion_tokens"] = run["max_completion_tokens"]
        rf = run.get("response_format")
        if isinstance(rf, dict) and rf.get("type") in ("json_object", "json_schema"):
            body["response_format"] = rf
        try:
            r = _call(_chat_req(body), dep)
        except Bad as e:
            run.update(status="failed", failed_at=int(time.time()), last_error={"code": "server_error" if e.status >= 500 else "invalid_request", "message": e.msg})
            return None
        for k_, v_ in (("prompt_tokens", r["input_tokens"]), ("completion_tokens", r["output_tokens"])):
            usage[k_] += v_
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        run["usage"] = dict(usage)
        calls = r["tool_calls"]
        ci_calls = [c for c in calls if ci_on and c["name"] == "code_interpreter"]
        user_calls = [c for c in calls if c not in ci_calls]
        if ci_calls:
            extra, tcs = [], []
            for c in ci_calls:
                code = c["arguments"].get("input") if isinstance(c["arguments"], dict) else None
                res, saved = _run_ci(code or "", t, asst)
                saved_all += saved
                logs = res["stdout"] + (("\n" + res["error"]) if res["error"] else "")
                tcs.append({"id": c["id"], "type": "code_interpreter", "code_interpreter": {"input": code or "", "outputs": ([{"type": "logs", "logs": logs}] if logs else [])}})
                extra.append({"role": "tool", "tool_call_id": c["id"], "content": (res["stdout"] or "(no output)") + (("\nERROR: " + res["error"]) if res["error"] else "") +
                              (("\nFiles written: " + ", ".join(x["filename"] for x in saved)) if saved else "")})
            _step(run, "tool_calls", {"type": "tool_calls", "tool_calls": tcs})
            hm = _hist_msg(r)
            if user_calls:
                run["_pending"] = hm
                run["_extra"] = extra
                run["required_action"] = {"type": "submit_tool_outputs", "submit_tool_outputs": {"tool_calls": [
                    {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for c in user_calls]}}
                run["status"] = "requires_action"
                return None
            t["_chat"].append(hm)
            t["_chat"] += extra
            continue
        if user_calls:
            run["_pending"] = _hist_msg(r)
            run["required_action"] = {"type": "submit_tool_outputs", "submit_tool_outputs": {"tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for c in user_calls]}}
            run["status"] = "requires_action"
            return None
        text = r["text"]
        ann = []
        for fid, fname in cites:
            mark = f"【{len(ann)}†{fname}】"
            ann.append({"type": "file_citation", "text": mark, "start_index": len(text) + 1, "end_index": len(text) + 1 + len(mark), "file_citation": {"file_id": fid}})
            text += " " + mark
        for sv in saved_all:
            i = text.find(sv["filename"])
            if i >= 0:
                ann.append({"type": "file_path", "text": sv["filename"], "start_index": i, "end_index": i + len(sv["filename"]), "file_path": {"file_id": sv["file_id"]}})
        t["_chat"].append({"role": "assistant", "content": r["text"]})
        m = _msg_obj(t["id"], "assistant", text, run["id"], asst["id"], ann, [{"file_id": sv["file_id"], "tools": [{"type": "code_interpreter"}]} for sv in saved_all])
        t["_msgs"].append(m)
        _step(run, "message_creation", {"type": "message_creation", "message_creation": {"message_id": m["id"]}}, dict(usage))
        run.update(status="incomplete" if r["finish_reason"] == "length" else "completed", required_action=None, completed_at=int(time.time()))
        if r["finish_reason"] == "length":
            run["incomplete_details"] = {"reason": "max_completion_tokens"}
        return m
    run.update(status="failed", failed_at=int(time.time()), last_error={"code": "server_error", "message": f"code_interpreter did not converge within {_MAX_CI_STEPS} steps"})
    return None


def _run_view(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def _new_run(t, asst, p):
    tools = _asst_tools(p["tools"]) if p.get("tools") else asst["tools"]
    now = int(time.time())
    return {"id": _id("run_"), "object": "thread.run", "created_at": now, "assistant_id": asst["id"], "thread_id": t["id"], "status": "queued",
            "started_at": now, "expires_at": None, "cancelled_at": None, "failed_at": None, "completed_at": None, "required_action": None,
            "last_error": None, "model": p.get("model") or asst["model"], "instructions": p.get("instructions") or asst.get("instructions"),
            "additional_instructions": p.get("additional_instructions"), "tools": tools, "metadata": p.get("metadata") or {}, "usage": None,
            "temperature": p.get("temperature", asst.get("temperature")), "top_p": p.get("top_p", asst.get("top_p")),
            "max_completion_tokens": p.get("max_completion_tokens"), "max_prompt_tokens": None, "truncation_strategy": {"type": "auto", "last_messages": None},
            "incomplete_details": None, "response_format": p.get("response_format", "auto"), "tool_choice": p.get("tool_choice", "auto"),
            "parallel_tool_calls": True, "_runs_stream": None}


def _tc(tc):
    if isinstance(tc, dict):
        return {"type": "function", "function": {"name": (tc.get("function") or {}).get("name")}}
    return tc


def _run_stream(t, run, asst, before_msgs):
    """Replay a finished synchronous run as the thread.* SSE sequence."""
    def ev(name, data):
        return f"event: {name}\ndata: " + json.dumps(data) + "\n\n"
    v = _run_view(run)
    yield ev("thread.run.created", dict(v, status="queued"))
    yield ev("thread.run.queued", dict(v, status="queued"))
    yield ev("thread.run.in_progress", dict(v, status="in_progress"))
    for m in t["_msgs"][before_msgs:]:
        yield ev("thread.message.created", dict(m, status="in_progress", content=[]))
        yield ev("thread.message.in_progress", dict(m, status="in_progress", content=[]))
        txt = m["content"][0]["text"]["value"]
        for i in range(0, len(txt), 12):
            yield ev("thread.message.delta", {"id": m["id"], "object": "thread.message.delta",
                                              "delta": {"content": [{"index": 0, "type": "text", "text": {"value": txt[i:i + 12], "annotations": []}}]}})
        yield ev("thread.message.completed", m)
    yield ev({"completed": "thread.run.completed", "requires_action": "thread.run.requires_action", "failed": "thread.run.failed",
              "incomplete": "thread.run.incomplete"}.get(run["status"], "thread.run.completed"), v)
    yield "event: done\ndata: [DONE]\n\n"


def assistants_dispatch(arm_find, method, path, query, p):
    """-> response dict, or None when path is not an Assistants route."""
    am = _am()
    if re.match(r"^/openai(/v1)?/evals(/|$)", path):
        return evals_dispatch(arm_find, method, path, query, p)
    if re.match(r"^/openai(/v1)?/vyomi/promptflow(/|$)", path):
        return pf_dispatch(arm_find, method, path, query, p)
    method = method.upper()
    path = re.sub(r"^/openai(/v1)?", "", path).rstrip("/")
    J = am._j

    def nf(what, i):
        return am._a_err(404, "invalid_request_error", f"No {what} found with id '{i}'.")
    try:
        if path == "/assistants":
            if method == "POST":
                if not p.get("model"):
                    raise Bad("Missing required parameter: 'model'.", "model")
                if arm_find is not None and not arm_find(p["model"])[1]:
                    raise Bad("The API deployment for this resource does not exist.", "model", 404, "DeploymentNotFound")
                a = {"id": _id("asst_"), "object": "assistant", "created_at": int(time.time()), "name": p.get("name"), "description": p.get("description"),
                     "model": p["model"], "instructions": p.get("instructions"), "tools": _asst_tools(p.get("tools")), "metadata": p.get("metadata") or {},
                     "temperature": p.get("temperature"), "top_p": p.get("top_p"), "response_format": p.get("response_format", "auto"), "tool_resources": _check_resources(p.get("tool_resources"))}
                _ASST[a["id"]] = a
                return J(200, _asst_view(a))
            if method == "GET":
                return J(200, _page([_asst_view(a) for a in _ASST.values()], query))
        m = re.match(r"^/assistants/([^/]+)$", path)
        if m:
            a = _ASST.get(m.group(1))
            if not a:
                return nf("assistant", m.group(1))
            if method == "GET":
                return J(200, _asst_view(a))
            if method == "POST":
                if "tools" in p:
                    p["tools"] = _asst_tools(p["tools"])
                if "tool_resources" in p:
                    p["tool_resources"] = _check_resources(p["tool_resources"])
                a.update({k: v for k, v in p.items() if k in ("name", "description", "model", "instructions", "tools", "metadata", "temperature", "top_p", "response_format", "tool_resources")})
                return J(200, _asst_view(a))
            if method == "DELETE":
                del _ASST[a["id"]]
                return J(200, {"id": a["id"], "object": "assistant.deleted", "deleted": True})
        if path == "/threads" and method == "POST":
            t = {"id": _id("thread_"), "object": "thread", "created_at": int(time.time()), "metadata": p.get("metadata") or {}, "tool_resources": _check_resources(p.get("tool_resources")),
                 "_chat": [], "_msgs": [], "_runs": {}}
            _THR[t["id"]] = t
            for mm in p.get("messages") or []:
                _add_message(t, mm)
            return J(200, {k: v for k, v in t.items() if not k.startswith("_")})
        if path == "/vector_stores" or path.startswith("/vector_stores/"):
            return _vector_stores_dispatch(method, path, query, p)
        if path == "/threads/runs" and method == "POST":
            asst = _ASST.get(p.get("assistant_id"))
            if not asst:
                return nf("assistant", p.get("assistant_id"))
            t = {"id": _id("thread_"), "object": "thread", "created_at": int(time.time()), "metadata": {}, "tool_resources": {}, "_chat": [], "_msgs": [], "_runs": {}}
            _THR[t["id"]] = t
            for mm in (p.get("thread") or {}).get("messages") or []:
                _add_message(t, mm)
            return _create_run(arm_find, t, asst, p)
        m = re.match(r"^/threads/([^/]+)$", path)
        if m:
            t = _THR.get(m.group(1))
            if not t:
                return nf("thread", m.group(1))
            if method == "GET":
                return J(200, {k: v for k, v in t.items() if not k.startswith("_")})
            if method == "POST":
                t["metadata"] = p.get("metadata", t["metadata"])
                return J(200, {k: v for k, v in t.items() if not k.startswith("_")})
            if method == "DELETE":
                del _THR[t["id"]]
                return J(200, {"id": t["id"], "object": "thread.deleted", "deleted": True})
        m = re.match(r"^/threads/([^/]+)/(messages|runs)(?:/([^/]+))?(?:/(submit_tool_outputs|cancel|steps))?(?:/([^/]+))?$", path)
        if m:
            t = _THR.get(m.group(1))
            if not t:
                return nf("thread", m.group(1))
            kind, oid, sub, sid = m.group(2), m.group(3), m.group(4), m.group(5)
            if kind == "messages":
                if oid is None and method == "POST":
                    return J(200, _add_message(t, p))
                if oid is None and method == "GET":
                    items = t["_msgs"]
                    if query.get("run_id"):
                        items = [x for x in items if x["run_id"] == query["run_id"]]
                    return J(200, _page(items, query))
                if oid and method == "GET":
                    mm = next((x for x in t["_msgs"] if x["id"] == oid), None)
                    return J(200, mm) if mm else nf("message", oid)
                if oid and method in ("POST", "DELETE"):
                    mm = next((x for x in t["_msgs"] if x["id"] == oid), None)
                    if not mm:
                        return nf("message", oid)
                    if method == "DELETE":
                        t["_msgs"].remove(mm)
                        return J(200, {"id": oid, "object": "thread.message.deleted", "deleted": True})
                    if "metadata" in p:
                        mm["metadata"] = p["metadata"] or {}
                    return J(200, mm)
            else:
                if oid is None and method == "POST":
                    asst = _ASST.get(p.get("assistant_id"))
                    if not asst:
                        return nf("assistant", p.get("assistant_id"))
                    return _create_run(arm_find, t, asst, p)
                if oid is None and method == "GET":
                    return J(200, _page([_run_view(r) for r in t["_runs"].values()], query))
                run = t["_runs"].get(oid)
                if oid and not run:
                    return nf("run", oid)
                if oid and sub is None and method == "GET":
                    return J(200, _run_view(run))
                if oid and sub is None and method == "POST":
                    if "metadata" in p:
                        run["metadata"] = p["metadata"] or {}
                    return J(200, _run_view(run))
                if sub == "steps" and sid and method == "GET":
                    stp = next((x for x in (run.get("_steps") or []) if x["id"] == sid), None)
                    return J(200, stp) if stp else nf("run step", sid)
                if sub == "steps" and method == "GET":
                    return J(200, _page(list(run.get("_steps") or []), query))
                if sub == "cancel" and method == "POST":
                    if run["status"] not in ("queued", "in_progress", "requires_action"):
                        raise Bad(f"Cannot cancel run with status '{run['status']}'.", None, 400, "invalid_request_error")
                    run.update(status="cancelled", cancelled_at=int(time.time()), required_action=None)
                    return J(200, _run_view(run))
                if sub == "submit_tool_outputs" and method == "POST":
                    if run["status"] != "requires_action":
                        raise Bad(f"Runs in status \"{run['status']}\" do not accept tool outputs.", None, 400, "invalid_request_error")
                    need = {c["id"] for c in run["required_action"]["submit_tool_outputs"]["tool_calls"]}
                    outs = p.get("tool_outputs") or []
                    if {o.get("tool_call_id") for o in outs} != need:
                        raise Bad(f"Expected tool outputs for call_ids {sorted(need)}, got {sorted(o.get('tool_call_id') for o in outs)}", "tool_outputs")
                    t["_chat"].append(run.pop("_pending"))
                    for o in outs:
                        t["_chat"].append({"role": "tool", "tool_call_id": o["tool_call_id"], "content": o.get("output") or ""})
                    t["_chat"] += run.pop("_extra", [])
                    before = len(t["_msgs"])
                    run.update(status="in_progress", required_action=None)
                    _execute_run(arm_find, t, run, _ASST[run["assistant_id"]])
                    if p.get("stream"):
                        return am._stream_out(200, {}, _run_stream(t, run, _ASST[run["assistant_id"]], before), "text/event-stream")
                    return J(200, _run_view(run))
        return None
    except Bad as e:
        return _err(e)


def _add_message(t, mm):
    if mm.get("role") not in ("user", "assistant"):
        raise Bad("Invalid value for 'role': must be 'user' or 'assistant'.", "role")
    c = mm.get("content")
    if isinstance(c, list):
        c = "".join((x.get("text") if isinstance(x.get("text"), str) else (x.get("text") or {}).get("value", "")) for x in c if x.get("type") == "text")
    if not isinstance(c, str) or not c:
        raise Bad("Missing required parameter: 'content'.", "content")
    atts = []
    for at in mm.get("attachments") or []:
        fid = (at or {}).get("file_id")
        _file_meta(fid)
        kinds = {x.get("type") for x in at.get("tools") or []}
        if not kinds or not kinds <= {"code_interpreter", "file_search"}:
            raise Bad("attachments[].tools must list code_interpreter and/or file_search.", "attachments")
        if "code_interpreter" in kinds:
            t.setdefault("_ci_files", []).append(fid)
        if "file_search" in kinds:
            if t.get("_vs"):
                _vs_add(_VS[t["_vs"]], fid)
            else:
                t["_vs"] = _new_vs(None, [fid])["id"]
        atts.append({"file_id": fid, "tools": [{"type": k} for k in sorted(kinds)]})
    obj = _msg_obj(t["id"], mm["role"], c)
    obj["attachments"] = atts
    obj["metadata"] = mm.get("metadata") or {}
    t["_msgs"].append(obj)
    t["_chat"].append({"role": mm["role"], "content": c})
    return obj


def _create_run(arm_find, t, asst, p):
    am = _am()
    for mm in p.get("additional_messages") or []:
        _add_message(t, mm)
    try:
        run = _new_run(t, asst, p)
    except Bad as e:
        return _err(e)
    run["tool_choice"] = _tc(run["tool_choice"])
    t["_runs"][run["id"]] = run
    before = len(t["_msgs"])
    try:
        _execute_run(arm_find, t, run, asst)
    except Bad as e:
        del t["_runs"][run["id"]]
        return _err(e)
    if p.get("stream"):
        return am._stream_out(200, {}, _run_stream(t, run, asst, before), "text/event-stream")
    return am._j(200, _run_view(run))


# ───────────────────── Azure OpenAI Evals + Microsoft Foundry Prompt flow (lane limflows) ─────────────────────
# Evals: the real Azure OpenAI Evals API (/openai/evals, runs, output_items) graded by the SAME scorers as Bedrock evaluations
# (core/bedrock_build_core: token F1 / ROUGE / embedding cosine, and the local-model judge parser). Prompt flow: a flow.dag.yaml-shaped DAG
# (inputs / outputs / nodes of type llm and prompt) executed on the SAME flow runner as Bedrock Flows (bedrock_build_core._Run); a flow is
# tested via .../test and served like a managed online endpoint via POST .../score. python-tool nodes are rejected (they would run
# arbitrary user code). Honest limits: the judge is the single small local model; state is process-local like the Assistants objects.
_EVALS: dict = {}
_EVRUNS: dict = {}
_PF: dict = {}
_EV_MAX = 1000
_EV_BATCH = 3 if sys.platform == "emscripten" else 25
_BB_RAW = [None]


def _bb():
    try:
        from core import bedrock_build_core as b
    except ImportError:  # Pyodide flat layout
        import bedrock_build_core as b  # type: ignore
    return b


def _dig(ctx, path):
    cur = ctx
    for k in path.split("."):
        cur = cur.get(k) if isinstance(cur, dict) else None
        if cur is None:
            return ""
    return cur if isinstance(cur, str) else json.dumps(cur)


def _tmpl(s, ctx):
    if isinstance(s, dict):      # {type: input_text, text: ...} content part
        s = s.get("text", "")
    return re.sub(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}", lambda m: _dig(ctx, m.group(1)), str(s or ""))


def _chat_text(arm_find, model, messages, temperature=0.0, max_tokens=256):
    if arm_find is not None and not arm_find(model)[1]:
        raise Bad(f"The API deployment '{model}' for this resource does not exist.", "model", 404, "DeploymentNotFound")
    body = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    return _call(_chat_req(body), model)["text"]


_METRICS = ("fuzzy_match", "bleu", "rouge_1", "rouge_2", "rouge_3", "rouge_4", "rouge_5", "rouge_l", "cosine")


def _ngrams(toks, n):
    from collections import Counter
    return Counter(tuple(toks[i:i + n]) for i in range(len(toks) - n + 1))


def _sim(metric, a, b):
    bb = _bb()
    ta, tb = bb._toks(a), bb._toks(b)
    if metric == "fuzzy_match":
        import difflib
        return difflib.SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    if metric == "rouge_l":
        return bb.rouge_l(a, b)
    if metric.startswith("rouge_"):
        n = int(metric[-1])
        ca, cb = _ngrams(ta, n), _ngrams(tb, n)
        common = sum((ca & cb).values())
        if not common:
            return 0.0
        pr, rc = common / max(1, sum(ca.values())), common / max(1, sum(cb.values()))
        return 2 * pr * rc / (pr + rc)
    if metric == "bleu":
        import math
        if not ta or not tb:
            return 0.0
        logs = []
        for n in range(1, 5):
            ca, cb = _ngrams(ta, n), _ngrams(tb, n)
            tot = max(1, sum(ca.values()))
            logs.append(math.log((sum((ca & cb).values()) + (0 if n == 1 else 1)) / (tot + (0 if n == 1 else 1)) or 1e-9))
        bp = 1.0 if len(ta) >= len(tb) else math.exp(1 - len(tb) / len(ta))
        return bp * math.exp(sum(logs) / 4)
    if metric == "cosine":
        v = llm.embed([a, b])["vectors"]
        return max(0.0, bb._cos(v[0], v[1]))
    raise Bad(f"Unsupported evaluation_metric '{metric}': supported {', '.join(_METRICS)}", "evaluation_metric")


def _grade(arm_find, c, ctx):
    t, name = c.get("type"), c.get("name") or c.get("type")
    bb = _bb()
    if t == "string_check":
        a, b = _tmpl(c.get("input"), ctx), _tmpl(c.get("reference"), ctx)
        op = c.get("operation")
        ok = {"eq": a == b, "ne": a != b, "like": b in a, "ilike": b.lower() in a.lower()}.get(op)
        return {"name": name, "type": t, "score": 1.0 if ok else 0.0, "passed": bool(ok)}
    if t == "text_similarity":
        a, b = _tmpl(c.get("input"), ctx), _tmpl(c.get("reference"), ctx)
        s = round(_sim(c.get("evaluation_metric"), a, b), 4)
        return {"name": name, "type": t, "score": s, "passed": s >= float(c.get("pass_threshold", 0.5))}
    if t in ("label_model", "score_model"):
        msgs = [{"role": m.get("role", "user"), "content": _tmpl(m.get("content"), ctx)} for m in (c.get("input") or [])]
        body = "\n\n".join(f"{m['role']}: {m['content']}" for m in msgs)
        if t == "label_model":
            labels, passing = c["labels"], set(c.get("passing_labels") or [])
            scale = [(l, 1.0 if l in passing else 0.0) for l in labels]
            prompt = f"You are an impartial grader.\n\n{body}\n\nChoose exactly one label from: {' | '.join(labels)}.\nReply with JSON only: " + '{"reasoning": "<one short sentence>", "answer": "<one label>"}'
            txt = _chat_text(arm_find, c["model"], [{"role": "user", "content": prompt}])
            sc, lab, why = bb._parse_verdict(txt, scale)
            if sc is None:
                return {"name": name, "type": t, "score": None, "passed": False, "sample": {"error": "unparsable judge verdict", "raw": why}}
            return {"name": name, "type": t, "score": sc, "passed": lab in passing, "sample": {"label": lab, "reasoning": why}}
        lo, hi = (c.get("range") or [0, 1])[:2]
        prompt = f"You are an impartial grader.\n\n{body}\n\nGive a numeric score between {lo} and {hi}.\nReply with JSON only: " + '{"reasoning": "<one short sentence>", "score": <number>}'
        txt = _chat_text(arm_find, c["model"], [{"role": "user", "content": prompt}])
        val = None
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                val = float(json.loads(m.group(0)).get("score"))
            except (ValueError, TypeError):
                val = None
        if val is None:
            mm = re.search(r"-?\d+(?:\.\d+)?", txt)
            val = float(mm.group(0)) if mm else None
        if val is None:
            return {"name": name, "type": t, "score": None, "passed": False, "sample": {"error": "unparsable judge score", "raw": txt[:200]}}
        val = max(float(lo), min(float(hi), val))
        return {"name": name, "type": t, "score": val, "passed": val >= float(c.get("pass_threshold", (lo + hi) / 2))}
    raise Bad(f"Unsupported testing_criteria type '{t}' (supported: string_check, text_similarity, label_model, score_model)", "testing_criteria")


def _eval_view(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def _ev_run_view(r):
    out = {k: v for k, v in r.items() if not k.startswith("_")}
    its = r["_items"]
    out["result_counts"] = {"total": len(r["_src"]), "errored": sum(1 for i in its if i["status"] == "error"), "failed": sum(1 for i in its if i["status"] == "fail"), "passed": sum(1 for i in its if i["status"] == "pass")}
    out["per_testing_criteria_results"] = [{"testing_criteria": c.get("name") or c["type"], "passed": sum(1 for i in its for x in i["results"] if x["name"] == (c.get("name") or c["type"]) and x["passed"]),
                                            "failed": sum(1 for i in its for x in i["results"] if x["name"] == (c.get("name") or c["type"]) and not x["passed"])} for c in r["_crit"]]
    out["vyomiProgress"] = {"processedItems": len(its), "totalItems": len(r["_src"])}
    return out


def _ev_step(arm_find, run, max_items=None):
    """Advance a run by up to max_items items, committing each item as it finishes (replay-safe on Nano)."""
    if run["status"] != "in_progress":
        return
    done, t0 = 0, time.time()
    try:
        while len(run["_items"]) < len(run["_src"]):
            if run["status"] != "in_progress" or (max_items is not None and done >= max_items) or time.time() - t0 > 25:
                return
            i = len(run["_items"])
            src = run["_src"][i]
            item = src.get("item") or {}
            ds = run["data_source"]
            sample = dict(src.get("sample") or {})
            if ds["type"] == "completions":
                msgs = [{"role": m.get("role", "user"), "content": _tmpl(m.get("content"), {"item": item})} for m in (ds["input_messages"].get("template") or [])]
                sp = ds.get("sampling_params") or {}
                text = _chat_text(arm_find, ds["model"], msgs, float(sp.get("temperature", 0.0)), int(sp.get("max_completion_tokens") or sp.get("max_tokens") or 256))
                sample = {"input": msgs, "output": [{"role": "assistant", "content": text}], "model": ds["model"]}
                sample["output_text"] = text
            elif "output_text" not in sample:
                o = sample.get("output")
                sample["output_text"] = o if isinstance(o, str) else (" ".join(m.get("content", "") for m in o) if isinstance(o, list) else "")
            ctx = {"item": item, "sample": {**sample, "output_text": sample.get("output_text", "")}}
            results = [_grade(arm_find, c, ctx) for c in run["_crit"]]
            ok = all(r["passed"] for r in results)
            bad = any(r["score"] is None for r in results)
            run["_items"].append({"object": "eval.run.output_item", "id": f"outputitem_{uuid.uuid4().hex[:16]}", "run_id": run["id"], "eval_id": run["eval_id"], "created_at": int(time.time()),
                                  "status": "error" if bad else ("pass" if ok else "fail"), "datasource_item_id": i, "datasource_item": item, "results": results, "sample": sample})
            done += 1
        run.update(status="completed", completed_at=int(time.time()), report_url=f"vyomi://evals/{run['eval_id']}/runs/{run['id']}")
    except Bad as e:
        run.update(status="failed", error={"code": e.code, "message": e.msg})
    except llm.LlmUnavailable as e:
        run.update(status="failed", error={"code": "ServiceUnavailable", "message": str(e)})


def _ev_drive(arm_find, run):
    if sys.platform == "emscripten":
        return
    import threading

    def go():
        while run["status"] == "in_progress":
            try:
                _ev_step(arm_find, run, _EV_BATCH)
            except BaseException:  # noqa: BLE001
                run.update(status="failed", error={"code": "server_error", "message": "background evaluation worker stopped"})
    threading.Thread(target=go, daemon=True).start()


def _source_items(ds):
    src = ds.get("source") or {}
    if src.get("type") == "file_content":
        rows = src.get("content") or []
    elif src.get("type") == "file_id":
        raw = _am()._trained().get_file(src.get("id")) if src.get("id") else None
        if raw is None:
            raise Bad(f"No such File object: {src.get('id')}", "data_source.source.id", 404, "NotFound")
        rows = [json.loads(x) for x in raw.decode("utf-8", "replace").splitlines() if x.strip()]
    else:
        raise Bad("data_source.source.type must be file_content or file_id", "data_source.source")
    rows = [r if isinstance(r, dict) and "item" in r else {"item": r} for r in rows]
    if not rows:
        raise Bad("The data source has no rows", "data_source.source")
    if len(rows) > _EV_MAX:
        raise Bad(f"The data source has {len(rows)} rows; the maximum is {_EV_MAX}", "data_source.source")
    return rows


def evals_dispatch(arm_find, method, path, query, p):
    am = _am()
    J = am._j
    method = method.upper()
    path = re.sub(r"^/openai(/v1)?", "", path).rstrip("/")

    def err(msg, param=None, code="invalid_request_error", status=400):
        return am._a_err(status, code, msg, param)
    try:
        if path == "/evals":
            if method == "POST":
                dsc = p.get("data_source_config") or {}
                if dsc.get("type") != "custom" or not isinstance(dsc.get("item_schema"), dict):
                    return err("data_source_config must be {type: 'custom', item_schema: {...}} (logs / stored_completions sources are not supported)", "data_source_config")
                crit = p.get("testing_criteria")
                if not crit or not isinstance(crit, list):
                    return err("Missing required parameter: 'testing_criteria'.", "testing_criteria")
                for c in crit:
                    if c.get("type") not in ("string_check", "text_similarity", "label_model", "score_model"):
                        return err(f"Unsupported testing_criteria type '{c.get('type')}' (supported: string_check, text_similarity, label_model, score_model; python graders run user code and are not simulated)", "testing_criteria")
                    if c["type"] == "text_similarity" and c.get("evaluation_metric") not in _METRICS:
                        return err(f"Unsupported evaluation_metric '{c.get('evaluation_metric')}': supported {', '.join(_METRICS)}", "testing_criteria")
                    if c["type"] in ("label_model", "score_model") and not c.get("model"):
                        return err("label_model / score_model criteria need a 'model' (a deployment of this resource)", "testing_criteria")
                    if c["type"] == "label_model" and not (c.get("labels") and c.get("passing_labels")):
                        return err("label_model criteria need 'labels' and 'passing_labels'", "testing_criteria")
                    if c["type"] == "string_check" and c.get("operation") not in ("eq", "ne", "like", "ilike"):
                        return err("string_check operation must be eq, ne, like or ilike", "testing_criteria")
                eid = _id("eval_", 32)
                _EVALS[eid] = {"object": "eval", "id": eid, "name": p.get("name"), "data_source_config": dsc, "testing_criteria": [dict(c, id=c.get("id") or _id(f"{c['type']}-", 16)) for c in crit],
                               "created_at": int(time.time()), "metadata": p.get("metadata") or {}}
                return J(200, _eval_view(_EVALS[eid]))
            if method == "GET":
                return J(200, _page([_eval_view(e) for e in _EVALS.values()], query))
        m = re.match(r"^/evals/([^/]+)$", path)
        if m:
            e = _EVALS.get(m.group(1))
            if not e:
                return err(f"Eval with id {m.group(1)} not found", None, "not_found", 404)
            if method == "GET":
                return J(200, _eval_view(e))
            if method == "POST":
                for k in ("name", "metadata"):
                    if k in p:
                        e[k] = p[k]
                return J(200, _eval_view(e))
            if method == "DELETE":
                del _EVALS[e["id"]]
                for rid in [r for r, v in _EVRUNS.items() if v["eval_id"] == e["id"]]:
                    del _EVRUNS[rid]
                return J(200, {"object": "eval.deleted", "deleted": True, "eval_id": e["id"]})
        m = re.match(r"^/evals/([^/]+)/runs$", path)
        if m:
            e = _EVALS.get(m.group(1))
            if not e:
                return err(f"Eval with id {m.group(1)} not found", None, "not_found", 404)
            if method == "POST":
                ds = p.get("data_source") or {}
                if ds.get("type") not in ("jsonl", "completions"):
                    return err("data_source.type must be jsonl or completions", "data_source")
                if ds["type"] == "completions" and not (ds.get("model") and (ds.get("input_messages") or {}).get("template")):
                    return err("completions data sources need 'model' and input_messages.template", "data_source")
                src = _source_items(ds)
                rid = _id("evalrun_", 32)
                run = {"object": "eval.run", "id": rid, "eval_id": e["id"], "status": "in_progress", "model": ds.get("model") or "", "name": p.get("name") or f"{e.get('name') or 'eval'} run", "created_at": int(time.time()),
                       "report_url": None, "data_source": ds, "metadata": p.get("metadata") or {}, "error": None, "_src": src, "_items": [], "_crit": e["testing_criteria"]}
                _EVRUNS[rid] = run
                _ev_step(arm_find, run, _EV_BATCH)
                _ev_drive(arm_find, run) if run["status"] == "in_progress" else None
                return J(200, _ev_run_view(run))
            if method == "GET":
                return J(200, _page([_ev_run_view(r) for r in _EVRUNS.values() if r["eval_id"] == e["id"]], query, "created_at"))
        m = re.match(r"^/evals/([^/]+)/runs/([^/]+)(?:/(output_items)(?:/([^/]+))?)?$", path)
        if m:
            r = _EVRUNS.get(m.group(2))
            if not r or r["eval_id"] != m.group(1):
                return err(f"Run with id {m.group(2)} not found", None, "not_found", 404)
            if m.group(3):
                _ev_step(arm_find, r, _EV_BATCH)
                its = r["_items"]
                if query.get("status"):
                    its = [i for i in its if i["status"] == query["status"]]
                if m.group(4):
                    it = next((i for i in r["_items"] if i["id"] == m.group(4)), None)
                    return J(200, it) if it else err(f"Output item {m.group(4)} not found", None, "not_found", 404)
                return J(200, _page(its, query, "created_at"))
            if method == "GET":
                _ev_step(arm_find, r, _EV_BATCH)
                return J(200, _ev_run_view(r))
            if method == "POST":       # cancel
                if r["status"] == "in_progress":
                    r["status"] = "canceled"
                return J(200, _ev_run_view(r))
            if method == "DELETE":
                del _EVRUNS[r["id"]]
                return J(200, {"object": "eval.run.deleted", "deleted": True, "run_id": r["id"]})
    except Bad as e:
        return _err(e)
    return None


# ── Prompt flow ─────────────────────────────────────────────────────────────────────────────
_REF = re.compile(r"^\$\{([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\}$")


def _pf_roles(text):
    """prompt-flow jinja2 role sections (a line 'system:' / 'user:' / 'assistant:') -> chat messages; no marker = one user message."""
    parts, cur = [], None
    for line in str(text).splitlines():
        m = re.match(r"^\s*#?\s*(system|user|assistant)\s*:\s*$", line, re.I)
        if m:
            cur = {"role": m.group(1).lower(), "content": ""}
            parts.append(cur)
        elif cur is None:
            cur = {"role": "user", "content": line + "\n"}
            parts.append(cur)
        else:
            cur["content"] += line + "\n"
    return [{"role": x["role"], "content": x["content"].strip()} for x in parts if x["content"].strip()]


def _pf_validate(flow):
    if not isinstance(flow, dict) or not isinstance(flow.get("nodes"), list):
        raise Bad("A flow needs 'nodes' (flow.dag.yaml shape: inputs, outputs, nodes)", "flow")
    names = {"inputs"}
    for n in flow["nodes"]:
        nm = n.get("name")
        if not nm or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", nm) or nm in names:
            raise Bad(f"Node name '{nm}' is missing, invalid or duplicated", "flow.nodes")
        names.add(nm)
        t = n.get("type")
        if t not in ("llm", "prompt"):
            raise Bad(f"Node '{nm}': type '{t}' is not supported (llm and prompt nodes only; python tool nodes would run arbitrary user code, use an Azure Function or the openai SDK from your own code)", "flow.nodes")
        path = ((n.get("source") or {}).get("path"))
        if not path or path not in (flow.get("files") or {}):
            raise Bad(f"Node '{nm}': source.path '{path}' is not a file of the flow (add it under 'files')", "flow.nodes")
        if t == "llm" and not (n.get("inputs") or {}).get("deployment_name"):
            raise Bad(f"Node '{nm}': an llm node needs inputs.deployment_name (a deployment of the Azure OpenAI / Foundry resource)", "flow.nodes")
    for nm, o in (flow.get("outputs") or {}).items():
        m = _REF.match(str((o or {}).get("reference", "")))
        if not m or (m.group(1) != "inputs" and m.group(1) not in names):
            raise Bad(f"Output '{nm}': reference must look like ${{node.output}} of an existing node", "flow.outputs")
    # every ${node.output} input reference must point at an existing node (cycles are rejected by the runner's validator)
    for n in flow["nodes"]:
        for k, v in (n.get("inputs") or {}).items():
            m = _REF.match(str(v))
            if m and m.group(1) not in names:
                raise Bad(f"Node '{n['name']}': input '{k}' references unknown node '{m.group(1)}'", "flow.nodes")
    return flow


def _pf_to_definition(flow, arm_find):
    """flow.dag.yaml -> the Bedrock Flows runner definition: Input (fields as ports) -> Template / Prompt nodes -> Output nodes."""
    ins = list((flow.get("inputs") or {}).keys())
    nodes = [{"name": "inputs", "type": "Input", "configuration": {"input": {}}, "outputs": [{"name": "document", "type": "Object"}] + [{"name": k, "type": "String"} for k in ins]}]
    conns = []

    def port(ref_node, ref_out):
        if ref_node == "inputs":
            return "inputs", ref_out
        n = next(x for x in flow["nodes"] if x["name"] == ref_node)
        return ref_node, ("modelCompletion" if n["type"] == "llm" else "output")
    for n in flow["nodes"]:
        text = flow["files"][n["source"]["path"]]
        consts = {}
        for k, v in (n.get("inputs") or {}).items():
            m = _REF.match(str(v))
            if m:
                s, so = port(m.group(1), m.group(2))
                conns.append({"name": f"{s}_{so}_{n['name']}_{k}", "type": "Data", "source": s, "target": n["name"], "configuration": {"data": {"sourceOutput": so, "targetInput": k}}})
            else:
                consts[k] = v
        if n["type"] == "llm":
            dep = consts.pop("deployment_name")
            temp = float(consts.pop("temperature", 0.2))
            mt = int(consts.pop("max_tokens", 256) or 256)
            consts.pop("response_format", None)
            nodes.append({"name": n["name"], "type": "Prompt", "constants": consts, "configuration": {"prompt": {"sourceConfiguration": {"inline": {
                "modelId": dep, "templateType": "TEXT", "messages": _pf_roles(text), "inferenceConfiguration": {"text": {"temperature": temp, "maxTokens": mt}}}}}}})
        else:
            nodes.append({"name": n["name"], "type": "Template", "constants": consts, "configuration": {"template": text}})
    for on, o in (flow.get("outputs") or {}).items():
        m = _REF.match(o["reference"])
        s, so = port(m.group(1), m.group(2))
        nodes.append({"name": f"out_{on}", "type": "Output", "configuration": {"output": {}}})
        conns.append({"name": f"{s}_{so}_out_{on}", "type": "Data", "source": s, "target": f"out_{on}", "configuration": {"data": {"sourceOutput": so, "targetInput": "document"}}})
    return {"nodes": nodes, "connections": conns}


def _pf_run(arm_find, flow, inputs, trace=False):
    bb = _bb()
    defs = {k: v.get("default") for k, v in (flow.get("inputs") or {}).items() if isinstance(v, dict) and "default" in v}
    doc = {**defs, **(inputs or {})}
    missing = [k for k in (flow.get("inputs") or {}) if k not in doc]
    if missing:
        raise Bad(f"Missing flow input(s): {', '.join(missing)}", "inputs")

    def chat(model, msgs, inl):
        t = ((inl.get("inferenceConfiguration") or {}).get("text") or {})
        return _chat_text(arm_find, model, msgs, float(t.get("temperature", 0.2)), int(t.get("maxTokens") or 256))
    try:
        outs, events = bb.run_flow(_pf_to_definition(flow, arm_find), [{"content": {"document": doc}}], exec_id="pf", trace=trace, chat=chat)
    except bb.BErr as e:
        raise Bad(e.msg, None, 500 if e.status >= 500 else 400, "FlowRunFailed")
    res = {k[4:]: v for k, v in outs}
    tr = []
    for kind, ev in events:
        if kind == "flowTraceEvent":
            t = ev["trace"]
            kk = next(iter(t))
            v = t[kk]
            if kk in ("nodeInputTrace", "nodeOutputTrace") and v["nodeName"] not in ("inputs",) and not v["nodeName"].startswith("out_"):
                tr.append({"node": v["nodeName"], "event": "input" if kk == "nodeInputTrace" else "output",
                           "fields": {f.get("nodeInputName") or f.get("nodeOutputName"): f["content"]["document"] for f in v["fields"]}})
    return res, tr


def pf_dispatch(arm_find, method, path, query, p):
    am = _am()
    J = am._j
    method = method.upper()
    path = re.sub(r"^/openai(/v1)?/vyomi/promptflow", "", path).rstrip("/")
    try:
        if path == "/flows":
            if method == "POST":
                name = p.get("name")
                if not name or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$", name):
                    raise Bad("Flow name must be 1-64 letters, digits, '-' or '_'", "name")
                if name in _PF:
                    raise Bad(f"A flow named '{name}' already exists", "name", 409, "Conflict")
                flow = _pf_validate(p.get("flow"))
                _PF[name] = {"name": name, "description": p.get("description") or "", "flow": flow, "created_at": int(time.time()), "updated_at": int(time.time()), "vyomiExtension": True}
                return J(200, _PF[name])
            if method == "GET":
                return J(200, {"object": "list", "data": [{k: v for k, v in f.items() if k != "flow"} | {"inputs": list((f["flow"].get("inputs") or {})), "outputs": list((f["flow"].get("outputs") or {})), "nodes": len(f["flow"]["nodes"])} for f in _PF.values()]})
        m = re.match(r"^/flows/([^/]+)(?:/(test|score))?$", path)
        if m:
            f = _PF.get(m.group(1))
            if not f:
                return am._a_err(404, "NotFound", f"Flow '{m.group(1)}' not found")
            sub = m.group(2)
            if sub in ("test", "score") and method == "POST":
                res, tr = _pf_run(arm_find, f["flow"], p.get("inputs", p) if sub == "test" else p, trace=sub == "test")
                return J(200, {"outputs": res, "trace": tr} if sub == "test" else res)
            if not sub and method == "GET":
                return J(200, f)
            if not sub and method == "PUT":
                if "flow" in p:
                    f["flow"] = _pf_validate(p["flow"])
                if "description" in p:
                    f["description"] = p["description"]
                f["updated_at"] = int(time.time())
                return J(200, f)
            if not sub and method == "DELETE":
                del _PF[f["name"]]
                return J(200, {"deleted": True, "name": f["name"]})
    except Bad as e:
        return _err(e)
    return None


def handles(path: str) -> bool:
    return bool(re.match(r"^/openai(/v1)?/(assistants|threads|responses|vector_stores|evals|conversations)(/|$)", path) or re.match(r"^/openai(/v1)?/vyomi/promptflow(/|$)", path))
