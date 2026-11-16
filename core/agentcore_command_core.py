"""InvokeAgentRuntimeCommand: run a command in a runtime session's sandbox, streamed as ``contentStart`` / ``contentDelta`` / ``contentStop``.

The real service runs ``/bin/sh -c`` inside the session's microVM. Vyomi has no microVM for the agent-spec runtime and will not hand
out a host shell, so a command runs on core/code_sandbox_core (OSS-free restricted-execution sandbox, Mesh: audit-hooked subprocess, Nano:
AST-gated in-process). The command language is a documented SUBSET of sh, implemented by this adapter:

  sequencing   ``a ; b``   ``a && b``   ``a || b``   (exit codes honoured)       redirection  ``> file``  ``>> file``  (stdout only)
  builtins     echo [-n], pwd, ls [path], cat file..., env / printenv [NAME], whoami, uname [-a], true, false, exit [n], which
  python       ``python[3] -c "code"``   ``python[3] script.py``   ``python[3] --version``   (sandbox rules: stdlib allow-list on Nano, no network / processes)
  anything else -> ``sh: 1: <cmd>: not found`` on stderr, exit 127 (no pip / npm / git / apt / pipes / globs / variables / subshells).

Files written by a command live in the session workspace (``/workspace``) and persist across commands of the same runtimeSessionId.
Output is emitted per command segment as each one finishes (the sandbox returns a whole result per call; it does not stream mid-process).
Pure stdlib; same code on Nano and Mesh.
"""
from __future__ import annotations

import json
import shlex
import sys
import time

try:
    from core import code_sandbox_core as cs
except ImportError:  # Pyodide flat layout
    import code_sandbox_core as cs  # type: ignore

MAX_TIMEOUT = 3600
MAX_DELTA = 8192
_OPS = {"&&", ";", "||"}


def _tokens(cmd):
    lx = shlex.shlex(cmd, posix=True, punctuation_chars=";&|<>")
    lx.whitespace_split = True
    lx.commenters = ""
    return list(lx)


def _split(tokens):
    """-> [(segment tokens, operator joining it to the NEXT segment or None)]"""
    out, cur = [], []
    for t in tokens:
        if t in _OPS:
            out.append((cur, t))
            cur = []
        else:
            cur.append(t)
    out.append((cur, None))
    return out


def _redirect(tokens):
    """-> (argv, (mode, file) | None)"""
    for i, t in enumerate(tokens):
        if t in (">", ">>"):
            if i + 1 >= len(tokens):
                raise ValueError("syntax error: expected a file name after " + t)
            return tokens[:i] + tokens[i + 2:], (t, tokens[i + 1])
        if t in ("<", "|", "&", "<<", ">>>", "|&"):
            raise ValueError(f"syntax error: unsupported shell operator '{t}' (pipes, input redirection and background jobs are not available)")
    return tokens, None


def _py(argv, files, env, timeout):
    """-> (stdout, stderr, exit, timed_out, new files)"""
    if len(argv) >= 2 and argv[1] in ("--version", "-V"):
        return f"Python {sys.version.split()[0]}\n", "", 0, False, {}
    if len(argv) >= 3 and argv[1] == "-c":
        code = argv[2]
    elif len(argv) >= 2 and not argv[1].startswith("-"):
        name = argv[1].lstrip("./")
        if name not in files:
            return "", f"python: can't open file '/workspace/{name}': [Errno 2] No such file or directory\n", 2, False, {}
        code = files[name].decode("utf-8", "replace")
    else:
        return "", "python: only `-c CODE`, `SCRIPT.py` and `--version` are supported\n", 2, False, {}
    r = cs.run(code, files, timeout=max(1.0, timeout))
    err = (r.get("error") or "")
    return r.get("stdout", ""), (err + "\n" if err and not err.endswith("\n") else err), (124 if r.get("timeout") else (1 if err else 0)), bool(r.get("timeout")), r.get("files") or {}


def _builtin(argv, files, env):
    c, a = argv[0], argv[1:]
    if c == "echo":
        nl = "\n"
        if a and a[0] == "-n":
            a, nl = a[1:], ""
        return " ".join(a) + nl, "", 0
    if c == "pwd":
        return "/workspace\n", "", 0
    if c == "whoami":
        return "agentcore\n", "", 0
    if c == "uname":
        return ("Linux vyomi-runtime 6.1.0 #1 SMP aarch64 GNU/Linux\n" if a and a[0] == "-a" else "Linux\n"), "", 0
    if c == "true":
        return "", "", 0
    if c == "false":
        return "", "", 1
    if c == "which":
        known = {"python": "/usr/bin/python3", "python3": "/usr/bin/python3", "echo": "/bin/echo", "cat": "/bin/cat", "ls": "/bin/ls"}
        hit = [known[x] for x in a if x in known]
        return "".join(h + "\n" for h in hit), "", 0 if len(hit) == len(a) and a else 1
    if c == "ls":
        names = sorted(files)
        if a and a[-1] not in (".", "/workspace", "./"):
            return "", f"ls: cannot access '{a[-1]}': No such file or directory\n", 2
        return "".join(n + "\n" for n in names), "", 0
    if c == "cat":
        out, err, rc = "", "", 0
        for n in a:
            if n.lstrip("./") in files:
                out += files[n.lstrip("./")].decode("utf-8", "replace")
            else:
                err, rc = err + f"cat: {n}: No such file or directory\n", 1
        return out, err, rc
    if c in ("env", "printenv"):
        if c == "printenv" and a:
            return (env.get(a[0], "") + "\n", "", 0) if a[0] in env else ("", "", 1)
        return "".join(f"{k}={v}\n" for k, v in sorted(env.items())), "", 0
    return None


def run(command, files, env=None, timeout=300):
    """Generator of ("out"|"err", text) pieces then ("stop", exitCode, status). ``files`` (name -> bytes) is mutated in place."""
    env = {"HOME": "/workspace", "PWD": "/workspace", "SHELL": "/bin/sh", **(env or {})}
    deadline = time.time() + timeout
    try:
        segs = _split(_tokens(command))
    except ValueError as e:
        yield "err", f"sh: 1: {e}\n"
        yield "stop", 2, "COMPLETED"
        return
    rc, skip = 0, False
    for argv, op in segs:
        if not argv:
            if op is not None or len(segs) == 1:
                yield "err", "sh: 1: syntax error: unexpected '" + (op or "end of file") + "'\n"
                yield "stop", 2, "COMPLETED"
                return
            continue
        if not skip:
            if time.time() >= deadline:
                yield "stop", 124, "TIMED_OUT"
                return
            try:
                argv, redir = _redirect(argv)
            except ValueError as e:
                yield "err", f"sh: 1: {e}\n"
                yield "stop", 2, "COMPLETED"
                return
            if not argv:
                rc = 0
            elif argv[0] == "exit":
                yield "stop", int(argv[1]) if len(argv) > 1 and argv[1].lstrip("-").isdigit() else rc, "COMPLETED"
                return
            else:
                new = {}
                if argv[0] in ("python", "python3"):
                    out, err, rc, to, new = _py(argv, files, env, deadline - time.time())
                    if to:
                        if out:
                            yield "out", out
                        yield "stop", 124, "TIMED_OUT"
                        return
                else:
                    b = _builtin(argv, files, env)
                    out, err, rc = b if b is not None else ("", f"sh: 1: {argv[0]}: not found\n", 127)
                files.update(new)
                if redir:
                    mode, fn = redir
                    old = files.get(fn.lstrip("./"), b"") if mode == ">>" else b""
                    files[fn.lstrip("./")] = (old + out.encode())[:cs.MAX_FILE]
                    out = ""
                for i in range(0, len(out), MAX_DELTA):
                    yield "out", out[i:i + MAX_DELTA]
                for i in range(0, len(err), MAX_DELTA):
                    yield "err", err[i:i + MAX_DELTA]
        # operator semantics: `a && b` skips b when a failed, `a || b` skips b when a succeeded, `;` always runs
        if op == "&&":
            skip = rc != 0
        elif op == "||":
            skip = rc == 0
        else:
            skip = False
        if skip and op in ("&&", "||"):
            pass
    yield "stop", rc, "COMPLETED"


def events(command, files, env=None, timeout=300):
    """The InvokeAgentRuntimeCommandStreamOutput ``chunk`` payloads, in order."""
    yield {"contentStart": {}}
    for ev in run(command, files, env, timeout):
        if ev[0] == "out":
            yield {"contentDelta": {"stdout": ev[1]}}
        elif ev[0] == "err":
            yield {"contentDelta": {"stderr": ev[1]}}
        else:
            yield {"contentStop": {"exitCode": ev[1], "status": ev[2]}}
