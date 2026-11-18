"""Real Cloud Functions execution.

Runs an uploaded function's source in a sandboxed subprocess with the declared
runtime, invoking the entry point with the request payload and returning the real
result + stdout logs (timeout-enforced). This lets a user deploy actual code and
have invocations execute it, instead of a canned response.

Python is always available (it backs the simulator); Node is used when a `node`
binary is on PATH. Unknown runtimes degrade to a clear error result.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

_RESULT_MARKER = "__CLOUDLEARN_FN_RESULT__"

from core import function_shims as _shims

_PY_HARNESS = '''
import json, importlib.util, sys, os
spec = importlib.util.spec_from_file_location("user_function", os.path.join(os.path.dirname(__file__), "main.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
fn = getattr(mod, {entry!r}, None)
if fn is None:
    raise SystemExit("Entry point %r not found in function source" % {entry!r})
event = json.loads({event!r})
result = fn(event)
sys.stdout.write("\\n" + {marker!r} + json.dumps(result, default=str))
'''

_NODE_HARNESS = '''
const path = require('path');
const mod = require(path.join(__dirname, 'main.js'));
const fn = mod[{entry}] || (typeof mod === 'function' ? mod : null);
if (!fn) {{ console.error('Entry point ' + {entry} + ' not found'); process.exit(1); }}
const event = JSON.parse({event});
Promise.resolve(fn(event)).then(r => {{
  process.stdout.write("\\n" + {marker} + JSON.stringify(r === undefined ? null : r));
}}).catch(e => {{ console.error(String(e && e.stack || e)); process.exit(1); }});
'''


def _parse(stdout: str) -> tuple:
    if _RESULT_MARKER in stdout:
        logs, _, payload = stdout.rpartition(_RESULT_MARKER)
        try:
            return json.loads(payload), logs.strip()
        except Exception:
            return payload.strip(), logs.strip()
    return None, stdout.strip()


def _run(cmd: list[str], cwd: str, timeout: int, env: dict[str, str] | None = None) -> dict:
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=run_env)
    except subprocess.TimeoutExpired:
        return {"status": "ERROR", "error": f"Function timed out after {timeout}s", "logs": "", "result": None}
    if proc.returncode != 0:
        return {"status": "ERROR", "error": (proc.stderr or "execution failed").strip()[:2000],
                "logs": (proc.stdout or "").strip()[:4000], "result": None}
    result, logs = _parse(proc.stdout or "")
    return {"status": "SUCCESS", "result": result, "logs": logs[:4000]}


def execute(code: str, entry_point: str, runtime: str, event: dict, timeout: int = 30, env: dict[str, str] | None = None) -> dict:
    """Execute the function source and return {status, result, logs[, error]}.

    *env* — optional mapping of environment variables injected into the
    subprocess (merged on top of the current process environment).
    """
    code = code or ""
    entry_point = entry_point or "handler"
    runtime = str(runtime or "python").lower()
    event_json = json.dumps(event if isinstance(event, (dict, list)) else {})
    if not code.strip():
        return {"status": "ERROR", "error": "No function source uploaded — deploy code to enable execution.",
                "logs": "", "result": None}

    workdir = tempfile.mkdtemp(prefix="cl-fn-")
    try:
        if runtime.startswith("python"):
            with open(os.path.join(workdir, "main.py"), "w") as fh:
                fh.write(code)
            harness = _PY_HARNESS.format(entry=entry_point, event=event_json, marker=_RESULT_MARKER)
            with open(os.path.join(workdir, "_run.py"), "w") as fh:
                fh.write(harness)
            return _run([sys.executable, os.path.join(workdir, "_run.py")], workdir, timeout, env=env)
        if runtime.startswith("node") or runtime.startswith("nodejs"):
            node = shutil.which("node")
            if not node:
                return {"status": "ERROR", "error": "Node runtime not available in this build.",
                        "logs": "", "result": None}
            with open(os.path.join(workdir, "main.js"), "w") as fh:
                fh.write(code)
            harness = _NODE_HARNESS.format(entry=json.dumps(entry_point), event=json.dumps(event_json), marker=json.dumps(_RESULT_MARKER))
            with open(os.path.join(workdir, "_run.js"), "w") as fh:
                fh.write(harness)
            return _run([node, os.path.join(workdir, "_run.js")], workdir, timeout, env=env)
        return {"status": "ERROR", "error": f"Runtime {runtime!r} not supported for execution.",
                "logs": "", "result": None}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ── HTTP / CloudEvent invocation (the real Cloud Functions contract) ─────────────────────────────
# HTTP functions get a Flask-like `request` and their return value IS the HTTP response (body, status,
# headers as the handler returned them); event functions get a CloudEvent. Runs in the same
# subprocess-per-call sandbox as execute() (temp dir, timeout, no state kept between calls).







# ── the function sandbox (GCP wire path): identity, network allow-list, filesystem confinement ───────
# Runs INSIDE the function's own subprocess, before user code is imported:
#   * a loopback metadata server (the one google-auth reaches via GCE_METADATA_HOST) answers with THIS function's project /
#     service account / token / ID token, so `google.auth.default()` works exactly as on Cloud Functions;
#   * sockets (Python level) and grpc channels may only reach loopback + the simulator endpoint: no arbitrary internet;
#   * a PEP 578 audit hook confines file access (reads: the interpreter + site-packages + the function dir; writes: the function
#     dir only) and denies spawning processes / loading libraries from outside the interpreter.
# This is a guard-rail, not a VM: native code that bypasses the interpreter (a malicious C extension) is not contained.
# Run hostile code on the Pro container runtime instead.
_GUARD_SRC = r"""
import sys, os, json, socket, threading, base64, time, ipaddress

def _install_guard(cfg):
    import http.server, urllib.parse
    workdir = os.path.realpath(cfg["workdir"])
    allowed_hosts = {h.lower() for h in cfg.get("hosts", [])} | {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    deny = lambda m: (_ for _ in ()).throw(PermissionError(m))

    def host_ok(h):
        h = (h or "").strip("[]").lower()
        if h in allowed_hosts or h == "":
            return True
        try:
            return ipaddress.ip_address(h).is_loopback
        except ValueError:
            return False

    # ---- loopback metadata server: this function's identity ----
    ident = cfg.get("identity") or {}
    def _jwt(aud):
        now = int(time.time())
        b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
        return b({"alg": "none", "typ": "JWT"}) + "." + b({"iss": "https://accounts.google.com", "aud": aud, "azp": ident["sub"],
            "sub": ident["sub"], "email": ident["email"], "email_verified": True, "iat": now, "exp": now + 3600}) + "."
    class _MD(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"
        def log_message(self, *a): pass
        def _send(self, code, body, ctype="text/plain"):
            b = body if isinstance(body, bytes) else (json.dumps(body) if isinstance(body, (dict, list)) else str(body)).encode()
            self.send_response(code); self.send_header("Metadata-Flavor", "Google"); self.send_header("Content-Type", ctype if not isinstance(body, (dict, list)) else "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def do_GET(self):
            u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query); p = u.path
            if self.headers.get("Metadata-Flavor") != "Google" and p != "/":
                return self._send(403, "Missing required header Metadata-Flavor:Google")
            if p == "/":
                return self._send(200, "computeMetadata/\n")
            sa = "/computeMetadata/v1/instance/service-accounts/"
            em = ident["email"]
            tbl = {"/computeMetadata/v1/project/project-id": ident["project"], "/computeMetadata/v1/project/numeric-project-id": ident["number"],
                   "/computeMetadata/v1/instance/region": "projects/%s/regions/%s" % (ident["number"], ident["region"]),
                   "/computeMetadata/v1/instance/zone": "projects/%s/zones/%s-1" % (ident["number"], ident["region"]),
                   "/computeMetadata/v1/instance/id": ident["instance_id"], "/computeMetadata/v1/instance/hostname": ident["hostname"]}
            if p in tbl:
                return self._send(200, tbl[p])
            if p.rstrip("/") == sa.rstrip("/"):
                return self._send(200, {"default": {"aliases": ["default"], "email": em, "scopes": ident["scopes"]}, em: {"aliases": ["default"], "email": em, "scopes": ident["scopes"]}} if q.get("recursive") else "default/\n%s/\n" % em)
            for who in ("default", em):
                base = sa + who
                if p.rstrip("/") == base:
                    return self._send(200, {"aliases": ["default"], "email": em, "scopes": ident["scopes"]} if q.get("recursive") else "aliases\nemail\nidentity\nscopes\ntoken\n")
                if p == base + "/email": return self._send(200, em)
                if p == base + "/scopes": return self._send(200, "\n".join(ident["scopes"]) + "\n")
                if p == base + "/aliases": return self._send(200, "default\n")
                if p == base + "/token":
                    return self._send(200, {"access_token": ident["token"], "expires_in": 3599, "token_type": "Bearer"})
                if p == base + "/identity":
                    return self._send(200, _jwt((q.get("audience") or [""])[0]))
            self._send(404, "not found")
    if cfg.get("identity"):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MD)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ["GCE_METADATA_HOST"] = "127.0.0.1:%d" % srv.server_address[1]
        os.environ["GCE_METADATA_IP"] = os.environ["GCE_METADATA_HOST"]

    # ---- Azure managed identity (App Service / Functions MSI endpoint: IDENTITY_ENDPOINT + IDENTITY_HEADER) ----
    az = cfg.get("azure_identity")
    if az:
        def _az_jwt(res):
            now = int(time.time())
            b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
            return b({"alg": "none", "typ": "JWT"}) + "." + b({"aud": res, "iss": "https://sts.windows.net/%s/" % az["tenant"], "iat": now, "nbf": now,
                "exp": now + 86400, "appid": az["client_id"], "appidacr": "2", "idp": "https://sts.windows.net/%s/" % az["tenant"], "oid": az["principal"],
                "sub": az["principal"], "tid": az["tenant"], "idtyp": "app", "xms_mirid": az.get("resource_id", "")}) + "."
        class _MSI(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"
            def log_message(self, *a): pass
            def do_GET(self):
                u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
                if self.headers.get("X-IDENTITY-HEADER") != az["header"] and self.headers.get("secret") != az["header"]:
                    b = json.dumps({"statusCode": 401, "message": "missing or invalid X-IDENTITY-HEADER"}).encode(); code = 401
                else:
                    res = (q.get("resource") or q.get("resource_uri") or ["https://management.azure.com/"])[0]
                    b = json.dumps({"access_token": _az_jwt(res), "expires_on": str(int(time.time()) + 86400), "resource": res, "token_type": "Bearer",
                                    "client_id": az["client_id"]}).encode(); code = 200
                self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
                self.end_headers(); self.wfile.write(b)
        msrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MSI)
        threading.Thread(target=msrv.serve_forever, daemon=True).start()
        os.environ["IDENTITY_ENDPOINT"] = "http://127.0.0.1:%d/msi/token" % msrv.server_address[1]
        os.environ["MSI_ENDPOINT"] = os.environ["IDENTITY_ENDPOINT"]
        os.environ["IDENTITY_HEADER"] = az["header"]
        os.environ["MSI_SECRET"] = az["header"]

    # ---- network allow-list ----
    _real_connect, _real_gai = socket.socket.connect, socket.getaddrinfo
    def _addr_host(a):
        return a[0] if isinstance(a, tuple) and a else None
    def _connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6) and not host_ok(_addr_host(address)):
            raise PermissionError("network egress to %s is blocked in the function sandbox (only the simulator endpoint and localhost are reachable)" % (_addr_host(address),))
        return _real_connect(self, address)
    def _connect_ex(self, address):
        try:
            return _connect(self, address) or 0
        except PermissionError:
            return 13
    def _gai(host, *a, **k):
        if host is not None and not host_ok(host if isinstance(host, str) else host.decode()):
            raise socket.gaierror(socket.EAI_NONAME, "name resolution for %s is blocked in the function sandbox" % (host,))
        return _real_gai(host, *a, **k)
    def _sendto(self, data, *a):
        addr = a[-1] if a else None
        if self.family in (socket.AF_INET, socket.AF_INET6) and addr is not None and not host_ok(_addr_host(addr)):
            raise PermissionError("network egress is blocked in the function sandbox")
        return _real_sendto(self, data, *a)
    _real_sendto = socket.socket.sendto
    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo, socket.socket.sendto = _connect, _connect_ex, _gai, _sendto
    try:                                   # grpc opens native sockets: guard channel creation instead
        import grpc
        def _tgt(t):
            h = str(t).split("://", 1)[-1].rsplit(":", 1)[0].strip("[]")
            if not host_ok(h):
                raise PermissionError("grpc egress to %s is blocked in the function sandbox" % h)
        for nm in ("insecure_channel", "secure_channel"):
            def _mk(orig):
                def _w(target, *a, **k):
                    _tgt(target); return orig(target, *a, **k)
                return _w
            setattr(grpc, nm, _mk(getattr(grpc, nm)))
    except ImportError:
        pass

    # ---- filesystem + process confinement (audit hook; cannot be removed once installed) ----
    import sysconfig
    ro = {workdir, "/dev/null", "/dev/urandom", "/dev/random", "/dev/zero", "/dev/tty",
          "/etc/ssl", "/etc/pki", "/usr/lib/ssl", "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf", "/etc/localtime", "/etc/mime.types",
          "/usr/share/zoneinfo", "/usr/share/ca-certificates", "/etc/ca-certificates", "/etc/gai.conf", "/etc/host.conf",
          "/proc/self", "/proc/cpuinfo", "/proc/meminfo", "/sys/devices/system/cpu", "/System", "/usr/lib", "/usr/share/zoneinfo.default",
          "/Library/Frameworks", "/private/etc/ssl", "/private/etc/hosts", "/private/etc/resolv.conf", "/private/etc/localtime"}
    for x in (sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix, *sys.path, *[v for v in sysconfig.get_paths().values()]):
        if x and os.path.isabs(str(x)):
            ro.add(os.path.realpath(str(x)))
    try:
        import certifi
        ro.add(os.path.dirname(os.path.realpath(certifi.where())))
    except Exception:
        pass
    ro = tuple(sorted(r.rstrip("/") or "/" for r in ro))
    rw = (workdir, "/dev/null", "/dev/tty")
    def under(p, roots):
        return any(p == r or p.startswith(r + os.sep) for r in roots)
    def norm(p):
        if isinstance(p, int) or p is None:
            return None
        if isinstance(p, bytes):
            p = os.fsdecode(p)
        return os.path.realpath(os.path.join(workdir, str(p)) if not os.path.isabs(str(p)) else str(p))
    WRITE_EV = {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.truncate", "os.symlink", "os.link", "os.utime", "os.mkfifo", "os.mknod", "shutil.copyfile", "shutil.move", "shutil.rmtree", "os.setxattr", "os.removexattr"}
    READ_EV = {"os.listdir", "os.scandir", "os.chdir", "os.walk", "glob.glob", "shutil.copytree"}
    DENY_EV = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty", "os.kill", "os.killpg", "pty.spawn", "os.startfile", "webbrowser.open"}
    def hook(ev, args):
        if ev == "open":
            path, mode, flags = args
            n = norm(path)
            if n is None:
                return
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if not under(n, rw if writing else ro):
                raise PermissionError("%s of %s is blocked in the function sandbox" % ("write" if writing else "read", path))
        elif ev in WRITE_EV or ev in READ_EV:
            for a in args[:2]:
                if isinstance(a, (str, bytes)) and (not isinstance(a, str) or "/" in a or a):
                    n = norm(a)
                    if n and not under(n, rw if ev in WRITE_EV else ro):
                        raise PermissionError("%s %s is blocked in the function sandbox" % (ev, a))
        elif ev in DENY_EV:
            raise PermissionError("%s is blocked in the function sandbox" % ev)
        elif ev == "ctypes.dlopen":
            n = norm(args[0]) if args and isinstance(args[0], (str, bytes)) and os.path.isabs(os.fsdecode(args[0])) else None
            if n is None or not under(n, ro):
                raise PermissionError("loading native libraries from outside the interpreter is blocked in the function sandbox")
        elif ev == "socket.bind":
            a = args[1] if len(args) > 1 else None
            if isinstance(a, tuple) and a and not host_ok(a[0]):
                raise PermissionError("binding a non-loopback address is blocked in the function sandbox")
    sys.dont_write_bytecode = True
    sys.addaudithook(hook)
"""

SANDBOX_HOME = "tmp"


def _sandbox_env(user_env: dict, workdir: str) -> dict:
    """Environment of a sandboxed function: NOT the simulator's (no host secrets/tokens), just what a Cloud Functions
    instance has plus the function's own variables."""
    keep = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "VIRTUAL_ENV", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE") if k in os.environ}
    env = dict(keep, HOME=workdir, TMPDIR=os.path.join(workdir, SANDBOX_HOME), PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    env.update(user_env or {})
    return env


def libraries() -> dict:
    """{distribution: version} of the client libraries a function can import (the appliance's own pre-baked wheel set)."""
    from importlib import metadata
    want = ("google-cloud-firestore", "google-cloud-pubsub", "google-cloud-storage", "google-cloud-secret-manager", "google-cloud-kms",
            "google-cloud-logging", "google-cloud-monitoring", "google-cloud-trace", "google-cloud-aiplatform", "google-genai", "google-auth",
            "google-api-core", "grpcio", "requests", "httpx", "pyjwt", "cryptography", "protobuf", "boto3", "pyarrow")
    out = {}
    for d in want:
        try:
            out[d] = metadata.version(d)
        except metadata.PackageNotFoundError:
            pass
    return out


_PROVIDED = {"functions-framework"}   # the sandbox harness IS the functions framework (HTTP + CloudEvent signatures): always satisfied


def check_requirements(text: str) -> list:
    """Honour requirements.txt without internet: every requirement must be satisfied by an installed distribution (the pre-baked
    wheel set, see libraries()). Returns the unsatisfied requirement lines, each with the reason."""
    from importlib import metadata
    missing = []
    try:
        from packaging.requirements import Requirement, InvalidRequirement
    except ImportError:   # pragma: no cover - packaging ships with pip/setuptools
        Requirement = None
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        if Requirement is None:
            name = line
            for sep in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", ";", " "):
                name = name.split(sep, 1)[0]
            try:
                metadata.version(name.strip())
            except metadata.PackageNotFoundError:
                missing.append("%s: not in the pre-baked wheel set" % line)
            continue
        try:
            req = Requirement(line)
        except InvalidRequirement:
            missing.append("%s: not a valid requirement" % line)
            continue
        if req.marker is not None and not req.marker.evaluate():
            continue
        if req.name.lower().replace("_", "-") in _PROVIDED:
            continue
        try:
            have = metadata.version(req.name)
        except metadata.PackageNotFoundError:
            missing.append("%s: not in the pre-baked wheel set (no internet to pip install it)" % line)
            continue
        if req.specifier and not req.specifier.contains(have, prereleases=True):
            missing.append("%s: installed version is %s" % (line, have))
    return missing


def function_env(*, project: str, project_number: str, region: str, service: str, revision: str, entry: str, signature: str,
                 endpoint: str, user_env: dict | None = None) -> dict:
    """The environment a deployed function sees: the standard Cloud Functions / Cloud Run variables, the simulator endpoints
    (STORAGE_EMULATOR_HOST for google-cloud-storage, VYOMI_ENDPOINT for REST clients), and, when the host runs the real
    Pub/Sub + Firestore emulators (VYOMI_GCP_REAL_BACKENDS), their gRPC hosts. The function's own variables win except for
    the reserved ones."""
    env = {"GOOGLE_CLOUD_PROJECT": project, "GCP_PROJECT": project, "GCLOUD_PROJECT": project,
           "GOOGLE_CLOUD_REGION": region, "FUNCTION_REGION": region, "FUNCTION_NAME": service, "FUNCTION_TARGET": entry,
           "FUNCTION_SIGNATURE_TYPE": signature, "K_SERVICE": service, "K_REVISION": revision, "K_CONFIGURATION": service,
           "PORT": "8080", "X_GOOGLE_FUNCTION_VERSION": "1", "CLOUD_RUN_JOB": "", "VYOMI_ENDPOINT": endpoint,
           "STORAGE_EMULATOR_HOST": endpoint, "VYOMI_PROJECT_NUMBER": project_number}
    env.pop("CLOUD_RUN_JOB")
    reserved = set(env)
    out = dict(user_env or {})
    for k in reserved:
        out.pop(k, None)
    out.update(env)
    for k in ("VYOMI_GCP_REAL_BACKENDS", "PUBSUB_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST"):
        if os.environ.get(k) and k not in out:
            out[k] = os.environ[k]
    return out


def self_url(base: str = "") -> str:
    """URL by which a function's subprocess reaches this simulator: VYOMI_SELF_URL, else the request's own base when it is a
    loopback address, else loopback on the appliance port (9000, or PORT/VYOMI_PORT)."""
    if os.environ.get("VYOMI_SELF_URL"):
        return os.environ["VYOMI_SELF_URL"].rstrip("/")
    import urllib.parse as _u
    pu = _u.urlparse(base or "")
    if pu.hostname in ("127.0.0.1", "localhost", "::1") and pu.port:
        return "http://127.0.0.1:%d" % pu.port
    return "http://127.0.0.1:%s" % (os.environ.get("VYOMI_PORT") or os.environ.get("PORT") or "9000")


def enabled() -> bool:
    """The subprocess runtime is used wherever a process can be spawned (offline appliance, Mesh, host tests); Nano (Pyodide)
    keeps the in-interpreter sandbox. VYOMI_GCP_FUNCTION_RUNTIME=inproc forces the latter."""
    return sys.platform != "emscripten" and os.environ.get("VYOMI_GCP_FUNCTION_RUNTIME", "subprocess") != "inproc"


_PY_HTTP_HARNESS = r'''
import json, importlib.util, sys, os, base64, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_shim"))
sys.path.append(os.path.join(os.path.dirname(__file__), "_shim_az"))     # fallback only: the real azure-functions package wins when installed
import flask as _flask
spec = json.loads(sys.stdin.read())
MARK = spec["marker"]
sys.path.insert(0, os.path.dirname(__file__))

'''.rstrip() + "\n" + _shims.SUPPORT_SRC + "\n" + r'''import traceback
try:
    if spec.get("sandbox"):
        sys.dont_write_bytecode = True
        import _guard
        _guard._install_guard(dict(spec["sandbox"], workdir=os.path.dirname(os.path.abspath(__file__))))
    p = os.path.join(os.path.dirname(__file__), "main.py")
    s = importlib.util.spec_from_file_location("user_function", p)
    mod = importlib.util.module_from_spec(s); s.loader.exec_module(mod)
    fn = getattr(mod, spec["entry"], None)
    _app = getattr(mod, "app", None)
    if fn is None and _app is not None and hasattr(_app, "fns"):
        fn = _app.fns.get(spec["entry"]) or next((f for f in _app.fns.values() if getattr(f, "_route", None) == spec["entry"]), None) \
            or (list(_app.fns.values())[0] if len(_app.fns) == 1 else None)
    if fn is None:
        raise SystemExit("Entry point %r not found in function source" % spec["entry"])
    if spec["mode"] == "http":
        try:
            _r = Request(spec["request"])
            if spec.get("flavor") == "azure":
                import azure.functions as _func
                import urllib.parse as _up
                _q = {k: v[0] for k, v in _up.parse_qs(spec["request"]["query"], keep_blank_values=True).items()}
                _r = _func.HttpRequest(_r.method, spec["request"].get("url", ""), headers=dict(_r.headers), params=_q, route_params=spec["request"].get("route_params") or {}, body=_r.data)
            rv = fn(_r)
            status, headers, body = _norm(rv)
        except _flask._Abort as a:
            status, headers, body = a.code, {"Content-Type": "text/html; charset=utf-8"}, str(a.description or a.code).encode()
        out = {"status": status, "headers": headers, "body_b64": base64.b64encode(body).decode()}
    else:
        ev = spec["event"]
        attrs = {k: v for k, v in ev.items() if k != "data"}
        rv = fn(CloudEvent(attrs, ev.get("data")))
        out = {"status": 200, "headers": {}, "body_b64": base64.b64encode(json.dumps(rv, default=str).encode()).decode()}
    sys.stdout.write("\n" + MARK + json.dumps(out))
except SystemExit:
    raise
except BaseException:
    sys.stderr.write(traceback.format_exc()); sys.exit(1)
'''



def _hosts(env: dict) -> list:
    """Hosts the sandbox may reach besides loopback: the simulator endpoint and the real-backend emulators."""
    import urllib.parse as _u
    out = []
    for k in ("VYOMI_ENDPOINT", "PUBSUB_EMULATOR_HOST", "FIRESTORE_EMULATOR_HOST", "STORAGE_EMULATOR_HOST"):
        v = (env or {}).get(k)
        if v:
            h = _u.urlparse(v if "://" in v else "//" + v).hostname
            if h:
                out.append(h)
    return out


def _http_result(proc_out: dict) -> dict:
    """execute-style result -> {status, headers, body(bytes), logs, ok}."""
    import base64
    if proc_out.get("status") != "SUCCESS":
        err = proc_out.get("error") or "execution failed"
        return {"ok": False, "status": 500, "headers": {"Content-Type": "text/plain"}, "body": ("Error: " + err).encode(),
                "logs": proc_out.get("logs", ""), "stderr": proc_out.get("stderr", ""), "error": err}
    r = proc_out.get("result") or {}
    return {"ok": True, "status": int(r.get("status", 200)), "headers": r.get("headers") or {},
            "body": base64.b64decode(r.get("body_b64", "")), "logs": proc_out.get("logs", ""), "stderr": proc_out.get("stderr", "")}


def _run_py_harness(code: str, spec: dict, timeout: int, env: dict | None, entry_files: dict | None = None, sandbox: dict | None = None) -> dict:
    workdir = tempfile.mkdtemp(prefix="cl-fn-")
    try:
        with open(os.path.join(workdir, "main.py"), "w") as fh:
            fh.write(code)
        for rel, text in (entry_files or {}).items():
            dest = os.path.normpath(os.path.join(workdir, rel))
            if dest.startswith(workdir + os.sep):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w") as fh:
                    fh.write(text)
        os.makedirs(os.path.join(workdir, "_shim"), exist_ok=True)
        os.makedirs(os.path.join(workdir, "_shim_az", "azure"))     # a namespace portion (no __init__): `azure.data.tables` etc. still resolve
        with open(os.path.join(workdir, "_shim_az", "azure", "functions.py"), "w") as fh:
            fh.write(_shims.AZ_FUNCTIONS_SHIM)
        with open(os.path.join(workdir, "_shim", "flask.py"), "w") as fh:
            fh.write(_shims.FLASK_SHIM)
        with open(os.path.join(workdir, "_shim", "functions_framework.py"), "w") as fh:
            fh.write(_shims.FF_SHIM)
        with open(os.path.join(workdir, "_run.py"), "w") as fh:
            fh.write(_PY_HTTP_HARNESS)
        if sandbox is not None:
            os.makedirs(os.path.join(workdir, SANDBOX_HOME), exist_ok=True)
            with open(os.path.join(workdir, "_guard.py"), "w") as fh:
                fh.write(_GUARD_SRC)
            run_env = _sandbox_env(env, workdir)
            spec = dict(spec, sandbox=dict(sandbox, hosts=_hosts(run_env)))
        else:
            run_env = dict(os.environ)
            run_env.update(env or {})
        spec = dict(spec, marker=_RESULT_MARKER)
        try:
            proc = subprocess.run([sys.executable, "-B", os.path.join(workdir, "_run.py")], cwd=workdir, input=json.dumps(spec),
                                  capture_output=True, text=True, timeout=timeout, env=run_env)
        except subprocess.TimeoutExpired:
            return {"status": "ERROR", "error": f"Function timed out after {timeout}s", "logs": "", "result": None}
        if proc.returncode != 0:
            return {"status": "ERROR", "error": (proc.stderr or "execution failed").strip()[-2000:],
                    "logs": (proc.stdout or "").strip()[:4000], "stderr": (proc.stderr or "")[-8000:], "result": None}
        result, logs = _parse(proc.stdout or "")
        return {"status": "SUCCESS", "result": result, "logs": logs[:4000], "stderr": (proc.stderr or "")[-8000:]}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def execute_http(code: str, entry_point: str, runtime: str, request: dict, timeout: int = 60,
                 env: dict | None = None, flavor: str = "gcp", sandbox: dict | None = None, files: dict | None = None) -> dict:
    """Invoke an HTTP function with a Flask-like request. `request`: {method, path, query, headers,
    body_b64, url, remote_addr}. Returns {ok, status, headers, body(bytes), logs[, error]}: the
    handler's own HTTP response, unwrapped. A crash is the platform's 500, like the real service."""
    runtime = str(runtime or "python").lower()
    if not (code or "").strip():
        return _http_result({"status": "ERROR", "error": "No function source uploaded — deploy code to enable execution."})
    if not runtime.startswith("python"):
        return _http_result({"status": "ERROR", "error": f"HTTP invocation of runtime {runtime!r} is not supported yet (python only)."})
    return _http_result(_run_py_harness(code, {"mode": "http", "entry": entry_point or "hello_http", "request": request,
                                               "flavor": flavor}, timeout, env, files, sandbox))


def execute_cloud_event(code: str, entry_point: str, runtime: str, event: dict, timeout: int = 60,
                        env: dict | None = None, sandbox: dict | None = None, files: dict | None = None) -> dict:
    """Invoke an event-driven function with a CloudEvent (attributes + .data)."""
    runtime = str(runtime or "python").lower()
    if not (code or "").strip():
        return _http_result({"status": "ERROR", "error": "No function source uploaded — deploy code to enable execution."})
    if not runtime.startswith("python"):
        return _http_result({"status": "ERROR", "error": f"CloudEvent invocation of runtime {runtime!r} is not supported yet (python only)."})
    return _http_result(_run_py_harness(code, {"mode": "event", "entry": entry_point or "handler", "event": event}, timeout, env, files, sandbox))


LOG_SINK = None   # set by the wire router: callable(project, location, service, revision, stream, lines) -> Cloud Logging


def _stream_logs(out: dict, project: str, location: str, service: str, revision: str) -> None:
    """A deployed function's stdout/stderr go to Cloud Logging (`run.googleapis.com/stdout|stderr`, cloud_run_revision), as on Cloud Run."""
    sink = LOG_SINK
    if sink is None:
        return
    for stream, text in (("stdout", out.get("logs") or ""), ("stderr", out.get("stderr") or "")):
        lines = [ln for ln in str(text).splitlines() if ln.strip()]
        if lines:
            try:
                sink(project, location, service, revision, stream, lines)
            except Exception:   # noqa: BLE001 - logging never fails an invocation
                pass


FUNCTION_TOKEN = "vyomi-local-function-token"   # what the sandbox's metadata server hands out as the access token


def run_deployed(*, project: str, project_number: str, location: str, service: str, revision: str, entry: str, runtime: str, code: str,
                 mode: str, payload, user_env: dict | None = None, timeout: int = 60, base: str = "", sa_email: str = "",
                 files: dict | None = None, flavor: str = "gcp") -> dict:
    """Run a DEPLOYED function (Cloud Functions v1/v2 or a Cloud Run service with inline source) in the sandboxed subprocess with
    the identity + environment a real instance has. mode 'http': payload is the request dict; mode 'event': payload is the
    CloudEvent dict. Returns {ok, status, headers, body(bytes), logs[, error][, result]}."""
    endpoint = self_url(base)
    env = function_env(project=project, project_number=project_number, region=location, service=service, revision=revision,
                       entry=entry, signature="http" if mode == "http" else "cloudevent", endpoint=endpoint, user_env=user_env)
    sandbox = {"identity": {"project": project, "number": project_number, "region": location, "email": sa_email or "%s-compute@developer.gserviceaccount.com" % project_number,
                            "sub": project_number, "token": FUNCTION_TOKEN, "instance_id": "00" + project_number, "hostname": "%s.%s.run.app" % (service, location),
                            "scopes": ["https://www.googleapis.com/auth/cloud-platform"]}}
    if mode == "http":
        out = execute_http(code, entry, runtime, payload, timeout=timeout, env=env, flavor=flavor, sandbox=sandbox, files=files)
        _stream_logs(out, project, location, service, revision)
        return out
    out = execute_cloud_event(code, entry, runtime, payload, timeout=timeout, env=env, sandbox=sandbox, files=files)
    _stream_logs(out, project, location, service, revision)
    if out.get("ok"):
        try:
            out["result"] = json.loads((out.get("body") or b"null").decode("utf-8", "replace"))
        except ValueError:
            out["result"] = None
    return out


# ── Vertex AI Agent Engine: user agent code from a source package, run in the same sandbox ─────────────────────
# The hosted agent is `entrypoint_module.entrypoint_object` from the uploaded source archive (an instance, or a class that is instantiated);
# set_up() is called when present and the requested class method is called with the request's `input` as keyword arguments. One sandboxed
# subprocess per call (same guard as functions: identity via the loopback metadata server, network allow-list, filesystem confinement), so
# instance state is NOT kept between calls: use sessions / memory for state, exactly what a scaled-out Agent Engine requires anyway.
_AGENT_HARNESS = r'''
import json, sys, os, traceback, inspect, asyncio, importlib
spec = json.loads(sys.stdin.read())
MARK = spec["marker"]
here = os.path.dirname(os.path.abspath(__file__))
_src = os.path.join(here, "src")
# The SDK tars each source_packages entry under its own relative path (a directory `agent/` arrives as `agent/...`), so the module may be
# `agent.app` (from the archive root) or `app` (from inside that directory): both resolve.
for _d in sorted((d for d in os.listdir(_src) if os.path.isdir(os.path.join(_src, d))), reverse=True):
    sys.path.insert(0, os.path.join(_src, _d))
sys.path.insert(0, _src)
try:
    sys.dont_write_bytecode = True
    import _guard
    _guard._install_guard(dict(spec["sandbox"], workdir=here))
    os.chdir(os.path.join(here, "src"))
    mod = importlib.import_module(spec["module"])
    obj = getattr(mod, spec["object"])
    if inspect.isclass(obj):
        obj = obj()
    if hasattr(obj, "set_up"):
        r = obj.set_up()
        if inspect.isawaitable(r):
            asyncio.run(r) if inspect.iscoroutine(r) else None
    fn = getattr(obj, spec["method"], None)
    if fn is None or not callable(fn):
        raise SystemExit("class method %r not found on %s.%s" % (spec["method"], spec["module"], spec["object"]))
    res = fn(**(spec["input"] or {}))
    kind = "value"
    if inspect.isasyncgen(res):
        async def _drain(g):
            return [x async for x in g]
        res, kind = asyncio.run(_drain(res)), "stream"
    elif inspect.isgenerator(res):
        res, kind = list(res), "stream"
    elif inspect.isawaitable(res):
        async def _aw(a):
            return await a
        res = asyncio.run(_aw(res))
    def _plain(o):
        for m in ("model_dump", "dict"):
            if hasattr(o, m):
                try:
                    return getattr(o, m)()
                except Exception:
                    pass
        return str(o)
    sys.stdout.write("\n" + MARK + json.dumps({"kind": kind, "value": res}, default=_plain))
except SystemExit:
    raise
except BaseException:
    sys.stderr.write(traceback.format_exc()); sys.exit(1)
'''

_MAX_ARCHIVE = 64 * 1024 * 1024


def extract_agent_archive(archive: bytes, dest: str) -> None:
    """Safely unpack a tar.gz (or tar) source package into dest: no absolute paths, no `..`, no links/devices, bounded size."""
    import io
    import tarfile
    if len(archive) > _MAX_ARCHIVE:
        raise ValueError("source archive is larger than %d MB" % (_MAX_ARCHIVE >> 20))
    total = 0
    root = os.path.realpath(dest)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as tf:
        for m in tf.getmembers():
            target = os.path.realpath(os.path.join(root, m.name))
            if not (target == root or target.startswith(root + os.sep)) or os.path.isabs(m.name):
                raise ValueError("unsafe path in source archive: %s" % m.name)
            if not (m.isreg() or m.isdir()):
                continue                      # links, devices, fifos are skipped, never created
            total += m.size
            if total > _MAX_ARCHIVE * 4:
                raise ValueError("source archive expands past the size limit")
            if m.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with tf.extractfile(m) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def run_agent_engine(*, archive: bytes, module: str, obj: str, method: str, input: dict, project: str, project_number: str, location: str,
                     engine_id: str, user_env: dict | None = None, timeout: int = 120, base: str = "") -> dict:
    """Run one class-method call of a source-packaged Agent Engine. -> {status:'SUCCESS', kind:'value'|'stream', value, logs} or
    {status:'ERROR', error, logs}."""
    endpoint = os.environ.get("VYOMI_SELF_URL") or os.environ.get("VYOMI_SELF_ENDPOINT") or self_url(base)
    env = function_env(project=project, project_number=project_number, region=location, service="reasoning-engine-" + engine_id, revision="1",
                       entry=obj, signature="http", endpoint=endpoint.rstrip("/"), user_env=user_env)
    env["GOOGLE_CLOUD_LOCATION"] = location
    sandbox = {"identity": {"project": project, "number": project_number, "region": location, "email": "service-%s@gcp-sa-aiplatform-re.iam.gserviceaccount.com" % project_number,
                            "sub": project_number, "token": FUNCTION_TOKEN, "instance_id": "00" + project_number, "hostname": "reasoning-engine-%s.%s" % (engine_id, location),
                            "scopes": ["https://www.googleapis.com/auth/cloud-platform"]}}
    workdir = tempfile.mkdtemp(prefix="cl-ae-")
    try:
        src = os.path.join(workdir, "src")
        os.makedirs(src)
        extract_agent_archive(archive, src)
        os.makedirs(os.path.join(workdir, SANDBOX_HOME), exist_ok=True)
        with open(os.path.join(workdir, "_guard.py"), "w") as fh:
            fh.write(_GUARD_SRC)
        with open(os.path.join(workdir, "_run.py"), "w") as fh:
            fh.write(_AGENT_HARNESS)
        run_env = _sandbox_env(env, workdir)
        spec = {"module": module, "object": obj, "method": method, "input": input, "marker": _RESULT_MARKER, "sandbox": dict(sandbox, hosts=_hosts(run_env))}
        try:
            proc = subprocess.run([sys.executable, "-B", os.path.join(workdir, "_run.py")], cwd=workdir, input=json.dumps(spec),
                                  capture_output=True, text=True, timeout=timeout, env=run_env)
        except subprocess.TimeoutExpired:
            return {"status": "ERROR", "error": f"Agent call timed out after {timeout}s", "logs": ""}
        if proc.returncode != 0:
            return {"status": "ERROR", "error": (proc.stderr or "execution failed").strip()[-2000:], "logs": (proc.stdout or "").strip()[:4000]}
        result, logs = _parse(proc.stdout or "")
        if not isinstance(result, dict):
            return {"status": "ERROR", "error": "the agent produced no result", "logs": logs[:4000]}
        return {"status": "SUCCESS", "kind": result.get("kind"), "value": result.get("value"), "logs": logs[:4000]}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ══════════════ Azure Functions host (v4 lane az-ref-runtime) ════════════════════════════════════════════
# A deployed Function App runs through the SAME sandbox as the Cloud Functions above (subprocess per call, scrubbed environment,
# interpreter-level egress/filesystem guard) with the Azure Functions contract: the standard environment (FUNCTIONS_WORKER_RUNTIME,
# WEBSITE_SITE_NAME, the app settings as environment variables, AzureWebJobsStorage), a managed-identity endpoint (IDENTITY_ENDPOINT /
# IDENTITY_HEADER, so DefaultAzureCredential works), the REAL `azure.functions` package (function.json v1 and decorator v2 programming
# models; the Vyomi shim is only a fallback when it is not installed) and the REAL Azure SDKs of the appliance wheel set.
# The `azure` namespace is never shadowed: `azure.functions` and `azure.data.tables` / `azure.cosmos` / `azure.servicebus` coexist.
_AZ_HARNESS = r'''
import json, sys, os, base64, traceback, importlib, importlib.util, inspect, logging, asyncio, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
spec = json.loads(sys.stdin.read())
MARK = spec["marker"]
sys.path.insert(0, HERE)
for _extra in (".python_packages/lib/site-packages",):
    if os.path.isdir(os.path.join(HERE, _extra)):
        sys.path.insert(1, os.path.join(HERE, _extra))
sys.path.append(os.path.join(HERE, "_shim_az"))      # fallback only: the real azure-functions package wins when installed
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s: %(message)s")
try:
    if spec.get("sandbox"):
        sys.dont_write_bytecode = True
        import _guard
        _guard._install_guard(dict(spec["sandbox"], workdir=HERE))
    import azure.functions as func
    low = lambda v: str(v).lower() if v is not None else v

    def _plain_val(v):
        if isinstance(v, dict):
            return {k: _plain_val(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_plain_val(x) for x in v]
        if hasattr(v, "name") and hasattr(v, "value") and not isinstance(v, (str, bytes)):      # an Enum (HttpMethod, AuthLevel, BindingDirection, ...)
            return v.value if isinstance(v.value, str) else v.name
        return v

    def _bindings_of(fn):
        out = []
        for b in fn.get_bindings():
            raw = dict(b.get_dict_repr()) if hasattr(b, "get_dict_repr") else dict(b)
            d = _plain_val(raw)
            dr = raw.get("direction")
            d["direction"] = low(dr.name if hasattr(dr, "name") else dr)
            if "authLevel" in d:
                d["authLevel"] = low(d["authLevel"])
            out.append(d)
        return out

    def _apps(mod):
        found = []
        for v in vars(mod).values():
            if hasattr(v, "get_functions") and callable(v.get_functions) and v not in found:
                found.append(v)
        return found

    def _load_v2(script):
        modname = os.path.splitext(script)[0]
        m = importlib.import_module(modname)
        fns = []
        for a in _apps(m):
            fns.extend(a.get_functions())
        return fns

    def _load_v1(d, script, entry):
        path = os.path.normpath(os.path.join(HERE, d, script))
        if script == "__init__.py":
            mod = importlib.import_module(d.replace("/", "."))
        else:
            sp = importlib.util.spec_from_file_location(d.replace("/", ".") + "." + os.path.splitext(os.path.basename(script))[0], path)
            mod = importlib.util.module_from_spec(sp); sp.loader.exec_module(mod)
        fn = getattr(mod, entry or "main", None)
        if fn is None:
            raise SystemExit("entry point %r not found in %s" % (entry or "main", os.path.join(d, script)))
        return fn

    if spec["mode"] == "discover":
        res = []
        for fn in _load_v2(spec["script"]):
            res.append({"name": fn.get_function_name(), "scriptFile": spec["script"], "bindings": _bindings_of(fn)})
        sys.stdout.write("\n" + MARK + json.dumps({"functions": res}))
        sys.exit(0)

    f = spec["fn"]
    if f.get("v2"):
        found = {x.get_function_name(): x for x in _load_v2(f["scriptFile"])}
        if f["name"] not in found:
            raise SystemExit("function %r is not registered by %s" % (f["name"], f["scriptFile"]))
        user = found[f["name"]].get_user_function()
    else:
        user = _load_v1(f["dir"], f.get("scriptFile") or "__init__.py", f.get("entryPoint") or "main")
    bindings = f["bindings"]
    trig = next((b for b in bindings if b.get("direction") == "in" and str(b.get("type", "")).lower().endswith("trigger")), None)

    class _Out(func.Out):
        def __init__(self): self._v = None
        def set(self, v): self._v = v
        def get(self): return self._v

    def _dt(v):
        try:
            return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except Exception:
            return datetime.datetime.now(datetime.timezone.utc)

    def _trigger_arg(t, ev):
        ty = str(t.get("type", "")).lower()
        data = ev.get("data") if isinstance(ev, dict) and "data" in ev and ty != "httptrigger" else ev
        if ty == "httptrigger":
            r = ev
            q = {k: v[0] for k, v in __import__("urllib.parse").parse.parse_qs(r.get("query", ""), keep_blank_values=True).items()}
            return func.HttpRequest(r["method"], r.get("url", ""), headers=dict(r.get("headers") or {}), params=q,
                                    route_params=r.get("route_params") or {}, body=base64.b64decode(r.get("body_b64", "")))
        if ty == "servicebustrigger":
            body = ev.get("body", ev) if isinstance(ev, dict) else ev
            if not isinstance(body, (str, bytes)):
                body = json.dumps(body)
            m = func.ServiceBusMessage(body=body, content_type=(ev.get("content_type") if isinstance(ev, dict) else None) or "application/json",
                                       correlation_id=ev.get("correlation_id") if isinstance(ev, dict) else None)
            return m
        if ty == "eventgridtrigger":
            e = ev if isinstance(ev, dict) else {}
            return func.EventGridEvent(id=str(e.get("id", "")), data=e.get("data") or {}, topic=str(e.get("topic", "")), subject=str(e.get("subject", "")),
                                       event_type=str(e.get("eventType") or e.get("type") or ""), event_time=_dt(e.get("eventTime") or e.get("time")),
                                       data_version=str(e.get("dataVersion") or e.get("specversion") or ""))
        if ty == "timertrigger":
            return func.TimerRequest(past_due=bool((ev or {}).get("past_due", False)) if isinstance(ev, dict) else False)
        if ty == "queuetrigger":
            body = ev.get("body", ev) if isinstance(ev, dict) else ev
            return func.QueueMessage(id=str((ev or {}).get("id", "")) if isinstance(ev, dict) else "", body=body if isinstance(body, (str, bytes)) else json.dumps(body))
        if ty == "blobtrigger":
            b = ev if isinstance(ev, dict) else {}
            return func.blob.InputStream(name=b.get("name"), uri=b.get("uri"), length=b.get("length")) if hasattr(func, "blob") else b
        return data

    arg = _trigger_arg(trig, spec["payload"]) if trig else None
    sig = inspect.signature(user)
    kwargs, outs = {}, {}
    for pname, prm in sig.parameters.items():
        if trig and pname == trig.get("name"):
            kwargs[pname] = arg
        elif any(b.get("name") == pname and b.get("direction") == "out" for b in bindings):
            outs[pname] = kwargs[pname] = _Out()
        elif prm.default is inspect._empty and prm.kind not in (prm.VAR_POSITIONAL, prm.VAR_KEYWORD):
            kwargs[pname] = None      # an input binding the simulator does not resolve (blob/table/cosmos input): the function gets None
    rv = user(**kwargs)
    if inspect.iscoroutine(rv):
        rv = asyncio.run(rv)
    if inspect.isasyncgen(rv):
        raise SystemExit("async generators are not supported as functions")

    def _plain(o):
        if hasattr(o, "get_body"):
            b = o.get_body()
            return b.decode("utf-8", "replace") if isinstance(b, bytes) else b
        if isinstance(o, bytes):
            return o.decode("utf-8", "replace")
        return str(o)

    if trig and str(trig.get("type")).lower() == "httptrigger":
        http_out = next((b for b in bindings if b.get("direction") == "out" and str(b.get("type")).lower() == "http"), None)
        if http_out and http_out.get("name") != "$return" and http_out["name"] in outs:
            rv = outs[http_out["name"]].get()
        if rv is None:
            status, headers, body = 204, {}, b""
        elif hasattr(rv, "get_body") and hasattr(rv, "status_code"):
            headers = {str(k): str(v) for k, v in dict(getattr(rv, "headers", {}) or {}).items()}
            if getattr(rv, "mimetype", None) and not any(k.lower() == "content-type" for k in headers):
                headers["Content-Type"] = rv.mimetype
            status, body = int(rv.status_code), bytes(rv.get_body() or b"")
        elif isinstance(rv, (dict, list)):
            status, headers, body = 200, {"Content-Type": "application/json"}, json.dumps(rv, default=_plain).encode()
        elif isinstance(rv, bytes):
            status, headers, body = 200, {"Content-Type": "application/octet-stream"}, rv
        else:
            status, headers, body = 200, {"Content-Type": "text/plain; charset=utf-8"}, str(rv).encode()
        out = {"kind": "http", "status": status, "headers": headers, "body_b64": base64.b64encode(body).decode()}
    else:
        out = {"kind": "event", "return": json.loads(json.dumps(rv, default=_plain)) if rv is not None else None,
               "outputs": {k: json.loads(json.dumps(v.get(), default=_plain)) for k, v in outs.items()}}
    sys.stdout.write("\n" + MARK + json.dumps(out))
except SystemExit:
    raise
except BaseException:
    sys.stderr.write(traceback.format_exc()); sys.exit(1)
'''

# What the pre-baked Azure wheel set must offer for a function to use the real SDKs (listed by azure_libraries()).
AZURE_LIBS = ("azure-functions", "azure-identity", "azure-core", "azure-data-tables", "azure-cosmos", "azure-servicebus", "azure-storage-blob",
              "azure-storage-queue", "azure-keyvault-secrets", "azure-keyvault-keys", "azure-monitor-opentelemetry-exporter", "opencensus-ext-azure",
              "opentelemetry-sdk")


def azure_libraries() -> dict:
    from importlib import metadata
    out = dict(libraries())
    for d in AZURE_LIBS:
        try:
            out[d] = metadata.version(d)
        except metadata.PackageNotFoundError:
            pass
    return out


def base64_key(seed: str) -> str:
    import base64
    import hashlib
    return base64.b64encode(hashlib.sha512(("vyomi-fn-" + seed).encode()).digest()).decode()


def azure_function_env(*, app: str, resource_group: str, region: str, subscription: str, runtime: str, endpoint: str, settings: dict | None = None,
                       conn_strings: dict | None = None, slot: str = "") -> dict:
    """The environment a deployed Function App's worker sees: the standard Functions variables, the app settings and connection strings
    (App Service exposes them as environment variables), the simulator endpoint, and an AzureWebJobsStorage connection string for the
    simulator's storage account (unless the app sets its own). Reserved platform variables cannot be overridden by app settings."""
    host = "%s.azurewebsites.net" % app
    acct = "vyomifn" + "".join(c for c in app.lower() if c.isalnum())[:16]
    storage = ("DefaultEndpointsProtocol=http;AccountName=%s;AccountKey=%s;BlobEndpoint=%s/azure-data/blob/%s;TableEndpoint=%s/azure-data/table/%s;"
               "QueueEndpoint=%s/azure-data/queue/%s") % (acct, base64_key(app), endpoint, acct, endpoint, acct, endpoint, acct)
    env = {"FUNCTIONS_WORKER_RUNTIME": "python", "FUNCTIONS_EXTENSION_VERSION": "~4", "AzureWebJobsStorage": storage}
    env.update({str(k): str(v) for k, v in (settings or {}).items()})
    if "AccountKey=sim;" in env["AzureWebJobsStorage"] or not env["AzureWebJobsStorage"]:      # the ARM engine's seeded placeholder: use the simulator storage
        env["AzureWebJobsStorage"] = storage
    for name, c in (conn_strings or {}).items():
        v = (c or {}).get("value", "") if isinstance(c, dict) else str(c)
        ty = str((c or {}).get("type", "Custom")) if isinstance(c, dict) else "Custom"
        prefix = {"sqlazure": "SQLAZURECONNSTR_", "mysql": "MYSQLCONNSTR_", "sqlserver": "SQLCONNSTR_", "postgresql": "POSTGRESQLCONNSTR_",
                  "servicebus": "SERVICEBUSCONNSTR_", "notificationhub": "NOTIFICATIONHUBCONNSTR_", "eventhub": "EVENTHUBCONNSTR_",
                  "apihub": "APIHUBCONNSTR_", "documentdb": "DOCDBCONNSTR_", "rediscache": "REDISCACHECONNSTR_"}.get(ty.lower(), "CUSTOMCONNSTR_")
        env[prefix + name] = v
    env.update({"WEBSITE_SITE_NAME": app, "WEBSITE_HOSTNAME": host, "WEBSITE_INSTANCE_ID": "vyomi-" + app, "WEBSITE_RESOURCE_GROUP": resource_group,
                "WEBSITE_OWNER_NAME": "%s+%s-%s" % (subscription, resource_group, region), "REGION_NAME": region, "FUNCTIONS_WORKER_RUNTIME_VERSION": "3.11",
                "AZURE_FUNCTIONS_ENVIRONMENT": "Production", "WEBSITE_AUTH_ENABLED": "False", "WEBSITE_SKU": "Dynamic", "VYOMI_ENDPOINT": endpoint,
                "WEBSITE_SLOT_NAME": slot or "Production", "AzureWebJobsScriptRoot": "/home/site/wwwroot"})
    for k in ("VYOMI_AMQP_HOST", "VYOMI_AMQP_PORT", "VYOMI_AMQPS_PORT", "VYOMI_AZURE_REAL_BACKENDS", "VYOMI_AZURE_AZURITE_ENDPOINT"):
        if os.environ.get(k) and k not in env:
            env[k] = os.environ[k]
    return env


_PROVIDED.add("azure-functions")        # the harness provides azure.functions (the real package when installed, else the Vyomi shim)


def _run_azure_harness(files: dict, spec: dict, timeout: int, env: dict, sandbox: dict) -> dict:
    workdir = tempfile.mkdtemp(prefix="cl-az-")
    try:
        root = os.path.realpath(workdir)
        for rel, data in (files or {}).items():
            dest = os.path.realpath(os.path.join(root, rel))
            if not dest.startswith(root + os.sep) or os.path.isabs(rel):
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb" if isinstance(data, (bytes, bytearray)) else "w") as fh:
                fh.write(data)
        os.makedirs(os.path.join(workdir, "_shim_az", "azure"), exist_ok=True)
        with open(os.path.join(workdir, "_shim_az", "azure", "functions.py"), "w") as fh:
            fh.write(_shims.AZ_FUNCTIONS_SHIM)
        os.makedirs(os.path.join(workdir, SANDBOX_HOME), exist_ok=True)
        with open(os.path.join(workdir, "_guard.py"), "w") as fh:
            fh.write(_GUARD_SRC)
        with open(os.path.join(workdir, "_run.py"), "w") as fh:
            fh.write(_AZ_HARNESS)
        run_env = _sandbox_env(env, workdir)
        spec = dict(spec, marker=_RESULT_MARKER, sandbox=dict(sandbox, hosts=_hosts(run_env)))
        try:
            proc = subprocess.run([sys.executable, "-B", os.path.join(workdir, "_run.py")], cwd=workdir, input=json.dumps(spec),
                                  capture_output=True, text=True, timeout=timeout, env=run_env)
        except subprocess.TimeoutExpired:
            return {"status": "ERROR", "error": "Timeout value of 00:%02d:%02d was exceeded by function" % (timeout // 60, timeout % 60), "logs": "", "stderr": ""}
        if proc.returncode != 0:
            return {"status": "ERROR", "error": (proc.stderr or "execution failed").strip()[-2000:], "logs": (proc.stdout or "").strip()[:4000],
                    "stderr": (proc.stderr or "")[-8000:]}
        result, logs = _parse(proc.stdout or "")
        return {"status": "SUCCESS", "result": result, "logs": logs[:4000], "stderr": (proc.stderr or "")[-8000:]}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _noid() -> dict:
    z = "00000000-0000-0000-0000-000000000000"
    return {"header": "discover", "client_id": z, "principal": z, "tenant": z}


def azure_discover(files: dict, script: str, env: dict, timeout: int = 60) -> dict:
    """Import a v2 (decorator) function_app in the sandbox and list the functions + bindings it registers.
    -> {ok, functions:[{name, scriptFile, bindings}], error, stderr}"""
    out = _run_azure_harness(files, {"mode": "discover", "script": script}, timeout, env, {"azure_identity": _noid()})
    if out["status"] != "SUCCESS":
        return {"ok": False, "functions": [], "error": out.get("error"), "stderr": out.get("stderr", "")}
    return {"ok": True, "functions": (out.get("result") or {}).get("functions", []), "error": None, "stderr": out.get("stderr", "")}


def azure_invoke(files: dict, fn: dict, payload, env: dict, identity: dict, timeout: int = 60) -> dict:
    """Run ONE function of a deployed app. `fn` = {name, v2, dir, scriptFile, entryPoint, bindings}; `payload` is the trigger input
    (http: {method, url, query, headers, body_b64, route_params}; others: the event dict). Returns
    {ok, kind:'http'|'event', status, headers, body(bytes), result, logs, stderr, error}."""
    import base64
    out = _run_azure_harness(files, {"mode": "invoke", "fn": fn, "payload": payload}, timeout, env, {"azure_identity": identity})
    if out["status"] != "SUCCESS":
        err = out.get("error") or "execution failed"
        return {"ok": False, "kind": "http", "status": 500, "headers": {"Content-Type": "text/plain"}, "body": b"", "error": err,
                "logs": out.get("logs", ""), "stderr": out.get("stderr", "")}
    r = out.get("result") or {}
    res = {"ok": True, "kind": r.get("kind", "http"), "logs": out.get("logs", ""), "stderr": out.get("stderr", ""), "error": None}
    if r.get("kind") == "http":
        res.update(status=int(r.get("status", 200)), headers=r.get("headers") or {}, body=base64.b64decode(r.get("body_b64", "")))
    else:
        res.update(status=200, headers={}, body=b"", result=r)
    return res
