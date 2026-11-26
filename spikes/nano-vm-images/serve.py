#!/usr/bin/env python3
"""Static server for the spike (ports 8500-8599 only). Sends COOP/COEP so SharedArrayBuffer/threads work,
and does NOT gzip. Usage: serve.py PORT [ROOT]"""
import http.server, sys, os, functools
port = int(sys.argv[1]); root = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(__file__))
assert 8500 <= port <= 8599, "spike servers must use 8500-8599"
class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".wasm": "application/wasm", ".js": "text/javascript"}
    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(H, directory=root)).serve_forever()
