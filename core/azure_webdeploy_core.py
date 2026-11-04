"""App Service / Function App deployment control plane (Microsoft.Web/sites/{site}/...), substrate-free.

Real ARM resources with real validation, stored on the site record (``_webdeploy``):

* ``sourcecontrols/web`` -- Deployment Center "Settings": repoUrl (http(s)/git, GitHub for Actions), branch,
  ``isManualIntegration``, ``isGitHubAction`` (a real workflow YAML is generated from the runtime stack and returned in
  ``properties.gitHubActionConfiguration.workflowYaml``), ``deploymentRollbackEnabled``; maintains ``siteConfig.scmType``
  (GitHubAction | ExternalGit | LocalGit | None) the way ARM does.
* ``deployments`` -- the Deployment Center "Logs" list; ``POST sync`` records a deployment attempt.
* ``config/publishingcredentials`` (+ ``POST newpassword``) and ``basicPublishingCredentialsPolicies/{ftp,scm}`` -- the
  "FTPS credentials" tab: ``$site`` user, generated password (rotates), per-protocol basic-auth allow switches.

NOT modelled: there is no build runner and no outbound git access, so a sync is recorded as a *Failed* deployment with
an explanatory log line (never a fake success), and the GitHub workflow is generated but not committed to the remote.
"""
from __future__ import annotations

import datetime
import hashlib
import re

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
    if r0 in ("sourcecontrols", "deployments", "sync", "newpassword", "basicpublishingcredentialspolicies"):
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
            return _ok(None)
        if method in ("PUT", "PATCH"):
            return _put_source(rec, s, props, method)
        return _err(405, "MethodNotAllowed", f"{method} not allowed.")

    if r0 == "deployments":
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
    cur.update({k: v for k, v in props.items() if k != "gitHubActionConfiguration"})
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
        g["generateWorkflowFile"] = True
    else:
        cur.pop("gitHubActionConfiguration", None)
    first = s["source"] is None
    s["source"] = cur
    _scm_type(rec, "GitHubAction" if gh else "ExternalGit")
    rec["properties"]["siteConfig"]["continuousDeploymentEnabled"] = not cur["isManualIntegration"]
    if not gh and not cur["isManualIntegration"]:
        _record_deployment(rec, s, cur)        # continuous integration: ARM kicks off an immediate sync
    return _ok(_source_view(rec, s), 201 if first else 200)


def _record_deployment(rec, s, src):
    n = len(s["deployments"]) + 1
    did = _h(rec["id"], "dep", n, _now(), n=40)
    ts = _now()
    msg = (f"Repository {src.get('repoUrl')} @ {src.get('branch')} was not fetched: Vyomi has no build runner and makes no outbound git "
           f"connections, so this deployment could not run. The attempt is recorded so the Deployment Center log is truthful.")
    d = {"id": did, "status": 3, "status_text": "Failed", "author_email": "N/A", "author": "N/A", "deployer": "Vyomi",
         "message": f"Sync from {src.get('repoUrl')}", "start_time": ts, "end_time": ts, "active": False, "provisioningState": "Succeeded",
         "logs": [{"id": did + "-1", "message": msg, "type": 1, "details_url": None, "log_time": ts}]}
    s["deployments"].append(d)
    return d
