"""Start the real appliance app (server.py) in-process on a plain-http port and a TLS port (self-signed CA exported through
REQUESTS_CA_BUNDLE / SSL_CERT_FILE), for the Azure SDKs that refuse bearer tokens over http (azure-keyvault-*).
Returns (https_endpoint, http_endpoint, ca_file)."""
import datetime, os, socket, sys, tempfile, threading, time


def _free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def make_ca(workdir):
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.DNSName("*.vault.localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
    crt, k = os.path.join(workdir, "ca.pem"), os.path.join(workdir, "key.pem")
    open(crt, "wb").write(cert.public_bytes(serialization.Encoding.PEM))
    open(k, "wb").write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    return crt, k


def start(extra_env=None):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    work = tempfile.mkdtemp(prefix="vyomi-aztls-")
    http_port, tls_port = _free(), _free()
    os.environ.update({"CLOUDLEARN_STATE_FILE": os.path.join(work, "state.sqlite3"), "VYOMI_DATA_DIR": work, "CLOUDLEARN_TIER_ENFORCE": "0",
                       "VYOMI_AMQP_PORT": str(_free()), "VYOMI_AMQPS_PORT": "0", "VYOMI_AMQP_HOST": "127.0.0.1", "VYOMI_AZSB_DB": os.path.join(work, "azsb.sqlite"),
                       "VYOMI_SELF_ENDPOINT": f"http://127.0.0.1:{http_port}", **(extra_env or {})})
    sys.path.insert(0, root); os.chdir(root)
    ca, key = make_ca(work)
    for v in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
        os.environ[v] = ca
    import uvicorn
    import server
    servers = [uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=http_port, log_level="error")),
               uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=tls_port, log_level="error", ssl_certfile=ca, ssl_keyfile=key))]
    for s in servers:
        threading.Thread(target=s.run, daemon=True).start()
    t0 = time.time()
    while not all(s.started for s in servers):
        if time.time() - t0 > 180:
            raise SystemExit("appliance did not start")
        time.sleep(0.1)
    return f"https://localhost:{tls_port}", f"http://127.0.0.1:{http_port}", ca
