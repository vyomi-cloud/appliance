# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Sandboxed Python execution shared by Bedrock Agents (AMAZON.CodeInterpreter) and Azure Foundry Assistants (code_interpreter).

Two engines behind one call, ``run(code, files=None, timeout=10) -> dict``:

  subprocess  Mesh / appliance (default where ``subprocess`` works): a fresh ``python -I`` child per call in a throw-away working directory,
              empty environment, CPU / file-size / address-space rlimits, a wall-clock kill, and a ``sys.addaudithook`` that denies sockets,
              process creation, ctypes, exec*, fork, and any file open outside the working directory (stdlib / site-packages stay readable so
              ``import pandas`` works when installed). Whatever Python libraries the host interpreter has are available.
  inproc      Nano / Pyodide (no subprocess): exec in a fresh namespace after an AST gate (no dunder attribute access, no eval / exec / open /
              getattr / globals ...), builtins and import allow-list (math, json, statistics, re, collections, itertools, datetime, random, csv,
              decimal, fractions, ...), a virtual in-memory file system for ``open`` and a sys.settrace line/time guard.

Declared limits (also in core/capabilities): this is a *restricted-execution* sandbox, not a VM. The subprocess engine cannot cap native code
that bypasses Python (there is no network namespace); the in-process engine cannot interrupt a single long-running C call (e.g. a huge
``10**10**8``) and has no numpy / pandas / matplotlib. Variables do not persist between calls; files do (the caller carries ``files``).
Pure Python, stdlib only.
"""
from __future__ import annotations

import ast
import builtins as _b
import io
import json
import os
import sys
import time

MAX_OUT = 20000
MAX_FILE = 1 << 20
MAX_FILES = 8

_WRAPPER = r'''
import sys, os, io, json, builtins
_cfg = json.loads(sys.stdin.buffer.read().decode())
_wd = os.path.realpath(os.getcwd())
_ok = tuple(os.path.realpath(p) for p in {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix} if p)
_deny = ("socket.", "subprocess.", "os.system", "os.exec", "os.fork", "os.posix_spawn", "os.spawn", "ctypes.", "os.kill", "shutil.rmtree",
         "os.chmod", "os.chown", "os.symlink", "os.link", "os.chdir", "os.chroot", "pty.", "webbrowser.", "urllib.Request", "os.putenv", "os.unsetenv", "winreg.")
def _hook(ev, args):
    if ev.startswith(_deny):
        raise PermissionError("blocked by the code interpreter sandbox: " + ev)
    if ev == "open":
        path = args[0]
        if isinstance(path, int):
            return
        if not isinstance(path, (str, bytes, os.PathLike)):
            return
        try:
            rp = os.path.realpath(os.fsdecode(path))
        except Exception:
            raise PermissionError("blocked path")
        mode = args[1] if len(args) > 1 and isinstance(args[1], str) else "r"
        write = any(c in (mode or "r") for c in "wax+")
        if rp == _wd or rp.startswith(_wd + os.sep):
            return
        if not write and rp.startswith(_ok):
            return
        raise PermissionError("file access outside the working directory is blocked: " + os.path.basename(rp))
    if ev in ("os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.truncate", "os.utime", "os.listdir", "os.scandir"):
        p = args[0]
        if isinstance(p, (str, bytes, os.PathLike)):
            rp = os.path.realpath(os.fsdecode(p))
            if not (rp == _wd or rp.startswith(_wd + os.sep) or (ev in ("os.listdir", "os.scandir") and rp.startswith(_ok))):
                raise PermissionError("blocked path: " + os.path.basename(rp))
sys.addaudithook(_hook)
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (_cfg["cpu"], _cfg["cpu"] + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_cfg["fsize"], _cfg["fsize"]))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (_cfg["mem"], _cfg["mem"]))
except Exception:
    pass
g = {"__name__": "__main__", "__builtins__": builtins}
try:
    exec(compile(_cfg["code"], "<code_interpreter>", "exec"), g)
except SystemExit:
    pass
except BaseException:
    import traceback
    tb = traceback.format_exc().splitlines()
    keep = [l for l in tb[1:] if '"<string>"' not in l and "_cfg[" not in l and "~~" not in l and "^^" not in l]
    sys.stderr.write("\n".join([tb[0]] + keep[-12:]) + "\n")
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(1)
sys.stdout.flush(); sys.stderr.flush()
'''

_SAFE_MODULES = {"math", "json", "statistics", "re", "collections", "itertools", "functools", "datetime", "random", "string", "decimal", "fractions",
                 "csv", "io", "textwrap", "heapq", "bisect", "operator", "copy", "typing", "dataclasses", "enum", "uuid", "base64", "hashlib",
                 "calendar", "array", "numbers", "abc", "contextlib", "time", "zlib", "html", "unicodedata", "difflib", "pprint"}
_BAD_NAMES = {"eval", "exec", "compile", "input", "getattr", "setattr", "delattr", "globals", "locals", "vars", "breakpoint", "memoryview",
              "__import__", "help", "exit", "quit", "dir"}
_SAFE_BUILTIN_NAMES = ("abs all any ascii bin bool bytearray bytes callable chr classmethod complex dict divmod enumerate filter float format frozenset "
                       "hasattr hash hex id int isinstance issubclass iter len list map max min next object oct ord pow print property range repr reversed "
                       "round set slice sorted staticmethod str sum super tuple type zip "
                       "ArithmeticError AssertionError AttributeError BaseException Exception IndexError KeyError KeyboardInterrupt LookupError "
                       "NameError NotImplementedError OverflowError RuntimeError StopIteration TypeError ValueError ZeroDivisionError "
                       "UnicodeError TimeoutError True False None Ellipsis NotImplemented").split()


def _gate(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and n.attr.startswith("__"):
            raise PermissionError(f"attribute access to '{n.attr}' is blocked by the code interpreter sandbox")
        if isinstance(n, ast.Name) and (n.id in _BAD_NAMES or (n.id.startswith("__") and n.id not in ("__name__", "__doc__"))):
            raise PermissionError(f"use of '{n.id}' is blocked by the code interpreter sandbox")


class _VFile:
    """open() inside the in-process sandbox: only bare file names, backed by a dict."""

    def __init__(self, store):
        self.store = store

    def __call__(self, name, mode="r", *a, **k):
        name = str(name)
        if "/" in name or "\\" in name or name.startswith("."):
            raise PermissionError("only plain file names in the working directory are allowed")
        binary = "b" in mode
        store = self.store
        if "r" in mode and "+" not in mode:
            if name not in store:
                raise FileNotFoundError(name)
            raw = store[name]
            return io.BytesIO(raw) if binary else io.StringIO(raw.decode("utf-8", "replace"))
        if len(store) >= MAX_FILES and name not in store:
            raise OSError("too many files")
        init = store.get(name, b"") if "a" in mode else b""

        class W(io.BytesIO if binary else io.StringIO):
            def close(s):
                v = s.getvalue()
                store[name] = v if binary else v.encode()
                super().close()
        w = W(init if binary else init.decode())
        if "a" in mode:
            w.seek(0, 2)
        return w


def _run_inproc(code, files, timeout):
    t0 = time.time()
    store = dict(files or {})
    out = io.StringIO()
    res = {"stdout": "", "error": None, "timeout": False, "engine": "inproc"}
    try:
        tree = ast.parse(code, "<code_interpreter>")
        _gate(tree)
    except (SyntaxError, PermissionError) as e:
        res["error"] = f"{type(e).__name__}: {e}"
        return res, store
    safe = {n: getattr(_b, n) for n in _SAFE_BUILTIN_NAMES if hasattr(_b, n)}

    def _imp(name, globs=None, locs=None, fromlist=(), level=0):
        if name.split(".")[0] not in _SAFE_MODULES:
            raise ImportError(f"module '{name}' is not available in the in-browser code interpreter")
        return _b.__import__(name, globs, locs, fromlist, level)
    safe["__import__"] = _imp
    safe["open"] = _VFile(store)
    safe["print"] = lambda *a, sep=" ", end="\n", **k: out.write(sep.join(str(x) for x in a) + end)
    deadline = t0 + timeout
    steps = [0]

    def tracer(frame, event, arg):
        steps[0] += 1
        if steps[0] % 200 == 0 and time.time() > deadline:
            raise TimeoutError("execution time limit exceeded")
        return tracer
    g = {"__name__": "__main__", "__builtins__": safe}
    old = sys.gettrace()
    try:
        sys.settrace(tracer)
        exec(compile(tree, "<code_interpreter>", "exec"), g)
    except TimeoutError as e:
        res["timeout"], res["error"] = True, f"TimeoutError: {e}"
    except SystemExit:
        pass
    except BaseException as e:  # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {e}"
    finally:
        sys.settrace(old)
    res["stdout"] = out.getvalue()
    return res, store


def _can_subprocess():
    if sys.platform == "emscripten" or os.environ.get("VYOMI_CODE_SANDBOX") == "inproc":
        return False
    try:
        import subprocess  # noqa: F401
        import resource  # noqa: F401
    except ImportError:
        return False
    return bool(sys.executable)


def _run_subprocess(code, files, timeout):
    import subprocess
    import tempfile
    import shutil
    wd = tempfile.mkdtemp(prefix="vyomi-ci-")
    res = {"stdout": "", "error": None, "timeout": False, "engine": "subprocess"}
    store = {}
    try:
        for n, v in (files or {}).items():
            with open(os.path.join(wd, os.path.basename(n)), "wb") as f:
                f.write(v)
        cfg = {"code": code, "cpu": max(1, int(timeout)), "fsize": 4 << 20, "mem": 1 << 30}

        def pre():
            os.setsid()
        try:
            p = subprocess.run([sys.executable, "-I", "-c", _WRAPPER], input=json.dumps(cfg).encode(), cwd=wd, env={"PYTHONIOENCODING": "utf-8", "PATH": "/usr/bin:/bin"},
                               capture_output=True, timeout=timeout + 2, preexec_fn=pre)
            res["stdout"] = p.stdout.decode("utf-8", "replace")
            if p.returncode != 0:
                err = p.stderr.decode("utf-8", "replace").strip()
                res["error"] = err[-4000:] or f"process exited with status {p.returncode}"
                if p.returncode in (-24, -9, 137, 152) and not err:
                    res["timeout"], res["error"] = True, "execution time limit exceeded"
        except subprocess.TimeoutExpired as e:
            res["timeout"], res["error"] = True, "TimeoutError: execution time limit exceeded"
            res["stdout"] = (e.stdout or b"").decode("utf-8", "replace")
        for n in sorted(os.listdir(wd))[:MAX_FILES]:
            fp = os.path.join(wd, n)
            if os.path.isfile(fp) and os.path.getsize(fp) <= MAX_FILE:
                with open(fp, "rb") as f:
                    store[n] = f.read()
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    return res, store


def run(code, files=None, timeout=10.0, engine=None):
    """-> {"stdout","error","timeout","engine","files":{name: bytes}}. Never raises for user-code failures."""
    files = {k: v for k, v in (files or {}).items()}
    eng = engine or ("subprocess" if _can_subprocess() else "inproc")
    res, store = (_run_subprocess if eng == "subprocess" else _run_inproc)(code, files, float(timeout))
    res["stdout"] = res["stdout"][:MAX_OUT]
    res["files"] = {n: v for n, v in store.items() if (n not in files or files[n] != v)}
    return res
