"""Start the REAL appliance app (server.py: wire ingress + /azure-data/* data planes + the Service Bus AMQP listener) inside this process, on TWO ports:
a plain-http one (the simulator's own call-backs, Function sandbox, AMQP) and a TLS one (https://localhost:<port>) for the Azure SDKs that refuse bearer
tokens over plain http (azure-identity, azure-keyvault-*, azure-monitor-query, azure-ai-agents). The TLS port serves the same app with a self-signed CA that the
harness exports through the standard variables (REQUESTS_CA_BUNDLE / SSL_CERT_FILE), exactly how a developer trusts a local dev CA. Nothing is shimmed."""
import datetime, os, socket, sys, tempfile, threading, time


def _free():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def make_ca(workdir):
    """Self-signed certificate for localhost / 127.0.0.1; the same file is the CA bundle the clients trust."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import ipaddress
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
    crt, k = os.path.join(workdir, "vyomi-local-ca.pem"), os.path.join(workdir, "vyomi-local-key.pem")
    open(crt, "wb").write(cert.public_bytes(serialization.Encoding.PEM))
    open(k, "wb").write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    return crt, k


def repo_root():
    r = os.environ.get("VYOMI_REPO") or os.path.abspath(__file__)
    while r != "/" and not os.path.exists(os.path.join(r, "core", "wire_ingress.py")):
        r = os.path.dirname(r)
    if r == "/":
        raise SystemExit("run from inside the simulator repo, or pass --endpoint https://host:port")
    return r


def start_in_process():
    """Returns (https_endpoint, http_endpoint, amqp_port, ca_file)."""
    root = repo_root()
    work = tempfile.mkdtemp(prefix="facilities-az-")
    http_port, tls_port, amqp = _free(), _free(), _free()
    os.environ.update({"CLOUDLEARN_STATE_FILE": os.path.join(work, "state.sqlite3"), "VYOMI_AZSB_DB": os.path.join(work, "azsb.sqlite"), "VYOMI_DATA_DIR": work,
                       "VYOMI_AMQP_PORT": str(amqp), "VYOMI_AMQPS_PORT": "0", "VYOMI_AMQP_HOST": "127.0.0.1", "CLOUDLEARN_TIER_ENFORCE": "0",
                       "VYOMI_SELF_ENDPOINT": f"http://127.0.0.1:{http_port}"})
    sys.path.insert(0, root)
    os.chdir(root)                                   # server.py resolves its templates / static dirs against the repo root
    ca, key = make_ca(work)
    for v in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
        os.environ[v] = ca
    import uvicorn
    import server                                    # the appliance app
    servers = [uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=http_port, log_level="error")),
               uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=tls_port, log_level="error", ssl_certfile=ca, ssl_keyfile=key))]
    for s in servers:
        threading.Thread(target=s.run, daemon=True).start()
    t0 = time.time()
    while not all(s.started for s in servers):
        if time.time() - t0 > 180:
            raise SystemExit("appliance did not start")
        time.sleep(0.1)
    time.sleep(1.0)
    return f"https://localhost:{tls_port}", f"http://127.0.0.1:{http_port}", amqp, ca
