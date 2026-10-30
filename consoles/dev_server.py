#!/usr/bin/env python3
"""v4 console dev server — no Docker, no appliance boot.

Serves the built consoles at /v4/<cloud>/ and answers /_wire/* with the SAME
core.aws_wire_router.AwsWireRouter that Nano and the appliance's unified ingress use
(in-memory stores). A fast inner loop for developing a service page and for the UI
conformance suite; final verification still runs on the real offline appliance + Nano.

    python3 consoles/dev_server.py [--port 8740]
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.aws_wire_router import AwsWireRouter  # noqa: E402
from core.azure_arm_core import AzureArm  # noqa: E402

STATIC = ROOT / "static"
ROUTER = AwsWireRouter()
# Azure ARM (/subscriptions/*) is not in AwsWireRouter. Nano sends /_wire/subscriptions/* to
# the same substrate-free AzureArm core (wasm/sw.js handleWire → the azure/_arm tuple) and the
# appliance serves it with providers/azure_services.handle_arm (which AzureArm ports), so the
# dev server does the same — the Azure lens's control plane, in-memory like the rest.
ARM = AzureArm()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _wire(self):
        u = urlsplit(self.path)
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else b""
        rest = u.path[len("/_wire"):] or "/"
        if rest.startswith("/subscriptions/") or rest.startswith("/api/azure/operations/"):
            return self._arm(rest, dict(parse_qsl(u.query, keep_blank_values=True)), body)
        try:
            out = ROUTER.handle(self.command, u.path[len("/_wire"):] or "/", dict(parse_qsl(u.query, keep_blank_values=True)),
                                {k.lower(): v for k, v in self.headers.items()}, body)
        except Exception as e:  # surface router bugs as a native-looking 500, never a dropped connection
            out = {"status": 500, "headers": {"content-type": "text/plain"}, "body": f"InternalError: {e!r}".encode()}
        data = out.get("body") or b""
        if isinstance(data, str):
            data = data.encode()
        self.send_response(int(out.get("status", 200)))
        for k, v in (out.get("headers") or {}).items():
            if k.lower() not in ("content-length", "transfer-encoding", "connection"):
                self.send_header(k, v)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _arm(self, path, query, body):
        try:
            payload = json.loads(body) if body.strip() else None
        except ValueError:
            payload = None
        try:
            out = ARM.handle(self.command, path, query, payload)
        except Exception as e:
            out = {"status": 500, "headers": {}, "body": {"error": {"code": "InternalServerError", "message": repr(e)}}}
        data = b"" if out.get("body") is None else json.dumps(out["body"]).encode()
        self.send_response(int(out.get("status", 200)))
        for k, v in (out.get("headers") or {}).items():
            self.send_header(k, v)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _static(self):
        p = urlsplit(self.path).path
        if p in ("/", "/v4", "/v4/"):
            self.send_response(302); self.send_header("location", "/v4/aws/"); self.send_header("content-length", "0"); self.end_headers(); return
        f = (STATIC / p.lstrip("/")).resolve()
        if f.is_dir():
            f = f / "index.html"
        if not str(f).startswith(str(STATIC / "v4")) or not f.is_file():
            self.send_response(404); self.send_header("content-length", "0"); self.end_headers(); return
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("content-type", mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _go(self):
        if self.path.startswith("/_wire"):
            return self._wire()
        return self._static()

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = _go

    def log_message(self, fmt, *args):
        if "-q" not in sys.argv:
            sys.stderr.write("%s %s\n" % (self.command, self.path[:120]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8740)
    ap.add_argument("-q", action="store_true")
    a = ap.parse_args()
    print(f"v4 consoles: http://127.0.0.1:{a.port}/v4/aws/   (/_wire → AwsWireRouter, in-memory)")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
