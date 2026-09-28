"""console-next serverless facade (Azure Functions) — the Azure lens's
serverless-invoke data plane.

The SAME serverless-invoke widget renders under lens=azure; the ONLY difference is
the manifest `api` block pointing at /api/console/azure-functions/* instead of
/api/lambda/* (§15.2 — no if(cloud) branching in the widget). This module is the
Azure Functions sibling of the AWS Lambda / GCP Cloud Functions console REST APIs:
it returns the SAME JSON response shapes the widget consumes (list functions, get
config, create, invoke → response payload + status + stdout/stderr), so the widget
stays cloud-agnostic.

Azure Functions mapping onto the serverless-invoke model:
    function_name  ->  the deployed function app / function id
    handler        ->  the entry-point function (Python programming model — `main`)
    invoke         ->  runs the REAL sandboxed handler (a Python subprocess), exactly
                       like the Lambda / Cloud Functions runtime — no fake result. The
                       trigger payload is delivered as the handler's single positional
                       arg.

Purely additive + substrate-free (no fastapi imports): it holds its OWN module-level
in-memory store so the Azure lens's function state is INDEPENDENT of the AWS Lambda /
GCP Cloud Functions stores, exactly like core/console_gcf mirrors the AWS messaging
facade. It runs the handler in a temp workdir via a subprocess (the same sandbox
technique the Lambda / Cloud Functions runtimes use) so the SAME real-handler-runs
guarantee holds; it never touches the appliance's native Lambda handling.
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

SUBSCRIPTION = "cloudlearn"
RESOURCE_GROUP = "cloudlearn-rg"
REGION = "eastus"
DEFAULT_RUNTIME = "python|3.12"
DEFAULT_ENTRY_POINT = "main"

# The default source the console creates when `code` is omitted — a simple echo
# handler you can invoke immediately (mirrors the Lambda / Cloud Functions defaults).
_DEFAULT_CODE = textwrap.dedent(
    '''
    def main(event):
        """Azure Functions entry point — echoes the event back."""
        return {"echo": event, "message": "hello from Azure Functions"}
    '''
).strip() + "\n"

# In-memory store, independent from the AWS Lambda / GCP Cloud Functions facades:
#   { function_name: { name, runtime, entry_point, code, state, memory_mb,
#                      timeout_s, created, invocations: int } }
_FUNCTIONS: dict[str, dict[str, Any]] = {}


class AzureFunctionError(Exception):
    """Facade error carrying an HTTP status + message (the route re-raises as
    HTTPException, mirroring the other console cores)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fn_resource_id(name: str) -> str:
    return (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.Web/sites/{name}"
    )


def _validate_name(name: str) -> None:
    if not name:
        raise AzureFunctionError(400, "ValidationError function name is required")
    if len(name) > 60 or not all(c.isalnum() or c in "-" for c in name):
        raise AzureFunctionError(
            400,
            "InvalidArgument function name must be <=60 chars of letters, "
            "digits or hyphens",
        )


def _view(fn: dict) -> dict:
    """The get-config shape the serverless-invoke widget consumes (same keys as the
    Lambda console view: runtime/handler/state/memory_size/timeout/function_arn)."""
    return {
        "function_name": fn["name"],
        "name": fn["name"],
        "runtime": fn.get("runtime", DEFAULT_RUNTIME),
        "handler": fn.get("entry_point", DEFAULT_ENTRY_POINT),
        "state": fn.get("state", "Running"),
        "memory_size": fn.get("memory_mb", 256),
        "timeout": fn.get("timeout_s", 300),
        # The serverless-invoke widget shows this under the `arn` label; Azure
        # Functions carry a resource id of the same role.
        "function_arn": _fn_resource_id(fn["name"]),
        "resource_id": _fn_resource_id(fn["name"]),
        "created": fn.get("created", ""),
        "invocations": fn.get("invocations", 0),
    }


def _list_view(fn: dict) -> dict:
    return {
        "function_name": fn["name"],
        "name": fn["name"],
        "runtime": fn.get("runtime", DEFAULT_RUNTIME),
        "handler": fn.get("entry_point", DEFAULT_ENTRY_POINT),
        "state": fn.get("state", "Running"),
    }


def list_functions() -> dict:
    fns = [_list_view(_FUNCTIONS[n]) for n in sorted(_FUNCTIONS)]
    return {"functions": fns, "count": len(fns)}


def get_function(name: str) -> dict:
    fn = _FUNCTIONS.get(name)
    if fn is None:
        raise AzureFunctionError(404, f"NotFound function {name!r} does not exist")
    return _view(fn)


def create_function(name: str, code: str = "", entry_point: str = "") -> dict:
    _validate_name(name)
    if name in _FUNCTIONS:
        raise AzureFunctionError(409, f"Conflict function {name!r} already exists")
    src = (code or "").strip()
    src = (src + "\n") if src else _DEFAULT_CODE
    _FUNCTIONS[name] = {
        "name": name,
        "runtime": DEFAULT_RUNTIME,
        "entry_point": (entry_point or DEFAULT_ENTRY_POINT).strip() or DEFAULT_ENTRY_POINT,
        "code": src,
        "state": "Running",
        "memory_mb": 256,
        "timeout_s": 300,
        "created": _now_iso(),
        "invocations": 0,
    }
    return _view(_FUNCTIONS[name])


def delete_function(name: str) -> dict:
    if name not in _FUNCTIONS:
        raise AzureFunctionError(404, f"NotFound function {name!r} does not exist")
    del _FUNCTIONS[name]
    return {"message": f"Function '{name}' deleted"}


# ── The real sandboxed handler run (same subprocess technique as the Lambda /
#    Cloud Functions runtimes): write the source to a temp module, import it, call
#    the entry point with the event payload, capture stdout/stderr + the return value
#    or the exception. No fake result — the REAL user code runs. ──
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
            # Azure Functions (Python model) call the entry point with the
            # trigger/event as the single positional arg.
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
    with tempfile.TemporaryDirectory(prefix="azfn-") as workdir:
        with open(os.path.join(workdir, "main.py"), "w", encoding="utf-8") as f:
            f.write(fn.get("code", _DEFAULT_CODE))
        entry = fn.get("entry_point", DEFAULT_ENTRY_POINT)
        timeout = max(int(fn.get("timeout_s", 300) or 300), 1)
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
        raise AzureFunctionError(404, f"NotFound function {name!r} does not exist")
    run = _run_handler(fn, event_payload)
    fn["invocations"] = int(fn.get("invocations", 0)) + 1
    return {
        "function_name": name,
        "function_arn": _fn_resource_id(name),
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
