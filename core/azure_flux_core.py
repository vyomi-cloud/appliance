"""AKS Flux GitOps (Microsoft.KubernetesConfiguration/fluxConfigurations) on the shared CI seam (substrate-free).

A fluxConfiguration on a managed cluster is a REAL reconcile over the cluster's Kubernetes object store
(core/azure_aks_k8s_core.py):

  source      GitRepository ``https://github.com/{owner}/{repo}`` (fetched with the user's own PAT when supplied via
              ``gitRepository.httpsUser`` + protected settings ``httpsKey``) or ``vyomi://{repo}`` (a repository in the
              cluster's CI seam: push with ``POST .../fluxConfigurations/{n}/vyomiPush`` or a real git push to Gitea).
  render      per kustomization ``path``: plain YAML directory or kustomization.yaml (core/k8s_render.py).
  apply       validated like ``kubectl apply`` and stamped ``kustomize.toolkit.fluxcd.io/name`` so ``prune: true`` removes
              what the repo no longer declares. ``dependsOn`` ordering, ``suspend`` and namespace scope are honoured.
  reconcile   on PUT, on every push to the source branch (CI hook), and via ``POST .../reconcile``.
  status      ARM ``statuses`` (GitRepository + Kustomization conditions), ``complianceState``,
              ``sourceSyncedCommitId`` (``branch@sha1:<commit>``), ``lastSourceSyncedAt`` -- all derived from the run.

Honest limits: no timer loop (syncIntervalInSeconds is stored, reconcile is event-driven + on demand); Helm charts /
HelmRelease and kustomize patches/generators are reported Not Ready, never faked; nothing is scheduled to nodes (the
k8s store holds objects only); Bucket/AzureBlob sources are rejected.
"""
from __future__ import annotations

import datetime
import re

try:
    from core import ci_core as ci
    from core import azure_aks_k8s_core as k8s
    from core import k8s_render
except ImportError:                                      # Pyodide flat layout
    import ci_core as ci                                 # type: ignore
    import azure_aks_k8s_core as k8s                     # type: ignore
    import k8s_render                                    # type: ignore

AKS = "microsoft.containerservice/managedclusters"
_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,251}[a-z0-9])?$")
_LABEL = "kustomize.toolkit.fluxcd.io/name"


def handles(full_type: str) -> bool:
    return str(full_type or "").lower().endswith("/providers/fluxconfigurations")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def _cluster_id(rid):
    low = rid.lower()
    i = low.find("/providers/microsoft.kubernetesconfiguration/")
    return rid[:i] if i > 0 else rid


def validate(state, full_type, rid, payload, existing, sub, rg):
    cid = _cluster_id(rid)
    cl = state.get(cid.lower())
    if cl is None or (cl.get("_type") or "").lower() != AKS:
        return _err(404, "ParentResourceNotFound", f"The managed cluster '{cid.rsplit('/', 1)[-1]}' was not found.")
    name = rid.rsplit("/", 1)[-1]
    if not _NAME.match(name):
        return _err(400, "InvalidParameter", f"Flux configuration name '{name}' must be lower case alphanumeric/hyphen, 1-253 characters.")
    p = dict((existing or {}).get("properties") or {})
    p.update((payload or {}).get("properties") or {})
    sk = p.get("sourceKind") or "GitRepository"
    if sk != "GitRepository":
        return _err(400, "InvalidParameter", f"sourceKind '{sk}' is not supported (Bucket/AzureBlob need an object-store source controller); use GitRepository.")
    if str(p.get("scope") or "cluster").lower() not in ("cluster", "namespace"):
        return _err(400, "InvalidParameter", "scope must be 'cluster' or 'namespace'.")
    if not re.match(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", str(p.get("namespace") or "default")):
        return _err(400, "InvalidParameter", "namespace must be a valid DNS-1123 label.")
    g = p.get("gitRepository") or {}
    url = str(g.get("url") or "")
    if not re.match(r"^(https://[^\s/]+/\S+|http://[^\s/]+/\S+|ssh://\S+|vyomi://[A-Za-z0-9][A-Za-z0-9._-]{0,99})$", url):
        return _err(400, "InvalidParameter", "properties.gitRepository.url is required (https://, http://, ssh:// or vyomi://{repo}).")
    ref = g.get("repositoryRef") or {}
    if sum(1 for k in ("branch", "tag", "semver", "commit") if ref.get(k)) > 1:
        return _err(400, "InvalidParameter", "repositoryRef may set only one of branch, tag, semver, commit.")
    if g.get("syncIntervalInSeconds") is not None and int(g["syncIntervalInSeconds"]) < 1:
        return _err(400, "InvalidParameter", "syncIntervalInSeconds must be >= 1.")
    ks = p.get("kustomizations") or {}
    if not isinstance(ks, dict) or not ks:
        return _err(400, "InvalidParameter", "properties.kustomizations must define at least one kustomization.")
    for kn, k in ks.items():
        if not _NAME.match(kn):
            return _err(400, "InvalidParameter", f"kustomization name '{kn}' must be lower case alphanumeric/hyphen.")
        for d in (k or {}).get("dependsOn") or []:
            if d not in ks:
                return _err(400, "InvalidParameter", f"kustomization '{kn}' dependsOn '{d}', which is not defined.")
    if _cycle(ks):
        return _err(400, "InvalidParameter", "kustomization dependsOn contains a cycle.")
    return None


def _cycle(ks):
    seen = {}

    def visit(n):
        if seen.get(n) == 1:
            return True
        if seen.get(n) == 2:
            return False
        seen[n] = 1
        for d in (ks[n] or {}).get("dependsOn") or []:
            if visit(d):
                return True
        seen[n] = 2
        return False
    return any(visit(n) for n in ks)


def _order(ks):
    done, out = set(), []

    def visit(n):
        if n in done:
            return
        done.add(n)
        for d in (ks[n] or {}).get("dependsOn") or []:
            visit(d)
        out.append(n)
    for n in sorted(ks):
        visit(n)
    return out


def _ensure_extension(state, cluster, cid, sub, rg):
    """`az k8s-configuration flux create` installs the microsoft.flux extension on the cluster first."""
    xid = f"{cid}/providers/Microsoft.KubernetesConfiguration/extensions/flux"
    if xid.lower() not in state:
        state[xid.lower()] = {"id": xid, "name": "flux", "type": "Microsoft.KubernetesConfiguration/extensions",
                              "_type": f"{AKS}/providers/extensions", "_sub": sub, "_rg": rg, "_created": _now(),
                              "properties": {"extensionType": "microsoft.flux", "autoUpgradeMinorVersion": True, "releaseTrain": "Stable",
                                             "scope": {"cluster": {"releaseNamespace": "flux-system"}}, "currentVersion": "1.9.1",
                                             "installedVersion": "1.9.1", "provisioningState": "Succeeded", "isSystemExtension": False,
                                             "statuses": [{"code": "Recorded", "displayStatus": "Installed by Flux configuration", "level": "Information",
                                                           "message": "Vyomi stores the extension; the Flux controllers are modelled by the reconcile in azure_flux_core."}]}}


def _cond(ok, reason, message):
    return [{"type": "Ready", "status": "True" if ok else "False", "reason": reason, "message": message, "lastTransitionTime": _now()}]


def _source(cluster, rec, p, ctx_token=None):
    """Return (repo, branch_or_ref, sha, error)."""
    db = ci.get_db(cluster)
    g = p["gitRepository"]
    url, ref = g["url"], g.get("repositoryRef") or {}
    rname = ref.get("branch") or ref.get("tag") or ref.get("commit") or "main"
    if url.startswith("vyomi://"):
        repo = url[len("vyomi://"):]
        try:
            tree_ok = ci.tree(db, repo, rname) is not None
        except ci.CiError as e:
            return repo, rname, None, f"failed to checkout and determine revision: {e.message}"
        sha = ci._git.head(db, repo, rname) or rname
        return repo, rname, sha, None
    m = ci._GH.match(url)
    if not m:
        return None, rname, None, f"failed to checkout and determine revision: only https://github.com/{{owner}}/{{repo}} and vyomi://{{repo}} sources can be fetched ({url})"
    repo = f"{m.group(1)}--{m.group(2)}"
    tok = (rec.get("_protected") or {}).get("httpsKey")
    if tok:
        ci.set_connection(db, "github", tok)
    try:
        ci.ensure_repo(db, repo, rname)
        ci.import_external(db, repo, url, rname, branch=rname, message=f"flux source {url}@{rname}")
    except ci.CiError as e:
        return repo, rname, None, f"failed to checkout and determine revision: {e.message}"
    return repo, rname, ci._git.head(db, repo, rname), None


def reconcile(state, rec, trigger="manual"):
    """One reconcile pass of this fluxConfiguration. Updates rec['properties'] status. Returns the properties."""
    p = rec["properties"]
    cid = _cluster_id(rec["id"])
    cluster = state.get(cid.lower())
    name = rec["name"]
    ns = p.get("namespace") or "flux-system"
    now = _now()
    statuses = []
    if p.get("suspend"):
        p.update({"complianceState": "Pending", "statusUpdatedAt": now, "provisioningState": "Succeeded",
                  "statuses": [{"kind": "GitRepository", "name": name, "namespace": ns, "complianceState": "Pending",
                                "statusConditions": _cond(False, "Suspended", "reconciliation is suspended")}]})
        return p
    repo, ref, sha, err = _source(cluster, rec, p)
    src = {"kind": "GitRepository", "name": name, "namespace": ns}
    if err:
        src.update(complianceState="Non-Compliant", statusConditions=_cond(False, "GitOperationFailed", err))
        p.update({"complianceState": "Non-Compliant", "statusUpdatedAt": now, "provisioningState": "Succeeded", "statuses": [src],
                  "errorMessage": err})
        return p
    rev = f"{ref}@sha1:{sha}"
    src.update(complianceState="Compliant", statusConditions=_cond(True, "Succeeded", f"stored artifact for revision '{rev}'"))
    statuses.append(src)
    db = ci.get_db(cluster)
    tree = ci._git.tree(db, repo, sha) or ci._git.tree(db, repo, ref) or {}
    ks, results = p.get("kustomizations") or {}, {}
    all_ok = True
    for kn in _order(ks):
        k = ks[kn] or {}
        kstat = {"kind": "Kustomization", "name": f"{name}-{kn}", "namespace": ns}
        bad = next((d for d in k.get("dependsOn") or [] if not results.get(d)), None)
        owner = (_LABEL, f"{name}-{kn}")
        try:
            if bad:
                raise k8s_render.RenderError(f"dependency '{ns}/{name}-{bad}' is not ready")
            docs = k8s_render.render_dir(tree, k.get("path") or "")
            helm = k8s_render.has_helm(docs)
            if helm:
                raise k8s_render.RenderError(f"{helm[0]['kind']}/{helm[0].get('metadata', {}).get('name')}: the Helm controller is not simulated, so Helm charts cannot be installed")
            default_ns = ns if str(p.get("scope") or "cluster").lower() == "namespace" else "default"
            applied = k8s.apply_manifests(cluster, docs, default_ns, owner)
            gone = []
            if k.get("prune"):
                keep = {(d["kind"], (d.get("metadata") or {}).get("namespace") or (default_ns if k8s._kind_spec(cluster, d["kind"]) and k8s._kind_spec(cluster, d["kind"])[4] else None),
                         (d.get("metadata") or {})["name"]) for d in docs if isinstance(d, dict) and d.get("kind")}
                gone = k8s.prune_owned(cluster, owner, keep)
            msg = f"Applied revision: {rev}" + ("" if not gone else f" (pruned {len(gone)})")
            kstat.update(complianceState="Compliant", statusConditions=_cond(True, "ReconciliationSucceeded", msg),
                         appliedObjects=len(applied), prunedObjects=len(gone))
            results[kn] = True
        except (k8s_render.RenderError, k8s.KubectlError) as e:
            all_ok, results[kn] = False, False
            kstat.update(complianceState="Non-Compliant", statusConditions=_cond(False, "BuildFailed" if isinstance(e, k8s_render.RenderError) else "ReconciliationFailed", str(e)))
        statuses.append(kstat)
    p.update({"complianceState": "Compliant" if all_ok else "Non-Compliant", "statuses": statuses, "statusUpdatedAt": now,
              "lastSourceSyncedAt": now, "sourceSyncedCommitId": rev, "provisioningState": "Succeeded", "lastTrigger": trigger})
    p.pop("errorMessage", None) if all_ok else p.__setitem__("errorMessage", next(s["statusConditions"][0]["message"] for s in statuses if s["complianceState"] != "Compliant"))
    return p


def after_put(state, rec, payload, prev=None):
    p = rec.setdefault("properties", {})
    cid = _cluster_id(rec["id"])
    cluster = state[cid.lower()]
    rec["type"] = "Microsoft.KubernetesConfiguration/fluxConfigurations"
    prot = (payload or {}).get("properties", {}).get("configurationProtectedSettings") or {}
    g = p.get("gitRepository") or {}
    key = (prot.get("httpsKey") or g.pop("httpsKey", None))
    if key:
        rec.setdefault("_protected", {})["httpsKey"] = key
    p.pop("configurationProtectedSettings", None)
    p.setdefault("sourceKind", "GitRepository")
    p.setdefault("scope", "cluster")
    p.setdefault("namespace", rec["name"])
    g.setdefault("syncIntervalInSeconds", 600)
    g.setdefault("timeoutInSeconds", 600)
    g.setdefault("repositoryRef", {"branch": "main"})
    p["gitRepository"] = g
    for kn, k in (p.get("kustomizations") or {}).items():
        k = p["kustomizations"][kn] = dict(k or {})
        k.setdefault("path", "")
        k.setdefault("prune", False)
        k.setdefault("syncIntervalInSeconds", 600)
        k.setdefault("timeoutInSeconds", 600)
        k.setdefault("retryIntervalInSeconds", 600)
        k.setdefault("force", False)
        k["name"] = kn
    p.setdefault("suspend", False)
    p["repositoryPublicKey"] = ""
    p["isHelmEnabled"] = False
    sub, rg = rec.get("_sub"), rec.get("_rg")
    _ensure_extension(state, cluster, cid, sub, rg)
    # (re)register the push hook on the source repo so a push reconciles this configuration
    url = g["url"]
    m = ci._GH.match(url)
    repo = url[len("vyomi://"):] if url.startswith("vyomi://") else (f"{m.group(1)}--{m.group(2)}" if m else None)
    db = ci.get_db(cluster)
    if repo:
        try:
            ci.ensure_repo(db, repo, (g["repositoryRef"] or {}).get("branch") or "main")
            ci.remove_hooks(db, repo, "azure.flux", "flux", rec["id"].lower())
            ci.add_hook(db, repo, "azure.flux", branch=(g["repositoryRef"] or {}).get("branch"), context={"flux": rec["id"].lower()})
        except ci.CiError:
            pass
    rec["systemData"] = rec.get("systemData") or {"createdByType": "User", "createdAt": _now()}
    reconcile(state, rec, "put")


def before_delete(state, rec):
    cid = _cluster_id(rec["id"])
    cluster = state.get(cid.lower())
    if cluster is None:
        return None
    for kn in (rec.get("properties") or {}).get("kustomizations") or {}:
        k8s.prune_owned(cluster, (_LABEL, f"{rec['name']}-{kn}"), set())
    db = ci.get_db(cluster)
    for r in list(db["repos"]):
        ci.remove_hooks(db, r, "azure.flux", "flux", rec["id"].lower())
    return None


def action(state, rec, verb, payload):
    """POST .../fluxConfigurations/{n}/reconcile | vyomiPush. Returns an ARM response dict."""
    verb = verb.lower()
    cluster = state[_cluster_id(rec["id"]).lower()]
    if verb == "reconcile":
        reconcile(state, rec, "manual")
        return {"status": 200, "headers": {}, "body": {"id": rec["id"], "name": rec["name"], "properties": rec["properties"]}}
    if verb == "vyomipush":
        g = rec["properties"]["gitRepository"]
        if not g["url"].startswith("vyomi://"):
            return _err(400, "InvalidParameter", "vyomiPush only applies to a vyomi:// source; push to the real GitHub repository instead.")
        repo = g["url"][len("vyomi://"):]
        p = payload or {}
        try:
            ev = ci.commit_files(ci.get_db(cluster), repo, p.get("branch") or (g.get("repositoryRef") or {}).get("branch") or "main",
                                 p.get("files") or {}, p.get("message") or "Update", p.get("author") or "vyomi", ctx={"state": state})
        except ci.CiError as e:
            return _err(e.status if hasattr(e, "status") else 400, e.code, e.message)
        return {"status": 200, "headers": {}, "body": {"commit": ev["after"], "branch": ev["branch"], "properties": rec["properties"]}}
    return _err(404, "NotFound", f"Unknown action '{verb}'.")


def _on_push(db, ev, hook, ctx, job):
    st = (ctx or {}).get("state")
    if st is None:
        return
    rec = st.get(hook["context"].get("flux"))
    if rec:
        reconcile(st, rec, f"push:{ev['after'][:7]}")


ci.register_consumer("azure.flux", _on_push)
