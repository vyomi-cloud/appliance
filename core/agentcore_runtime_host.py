"""AgentCore Runtime hosting: really run the agent code a runtime points at, through the AgentCore runtime contract.

Contract (Bedrock AgentCore starter toolkit / bedrock-agentcore SDK): the agent is an HTTP server with
    GET  /ping          -> {"status": "Healthy"}
    POST /invocations   -> body = the InvokeAgentRuntime payload; header X-Amzn-Bedrock-AgentCore-Runtime-Session-Id;
                           JSON response, or text/event-stream when the handler is a generator.
Entrypoint module shapes accepted: a function ``handler(payload, context)`` / ``invoke`` / ``main``, or a bedrock-agentcore
``app = BedrockAgentCoreApp()`` whose ``@app.entrypoint`` function is registered in ``app.handlers['main']``.

Backends (same seam, picked by VYOMI_RUNTIME_BACKEND = auto|subprocess|docker|inproc):
  subprocess  Mesh/offline default: ONE python process per (runtime, version, session) = session isolation; started from this very
              file (``python agentcore_runtime_host.py --serve``), speaks the contract on an ephemeral port. Code comes from the
              runtime's codeConfiguration (zip in the simulator's S3), the agent's AWS SDK calls go back to the simulator through
              AWS_ENDPOINT_URL (+ dummy credentials), runtime environmentVariables are injected.
  docker      containerConfiguration images that exist locally; container port 8080, host port ephemeral. Needs docker + the image.
  inproc      Nano / Pyodide (no subprocess): the entrypoint is exec'd in-process, one fresh module namespace per session.
              Subset: handler functions only, runs on the caller's thread, environment is process-global.
Stdlib only (the child process and Pyodide import nothing else)."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

SESS_HDR = "x-amzn-bedrock-agentcore-runtime-session-id"
IDLE_TTL = float(os.environ.get("VYOMI_RUNTIME_IDLE_TTL", "900"))
MAX_SESSIONS = int(os.environ.get("VYOMI_RUNTIME_MAX_SESSIONS", "16"))
_LOCK = threading.RLock()
_SESSIONS: dict = {}          # (rid, version, sid) -> session


class HostError(Exception):
    def __init__(self, msg, status=424):
        super().__init__(msg)
        self.status = status


# ─────────────────────────── child side: the contract server ───────────────────────────
class _Ctx:
    """The RequestContext the SDK hands to entrypoints."""
    def __init__(self, session_id, headers):
        self.session_id, self.request_headers = session_id, headers


def _load_entry(code_dir, entry):
    path = os.path.join(code_dir, entry)
    if code_dir not in sys.path:
        sys.path.insert(0, code_dir)
    spec = importlib.util.spec_from_file_location("agent_entry_" + str(abs(hash(path))), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app = getattr(mod, "app", None)
    fn = None
    if app is not None and isinstance(getattr(app, "handlers", None), dict) and app.handlers.get("main"):
        fn = app.handlers["main"]                                   # real bedrock_agentcore SDK object
    for n in ("handler", "invoke", "main", "entrypoint"):
        fn = fn or getattr(mod, n, None)
    if not callable(fn):
        raise HostError("entrypoint %s defines no handler(payload, context)" % entry)
    return fn


def _call(fn, payload, ctx):
    try:
        return fn(payload, ctx)
    except TypeError:
        return fn(payload)


def _is_gen(x):
    return hasattr(x, "__next__") or hasattr(x, "__aiter__")


def _sse(gen):
    for ev in gen:
        yield "data: " + json.dumps(ev, default=str) + "\n\n"


def _serve(code_dir, entry, port):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    fn = _load_entry(code_dir, entry)
    boot = time.time()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *a):
            pass

        def _send(self, status, body, ctype="application/json"):
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?")[0] == "/ping":
                self._send(200, json.dumps({"status": "Healthy", "time_of_last_update": int(boot)}).encode())
            else:
                self._send(404, b'{"error":"not found"}')

        def do_POST(self):
            if self.path.split("?")[0] != "/invocations":
                return self._send(404, b'{"error":"not found"}')
            raw = self.rfile.read(int(self.headers.get("content-length") or 0))
            hdrs = {k.lower(): v for k, v in self.headers.items()}
            try:
                try:
                    payload = json.loads(raw) if raw else {}
                except ValueError:
                    payload = raw.decode("utf-8", "replace")
                out = _call(fn, payload, _Ctx(hdrs.get(SESS_HDR), hdrs))
                if _is_gen(out):
                    self.send_response(200)
                    self.send_header("content-type", "text/event-stream")
                    self.end_headers()
                    for chunk in _sse(out):
                        self.wfile.write(chunk.encode())
                        self.wfile.flush()
                    return
                self._send(200, (out if isinstance(out, (bytes,)) else json.dumps(out, default=str).encode()))
            except Exception as e:     # the SDK returns 500 {"error": ...}
                import traceback
                sys.stderr.write(traceback.format_exc())
                self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}).encode())
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


# ─────────────────────────── host side ───────────────────────────
def backend_for(artifact):
    b = os.environ.get("VYOMI_RUNTIME_BACKEND", "auto")
    if b != "auto":
        return b
    if sys.platform == "emscripten":
        return "inproc"
    if "codeConfiguration" in (artifact or {}):
        return "subprocess"
    return "docker" if shutil.which("docker") else "none"


def hostable(artifact):
    """True when this runtime's artifact can be run by the host (otherwise the caller keeps the agent-spec path)."""
    art = artifact or {}
    if "codeConfiguration" in art:
        return True
    return bool((art.get("containerConfiguration") or {}).get("containerUri")) and os.environ.get("VYOMI_RUNTIME_BACKEND") == "docker"


def _fetch_code(s3store, art):
    cc = art["codeConfiguration"]
    s3 = (cc.get("code") or {}).get("s3") or {}
    try:
        from core import s3_object_core as so
    except ImportError:
        import s3_object_core as so  # type: ignore
    q = {"versionId": s3["versionId"]} if s3.get("versionId") else {}
    r = so.get_object(s3store, s3.get("bucket", ""), s3.get("prefix", ""), q, {})
    if r.status != 200:
        raise HostError("agent code s3://%s/%s not readable (%s)" % (s3.get("bucket"), s3.get("prefix"), r.status))
    ep = [e for e in (cc.get("entryPoint") or []) if str(e).endswith(".py")]
    if not ep:
        raise HostError("codeConfiguration.entryPoint must name a .py file")
    return r.body, ep[-1]


def _unzip(blob, dest):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for n in z.namelist():
            if n.startswith("/") or ".." in n.split("/"):
                raise HostError("unsafe path in code archive: " + n)
        z.extractall(dest)


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _env(rt, snap, endpoint, sid):
    e = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "SYSTEMROOT", "LANG", "PYTHONPATH", "VIRTUAL_ENV")}
    e.update({"AWS_ENDPOINT_URL": endpoint, "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", "test"),
              "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", "test"), "AWS_DEFAULT_REGION": rt["agentRuntimeArn"].split(":")[3],
              "AWS_REGION": rt["agentRuntimeArn"].split(":")[3], "AGENT_RUNTIME_ARN": rt["agentRuntimeArn"], "AGENT_RUNTIME_ID": rt["agentRuntimeId"],
              "AGENT_SESSION_ID": sid, "PYTHONUNBUFFERED": "1"})
    e.update({str(k): str(v) for k, v in (snap.get("environmentVariables") or {}).items()})
    return e


class _Proc:
    kind = "subprocess"

    def __init__(self, rt, snap, s3store, endpoint, sid):
        blob, entry = _fetch_code(s3store, snap["agentRuntimeArtifact"])
        self.dir = tempfile.mkdtemp(prefix="agentcore-rt-")
        _unzip(blob, self.dir)
        self.port = _free_port()
        py = os.environ.get("VYOMI_RUNTIME_PYTHON") or sys.executable
        self.log = open(os.path.join(self.dir, ".agent.log"), "w+")
        self.p = subprocess.Popen([py, os.path.abspath(__file__), "--serve", self.dir, entry, str(self.port)], cwd=self.dir,
                                  env=_env(rt, snap, endpoint, sid), stdout=self.log, stderr=subprocess.STDOUT)
        self._wait_ping()

    def _wait_ping(self):
        end = time.time() + float(os.environ.get("VYOMI_RUNTIME_START_TIMEOUT", "60"))
        while time.time() < end:
            if self.p.poll() is not None:
                raise HostError("agent process exited at startup: " + self._tail())
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/ping" % self.port, timeout=1) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.1)
        self.close()
        raise HostError("agent did not answer GET /ping within the startup timeout")

    def _tail(self):
        try:
            self.log.flush(); self.log.seek(0)
            return self.log.read()[-600:]
        except Exception:
            return ""

    def post(self, body, headers):
        req = urllib.request.Request("http://127.0.0.1:%d/invocations" % self.port, data=body, method="POST", headers=headers)
        try:
            r = urllib.request.urlopen(req, timeout=float(os.environ.get("VYOMI_RUNTIME_INVOKE_TIMEOUT", "300")))
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers.items()), e.read()
        return r.status, dict(r.headers.items()), r          # r is a file-like: caller streams it when text/event-stream

    def close(self):
        try:
            self.p.terminate(); self.p.wait(5)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass
        shutil.rmtree(self.dir, ignore_errors=True)


class _Docker:
    kind = "docker"

    def __init__(self, rt, snap, s3store, endpoint, sid):
        image = snap["agentRuntimeArtifact"]["containerConfiguration"]["containerUri"]
        if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode != 0:
            raise HostError("image %s is not present locally (the simulator never pulls images); build/tag it locally" % image)
        self.port = _free_port()
        env = _env(rt, snap, endpoint.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal"), sid)
        args = ["docker", "run", "-d", "--rm", "--add-host=host.docker.internal:host-gateway", "-p", "127.0.0.1:%d:8080" % self.port]
        for k, v in env.items():
            if k not in ("PATH", "HOME", "TMPDIR", "PYTHONPATH", "VIRTUAL_ENV", "SYSTEMROOT"):
                args += ["-e", f"{k}={v}"]
        self.cid = subprocess.run(args + [image], capture_output=True, text=True, check=True).stdout.strip()
        end = time.time() + 60
        while time.time() < end:
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/ping" % self.port, timeout=1):
                    return
            except Exception:
                time.sleep(0.3)
        self.close()
        raise HostError("container did not answer GET /ping on 8080")

    post = _Proc.post

    def close(self):
        subprocess.run(["docker", "rm", "-f", self.cid], capture_output=True)


def _ensure_sdk(region):
    """Nano / Pyodide has no boto3 wheel and no sockets: hosted agent code gets the in-process one (core/lambda_sdk) whose calls land in the same
    stores. A real boto3 (anything that can import it) is never shadowed."""
    import importlib.util
    if "boto3" in sys.modules:
        return
    try:
        if importlib.util.find_spec("boto3") is not None:
            return
        try:
            from core import lambda_sdk
        except ImportError:
            import lambda_sdk  # type: ignore
        lambda_sdk.install_boto3(region)
    except Exception:
        pass


class _InProc:
    kind = "inproc"

    def __init__(self, rt, snap, s3store, endpoint, sid):
        blob, entry = _fetch_code(s3store, snap["agentRuntimeArtifact"])
        self.dir = tempfile.mkdtemp(prefix="agentcore-rt-")
        _unzip(blob, self.dir)
        self.env = _env(rt, snap, endpoint, sid)
        self.entry, self.sid = entry, sid
        self.fn = None

    def post(self, body, headers):
        old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        try:
            if self.fn is None:
                _ensure_sdk(self.env.get("AWS_REGION", "us-east-1"))
                self.fn = _load_entry(self.dir, self.entry)
            try:
                payload = json.loads(body) if body else {}
            except ValueError:
                payload = body.decode("utf-8", "replace")
            out = _call(self.fn, payload, _Ctx(self.sid, {k.lower(): v for k, v in headers.items()}))
            if _is_gen(out):
                return 200, {"content-type": "text/event-stream"}, io.BytesIO("".join(_sse(out)).encode())
            return 200, {"content-type": "application/json"}, io.BytesIO(out if isinstance(out, bytes) else json.dumps(out, default=str).encode())
        except Exception as e:
            return 500, {"content-type": "application/json"}, io.BytesIO(json.dumps({"error": f"{type(e).__name__}: {e}"}).encode())
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def _reap(now):
    for k, s in list(_SESSIONS.items()):
        if now - s["last"] > IDLE_TTL:
            _SESSIONS.pop(k)["h"].close()


def invoke(rt, snap, s3store, endpoint, sid, body, headers):
    """Run one invocation in the session's own agent process. Returns (status, headers, body_or_filelike)."""
    key = (rt["agentRuntimeId"], snap["version"], sid)
    with _LOCK:
        now = time.time()
        _reap(now)
        s = _SESSIONS.get(key)
        if s is None:
            if len(_SESSIONS) >= MAX_SESSIONS:
                oldest = min(_SESSIONS, key=lambda k: _SESSIONS[k]["last"])
                _SESSIONS.pop(oldest)["h"].close()
            art = snap["agentRuntimeArtifact"]
            b = backend_for(art)
            cls = {"subprocess": _Proc, "docker": _Docker, "inproc": _InProc}.get(b)
            if not cls:
                raise HostError("no backend can run this runtime (code deploy needs subprocess/inproc; containers need docker). backend=%s" % b)
            s = _SESSIONS[key] = {"h": cls(rt, snap, s3store, endpoint, sid), "last": now, "created": now, "lock": threading.Lock()}
        s["last"] = now
    h = {"content-type": "application/json", SESS_HDR: sid}
    h.update({k: v for k, v in headers.items() if k in ("authorization", "x-amzn-bedrock-agentcore-runtime-custom-authorization")})
    with s["lock"]:                                                     # one in-flight request per session, like the real microVM
        st, rh, out = s["h"].post(body, h)
        if hasattr(out, "read") and "text/event-stream" not in rh.get("content-type", rh.get("Content-Type", "")):
            out = out.read()
        return st, rh, out


def stop_session(rid, sid=None):
    with _LOCK:
        n = 0
        for k in [k for k in _SESSIONS if k[0] == rid and (sid is None or k[2] == sid)]:
            _SESSIONS.pop(k)["h"].close(); n += 1
        return n


def session_ids(rid):
    return [k[2] for k in _SESSIONS if k[0] == rid]


def _atexit():
    for k in list(_SESSIONS):
        try:
            _SESSIONS.pop(k)["h"].close()
        except Exception:
            pass


import atexit as _a
_a.register(_atexit)

if __name__ == "__main__" and len(sys.argv) >= 5 and sys.argv[1] == "--serve":
    _serve(sys.argv[2], sys.argv[3], int(sys.argv[4]))
