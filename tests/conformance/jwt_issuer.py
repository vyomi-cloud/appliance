"""Test OIDC issuer: an RSA keypair, a stdlib HTTP server that serves /.well-known/openid-configuration + /jwks.json, and mint() for RS256 tokens."""
import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Issuer:
    def __init__(self, kid="k1"):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = kid
        n = self.key.public_key().public_numbers()
        self.jwk = {"kty": "RSA", "kid": kid, "alg": "RS256", "use": "sig", "n": _b64(n.n.to_bytes(256, "big")), "e": _b64(n.e.to_bytes(3, "big"))}
        me = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.endswith("/.well-known/openid-configuration"):
                    doc = {"issuer": me.issuer, "jwks_uri": me.issuer + "/jwks.json"}
                elif self.path.endswith("/jwks.json"):
                    doc = {"keys": [me.jwk]}
                else:
                    self.send_response(404); self.end_headers(); return
                b = json.dumps(doc).encode()
                self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b))); self.end_headers()
                self.wfile.write(b)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.issuer = f"http://127.0.0.1:{self.srv.server_address[1]}/pool"
        self.discovery_url = self.issuer + "/.well-known/openid-configuration"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def mint(self, sub="u1", key=None, iss=None, exp_in=3600, extra=None, kid=None):
        h = {"alg": "RS256", "typ": "JWT", "kid": kid or self.kid}
        now = int(time.time())
        c = {"sub": sub, "iss": iss or self.issuer, "iat": now, "exp": now + exp_in, "token_use": "access", "client_id": "app-client"}
        c.update(extra or {})
        si = _b64(json.dumps(h).encode()) + "." + _b64(json.dumps(c).encode())
        sig = (key or self.key).sign(si.encode(), padding.PKCS1v15(), hashes.SHA256())
        return si + "." + _b64(sig)
