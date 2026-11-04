"""App Service / Function App deployment control plane (Microsoft.Web/sites/{site}/...), substrate-free.

Real ARM resources with real validation, stored on the site record (``_webdeploy``):

* ``sourcecontrols/web`` -- Deployment Center "Settings": repoUrl (http(s)/git, GitHub for Actions), branch,
  ``isManualIntegration``, ``isGitHubAction`` (a real workflow YAML is generated from the runtime stack and returned in
  ``properties.gitHubActionConfiguration.workflowYaml``), ``deploymentRollbackEnabled``; maintains ``siteConfig.scmType``
  (GitHubAction | ExternalGit | LocalGit | None) the way ARM does.
* ``deployments`` -- the Deployment Center "Logs" list; ``POST sync`` records a deployment attempt.
* ``config/publishingcredentials`` (+ ``POST newpassword``) and ``basicPublishingCredentialsPolicies/{ftp,scm}`` -- the
  "FTPS credentials" tab: ``$site`` user, generated password (rotates), per-protocol basic-auth allow switches.

Deployments are REAL through the shared CI seam (core/ci_core.py, one repo ``site-<name>`` per app on the site record):

* Local Git (scmType LocalGit): ``POST localgit`` {branch, message, author, files:{path: text}} is a push -- it commits
  to the app's repo and the push hook builds a package artifact and records a deployment (Vyomi extension: the Kudu git
  receiver itself is the git wire protocol; with the Gitea git host the repo has a real clone URL). ``GET localgit``
  returns the remote info and, with Gitea, picks up pushes made straight to the git host.
* GitHub source (public, or private with the user's own PAT in ``properties.vyomiAccessToken`` -- stored server-side,
  never returned): a sync/continuous-integration fetches the branch tarball and builds it.
* Azure Repos / Bitbucket / generic git: not fetchable (no HTTP git client) -> a Failed deployment saying so.
* On Nano (no outbound HTTP) a GitHub fetch is Failed with that reason; Local Git works.

A build/fetch failure is recorded as a *Failed* deployment with the real reason (never a fake success). The deployed
package is a stored artifact: the App Service runtime does not hot-swap to it (limited; see capability JSON). The
GitHub Actions workflow is generated but not committed to the remote.
"""
from __future__ import annotations

import datetime
import hashlib
import re

try:
    from core import ci_core as ci
except ImportError:                                    # Pyodide flat layout
    import ci_core as ci                               # type: ignore

_REPO_RE = re.compile(r"^(https?://[^\s/]+/\S+|git@[^\s:]+:\S+|ssh://\S+)$")
STACKS = {"python": "Python", "node": "Node.js", "dotnetcore": ".NET", "java": "Java", "php": "PHP", "dotnet": ".NET"}


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def _ok(body=None, status=200):
    return {"status": status, "headers": {}, "body": body, "lro": False}


def _h(*parts, n=24):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


def _store(rec):
    s = rec.setdefault("_webdeploy", {})
    s.setdefault("source", None)
    s.setdefault("deployments", [])
    s.setdefault("passwordGen", 0)
    s.setdefault("policies", {"ftp": True, "scm": True})
    return s


def handles(rest):
    r0 = rest[0].lower()
    if r0 in ("sourcecontrols", "deployments", "sync", "newpassword", "basicpublishingcredentialspolicies", "localgit"):
        return True
    return r0 == "config" and len(rest) >= 2 and rest[1].lower() == "publishingcredentials"


def _scm_type(rec, value):
    cfg = rec.setdefault("properties", {}).setdefault("siteConfig", {})
    cfg["scmType"] = value


def workflow_yaml(rec, branch, stack, version, is_linux):
    name = rec["name"]
    runner = "ubuntu-latest" if is_linux else "windows-latest"
    setup = {
        "Python": f"      - uses: actions/setup-python@v5\n        with:\n          python-version: '{version or '3.11'}'\n      - run: pip install -r requirements.txt",
        "Node.js": f"      - uses: actions/setup-node@v4\n        with:\n          node-version: '{version or '20'}'\n      - run: npm ci && npm run build --if-present",
        ".NET": f"      - uses: actions/setup-dotnet@v4\n        with:\n          dotnet-version: '{version or '8.0'}'\n      - run: dotnet publish -c Release -o ./out",
        "Java": f"      - uses: actions/setup-java@v4\n        with:\n          java-version: '{version or '17'}'\n          distribution: 'microsoft'\n      - run: mvn clean package",
    }.get(stack, "      - run: echo 'build'")
    return (f"name: Build and deploy to Azure Web App - {name}\n\non:\n  push:\n    branches:\n      - {branch}\n  workflow_dispatch:\n\n"
            f"jobs:\n  build:\n    runs-on: {runner}\n    steps:\n      - uses: actions/checkout@v4\n{setup}\n"
            f"      - uses: actions/upload-artifact@v4\n        with:\n          name: app\n          path: .\n\n"
            f"  deploy:\n    runs-on: {runner}\n    needs: build\n    permissions:\n      id-token: write\n      contents: read\n    steps:\n"
            f"      - uses: actions/download-artifact@v4\n        with:\n          name: app\n"
            f"      - uses: azure/login@v2\n        with:\n          client-id: ${{{{ secrets.AZUREAPPSERVICE_CLIENTID }}}}\n          tenant-id: ${{{{ secrets.AZUREAPPSERVICE_TENANTID }}}}\n          subscription-id: ${{{{ secrets.AZUREAPPSERVICE_SUBSCRIPTIONID }}}}\n"
            f"      - uses: azure/webapps-deploy@v3\n        with:\n          app-name: '{name}'\n          slot-name: 'Production'\n")


def _source_view(rec, s):
    src = s["source"]
    if src is None:
        return None
    return {"id": f"{rec['id']}/sourcecontrols/web", "name": "web", "type": "Microsoft.Web/sites/sourcecontrols", "kind": rec.get("kind"), "properties": src}


def _dep_view(rec, d):
    return {"id": f"{rec['id']}/deployments/{d['id']}", "name": d["id"], "type": "Microsoft.Web/sites/deployments", "properties": d}


def _creds(rec, s):
    pw = _h(rec["id"], "pubpw", s["passwordGen"])
    return {"id": f"{rec['id']}/config/publishingcredentials", "name": "publishingcredentials", "type": "Microsoft.Web/sites/config",
            "properties": {"name": f"${rec['name']}", "publishingUserName": f"${rec['name']}", "publishingPassword": pw,
                           "publishingPasswordHash": _h(pw, n=16), "publishingPasswordHashSalt": _h(rec["id"], "salt", n=8),
                           "scmUri": f"https://${rec['name']}:{pw}@{rec['name']}.scm.azurewebsites.net"}}


def dispatch(state, rec, rest, method, payload):
    s = _store(rec)
    r0 = rest[0].lower()
    props = (payload or {}).get("properties") if isinstance(payload, dict) else None
    props = props or {}

    if r0 == "sourcecontrols":
        if len(rest) == 1:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            v = _source_view(rec, s)
            return _ok({"value": [v] if v else []})
        if rest[1].lower() != "web":
            return _err(404, "ResourceNotFound", f"Source control '{rest[1]}' was not found; the only source control resource is 'web'.")
        if method == "GET":
            v = _source_view(rec, s)
            return _ok(v) if v else _err(404, "ResourceNotFound", "No source control is configured on this app.")
        if method == "DELETE":
            s["source"] = None
            _scm_type(rec, "None")
            rec.setdefault("properties", {}).setdefault("siteConfig", {})["continuousDeploymentEnabled"] = False
            return _ok(None)
        if method in ("PUT", "PATCH"):
            return _put_source(rec, s, props, method)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")

    if r0 == "localgit":
        return _localgit(rec, s, method, payload)

    if r0 == "deployments":
        _reconcile(rec)
        deps = s["deployments"]
        if len(rest) == 1:
            if method != "GET":
                return _err(405, "MethodNotAllowed", "Collection supports GET only.")
            return _ok({"value": [_dep_view(rec, d) for d in reversed(deps)]})
        d = next((x for x in deps if x["id"] == rest[1]), None)
        if len(rest) == 3 and rest[2].lower() == "log" and method == "GET":
            return _ok({"value": d["logs"]}) if d else _err(404, "ResourceNotFound", f"Deployment '{rest[1]}' was not found.")
        if d is None:
            return _err(404, "ResourceNotFound", f"Deployment '{rest[1]}' was not found.")
        if method == "GET":
            return _ok(_dep_view(rec, d))
        if method == "DELETE":
            if d["active"]:
                return _err(409, "Conflict", "The active deployment cannot be deleted.")
            deps.remove(d)
            return _ok(None)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")

    if r0 == "sync":
        if method != "POST":
            return _err(405, "MethodNotAllowed", "Use POST to sync.")
        src = s["source"]
        if not src and ((rec.get("properties", {}).get("siteConfig") or {}).get("scmType")) == "LocalGit":
            return _err(400, "BadRequest", "This app deploys from a local Git repository; deployments are created by pushing to the app's Git remote, not by a sync.")
        if not src:
            return _err(400, "BadRequest", "No source control is configured on this app; configure the Deployment Center first.")
        if src.get("isGitHubAction"):
            return _err(409, "Conflict", "This app deploys with GitHub Actions; the build and deployment run on GitHub, not through Kudu sync.")
        d = _record_deployment(rec, s, src)
        return _ok(_dep_view(rec, d), 200)

    if r0 == "newpassword":
        if method != "POST":
            return _err(405, "MethodNotAllowed", "Use POST.")
        s["passwordGen"] += 1
        return _ok(None, 200)

    if r0 == "config":                                    # config/publishingcredentials[/list]
        if method not in ("GET", "POST"):
            return _err(405, "MethodNotAllowed", f"{method} not allowed on publishingcredentials.")
        return _ok(_creds(rec, s))

    if r0 == "basicpublishingcredentialspolicies":
        names = ("ftp", "scm")
        if len(rest) == 1:
            return _ok({"value": [_policy_view(rec, s, n) for n in names]})
        n = rest[1].lower()
        if n not in names:
            return _err(404, "ResourceNotFound", f"Basic publishing credentials policy '{rest[1]}' was not found (use 'ftp' or 'scm').")
        if method == "GET":
            return _ok(_policy_view(rec, s, n))
        if method in ("PUT", "PATCH"):
            allow = props.get("allow")
            if not isinstance(allow, bool):
                return _err(400, "BadRequest", "properties.allow must be true or false.")
            s["policies"][n] = allow
            _scm_basic(rec, n, allow)
            return _ok(_policy_view(rec, s, n))
    return _err(404, "ResourceTypeNotSupported", f"'{'/'.join(rest)}' is not supported on sites.")


def _scm_basic(rec, n, allow):
    cfg = rec.setdefault("properties", {}).setdefault("siteConfig", {})
    cfg["ftpBasicAuthEnabled" if n == "ftp" else "scmBasicAuthEnabled"] = allow


def _policy_view(rec, s, n):
    return {"id": f"{rec['id']}/basicPublishingCredentialsPolicies/{n}", "name": n, "type": "Microsoft.Web/sites/basicPublishingCredentialsPolicies",
            "properties": {"allow": s["policies"][n]}}


def _put_source(rec, s, props, method):
    cur = dict(s["source"] or {}) if method == "PATCH" else {}
    cur.update({k: v for k, v in props.items() if k not in ("gitHubActionConfiguration", "vyomiAccessToken")})
    if props.get("vyomiAccessToken"):
        try:
            ci.set_connection(ci.get_db(rec), "github", props["vyomiAccessToken"])
        except ci.CiError as e:
            return _err(e.status, e.code, e.message)
    if "gitHubActionConfiguration" in props:
        cur["gitHubActionConfiguration"] = dict(props["gitHubActionConfiguration"] or {})
    repo = str(cur.get("repoUrl") or "")
    if not repo:
        return _err(400, "BadRequest", "properties.repoUrl is required.")
    if not _REPO_RE.match(repo):
        return _err(400, "BadRequest", f"repoUrl '{repo}' is not a valid git repository URL (https://..., git@host:org/repo or ssh://...).")
    branch = str(cur.get("branch") or "master")
    if not re.match(r"^[\w./-]{1,255}$", branch) or branch.startswith("/") or ".." in branch:
        return _err(400, "BadRequest", f"branch '{branch}' is not a valid git branch name.")
    cur["branch"] = branch
    gh = bool(cur.get("isGitHubAction"))
    if gh and not re.match(r"^https://github\.com/[^/]+/[^/]+?(\.git)?/?$", repo):
        return _err(400, "BadRequest", "GitHub Actions deployment requires a https://github.com/{org}/{repo} repository URL.")
    cur["isGitHubAction"] = gh
    existing_scm = (rec.get("properties", {}).get("siteConfig") or {}).get("scmType") or "None"
    if existing_scm == "LocalGit":
        return _err(409, "SourceControlAlreadyConfigured", "The app deploys from a local Git repository (scmType LocalGit); disconnect it (scmType None) before configuring a repository source.")
    provider = _provider(repo)
    if provider == "AzureRepos" and not re.match(r"^https://(dev\.azure\.com/[^/]+/[^/]+|[^/.]+\.visualstudio\.com(/[^/]+)?)/_git/[^/]+/?$", repo):
        return _err(400, "BadRequest", "An Azure Repos source needs a URL like https://dev.azure.com/{org}/{project}/_git/{repo}.")
    if provider == "AzureRepos" and gh:
        return _err(400, "BadRequest", "isGitHubAction is only valid for GitHub repositories.")
    cur["provider"] = provider
    cur["isManualIntegration"] = bool(cur.get("isManualIntegration", False))
    cur["isMercurial"] = bool(cur.get("isMercurial", False))
    cur["deploymentRollbackEnabled"] = bool(cur.get("deploymentRollbackEnabled", False))
    if gh:
        g = cur.setdefault("gitHubActionConfiguration", {})
        code = g.get("codeConfiguration") or {}
        cont = g.get("containerConfiguration")
        if not code and not cont:
            return _err(400, "BadRequest", "gitHubActionConfiguration needs codeConfiguration (runtimeStack/runtimeVersion) or containerConfiguration.")
        stack = STACKS.get(str(code.get("runtimeStack") or "").lower(), code.get("runtimeStack") or "")
        if code and not stack:
            return _err(400, "BadRequest", "codeConfiguration.runtimeStack is required.")
        is_linux = bool(g.get("isLinux", "linux" in str(rec.get("kind") or "")))
        g["isLinux"] = is_linux
        if g.get("generateWorkflowFile", True):
            g["workflowYaml"] = workflow_yaml(rec, branch, stack, code.get("runtimeVersion"), is_linux)
            g["workflowFilePath"] = f".github/workflows/{branch.replace('/', '-')}_{rec['name']}.yml"
            g.pop("workflowCommit", None); g.pop("workflowCommitError", None)
            if (ci.get_db(rec)["connections"].get("github") or {}).get("token"):
                try:                                     # the real workflow file lands in the user's own repo
                    g["workflowCommit"] = ci.github_commit_file(ci.get_db(rec), repo, branch, g["workflowFilePath"], g["workflowYaml"],
                                                                f"Add or update the Azure App Service build and deployment workflow config ({rec['name']})")
                except ci.CiError as e:
                    return _err(e.status, e.code, f"The workflow was generated but could not be committed to {repo}: {e.message}")
            else:
                g["workflowCommitError"] = "No personal access token connected: the workflow was generated but not committed (set properties.vyomiAccessToken)."
        g["generateWorkflowFile"] = True
    else:
        cur.pop("gitHubActionConfiguration", None)
    first = s["source"] is None
    s["source"] = cur
    _scm_type(rec, "GitHubAction" if gh else {"AzureRepos": "VSTSRM", "Bitbucket": "BitbucketGit"}.get(provider, "ExternalGit"))
    rec["properties"]["siteConfig"]["continuousDeploymentEnabled"] = not cur["isManualIntegration"]
    if not gh and not cur["isManualIntegration"]:
        _record_deployment(rec, s, cur)        # continuous integration: ARM kicks off an immediate sync
    return _ok(_source_view(rec, s), 201 if first else 200)


def _provider(repo):
    h = repo.lower()
    if "dev.azure.com/" in h or ".visualstudio.com" in h:
        return "AzureRepos"
    if "bitbucket.org/" in h:
        return "Bitbucket"
    if "github.com" in h:
        return "GitHub"
    return "ExternalGit"


def _site_repo(rec):
    db = ci.get_db(rec)
    repo = f"site-{rec['name']}"
    ci.ensure_repo(db, repo, "main")
    return db, repo


def _ensure_hook(db, repo, branch):
    r = db["repos"][repo]
    if not any(h["consumer"] == "azure.webdeploy" and h["branch"] == branch for h in r["hooks"]):
        ci.add_hook(db, repo, "azure.webdeploy", branch=branch, build={"kind": "package"}, context={"site": repo})


def _on_push(db, ev, hook, rec, job):
    """CI consumer: a push (or import) on a hooked branch becomes a Deployment Center record from the build job."""
    if rec is None:
        return
    s = _store(rec)
    n = len(s["deployments"]) + 1
    did = _h(rec["id"], "dep", n, ev["after"], n=40)
    ok = bool(job) and job["status"] == "Succeeded"
    for d in s["deployments"]:
        if ok:
            d["active"] = False
    logs = [{"id": f"{did}-{i}", "message": l["message"], "type": 1 if ok else 2, "details_url": None, "log_time": l["time"]}
            for i, l in enumerate(job["logs"] if job else [], 1)]
    if job and ok:
        a = job["artifact"]
        logs.append({"id": f"{did}-p", "message": f"Deployed package {a['digest']} ({a['files']} files, {a['runtime']}) to the app's deployment store. "
                     "The App Service runtime does not hot-swap to it in this simulator.", "type": 1, "details_url": None, "log_time": ev["time"]})
    s["deployments"].append({"id": did, "status": 4 if ok else 3, "status_text": "Success" if ok else "Failed", "author_email": "N/A",
                             "author": ev["author"], "deployer": "Vyomi CI", "message": ev["message"], "id_commit": ev["after"],
                             "start_time": job["started"] if job else ev["time"], "end_time": job["finished"] if job else ev["time"],
                             "active": ok, "provisioningState": "Succeeded", "jobId": job["id"] if job else None, "logs": logs})


ci.register_consumer("azure.webdeploy", _on_push)


def _reconcile(rec):
    db = ci.get_db(rec)
    repo = f"site-{rec['name']}"
    if repo in db["repos"]:
        try:
            ci.reconcile(db, repo, rec)
        except ci.CiError:
            pass


def _localgit(rec, s, method, payload):
    if (rec.get("properties", {}).get("siteConfig") or {}).get("scmType") != "LocalGit":
        return _err(409, "Conflict", "Local Git deployment is not enabled on this app (scmType must be LocalGit).")
    try:
        db, repo = _site_repo(rec)
        _ensure_hook(db, repo, "main")
        if method == "GET":
            _reconcile(rec)
            v = ci.repo_view(db, repo)
            return _ok({"repo": repo, "branches": v["branches"], "backend": v["backend"], "cloneUrl": v["cloneUrl"],
                        "commits": ci.log(db, repo, None, 20) if v["branches"] else []})
        if method != "POST":
            return _err(405, "MethodNotAllowed", f"{method} not allowed.")
        p = payload if isinstance(payload, dict) else {}
        branch = str(p.get("branch") or "main")
        _ensure_hook(db, repo, branch)
        ev = ci.commit_files(db, repo, branch, p.get("files") or {}, str(p.get("message") or "Update"), str(p.get("author") or "vyomi"), rec)
        return _ok({"commit": ev["after"], "branch": branch, "jobs": ev["jobs"], "deployment": s["deployments"][-1]["id"] if s["deployments"] else None}, 200)
    except ci.CiError as e:
        return _err(e.status, e.code, e.message)


def _record_deployment(rec, s, src):
    """Sync from the configured repo through the CI seam; the hook records the Deployment (success or failure)."""
    before = len(s["deployments"])
    try:
        db, repo = _site_repo(rec)
        branch = src.get("branch") or "main"
        _ensure_hook(db, repo, branch)
        ci.import_external(db, repo, src.get("repoUrl"), branch, branch=branch, message=f"Sync from {src.get('repoUrl')} @ {branch}", ctx=rec)
    except ci.CiError as e:
        if len(s["deployments"]) == before:
            n = before + 1
            did = _h(rec["id"], "dep", n, _now(), n=40)
            ts = _now()
            s["deployments"].append({"id": did, "status": 3, "status_text": "Failed", "author_email": "N/A", "author": "N/A", "deployer": "Vyomi CI",
                                     "message": f"Sync from {src.get('repoUrl')}", "start_time": ts, "end_time": ts, "active": False,
                                     "provisioningState": "Succeeded",
                                     "logs": [{"id": did + "-1", "message": f"Sync of {src.get('repoUrl')} @ {src.get('branch')} failed: {e.message}",
                                               "type": 2, "details_url": None, "log_time": ts}]})
    return s["deployments"][-1]
