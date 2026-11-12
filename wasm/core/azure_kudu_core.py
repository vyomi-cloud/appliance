# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""App Service developer tooling = the Kudu (SCM) surface for a site, substrate-free (Nano + offline).

Vyomi extension under ``Microsoft.Web/sites/{site}/kudu/...`` mirroring the real Kudu REST API
(``https://{site}.scm.azurewebsites.net/api/...``), over the site's REAL stored state:

* ``vfs/{path}``      -- virtual file system rooted at ``/home`` (``/home/site/wwwroot``, ``/home/LogFiles``, ``/home/data``).
                          GET lists a directory / reads a file, PUT writes (``?mkdir=true`` makes a directory), DELETE removes.
                          Content is the site's own: the deployed package from the Deployment Center CI repo (``site-<name>``),
                          function sources (``function.json`` + code) of a Function App, ``hostingstart.html`` otherwise, plus the
                          log files generated from the site's invocation / WebJob / deployment history.  User edits layer on top
                          (the App Service Editor and the console write here).
* ``command``         -- POST {command, dir}: the Kudu console.  A real interpreter over that VFS and the site's app settings
                          (pwd cd ls cat echo > >> mkdir rm cp mv touch env head tail wc grep tree find ps whoami hostname date uname ...).
                          It is NOT an OS shell: there is no process to exec, so unknown commands fail like a missing binary.
* ``processes``       -- the process table, MODELLED from the site (runtime worker per instance, the scm/Kudu process, running
                          continuous WebJobs); CPU time is the sum of the real measured invocation durations.  Not an OS table.
* ``deployments``     -- the Deployment Center records (core/azure_webdeploy_core).
* ``settings``        -- Kudu settings (SCM_* knobs) stored on the site; ``environment`` -- runtime/version info.
* ``logstream``       -- cursor-based log tail (``?since=<iso>``) merged from invocations, WebJob runs, deployments and lifecycle.
* ``siteextensions``  -- the site-extension gallery + install state (Windows apps only, as in Azure; installing records state, the
                          extension's code is not executed).

Each function returns ``{"status": int, "body": ...}``.
"""
from __future__ import annotations

import datetime
import fnmatch
import hashlib
import re
import shlex

try:
    from core import ci_core as ci
except ImportError:                                    # Pyodide flat layout
    import ci_core as ci                               # type: ignore

ROOT = "/home"
WWW = ROOT + "/site/wwwroot"
MAX_FILE = 512 * 1024
MAX_FILES = 500

GALLERY = [
    {"id": "Microsoft.ApplicationInsights.AzureWebSites", "title": "Application Insights", "version": "2.22.0",
     "description": "Application Insights profiler and auto-instrumentation agent for App Service.", "authors": ["Microsoft"]},
    {"id": "Microsoft.AspNetCore.AzureAppServices.SiteExtension", "title": "ASP.NET Core Runtime Extension", "version": "8.0.11",
     "description": "ASP.NET Core runtime preview/servicing builds for App Service on Windows.", "authors": ["Microsoft"]},
    {"id": "AspNetCoreRuntime.9.0.x64", "title": "ASP.NET Core 9.0 (x64) Runtime", "version": "9.0.0",
     "description": "ASP.NET Core 9.0 x64 runtime site extension.", "authors": ["Microsoft"]},
    {"id": "python3111x64", "title": "Python 3.11.1 (x64)", "version": "3.11.1",
     "description": "Python 3.11.1 x64 installed as a site extension.", "authors": ["Microsoft"]},
    {"id": "Kudu.Services.Extensions.LogStreaming", "title": "Extended log streaming", "version": "1.4.2",
     "description": "Adds filtered log streaming to the Kudu dashboard.", "authors": ["Microsoft"]},
    {"id": "Microsoft.WebJobs.Dashboard", "title": "WebJobs Dashboard", "version": "1.1.0",
     "description": "Dashboard for WebJobs SDK invocations.", "authors": ["Microsoft"]},
    {"id": "DaaS", "title": "Diagnostics as a Service", "version": "3.2.7",
     "description": "Collect memory dumps and profiler traces for diagnosing slow or crashing apps.", "authors": ["Microsoft"]},
]


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _ok(body=None, status=200):
    return {"status": status, "body": body}


def _err(status, code, message):
    return {"status": status, "body": {"error": {"code": code, "message": message}}}


def _h(*parts, n=8):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


def handles(rest):
    return bool(rest) and rest[0].lower() == "kudu"


def _store(rec):
    k = rec.setdefault("_kudu", {})
    k.setdefault("files", {})        # user layer: path -> {"content": str, "mtime": iso}
    k.setdefault("dirs", [])
    k.setdefault("deleted", [])
    k.setdefault("extensions", {})
    k.setdefault("settings", {"SCM_COMMAND_IDLE_TIMEOUT": "60", "SCM_LOGSTREAM_TIMEOUT": "7200", "SCM_TRACE_LEVEL": "Error",
                              "SCM_USE_LIBGIT2SHARP_REPOSITORY": "0", "WEBSITE_SCM_ALWAYS_ON_ENABLED": "0"})
    k.setdefault("fslog", [])        # lines written by the console to /home/LogFiles via echo >>
    return k


def _is_fn(rec):
    return "functionapp" in (rec.get("kind") or "").lower()


def _is_linux(rec):
    return bool(rec["properties"].get("reserved"))


# ── virtual file system ──────────────────────────────────────────────────────────────────────
def _log_lines(rec):
    """Every log line the site really produced, oldest first: (iso, source, text)."""
    out = []
    for e in rec.get("_invocationlog") or []:
        ok = e.get("ok")
        txt = (f"Executed 'Functions.{e.get('function')}' ({'Succeeded' if ok else 'Failed'}, Duration={e.get('durationMs')}ms, status={e.get('status')})"
               + ("" if ok else f" -- {e.get('error')}"))
        out.append((e.get("timestamp") or "", "Application" if ok else "Application", txt))
    for kind, bucket in (rec.get("_webjobs") or {}).items():
        for name, j in bucket.items():
            for r in j.get("history") or []:
                out.append((r.get("start_time") or "", "WebJob",
                            f"[webjob {kind}/{name}] {r.get('status')} in {r.get('duration')}: {str(r.get('output') or r.get('error') or '').strip()[:300]}"))
    for d in (rec.get("_webdeploy") or {}).get("deployments") or []:
        out.append((d.get("start_time") or "", "Deployment", f"Deployment {str(d.get('id'))[:8]} {d.get('status_text')}: {d.get('message')}"))
    for t, msg in rec.get("_sitelog") or []:
        out.append((t, "Platform", msg))
    out.append((rec.get("_created") or "", "Platform", f"Site {rec['name']} created ({rec.get('kind')})"))
    out.sort(key=lambda x: x[0])
    return out


def _generated(rec):
    f = {}
    name = rec["name"]
    if _is_fn(rec):
        f[WWW + "/host.json"] = '{\n  "version": "2.0"\n}\n'
        for fname, fn in (rec.get("_functions") or {}).items():
            f[f"{WWW}/{fname}/function.json"] = ('{\n  "bindings": [{"authLevel": "function", "type": "httpTrigger", "direction": "in", "name": "req", '
                                                   '"methods": ["get", "post"]}, {"type": "http", "direction": "out", "name": "$return"}],\n'
                                                   f'  "scriptFile": "__init__.py", "entryPoint": "{fn.get("_entry", "main")}"\n}}\n')
            f[f"{WWW}/{fname}/__init__.py"] = fn.get("_code") or ""
    else:
        try:
            db = ci.get_db(rec)
            repo = f"site-{name}"
            if repo in db["repos"]:
                for p, data in ci.tree(db, repo).items():
                    try:
                        f[f"{WWW}/{p.lstrip('/')}"] = data.decode("utf-8")
                    except (UnicodeDecodeError, AttributeError):
                        f[f"{WWW}/{p.lstrip('/')}"] = "[binary file]"
        except Exception:
            pass
        if not any(p.startswith(WWW) for p in f):
            f[WWW + "/hostingstart.html"] = (f"<!DOCTYPE html>\n<html><head><title>{name}</title></head>\n<body><h1>Your web app is running and waiting for your content</h1>\n"
                                             f"<p>{name}.{'azurewebsites.net'}</p></body></html>\n")
    log = "".join(f"{t} {txt}\n" for t, src, txt in _log_lines(rec))
    f[ROOT + "/LogFiles/kudu/trace/kudu.log"] = log
    f[ROOT + "/LogFiles/Application/functions.log" if _is_fn(rec) else ROOT + "/LogFiles/Application/app.log"] = "".join(
        f"{t} {txt}\n" for t, src, txt in _log_lines(rec) if src in ("Application", "WebJob"))
    f[ROOT + "/LogFiles/deployments.log"] = "".join(f"{t} {txt}\n" for t, src, txt in _log_lines(rec) if src == "Deployment")
    f[ROOT + "/data/.vyomi-site"] = f"{rec['id']}\n"
    return f


def _view(rec):
    """Effective file map: generated, overlaid by the user layer, minus deletions."""
    k = _store(rec)
    f = _generated(rec)
    for p, v in k["files"].items():
        f[p] = v["content"]
    for d in k["deleted"]:
        for p in [p for p in f if p == d or p.startswith(d + "/")]:
            f.pop(p, None)
    return f


def _dirs(files, k):
    ds = {ROOT, ROOT + "/site", WWW, ROOT + "/LogFiles", ROOT + "/data"}
    ds.update(k["dirs"])
    for p in files:
        parts = p.split("/")
        for i in range(2, len(parts)):
            ds.add("/".join(parts[:i]))
    return ds


def _norm(path, cwd=ROOT):
    if not path:
        return cwd
    if not path.startswith("/"):
        path = cwd.rstrip("/") + "/" + path
    out = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if out:
                out.pop()
            continue
        out.append(seg)
    return "/" + "/".join(out)


def _vpath(tokens):
    p = "/" + "/".join(tokens)
    if p == "/":
        return ROOT
    return p if p.startswith(ROOT) else ROOT + p


def _mtime(rec, p, k):
    return (k["files"].get(p) or {}).get("mtime") or rec.get("_created") or _now()


def _entry(rec, p, files, dirs, k):
    isdir = p in dirs
    name = p.rsplit("/", 1)[-1]
    return {"name": name, "size": 0 if isdir else len(files[p].encode()), "mtime": _mtime(rec, p, k),
            "mime": "inode/directory" if isdir else "text/plain", "path": p, "href": f"{p}/" if isdir else p}


def _list(rec, p, files, dirs, k):
    pre = p.rstrip("/") + "/"
    kids = set()
    for q in list(files) + list(dirs):
        if q.startswith(pre) and q != p:
            kids.add(pre + q[len(pre):].split("/", 1)[0])
    return [_entry(rec, q, files, dirs, k) for q in sorted(kids, key=lambda q: (q not in dirs, q))]


def _write(rec, p, content):
    k = _store(rec)
    files = _view(rec)
    if len(content.encode()) > MAX_FILE:
        return _err(413, "RequestEntityTooLarge", f"File exceeds {MAX_FILE} bytes.")
    if p not in files and len(files) >= MAX_FILES:
        return _err(409, "Conflict", f"The site file store is limited to {MAX_FILES} files.")
    if p in _dirs(files, k):
        return _err(409, "Conflict", f"'{p}' is a directory.")
    if not p.startswith(ROOT + "/") or p.endswith("/"):
        return _err(400, "BadRequest", "Invalid path.")
    parent = p.rsplit("/", 1)[0]
    if parent not in _dirs(files, k):
        k["dirs"].append(parent)
    k["files"][p] = {"content": content, "mtime": _now()}
    if p in k["deleted"]:
        k["deleted"].remove(p)
    return None


def _remove(rec, p):
    k = _store(rec)
    files = _view(rec)
    dirs = _dirs(files, k)
    if p in (ROOT, WWW, ROOT + "/site"):
        return _err(409, "Conflict", f"'{p}' is a protected directory.")
    if p not in files and p not in dirs:
        return _err(404, "NotFound", f"'{p}' was not found.")
    for q in [q for q in k["files"] if q == p or q.startswith(p + "/")]:
        del k["files"][q]
    k["dirs"] = [d for d in k["dirs"] if not (d == p or d.startswith(p + "/"))]
    if p in _generated(rec) or any(q.startswith(p + "/") for q in _generated(rec)):
        k["deleted"].append(p)
    return None


def _vfs(rec, rest, method, payload, query):
    k = _store(rec)
    p = _vpath(rest)
    files = _view(rec)
    dirs = _dirs(files, k)
    if method == "GET":
        if p in dirs:
            return _ok(_list(rec, p, files, dirs, k))
        if p in files:
            return _ok({"path": p, "content": files[p], "size": len(files[p].encode()), "mtime": _mtime(rec, p, k)})
        return _err(404, "NotFound", f"'{p}' was not found.")
    if rec["properties"].get("state") == "Stopped" and method != "GET":
        return _err(409, "SiteStopped", "The app is stopped; start it before editing its files.")
    if method == "PUT":
        if (query or {}).get("mkdir") in (True, "true", "True"):
            if p in files:
                return _err(409, "Conflict", f"'{p}' is a file.")
            if not p.startswith(ROOT + "/"):
                return _err(400, "BadRequest", "Invalid path.")
            if p not in dirs:
                k["dirs"].append(p)
            return _ok({"path": p}, 201)
        c = (payload or {}).get("content")
        if not isinstance(c, str):
            return _err(400, "BadRequest", "Body must be {\"content\": \"<text>\"}.")
        existed = p in files
        e = _write(rec, p, c)
        return e or _ok({"path": p, "size": len(c.encode())}, 200 if existed else 201)
    if method == "DELETE":
        return _remove(rec, p) or _ok(None, 200)
    return _err(405, "MethodNotAllowed", f"{method} is not supported on vfs.")


# ── environment, settings, processes ─────────────────────────────────────────────────────────
def _runtime(rec):
    cfg = rec["properties"].get("siteConfig") or {}
    fx = cfg.get("linuxFxVersion") or cfg.get("windowsFxVersion") or ""
    if fx:
        return fx
    if _is_fn(rec):
        return (rec.get("_appsettings") or {}).get("FUNCTIONS_WORKER_RUNTIME", "dotnet")
    return "DOTNET|8.0" if _is_linux(rec) else "dotnet 8.0"


def _worker_name(rec):
    r = _runtime(rec).lower()
    if _is_fn(rec):
        return "Microsoft.Azure.WebJobs.Script.WebHost" if not _is_linux(rec) else "azure-functions-host"
    if "python" in r:
        return "gunicorn"
    if "node" in r:
        return "node"
    if "java" in r or "tomcat" in r:
        return "java"
    if "php" in r:
        return "apache2"
    return "dotnet" if _is_linux(rec) else "w3wp.exe"


def _processes(rec):
    running = rec["properties"].get("state") == "Running"
    if not running:
        return []
    inv = rec.get("_invocationlog") or []
    cpu_ms = sum(float(e.get("durationMs") or 0) for e in inv)
    n = int((rec["properties"].get("siteConfig") or {}).get("numberOfWorkers") or 1)
    out = []
    pid = 100 + int(_h(rec["id"], n=3), 16) % 400
    for i in range(max(1, n)):
        out.append({"id": pid, "name": _worker_name(rec), "instance": f"RD{_h(rec['id'], i, n=10).upper()}", "kind": "worker",
                    "cpuTimeMs": round(cpu_ms / max(1, n), 2), "workingSetMb": 60 + 14 * len(rec.get("_functions") or {}) + len(inv) // 8,
                    "threads": 12 + i, "startTime": rec.get("_created"), "handles": 220 + len(inv), "modeled": True})
        pid += 7
    out.append({"id": pid + 3, "name": "kudu" if _is_linux(rec) else "KuduService", "instance": f"RD{_h(rec['id'], 0, n=10).upper()}", "kind": "scm",
                "cpuTimeMs": 0, "workingSetMb": 48, "threads": 9, "startTime": rec.get("_created"), "handles": 180, "modeled": True})
    for name, j in ((rec.get("_webjobs") or {}).get("continuous") or {}).items():
        if j.get("status") == "Running":
            out.append({"id": pid + 11, "name": f"webjob:{name}", "instance": f"RD{_h(rec['id'], 0, n=10).upper()}", "kind": "webjob",
                        "cpuTimeMs": 0, "workingSetMb": 22, "threads": 4, "startTime": rec.get("_created"), "handles": 90, "modeled": True})
            pid += 5
    return out


def _env(rec):
    p = rec["properties"]
    e = {"WEBSITE_SITE_NAME": rec["name"], "WEBSITE_HOSTNAME": p.get("defaultHostName"), "WEBSITE_INSTANCE_ID": _h(rec["id"], "inst", n=32),
         "WEBSITE_RESOURCE_GROUP": rec.get("_rg"), "REGION_NAME": rec.get("location"), "HOME": ROOT, "HOSTNAME": f"{rec['name']}-{_h(rec['id'], n=6)}",
         "APPSETTING_WEBSITE_SITE_NAME": rec["name"], "WEBSITE_OS": "linux" if _is_linux(rec) else "windows", "WEBSITE_RUNTIME": _runtime(rec)}
    for kk, v in (rec.get("_appsettings") or {}).items():
        e[kk] = str(v)
        e["APPSETTING_" + kk] = str(v)
    for kk, v in (rec.get("_connectionstrings") or {}).items():
        t = (v or {}).get("type") or "Custom"
        e[f"{t.upper()}CONNSTR_{kk}"] = str((v or {}).get("value", ""))
    return e


# ── console ──────────────────────────────────────────────────────────────────────────────────
class _Fail(Exception):
    pass


def _run_one(rec, argv, cwd, stdin, files, dirs, k, out_state):
    c, a = argv[0], argv[1:]
    if c in ("pwd",):
        return cwd + "\n"
    if c == "cd":
        t = _norm(a[0] if a else ROOT, cwd)
        if t not in dirs:
            raise _Fail(f"cd: {a[0] if a else t}: No such file or directory")
        out_state["cwd"] = t
        return ""
    if c in ("ls", "dir"):
        flags = [x for x in a if x.startswith("-")]
        tg = [x for x in a if not x.startswith("-")] or ["."]
        res = []
        for t in tg:
            p = _norm(t, cwd)
            if p in files:
                res.append(p.rsplit("/", 1)[-1])
            elif p in dirs:
                ent = _list(rec, p, files, dirs, k)
                if "-l" in flags or "-la" in flags or "-al" in flags:
                    res += [f"{'d' if e['mime'] == 'inode/directory' else '-'}rw-r--r-- 1 app app {e['size']:>7} {e['mtime'][:16]} {e['name']}" for e in ent]
                else:
                    res += [e["name"] + ("/" if e["mime"] == "inode/directory" else "") for e in ent]
            else:
                raise _Fail(f"ls: cannot access '{t}': No such file or directory")
        return "\n".join(res) + ("\n" if res else "")
    if c in ("cat", "type"):
        if not a:
            return stdin or ""
        o = ""
        for t in a:
            p = _norm(t, cwd)
            if p in dirs:
                raise _Fail(f"cat: {t}: Is a directory")
            if p not in files:
                raise _Fail(f"cat: {t}: No such file or directory")
            o += files[p]
        return o
    if c == "echo":
        return " ".join(a) + "\n"
    if c in ("head", "tail"):
        n = 10
        args = list(a)
        if len(args) >= 2 and args[0] == "-n":
            n = int(args[1]); args = args[2:]
        text = stdin if not args else (files.get(_norm(args[0], cwd)) if _norm(args[0], cwd) in files else None)
        if text is None:
            raise _Fail(f"{c}: cannot open '{args[0]}' for reading: No such file or directory")
        ls = text.splitlines()
        return "\n".join(ls[:n] if c == "head" else ls[-n:]) + "\n"
    if c == "wc":
        text = stdin if not a else files.get(_norm(a[-1], cwd))
        if text is None:
            raise _Fail(f"wc: {a[-1]}: No such file or directory")
        return f"{len(text.splitlines())} {len(text.split())} {len(text.encode())}\n"
    if c == "grep":
        pats = [x for x in a if not x.startswith("-")]
        if not pats:
            raise _Fail("grep: missing pattern")
        rx = re.compile(pats[0], re.I if "-i" in a else 0)
        srcs = pats[1:]
        text = stdin if not srcs else "".join(files.get(_norm(s, cwd), "") for s in srcs)
        return "".join(l + "\n" for l in text.splitlines() if rx.search(l))
    if c == "mkdir":
        for t in [x for x in a if not x.startswith("-")]:
            p = _norm(t, cwd)
            if p in files:
                raise _Fail(f"mkdir: cannot create directory '{t}': File exists")
            if p not in dirs:
                k["dirs"].append(p)
        return ""
    if c in ("touch",):
        for t in a:
            p = _norm(t, cwd)
            if p not in files:
                e = _write(rec, p, "")
                if e:
                    raise _Fail(e["body"]["error"]["message"])
        return ""
    if c in ("rm", "del", "rmdir"):
        for t in [x for x in a if not x.startswith("-")]:
            p = _norm(t, cwd)
            if p in dirs and "-r" not in a and "-rf" not in a and c != "rmdir":
                raise _Fail(f"rm: cannot remove '{t}': Is a directory")
            e = _remove(rec, p)
            if e and "-f" not in a and "-rf" not in a:
                raise _Fail(f"rm: cannot remove '{t}': " + ("No such file or directory" if e["status"] == 404 else e["body"]["error"]["message"]))
        return ""
    if c in ("cp", "mv", "copy", "move"):
        ar = [x for x in a if not x.startswith("-")]
        if len(ar) != 2:
            raise _Fail(f"{c}: missing file operand")
        s, d = _norm(ar[0], cwd), _norm(ar[1], cwd)
        if s not in files:
            raise _Fail(f"{c}: cannot stat '{ar[0]}': No such file or directory")
        if d in dirs:
            d = d + "/" + s.rsplit("/", 1)[-1]
        e = _write(rec, d, files[s])
        if e:
            raise _Fail(e["body"]["error"]["message"])
        if c in ("mv", "move"):
            _remove(rec, s)
        return ""
    if c in ("env", "printenv", "set"):
        e = _env(rec)
        if a and c == "printenv":
            return (e.get(a[0], "") + "\n") if a[0] in e else ""
        return "".join(f"{kk}={v}\n" for kk, v in sorted(e.items()))
    if c in ("ps", "tasklist"):
        rows = ["  PID NAME                              CPU(ms)   MEM(MB)"] + [
            f"{p['id']:>5} {p['name']:<32} {p['cpuTimeMs']:>9} {p['workingSetMb']:>9}" for p in _processes(rec)]
        return "\n".join(rows) + "\n"
    if c == "whoami":
        return ("app\n" if _is_linux(rec) else f"IIS APPPOOL\\{rec['name']}\n")
    if c == "hostname":
        return _env(rec)["HOSTNAME"] + "\n"
    if c == "date":
        return _now() + "\n"
    if c == "uname":
        return ("Linux " + _env(rec)["HOSTNAME"] + " 5.15.0-azure x86_64\n") if _is_linux(rec) else "Windows_NT\n"
    if c == "tree":
        base = _norm(a[0] if a else ".", cwd)
        lines = [base]

        def walk(p, ind):
            for e in _list(rec, p, files, dirs, k):
                lines.append(f"{ind}{e['name']}{'/' if e['mime'] == 'inode/directory' else ''}")
                if e["mime"] == "inode/directory":
                    walk(e["path"], ind + "  ")
        if base not in dirs:
            raise _Fail(f"tree: {base}: No such directory")
        walk(base, "  ")
        return "\n".join(lines) + "\n"
    if c == "find":
        base = _norm(a[0] if a and not a[0].startswith("-") else ".", cwd)
        pat = a[a.index("-name") + 1] if "-name" in a else "*"
        return "".join(p + "\n" for p in sorted(set(files) | dirs) if (p == base or p.startswith(base.rstrip("/") + "/")) and fnmatch.fnmatch(p.rsplit("/", 1)[-1], pat))
    if c in ("python", "python3", "node", "dotnet", "java", "php") and a and a[0] in ("--version", "-v", "-V", "version"):
        r = _runtime(rec)
        return f"{c} (site runtime: {r})\n"
    if c == "help":
        return ("Vyomi Kudu console -- commands operate on the site's virtual file system and app settings:\n"
                "  pwd cd ls dir cat type echo head tail wc grep mkdir touch rm cp mv env printenv ps whoami hostname date uname tree find\n"
                "  Redirection: > and >> to a file; pipes: |. This is not an OS shell; programs cannot be executed.\n")
    raise _Fail(f"{c}: command not found")


def _command(rec, payload):
    cmd = str((payload or {}).get("command") or "").strip()
    cwd = _norm((payload or {}).get("dir") or ROOT)
    if not cmd:
        return _err(400, "BadRequest", "A command is required.")
    if len(cmd) > 2000:
        return _err(400, "BadRequest", "Command too long.")
    if rec["properties"].get("state") == "Stopped":
        return _err(409, "SiteStopped", "The app is stopped; the Kudu console is unavailable until it is started.")
    k = _store(rec)
    out, err, code = "", "", 0
    state = {"cwd": cwd}
    for seg in re.split(r"\s*&&\s*", cmd):
        try:
            files = _view(rec)
            dirs = _dirs(files, k)
            redir = None
            m = re.match(r"^(.*?)\s*(>>|>)\s*(\S+)\s*$", seg)
            if m and "|" not in m.group(1)[-1:]:
                seg, redir = m.group(1), (m.group(2), m.group(3))
            stdin = None
            res = ""
            for part in seg.split("|"):
                argv = shlex.split(part)
                if not argv:
                    raise _Fail("syntax error")
                res = _run_one(rec, argv, state["cwd"], stdin, files, dirs, k, state)
                stdin = res
            if redir:
                p = _norm(redir[1], state["cwd"])
                prev = files.get(p, "") if redir[0] == ">>" else ""
                e = _write(rec, p, prev + res)
                if e:
                    raise _Fail(e["body"]["error"]["message"])
                if p.startswith(ROOT + "/LogFiles"):
                    k["fslog"].append((_now(), f"[console] wrote {p}"))
                res = ""
            out += res
        except _Fail as e:
            err += str(e) + "\n"
            code = 1
            break
        except ValueError as e:
            err += f"parse error: {e}\n"
            code = 2
            break
    rec.setdefault("_sitelog", []).append((_now(), f"[kudu] command: {cmd[:120]} -> exit {code}"))
    del rec["_sitelog"][:-200]
    return _ok({"Output": out, "Error": err, "ExitCode": code, "Dir": state["cwd"]})


# ── log stream ───────────────────────────────────────────────────────────────────────────────
def _logstream(rec, query):
    since = str((query or {}).get("since") or "")
    kind = str((query or {}).get("type") or "all").lower()
    lines = _log_lines(rec)
    for t, msg in _store(rec)["fslog"]:
        lines.append((t, "Application", msg))
    lines.sort(key=lambda x: x[0])
    if kind in ("application", "app service logs", "app"):
        lines = [x for x in lines if x[1] in ("Application", "WebJob")]
    elif kind in ("platform",):
        lines = [x for x in lines if x[1] in ("Platform", "Deployment")]
    lines = [x for x in lines if x[0] > since] if since else lines[-200:]
    cfg = (((rec.get("_logs") or {}).get("applicationLogs") or {}).get("fileSystem") or {}).get("level") or "Off"
    return _ok({"cursor": lines[-1][0] if lines else since, "applicationLogging": cfg,
                "lines": [{"time": t, "source": s, "text": x} for t, s, x in lines]})


# ── extensions ───────────────────────────────────────────────────────────────────────────────
def _ext_view(e, installed):
    d = dict(e)
    d["installed"] = installed is not None
    if installed:
        d["installedVersion"], d["installedAt"] = installed["version"], installed["time"]
    return d


def _extensions(rec, rest, method, payload, query):
    if _is_linux(rec):
        return _err(400, "BadRequest", "Site extensions are only supported on Windows apps; this is a Linux app.")
    k = _store(rec)
    inst = k["extensions"]
    if not rest:
        if method != "GET":
            return _err(405, "MethodNotAllowed", "Collection supports GET only.")
        scope = (query or {}).get("scope", "gallery")
        filt = str((query or {}).get("filter") or "").lower()
        rows = [_ext_view(e, inst.get(e["id"])) for e in GALLERY if not filt or filt in e["id"].lower() or filt in e["title"].lower()]
        if scope == "installed":
            rows = [r for r in rows if r["installed"]]
        return _ok({"value": rows})
    eid = rest[0]
    ent = next((e for e in GALLERY if e["id"].lower() == eid.lower()), None)
    if ent is None:
        return _err(404, "NotFound", f"Site extension '{eid}' was not found in the gallery.")
    if method == "GET":
        return _ok(_ext_view(ent, inst.get(ent["id"])))
    if method == "PUT":
        if rec["properties"].get("state") == "Stopped":
            return _err(409, "SiteStopped", "Start the app before installing an extension.")
        if ent["id"] in inst:
            return _err(409, "Conflict", f"'{ent['id']}' is already installed (uninstall it first).")
        inst[ent["id"]] = {"version": ent["version"], "time": _now()}
        rec.setdefault("_sitelog", []).append((_now(), f"[extensions] installed {ent['id']} {ent['version']}"))
        k["files"][f"{ROOT}/SiteExtensions/{ent['id']}/extension.txt"] = {"content": f"{ent['title']} {ent['version']}\n", "mtime": _now()}
        return _ok(_ext_view(ent, inst[ent["id"]]), 201)
    if method == "DELETE":
        if ent["id"] not in inst:
            return _err(404, "NotFound", f"'{ent['id']}' is not installed.")
        del inst[ent["id"]]
        k["files"].pop(f"{ROOT}/SiteExtensions/{ent['id']}/extension.txt", None)
        rec.setdefault("_sitelog", []).append((_now(), f"[extensions] uninstalled {ent['id']}"))
        return _ok(True)
    return _err(405, "MethodNotAllowed", f"{method} is not supported.")


# ── dispatch ─────────────────────────────────────────────────────────────────────────────────
def dispatch(state, rec, rest, method, payload, query=None):
    """``rest`` = tokens after ``kudu`` is rest[1:]; first is the Kudu API segment (``api`` prefix optional)."""
    toks = list(rest[1:])
    if toks and toks[0].lower() == "api":
        toks = toks[1:]
    if not toks:
        return _ok({"site": rec["name"], "scm": f"{rec['name']}.scm.azurewebsites.net",
                    "apis": ["vfs", "command", "processes", "deployments", "settings", "environment", "logstream", "siteextensions"]})
    seg, tail = toks[0].lower(), toks[1:]
    method = method.upper()
    if seg == "vfs":
        return _vfs(rec, tail, method, payload, query)
    if seg == "command":
        if method != "POST":
            return _err(405, "MethodNotAllowed", "command supports POST only.")
        return _command(rec, payload)
    if seg == "processes":
        if method != "GET":
            return _err(405, "MethodNotAllowed", "processes supports GET only.")
        ps = _processes(rec)
        if tail:
            pr = next((p for p in ps if str(p["id"]) == tail[0]), None)
            return _ok(pr) if pr else _err(404, "NotFound", f"Process {tail[0]} was not found.")
        return _ok({"value": ps, "modeled": True,
                    "note": "Modelled from the site's runtime, instances and running WebJobs; not an operating-system process table."})
    if seg == "deployments":
        if method != "GET":
            return _err(405, "MethodNotAllowed", "deployments supports GET only.")
        deps = list(reversed((rec.get("_webdeploy") or {}).get("deployments") or []))
        return _ok({"value": [{k2: d.get(k2) for k2 in ("id", "status", "status_text", "author", "deployer", "message", "start_time", "end_time", "active")} for d in deps]})
    if seg == "settings":
        kst = _store(rec)["settings"]
        if method == "GET":
            return _ok(dict(kst))
        if method in ("POST", "PUT"):
            if not isinstance(payload, dict) or not payload:
                return _err(400, "BadRequest", "Body must be a JSON object of settings.")
            for kk, v in payload.items():
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(kk)):
                    return _err(400, "BadRequest", f"Invalid setting name '{kk}'.")
                kst[str(kk)] = str(v)
            return _ok(dict(kst))
        if method == "DELETE" and tail:
            kst.pop(tail[0], None)
            return _ok(None)
    if seg == "environment":
        return _ok({"version": "Vyomi-Kudu 1.0", "siteName": rec["name"], "os": "linux" if _is_linux(rec) else "windows",
                    "runtime": _runtime(rec), "instances": int((rec["properties"].get("siteConfig") or {}).get("numberOfWorkers") or 1),
                    "home": ROOT, "state": rec["properties"].get("state")})
    if seg == "logstream":
        return _logstream(rec, query)
    if seg == "siteextensions":
        return _extensions(rec, tail, method, payload, query)
    return _err(404, "NotFound", f"Kudu API '{seg}' is not supported.")
