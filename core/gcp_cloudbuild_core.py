"""Cloud Build API v1 (cloudbuild.googleapis.com) — builds + triggers on the shared CI seam (core/ci_core.py).

Substrate-independent (stdlib only). State: store.ext["cloudbuild_*"] on the Monitoring store (+ the CI seam db at store.ext["_ci"]).

  /v1/projects/{p}[/locations/{l}]/builds[/{id}]       create (LRO, runs the build), get, list, :cancel, :retry
  /v1/projects/{p}/triggers[/{id}]                     create/get/list/patch/delete, :run  (regional triggers are not routed:
                                                       that path is Eventarc's)
  /v1/projects/{p}/triggers:vyomiPush                  Vyomi extension: commit files to a source repo (the Gitea/vyomi:// seam);
                                                       matching triggers fire like a real push (body {repoName, branch, files, message})
  /v1/projects/{p}/triggers:vyomiReconcile             detect pushes made straight to the git host and fire their triggers

Source: repoSource {repoName, branchName|tagName|commitSha, dir} (a repo in the CI seam), gitSource {url (GitHub), revision}
(fetched with the user's own PAT), storageSource {bucket, object} (.tgz / .zip read from the simulator's GCS).
Build config: inline steps, or a trigger's `filename` (cloudbuild.json / cloudbuild.yaml in the repo) or inline `build`.

Steps really execute on the shared builder (BuildKit on the offline appliance): `docker build [-t T] [-f F] [--build-arg A=B] CTX`
builds the image, `docker push T` and the top-level `images:` push the built image into the simulated Artifact Registry
(gcp_artifactregistry_core.push_built_image) — a missing repository fails the step like the real registry. Substitutions
($PROJECT_ID, $BUILD_ID, $COMMIT_SHA, $SHORT_SHA, $BRANCH_NAME, $REPO_NAME, $TAG_NAME, $LOCATION, user `_VARS`) are applied and validated.

Honest limits: only docker build/push steps and `gcloud run deploy|services update` (against the simulated Cloud Run) run (no other builder containers: npm, bash...), no Cloud Build worker pools,
approvals, GitHub PR / pubsub / webhook triggers, Cloud Logging streaming (logs are on the build as `vyomiLogs`); builds run
synchronously (so :cancel only ever sees finished builds); on Nano there is no container builder so image builds FAIL with that reason.
"""
from __future__ import annotations

import copy
import fnmatch
import io
import json
import re
import tarfile
import uuid
import zipfile
from datetime import datetime, timezone

try:
    from core import ci_core as ci
    from core import gcp_artifactregistry_core as ar
except ImportError:  # pragma: no cover - Pyodide flat layout
    import ci_core as ci  # type: ignore
    import gcp_artifactregistry_core as ar  # type: ignore

BUILTIN = ("PROJECT_ID", "PROJECT_NUMBER", "BUILD_ID", "LOCATION", "COMMIT_SHA", "SHORT_SHA", "REPO_NAME", "BRANCH_NAME", "TAG_NAME", "REVISION_ID", "TRIGGER_NAME")
AR_REF = re.compile(r"^([a-z0-9-]+)-docker\.pkg\.dev/([^/]+)/([^/]+)/(.+?)(?::([\w][\w.-]{0,127}))?$")
DOCKER_BUILDERS = ("gcr.io/cloud-builders/docker", "docker", "docker:latest", "gcr.io/cloud-builders/docker:latest")
STATUS = ("QUEUED", "WORKING", "SUCCESS", "FAILURE", "INTERNAL_ERROR", "TIMEOUT", "CANCELLED", "EXPIRED")


class Resp:
    media_type = "application/json"

    def __init__(self, status, obj):
        self.status, self.headers = status, {}
        self.body = json.dumps(obj).encode()


class _E(Exception):
    def __init__(self, status, gcp_status, message):
        super().__init__(message)
        self.status, self.gcp_status, self.message = status, gcp_status, message


def _bad(m):
    return _E(400, "INVALID_ARGUMENT", m)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _x(store, coll):
    if getattr(store, "ext", None) is None:
        store.ext = {}
    return store.ext.setdefault("cloudbuild_" + coll, {})


def _view(o):
    return {k: copy.deepcopy(v) for k, v in o.items() if not k.startswith("_")}


def _page(items, query, key):
    try:
        size = min(int(query.get("pageSize") or 100), 1000)
        start = int(query.get("pageToken") or 0)
    except Exception:
        raise _bad("Invalid pageSize/pageToken.")
    out = {key: items[start:start + size]}
    if start + size < len(items):
        out["nextPageToken"] = str(start + size)
    return out


def _op(project, resource, kind):
    meta = {"@type": "type.googleapis.com/google.devtools.cloudbuild.v1.BuildOperationMetadata"}
    if kind == "Build":
        meta["build"] = resource
    return {"name": "projects/%s/locations/global/operations/%s" % (project, uuid.uuid4()), "metadata": meta, "done": True,
            "response": dict(resource, **{"@type": "type.googleapis.com/google.devtools.cloudbuild.v1.%s" % kind})}


# ── minimal YAML subset (cloudbuild.yaml: maps, lists, scalars, flow lists/maps, block scalars, comments) ──
def _scalar(v):
    v = v.strip()
    if v in ("", "~", "null"):
        return None
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        return json.loads(v) if v[0] == '"' else v[1:-1].replace("''", "'")
    if v[0] in "[{" and v[-1] in "]}":
        return _flow(v)
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def _split_top(s):
    out, cur, depth, q = [], "", 0, None
    for ch in s:
        if q:
            cur += ch
            q = None if ch == q else q
            continue
        if ch in "\"'":
            q = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _flow(v):
    inner = v[1:-1]
    if v[0] == "[":
        return [_scalar(x) for x in _split_top(inner)]
    d = {}
    for x in _split_top(inner):
        k, _, val = x.partition(":")
        d[k.strip().strip("'\"")] = _scalar(val)
    return d


def _strip_comment(line):
    q = None
    for i, ch in enumerate(line):
        if q:
            q = None if ch == q else q
        elif ch in "\"'":
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] == " "):
            return line[:i]
    return line


def parse_yaml(text):
    raw, lines, i = text.splitlines(), [], 0
    while i < len(raw):
        s = _strip_comment(raw[i]).rstrip()
        if not s.strip():
            i += 1
            continue
        ind, body = len(s) - len(s.lstrip()), s.strip()
        m = re.match(r"^((?:- )*)(.*?:)\s*(\|[-+]?|>[-+]?)$", body)
        if m:
            j, blk = i + 1, []
            while j < len(raw) and (not raw[j].strip() or len(raw[j]) - len(raw[j].lstrip()) > ind):
                blk.append(raw[j])
                j += 1
            bi = min([len(b) - len(b.lstrip()) for b in blk if b.strip()] or [0])
            txt = "\n".join(b[bi:] for b in blk).rstrip("\n") + "\n"
            if m.group(3).startswith(">"):
                txt = txt.replace("\n", " ").strip() + "\n"
            lines.append((ind, m.group(1) + m.group(2) + " " + json.dumps(txt)))
            i = j
            continue
        lines.append((ind, body))
        i += 1
    pos = [0]

    def block(ind):
        if lines[pos[0]][1].startswith("- ") or lines[pos[0]][1] == "-":
            out = []
            while pos[0] < len(lines) and lines[pos[0]][0] == ind and (lines[pos[0]][1].startswith("- ") or lines[pos[0]][1] == "-"):
                b = lines[pos[0]][1][2:]
                if not b.strip():
                    pos[0] += 1
                    out.append(block(lines[pos[0]][0]) if pos[0] < len(lines) and lines[pos[0]][0] > ind else None)
                    continue
                lines[pos[0]] = (ind + 2, b)
                if re.match(r"^[^\s\[{'\"][^:]*:(\s|$)", b) or re.match(r"^['\"].*['\"]:(\s|$)", b):
                    out.append(block(ind + 2))
                else:
                    pos[0] += 1
                    out.append(_scalar(b))
            return out
        d = {}
        while pos[0] < len(lines) and lines[pos[0]][0] == ind:
            body = lines[pos[0]][1]
            m = re.match(r"^(['\"]?)([^'\":]+|[^'\"]+?)\1:(?:\s+(.*))?$", body)
            if not m:
                raise ValueError("cannot parse YAML line: " + body)
            k, v = m.group(2).strip(), m.group(3)
            pos[0] += 1
            if v is None or v == "":
                nxt = lines[pos[0]] if pos[0] < len(lines) else None
                d[k] = block(nxt[0]) if nxt and (nxt[0] > ind or (nxt[0] == ind and nxt[1].startswith("-"))) else None
            else:
                d[k] = _scalar(v)
        return d
    return block(lines[0][0]) if lines else {}


# ── substitutions ────────────────────────────────────────────────────────────────────────────
_SUB = re.compile(r"\$(\$|\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Z_][A-Z0-9_]*))")


def _sub_str(s, values, loose):
    def r(m):
        if m.group(1) == "$":
            return "$"
        k = m.group(2) or m.group(3)
        if k in values:
            return values[k]
        if k.startswith("_"):
            if loose:
                return ""
            raise _bad('key in the template "%s" is not matched in the substitution map' % k)
        if k in BUILTIN:
            return ""
        raise _bad('key in the template "%s" is not a valid built-in substitution' % k)
    return _SUB.sub(r, s)


def _sub_all(o, values, loose):
    if isinstance(o, str):
        return _sub_str(o, values, loose)
    if isinstance(o, list):
        return [_sub_all(x, values, loose) for x in o]
    if isinstance(o, dict):
        return {k: _sub_all(v, values, loose) for k, v in o.items()}
    return o


def _timeout(v, default=600):
    if v is None:
        return default
    m = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(v))
    if not m or not 0 < float(m.group(1)) <= 86400:
        raise _bad("Invalid timeout '%s': must be a duration in seconds (e.g. 600s) of at most 86400s." % v)
    return float(m.group(1))


def _check_config(cfg):
    steps = cfg.get("steps")
    if not isinstance(steps, list) or not steps:
        raise _bad("Invalid build: a build must have at least one step (steps).")
    ids = set()
    for i, s in enumerate(steps):
        if not isinstance(s, dict) or not s.get("name"):
            raise _bad("Invalid build: steps[%d].name is required." % i)
        if s.get("args") is not None and (not isinstance(s["args"], list) or any(not isinstance(a, str) for a in s["args"])):
            raise _bad("Invalid build: steps[%d].args must be a list of strings." % i)
        if s.get("id"):
            if s["id"] in ids:
                raise _bad("Invalid build: duplicate step id '%s'." % s["id"])
            ids.add(s["id"])
    for w in [w for s in steps for w in s.get("waitFor") or []]:
        if w not in ids and w != "-":
            raise _bad("Invalid build: waitFor references unknown step id '%s'." % w)
    imgs = cfg.get("images")
    if imgs is not None and (not isinstance(imgs, list) or any(not isinstance(a, str) for a in imgs)):
        raise _bad("Invalid build: images must be a list of strings.")
    _timeout(cfg.get("timeout"))
    for k in (cfg.get("substitutions") or {}):
        if not re.fullmatch(r"_[A-Z0-9_]+", k):
            raise _bad("Invalid build: user substitution '%s' must start with an underscore and use A-Z, 0-9 and _." % k)


# ── Artifact Registry push ───────────────────────────────────────────────────────────────────
def push_to_ar(ar_store, project, ref, primary_tag):
    """What `docker push LOC-docker.pkg.dev/P/REPO/IMAGE[:TAG]` does for an image built on the CI seam. Returns the digest."""
    m = AR_REF.match(ref or "")
    if not m:
        raise ci.CiError("PushFailed", "denied: only Artifact Registry references (LOCATION-docker.pkg.dev/PROJECT/REPO/IMAGE[:TAG]) can be pushed; "
                                       "Container Registry (gcr.io) is not simulated.", 400)
    loc, proj, repo, image, tag = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5) or "latest"
    if proj != project:
        raise ci.CiError("PushFailed", 'denied: Permission "artifactregistry.repositories.uploadArtifacts" denied on resource "projects/%s/locations/%s/repositories/%s".' % (proj, loc, repo), 403)
    if ar_store is None:
        raise ci.CiError("PushFailed", "Artifact Registry is not available in this runtime.", 502)
    rname = ar._repo_name(proj, loc, repo)
    r = ar_store.repos.get(rname)
    if r is None:
        raise ci.CiError("PushFailed", 'name unknown: Repository "%s" not found' % repo, 404)
    if r.get("format") != "DOCKER":
        raise ci.CiError("PushFailed", 'Repository "%s" is format %s, not DOCKER.' % (repo, r.get("format")), 400)
    img = ci.export_image(primary_tag)
    try:
        ar.push_built_image(ar_store, rname, image, tag, img)
    except ar.CmekKeyUnavailable as e:
        raise ci.CiError("PushFailed", str(e), 400)
    return img["digest"]


# ── source resolution ────────────────────────────────────────────────────────────────────────
def _unpack(raw, name):
    files = {}
    if name.endswith(".zip") or raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            for n in z.namelist():
                if not n.endswith("/"):
                    files[n.lstrip("./")] = z.read(n)
    else:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:*") as t:
            for mem in t.getmembers():
                if mem.isfile():
                    files[mem.name.lstrip("./")] = t.extractfile(mem).read()
    if not files:
        raise ci.CiError("EmptySource", "The source archive contains no files.", 400)
    return files


def _resolve_source(store, project, bid, source, ctx):
    """-> (tree {path: bytes}, resolved sourceProvenance dict)."""
    db = ci.get_db(store.ext)
    source = source or {}
    if source.get("repoSource"):
        rs = source["repoSource"]
        repo = rs.get("repoName") or "default"
        ref = rs.get("commitSha") or rs.get("branchName") or rs.get("tagName")
        if repo not in db["repos"]:
            raise ci.CiError("RepoNotFound", "Source repository '%s' was not found in project '%s'." % (repo, project), 404)
        ref = ref or db["repos"][repo]["defaultBranch"]
        tree = ci.tree(db, repo, ref)
        if tree is None:
            raise ci.CiError("RefNotFound", "Revision '%s' was not found in repository '%s'." % (ref, repo), 404)
        sha = ci._git.head(db, repo, ref) or ref
        sub = (rs.get("dir") or "").strip("/")
        if sub:
            tree = {p[len(sub) + 1:]: v for p, v in tree.items() if p.startswith(sub + "/")}
        return tree, {"resolvedRepoSource": {"projectId": project, "repoName": repo, "commitSha": sha}}
    if source.get("gitSource"):
        gs = source["gitSource"]
        repo = "git-" + bid[:12]
        ci.import_external(db, repo, gs.get("url", ""), gs.get("revision") or "main", branch="main", message="cloud build source")
        tree = ci.tree(db, repo, "main")
        sha = ci._git.head(db, repo, "main")
        ci.delete_repo(db, repo)
        return tree, {"resolvedGitSource": {"url": gs.get("url"), "revision": gs.get("revision") or "main", "commitSha": sha}}
    if source.get("storageSource"):
        ss = source["storageSource"]
        rd = (ctx or {}).get("gcs_read")
        if rd is None:
            raise ci.CiError("StorageUnavailable", "Cloud Storage is not available in this runtime.", 502)
        raw = rd(ss.get("bucket", ""), ss.get("object", ""))
        if raw is None:
            raise ci.CiError("SourceNotFound", "gs://%s/%s was not found." % (ss.get("bucket"), ss.get("object")), 404)
        return _unpack(raw, ss.get("object", "")), {"resolvedStorageSource": {"bucket": ss.get("bucket"), "object": ss.get("object")}}
    return {}, {}


# ── step execution ───────────────────────────────────────────────────────────────────────────
class _StepFail(Exception):
    pass


def _norm(p):
    parts = [x for x in (p or "").split("/") if x not in ("", ".")]
    return "/".join(parts)


def _docker_build(store, build, step, args, tree, logs, local):
    tags, f, bargs, ctxdir, i = [], None, [], None, 1
    while i < len(args):
        a = args[i]
        if a in ("-t", "--tag") and i + 1 < len(args):
            tags.append(args[i + 1]); i += 2
        elif a.startswith("--tag="):
            tags.append(a[6:]); i += 1
        elif a in ("-f", "--file") and i + 1 < len(args):
            f = args[i + 1]; i += 2
        elif a.startswith("--file="):
            f = a[7:]; i += 1
        elif a == "--build-arg" and i + 1 < len(args):
            bargs.append(args[i + 1]); i += 2
        elif a.startswith("--build-arg="):
            bargs.append(a[12:]); i += 1
        elif a in ("--no-cache", "--pull", "--quiet", "-q", "--rm"):
            i += 1
        elif a.startswith("-"):
            raise _StepFail("docker build: flag '%s' is not supported by Vyomi's builder step." % a)
        else:
            ctxdir = a; i += 1
    if ctxdir is None:
        raise _StepFail('"docker build" requires exactly 1 argument (the build context).')
    cwd = _norm(step.get("dir"))
    prefix = _norm("%s/%s" % (cwd, ctxdir))
    ctree = {(p[len(prefix) + 1:] if prefix else p): v for p, v in tree.items() if not prefix or p.startswith(prefix + "/")}
    dfpath = _norm("%s/%s" % (cwd, f)) if f else (prefix + "/Dockerfile" if prefix else "Dockerfile")
    if dfpath not in tree:
        raise _StepFail("unable to prepare context: unable to evaluate symlinks in Dockerfile path: lstat /workspace/%s: no such file or directory" % dfpath)
    ctree["Dockerfile"] = tree[dfpath]
    if not tags:
        tags = ["vyomi-cb/%s:%s" % (build["projectId"], build["id"][:12])]
    db = ci.get_db(store.ext)
    repo = "cb-%s-%d" % (build["id"][:12], len(local))
    ci.create_repo(db, repo)
    try:
        ci.commit_files(db, repo, "main", {k: v for k, v in ctree.items()}, "cloud build context", "cloudbuild")
        job = ci.submit_job(db, repo, "main", {"kind": "image", "tag": tags[0], "buildArgs": bargs}, trigger="cloudbuild")
    finally:
        ci.delete_repo(db, repo)
    logs.extend(l["message"] for l in job["logs"])
    if job["status"] != "Succeeded":
        raise _StepFail(job["error"] or "docker build failed")
    for t in tags:
        local[t] = {"primary": tags[0], "digest": job["artifact"]["digest"]}
    return {"images": tags}


GCLOUD_BUILDERS = ("gcr.io/google.com/cloudsdktool/cloud-sdk", "gcr.io/google.com/cloudsdktool/cloud-sdk:slim", "gcr.io/google.com/cloudsdktool/cloud-sdk:latest",
                   "gcr.io/cloud-builders/gcloud", "gcr.io/cloud-builders/gcloud:latest")
_DEPLOY_FLAGS = {"image", "region", "platform", "quiet", "port", "set-env-vars", "labels", "allow-unauthenticated", "project", "memory", "cpu",
                 "min-instances", "max-instances", "no-traffic", "tag"}


def _gcloud_run(build, step, args, logs, ctx):
    """`gcloud run deploy|services update SERVICE --image IMG --region R [--labels k=v,...]` — the deploy step of Cloud Run's
    continuous-deployment build config — executed against the simulated Cloud Run (ctx['run_deploy'])."""
    argv = list(args)
    if (step.get("entrypoint") or "gcloud") not in ("gcloud", "") and argv[:1] != ["run"]:
        raise _StepFail("entrypoint '%s' cannot run in Vyomi (only gcloud run deploy / services update)." % step.get("entrypoint"))
    if argv and argv[0] == "gcloud":
        argv = argv[1:]
    if argv[:2] == ["run", "deploy"]:
        verb, rest, create = "deploy", argv[2:], True
    elif argv[:3] == ["run", "services", "update"]:
        verb, rest, create = "services update", argv[3:], False
    else:
        raise _StepFail("builder step 'gcloud %s' cannot run in Vyomi: only gcloud run deploy / gcloud run services update are executed." % " ".join(argv[:3]))
    opts, pos, i = {}, [], 0
    while i < len(rest):
        a = rest[i]
        if a.startswith("--"):
            k, eq, v = a[2:].partition("=")
            if k not in _DEPLOY_FLAGS:
                raise _StepFail("gcloud run %s: flag --%s is not supported by Vyomi's builder step." % (verb, k))
            if not eq and k not in ("quiet", "allow-unauthenticated", "no-traffic") and i + 1 < len(rest):
                v = rest[i + 1]
                i += 1
            opts[k] = v or True
        else:
            pos.append(a)
        i += 1
    if len(pos) != 1:
        raise _StepFail("gcloud run %s requires exactly one SERVICE argument." % verb)
    if not opts.get("image") and create:
        raise _StepFail("gcloud run deploy: --image (or --source) is required.")
    if not opts.get("region"):
        raise _StepFail("gcloud run %s: --region is required (no default region is configured)." % verb)
    fn = (ctx or {}).get("run_deploy")
    if not callable(fn):
        raise _StepFail("Cloud Run is not available to this build.")
    try:
        msg = fn(build["projectId"], opts["region"], pos[0], opts, create)
    except ValueError as e:
        raise _StepFail(str(e))
    logs.append(msg)
    return {}


def _run_step(store, build, step, tree, logs, local, ctx):
    name, args = step["name"], step.get("args") or []
    if name in GCLOUD_BUILDERS and args:
        logs.append("Starting Step #%s - \"%s\": gcloud %s" % (build["steps"].index(step), step.get("id") or name, " ".join(args)))
        return _gcloud_run(build, step, args, logs, ctx)
    if name not in DOCKER_BUILDERS or not args:
        raise _StepFail("builder '%s' cannot run in Vyomi: only the docker builder (docker build / docker push) is executed, "
                        "arbitrary builder containers are not simulated." % name)
    logs.append("Starting Step #%s - \"%s\": docker %s" % (build["steps"].index(step), step.get("id") or name, " ".join(args)))
    if args[0] == "build":
        return _docker_build(store, build, step, args, tree, logs, local)
    if args[0] == "push" and len(args) == 2:
        ref = args[1]
        if ref not in local and "%s:latest" % ref not in local:
            raise _StepFail("An image does not exist locally with the tag: %s" % ref)
        loc = local.get(ref) or local["%s:latest" % ref]
        try:
            digest = push_to_ar((ctx or {}).get("ar_store"), build["projectId"], ref, loc["primary"])
        except ci.CiError as e:
            raise _StepFail(e.message)
        logs.append("The push refers to repository [%s]\n%s: digest: %s" % (ref.rsplit(":", 1)[0], ref.rsplit(":", 1)[-1], digest))
        return {"pushed": [{"name": ref, "digest": digest}]}
    raise _StepFail("docker %s is not supported by Vyomi's builder step (supported: build, push)." % args[0])


def _execute(store, build, ctx):
    logs, local, t0 = build["vyomiLogs"], {}, _now()
    build["status"], build["startTime"] = "WORKING", t0
    try:
        tree, prov = _resolve_source(store, build["projectId"], build["id"], build.get("source"), ctx)
        if prov:
            build["sourceProvenance"] = prov
        logs.append("Fetching source: %d files" % len(tree))
    except ci.CiError as e:
        return _finish(build, "FAILURE", "FETCH_SOURCE_FAILED", e.message)
    results = {"images": [], "buildStepImages": [], "buildStepOutputs": []}
    build["results"] = results
    for st in build["steps"]:
        st["status"] = "QUEUED"
    for st in build["steps"]:
        st["status"], s0 = "WORKING", _now()
        try:
            out = _run_step(store, build, st, tree, logs, local, ctx)
        except _StepFail as e:
            st["status"] = "FAILURE"
            st["timing"] = {"startTime": s0, "endTime": _now()}
            logs.append("ERROR: build step %d \"%s\" failed: %s" % (build["steps"].index(st), st["name"], e))
            return _finish(build, "FAILURE", "USER_BUILD_STEP", "build step %d \"%s\" failed: %s" % (build["steps"].index(st), st["name"], e))
        st["status"] = "SUCCESS"
        st["timing"] = {"startTime": s0, "endTime": _now()}
        for p in out.get("pushed", []):
            results["images"].append({"name": p["name"], "digest": p["digest"], "pushTiming": {"startTime": s0, "endTime": _now()}})
    for ref in build.get("images") or []:
        if any(i["name"] == ref for i in results["images"]):
            continue
        loc = local.get(ref) or local.get("%s:latest" % ref)
        if not loc:
            return _finish(build, "FAILURE", "USER_BUILD_STEP", "failed to push: image %s was not built by any step (error pushing image: An image does not exist locally with the tag: %s)" % (ref, ref))
        try:
            digest = push_to_ar((ctx or {}).get("ar_store"), build["projectId"], ref, loc["primary"])
        except ci.CiError as e:
            return _finish(build, "FAILURE", "USER_BUILD_STEP", "failed to push %s: %s" % (ref, e.message))
        logs.append("PUSH %s -> %s" % (ref, digest))
        results["images"].append({"name": ref, "digest": digest, "pushTiming": {"startTime": _now(), "endTime": _now()}})
    return _finish(build, "SUCCESS")


def _finish(build, status, ftype=None, detail=None):
    build["status"] = status
    build["finishTime"] = _now()
    build["timing"] = {"BUILD": {"startTime": build.get("startTime"), "endTime": build["finishTime"]}}
    if status == "FAILURE":
        build["failureInfo"] = {"type": ftype, "detail": detail}
        build["statusDetail"] = detail
    build["vyomiLogs"].append("%s" % ("DONE" if status == "SUCCESS" else "ERROR"))
    return build


def create_build(store, project, location, cfg, ctx=None, trigger=None, subs_extra=None, provenance=None):
    """Validate, substitute, then run a build to completion. Returns the Build resource (stored)."""
    cfg = copy.deepcopy(cfg)
    _check_config(cfg)
    bid = str(uuid.uuid4())
    sub = dict(subs_extra or {})
    for k, v in (cfg.get("substitutions") or {}).items():
        sub.setdefault(k, str(v))
    values = {"PROJECT_ID": project, "PROJECT_NUMBER": str(abs(hash(project)) % 10**12), "BUILD_ID": bid, "LOCATION": location}
    values.update(sub)
    loose = ((cfg.get("options") or {}).get("substitutionOption") == "ALLOW_LOOSE")
    for k in ("steps", "images"):
        if k in cfg:
            cfg[k] = _sub_all(cfg[k], values, loose)
    now = _now()
    build = {"id": bid, "name": "projects/%s/locations/%s/builds/%s" % (project, location, bid), "projectId": project, "status": "QUEUED",
             "source": cfg.get("source"), "steps": cfg["steps"], "images": cfg.get("images") or [], "createTime": now,
             "timeout": cfg.get("timeout") or "600s", "queueTtl": "3600s", "options": cfg.get("options") or {},
             "substitutions": {k: v for k, v in sub.items() if k.startswith("_")}, "tags": cfg.get("tags") or [],
             "logsBucket": "gs://%s_cloudbuild/logs" % project,
             "logUrl": "https://console.cloud.google.com/cloud-build/builds/%s?project=%s" % (bid, project),
             "serviceAccount": cfg.get("serviceAccount") or "projects/%s/serviceAccounts/%s-compute@developer.gserviceaccount.com" % (project, project),
             "vyomiLogs": []}
    if trigger:
        build["buildTriggerId"] = trigger
    for k in ("source",):
        if not build.get(k):
            build.pop(k, None)
    _x(store, "builds")[build["name"]] = build
    if provenance:
        build["sourceProvenance"] = provenance
    _execute(store, build, ctx)
    return build


# ── triggers ─────────────────────────────────────────────────────────────────────────────────
def _trigger_repo(t):
    if t.get("triggerTemplate"):
        return t["triggerTemplate"].get("repoName") or "default"
    g = t.get("github")
    return "%s--%s" % (g.get("owner"), g.get("name")) if g else None


def _check_trigger(t):
    ev = [k for k in ("triggerTemplate", "github", "sourceToBuild") if t.get(k)]
    if len(ev) != 1:
        raise _bad("Exactly one of triggerTemplate, github or sourceToBuild (manual) must be set on a trigger.")
    for k in ("pubsubConfig", "webhookConfig", "repositoryEventConfig"):
        if t.get(k):
            raise _bad("%s triggers are not simulated by Vyomi." % k)
    if t.get("github"):
        g = t["github"]
        if not g.get("owner") or not g.get("name"):
            raise _bad("github.owner and github.name are required.")
        if g.get("pullRequest"):
            raise _bad("GitHub pull_request triggers are not simulated (push only).")
        p = g.get("push") or {}
        if bool(p.get("branch")) == bool(p.get("tag")):
            raise _bad("github.push must set exactly one of branch or tag.")
    if t.get("triggerTemplate"):
        tt = t["triggerTemplate"]
        if bool(tt.get("branchName")) + bool(tt.get("tagName")) + bool(tt.get("commitSha")) != 1:
            raise _bad("triggerTemplate must set exactly one of branchName, tagName or commitSha.")
    cfgs = [k for k in ("filename", "build", "autodetect", "gitFileSource") if t.get(k)]
    if len(cfgs) != 1:
        raise _bad("Exactly one of filename, build, autodetect or gitFileSource must be set on a trigger.")
    if t.get("autodetect") or t.get("gitFileSource"):
        raise _bad("autodetect / gitFileSource build configs are not simulated; use filename or an inline build.")
    for rx in [t.get("triggerTemplate", {}).get("branchName"), (t.get("github", {}).get("push") or {}).get("branch")]:
        if rx:
            try:
                re.compile(rx)
            except re.error:
                raise _bad("Invalid branch regex '%s'." % rx)
    if t.get("build"):
        _check_config(t["build"])
    for k in (t.get("substitutions") or {}):
        if not re.fullmatch(r"_[A-Z0-9_]+", k):
            raise _bad("User substitution '%s' must start with an underscore and use A-Z, 0-9 and _." % k)


def _hook(store, trig):
    db = ci.get_db(store.ext)
    repo = _trigger_repo(trig)
    ci.remove_hooks(db, repo, "gcp.cloudbuild", "trigger", trig["id"]) if repo in db["repos"] else None
    if repo and not trig.get("disabled") and not trig.get("sourceToBuild"):
        ci.ensure_repo(db, repo)
        ci.add_hook(db, repo, "gcp.cloudbuild", context={"trigger": trig["id"]})


def _config_for(store, trig, tree):
    if trig.get("build"):
        return copy.deepcopy(trig["build"])
    fn = trig.get("filename") or "cloudbuild.yaml"
    if fn not in (tree or {}):
        raise _bad("build config '%s' was not found in the source (failed parsing build config)." % fn)
    text = tree[fn].decode("utf-8", "replace")
    try:
        cfg = json.loads(text) if fn.endswith(".json") else parse_yaml(text)
    except Exception as e:
        raise _bad("failed parsing build config %s: %s" % (fn, e))
    if not isinstance(cfg, dict):
        raise _bad("build config '%s' must be a mapping." % fn)
    return cfg


def run_trigger(store, project, trig, repo, ref_kind, ref, sha, ctx, location="global"):
    db = ci.get_db(store.ext)
    tree = ci.tree(db, repo, sha or ref) or {}
    try:
        cfg = _config_for(store, trig, tree)
    except _E as e:
        b = _fail_build(store, project, location, trig, e.message)
        return b
    cfg["source"] = {"repoSource": {"repoName": repo, "commitSha": sha or ref, "projectId": project}}
    for k in ("tags", "images", "timeout", "options"):
        if trig.get(k) and not cfg.get(k):
            cfg[k] = trig[k]
    subs = {"REPO_NAME": repo, "COMMIT_SHA": sha or "", "SHORT_SHA": (sha or "")[:7], "REVISION_ID": sha or "", "TRIGGER_NAME": trig.get("name", ""),
            "BRANCH_NAME": ref if ref_kind == "branch" else "", "TAG_NAME": ref if ref_kind == "tag" else ""}
    subs.update({k: str(v) for k, v in (trig.get("substitutions") or {}).items()})
    try:
        return create_build(store, project, location, cfg, ctx, trigger=trig["id"], subs_extra=subs)
    except _E as e:
        return _fail_build(store, project, location, trig, e.message)


def _fail_build(store, project, location, trig, msg):
    bid = str(uuid.uuid4())
    b = {"id": bid, "name": "projects/%s/locations/%s/builds/%s" % (project, location, bid), "projectId": project, "status": "QUEUED", "steps": [],
         "createTime": _now(), "buildTriggerId": trig["id"], "vyomiLogs": [], "logUrl": "https://console.cloud.google.com/cloud-build/builds/%s?project=%s" % (bid, project)}
    _finish(b, "FAILURE", "INVALID_CONFIG", msg)
    _x(store, "builds")[b["name"]] = b
    return b


def _on_push(db, ev, hook, ctx, job):
    c = ctx or {}
    store = c.get("cb_store")
    if store is None:
        return
    trig = _x(store, "triggers").get(hook["context"]["trigger"])
    if not trig or trig.get("disabled"):
        return
    tt, gh = trig.get("triggerTemplate") or {}, (trig.get("github") or {}).get("push") or {}
    rx = tt.get("branchName") or gh.get("branch")
    if not rx or not re.search(rx, ev["branch"]):
        return
    changed = None
    try:
        a = ci._git.tree(db, ev["repo"], ev["after"]) or {}
        b = (ci._git.tree(db, ev["repo"], ev["before"]) or {}) if ev.get("before") else {}
        changed = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
    except Exception:
        pass
    if changed is not None:
        inc, ign = trig.get("includedFiles") or [], trig.get("ignoredFiles") or []
        if inc and not any(fnmatch.fnmatch(f, g) for f in changed for g in inc):
            return
        if ign and all(any(fnmatch.fnmatch(f, g) for g in ign) for f in changed):
            return
    ev.setdefault("builds", []).append(run_trigger(store, c.get("project") or trig.get("_project") or "", trig, ev["repo"], "branch", ev["branch"], ev["after"], c)["id"])


ci.register_consumer("gcp.cloudbuild", _on_push)


def _tview(t):
    return _view(t)


def _triggers(store, method, project, rest, query, payload, ctx):
    coll = _x(store, "triggers")
    if rest and rest[0].startswith("triggers:vyomi"):
        verb = rest[0].split(":", 1)[1]
        db = ci.get_db(store.ext)
        c = dict(ctx or {}, cb_store=store, project=project)
        try:
            if verb == "vyomiPush" and method == "POST":
                repo = payload.get("repoName", "")
                if not repo:
                    raise _bad("repoName is required.")
                ci.ensure_repo(db, repo, payload.get("defaultBranch") or "main")
                files = {k: (None if v is None else str(v)) for k, v in (payload.get("files") or {}).items()}
                ev = ci.commit_files(db, repo, payload.get("branch") or "main", files, payload.get("message") or "Update", payload.get("author") or "vyomi", ctx=c)
                return {"repoName": repo, "branch": ev["branch"], "commitSha": ev["after"], "builds": ev.get("builds", [])}
            if verb == "vyomiReconcile" and method == "POST":
                evs = ci.reconcile(db, payload.get("repoName", ""), c)
                return {"events": [{"branch": e["branch"], "commitSha": e["after"], "builds": e.get("builds", [])} for e in evs]}
        except ci.CiError as e:
            raise _E(e.status if isinstance(getattr(e, "status", None), int) else 400, "FAILED_PRECONDITION", e.message)
        raise _E(404, "NOT_FOUND", "Unknown method %s." % rest[0])
    pre = "projects/%s/locations/global/triggers/" % project
    if not rest:
        if method == "GET":
            return _page([_tview(v) for k, v in sorted(coll.items(), key=lambda kv: kv[1]["createTime"]) if v["_project"] == project], query, "triggers")
        if method == "POST":
            _check_trigger(payload)
            if payload.get("name") and any(v.get("name") == payload["name"] and v["_project"] == project for v in coll.values()):
                raise _E(409, "ALREADY_EXISTS", "Trigger with name '%s' already exists." % payload["name"])
            tid = str(uuid.uuid4())
            t = {k: copy.deepcopy(v) for k, v in payload.items() if k not in ("id", "createTime")}
            t.update({"id": tid, "resourceName": pre + tid, "createTime": _now(), "_project": project})
            t.setdefault("name", "trigger-" + tid[:8])
            coll[tid] = t
            _hook(store, t)
            return _tview(t)
        raise _E(405, "UNIMPLEMENTED", "Method not allowed.")
    tid, verb = (rest[0].split(":", 1) + [""])[:2]
    t = coll.get(tid)
    if t is None or t["_project"] != project:
        raise _E(404, "NOT_FOUND", "Trigger '%s' not found." % tid)
    if verb == "run" and method == "POST":
        rs = payload.get("source", payload) or {}
        repo = _trigger_repo(t) or rs.get("repoName") or "default"
        db = ci.get_db(store.ext)
        if repo not in db["repos"]:
            raise _E(404, "NOT_FOUND", "Source repository '%s' not found." % repo)
        kind, ref = ("tag", rs["tagName"]) if rs.get("tagName") else ("branch", rs.get("branchName") or rs.get("commitSha") or db["repos"][repo]["defaultBranch"])
        if ci.tree(db, repo, ref) is None:
            raise _E(404, "NOT_FOUND", "Revision '%s' not found in repository '%s'." % (ref, repo))
        sha = ci._git.head(db, repo, ref) or ref
        b = run_trigger(store, project, t, repo, kind, ref, sha, dict(ctx or {}, cb_store=store, project=project))
        return _op(project, _view(b), "Build")
    if method == "GET" and not verb:
        return _tview(t)
    if method == "PATCH" and not verb:
        new = dict(t)
        new.update({k: v for k, v in payload.items() if k not in ("id", "resourceName", "createTime")})
        _check_trigger(new)
        coll[tid] = new
        _hook(store, new)
        return _tview(new)
    if method == "DELETE" and not verb:
        db = ci.get_db(store.ext)
        repo = _trigger_repo(t)
        if repo in db["repos"]:
            ci.remove_hooks(db, repo, "gcp.cloudbuild", "trigger", tid)
        coll.pop(tid)
        return {}
    raise _E(405, "UNIMPLEMENTED", "Method not allowed.")


# ── builds ───────────────────────────────────────────────────────────────────────────────────
def _builds(store, method, project, loc, rest, query, payload, ctx):
    coll = _x(store, "builds")
    if not rest:
        if method == "GET":
            items = [_view(b) for b in sorted(coll.values(), key=lambda b: b["createTime"], reverse=True) if b["projectId"] == project]
            if query.get("filter"):
                m = re.search(r'status\s*=\s*"?([A-Z_]+)"?', query["filter"])
                if m:
                    items = [b for b in items if b["status"] == m.group(1)]
                m = re.search(r'trigger_id\s*=\s*"?([\w-]+)"?', query["filter"])
                if m:
                    items = [b for b in items if b.get("buildTriggerId") == m.group(1)]
            return _page(items, query, "builds")
        if method == "POST":
            c = dict(ctx or {}, cb_store=store, project=project)
            b = create_build(store, project, loc or "global", payload, c)
            return _op(project, _view(b), "Build")
        raise _E(405, "UNIMPLEMENTED", "Method not allowed.")
    bid, verb = (rest[0].split(":", 1) + [""])[:2]
    b = next((x for x in coll.values() if x["id"] == bid and x["projectId"] == project), None)
    if b is None:
        raise _E(404, "NOT_FOUND", "Build '%s' not found." % bid)
    if method == "GET" and not verb:
        return _view(b)
    if verb == "cancel" and method == "POST":
        if b["status"] not in ("QUEUED", "WORKING"):
            raise _E(400, "FAILED_PRECONDITION", "Build %s is %s and cannot be cancelled." % (bid, b["status"]))
        b["status"] = "CANCELLED"
        return _view(b)
    if verb == "retry" and method == "POST":
        cfg = {k: copy.deepcopy(b[k]) for k in ("steps", "images", "timeout", "options", "tags", "source") if k in b}
        cfg["substitutions"] = dict(b.get("substitutions") or {})
        nb = create_build(store, project, loc or "global", cfg, dict(ctx or {}, cb_store=store, project=project), trigger=b.get("buildTriggerId"))
        return _op(project, _view(nb), "Build")
    raise _E(405, "UNIMPLEMENTED", "Method not allowed.")


_PATH = re.compile(r"^v1/projects/([^/]+)/(?:locations/([^/]+)/)?(builds|triggers)(?:/(.+))?$")


def dispatch(store, method, path, query=None, headers=None, body=b"", ar_store=None, gcs_read=None, run_deploy=None):
    query, method = dict(query or {}), method.upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        return Resp(400, {"error": {"code": 400, "message": "Invalid JSON payload received.", "status": "INVALID_ARGUMENT"}})
    p = path.split("?", 1)[0].strip("/")
    m = _PATH.match(p)
    try:
        if not m:
            m2 = re.match(r"^v1/projects/([^/]+)/(triggers:vyomi\w+)$", p)
            if not m2:
                raise _E(404, "NOT_FOUND", "Unknown path: %s" % path)
            project, kind, loc, tail = m2.group(1), "triggers", None, m2.group(2)
            rest = [tail]
        else:
            project, loc, kind, tail = m.group(1), m.group(2), m.group(3), m.group(4)
            rest = tail.split("/") if tail else []
        ctx = {"ar_store": ar_store, "gcs_read": gcs_read, "run_deploy": run_deploy}
        if kind == "triggers":
            if loc and loc != "global":
                raise _E(404, "NOT_FOUND", "Regional triggers are not routed by Vyomi (use the global trigger path).")
            if rest and ":" in rest[0] and not rest[0].startswith("triggers:") and rest[0].split(":")[1] in ("vyomiPush", "vyomiReconcile"):
                rest = ["triggers:" + rest[0].split(":", 1)[1]]
            out = _triggers(store, method, project, rest, query, payload, ctx)
        else:
            out = _builds(store, method, project, loc, rest, query, payload, ctx)
        if method != "GET" and hasattr(store, "persist"):
            try:
                store.persist()
            except Exception:
                pass
        return Resp(200, out)
    except _E as e:
        return Resp(e.status, {"error": {"code": e.status, "message": e.message, "status": e.gcp_status}})
    except ci.CiError as e:
        return Resp(e.status if isinstance(getattr(e, "status", None), int) else 400, {"error": {"code": 400, "message": e.message, "status": "FAILED_PRECONDITION"}})
