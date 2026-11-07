# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Shared source-control + CI seam (substrate-free): repos, push events/webhooks, build jobs, logs, artifacts.

Every CI/CD surface (App Service / Function App Deployment Center, ACR Tasks, Cloud Run source deploy, Flux, Cloud
Build, CloudFormation Git sync, ...) talks to THIS module, never to a git host or a container runtime directly.

State lives in a plain dict ``db`` the caller owns (``holder.setdefault("_ci", ...)`` via :func:`get_db`), so it is
persisted with the owning resource record on both substrates.

Backends are pluggable, one pair per substrate:

* **Git host** (``set_git``) -- where commits live.
    - ``MemoryGit`` (default, both substrates): content-addressed commits/trees held in ``db``. Pushes arrive through
      this API (``commit_files`` / ``import_external``); it is NOT the git wire protocol.
    - ``GiteaGit`` (offline appliance, providers/ci_runner.py): a real Gitea container driven over its REST API, so
      ``git clone/push`` over HTTP work against a real server.
* **Builder** (``set_builder``) -- what a build job does.
    - ``PackageBuilder`` (default, both substrates): validates the tree (Dockerfile syntax + COPY sources,
      runtime detection), snapshots it into a deterministic content-addressed ``package`` artifact. It runs NO
      container: an ``image`` job fails with that reason rather than reporting a fake success.
    - ``BuildKitBuilder`` (offline appliance): the real BuildKit through ``docker build`` (``--pull=false``: only base
      images already on the host are used; nothing is fetched from a registry).
* **Fetcher** (``set_fetcher``) -- outbound HTTPS used ONLY to import from the user's own GitHub with a PAT they
  supplied (``import_external``). None on Nano (no outbound HTTP from the page) -> a clear "unavailable" error.

Nothing here invents a result: a missing backend / unreachable remote / failed build yields a ``Failed`` job with the
real reason in its log.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import io
import json
import re
import shlex
import tarfile
import time

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_BRANCH = re.compile(r"^[\w./-]{1,255}$")
_DOCKER_INSTR = {"FROM", "RUN", "CMD", "LABEL", "MAINTAINER", "EXPOSE", "ENV", "ADD", "COPY", "ENTRYPOINT", "VOLUME",
                 "USER", "WORKDIR", "ARG", "ONBUILD", "STOPSIGNAL", "HEALTHCHECK", "SHELL"}


class CiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(*parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode())
        h.update(b"\0")
    return h.hexdigest()


def get_db(holder: dict) -> dict:
    db = holder.setdefault("_ci", {})
    for k in ("repos", "jobs", "git", "artifacts", "connections"):
        db.setdefault(k, {})
    db.setdefault("seq", 0)
    return db


def _b(v) -> bytes:
    return v if isinstance(v, bytes) else str(v).encode()


# ── git backends ─────────────────────────────────────────────────────────────────────────────
class MemoryGit:
    """Commits + blobs in ``db['git'][repo]``: {commits: {sha: {parent, tree, message, author, time}}, branches, blobs}."""
    name = "memory"

    def ensure_repo(self, db, repo):
        db["git"].setdefault(repo, {"commits": {}, "branches": {}, "blobs": {}})

    def delete_repo(self, db, repo):
        db["git"].pop(repo, None)

    def head(self, db, repo, branch):
        return db["git"].get(repo, {}).get("branches", {}).get(branch)

    def branches(self, db, repo):
        return dict(db["git"].get(repo, {}).get("branches", {}))

    def tree(self, db, repo, ref):
        g = db["git"].get(repo) or {}
        sha = g.get("branches", {}).get(ref, ref)
        c = g.get("commits", {}).get(sha)
        if not c:
            return None
        return {p: base64.b64decode(g["blobs"][bs]) for p, bs in c["tree"].items()}

    def commit(self, db, repo, branch, files, message, author):
        g = db["git"][repo]
        parent = g["branches"].get(branch)
        tree = dict(g["commits"][parent]["tree"]) if parent else {}
        for path, content in files.items():
            if content is None:
                tree.pop(path, None)
            else:
                data = _b(content)
                bs = _sha("blob", data)
                g["blobs"][bs] = base64.b64encode(data).decode()
                tree[path] = bs
        ts = _now()
        sha = _sha("commit", parent or "", json.dumps(tree, sort_keys=True), message, author, ts, db["seq"])
        g["commits"][sha] = {"parent": parent, "tree": tree, "message": message, "author": author, "time": ts}
        g["branches"][branch] = sha
        return sha

    def log(self, db, repo, branch, limit=30):
        g, out = db["git"].get(repo) or {}, []
        sha = g.get("branches", {}).get(branch)
        while sha and len(out) < limit:
            c = g["commits"][sha]
            out.append({"sha": sha, "message": c["message"], "author": c["author"], "time": c["time"]})
            sha = c["parent"]
        return out

    def clone_url(self, db, repo):
        return None


class GiteaGit:
    """Gitea over its REST API. ``http(method, url, headers, body) -> (status, bytes)`` is injected (urllib offline)."""
    name = "gitea"

    def __init__(self, base_url, user, token, http, owner=None):
        self.base, self.user, self.owner, self.http = base_url.rstrip("/"), user, owner or user, http
        self.h = {"Authorization": "token " + token, "Content-Type": "application/json", "Accept": "application/json"}

    def _call(self, method, path, body=None, ok=(200, 201, 204)):
        st, raw = self.http(method, f"{self.base}/api/v1{path}", self.h, json.dumps(body).encode() if body is not None else None)
        if st not in ok:
            raise CiError("GitBackendError", f"Gitea {method} {path} -> HTTP {st}: {raw[:200].decode(errors='replace')}", 502)
        return json.loads(raw) if raw and raw.lstrip()[:1] in (b"{", b"[") else raw

    def ensure_repo(self, db, repo):
        st, _ = self.http("GET", f"{self.base}/api/v1/repos/{self.owner}/{repo}", self.h, None)
        if st == 404:
            self._call("POST", "/user/repos", {"name": repo, "auto_init": True, "default_branch": "main", "private": True})
        elif st != 200:
            raise CiError("GitBackendError", f"Gitea repo lookup -> HTTP {st}", 502)

    def delete_repo(self, db, repo):
        self.http("DELETE", f"{self.base}/api/v1/repos/{self.owner}/{repo}", self.h, None)

    def head(self, db, repo, branch):
        st, raw = self.http("GET", f"{self.base}/api/v1/repos/{self.owner}/{repo}/branches/{branch}", self.h, None)
        return json.loads(raw)["commit"]["id"] if st == 200 else None

    def branches(self, db, repo):
        return {b["name"]: b["commit"]["id"] for b in self._call("GET", f"/repos/{self.owner}/{repo}/branches")}

    def tree(self, db, repo, ref):
        st, raw = self.http("GET", f"{self.base}/api/v1/repos/{self.owner}/{repo}/archive/{ref}.tar.gz", self.h, None)
        if st != 200:
            return None
        out = {}
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
            for m in tf.getmembers():
                if m.isfile():
                    out[m.name.split("/", 1)[1] if "/" in m.name else m.name] = tf.extractfile(m).read()
        return out

    def commit(self, db, repo, branch, files, message, author):
        existing = {}
        st, raw = self.http("GET", f"{self.base}/api/v1/repos/{self.owner}/{repo}/git/trees/{branch}?recursive=true&per_page=1000", self.h, None)
        if st == 200:
            existing = {e["path"]: e["sha"] for e in json.loads(raw).get("tree", []) if e.get("type") == "blob"}
        ops = []
        for path, content in files.items():
            if content is None:
                if path in existing:
                    ops.append({"operation": "delete", "path": path, "sha": existing[path]})
            elif path in existing:
                ops.append({"operation": "update", "path": path, "sha": existing[path], "content": base64.b64encode(_b(content)).decode()})
            else:
                ops.append({"operation": "create", "path": path, "content": base64.b64encode(_b(content)).decode()})
        body = {"message": message, "files": ops, "author": {"name": author, "email": "ci@vyomi.local"}}
        if st == 200:
            body["branch"] = branch
        else:
            body["new_branch"] = branch
        r = self._call("POST", f"/repos/{self.owner}/{repo}/contents", body)
        return r["commit"]["sha"]

    def log(self, db, repo, branch, limit=30):
        return [{"sha": c["sha"], "message": c["commit"]["message"], "author": c["commit"]["author"]["name"], "time": c["commit"]["author"]["date"]}
                for c in self._call("GET", f"/repos/{self.owner}/{repo}/commits?sha={branch}&limit={limit}")]

    def clone_url(self, db, repo):
        return f"{self.base}/{self.owner}/{repo}.git"


# ── builders ─────────────────────────────────────────────────────────────────────────────────
def parse_dockerfile(text: str):
    """Return (instructions, errors). Handles line continuations + comments; checks FROM first, known instructions."""
    lines, cur = [], ""
    for raw in text.splitlines():
        s = raw.strip()
        if not cur and (not s or s.startswith("#")):
            continue
        if s.endswith("\\"):
            cur += s[:-1] + " "
            continue
        lines.append((cur + s).strip())
        cur = ""
    if cur.strip():
        lines.append(cur.strip())
    instr, errs = [], []
    for ln in lines:
        op, _, arg = ln.partition(" ")
        op = op.upper()
        if op not in _DOCKER_INSTR:
            errs.append(f"unknown instruction '{op}'")
        elif not arg.strip() and op not in ("HEALTHCHECK",):
            errs.append(f"{op} requires arguments")
        else:
            instr.append((op, arg.strip()))
    if not instr or not any(o == "FROM" for o, _ in instr):
        errs.append("a Dockerfile must contain a FROM instruction")
    else:
        first = next(o for o, _ in instr if o != "ARG")
        if first != "FROM":
            errs.append("the first instruction must be FROM (only ARG may precede it)")
    return instr, errs


def detect_runtime(tree: dict) -> str:
    names = set(tree)
    if "Dockerfile" in names:
        return "docker"
    for marker, rt in (("requirements.txt", "python"), ("pyproject.toml", "python"), ("package.json", "node"), ("pom.xml", "java"),
                       ("build.gradle", "java"), ("go.mod", "go"), ("composer.json", "php")):
        if marker in names:
            return rt
    if any(n.endswith((".csproj", ".sln")) for n in names):
        return "dotnet"
    return "static" if any(n.endswith(".html") for n in names) else "unknown"


def _pack(tree: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:       # uncompressed + fixed metadata -> deterministic digest
        for p in sorted(tree):
            ti = tarfile.TarInfo(p)
            ti.size, ti.mtime, ti.mode = len(tree[p]), 0, 0o644
            tf.addfile(ti, io.BytesIO(tree[p]))
    return buf.getvalue()


def _copy_sources_ok(instr, tree, ctx_dir=""):
    errs = []
    for op, arg in instr:
        if op not in ("COPY", "ADD") or "--from=" in arg:
            continue
        try:
            parts = [a for a in shlex.split(arg) if not a.startswith("--")]
        except ValueError:
            errs.append(f"{op} {arg}: unparsable"); continue
        for src in parts[:-1]:
            if src.startswith(("http://", "https://")) or src in (".", "./", "/"):
                continue
            s = src.lstrip("./")
            if "*" in s or "?" in s:
                import fnmatch
                if not any(fnmatch.fnmatch(p, s) for p in tree):
                    errs.append(f"{op} {src}: no files match in the build context")
            elif s not in tree and not any(p.startswith(s.rstrip("/") + "/") for p in tree):
                errs.append(f"{op} {src}: not found in the build context")
    return errs


class PackageBuilder:
    name = "package"
    runs_containers = False

    def build(self, job, tree, log):
        runtime = detect_runtime(tree)
        log(f"Detected runtime: {runtime}")
        if "Dockerfile" in tree and job["kind"] in ("image", "package"):
            instr, errs = parse_dockerfile(tree["Dockerfile"].decode(errors="replace"))
            errs += _copy_sources_ok(instr, tree)
            for e in errs:
                log(f"Dockerfile: {e}")
            if errs:
                return {"ok": False, "error": "Dockerfile validation failed"}
            log(f"Dockerfile OK: {len(instr)} instructions, base image {next(a for o, a in instr if o == 'FROM')}")
        if job["kind"] == "image":
            return {"ok": False, "error": "No container builder on this substrate (BuildKit is only available on the offline appliance); "
                                           "the Dockerfile was validated but no image was built."}
        data = _pack(tree)
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        log(f"Packaged {len(tree)} files, {len(data)} bytes -> {digest}")
        return {"ok": True, "artifact": {"type": "package", "digest": digest, "size": len(data), "files": len(tree), "runtime": runtime}}


class LayerBuilder:
    """Daemonless OCI image builder for substrates with no container runtime (Nano, offline without Docker).

    It builds REAL images: every COPY/ADD becomes a deterministic gzip'd tar layer (real sha256 diff-ids/digests), and
    ENV / WORKDIR / EXPOSE / CMD / ENTRYPOINT / LABEL / USER / VOLUME / ARG populate a real OCI image config. What it can
    NOT do is execute anything or pull anything: `RUN` needs a container, and a base image other than `scratch` (or a
    tag this builder produced earlier / an earlier stage of the same Dockerfile) has layers that cannot be fetched
    without registry egress. Those Dockerfiles FAIL with that reason; they are never reported as built."""
    name = "layers"
    runs_containers = False
    NOPE = "No container builder on this substrate (the Vyomi layer builder runs no commands and pulls no base images): "

    def __init__(self):
        self.images = {}        # tag -> {"config": bytes, "layers": [gz bytes], "repoTags": [tag]}

    # -- helpers --
    @staticmethod
    def _tar(files: dict) -> tuple:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
            dirs = set()
            for path in sorted(files):
                parts = path.strip("/").split("/")
                for i in range(1, len(parts)):
                    d = "/".join(parts[:i])
                    if d not in dirs:
                        dirs.add(d)
                        ti = tarfile.TarInfo(d)
                        ti.type, ti.mode, ti.mtime = tarfile.DIRTYPE, 0o755, 0
                        tf.addfile(ti)
                ti = tarfile.TarInfo(path.strip("/"))
                ti.size, ti.mode, ti.mtime = len(files[path]), 0o644, 0
                tf.addfile(ti, io.BytesIO(files[path]))
        raw = buf.getvalue()
        import gzip
        gz = io.BytesIO()
        with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0) as g:
            g.write(raw)
        return raw, gz.getvalue()

    @staticmethod
    def _expand(text, env):
        return re.sub(r"\$\{(\w+)\}|\$(\w+)", lambda m: str(env.get(m.group(1) or m.group(2), "")), text)

    @staticmethod
    def _exec_form(arg):
        a = arg.strip()
        if a.startswith("["):
            try:
                v = json.loads(a)
                if isinstance(v, list) and all(isinstance(x, str) for x in v):
                    return v
            except ValueError:
                pass
        return ["/bin/sh", "-c", a]

    def _ignored(self, tree):
        pats = [l.strip() for l in tree.get(".dockerignore", b"").decode(errors="replace").splitlines() if l.strip() and not l.startswith("#")]
        if not pats:
            return tree
        import fnmatch
        return {k: v for k, v in tree.items() if not any(fnmatch.fnmatch(k, p.lstrip("/")) or k.startswith(p.strip("/") + "/") for p in pats)}

    # -- build --
    def build(self, job, tree, log):
        import fnmatch
        if "Dockerfile" not in tree:
            return {"ok": False, "error": "No Dockerfile in the repository root."}
        instr, errs = parse_dockerfile(tree["Dockerfile"].decode(errors="replace"))
        errs += _copy_sources_ok([(o, a) for o, a in instr if "--from=" not in a], tree)
        if errs:
            for e in errs:
                log(f"Dockerfile: {e}")
            return {"ok": False, "error": "Dockerfile validation failed"}
        ctx = self._ignored({k: v for k, v in tree.items() if k not in ("Dockerfile", ".dockerignore")} | {"Dockerfile": tree["Dockerfile"]})
        build_args = dict(a.split("=", 1) for a in job["spec"].get("buildArgs", []) if "=" in a)
        stages, cur, global_args = {}, None, {}
        history = []

        def new_stage(base, alias):
            nonlocal cur
            if base == "scratch":
                cur = {"fs": {}, "layers": [], "diff": [], "cfg": {"Env": [], "Labels": {}}, "env": {}, "workdir": "/", "alias": alias}
            elif base in stages:
                o = stages[base]
                cur = {"fs": dict(o["fs"]), "layers": list(o["layers"]), "diff": list(o["diff"]),
                       "cfg": json.loads(json.dumps(o["cfg"])), "env": dict(o["env"]), "workdir": o["workdir"], "alias": alias}
            elif base in self.images:
                img = self.images[base]
                c = json.loads(img["config"])
                cur = {"fs": {}, "layers": list(img["layers"]), "diff": list(c["rootfs"]["diff_ids"]), "cfg": c.get("config") or {"Env": [], "Labels": {}},
                       "env": dict(e.split("=", 1) for e in (c.get("config") or {}).get("Env", [])), "workdir": (c.get("config") or {}).get("WorkingDir") or "/", "alias": alias}
            else:
                raise ValueError(self.NOPE + f"base image '{base}' has layers that cannot be pulled here (only FROM scratch, an earlier stage, "
                                 "or an image this builder built can be used).")
            if alias:
                stages[alias] = cur
            cur.setdefault("cfg", {}).setdefault("Env", [])

        def add_layer(files, note):
            raw, gz = self._tar(files)
            cur["layers"].append(gz)
            cur["diff"].append("sha256:" + hashlib.sha256(raw).hexdigest())
            cur["fs"].update(files)
            history.append({"created_by": note, "created": "1970-01-01T00:00:00Z"})

        try:
            for op, arg in instr:
                if op == "ARG":
                    k, _, v = arg.partition("=")
                    val = build_args.get(k.strip(), v.strip())
                    if cur is None:
                        global_args[k.strip()] = val
                    else:
                        cur["env"][k.strip()] = val
                    continue
                if op == "FROM":
                    toks = arg.split()
                    alias = toks[toks.index("AS") + 1] if "AS" in toks else (toks[toks.index("as") + 1] if "as" in toks else None)
                    base = self._expand([t for t in toks if not t.startswith("--")][0], global_args)
                    new_stage(base, alias)
                    log(f"FROM {base}" + (f" AS {alias}" if alias else ""))
                    last = cur
                    continue
                if op == "RUN":
                    raise ValueError(self.NOPE + f"`RUN {arg[:80]}` needs a container to execute in.")
                env = cur["env"]
                if op in ("COPY", "ADD"):
                    toks = shlex.split(self._expand(arg, env))
                    frm = None
                    flags = [t for t in toks if t.startswith("--")]
                    for f in flags:
                        if f.startswith("--from="):
                            frm = f[7:]
                        elif not f.startswith("--chown=") and not f.startswith("--chmod="):
                            raise ValueError(f"{op}: flag {f} is not supported by the layer builder.")
                    parts = [t for t in toks if not t.startswith("--")]
                    if len(parts) < 2:
                        raise ValueError(f"{op} requires at least a source and a destination.")
                    *srcs, dest = parts
                    if frm is not None:
                        if frm not in stages:
                            raise ValueError(f"{op} --from={frm}: no such earlier stage (pulling an external image is not possible here).")
                        src_fs = stages[frm]["fs"]
                    else:
                        src_fs = ctx
                    if any(sx.startswith(("http://", "https://")) for sx in srcs):
                        raise ValueError(f"{op}: remote URL sources need network egress and are not fetched here.")
                    import posixpath
                    d = posixpath.normpath(dest if dest.startswith("/") else (cur["workdir"].rstrip("/") + "/" + dest)) + ("/" if dest.endswith("/") or dest in (".", "./") else "")
                    dir_dest = dest.endswith("/") or len(srcs) > 1 or any(sx in (".", "./") or sx.endswith("/") for sx in srcs)
                    files = {}
                    for sx in srcs:
                        sp = sx.lstrip("./") if sx not in (".", "./") else ""
                        sp = sp.strip("/")
                        hits = {k: v for k, v in src_fs.items() if (not sp) or k == sp or k.startswith(sp + "/")
                                or fnmatch.fnmatch(k, sp) or any(fnmatch.fnmatch(k, sp + "/*") for _ in [0])}
                        if not hits:
                            raise ValueError(f"{op} {sx}: not found in the {'stage' if frm else 'build context'}.")
                        for k, v in hits.items():
                            if sp and k == sp and not dir_dest:
                                files[d.strip("/")] = v
                            else:
                                rel = k[len(sp) + 1:] if (sp and k.startswith(sp + "/")) else (k if not sp else k.rsplit("/", 1)[-1])
                                files[(d.rstrip("/") + "/" + rel).strip("/")] = v
                    if op == "ADD":
                        pass
                    add_layer(files, f"{op} {arg}")
                    continue
                if op == "ENV":
                    toks = shlex.split(self._expand(arg, env)) if "=" in arg.split()[0] else None
                    pairs = [t.split("=", 1) for t in toks] if toks else [arg.split(None, 1)]
                    for k, v in pairs:
                        env[k] = v
                        cur["cfg"]["Env"] = [e for e in cur["cfg"]["Env"] if not e.startswith(k + "=")] + [f"{k}={v}"]
                elif op == "WORKDIR":
                    w = self._expand(arg, env)
                    cur["workdir"] = w if w.startswith("/") else cur["workdir"].rstrip("/") + "/" + w
                    cur["cfg"]["WorkingDir"] = cur["workdir"]
                elif op == "EXPOSE":
                    cur["cfg"].setdefault("ExposedPorts", {}).update({(p if "/" in p else p + "/tcp"): {} for p in self._expand(arg, env).split()})
                elif op == "CMD":
                    cur["cfg"]["Cmd"] = self._exec_form(arg)
                elif op == "ENTRYPOINT":
                    cur["cfg"]["Entrypoint"] = self._exec_form(arg)
                elif op == "LABEL":
                    for t in shlex.split(self._expand(arg, env)):
                        if "=" in t:
                            k, v = t.split("=", 1)
                            cur["cfg"].setdefault("Labels", {})[k] = v
                elif op == "USER":
                    cur["cfg"]["User"] = self._expand(arg, env)
                elif op == "VOLUME":
                    cur["cfg"].setdefault("Volumes", {}).update({v: {} for v in (json.loads(arg) if arg.strip().startswith("[") else arg.split())})
                elif op in ("STOPSIGNAL", "SHELL", "HEALTHCHECK", "MAINTAINER", "ONBUILD"):
                    cur["cfg"].setdefault("Labels", {})[f"vyomi.dockerfile.{op.lower()}"] = arg[:200]
                history.append({"created_by": f"{op} {arg}", "created": "1970-01-01T00:00:00Z", "empty_layer": True})
            if cur is None:
                raise ValueError("a Dockerfile must contain a FROM instruction")
        except ValueError as e:
            log(f"Dockerfile: {e}")
            return {"ok": False, "error": str(e)}
        cfg = dict(cur["cfg"])
        cfg.setdefault("Env", cfg.get("Env") or [])
        config = {"architecture": "amd64", "os": "linux", "created": "1970-01-01T00:00:00Z", "config": cfg,
                  "rootfs": {"type": "layers", "diff_ids": cur["diff"]}, "history": history}
        cb = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
        tag = job["spec"].get("tag") or f"vyomi-ci/{job['repo']}:{job['commit'][:7]}"
        self.images[tag] = {"config": cb, "layers": list(cur["layers"]), "repoTags": [tag]}
        digest = "sha256:" + hashlib.sha256(cb).hexdigest()
        size = sum(len(x) for x in cur["layers"]) + len(cb)
        log(f"Built {tag}: {len(cur['layers'])} layer(s), {size} bytes, config {digest[:19]}")
        return {"ok": True, "artifact": {"type": "image", "tag": tag, "digest": digest, "size": size, "layers": len(cur["layers"])}}

    def export(self, tag):
        img = self.images.get(tag)
        if img is None:
            raise CiError("ExportFailed", f"image {tag} was not built by the layer builder", 404)
        return img


class BuildKitBuilder:
    """Real BuildKit via the docker CLI. ``run(argv, input_bytes, timeout) -> (rc, stdout_bytes)`` injected (subprocess)."""
    name = "buildkit"
    runs_containers = True

    def __init__(self, run, timeout=300):
        self.run, self.timeout = run, timeout

    def build(self, job, tree, log):
        if job["kind"] != "image":                          # code packages don't need a container
            return PackageBuilder().build(job, tree, log)
        if "Dockerfile" not in tree:
            return {"ok": False, "error": "No Dockerfile in the repository root."}
        instr, errs = parse_dockerfile(tree["Dockerfile"].decode(errors="replace"))
        errs += _copy_sources_ok(instr, tree)
        if errs:
            for e in errs:
                log(f"Dockerfile: {e}")
            return {"ok": False, "error": "Dockerfile validation failed"}
        tag = job["spec"].get("tag") or f"vyomi-ci/{job['repo']}:{job['commit'][:7]}"
        argv = ["docker", "build", "--pull=false", "--progress=plain", "-t", tag]
        for a in job["spec"].get("buildArgs", []):
            argv += ["--build-arg", a]
        argv.append("-")
        log(f"$ {' '.join(argv)}   (BuildKit, context {len(tree)} files)")
        rc, out = self.run(argv, _pack(tree), self.timeout)
        for ln in out.decode(errors="replace").splitlines()[-200:]:
            log(ln)
        if rc != 0:
            return {"ok": False, "error": f"BuildKit build failed (exit {rc})"}
        rc2, idb = self.run(["docker", "image", "inspect", "-f", "{{.Id}} {{.Size}}", tag], None, 30)
        iid, _, size = idb.decode().strip().partition(" ")
        return {"ok": True, "artifact": {"type": "image", "tag": tag, "digest": iid, "size": int(size or 0)}}

    def export(self, tag):
        rc, raw = self.run(["docker", "save", tag], None, self.timeout)
        if rc != 0:
            raise CiError("ExportFailed", f"docker save {tag} failed (exit {rc})", 500)
        if len(raw) > MAX_EXPORT:
            raise CiError("ExportTooLarge", f"Image is {len(raw) // 1048576} MB; images over {MAX_EXPORT // 1048576} MB are not pushed to the simulated registry.", 413)
        return parse_docker_save(raw)


MAX_EXPORT = 300 * 1024 * 1024


def parse_docker_save(raw: bytes) -> dict:
    """Parse a ``docker save`` archive (docker-archive or OCI layout; both carry manifest.json) into the image
    config blob + layer blobs, ready to be pushed to a registry. Digests are of the bytes exactly as stored."""
    try:
        tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")
    except tarfile.TarError as e:
        raise CiError("ExportFailed", f"docker save output is not a tar archive: {e}", 500)
    with tf:
        def read(name):
            try:
                return tf.extractfile(tf.getmember(name.lstrip("./"))).read()
            except (KeyError, AttributeError):
                raise CiError("ExportFailed", f"docker save archive is missing '{name}'", 500)
        man = json.loads(read("manifest.json"))
        if not man:
            raise CiError("ExportFailed", "docker save archive has an empty manifest.json", 500)
        m = man[0]
        cfg = read(m["Config"])
        layers = [read(n) for n in m.get("Layers", [])]
    return {"config": cfg, "layers": layers, "repoTags": m.get("RepoTags") or []}


def image_to_registry(exp: dict) -> dict:
    """Docker v2 schema2 manifest + blobs ({digest: bytes}) for an exported image."""
    blobs, layer_desc = {}, []
    for lb in exp["layers"]:
        d = "sha256:" + hashlib.sha256(lb).hexdigest()
        blobs[d] = lb
        gz = lb[:2] == b"\x1f\x8b"
        layer_desc.append({"mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip" if gz else "application/vnd.docker.image.rootfs.diff.tar",
                           "size": len(lb), "digest": d})
    cd = "sha256:" + hashlib.sha256(exp["config"]).hexdigest()
    blobs[cd] = exp["config"]
    manifest = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                           "config": {"mediaType": "application/vnd.docker.container.image.v1+json", "size": len(exp["config"]), "digest": cd},
                           "layers": layer_desc}, separators=(",", ":")).encode()
    return {"manifest": manifest, "digest": "sha256:" + hashlib.sha256(manifest).hexdigest(), "blobs": blobs,
            "config": json.loads(exp["config"] or b"{}"), "size": sum(len(b) for b in blobs.values()) + len(manifest)}


def export_image(tag: str) -> dict:
    """Export a built image (by tag) from the active builder. Only a builder that really holds images can."""
    if tag in _layer_builder.images and not getattr(_builder, "runs_containers", False):
        return image_to_registry(_layer_builder.export(tag))
    fn = getattr(_builder, "export", None)
    if fn is None:
        raise CiError("NoImage", f"The '{_builder.name}' builder holds no container images, so nothing can be pushed to a registry.", 400)
    return image_to_registry(fn(tag))


_git: object = MemoryGit()
_builder: object = PackageBuilder()
_layer_builder = LayerBuilder()
_fetcher = None
_consumers: dict = {}


def set_git(g):
    global _git
    _git = g or MemoryGit()


def set_builder(b):
    global _builder
    _builder = b or PackageBuilder()


def set_fetcher(f):
    global _fetcher
    _fetcher = f


def set_http(fn):
    """fn(method, url, headers, body_bytes|None) -> (status, bytes). Outbound HTTPS for WRITES to the user's own GitHub
    (committing a workflow file). None on Nano -> a clear 'unavailable' error."""
    global _http
    _http = fn


_http = None


def backends() -> dict:
    return {"git": _git.name, "builder": _builder.name, "containers": bool(getattr(_builder, "runs_containers", False)),
            "externalFetch": _fetcher is not None}


def register_consumer(name, fn):
    """fn(db, event, hook, ctx) is called after a push matching a hook with consumer == name."""
    _consumers[name] = fn


# ── repos ────────────────────────────────────────────────────────────────────────────────────
def create_repo(db, name, default_branch="main", description=""):
    if not _NAME.match(name or ""):
        raise CiError("InvalidRepositoryName", f"'{name}' is not a valid repository name (letters, digits, '.', '_', '-'; max 100).")
    if name in db["repos"]:
        raise CiError("RepositoryExists", f"Repository '{name}' already exists.", 409)
    if not _BRANCH.match(default_branch) or ".." in default_branch:
        raise CiError("InvalidBranch", f"'{default_branch}' is not a valid branch name.")
    _git.ensure_repo(db, name)
    db["repos"][name] = {"name": name, "defaultBranch": default_branch, "description": description, "hooks": [], "created": _now(),
                         "backend": _git.name}
    return repo_view(db, name)


def ensure_repo(db, name, default_branch="main"):
    return repo_view(db, name) if name in db["repos"] else create_repo(db, name, default_branch)


def _repo(db, name):
    r = db["repos"].get(name)
    if not r:
        raise CiError("RepositoryNotFound", f"Repository '{name}' was not found.", 404)
    return r


def repo_view(db, name):
    r = _repo(db, name)
    return {"name": name, "defaultBranch": r["defaultBranch"], "description": r["description"], "created": r["created"],
            "backend": r["backend"], "branches": _git.branches(db, name), "cloneUrl": _git.clone_url(db, name),
            "hooks": [dict(h) for h in r["hooks"]]}


def list_repos(db):
    return [repo_view(db, n) for n in sorted(db["repos"])]


def delete_repo(db, name):
    _repo(db, name)
    _git.delete_repo(db, name)
    del db["repos"][name]
    for j in [j for j, v in db["jobs"].items() if v["repo"] == name]:
        del db["jobs"][j]


def tree(db, repo, ref=None):
    r = _repo(db, repo)
    t = _git.tree(db, repo, ref or r["defaultBranch"])
    if t is None:
        raise CiError("RefNotFound", f"Ref '{ref or r['defaultBranch']}' does not exist in '{repo}' (empty repository or unknown branch).", 404)
    return t


def log(db, repo, branch=None, limit=30):
    r = _repo(db, repo)
    return _git.log(db, repo, branch or r["defaultBranch"], limit)


# ── hooks, push ──────────────────────────────────────────────────────────────────────────────
def add_hook(db, repo, consumer, branch=None, build=None, context=None):
    """build: None (just notify) or {'kind': 'package'|'image', ...spec}. Returns the hook."""
    r = _repo(db, repo)
    if consumer not in _consumers:
        raise CiError("UnknownConsumer", f"No CI consumer '{consumer}' is registered.")
    if build and build.get("kind") not in ("package", "image"):
        raise CiError("InvalidBuild", "build.kind must be 'package' or 'image'.")
    db["seq"] += 1
    h = {"id": f"hook-{db['seq']}", "consumer": consumer, "branch": branch, "build": build, "context": context or {}}
    r["hooks"].append(h)
    return h


def remove_hooks(db, repo, consumer=None, context_key=None, context_val=None):
    r = _repo(db, repo)
    r["hooks"] = [h for h in r["hooks"] if not ((consumer is None or h["consumer"] == consumer)
                                                and (context_key is None or h["context"].get(context_key) == context_val))]


def commit_files(db, repo, branch, files, message="Update", author="vyomi", ctx=None):
    """A push: commit `files` ({path: text|bytes|None to delete}) to `branch`; fire hooks. Returns the push event."""
    r = _repo(db, repo)
    if not _BRANCH.match(branch or "") or ".." in branch or branch.startswith("/"):
        raise CiError("InvalidBranch", f"'{branch}' is not a valid branch name.")
    if not isinstance(files, dict) or not files:
        raise CiError("EmptyCommit", "A commit needs at least one file change.")
    for p in files:
        if not isinstance(p, str) or not p or p.startswith("/") or ".." in p.split("/") or len(p) > 500:
            raise CiError("InvalidPath", f"'{p}' is not a valid repository path.")
    before = _git.head(db, repo, branch)
    db["seq"] += 1
    sha = _git.commit(db, repo, branch, files, message, author)
    r.setdefault("seen", {})[branch] = sha
    return _fire(db, r, {"type": "push", "repo": repo, "branch": branch, "before": before, "after": sha, "message": message,
                         "author": author, "time": _now()}, ctx)


def _fire(db, r, ev, ctx):
    ev["jobs"] = []
    for h in list(r["hooks"]):
        if h["branch"] and h["branch"] != ev["branch"]:
            continue
        job = None
        if h["build"]:
            job = submit_job(db, ev["repo"], ev["after"], dict(h["build"]), branch=ev["branch"], trigger=f"push:{h['consumer']}")
            ev["jobs"].append(job["id"])
        fn = _consumers.get(h["consumer"])
        if fn:
            fn(db, ev, h, ctx, job)
    return ev


def reconcile(db, repo, ctx=None):
    """Detect pushes made straight to the git host (real `git push` to Gitea) and fire hooks for them."""
    r = _repo(db, repo)
    seen = r.setdefault("seen", {})
    fired = []
    for b, sha in _git.branches(db, repo).items():
        if seen.get(b) != sha:
            lg = _git.log(db, repo, b, 1)
            fired.append(_fire(db, r, {"type": "push", "repo": repo, "branch": b, "before": seen.get(b), "after": sha,
                                       "message": lg[0]["message"] if lg else "", "author": lg[0]["author"] if lg else "",
                                       "time": _now()}, ctx))
        seen[b] = sha
    return fired


# ── external source (the user's own GitHub with a PAT) ───────────────────────────────────────
_GH = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def set_connection(db, provider, token):
    if not token or not isinstance(token, str) or len(token) < 8:
        raise CiError("InvalidToken", "A personal access token is required (at least 8 characters).")
    db["connections"][provider] = {"token": token, "connected": _now()}


def connection_view(db, provider):
    c = db["connections"].get(provider)
    return {"provider": provider, "connected": bool(c), "since": c and c["connected"], "token": "***" if c else None}


def import_external(db, repo, url, ref, branch=None, message=None, ctx=None):
    """Fetch a GitHub repo ref (tarball API, user's PAT if one is connected) and commit it to `repo`."""
    m = _GH.match(url or "")
    if not m:
        raise CiError("UnsupportedSource", "Only https://github.com/{owner}/{repo} sources can be imported "
                                           "(Azure Repos / Bitbucket / generic git need an HTTP git client this substrate lacks); "
                                           "push to the local repository instead.")
    if _fetcher is None:
        raise CiError("FetchUnavailable", "This substrate cannot make outbound HTTPS requests, so the GitHub repository cannot be fetched. "
                                          "Push to the local repository instead.", 502)
    tok = (db["connections"].get("github") or {}).get("token")
    st, raw = _fetcher(f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}/tarball/{ref}",
                       {"Accept": "application/vnd.github+json", "User-Agent": "vyomi-ci", **({"Authorization": f"Bearer {tok}"} if tok else {})})
    if st in (401, 403, 404):
        hint = "" if tok else " (private repositories need a connected personal access token)"
        raise CiError("SourceNotFound", f"GitHub returned HTTP {st} for {m.group(1)}/{m.group(2)}@{ref}{hint}.", 404 if st == 404 else 403)
    if st != 200:
        raise CiError("FetchFailed", f"GitHub returned HTTP {st}.", 502)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
        for mem in tf.getmembers():
            if mem.isfile() and "/" in mem.name:
                files[mem.name.split("/", 1)[1]] = tf.extractfile(mem).read()
    if not files:
        raise CiError("EmptySource", "The repository ref contained no files.")
    ensure_repo(db, repo, branch or "main")
    if _git.head(db, repo, branch or "main"):               # an import mirrors the remote: files it no longer has are removed
        old = _git.tree(db, repo, branch or "main") or {}
        files.update({p: None for p in old if p not in files})
    return commit_files(db, repo, branch or "main", files, message or f"Import {m.group(1)}/{m.group(2)}@{ref}", "github-import", ctx)


def github_commit_file(db, url, branch, path, text, message):
    """Commit ONE file to the user's own GitHub repo through the Contents API with the connected PAT (create or update).
    Returns {"commit": sha, "path": path, "url": html_url}. Never fabricates: no PAT / no outbound HTTP / API error -> CiError."""
    m = _GH.match(url or "")
    if not m:
        raise CiError("UnsupportedSource", "Only https://github.com/{owner}/{repo} repositories can be written to.")
    if _http is None:
        raise CiError("FetchUnavailable", "This substrate cannot make outbound HTTPS requests, so the file cannot be committed to GitHub.", 502)
    tok = (db["connections"].get("github") or {}).get("token")
    if not tok:
        raise CiError("NoToken", "Committing to GitHub needs a connected personal access token with repo/workflow scope.", 401)
    hdr = {"Accept": "application/vnd.github+json", "User-Agent": "vyomi-ci", "Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    api = f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}/contents/{path}"
    st, raw = _http("GET", f"{api}?ref={branch}", hdr, None)
    body = {"message": message, "branch": branch, "content": base64.b64encode(_b(text)).decode()}
    if st == 200:
        body["sha"] = json.loads(raw).get("sha")
    elif st not in (404,):
        raise CiError("GitHubError", f"GitHub returned HTTP {st} reading {path}.", 403 if st in (401, 403) else 502)
    st, raw = _http("PUT", api, hdr, json.dumps(body).encode())
    if st not in (200, 201):
        try:
            msg = json.loads(raw).get("message", "")
        except Exception:
            msg = ""
        raise CiError("GitHubError", f"GitHub returned HTTP {st} writing {path}: {msg}".strip(), 403 if st in (401, 403) else 502)
    j = json.loads(raw)
    return {"commit": (j.get("commit") or {}).get("sha"), "path": path, "url": (j.get("content") or {}).get("html_url")}


# ── build jobs ───────────────────────────────────────────────────────────────────────────────
def submit_job(db, repo, ref, spec=None, branch=None, trigger="manual"):
    """Run a build synchronously. spec: {'kind': 'package'|'image', 'tag'?, 'buildArgs'?}. Returns the finished job."""
    spec = dict(spec or {})
    kind = spec.get("kind") or "package"
    if kind not in ("package", "image"):
        raise CiError("InvalidBuild", "kind must be 'package' or 'image'.")
    spec["kind"] = kind
    r = _repo(db, repo)
    ref = ref or r["defaultBranch"]
    t = _git.tree(db, repo, ref)
    if t is None:
        raise CiError("RefNotFound", f"Ref '{ref}' does not exist in '{repo}'.", 404)
    commit = _git.head(db, repo, ref) or ref
    db["seq"] += 1
    jid = f"job-{db['seq']:04d}"
    bld = _builder
    if kind == "image" and spec.get("layered") and not getattr(_builder, "runs_containers", False):
        bld = _layer_builder        # GCP callers opt in: a daemonless builder for substrates with no container runtime
    job = {"id": jid, "repo": repo, "ref": ref, "commit": commit, "branch": branch, "kind": kind, "spec": spec, "trigger": trigger,
           "status": "Running", "builder": bld.name, "queued": _now(), "started": _now(), "finished": None, "logs": [], "artifact": None,
           "error": None}
    db["jobs"][jid] = job
    t0 = time.time()

    def lg(msg):
        job["logs"].append({"time": _now(), "message": str(msg)[:2000]})
    lg(f"Build {jid}: {repo}@{commit[:7]} ({kind}) on builder '{bld.name}'")
    try:
        res = bld.build(job, t, lg)
    except CiError as e:
        res = {"ok": False, "error": e.message}
    except Exception as e:                                  # a crashing builder is a failed build, not a 500
        res = {"ok": False, "error": f"builder error: {e}"}
    job["finished"] = _now()
    job["durationSeconds"] = round(time.time() - t0, 3)
    if res["ok"]:
        job["status"], job["artifact"] = "Succeeded", res["artifact"]
        db["artifacts"][res["artifact"]["digest"]] = {**res["artifact"], "job": jid, "repo": repo, "commit": commit, "created": job["finished"]}
        lg("Build succeeded")
    else:
        job["status"], job["error"] = "Failed", res["error"]
        lg("Build failed: " + res["error"])
    return job


def get_job(db, jid):
    j = db["jobs"].get(jid)
    if not j:
        raise CiError("JobNotFound", f"Build job '{jid}' was not found.", 404)
    return j


def list_jobs(db, repo=None):
    return [j for j in db["jobs"].values() if repo is None or j["repo"] == repo]


def job_logs(db, jid):
    return get_job(db, jid)["logs"]


def list_artifacts(db):
    return list(db["artifacts"].values())
