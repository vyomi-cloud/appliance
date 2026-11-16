"""DETERMINISTIC TEST STUB for the local-LLM seam. NOT A MODEL. Used only so CI / the reference app can exercise
Converse / ConverseStream / InvokeModel / tool-use / RetrieveAndGenerate with no 2 GB model download.

Speaks the OpenAI-compatible subset core/llm_core.py uses (GET /v1/models, GET /health, POST /v1/chat/completions incl. stream,
tools/tool_calls, response_format, POST /v1/embeddings). Point the simulator at it with:  VYOMI_LLM_ENDPOINT=http://127.0.0.1:<port>

Behaviour is rule-based and labelled: model name is "vyomi-stub-llm (deterministic test stub)". It never claims capability: it
extracts, it does not reason. Real replacements (same seam, no code change): Mesh = llama.cpp Qwen2.5-3B Q4 at vyomi-llm:8080,
Nano = WebLLM registered through llm.set_async_backend.

Run standalone:  python tools/llm_stub/stub_llm_server.py [port]      In-process:  start() -> base url
"""
import hashlib
import json
import math
import re
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "vyomi-stub-llm (deterministic test stub)"
_ROUTES = (("maintenance", r"[A-Z]{1,3}-\d+|work order|status|ticket|asset|repair"),
           ("analytics", r"how many|count|summary|report|trend|open work orders"))


def _text(m):
    c = m.get("content")
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c or ""


def _tokens(s):
    return max(1, len(s) // 4)


def _example(schema):
    """Smallest value valid for a JSON schema."""
    t = (schema or {}).get("type")
    if "enum" in (schema or {}):
        return schema["enum"][0]
    if t == "object":
        return {k: _example(v) for k, v in (schema.get("properties") or {}).items() if k in (schema.get("required") or [])}
    if t == "array":
        return [_example(schema.get("items") or {})]
    return {"integer": 0, "number": 0, "boolean": True}.get(t, "stub")


def _fill_args(tool, user):
    """Deterministic argument extraction from the user text: ids like B-12 go to *id args, else the whole text to the first string arg."""
    params = (tool.get("parameters") or {})
    out = {}
    ident = re.search(r"\b([A-Z]{1,3}-\d+)\b", user)
    for k, v in (params.get("properties") or {}).items():
        if k in (params.get("required") or []) or True:
            if v.get("type") in ("integer", "number"):
                out[k] = 3 if k in ("top_k", "limit") else 1
            elif k.endswith("id") and ident:
                out[k] = ident.group(1)
            elif v.get("type", "string") == "string":
                out[k] = (ident.group(1) if ident and "id" in k else user[:200])
            else:
                out[k] = _example(v)
    return {k: v for k, v in out.items() if k in (params.get("required") or []) or k in ("query",)} or out


def _pick_tool(tools, user, forced):
    if forced:
        for t in tools:
            if t["function"]["name"] == forced:
                return t["function"]
    words = set(re.findall(r"[a-z]+", user.lower()))
    best = max(tools, key=lambda t: len(words & set(re.findall(r"[a-z]+", (t["function"]["name"] + " " + (t["function"].get("description") or "")).lower()))))
    return best["function"]


def decide(body):
    """-> (text, tool_calls). The whole 'model'."""
    msgs = body.get("messages") or []
    user = next((_text(m) for m in reversed(msgs) if m.get("role") == "user"), "")
    system = next((_text(m) for m in msgs if m.get("role") == "system"), "")
    tools, choice = body.get("tools") or [], body.get("tool_choice")
    last = msgs[-1] if msgs else {}
    if tools and choice != "none" and last.get("role") != "tool":
        forced = choice["function"]["name"] if isinstance(choice, dict) else None
        fn = _pick_tool(tools, user, forced)
        return "", [{"id": "call_" + uuid.uuid4().hex[:24], "type": "function",
                     "function": {"name": fn["name"], "arguments": json.dumps(_fill_args(fn, user))}}]
    if last.get("role") == "tool":
        return "Tool result received: " + _text(last)[:300], []
    rf = body.get("response_format") or {}
    if rf.get("type") == "json_schema":
        return json.dumps(_example((rf.get("json_schema") or {}).get("schema") or {})), []
    if rf.get("type") == "json_object":
        return "{}", []
    if "route" in system.lower() and "json list" in system.lower():
        plan = ["facilities"] + [n for n, rx in _ROUTES if re.search(rx, user, re.I if n == "analytics" else 0) or re.search(rx, user.lower())]
        return json.dumps(plan), []
    m = re.search(r"Context:\s*(.*?)\s*(?:\n\s*)?Question:", user, re.S)
    if m or "Search results" in user:
        ctx = (m.group(1) if m else user).strip()
        first = re.sub(r"^\[\d+\]\s*", "", ctx.splitlines()[0] if ctx else "")
        return (first[:400] + " [1]").strip(), []
    if re.search(r"single word OK", user, re.I):
        return "OK", []
    return "Stub model reply (deterministic): " + user[:120], []


def _vec(text, dim=768):
    v = [0.0] * dim
    toks = re.findall(r"[a-z0-9]+", text.lower())
    for f in toks + [a + "_" + b for a, b in zip(toks, toks[1:])]:
        h = int(hashlib.md5(f.encode()).hexdigest(), 16)
        v[h % dim] += 1.0 if (h >> 64) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class _H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, doc, ctype="application/json"):
        b = doc if isinstance(doc, bytes) else json.dumps(doc).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            return self._send(200, {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "vyomi-test-stub"}]})
        if self.path.startswith("/health"):
            return self._send(200, {"status": "ok", "stub": True})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        if self.path.startswith("/v1/embeddings"):
            inp = body.get("input")
            inp = [inp] if isinstance(inp, str) else inp or []
            return self._send(200, {"object": "list", "model": MODEL, "data": [{"object": "embedding", "index": i, "embedding": _vec(t)} for i, t in enumerate(inp)],
                                    "usage": {"prompt_tokens": sum(_tokens(t) for t in inp), "total_tokens": sum(_tokens(t) for t in inp)}})
        if not self.path.startswith("/v1/chat/completions"):
            return self._send(404, {"error": "not found"})
        text, calls = decide(body)
        pt = _tokens(json.dumps(body.get("messages")))
        usage = {"prompt_tokens": pt, "completion_tokens": _tokens(text + json.dumps(calls)), "total_tokens": 0}
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        fin = "tool_calls" if calls else "stop"
        cid = "chatcmpl-" + uuid.uuid4().hex[:12]
        if not body.get("stream"):
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            return self._send(200, {"id": cid, "object": "chat.completion", "created": int(time.time()), "model": MODEL,
                                    "choices": [{"index": 0, "message": msg, "finish_reason": fin}], "usage": usage})
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()

        def ev(delta, f=None, u=None):
            d = {"id": cid, "object": "chat.completion.chunk", "model": MODEL, "choices": [{"index": 0, "delta": delta, "finish_reason": f}]}
            if u:
                d["usage"] = u
            self.wfile.write(b"data: " + json.dumps(d).encode() + b"\n\n")
        for i in range(0, len(text), 12):
            ev({"content": text[i:i + 12]})
        for i, c in enumerate(calls):
            ev({"tool_calls": [{"index": i, "id": c["id"], "type": "function", "function": {"name": c["function"]["name"], "arguments": ""}}]})
            ev({"tool_calls": [{"index": i, "function": {"arguments": c["function"]["arguments"]}}]})
        ev({}, fin, usage)
        self.wfile.write(b"data: [DONE]\n\n")


def start(port=0):
    """Start in a daemon thread; returns the base url (use as VYOMI_LLM_ENDPOINT)."""
    if not port:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}"


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"vyomi-stub-llm (TEST STUB, not a model) on http://127.0.0.1:{p}")
    ThreadingHTTPServer(("127.0.0.1", p), _H).serve_forever()
