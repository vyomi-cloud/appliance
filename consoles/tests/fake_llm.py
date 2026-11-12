#!/usr/bin/env python3
"""TEST DOUBLE for the local LLM container: a tiny OpenAI-compatible /v1/chat/completions + /v1/embeddings server so the playground
smokes exercise the real HTTP seam of core/llm_core. It answers deterministically ("pong: <last user message>"); it is not a model.
    python3 consoles/tests/fake_llm.py 9076   then   VYOMI_LLM_ENDPOINT=http://127.0.0.1:9076 python3 consoles/dev_server.py --port 9075"""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, doc):
        b = json.dumps(doc).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._send({"object": "list", "data": [{"id": "fake-smol"}]})

    def do_POST(self):
        p = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        if self.path.endswith("/embeddings"):
            return self._send({"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}], "usage": {"prompt_tokens": 3}})
        last = next((m["content"] for m in reversed(p.get("messages", [])) if m.get("role") == "user"), "")
        last = last if isinstance(last, str) else json.dumps(last)
        self._send({"model": "fake-smol", "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "pong: " + last}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 9076), H).serve_forever()
