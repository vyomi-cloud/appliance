"""Deterministic OpenAI-compatible fake model server for the seam / SDK conformance tests (a stand-in for llama-server / Ollama).

It is NOT a model: ``handler(body) -> {"content": str} | {"tool_calls": [{"name","arguments"}]}`` is scripted per test. It does
implement the wire behaviours the seam relies on: tools (or a 400 "does not support tools"), response_format (or 400),
``stream: true`` SSE with per-piece delays and a final usage chunk, ``stream_options.include_usage``, usage counts.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeLLM:
    def __init__(self, handler=None, tools_supported=True, rf_supported=True, delay=0.0, model="fake-qwen"):
        self.handler = handler or (lambda body: {"content": "pong"})
        self.tools_supported, self.rf_supported, self.delay, self.model = tools_supported, rf_supported, delay, model
        self.requests = []
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _json(self, code, doc):
                b = json.dumps(doc).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                self._json(200, {"object": "list", "data": [{"id": fake.model}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
                if self.path.endswith("/embeddings"):
                    return self._json(200, {"data": [{"embedding": [0.1, 0.2, 0.3], "index": i} for i in range(len(body["input"]) if isinstance(body.get("input"), list) else 1)], "usage": {"prompt_tokens": 3}})
                fake.requests.append(body)
                if body.get("tools") and not fake.tools_supported:
                    return self._json(400, {"error": {"message": f"{fake.model} does not support tools"}})
                if body.get("response_format") and not fake.rf_supported:
                    return self._json(400, {"error": {"message": "response_format is not supported"}})
                out = fake.handler(body)
                content, calls = out.get("content") or "", out.get("tool_calls") or []
                oa_calls = [{"id": c.get("id") or f"call_{i}", "type": "function",
                             "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for i, c in enumerate(calls)]
                ptoks = sum(len(str(m.get("content") or "")) for m in body["messages"]) // 4 + 1
                ctoks = (len(content) + sum(len(c["function"]["arguments"]) for c in oa_calls)) // 4 + 1
                fin = out.get("finish_reason") or ("tool_calls" if oa_calls else "stop")
                if not body.get("stream"):
                    msg = {"role": "assistant", "content": content or None}
                    if oa_calls:
                        msg["tool_calls"] = oa_calls
                    return self._json(200, {"model": fake.model, "choices": [{"index": 0, "finish_reason": fin, "message": msg}],
                                            "usage": {"prompt_tokens": ptoks, "completion_tokens": ctoks, "total_tokens": ptoks + ctoks}})
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("transfer-encoding", "chunked")
                self.end_headers()

                def send(doc):
                    data = ("data: " + (doc if isinstance(doc, str) else json.dumps(doc)) + "\n\n").encode()
                    self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n")
                    self.wfile.flush()
                base = {"model": fake.model, "object": "chat.completion.chunk"}
                send(dict(base, choices=[{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]))
                for i in range(0, len(content), 4):
                    time.sleep(fake.delay)
                    send(dict(base, choices=[{"index": 0, "delta": {"content": content[i:i + 4]}, "finish_reason": None}]))
                for i, c in enumerate(oa_calls):
                    send(dict(base, choices=[{"index": 0, "delta": {"tool_calls": [{"index": i, "id": c["id"], "type": "function",
                                                                                      "function": {"name": c["function"]["name"], "arguments": ""}}]}, "finish_reason": None}]))
                    a = c["function"]["arguments"]
                    for k in range(0, len(a), 5):
                        time.sleep(fake.delay)
                        send(dict(base, choices=[{"index": 0, "delta": {"tool_calls": [{"index": i, "function": {"arguments": a[k:k + 5]}}]}, "finish_reason": None}]))
                send(dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": fin}]))
                if (body.get("stream_options") or {}).get("include_usage"):
                    send(dict(base, choices=[], usage={"prompt_tokens": ptoks, "completion_tokens": ctoks, "total_tokens": ptoks + ctoks}))
                send("[DONE]")
                self.wfile.write(b"0\r\n\r\n")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
