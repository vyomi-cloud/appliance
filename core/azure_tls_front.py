"""An HTTPS listener for the Azure clients that refuse plain http (offline / Mesh only; Nano never starts it).

``azure-identity`` / ``msal`` raise ``ValueError: authority ... must use https`` for a non-TLS authority, and several data-plane SDKs
(azure-keyvault-*, azure-search-documents, azure-monitor-query, azure-servicebus management) hard-code https. This module is NOT a new
backend: it serves the SAME ASGI app (``server.app``) a second time on a TLS port with a generated self-signed certificate, so every
route (Entra token / OIDC / JWKS, Key Vault, Search, ...) answers on https too, from the one engine.

Start: ``VYOMI_AZURE_TLS_PORT=<port>`` (0 = any free port), or ``VYOMI_AZURE_TLS=1`` (port 9443) or ``VYOMI_AZURE_REAL_BACKENDS=1``;
otherwise nothing starts and nothing changes. ``server.py`` calls ``maybe_start(app)`` once the app is built. Optional cert:
``VYOMI_AZURE_TLS_CERT`` / ``_KEY`` (PEM paths); extra SANs: ``VYOMI_AZURE_TLS_HOSTS=a.example,b.example``.

Contract for clients (also served at ``GET /_vyomi/azure-tls``):
    VYOMI_AZURE_TLS_ENDPOINT = https://localhost:<port>
    VYOMI_AZURE_TLS_CA       = PEM file of the serving certificate. Trust it with ``REQUESTS_CA_BUNDLE=<ca>`` (msal/azure-identity/azure-core
                               requests transport) or ``connection_verify=<ca>`` on the credential/client, ``SSL_CERT_FILE=<ca>`` for stdlib.
    Entra:  ClientSecretCredential(tenant, client_id, secret, authority="https://localhost:<port>", disable_instance_discovery=True)
            (the authority must carry the scheme: a bare "host:port" is mis-parsed as a URL scheme)
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import threading
import time

_log = logging.getLogger("vyomi.azuretls")
_info: dict = {}
_server = None


def _truthy(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def wanted() -> bool:
    return bool(os.environ.get("VYOMI_AZURE_TLS_PORT", "").strip()) or _truthy(os.environ.get("VYOMI_AZURE_TLS")) \
        or _truthy(os.environ.get("VYOMI_AZURE_REAL_BACKENDS"))


def _self_signed(dirpath: str):
    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.timezone.utc)
        sans = [x509.DNSName(h) for h in ("localhost", "host.docker.internal")]
        sans += [x509.DNSName(h.strip()) for h in os.environ.get("VYOMI_AZURE_TLS_HOSTS", "").split(",") if h.strip()]
        sans += [x509.IPAddress(ipaddress.ip_address("127.0.0.1")), x509.IPAddress(ipaddress.ip_address("::1"))]
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=365))
                .add_extension(x509.SubjectAlternativeName(sans), critical=False)
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        c, k = os.path.join(dirpath, "azure-front.crt"), os.path.join(dirpath, "azure-front.key")
        open(c, "wb").write(cert.public_bytes(serialization.Encoding.PEM))
        open(k, "wb").write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        return c, k
    except Exception:  # noqa: BLE001
        return None


def maybe_start(app) -> int:
    """Serve ``app`` on a TLS port when wanted(); returns the bound port or 0. Never raises (appliance boot must not break)."""
    global _server
    if sys.platform == "emscripten" or _server is not None:
        return _info.get("port", 0) if _server is not None else 0
    if not wanted():
        return 0
    try:
        import socket
        import uvicorn
        cert, key = os.environ.get("VYOMI_AZURE_TLS_CERT", ""), os.environ.get("VYOMI_AZURE_TLS_KEY", "")
        if not (cert and key):
            pair = _self_signed(tempfile.mkdtemp(prefix="vyomi-aztls-"))
            if not pair:
                raise RuntimeError("cannot generate a certificate (cryptography missing)")
            cert, key = pair
        want = os.environ.get("VYOMI_AZURE_TLS_PORT", "").strip()
        port = int(want) if want else 9443
        if port == 0:
            s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        host = os.environ.get("VYOMI_AZURE_TLS_HOST", "0.0.0.0")
        cfg = uvicorn.Config(app, host=host, port=port, log_level="error", ssl_certfile=cert, ssl_keyfile=key, lifespan="off")
        _server = uvicorn.Server(cfg)
        threading.Thread(target=_server.run, daemon=True, name="azure-tls-front").start()
        t0 = time.time()
        while not _server.started and time.time() - t0 < 10:
            time.sleep(0.05)
        _info.update(port=port, endpoint=f"https://localhost:{port}", ca=cert)
        os.environ["VYOMI_AZURE_TLS_ENDPOINT"], os.environ["VYOMI_AZURE_TLS_CA"] = _info["endpoint"], cert
        _log.info("Azure TLS front on :%s", port)
        return port
    except Exception as exc:  # noqa: BLE001
        _server = None
        _log.warning("Azure TLS front not started: %s", exc)
        return 0


def discovery() -> dict:
    if not _info:
        return {"enabled": False}
    try:
        pem = open(_info["ca"]).read()
    except OSError:
        pem = ""
    return {"enabled": True, "endpoint": _info["endpoint"], "port": _info["port"], "ca_pem": pem,
            "authority": _info["endpoint"]}
