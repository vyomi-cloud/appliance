#!/usr/bin/env python3
"""Spike: HTTPS front that lets the real azurerm provider talk to the simulator's ARM core.

azurerm (via go-azure-sdk) needs, beyond ARM itself:
  GET  /metadata/endpoints?api-version=*   -> cloud environment JSON (where login / ARM / graph live)
  POST /<tenant>/oauth2/v2.0/token         -> a bearer token (the simulator ignores the token value)
  GET  /<tenant>/v2.0/.well-known/openid-configuration, /common/discovery/instance (AAD discovery)
and TLS. Everything else is forwarded to the ARM core with the /_wire prefix.

    python3 front.py --cert cert.pem --key key.pem --port 8443 --upstream http://127.0.0.1:8740 --host host.docker.internal:8443
"""
import argparse, base64, http.client, json, ssl, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

A = argparse.ArgumentParser()
A.add_argument("--cert"); A.add_argument("--key"); A.add_argument("--port", type=int, default=8443)
A.add_argument("--upstream", default="http://127.0.0.1:8740"); A.add_argument("--prefix", default=""); A.add_argument("--host", default="localhost:8443")
ARGS = A.parse_args()
UP = urlsplit(ARGS.upstream)
BASE = f"https://{ARGS.host}"


def metadata():
    return {
        "portal": BASE, "authentication": {"loginEndpoint": BASE, "audiences": [BASE + "/", "https://management.core.windows.net/"], "tenant": "common", "identityProvider": "AAD"},
        "media": BASE, "graphAudience": BASE + "/", "graph": BASE + "/", "name": "VyomiAzure",
        "suffixes": {"azureDataLakeStoreFileSystem": "azuredatalakestore.net", "acrLoginServer": "azurecr.io", "sqlServerHostname": ".database.windows.net",
                     "azureDataLakeAnalyticsCatalogAndJob": "azuredatalakeanalytics.net", "keyVaultDns": "vault.azure.net", "storage": "core.windows.net" + (":" + ARGS.host.split(":")[1] if ":" in ARGS.host else ""),
                     "azureFrontDoorEndpointSuffix": "azurefd.net", "storageEndpointSuffix": "core.windows.net" + (":" + ARGS.host.split(":")[1] if ":" in ARGS.host else ""), "mhsmDns": "managedhsm.azure.net",
                     "attestationEndpoint": "attest.azure.net"},
        "batch": BASE + "/", "resourceManager": BASE + "/", "vmImageAliasDoc": BASE, "activeDirectoryDataLake": BASE + "/", "sqlManagement": BASE + "/",
        "microsoftGraphResourceId": BASE + "/", "appInsightsResourceId": "https://api.applicationinsights.io",
        "appInsightsTelemetryChannelResourceId": "https://dc.applicationinsights.azure.com/v2/track", "synapseAnalyticsResourceId": "https://dev.azuresynapse.net",
        "attestationResourceId": "https://attest.azure.net", "portalResourceId": BASE, "keyVaultResourceId": "https://vault.azure.net",
        "operationalInsightsResourceId": "https://api.loganalytics.io", "ossrDbmsResourceId": "https://ossrdbms-aad.database.windows.net",
        "storageResourceId": "https://storage.azure.com/",
    }


def jwt(tenant):
    """Structurally valid, unsigned JWT: azurerm reads claims (tid/oid/appid) but never verifies the signature."""
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    now = int(time.time())
    return ".".join([b({"alg": "none", "typ": "JWT"}),
                     b({"aud": BASE + "/", "iss": f"https://sts.windows.net/{tenant}/", "iat": now, "nbf": now, "exp": now + 3600,
                        "tid": tenant, "oid": "00000000-0000-0000-0000-0000000000bb", "appid": "00000000-0000-0000-0000-0000000000bb", "idtyp": "app"}),
                     "c2ln"])


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, fmt, *a): sys.stderr.write("front %s %s\n" % (self.command, self.path))

    def _send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(data)

    def _do(self):
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n) if n else b""
        p = urlsplit(self.path).path
        if p.startswith("/metadata/endpoints"): return self._send(200, metadata())
        if p.endswith("/oauth2/v2.0/token") or p.endswith("/oauth2/token"):
            return self._send(200, {"token_type": "Bearer", "expires_in": 3600, "ext_expires_in": 3600, "access_token": jwt(p.split("/")[1] if "/oauth2/" in p and p.count("/")>2 else "common")})
        if p.endswith("/openid-configuration"):
            t = p.split("/")[1]
            return self._send(200, {"token_endpoint": f"{BASE}/{t}/oauth2/v2.0/token", "authorization_endpoint": f"{BASE}/{t}/oauth2/v2.0/authorize",
                                    "issuer": f"{BASE}/{t}/v2.0", "tenant_region_scope": "NA"})
        if "/discovery/instance" in p:
            return self._send(200, {"tenant_discovery_endpoint": f"{BASE}/common/v2.0/.well-known/openid-configuration", "api-version": "1.1", "metadata": []})
        c = http.client.HTTPConnection(UP.hostname, UP.port, timeout=120)
        hdrs = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection")}
        hdrs["Host"] = self.headers.get("Host") or ARGS.host; hdrs["X-Forwarded-Proto"] = "https"   # the simulator builds vaultUri / Location / endpoints from these
        c.request(self.command, ARGS.prefix + self.path, body, hdrs)
        r = c.getresponse(); data = r.read()
        if r.status >= 400: sys.stderr.write("front-ERR %s %s%s -> %s %s\n" % (self.command, self.headers.get("Host","")[:40], self.path, r.status, data[:160]))
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() in ("transfer-encoding", "connection", "content-length"): continue
            if k.lower() in ("azure-asyncoperation", "location"): v = v.replace(f"{UP.scheme}://{UP.netloc}{ARGS.prefix}", BASE).replace(ARGS.prefix or "\0", "")
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _do


ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(ARGS.cert, ARGS.key)
class Srv(ThreadingHTTPServer):
    request_queue_size = 512      # the default backlog of 5 refused connections under terraform's parallelism
    daemon_threads = True


srv = Srv(("0.0.0.0", ARGS.port), H); srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
print(f"front on {BASE} -> {ARGS.upstream}", flush=True); srv.serve_forever()
