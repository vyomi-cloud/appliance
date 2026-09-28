"""console-next serverless facade (GCP Cloud Functions) — the GCP lens's
serverless-invoke data plane.

The SAME serverless-invoke widget renders under lens=gcp; the ONLY difference is the
manifest `api` block pointing at /api/console/gcf/* instead of /api/lambda/*
(§15.2 — no if(cloud) branching in the widget). This module is the Cloud Functions
sibling of the AWS Lambda console REST API: it returns the SAME JSON response shapes
the widget consumes (list functions, get config, create, invoke → response payload +
status + stdout/stderr), so the widget stays cloud-agnostic.

Cloud Functions mapping onto the serverless-invoke model:
    function_name  ->  the deployed function id
    handler        ->  the entry-point function (Functions Framework style)
    invoke         ->  runs the REAL sandboxed handler (a Python subprocess), exactly
                       like the Lambda runtime — no fake result. The event payload is
                       delivered as the handler's single positional arg.

Purely additive + substrate-free (no fastapi imports): it holds its OWN module-level
in-memory store so the GCP lens's function state is INDEPENDENT of the AWS Lambda
store, exactly like core/console_gcp_pubsub mirrors the AWS messaging facade. It runs
the handler in a temp workdir via a subprocess (the same sandbox technique the Lambda
runtime uses) so the SAME real-handler-runs guarantee holds; it never touches the
appliance's native Lambda handling.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime, timezone
from typing import Any

PROJECT = "cloudlearn"
REGION = "us-central1"
DEFAULT_RUNTIME = "python312"
DEFAULT_ENTRY_POINT = "handler"

# The default source the console creates when `code` is omitted — a simple echo
# handler you can invoke immediately (mirrors the Lambda facade's default echo).
_DEFAULT_CODE = textwrap.dedent(
    '''
    def handler(event):
        """Cloud Functions entry point — echoes the event back."""
        return {"echo": event, "message": "hello from Cloud Functions"}
    '''
).strip() + "\n"

# In-memory store, independent from the AWS Lambda facade:
#   { function_name: { name, runtime, entry_point, code, state, memory_mb,
#                      timeout_s, created, invocations: int } }
_FUNCTIONS: dict[str, dict[str, Any]] = {}


class GcfError(Exception):
    """Facade error carrying an HTTP status + message (the route re-raises as
    HTTPException, mirroring the other GCP console cores)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fn_resource_name(name: str) -> str:
    return f"projects/{PROJECT}/locations/{REGION}/functions/{name}"


def _validate_name(name: str) -> None:
    if not name:
        raise GcfError(400, "ValidationError function name is required")
    if len(name) > 63 or not all(c.isalnum() or c in "-_" for c in name):
        raise GcfError(
            400,
            "InvalidArgument function name must be <=63 chars of letters, "
            "digits, hyphens or underscores",
        )


def _view(fn: dict) -> dict:
    """The get-config shape the serverless-invoke widget consumes (same keys as the
    Lambda console view: runtime/handler/state/memory_size/timeout/function_arn)."""
    return {
        "function_name": fn["name"],
        "name": fn["name"],
        "runtime": fn.get("runtime", DEFAULT_RUNTIME),
        "handler": fn.get("entry_point", DEFAULT_ENTRY_POINT),
        "state": fn.get("state", "ACTIVE"),
        "memory_size": fn.get("memory_mb", 256),
        "timeout": fn.get("timeout_s", 60),
        # The serverless-invoke widget shows this under the `arn` label; Cloud
        # Functions carry a resource name of the same role.
        "function_arn": _fn_resource_name(fn["name"]),
        "resource_name": _fn_resource_name(fn["name"]),
        "created": fn.get("created", ""),
        "invocations": fn.get("invocations", 0),
    }


def _list_view(fn: dict) -> dict:
    return {
        "function_name": fn["name"],
        "name": fn["name"],
        "runtime": fn.get("runtime", DEFAULT_RUNTIME),
        "handler": fn.get("entry_point", DEFAULT_ENTRY_POINT),
        "state": fn.get("state", "ACTIVE"),
    }


def list_functions() -> dict:
    fns = [_list_view(_FUNCTIONS[n]) for n in sorted(_FUNCTIONS)]
    return {"functions": fns, "count": len(fns)}


def get_function(name: str) -> dict:
    fn = _FUNCTIONS.get(name)
    if fn is None:
        raise GcfError(404, f"NotFound function {name!r} does not exist")
    return _view(fn)


def create_function(name: str, code: str = "", entry_point: str = "") -> dict:
    _validate_name(name)
    if name in _FUNCTIONS:
        raise GcfError(409, f"AlreadyExists function {name!r} already exists")
    src = (code or "").strip()
    src = (src + "\n") if src else _DEFAULT_CODE
    _FUNCTIONS[name] = {
        "name": name,
        "runtime": DEFAULT_RUNTIME,
        "entry_point": (entry_point or DEFAULT_ENTRY_POINT).strip() or DEFAULT_ENTRY_POINT,
        "code": src,
        "state": "ACTIVE",
        "memory_mb": 256,
        "timeout_s": 60,
        "created": _now_iso(),
        "invocations": 0,
    }
    return _view(_FUNCTIONS[name])


def delete_function(name: str) -> dict:
    if name not in _FUNCTIONS:
        raise GcfError(404, f"NotFound function {name!r} does not exist")
    del _FUNCTIONS[name]
    return {"message": f"Function '{name}' deleted"}


# ── The real sandboxed handler run (same subprocess technique as the Lambda
#    runtime): write the source to a temp module, import it, call the entry point
#    with the event payload, capture stdout/stderr + the return value or the
#    exception. No fake result — the REAL user code runs. ──
_HELPER = textwrap.dedent(
    """
    import contextlib, importlib.util, io, json, os, sys, traceback
    workdir = sys.argv[1]
    entry = sys.argv[2]
    payload = json.loads(sys.stdin.read() or "{}")
    sys.path.insert(0, workdir)
    module_path = os.path.join(workdir, "main.py")
    spec = importlib.util.spec_from_file_location("main", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handler = getattr(module, entry)
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            # Cloud Functions (Functions Framework) call the entry point with the
            # request/event as the single positional arg.
            result = handler(payload)
        print(json.dumps({"ok": True, "result": result,
                          "stdout": stdout.getvalue(), "stderr": stderr.getvalue()},
                         default=str))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc),
                          "traceback": traceback.format_exc(),
                          "stdout": stdout.getvalue(), "stderr": stderr.getvalue()},
                         default=str))
    """
).strip()


def _run_handler(fn: dict, event_payload: Any) -> dict:
    with tempfile.TemporaryDirectory(prefix="gcf-") as workdir:
        with open(os.path.join(workdir, "main.py"), "w", encoding="utf-8") as f:
            f.write(fn.get("code", _DEFAULT_CODE))
        entry = fn.get("entry_point", DEFAULT_ENTRY_POINT)
        timeout = max(int(fn.get("timeout_s", 60) or 60), 1)
        try:
            proc = subprocess.run(
                [sys.executable, "-c", _HELPER, workdir, entry],
                input=json.dumps(event_payload or {}, default=str),
                capture_output=True, text=True,
                timeout=min(timeout, 30) + 1,
                env={**os.environ, "PYTHONPATH": workdir},
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "result": None, "stdout": "", "stderr": "",
                    "error": "TimeoutError function exceeded its timeout",
                    "traceback": ""}
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if lines:
        try:
            payload = json.loads(lines[-1])
        except Exception:
            payload = {"ok": False, "error": proc.stdout or proc.stderr or "runtime error"}
    else:
        payload = {"ok": False, "error": proc.stderr or "runtime error"}
    return {
        "ok": bool(payload.get("ok")) and proc.returncode == 0,
        "result": payload.get("result"),
        "stdout": payload.get("stdout", ""),
        "stderr": payload.get("stderr", ""),
        "error": payload.get("error", ""),
        "traceback": payload.get("traceback", ""),
    }


def invoke(name: str, event_payload: Any) -> dict:
    """Invoke the function's REAL handler and return the response in the SAME shape
    the serverless-invoke widget consumes (status/payload/stdout/stderr/error/at)."""
    fn = _FUNCTIONS.get(name)
    if fn is None:
        raise GcfError(404, f"NotFound function {name!r} does not exist")
    run = _run_handler(fn, event_payload)
    fn["invocations"] = int(fn.get("invocations", 0)) + 1
    return {
        "function_name": name,
        "function_arn": _fn_resource_name(name),
        "invocation_type": "RequestResponse",
        "status": "success" if run.get("ok") else "error",
        "payload": run.get("result"),
        "stdout": run.get("stdout", ""),
        "stderr": run.get("stderr", ""),
        "error": run.get("error", ""),
        "traceback": run.get("traceback", ""),
        "at": _now_iso(),
    }


def reset() -> None:  # test hook
    _FUNCTIONS.clear()
