#!/usr/bin/env python3
"""Spike helper: plain-HTTP forwarder that prepends /_wire so Terraform/SDK clients that expect the service at the
root reach consoles/dev_server.py (which serves the shared wire router under /_wire).
    python3 wire_front.py --port 8741 --upstream http://127.0.0.1:8740"""
import argparse, http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
A = argparse.ArgumentParser(); A.add_argument("--port", type=int, default=8741); A.add_argument("--upstream", default="http://127.0.0.1:8740")
ARGS = A.parse_args(); UP = urlsplit(ARGS.upstream)

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, f, *a): print(self.command, self.path, flush=True)
    def _do(self):
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n) if n else b""
        c = http.client.HTTPConnection(UP.hostname, UP.port, timeout=120)
        c.request(self.command, "/_wire" + self.path, body, {k: v for k, v in self.headers.items() if k.lower() not in ("connection",)})
        r = c.getresponse(); d = r.read(); self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() not in ("transfer-encoding", "connection", "content-length"): self.send_header(k, v)
        self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _do
ThreadingHTTPServer(("0.0.0.0", ARGS.port), H).serve_forever()
