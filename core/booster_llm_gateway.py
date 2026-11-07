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
    # Remote-LLM mode (spike, core/booster_remote_llm.py): when `remote` is set, EVERY request goes to the relay's /llm plane
    # (the runner routes chat vs embeddings itself) carrying the booster session token. `remote` is a callable returning
    # (base_url, token) or None when detached. Relay-generated failures (x-vyomi-hub: 1) and connection errors are an
    # honest 503 - never a silent fallback to a local model.
    remote = None

    def log_message(self, *a):  # quiet
        pass

    def _send_json(self, code: int, obj) -> None:
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _unavailable(self, why: str, code: str = "RemoteLLMUnavailable") -> None:
        self._send_json(503, {"error": {"message": f"remote LLM runner unavailable: {why}", "type": "unavailable", "code": code}})

    def _health(self) -> None:
        if self.remote is not None:
            t = self.remote()
            if not t:
                return self._send_json(503, {"status": "detached", "chat": False, "embed": False})
            try:
                r = urllib.request.urlopen(urllib.request.Request(t[0] + "/_status", headers={"x-vyomi-session-token": t[1]}), timeout=3)
                st = json.loads(r.read()).get("runner")
            except Exception:
                st = "unreachable"
            ok = st == "ready"
            return self._send_json(200 if ok else 503, {"status": "ok" if ok else st, "chat": ok, "embed": ok})
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
        headers = {"content-type": self.headers.get("content-type", "application/json")}
        if self.remote is not None:
            t = self.remote()
            if not t:
                return self._unavailable("no runner is attached", "RemoteLLMDetached")
            up = t[0]
            headers["x-vyomi-session-token"] = t[1]
        else:
            up = route(p, self.chat_url, self.embed_url)
        if self.remote is None and up == self.embed_url and body:
            try:
                j = json.loads(body)
                j["model"] = "embed"
                body = json.dumps(j).encode()
            except Exception:
                pass
        req = urllib.request.Request(up + p, data=body, method=method, headers=headers)
        try:
            r = urllib.request.urlopen(req, timeout=TIMEOUT)
            code = r.status
        except urllib.error.HTTPError as e:
            r, code = e, e.code
            if self.remote is not None and e.headers.get("x-vyomi-hub"):        # the relay says the runner isn't there / ended
                try:
                    c = str(json.loads(e.read()).get("error", {}).get("code", "RunnerUnavailable"))[:60]
                except Exception:
                    c = "RunnerUnavailable"
                return self._unavailable(c, c)
        except Exception as e:
            if self.remote is not None:
                return self._unavailable("relay not reachable")
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


def serve(port: int = 8080, chat_url: str = CHAT_URL, embed_url: str = EMBED_URL, *, remote=None,
          host: str = "0.0.0.0") -> ThreadingHTTPServer:
    h = type("H", (Handler,), {"chat_url": chat_url.rstrip("/"), "embed_url": embed_url.rstrip("/"),
                               "remote": staticmethod(remote) if remote else None})
    return ThreadingHTTPServer((host, port), h)


if __name__ == "__main__":
    srv = serve(int(os.environ.get("PORT", "8080")))
    print(f"[booster-llm-gateway] :{srv.server_address[1]} chat={CHAT_URL} embed={EMBED_URL}", file=sys.stderr, flush=True)
    srv.serve_forever()
