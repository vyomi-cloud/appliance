"""Lambda CI/CD pipeline applications on the shared CI seam (substrate-free).

``POST /2015-03-31/applications`` with ``Pipeline: {Repository, Branch, FunctionName, Runtime, Handler}`` creates an
application plus a Source -> Build -> Deploy pipeline:

  Source   the repository (``vyomi/{name}`` inside Vyomi -- seeded with a working hello-world function -- or
           ``https://github.com/{owner}/{repo}`` fetched with the user's own PAT on the offline appliance).
  Build    the tree is validated and packaged: the handler module must exist, every ``.py`` file must COMPILE (a real
           syntax check), and a deployment zip is produced. ``buildspec.yml`` commands are NOT executed (no CodeBuild
           container); that is reported in the stage log.
  Deploy   the function is created (first run) or its code updated through the real Lambda core, a version is
           published and the ``live`` alias is moved to it -- so the deployed function is invocable with new code.

A push to the branch (``POST .../pipeline/push`` for a vyomi repo, a git push to Gitea, or ``.../pipeline/executions``
for GitHub, which does not call back) starts an execution. Failures stop the pipeline at the failing stage with the real
reason; nothing is marked deployed that was not.
"""
from __future__ import annotations

import base64
import datetime
import io
import json
import re
import zipfile

try:
    from core import ci_core as ci
except ImportError:                                      # Pyodide flat layout
    import ci_core as ci                                 # type: ignore

_FN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SEED = {
    "app.py": 'def handler(event, context):\n    return {"statusCode": 200, "body": "Hello from {name} - version 1"}\n',
    "buildspec.yml": "version: 0.2\nphases:\n  build:\n    commands:\n      - echo build (not executed by Vyomi)\nartifacts:\n  files:\n    - '**/*'\n",
    "README.md": "# {name}\n\nPush to this repository to run the Source -> Build -> Deploy pipeline.\n",
}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo_of(cfg):
    r = cfg["Repository"]
    if r.startswith("vyomi/"):
        return r[len("vyomi/"):]
    m = ci._GH.match(r)
    return f"{m.group(1)}--{m.group(2)}" if m else None


def validate(name, cfg):
    if not isinstance(cfg, dict):
        return "Pipeline must be an object."
    repo = str(cfg.get("Repository") or "")
    if not (repo.startswith("vyomi/") and re.match(r"^vyomi/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$", repo)) and not ci._GH.match(repo):
        return "Pipeline.Repository must be 'vyomi/<repo>' or https://github.com/<owner>/<repo>."
    if not re.match(r"^[\w./-]{1,255}$", str(cfg.get("Branch") or "main")):
        return "Pipeline.Branch is not a valid branch name."
    fn = str(cfg.get("FunctionName") or name)
    if not _FN.match(fn):
        return "Pipeline.FunctionName must match [a-zA-Z0-9-_]+ (1-64 chars)."
    if not str(cfg.get("Runtime") or "python3.12").startswith("python"):
        return "Pipeline.Runtime: Vyomi's Lambda core runs Python handlers only (python3.x)."
    if "." not in str(cfg.get("Handler") or "app.handler"):
        return "Pipeline.Handler must be module.function."
    return None


def create(app, cfg, call, ctx_store):
    """Seed/prepare the pipeline on application record ``app``; run it once. Returns the pipeline dict."""
    db = ci.get_db(app)
    repo = _repo_of(cfg)
    branch = cfg.get("Branch") or "main"
    p = {"Repository": cfg["Repository"], "Branch": branch, "FunctionName": cfg.get("FunctionName") or app["name"],
         "Runtime": cfg.get("Runtime") or "python3.12", "Handler": cfg.get("Handler") or "app.handler",
         "Role": cfg.get("Role") or "arn:aws:iam::123456789012:role/service-role/lambda-basic-execution",
         "SourceDirectory": (cfg.get("SourceDirectory") or "").strip("/"), "Executions": []}
    app["pipeline"] = p
    token = cfg.get("GitHubToken")
    if token:
        ci.set_connection(db, "github", token)
    ci.ensure_repo(db, repo, branch)
    ci.add_hook(db, repo, "aws.lambda-pipeline", branch=branch, context={"app": app["name"]})
    if cfg["Repository"].startswith("vyomi/") and not ci._git.head(db, repo, branch):
        ci.commit_files(db, repo, branch, {k: v.replace("{name}", app["name"]) for k, v in _SEED.items()}, "Initial commit (Vyomi starter)", "vyomi",
                        ctx={"call": call, "app": app})
    else:
        run(app, "create", call)
    return p


def _zip(tree, srcdir):
    buf = io.BytesIO()
    pref = srcdir + "/" if srcdir else ""
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(tree):
            if path.startswith(".git/") or path.startswith(".github/") or (pref and not path.startswith(pref)):
                continue
            z.writestr(path[len(pref):], tree[path])
    return buf.getvalue()


def run(app, trigger, call):
    p = app["pipeline"]
    db = ci.get_db(app)
    ex = {"Id": f"exec-{len(p['Executions']) + 1}", "Trigger": trigger, "StartedAt": _now(), "Status": "InProgress",
          "Stages": [{"Name": n, "Status": "NotStarted", "Logs": []} for n in ("Source", "Build", "Deploy")]}
    p["Executions"].insert(0, ex)
    del p["Executions"][25:]
    S = {s["Name"]: s for s in ex["Stages"]}

    def fail(stage, msg):
        S[stage]["Status"] = "Failed"
        S[stage]["Logs"].append(msg)
        ex["Status"], ex["Error"], ex["FailedStage"] = "Failed", msg, stage
        ex["FinishedAt"] = _now()
        p["LastExecution"] = {"Id": ex["Id"], "Status": "Failed", "Commit": ex.get("Commit")}
        return ex
    repo, branch = _repo_of(p), p["Branch"]
    S["Source"]["Status"] = "InProgress"
    try:
        if not p["Repository"].startswith("vyomi/"):
            S["Source"]["Logs"].append(f"Fetching {p['Repository']}@{branch}")
            ci.import_external(db, repo, p["Repository"], branch, branch=branch, message="pipeline source")
        sha = ci._git.head(db, repo, branch)
        tree = ci.tree(db, repo, branch)
    except ci.CiError as e:
        return fail("Source", e.message)
    ex["Commit"] = sha
    S["Source"].update(Status="Succeeded")
    S["Source"]["Logs"].append(f"Source revision {sha[:7]} ({len(tree)} files)")
    S["Build"]["Status"] = "InProgress"
    src = p["SourceDirectory"]
    pref = src + "/" if src else ""
    mod = p["Handler"].rsplit(".", 1)[0].replace(".", "/") + ".py"
    if pref + mod not in tree:
        return fail("Build", f"Handler module '{mod}' was not found in the repository{' under ' + src if src else ''}.")
    for path, data in sorted(tree.items()):
        if path.endswith(".py") and path.startswith(pref):
            try:
                compile(data.decode(errors="replace"), path, "exec")
            except SyntaxError as e:
                return fail("Build", f"{path}:{e.lineno}: SyntaxError: {e.msg}")
    bs = "buildspec.yml" in tree
    S["Build"]["Logs"].append("Compiled every .py file" + ("; buildspec.yml present but its commands are not executed (no build container)" if bs else ""))
    z = _zip(tree, src)
    S["Build"].update(Status="Succeeded")
    S["Build"]["Logs"].append(f"Packaged {len(z)} bytes")
    ex["PackageSize"] = len(z)
    S["Deploy"]["Status"] = "InProgress"
    fn, b64 = p["FunctionName"], base64.b64encode(z).decode()
    st, doc = call("GET", f"/2015-03-31/functions/{fn}", None)
    if st == 404:
        st, doc = call("POST", "/2015-03-31/functions", {"FunctionName": fn, "Runtime": p["Runtime"], "Handler": p["Handler"], "Role": p["Role"],
                                                       "Code": {"ZipFile": b64}, "Description": f"Deployed by pipeline of application {app['name']}",
                                                       "Tags": {"vyomi:application": app["name"]}})
        S["Deploy"]["Logs"].append(f"Created function {fn}")
    else:
        st, doc = call("PUT", f"/2015-03-31/functions/{fn}/code", {"ZipFile": b64})
        S["Deploy"]["Logs"].append(f"Updated code of {fn}")
    if st >= 300:
        return fail("Deploy", (doc.get("Message") or str(doc)))
    st, ver = call("POST", f"/2015-03-31/functions/{fn}/versions", {"Description": f"pipeline {ex['Id']} @ {sha[:7]}"})
    if st >= 300:
        return fail("Deploy", ver.get("Message") or str(ver))
    v = ver.get("Version")
    st, al = call("POST", f"/2015-03-31/functions/{fn}/aliases", {"Name": "live", "FunctionVersion": v})
    if st == 409:
        st, al = call("PUT", f"/2015-03-31/functions/{fn}/aliases/live", {"FunctionVersion": v})
    if st >= 300:
        return fail("Deploy", al.get("Message") or str(al))
    S["Deploy"].update(Status="Succeeded")
    S["Deploy"]["Logs"].append(f"Published version {v}; alias 'live' -> {v}")
    ex.update(Status="Succeeded", FunctionVersion=v, FunctionArn=ver.get("FunctionArn"), FinishedAt=_now())
    p["LastExecution"] = {"Id": ex["Id"], "Status": "Succeeded", "Commit": sha, "FunctionVersion": v}
    return ex


def _on_push(db, ev, hook, ctx, job):
    c = ctx or {}
    app = c.get("app")
    if app is not None and c.get("call"):
        run(app, f"push:{ev['after'][:7]}", c["call"])


ci.register_consumer("aws.lambda-pipeline", _on_push)


def push(app, doc, call):
    p = app.get("pipeline")
    if not p:
        return 404, {"Message": f"Application {app['name']} has no pipeline."}
    if not p["Repository"].startswith("vyomi/"):
        return 400, {"Message": "Push applies to vyomi/ repositories; push to GitHub and start an execution instead."}
    try:
        ev = ci.commit_files(ci.get_db(app), _repo_of(p), doc.get("Branch") or p["Branch"], doc.get("Files") or {}, doc.get("Message") or "Update",
                             doc.get("Author") or "vyomi", ctx={"call": call, "app": app})
    except ci.CiError as e:
        return e.status, {"Message": e.message}
    return 200, {"CommitId": ev["after"], "Pipeline": pipeline_view(app)}


def pipeline_view(app):
    p = app.get("pipeline")
    return None if not p else {k: v for k, v in p.items()}
