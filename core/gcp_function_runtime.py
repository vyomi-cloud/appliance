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
