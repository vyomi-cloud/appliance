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
_FLASK_SHIM = '''
import json as _json
class Response:
    def __init__(self, response=b"", status=200, headers=None, mimetype=None, content_type=None):
        self.data = response if isinstance(response, (bytes, bytearray)) else str(response).encode()
        self.status_code = int(status)
        self.headers = dict(headers or {})
        ct = content_type or mimetype
        if ct:
            self.headers["Content-Type"] = ct
    status = property(lambda s: s.status_code)
def jsonify(*a, **kw):
    obj = a[0] if len(a) == 1 and not kw else (list(a) if a else kw)
    return Response(_json.dumps(obj), 200, mimetype="application/json")
def make_response(*a):
    if len(a) == 1 and isinstance(a[0], Response):
        return a[0]
    body = a[0] if a else ""
    status = a[1] if len(a) > 1 and isinstance(a[1], int) else 200
    hdrs = a[-1] if len(a) > 1 and isinstance(a[-1], dict) else None
    if isinstance(body, (dict, list)):
        return Response(_json.dumps(body), status, hdrs, mimetype="application/json")
    return Response(body, status, hdrs, mimetype="text/html; charset=utf-8")
def abort(code, description=None):
    raise _Abort(code, description)
class _Abort(Exception):
    def __init__(self, code, description=None):
        super().__init__(description or str(code)); self.code = code; self.description = description
'''

_AZ_FUNCTIONS_SHIM = '''
import json as _json
class AuthLevel:
    ANONYMOUS = "anonymous"; FUNCTION = "function"; ADMIN = "admin"
class HttpRequest:
    def __init__(self, method, url, headers=None, params=None, route_params=None, body=b""):
        self.method = method; self.url = url; self.headers = headers or {}
        self.params = params or {}; self.route_params = route_params or {}; self._body = body or b""
    def get_body(self):
        return self._body
    def get_json(self):
        try:
            return _json.loads(self._body.decode("utf-8"))
        except Exception:
            raise ValueError("req_body is not JSON serializable")
class HttpResponse:
    def __init__(self, body=None, *, status_code=200, headers=None, mimetype=None, charset="utf-8"):
        if isinstance(body, str): body = body.encode(charset)
        self._body = body or b""
        self.status_code = int(status_code); self.headers = dict(headers or {})
        if mimetype: self.headers["Content-Type"] = mimetype
        elif "Content-Type" not in self.headers and "content-type" not in self.headers:
            self.headers["Content-Type"] = "text/plain; charset=utf-8"
    def get_body(self): return self._body
    data = property(lambda s: s._body)
class FunctionApp:
    def __init__(self, http_auth_level=None):
        self.fns = {}
    def _reg(self, fn): self.fns[fn.__name__] = fn; return fn
    def route(self, route=None, methods=None, auth_level=None, **kw):
        def deco(fn):
            fn._route = route or fn.__name__; return self._reg(fn)
        return deco
    def function_name(self, name=None, **kw):
        def deco(fn): self.fns[name or fn.__name__] = fn; return fn
        return deco
    def __getattr__(self, n):   # timer_trigger / queue_trigger / ... decorators: register, return fn
        def trig(*a, **k):
            return lambda fn: self._reg(fn)
        return trig
'''

_FF_SHIM = '''
def http(fn):
    return fn
def cloud_event(fn):
    return fn
'''

_PY_HTTP_HARNESS = r'''
import json, importlib.util, sys, os, base64, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_shim"))
import flask as _flask
spec = json.loads(sys.stdin.read())
MARK = spec["marker"]
sys.path.insert(0, os.path.dirname(__file__))

class _Headers(dict):
    def __init__(self, d):
        super().__init__({k.title(): v for k, v in d.items()})
    def get(self, k, default=None):
        return dict.get(self, str(k).title(), default)
    def __getitem__(self, k):
        return dict.__getitem__(self, str(k).title())
    def __contains__(self, k):
        return dict.__contains__(self, str(k).title())

class Request:
    def __init__(self, r):
        self.method = r["method"]; self.path = r["path"]
        self.query_string = r["query"].encode(); self.full_path = r["path"] + "?" + r["query"]
        self.url = r.get("url", ""); self.base_url = self.url.split("?")[0]
        self.headers = _Headers(r["headers"])
        self.data = base64.b64decode(r["body_b64"])
        self.args = _Args(urllib.parse.parse_qs(r["query"], keep_blank_values=True))
        self.content_type = self.headers.get("Content-Type", "")
        self.mimetype = self.content_type.split(";")[0].strip()
        self.is_json = self.mimetype == "application/json" or self.mimetype.endswith("+json")
        self.remote_addr = r.get("remote_addr", "")
        self.cookies = {}; self.files = {}
        self.form = _Args(urllib.parse.parse_qs(self.data.decode("utf-8", "replace"), keep_blank_values=True)) \
            if self.mimetype == "application/x-www-form-urlencoded" else _Args({})
        self.values = _Args({**{k: v for k, v in self.args.lists()}, **{k: v for k, v in self.form.lists()}})
    def get_data(self, as_text=False, cache=True, parse_form_data=False):
        return self.data.decode("utf-8", "replace") if as_text else self.data
    def get_json(self, force=False, silent=False, cache=True):
        if not (force or self.is_json):
            if silent: return None
            raise _flask._Abort(415, "Content-Type was not 'application/json'")
        try:
            return json.loads(self.data.decode("utf-8")) if self.data else None
        except Exception:
            if silent: return None
            raise _flask._Abort(400, "Failed to decode JSON object")
    json = property(lambda s: s.get_json())
    text = property(lambda s: s.data.decode("utf-8", "replace"))

class _Args(dict):
    def __init__(self, m):
        super().__init__({k: v[0] if isinstance(v, list) and v else v for k, v in m.items()})
        self._m = m
    def getlist(self, k): return list(self._m.get(k, []))
    def lists(self): return self._m.items()
    def to_dict(self, flat=True): return dict(self)

def _norm(rv):
    status, headers = 200, {}
    if isinstance(rv, tuple):
        if len(rv) == 3: rv, status, headers = rv
        elif len(rv) == 2:
            rv, x = rv
            if isinstance(x, dict): headers = x
            else: status = x
        else: rv = rv[0]
    if isinstance(rv, _flask.Response):
        h = dict(rv.headers); h.update(headers or {})
        return rv.status_code if status == 200 else int(status), h, rv.data
    if hasattr(rv, "status_code") and hasattr(rv, "data"):     # a real framework Response
        return int(rv.status_code), dict(getattr(rv, "headers", {}) or {}), bytes(rv.data)
    h = dict(headers or {})
    if rv is None:
        return 500, {"Content-Type": "text/html; charset=utf-8"}, b"The view function did not return a valid response."
    if isinstance(rv, (dict, list)):
        h.setdefault("Content-Type", "application/json"); body = json.dumps(rv).encode()
    elif isinstance(rv, (bytes, bytearray)):
        h.setdefault("Content-Type", "application/octet-stream"); body = bytes(rv)
    else:
        h.setdefault("Content-Type", "text/html; charset=utf-8"); body = str(rv).encode()
    return int(status), h, body

class CloudEvent(dict):
    """functions_framework CloudEvent: dict of attributes + .data"""
    def __init__(self, attributes, data=None):
        super().__init__(attributes); self.data = data; self._attributes = dict(attributes)
    def get_attributes(self): return dict(self._attributes)
    def get_data(self): return self.data

import traceback
try:
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
                _r = _func.HttpRequest(_r.method, spec["request"].get("url", ""), dict(_r.headers), _q, spec["request"].get("route_params") or {}, _r.data)
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


def _http_result(proc_out: dict) -> dict:
    """execute-style result -> {status, headers, body(bytes), logs, ok}."""
    import base64
    if proc_out.get("status") != "SUCCESS":
        err = proc_out.get("error") or "execution failed"
        return {"ok": False, "status": 500, "headers": {"Content-Type": "text/plain"}, "body": ("Error: " + err).encode(),
                "logs": proc_out.get("logs", ""), "error": err}
    r = proc_out.get("result") or {}
    return {"ok": True, "status": int(r.get("status", 200)), "headers": r.get("headers") or {},
            "body": base64.b64decode(r.get("body_b64", "")), "logs": proc_out.get("logs", "")}


def _run_py_harness(code: str, spec: dict, timeout: int, env: dict | None, entry_files: dict | None = None) -> dict:
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
        os.makedirs(os.path.join(workdir, "_shim", "azure"))
        with open(os.path.join(workdir, "_shim", "azure", "__init__.py"), "w") as fh:
            fh.write("")
        with open(os.path.join(workdir, "_shim", "azure", "functions.py"), "w") as fh:
            fh.write(_AZ_FUNCTIONS_SHIM)
        with open(os.path.join(workdir, "_shim", "flask.py"), "w") as fh:
            fh.write(_FLASK_SHIM)
        with open(os.path.join(workdir, "_shim", "functions_framework.py"), "w") as fh:
            fh.write(_FF_SHIM)
        with open(os.path.join(workdir, "_run.py"), "w") as fh:
            fh.write(_PY_HTTP_HARNESS)
        run_env = dict(os.environ)
        run_env.update(env or {})
        spec = dict(spec, marker=_RESULT_MARKER)
        try:
            proc = subprocess.run([sys.executable, os.path.join(workdir, "_run.py")], cwd=workdir, input=json.dumps(spec),
                                  capture_output=True, text=True, timeout=timeout, env=run_env)
        except subprocess.TimeoutExpired:
            return {"status": "ERROR", "error": f"Function timed out after {timeout}s", "logs": "", "result": None}
        if proc.returncode != 0:
            return {"status": "ERROR", "error": (proc.stderr or "execution failed").strip()[-2000:],
                    "logs": (proc.stdout or "").strip()[:4000], "result": None}
        result, logs = _parse(proc.stdout or "")
        return {"status": "SUCCESS", "result": result, "logs": logs[:4000]}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def execute_http(code: str, entry_point: str, runtime: str, request: dict, timeout: int = 60,
                 env: dict | None = None, flavor: str = "gcp") -> dict:
    """Invoke an HTTP function with a Flask-like request. `request`: {method, path, query, headers,
    body_b64, url, remote_addr}. Returns {ok, status, headers, body(bytes), logs[, error]}: the
    handler's own HTTP response, unwrapped. A crash is the platform's 500, like the real service."""
    runtime = str(runtime or "python").lower()
    if not (code or "").strip():
        return _http_result({"status": "ERROR", "error": "No function source uploaded — deploy code to enable execution."})
    if not runtime.startswith("python"):
        return _http_result({"status": "ERROR", "error": f"HTTP invocation of runtime {runtime!r} is not supported yet (python only)."})
    return _http_result(_run_py_harness(code, {"mode": "http", "entry": entry_point or "hello_http", "request": request,
                                               "flavor": flavor}, timeout, env))


def execute_cloud_event(code: str, entry_point: str, runtime: str, event: dict, timeout: int = 60,
                        env: dict | None = None) -> dict:
    """Invoke an event-driven function with a CloudEvent (attributes + .data)."""
    runtime = str(runtime or "python").lower()
    if not (code or "").strip():
        return _http_result({"status": "ERROR", "error": "No function source uploaded — deploy code to enable execution."})
    if not runtime.startswith("python"):
        return _http_result({"status": "ERROR", "error": f"CloudEvent invocation of runtime {runtime!r} is not supported yet (python only)."})
    return _http_result(_run_py_harness(code, {"mode": "event", "entry": entry_point or "handler", "event": event}, timeout, env))
