#!/usr/bin/env python3
"""Tiny OpenAI-compatible stub for UI smokes (the real offline backend is llama.cpp): /v1/models + /v1/chat/completions.
Not a fake model for product use - only lets a smoke exercise the console against the real wire without a 270 MB model.
    python3 consoles/tests/llm_stub.py 9072
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, doc):
        b = json.dumps(doc).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        self._send(200, {"data": [{"id": "stub"}]}) if self.path.startswith("/v1/models") else self._send(404, {})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path.startswith("/v1/chat/completions"):
            last = (body.get("messages") or [{}])[-1].get("content", "")
            self._send(200, {"model": "stub", "choices": [{"message": {"content": "STUB ANSWER: " + last[-80:].replace("\n", " ")}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 7, "completion_tokens": 5}})
        else:
            self._send(404, {})


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
