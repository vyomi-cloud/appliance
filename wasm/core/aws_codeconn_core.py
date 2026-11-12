# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""AWS CodeConnections-lite + CloudFormation Git sync on the shared CI seam (substrate-free; JSON 1.0
``com.amazonaws.codeconnections.CodeConnections_20231201.<Op>`` / legacy ``CodeStar_connections_20191201``).

Real behaviour (not a stub): a ``CFN_STACK_SYNC`` sync configuration links a repository branch to a CloudFormation stack.
On every push to the branch (and on ``VyomiSync``) the deployment file (``ConfigFile``: ``template-file-path`` /
``parameters`` / ``tags``, JSON or YAML) is read from the repository, the template is read, and the stack is CREATED or
UPDATED through the real CloudFormation core (core/cloudformation_core.py): a changed template/parameter set becomes an
UpdateStack, an identical one is recorded as "no changes". ``TriggerResourceUpdateOn=FILE_CHANGE`` only syncs when the
deployment file or the template it names changed in the push. Status (``GetResourceSyncStatus``: DesiredState sha,
LatestSync events, Status, Target) is derived from those runs; failures carry the real reason (missing file, bad template,
CloudFormation validation error).

Repositories: ``ProviderType=GitHub`` with ``OwnerId=vyomi`` is a repository INSIDE Vyomi (push with the Vyomi op
``VyomiPush`` or a real git push to Gitea); any other GitHub owner is fetched with the user's own PAT
(``VyomiSetGitHubToken``) on offline; Nano cannot reach GitHub. Other providers are accepted on the connection but cannot
be fetched (reported on sync). Connections are AVAILABLE immediately (no OAuth handshake exists to complete).
"""
from __future__ import annotations

import datetime
import json
import re
import uuid

try:
    from core import ci_core as ci
    from core import cloudformation_core as cfn
    from core import k8s_yaml
except ImportError:                                      # Pyodide flat layout
    import ci_core as ci                                 # type: ignore
    import cloudformation_core as cfn                    # type: ignore
    import k8s_yaml                                      # type: ignore

ACCOUNT = "000000000000"
REGION = "us-east-1"
PROVIDERS = ("Bitbucket", "GitHub", "GitHubEnterpriseServer", "GitLab", "GitLabSelfManaged", "AzureDevOps")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
_STACK = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,127}$")


class CcError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch():
    return datetime.datetime.now(datetime.timezone.utc).timestamp()


def state(bag):
    st = bag.setdefault("codeconn", {"connections": {}, "links": {}, "syncs": {}})
    st.setdefault("ci", {})
    return st


def _db(st):
    return ci.get_db(st)


def _arn(kind, ident, region=REGION):
    return f"arn:aws:codeconnections:{region}:{ACCOUNT}:{kind}/{ident}"


# ── connections ──────────────────────────────────────────────────────────────────────────────
def create_connection(st, p):
    name = p.get("ConnectionName")
    prov = p.get("ProviderType") or ("GitHub" if not p.get("HostArn") else "GitHubEnterpriseServer")
    if not name or not _NAME.match(name) and not re.match(r"^[\w .-]{1,32}$", name or ""):
        raise CcError("ValidationException", "ConnectionName must be 1-32 characters.")
    if prov not in PROVIDERS:
        raise CcError("ValidationException", f"ProviderType must be one of {', '.join(PROVIDERS)}.")
    if any(c["ConnectionName"] == name for c in st["connections"].values()):
        raise CcError("ResourceAlreadyExistsException", f"A connection named {name} already exists.")
    cid = str(uuid.uuid4())
    c = {"ConnectionName": name, "ConnectionArn": _arn("connection", cid), "ProviderType": prov, "OwnerAccountId": ACCOUNT,
         "ConnectionStatus": "AVAILABLE"}
    if p.get("HostArn"):
        c["HostArn"] = p["HostArn"]
    st["connections"][c["ConnectionArn"]] = c
    return {"ConnectionArn": c["ConnectionArn"], "Tags": p.get("Tags") or []}


def get_connection(st, p):
    c = st["connections"].get(p.get("ConnectionArn"))
    if not c:
        raise CcError("ResourceNotFoundException", f"Connection {p.get('ConnectionArn')} not found.", 404)
    return {"Connection": c}


def list_connections(st, p):
    return {"Connections": [c for c in st["connections"].values() if not p.get("ProviderTypeFilter") or c["ProviderType"] == p["ProviderTypeFilter"]]}


def delete_connection(st, p):
    if p.get("ConnectionArn") not in st["connections"]:
        raise CcError("ResourceNotFoundException", f"Connection {p.get('ConnectionArn')} not found.", 404)
    if any(l["ConnectionArn"] == p["ConnectionArn"] for l in st["links"].values()):
        raise CcError("ConditionalCheckFailedException", "The connection is used by a repository link; delete the link first.")
    del st["connections"][p["ConnectionArn"]]
    return {}


# ── repository links ─────────────────────────────────────────────────────────────────────────
def create_repository_link(st, p):
    c = st["connections"].get(p.get("ConnectionArn"))
    if not c:
        raise CcError("ResourceNotFoundException", f"Connection {p.get('ConnectionArn')} not found.", 404)
    for k in ("OwnerId", "RepositoryName"):
        if not p.get(k):
            raise CcError("InvalidInputException", f"{k} is required.")
    if any(l["OwnerId"] == p["OwnerId"] and l["RepositoryName"] == p["RepositoryName"] and l["ProviderType"] == c["ProviderType"] for l in st["links"].values()):
        raise CcError("ResourceAlreadyExistsException", "A repository link for this repository already exists.")
    lid = str(uuid.uuid4())
    l = {"RepositoryLinkId": lid, "RepositoryLinkArn": _arn("repository-link", lid), "ConnectionArn": c["ConnectionArn"], "OwnerId": p["OwnerId"],
         "RepositoryName": p["RepositoryName"], "ProviderType": c["ProviderType"]}
    if p.get("EncryptionKeyArn"):
        l["EncryptionKeyArn"] = p["EncryptionKeyArn"]
    st["links"][lid] = l
    if p["OwnerId"] == "vyomi":                            # a repository inside Vyomi
        ci.ensure_repo(_db(st), _repo_name(l), "main")
    return {"RepositoryLinkInfo": l}


def _link(st, lid):
    l = st["links"].get(lid)
    if not l:
        raise CcError("ResourceNotFoundException", f"Repository link {lid} not found.", 404)
    return l


def get_repository_link(st, p):
    return {"RepositoryLinkInfo": _link(st, p.get("RepositoryLinkId"))}


def list_repository_links(st, p):
    return {"RepositoryLinks": list(st["links"].values())}


def delete_repository_link(st, p):
    _link(st, p.get("RepositoryLinkId"))
    if any(s["RepositoryLinkId"] == p["RepositoryLinkId"] for s in st["syncs"].values()):
        raise CcError("SyncConfigurationStillExistsException", "Delete the sync configurations that use this repository link first.")
    del st["links"][p["RepositoryLinkId"]]
    return {}


def _repo_name(l):
    return f"{l['OwnerId']}--{l['RepositoryName']}"


# ── sync configurations ──────────────────────────────────────────────────────────────────────
def _sync_view(s):
    return {k: s[k] for k in ("Branch", "ConfigFile", "OwnerId", "ProviderType", "RepositoryLinkId", "RepositoryName", "ResourceName", "RoleArn",
                              "SyncType", "PublishDeploymentStatus", "TriggerResourceUpdateOn") if k in s}


def _skey(p):
    return (p.get("ResourceName"), p.get("SyncType"))


def create_sync_configuration(st, p):
    for k in ("Branch", "ConfigFile", "RepositoryLinkId", "ResourceName", "RoleArn", "SyncType"):
        if not p.get(k):
            raise CcError("InvalidInputException", f"{k} is required.")
    if p["SyncType"] != "CFN_STACK_SYNC":
        raise CcError("InvalidInputException", "SyncType must be CFN_STACK_SYNC.")
    if not _STACK.match(p["ResourceName"]):
        raise CcError("InvalidInputException", "ResourceName must be a CloudFormation stack name ([a-zA-Z][-a-zA-Z0-9]*).")
    if not re.match(r"^arn:aws[a-z-]*:iam::\d{12}:role/.+$", p["RoleArn"]):
        raise CcError("InvalidInputException", "RoleArn must be an IAM role ARN.")
    if not re.match(r"^[\w./-]{1,255}$", p["Branch"]) or ".." in p["Branch"]:
        raise CcError("InvalidInputException", "Branch is not a valid branch name.")
    if p["ConfigFile"].startswith("/") or ".." in p["ConfigFile"].split("/"):
        raise CcError("InvalidInputException", "ConfigFile must be a relative repository path.")
    trig = p.get("TriggerResourceUpdateOn") or "ANY_CHANGE"
    if trig not in ("ANY_CHANGE", "FILE_CHANGE"):
        raise CcError("InvalidInputException", "TriggerResourceUpdateOn must be ANY_CHANGE or FILE_CHANGE.")
    l = _link(st, p["RepositoryLinkId"])
    if _skey(p) in [(s["ResourceName"], s["SyncType"]) for s in st["syncs"].values()]:
        raise CcError("ResourceAlreadyExistsException", f"A sync configuration for {p['ResourceName']} already exists.")
    s = {"Branch": p["Branch"], "ConfigFile": p["ConfigFile"], "OwnerId": l["OwnerId"], "ProviderType": l["ProviderType"], "RepositoryLinkId": l["RepositoryLinkId"],
         "RepositoryName": l["RepositoryName"], "ResourceName": p["ResourceName"], "RoleArn": p["RoleArn"], "SyncType": "CFN_STACK_SYNC",
         "PublishDeploymentStatus": p.get("PublishDeploymentStatus") or "DISABLED", "TriggerResourceUpdateOn": trig,
         "_syncs": [], "_status": "INITIATED", "_sha": None, "_last": None}
    st["syncs"][f"{p['ResourceName']}|CFN_STACK_SYNC"] = s
    if l["OwnerId"] == "vyomi":
        db = _db(st)
        repo = _repo_name(l)
        ci.ensure_repo(db, repo, p["Branch"])
        ci.add_hook(db, repo, "aws.cfn-gitsync", branch=p["Branch"], context={"sync": f"{p['ResourceName']}|CFN_STACK_SYNC"})
    return {"SyncConfiguration": _sync_view(s)}


def _sync(st, p):
    s = st["syncs"].get(f"{p.get('ResourceName')}|{p.get('SyncType')}")
    if not s:
        raise CcError("ResourceNotFoundException", f"No sync configuration exists for {p.get('ResourceName')} ({p.get('SyncType')}).", 404)
    return s


def get_sync_configuration(st, p):
    return {"SyncConfiguration": _sync_view(_sync(st, p))}


def list_sync_configurations(st, p):
    rows = [_sync_view(s) for s in st["syncs"].values() if s["RepositoryLinkId"] == p.get("RepositoryLinkId") and s["SyncType"] == p.get("SyncType")]
    return {"SyncConfigurations": rows}


def update_sync_configuration(st, p):
    s = _sync(st, p)
    for k in ("Branch", "ConfigFile", "RoleArn", "PublishDeploymentStatus", "TriggerResourceUpdateOn"):
        if p.get(k):
            s[k] = p[k]
    if p.get("RepositoryLinkId"):
        l = _link(st, p["RepositoryLinkId"])
        s.update(RepositoryLinkId=l["RepositoryLinkId"], OwnerId=l["OwnerId"], RepositoryName=l["RepositoryName"], ProviderType=l["ProviderType"])
    for lk in st["links"].values():                        # re-point the push hook at the (possibly new) repo/branch
        if lk["OwnerId"] == "vyomi":
            ci.remove_hooks(_db(st), _repo_name(lk), "aws.cfn-gitsync", "sync", f"{s['ResourceName']}|CFN_STACK_SYNC")
    nl = st["links"][s["RepositoryLinkId"]]
    if nl["OwnerId"] == "vyomi":
        ci.ensure_repo(_db(st), _repo_name(nl), s["Branch"])
        ci.add_hook(_db(st), _repo_name(nl), "aws.cfn-gitsync", branch=s["Branch"], context={"sync": f"{s['ResourceName']}|CFN_STACK_SYNC"})
    return {"SyncConfiguration": _sync_view(s)}


def delete_sync_configuration(st, p):
    s = _sync(st, p)
    l = st["links"].get(s["RepositoryLinkId"])
    if l and l["OwnerId"] == "vyomi":
        ci.remove_hooks(_db(st), _repo_name(l), "aws.cfn-gitsync", "sync", f"{s['ResourceName']}|CFN_STACK_SYNC")
    del st["syncs"][f"{s['ResourceName']}|CFN_STACK_SYNC"]
    return {}


def get_resource_sync_status(st, p):
    s = _sync(st, p)
    l = st["links"].get(s["RepositoryLinkId"]) or {}
    out = {"DesiredState": {"Branch": s["Branch"], "Directory": s["ConfigFile"], "OwnerId": s["OwnerId"], "Provider": s["ProviderType"],
                            "Repo": s["RepositoryName"], "Sha": s.get("_sha") or ""},
           "Target": s["ResourceName"], "LatestSync": s["_last"] or {"Events": [], "Status": s["_status"], "Target": s["ResourceName"]},
           "Events": s["_syncs"][:50]}
    if s.get("_lastOk"):
        out["LatestSuccessfulSync"] = s["_lastOk"]
    return out


def get_repository_sync_status(st, p):
    for s in st["syncs"].values():
        if s["Branch"] == p.get("Branch") and s["RepositoryLinkId"] == p.get("RepositoryLinkId"):
            return {"LatestSync": {"Events": s["_syncs"][:20], "StartedAt": (s["_last"] or {}).get("StartedAt"), "Status": s["_status"]}}
    raise CcError("ResourceNotFoundException", "No sync is configured for this repository branch.", 404)


# ── the sync itself ──────────────────────────────────────────────────────────────────────────
def set_token(st, p):
    ci.set_connection(_db(st), "github", p.get("Token"))
    return {}


def _load_config(text, path):
    try:
        if path.endswith((".yaml", ".yml")):
            d = k8s_yaml.load_all(text)
            d = d[0] if d else {}
        else:
            d = json.loads(text)
    except Exception as e:
        raise CcError("SyncError", f"deployment file '{path}' could not be parsed: {e}")
    if not isinstance(d, dict) or not d.get("template-file-path"):
        raise CcError("SyncError", f"deployment file '{path}' must define 'template-file-path'.")
    return d


def _cfn(call, params):
    r = call(params)
    if r.status >= 400:
        m = re.search(r"<Code>(.*?)</Code><Message>(.*?)</Message>", r.body if isinstance(r.body, str) else str(r.body), re.S)
        return False, (m.group(1), m.group(2)) if m else ("Error", "CloudFormation call failed")
    return True, None


def sync_now(st, s, call, cfn_store, reason="manual", changed=None, sha=None):
    """Run one sync. call(params)->CfnResponse is the real CloudFormation core. Mutates and returns the sync record."""
    l = st["links"][s["RepositoryLinkId"]]
    db = _db(st)
    started = _now()
    events = []
    ev = lambda e, ext="": events.append({"Event": e, "ExternalId": ext or reason, "Time": started, "Type": "CFN_STACK_SYNC"})
    s["_status"] = "INITIATED"
    status, err, noop = "SUCCEEDED", None, False
    try:
        repo = _repo_name(l)
        if l["OwnerId"] == "vyomi":
            tree = ci.tree(db, repo, s["Branch"])
        elif l["ProviderType"] == "GitHub":
            ci.ensure_repo(db, repo, s["Branch"])
            ci.import_external(db, repo, f"https://github.com/{l['OwnerId']}/{l['RepositoryName']}", s["Branch"], branch=s["Branch"], message="git sync fetch")
            tree = ci.tree(db, repo, s["Branch"])
        else:
            raise CcError("SyncError", f"{l['ProviderType']} repositories cannot be fetched by Vyomi (only GitHub and vyomi-owned repositories).")
        sha = ci._git.head(db, repo, s["Branch"]) or sha
        s["_sha"] = sha
        ev("Deployment file read", sha)
        if s["ConfigFile"] not in tree:
            raise CcError("SyncError", f"The deployment file '{s['ConfigFile']}' was not found on branch '{s['Branch']}'.")
        cfg = _load_config(tree[s["ConfigFile"]].decode(errors="replace"), s["ConfigFile"])
        tpath = cfg["template-file-path"]
        if tpath not in tree:
            raise CcError("SyncError", f"The template '{tpath}' named by the deployment file was not found on branch '{s['Branch']}'.")
        if changed is not None and s["TriggerResourceUpdateOn"] == "FILE_CHANGE" and not ({s["ConfigFile"], tpath} & set(changed)):
            ev("Skipped: neither the deployment file nor the template changed (FILE_CHANGE)")
            noop = True
        else:
            template = tree[tpath].decode(errors="replace")
            params = {k: str(v) for k, v in (cfg.get("parameters") or {}).items()}
            tags = {k: str(v) for k, v in (cfg.get("tags") or {}).items()}
            cur = cfn_store.stacks.get(cfn_store.stack_names.get(s["ResourceName"], ""))
            p = {"StackName": s["ResourceName"], "TemplateBody": template}
            for i, c in enumerate(("CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"), 1):
                p[f"Capabilities.member.{i}"] = c
            for i, (k, v) in enumerate(params.items(), 1):
                p[f"Parameters.member.{i}.ParameterKey"], p[f"Parameters.member.{i}.ParameterValue"] = k, v
            for i, (k, v) in enumerate(tags.items(), 1):
                p[f"Tags.member.{i}.Key"], p[f"Tags.member.{i}.Value"] = k, v
            if cur is None:
                p["Action"] = "CreateStack"
                ev("Creating stack")
            elif cur.get("template_body") == template and {k: str(v) for k, v in (cur.get("parameters") or {}).items()} == params:
                ev("No changes: the stack already matches the repository")
                noop = True
                p = None
            else:
                p["Action"] = "UpdateStack"
                ev("Updating stack")
            if p is not None:
                ok, e = _cfn(call, p)
                if not ok:
                    raise CcError(e[0], e[1])
                stk = cfn_store.stacks.get(cfn_store.stack_names.get(s["ResourceName"], ""))
                ev(f"Stack {stk['status'] if stk else 'unknown'}")
                if stk and stk["status"].endswith("FAILED") or (stk and "ROLLBACK" in stk["status"]):
                    raise CcError("SyncError", f"The stack ended in {stk['status']}: {stk.get('status_reason') or ''}".strip())
    except (CcError, ci.CiError) as e:
        status, err = "FAILED", getattr(e, "message", str(e))
        ev(f"Failed: {err}")
    run = {"Events": events, "InitialRevision": {"Branch": s["Branch"], "DeploymentFilePath": s["ConfigFile"], "OwnerId": s["OwnerId"], "RepositoryName": s["RepositoryName"],
                                                  "ProviderType": s["ProviderType"], "Sha": s.get("_sha") or ""},
           "StartedAt": started, "Status": status, "Target": s["ResourceName"], "Noop": noop}
    if err:
        run["Error"] = err
    s["_status"], s["_last"] = status, run
    s["_syncs"] = (events + s["_syncs"])[:100]
    if status == "SUCCEEDED":
        s["_lastOk"] = run
    return s


def on_push_consumer():
    def _fn(db, ev, hook, ctx, job):
        c = ctx or {}
        st, call, store = c.get("st"), c.get("call"), c.get("cfn_store")
        s = st["syncs"].get(hook["context"]["sync"]) if st else None
        if s:
            files = []
            try:
                a, b = ci._git.tree(db, ev["repo"], ev["after"]) or {}, (ci._git.tree(db, ev["repo"], ev["before"]) or {}) if ev.get("before") else {}
                files = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
            except Exception:
                files = None
            sync_now(st, s, call, store, f"push:{ev['after'][:7]}", files, ev["after"])
    return _fn


ci.register_consumer("aws.cfn-gitsync", on_push_consumer())


def vyomi_push(st, p, call, cfn_store):
    l = _link(st, p.get("RepositoryLinkId"))
    if l["OwnerId"] != "vyomi":
        raise CcError("InvalidInputException", "VyomiPush only applies to repository links owned by 'vyomi'; push to GitHub instead and call VyomiSync.")
    try:
        ev = ci.commit_files(_db(st), _repo_name(l), p.get("Branch") or "main", p.get("Files") or {}, p.get("Message") or "Update", p.get("Author") or "vyomi",
                             ctx={"st": st, "call": call, "cfn_store": cfn_store})
    except ci.CiError as e:
        raise CcError(e.code, e.message, e.status)
    return {"CommitId": ev["after"], "Branch": ev["branch"]}


def vyomi_sync(st, p, call, cfn_store):
    s = _sync(st, {"ResourceName": p.get("ResourceName"), "SyncType": p.get("SyncType") or "CFN_STACK_SYNC"})
    sync_now(st, s, call, cfn_store, "manual")
    return get_resource_sync_status(st, {"ResourceName": s["ResourceName"], "SyncType": s["SyncType"]})


_OPS = {
    "CreateConnection": create_connection, "GetConnection": get_connection, "ListConnections": list_connections, "DeleteConnection": delete_connection,
    "CreateRepositoryLink": create_repository_link, "GetRepositoryLink": get_repository_link, "ListRepositoryLinks": list_repository_links,
    "DeleteRepositoryLink": delete_repository_link, "CreateSyncConfiguration": create_sync_configuration,
    "GetSyncConfiguration": get_sync_configuration, "ListSyncConfigurations": list_sync_configurations,
    "UpdateSyncConfiguration": update_sync_configuration, "DeleteSyncConfiguration": delete_sync_configuration,
    "GetResourceSyncStatus": get_resource_sync_status, "GetRepositorySyncStatus": get_repository_sync_status,
    "VyomiSetGitHubToken": set_token,
}
_NEEDS_CFN = {"VyomiPush": vyomi_push, "VyomiSync": vyomi_sync}


def dispatch_json(bag, target, body: bytes, call, cfn_store):
    """-> (status, json_dict). ``target`` = the X-Amz-Target header."""
    op = target.rsplit(".", 1)[-1]
    try:
        p = json.loads(body) if body else {}
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return 400, {"__type": "InvalidInputException", "message": "The request body must be a JSON object."}
    st = state(bag)
    try:
        if op in _OPS:
            return 200, _OPS[op](st, p)
        if op in _NEEDS_CFN:
            return 200, _NEEDS_CFN[op](st, p, call, cfn_store)
    except CcError as e:
        return e.status, {"__type": e.code, "message": e.message}
    except ci.CiError as e:
        return e.status, {"__type": e.code, "message": e.message}
    return 400, {"__type": "UnknownOperationException", "message": f"Operation {op} is not supported."}
