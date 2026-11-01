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






_PY_HTTP_HARNESS = r'''
import json, importlib.util, sys, os, base64, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_shim"))
import flask as _flask
spec = json.loads(sys.stdin.read())
MARK = spec["marker"]
sys.path.insert(0, os.path.dirname(__file__))

'''.rstrip() + "\n" + _shims.SUPPORT_SRC + "\n" + r'''import traceback
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
            fh.write(_shims.AZ_FUNCTIONS_SHIM)
        with open(os.path.join(workdir, "_shim", "flask.py"), "w") as fh:
            fh.write(_shims.FLASK_SHIM)
        with open(os.path.join(workdir, "_shim", "functions_framework.py"), "w") as fh:
            fh.write(_shims.FF_SHIM)
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
