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
              Only function tools; code_interpreter / file_search / vector stores are rejected; run steps return an empty list.
State is process-local (module dicts); a restart clears it.
"""
from __future__ import annotations

import json
import re
import time
import uuid

try:
    from core import llm_core as llm
except ImportError:  # Pyodide flat layout
    import llm_core as llm  # type: ignore

_RESP: dict[str, dict] = {}
_ASST: dict[str, dict] = {}
_THR: dict[str, dict] = {}


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
        if (t or {}).get("type") != "function":
            raise Bad(f"Tool type {(t or {}).get('type')!r} is not supported by the local model (only function tools).", "tools")
        if not (t.get("function") or {}).get("name"):
            raise Bad("function tools need function.name.", "tools")
    return tools or []


def _asst_view(a):
    return {k: v for k, v in a.items() if not k.startswith("_")}


def _msg_obj(thread_id, role, text, run_id=None, asst_id=None):
    return {"id": _id("msg_"), "object": "thread.message", "created_at": int(time.time()), "assistant_id": asst_id, "thread_id": thread_id,
            "run_id": run_id, "role": role, "content": [{"type": "text", "text": {"value": text, "annotations": []}}], "attachments": [],
            "metadata": {}, "status": "completed", "completed_at": int(time.time()), "incomplete_at": None, "incomplete_details": None}


def _thread_chat(t, asst, extra_instr=None):
    sysm = "\n".join(x for x in (asst.get("instructions"), extra_instr) if x)
    msgs = ([{"role": "system", "content": sysm}] if sysm else []) + [dict(m) for m in t["_chat"]]
    return msgs


def _execute_run(arm_find, t, run, asst):
    """Run the model once over the thread; mutate run + thread. Terminal status on return."""
    dep = run["model"]
    if arm_find is not None and not arm_find(dep)[1]:
        raise Bad("The API deployment for this resource does not exist.", None, 404, "DeploymentNotFound")
    body = {"messages": _thread_chat(t, asst, run.get("additional_instructions")), "tools": [{"type": "function", "function": t_["function"]} for t_ in run["tools"]]}
    if not body["tools"]:
        del body["tools"]
    if run.get("tool_choice") not in (None, "auto"):
        body["tool_choice"] = run["tool_choice"]
    for k in ("temperature", "top_p"):
        if run.get(k) is not None:
            body[k] = run[k]
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
    run["usage"] = {"prompt_tokens": r["input_tokens"], "completion_tokens": r["output_tokens"], "total_tokens": r["input_tokens"] + r["output_tokens"]}
    if r["tool_calls"]:
        am = _hist_msg(r)
        run["_pending"] = am
        run["required_action"] = {"type": "submit_tool_outputs", "submit_tool_outputs": {"tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for c in r["tool_calls"]]}}
        run["status"] = "requires_action"
        return None
    t["_chat"].append({"role": "assistant", "content": r["text"]})
    m = _msg_obj(t["id"], "assistant", r["text"], run["id"], asst["id"])
    t["_msgs"].append(m)
    run.update(status="incomplete" if r["finish_reason"] == "length" else "completed", required_action=None, completed_at=int(time.time()))
    if r["finish_reason"] == "length":
        run["incomplete_details"] = {"reason": "max_completion_tokens"}
    return m


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
                     "temperature": p.get("temperature"), "top_p": p.get("top_p"), "response_format": p.get("response_format", "auto"), "tool_resources": {}}
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
                a.update({k: v for k, v in p.items() if k in ("name", "description", "model", "instructions", "tools", "metadata", "temperature", "top_p", "response_format")})
                return J(200, _asst_view(a))
            if method == "DELETE":
                del _ASST[a["id"]]
                return J(200, {"id": a["id"], "object": "assistant.deleted", "deleted": True})
        if path == "/threads" and method == "POST":
            if p.get("tool_resources"):
                raise Bad("tool_resources (file_search / code_interpreter) are not supported by the local model.", "tool_resources")
            t = {"id": _id("thread_"), "object": "thread", "created_at": int(time.time()), "metadata": p.get("metadata") or {}, "tool_resources": {},
                 "_chat": [], "_msgs": [], "_runs": {}}
            _THR[t["id"]] = t
            for mm in p.get("messages") or []:
                _add_message(t, mm)
            return J(200, {k: v for k, v in t.items() if not k.startswith("_")})
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
        m = re.match(r"^/threads/([^/]+)/(messages|runs)(?:/([^/]+))?(?:/(submit_tool_outputs|cancel|steps))?$", path)
        if m:
            t = _THR.get(m.group(1))
            if not t:
                return nf("thread", m.group(1))
            kind, oid, sub = m.group(2), m.group(3), m.group(4)
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
                if sub == "steps" and method == "GET":
                    return J(200, {"object": "list", "data": [], "first_id": None, "last_id": None, "has_more": False})
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
    if mm.get("attachments"):
        raise Bad("attachments are not supported by the local model.", "attachments")
    obj = _msg_obj(t["id"], mm["role"], c)
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


def handles(path: str) -> bool:
    return bool(re.match(r"^/openai(/v1)?/(assistants|threads|responses)(/|$)", path))
