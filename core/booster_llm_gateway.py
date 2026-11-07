"""Tiny OpenAI-compatible gateway in front of the booster's two llama.cpp servers (stdlib only).

llama-server serves ONE model per process, but the seam (core/llm_core) talks to ONE endpoint for /v1/chat/completions AND
/v1/embeddings. This gateway is that endpoint: ``/v1/embeddings`` -> the embeddings server, everything else -> the chat
server, rewriting nothing but the ``model`` field of embeddings requests (the seam sends the chat model's name there).
Streaming responses are passed through chunk by chunk.

    python -m core.booster_llm_gateway      (env: CHAT_URL, EMBED_URL, PORT)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHAT_URL = os.environ.get("CHAT_URL", "http://llm-chat:8080").rstrip("/")
EMBED_URL = os.environ.get("EMBED_URL", "http://llm-embed:8080").rstrip("/")
TIMEOUT = float(os.environ.get("GATEWAY_TIMEOUT_S", "300"))


def route(path: str, chat_url: str, embed_url: str) -> str:
    return embed_url if path.split("?", 1)[0].rstrip("/") == "/v1/embeddings" else chat_url


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    chat_url, embed_url = CHAT_URL, EMBED_URL

    def log_message(self, *a):  # quiet
        pass

    def _send_json(self, code: int, obj) -> None:
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _health(self) -> None:
        out = {}
        for name, url in (("chat", self.chat_url), ("embed", self.embed_url)):
            try:
                urllib.request.urlopen(url + "/health", timeout=2).read()
                out[name] = True
            except Exception:
                out[name] = False
        self._send_json(200 if out["chat"] else 503, {"status": "ok" if out["chat"] else "loading", **out})

    def _proxy(self, method: str) -> None:
        p = self.path
        if p.split("?", 1)[0] in ("/health", "/healthz"):
            return self._health()
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else None
        up = route(p, self.chat_url, self.embed_url)
        if up == self.embed_url and body:
            try:
                j = json.loads(body)
                j["model"] = "embed"
                body = json.dumps(j).encode()
            except Exception:
                pass
        req = urllib.request.Request(up + p, data=body, method=method, headers={"content-type": self.headers.get("content-type", "application/json")})
        try:
            r = urllib.request.urlopen(req, timeout=TIMEOUT)
            code = r.status
        except urllib.error.HTTPError as e:
            r, code = e, e.code
        except Exception as e:
            return self._send_json(503, {"error": {"message": f"model server not reachable: {type(e).__name__}", "type": "unavailable"}})
        ctype = r.headers.get("content-type", "application/json")
        if "text/event-stream" in ctype:
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.end_headers()
            self.close_connection = True
            while True:
                chunk = r.read1(8192) if hasattr(r, "read1") else r.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
            return
        data = r.read()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")


def serve(port: int = 8080, chat_url: str = CHAT_URL, embed_url: str = EMBED_URL) -> ThreadingHTTPServer:
    h = type("H", (Handler,), {"chat_url": chat_url.rstrip("/"), "embed_url": embed_url.rstrip("/")})
    return ThreadingHTTPServer(("0.0.0.0", port), h)


if __name__ == "__main__":
    srv = serve(int(os.environ.get("PORT", "8080")))
    print(f"[booster-llm-gateway] :{srv.server_address[1]} chat={CHAT_URL} embed={EMBED_URL}", file=sys.stderr, flush=True)
    srv.serve_forever()
