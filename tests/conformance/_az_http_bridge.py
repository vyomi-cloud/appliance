"""In-process HTTP bridge: serves AwsWireRouter on 127.0.0.1 so REAL Azure SDK clients (azure-storage-queue, azure-cosmos,
azure-mgmt-*, azure-appconfiguration, azure-data-tables) can talk to the simulator wire in tests."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qsl

from core.aws_wire_router import AwsWireRouter


def start(router=None):
    router = router or AwsWireRouter()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _do(self):
            u = urlsplit(self.path)
            n = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(n) if n else b""
            hdrs = {k.lower(): v for k, v in self.headers.items()}
            q = dict(parse_qsl(u.query, keep_blank_values=True))
            r = router.handle(self.command, u.path + (("?" + u.query) if u.query else ""), q, hdrs, body)
            out = r.get("body") or b""
            if isinstance(out, str):
                out = out.encode()
            self.send_response(r.get("status", 200))
            sent = set()
            for k, v in (r.get("headers") or {}).items():
                if k.lower() in ("content-length", "transfer-encoding", "connection"):
                    continue
                self.send_header(k, str(v)); sent.add(k.lower())
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(out)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _do

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return router, srv, f"http://127.0.0.1:{srv.server_address[1]}"


def header_transport(extra):
    """An azure-core transport that adds `extra` headers to every request (the simulator's routing hints)."""
    from azure.core.pipeline.transport import RequestsTransport

    class T(RequestsTransport):
        def send(self, request, **kw):
            for k, v in extra.items():
                request.headers[k] = v
            return super().send(request, **kw)
    return T()
