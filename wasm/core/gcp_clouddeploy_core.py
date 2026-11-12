# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""Cloud Deploy API v1 (clouddeploy.googleapis.com) — delivery pipelines, targets, releases and rollouts as a real state machine.

Substrate-independent (stdlib only). State: store.ext["clouddeploy_*"] on the Monitoring store (persisted with it).

  /v1/projects/{p}/locations/{l}/deliveryPipelines[/{d}]                  create/get/list/patch/delete(force)
  /v1/projects/{p}/locations/{l}/deliveryPipelines/{d}:rollbackTarget
  /v1/projects/{p}/locations/{l}/targets[/{t}]                            gke | run targets, requireApproval
  .../deliveryPipelines/{d}/releases[/{r}]                                create (renders), get, list, :abandon
  .../releases/{r}/rollouts[/{ro}]                                        create, get, list,
                                  :approve  :advance  :cancel  :retryJob  :ignoreJob
  .../rollouts/{ro}/jobRuns[/{jr}]                                        get, list

Behaviour (not a stub):
  * a release renders (renderState, per-target targetRenders) and automatically creates the first stage's rollout; a target
    with requireApproval parks it in PENDING_APPROVAL until `:approve` (approved=false -> APPROVAL_REJECTED);
  * rollouts have phases and jobs. standard strategy = one `stable` phase (deploy [+ verify]); canary strategy =
    `canary-N` phases then `stable`, each canary phase pausing the rollout (IN_PROGRESS, next phase PENDING) until `:advance`;
  * the deploy job REALLY deploys into the simulator: Cloud Run target -> the service's image is updated (new revision; canary
    phases split traffic between the new and previous revision), GKE target -> the Deployment in the cluster's data plane is
    replaced (canary phases run a `<name>-canary` Deployment). A missing cluster / bad image makes the deploy job and the
    rollout FAILED with a failureCause; `:retryJob` / `:ignoreJob` / `:cancel` follow;
  * `:rollbackTarget` creates a rollout of the previous successful release on the target (rollbackOfRollout /
    rolledBackByRollouts are linked).

Which service / Deployment a pipeline deploys is taken from deployParameters (release > target > pipeline): `service` (Cloud Run,
default = pipeline id), `deployment` + `namespace` + `container` (GKE, default = pipeline id / default / pipeline id).

Honest limits: Skaffold is not run (a release's manifests are not rendered from skaffold.yaml; the deployed workload is built from the
release's buildArtifacts image), verify jobs do not execute the verify container (they succeed unless deployParameter
`vyomi-verify=fail`), predeploy/postdeploy hooks, multiTarget, custom targets, Anthos targets, automations, deploy policies and
custom target types are not simulated, LROs complete inline.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

try:
    from core import gcp_run_core as _run
    from core import gcp_gke_dataplane_core as _dp
except ImportError:  # pragma: no cover - Pyodide flat layout
    import gcp_run_core as _run  # type: ignore
    import gcp_gke_dataplane_core as _dp  # type: ignore

ID_RE = re.compile(r"^[a-z]([a-z0-9-]{0,61}[a-z0-9])?$")
REL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
CLUSTER_RE = re.compile(r"^projects/([^/]+)/locations/([^/]+)/clusters/([^/]+)$")
IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._:/@-]*$")
ROLLOUT_STATES = ("SUCCEEDED", "FAILED", "IN_PROGRESS", "PENDING_APPROVAL", "APPROVAL_REJECTED", "PENDING", "PENDING_RELEASE", "CANCELLING", "CANCELLED", "HALTED")


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


def _pre(m):
    return _E(400, "FAILED_PRECONDITION", m)


def _nf(kind, name):
    return _E(404, "NOT_FOUND", "Resource '%s' not found." % name) if kind is None else _E(404, "NOT_FOUND", "%s '%s' not found." % (kind, name))


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _uid():
    return str(uuid.uuid4())


def _etag(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:20]


def _x(store, coll):
    if getattr(store, "ext", None) is None:
        store.ext = {}
    return store.ext.setdefault("clouddeploy_" + coll, {})


def _view(o):
    out = {k: copy.deepcopy(v) for k, v in o.items() if not k.startswith("_")}
    if isinstance(out.get("phases"), list):
        out["phases"] = [{k: v for k, v in ph.items() if not k.startswith("_")} for ph in out["phases"]]
    return out


def _lro(project, loc, kind, resource, verb="create"):
    return {"name": "projects/%s/locations/%s/operations/operation-%s" % (project, loc, uuid.uuid4().hex[:16]), "done": True,
            "metadata": {"@type": "type.googleapis.com/google.cloud.deploy.v1.OperationMetadata", "verb": verb, "createTime": _now(),
                         "endTime": _now(), "target": resource.get("name", ""), "apiVersion": "v1", "requestedCancellation": False},
            "response": dict(resource, **{"@type": "type.googleapis.com/google.cloud.deploy.v1.%s" % kind})}


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


def _map(m, what):
    if m is None:
        return {}
    if not isinstance(m, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in m.items()):
        raise _bad("%s must be a map of strings." % what)
    return dict(m)


def _id(kind, v, rx=ID_RE):
    if not v or not rx.match(v):
        raise _bad("Invalid %s ID '%s': must match %s." % (kind, v, rx.pattern))


# ── targets ───────────────────────────────────────────────────────────────────
def _check_target(p):
    kinds = [k for k in ("gke", "run", "anthosCluster", "multiTarget", "customTarget") if p.get(k)]
    if len(kinds) != 1:
        raise _bad("Exactly one of gke, run, anthosCluster, multiTarget or customTarget must be set on a target.")
    if kinds[0] in ("anthosCluster", "multiTarget", "customTarget"):
        raise _bad("Target type '%s' is not simulated by Vyomi (supported: gke, run)." % kinds[0])
    if kinds[0] == "gke":
        c = (p["gke"] or {}).get("cluster", "")
        if not CLUSTER_RE.match(c):
            raise _bad("gke.cluster must be of the form projects/{project}/locations/{location}/clusters/{cluster}.")
    else:
        loc = (p["run"] or {}).get("location", "")
        if not re.match(r"^projects/[^/]+/locations/[^/]+$", loc):
            raise _bad("run.location must be of the form projects/{project}/locations/{location}.")
    if p.get("requireApproval") is not None and not isinstance(p["requireApproval"], bool):
        raise _bad("requireApproval must be a boolean.")
    for ec in p.get("executionConfigs") or []:
        for u in ec.get("usages") or []:
            if u not in ("RENDER", "DEPLOY", "VERIFY", "PREDEPLOY", "POSTDEPLOY"):
                raise _bad("executionConfigs.usages: unknown usage '%s'." % u)
    return kinds[0]


_TARGET_FIELDS = ("description", "annotations", "labels", "requireApproval", "gke", "run", "executionConfigs", "deployParameters", "anthosCluster", "multiTarget", "customTarget")


def _targets(store, method, project, loc, rest, query, payload):
    coll = _x(store, "targets")
    pre = "projects/%s/locations/%s/targets/" % (project, loc)
    if not rest:
        if method == "GET":
            return _page([_view(v) for k, v in sorted(coll.items()) if k.startswith(pre)], query, "targets")
        if method == "POST":
            tid = query.get("targetId", "")
            _id("target", tid)
            if pre + tid in coll:
                raise _E(409, "ALREADY_EXISTS", "Resource 'projects/%s/locations/%s/targets/%s' already exists." % (project, loc, tid))
            _check_target(payload)
            now = _now()
            t = {"name": pre + tid, "targetId": tid, "uid": _uid(), "description": str(payload.get("description", "")),
                 "annotations": _map(payload.get("annotations"), "annotations"), "labels": _map(payload.get("labels"), "labels"),
                 "requireApproval": bool(payload.get("requireApproval", False)), "createTime": now, "updateTime": now,
                 "executionConfigs": payload.get("executionConfigs") or [{"usages": ["RENDER", "DEPLOY"], "executionTimeout": "3600s"}],
                 "deployParameters": _map(payload.get("deployParameters"), "deployParameters")}
            for k in ("gke", "run"):
                if payload.get(k):
                    t[k] = payload[k]
            t["etag"] = _etag(t)
            if query.get("validateOnly") != "true":
                coll[pre + tid] = t
            return _lro(project, loc, "Target", _view(t))
        raise _E(405, "UNIMPLEMENTED", "Method not allowed.")
    tid = rest[0]
    verb = ""
    if ":" in tid:
        tid, verb = tid.split(":", 1)
    name = pre + tid
    t = coll.get(name)
    if t is None:
        raise _nf("Target", name)
    if method == "GET" and not verb:
        return _view(t)
    if method == "PATCH":
        mask = [m.split(".", 1)[0] for m in (query.get("updateMask") or "").split(",") if m] or [k for k in payload if k in _TARGET_FIELDS]
        new = copy.deepcopy(t)
        for f in mask:
            if f not in _TARGET_FIELDS:
                raise _bad("Field '%s' is not updatable." % f)
            if f in payload:
                new[f] = payload[f]
            elif f in ("labels", "annotations", "deployParameters"):
                new[f] = {}
        merged = {k: new.get(k) for k in ("gke", "run")}
        _check_target(merged) if (merged["gke"] or merged["run"]) else None
        if merged["gke"] and merged["run"]:
            raise _bad("Exactly one of gke or run must be set on a target.")
        new["updateTime"] = _now()
        new["etag"] = _etag(new)
        if query.get("validateOnly") != "true":
            coll[name] = new
        return _lro(project, loc, "Target", _view(new), "update")
    if method == "DELETE":
        for pn, pl in _x(store, "pipelines").items():
            if any(_target_name(pn, s.get("targetId")) == name for s in _stages(pl)):
                raise _pre("Target '%s' is referenced by delivery pipeline '%s' and cannot be deleted." % (name, pn))
        coll.pop(name)
        return _lro(project, loc, "Empty", {}, "delete")
    raise _E(405, "UNIMPLEMENTED", "Method not allowed.")


def _target_name(pipeline_name, tid):
    m = re.match(r"^(projects/[^/]+/locations/[^/]+)/", pipeline_name)
    return "%s/targets/%s" % (m.group(1), tid)


# ── delivery pipelines ────────────────────────────────────────────────────────
def _stages(pl):
    return ((pl.get("serialPipeline") or {}).get("stages")) or []


def _check_pipeline(p):
    sp = p.get("serialPipeline")
    if not isinstance(sp, dict) or not sp.get("stages"):
        raise _bad("serialPipeline.stages must contain at least one stage.")
    seen = set()
    for i, s in enumerate(sp["stages"]):
        tid = (s or {}).get("targetId", "")
        if not tid:
            raise _bad("serialPipeline.stages[%d].targetId is required." % i)
        if tid in seen:
            raise _bad("Target '%s' appears in more than one stage." % tid)
        seen.add(tid)
        st = s.get("strategy") or {}
        if st.get("standard") is not None and st.get("canary") is not None:
            raise _bad("serialPipeline.stages[%d].strategy: exactly one of standard or canary may be set." % i)
        std = st.get("standard")
        if std:
            for hook in ("predeploy", "postdeploy"):
                if std.get(hook):
                    raise _bad("strategy.standard.%s hooks are not simulated by Vyomi." % hook)
        can = st.get("canary")
        if can:
            if can.get("customCanaryDeployment"):
                raise _bad("customCanaryDeployment is not simulated by Vyomi (use canaryDeployment.percentages).")
            cd = can.get("canaryDeployment") or {}
            pcts = cd.get("percentages") or []
            if not pcts or any(not isinstance(x, int) or not 0 <= x < 100 for x in pcts) or pcts != sorted(set(pcts)):
                raise _bad("canary.canaryDeployment.percentages must be a strictly increasing list of integers in [0, 100).")


def _conditions(store, name, pl):
    tcoll = _x(store, "targets")
    missing = [s["targetId"] for s in _stages(pl) if _target_name(name, s["targetId"]) not in tcoll]
    now = _now()
    return {"pipelineReadyCondition": {"status": not missing, "updateTime": now},
            "targetsPresentCondition": {"status": not missing, "missingTargets": [_target_name(name, m) for m in missing], "updateTime": now},
            "targetsTypeCondition": {"status": True}}


def _pview(store, name, pl):
    v = _view(pl)
    v["condition"] = _conditions(store, name, pl)
    return v


def _pipelines(store, method, project, loc, rest, query, payload):
    coll = _x(store, "pipelines")
    pre = "projects/%s/locations/%s/deliveryPipelines/" % (project, loc)
    if not rest:
        if method == "GET":
            return _page([_pview(store, k, v) for k, v in sorted(coll.items()) if k.startswith(pre)], query, "deliveryPipelines")
        if method == "POST":
            did = query.get("deliveryPipelineId", "")
            _id("delivery pipeline", did)
            if pre + did in coll:
                raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % (pre + did))
            _check_pipeline(payload)
            now = _now()
            pl = {"name": pre + did, "uid": _uid(), "description": str(payload.get("description", "")),
                  "annotations": _map(payload.get("annotations"), "annotations"), "labels": _map(payload.get("labels"), "labels"),
                  "serialPipeline": payload["serialPipeline"], "suspended": bool(payload.get("suspended", False)),
                  "deployParameters": _map(payload.get("deployParameters"), "deployParameters") if "deployParameters" in payload else {},
                  "createTime": now, "updateTime": now}
            pl["etag"] = _etag(pl)
            if query.get("validateOnly") != "true":
                coll[pre + did] = pl
            return _lro(project, loc, "DeliveryPipeline", _pview(store, pre + did, pl))
        raise _E(405, "UNIMPLEMENTED", "Method not allowed.")
    did = rest[0]
    verb = ""
    if ":" in did:
        did, verb = did.split(":", 1)
    name = pre + did
    pl = coll.get(name)
    if pl is None:
        raise _nf("DeliveryPipeline", name)
    if len(rest) > 1:
        if rest[1] == "releases":
            return _releases(store, method, project, loc, name, rest[2:], query, payload)
        raise _nf(None, "/".join(rest))
    if verb == "rollbackTarget" and method == "POST":
        return _rollback(store, project, loc, name, payload)
    if method == "GET":
        return _pview(store, name, pl)
    if method == "PATCH":
        fields = ("description", "annotations", "labels", "serialPipeline", "suspended", "deployParameters")
        mask = [m.split(".", 1)[0] for m in (query.get("updateMask") or "").split(",") if m] or [k for k in payload if k in fields]
        new = copy.deepcopy(pl)
        for f in mask:
            if f not in fields:
                raise _bad("Field '%s' is not updatable." % f)
            if f in payload:
                new[f] = payload[f]
        if "serialPipeline" in mask:
            _check_pipeline(new)
        new["updateTime"] = _now()
        new["etag"] = _etag(new)
        if query.get("validateOnly") != "true":
            coll[name] = new
        return _lro(project, loc, "DeliveryPipeline", _pview(store, name, new), "update")
    if method == "DELETE":
        has = [r for r in _x(store, "releases") if r.startswith(name + "/")]
        if has and query.get("force") != "true":
            raise _pre("Delivery pipeline '%s' has child releases; set force=true to delete it with them." % name)
        for tbl in ("releases", "rollouts", "jobruns"):
            c = _x(store, tbl)
            for k in [k for k in c if k.startswith(name + "/")]:
                c.pop(k)
        coll.pop(name)
        return _lro(project, loc, "Empty", {}, "delete")
    raise _E(405, "UNIMPLEMENTED", "Method not allowed.")


# ── releases ──────────────────────────────────────────────────────────────────
def _param(store, pipeline, target, release, key, default):
    for src in (release, target, pipeline):
        v = ((src or {}).get("deployParameters") or {}).get(key)
        if v:
            return v
    return default


def _releases(store, method, project, loc, pname, rest, query, payload):
    coll = _x(store, "releases")
    pre = pname + "/releases/"
    if not rest:
        if method == "GET":
            return _page([_view(v) for k, v in sorted(coll.items()) if k.startswith(pre)], query, "releases")
        if method == "POST":
            rid = query.get("releaseId", "")
            _id("release", rid, REL_RE)
            if pre + rid in coll:
                raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % (pre + rid))
            return _create_release(store, project, loc, pname, rid, query, payload)
        raise _E(405, "UNIMPLEMENTED", "Method not allowed.")
    rid = rest[0]
    verb = ""
    if ":" in rid:
        rid, verb = rid.split(":", 1)
    name = pre + rid
    rel = coll.get(name)
    if rel is None:
        raise _nf("Release", name)
    if len(rest) > 1:
        if rest[1] == "rollouts":
            return _rollouts(store, method, project, loc, pname, rel, rest[2:], query, payload)
        raise _nf(None, "/".join(rest))
    if verb == "abandon" and method == "POST":
        if rel.get("abandoned"):
            raise _pre("Release '%s' is already abandoned." % name)
        rel["abandoned"] = True
        return {}
    if method == "GET":
        return _view(rel)
    raise _E(405, "UNIMPLEMENTED", "Method not allowed.")


def _create_release(store, project, loc, pname, rid, query, payload):
    pl = _x(store, "pipelines")[pname]
    cond = _conditions(store, pname, pl)
    if not cond["targetsPresentCondition"]["status"]:
        raise _pre("Delivery pipeline '%s' has missing targets: %s." % (pname, ", ".join(cond["targetsPresentCondition"]["missingTargets"])))
    if pl.get("suspended"):
        raise _pre("Delivery pipeline '%s' is suspended; releases cannot be created." % pname)
    arts = payload.get("buildArtifacts") or []
    uri = payload.get("skaffoldConfigUri", "")
    if not arts and not uri:
        raise _bad("Either skaffoldConfigUri or buildArtifacts must be set on a release.")
    if uri and not re.match(r"^(gs|https?)://", uri):
        raise _bad("skaffoldConfigUri must be a gs:// or https:// URI.")
    for i, a in enumerate(arts):
        img = (a or {}).get("image", "")
        tag = (a or {}).get("tag", "")
        if not img or not IMAGE_RE.match(img.lower()):
            raise _bad("buildArtifacts[%d].image is not a valid image name." % i)
        if not tag:
            raise _bad("buildArtifacts[%d].tag is required (the fully qualified image reference to deploy)." % i)
    now = _now()
    renders, snaps = {}, []
    for s in _stages(pl):
        tn = _target_name(pname, s["targetId"])
        snaps.append(_view(_x(store, "targets")[tn]))
        renders[s["targetId"]] = {"renderingBuild": "projects/%s/locations/%s/builds/render-%s" % (project, loc, uuid.uuid4().hex[:12]),
                                  "renderingState": "SUCCEEDED"}
    rel = {"name": pname + "/releases/" + rid, "uid": _uid(), "description": str(payload.get("description", "")),
           "annotations": _map(payload.get("annotations"), "annotations"), "labels": _map(payload.get("labels"), "labels"),
           "abandoned": False, "createTime": now, "renderStartTime": now, "renderEndTime": _now(),
           "skaffoldConfigUri": uri, "skaffoldConfigPath": payload.get("skaffoldConfigPath", "skaffold.yaml"), "buildArtifacts": arts,
           "deliveryPipelineSnapshot": _pview(store, pname, pl), "targetSnapshots": snaps, "renderState": "SUCCEEDED",
           "targetRenders": renders, "skaffoldVersion": "2.13",
           "condition": {"releaseReadyCondition": {"status": True},
                         "skaffoldSupportedCondition": {"status": True, "skaffoldSupportState": "SKAFFOLD_SUPPORT_STATE_SUPPORTED",
                                                        "maintenanceModeTime": "2027-01-01T00:00:00Z", "supportExpirationTime": "2027-07-01T00:00:00Z"}},
           "deployParameters": _map(payload.get("deployParameters"), "deployParameters") if "deployParameters" in payload else {}}
    rel["etag"] = _etag(rel)
    if query.get("validateOnly") == "true":
        return _lro(project, loc, "Release", _view(rel))
    _x(store, "releases")[rel["name"]] = rel
    first = _stages(pl)[0]["targetId"]
    _new_rollout(store, project, loc, pname, rel, first, None, {})
    return _lro(project, loc, "Release", _view(rel))


# ── rollouts ──────────────────────────────────────────────────────────────────
def _phases_for(stage):
    st = (stage.get("strategy") or {})
    can = st.get("canary")
    verify = bool(((can or {}).get("canaryDeployment") or {}).get("verify")) if can else bool((st.get("standard") or {}).get("verify"))
    phases = []
    if can:
        for pct in (can.get("canaryDeployment") or {}).get("percentages") or []:
            phases.append(("canary-%d" % pct, pct, verify))
    phases.append(("stable", 100, verify))
    out = []
    for pid, pct, v in phases:
        jobs = {"deployJob": {"id": "deploy", "state": "PENDING"}}
        if v:
            jobs["verifyJob"] = {"id": "verify", "state": "PENDING"}
        out.append({"id": pid, "state": "PENDING", "_pct": pct, "deploymentJobs": jobs})
    return out


def _new_rollout(store, project, loc, pname, rel, tid, rid, extra):
    pl = _x(store, "pipelines")[pname]
    stage = next((s for s in _stages(pl) if s["targetId"] == tid), None)
    if stage is None:
        raise _bad("Target '%s' is not a stage of delivery pipeline '%s'." % (tid, pname))
    tn = _target_name(pname, tid)
    target = _x(store, "targets").get(tn)
    if target is None:
        raise _pre("Target '%s' does not exist." % tn)
    if rel.get("abandoned"):
        raise _pre("Release '%s' is abandoned; rollouts cannot be created." % rel["name"])
    if rel.get("renderState") != "SUCCEEDED":
        raise _pre("Release '%s' has not rendered successfully (renderState=%s)." % (rel["name"], rel.get("renderState")))
    coll = _x(store, "rollouts")
    if not rid:
        n = 1 + sum(1 for k, v in coll.items() if k.startswith(rel["name"] + "/rollouts/") and v.get("targetId") == tid)
        rid = "%s-to-%s-%04d" % (rel["name"].rsplit("/", 1)[-1], tid, n)
        while rel["name"] + "/rollouts/" + rid in coll:
            n += 1
            rid = "%s-to-%s-%04d" % (rel["name"].rsplit("/", 1)[-1], tid, n)
    name = rel["name"] + "/rollouts/" + rid
    if name in coll:
        raise _E(409, "ALREADY_EXISTS", "Resource '%s' already exists." % name)
    now = _now()
    ro = {"name": name, "uid": _uid(), "description": "", "annotations": {}, "labels": {}, "createTime": now, "targetId": tid,
          "approvalState": "APPROVAL_STATE_UNSPECIFIED", "state": "PENDING", "failureReason": "", "deployingBuild": "",
          "phases": _phases_for(stage), "metadata": {}, "controllerRollout": "", "rollbackOfRollout": extra.get("rollbackOfRollout", ""),
          "rolledBackByRollouts": [], "deployFailureCause": "FAILURE_CAUSE_UNSPECIFIED", "enqueueTime": now}
    coll[name] = ro
    if target.get("requireApproval"):
        ro["approvalState"] = "NEEDS_APPROVAL"
        ro["state"] = "PENDING_APPROVAL"
    else:
        ro["approvalState"] = "DOES_NOT_NEED_APPROVAL"
        _start(store, pname, rel, target, ro)
    ro["etag"] = _etag(ro)
    return ro


def _jobrun(store, ro, phase, job, state, **kw):
    coll = _x(store, "jobruns")
    jid = "jr-%s" % uuid.uuid4().hex[:12]
    name = ro["name"] + "/jobRuns/" + jid
    now = _now()
    jr = {"name": name, "uid": _uid(), "phaseId": phase["id"], "jobId": job["id"], "state": state, "createTime": now, "startTime": now, "endTime": now}
    jr.update(kw)
    coll[name] = jr
    job["jobRun"] = name
    return jr


def _start(store, pname, rel, target, ro):
    ro["state"] = "IN_PROGRESS"
    ro["deployStartTime"] = _now()
    _run_phase(store, pname, rel, target, ro, ro["phases"][0])


def _deploy(store, pname, rel, target, ro, phase):
    """Really deploy the release's image to the target; returns the job-run detail or raises _Fail."""
    pl = _x(store, "pipelines")[pname]
    arts = rel.get("buildArtifacts") or []
    if not arts:
        raise _Fail("MISSING_RESOURCES_PERMISSION", "The release has no buildArtifacts; Vyomi deploys the artifact image (Skaffold manifests are not rendered).")
    image = arts[0]["tag"]
    pct = phase.get("_pct", 100)
    canary = phase["id"] != "stable"
    if target.get("run"):
        return _deploy_run(store, pl, rel, target, image, pct, canary)
    return _deploy_gke(store, pl, rel, target, image, pct, canary, pname)


class _Fail(Exception):
    def __init__(self, cause, msg):
        super().__init__(msg)
        self.cause, self.msg = cause, msg


def _deploy_run(store, pl, rel, target, image, pct, canary):
    rs = getattr(store, "run_store", None)
    if rs is None:
        raise _Fail("EXECUTION_FAILED", "Cloud Run is not available in this runtime.")
    m = re.match(r"^projects/([^/]+)/locations/([^/]+)$", target["run"]["location"])
    project, location = m.group(1), m.group(2)
    if location not in _run.REGIONS:
        raise _Fail("EXECUTION_FAILED", "Cloud Run location '%s' is not a valid region." % location)
    sid = _param(store, pl, target, rel, "service", pl["name"].rsplit("/", 1)[-1])
    full = _run.service_name(project, location, sid)
    svc = rs.services.get(full)
    prev = (svc or {}).get("latestReadyRevision", "")
    try:
        if svc is None:
            _run.create_service(rs, project, location, {"serviceId": sid},
                                {"template": {"containers": [{"image": image}]}, "labels": {"managed-by": "cloud-deploy"}})
        else:
            tpl = copy.deepcopy(svc["template"])
            tpl.pop("revision", None)
            tpl["containers"] = [dict(c) for c in tpl.get("containers") or [{}]]
            tpl["containers"][0]["image"] = image
            _run.update_service(rs, project, location, sid, {"updateMask": "template"}, {"template": tpl})
        svc = rs.services[full]
        new = svc["latestReadyRevision"]
        if canary and prev and prev != new:
            traffic = [{"type": _run.REVISION, "revision": new.rsplit("/", 1)[-1], "percent": pct},
                       {"type": _run.REVISION, "revision": prev.rsplit("/", 1)[-1], "percent": 100 - pct}]
            traffic = [t for t in traffic if t["percent"] > 0]
            _run.update_service(rs, project, location, sid, {"updateMask": "traffic"}, {"traffic": traffic})
        elif not canary:
            _run.update_service(rs, project, location, sid, {"updateMask": "traffic"}, {"traffic": [{"type": _run.LATEST, "percent": 100}]})
        svc = rs.services[full]
    except _run._E as e:
        raise _Fail("EXECUTION_FAILED", str(getattr(e, "message", None) or e.args))
    return {"cloudRun": {"service": full, "revision": svc["latestReadyRevision"], "serviceUrls": [svc.get("uri", "")], "image": image, "trafficPercent": pct}}


def _deploy_gke(store, pl, rel, target, image, pct, canary, pname):
    gs = getattr(store, "gke_store", None)
    if gs is None:
        raise _Fail("EXECUTION_FAILED", "GKE is not available in this runtime.")
    cname = target["gke"]["cluster"]
    cl = gs.clusters.get(cname)
    if cl is None:
        raise _Fail("EXECUTION_FAILED", "GKE cluster '%s' was not found." % cname)
    if str(cl.get("status", "RUNNING")) not in ("RUNNING", "RECONCILING"):
        raise _Fail("EXECUTION_FAILED", "GKE cluster '%s' is not RUNNING (status=%s)." % (cname, cl.get("status")))
    cs = _dp.ensure_cluster(gs.k8s, cname)
    ns = _param(store, pl, target, rel, "namespace", "default")
    base = _param(store, pl, target, rel, "deployment", pl["name"].rsplit("/", 1)[-1])
    cont = _param(store, pl, target, rel, "container", base)
    if ns not in cs["namespaces"]:
        raise _Fail("EXECUTION_FAILED", "namespace '%s' not found in cluster '%s'." % (ns, cname))
    stable_key = "%s/%s" % (ns, base)
    cur = cs["deployments"].get(stable_key)
    replicas = int(((cur or {}).get("spec") or {}).get("replicas", 1)) or 1

    def put(name, reps):
        key = "%s/%s" % (ns, name)
        if key in cs["deployments"]:
            _dp.delete_workload(cs, "deployments", ns, name)
        body = {"metadata": {"name": name, "labels": {"app": base, "managed-by": "cloud-deploy"}},
                "spec": {"replicas": reps, "template": {"metadata": {"labels": {"app": base}},
                                                        "spec": {"containers": [{"name": cont, "image": image}]}}}}
        try:
            _dp.create_workload(cs, "deployments", ns, body)
        except _dp._KErr as e:
            raise _Fail("EXECUTION_FAILED", str(e))

    if canary:
        put(base + "-canary", max(1, -(-replicas * pct // 100)))
        if cur is None:   # first deploy: nothing to canary against
            put(base, replicas)
    else:
        put(base, replicas)
        if "%s/%s-canary" % (ns, base) in cs["deployments"]:
            _dp.delete_workload(cs, "deployments", ns, base + "-canary")
    return {"gke": {"cluster": cname, "namespace": ns, "deployment": base, "image": image, "canary": canary}}


def _run_phase(store, pname, rel, target, ro, phase):
    """Run one phase's jobs; maintains phase/rollout state. Returns True if the phase succeeded."""
    phase["state"] = "IN_PROGRESS"
    phase["startTime"] = _now()
    for key in ("deployJob", "verifyJob"):
        job = phase["deploymentJobs"].get(key)
        if not job or job["state"] in ("SUCCEEDED", "SKIPPED"):
            continue
        job["state"] = "IN_PROGRESS"
        pl = _x(store, "pipelines")[pname]
        try:
            if key == "deployJob":
                detail = _deploy(store, pname, rel, target, ro, phase)
                _jobrun(store, ro, phase, job, "SUCCEEDED", deployJobRun={"build": "", "metadata": detail})
            else:
                if _param(store, pl, target, rel, "vyomi-verify", "pass") == "fail":
                    raise _Fail("EXECUTION_FAILED", "verify container exited with a non-zero status (vyomi-verify=fail).")
                _jobrun(store, ro, phase, job, "SUCCEEDED", verifyJobRun={"build": "", "artifactUri": "", "eventLogPath": ""})
            job["state"] = "SUCCEEDED"
        except _Fail as f:
            job["state"] = "FAILED"
            phase["state"] = "FAILED"
            ro["state"] = "FAILED"
            ro["failureReason"] = "Cloud Deploy job %s failed: %s" % (job["id"], f.msg)
            ro["deployFailureCause"] = f.cause
            jr = _jobrun(store, ro, phase, job, "FAILED")
            jr["deployJobRun" if key == "deployJob" else "verifyJobRun"] = {"failureCause": f.cause, "failureMessage": f.msg}
            return False
    phase["state"] = "SUCCEEDED"
    phase["endTime"] = _now()
    _after_phase(ro)
    return True


def _after_phase(ro):
    nxt = next((p for p in ro["phases"] if p["state"] == "PENDING"), None)
    if nxt is None:
        ro["state"] = "SUCCEEDED"
        ro["deployEndTime"] = _now()
        ro["failureReason"] = ""
        ro["deployFailureCause"] = "FAILURE_CAUSE_UNSPECIFIED"
    else:
        ro["state"] = "IN_PROGRESS"   # canary: paused until :advance


def _ctx_of(store, ro):
    pname = ro["name"].split("/releases/")[0]
    rel = _x(store, "releases")[ro["name"].split("/rollouts/")[0]]
    target = _x(store, "targets")[_target_name(pname, ro["targetId"])]
    return pname, rel, target


def _rollouts(store, method, project, loc, pname, rel, rest, query, payload):
    coll = _x(store, "rollouts")
    pre = rel["name"] + "/rollouts/"
    if not rest:
        if method == "GET":
            return _page([_view(v) for k, v in sorted(coll.items()) if k.startswith(pre)], query, "rollouts")
        if method == "POST":
            rid = query.get("rolloutId", "")
            _id("rollout", rid, REL_RE)
            tid = payload.get("targetId", "")
            if not tid:
                raise _bad("targetId is required.")
            ro = _new_rollout(store, project, loc, pname, rel, tid, rid, {})
            return _lro(project, loc, "Rollout", _view(ro))
        raise _E(405, "UNIMPLEMENTED", "Method not allowed.")
    rid = rest[0]
    verb = ""
    if ":" in rid:
        rid, verb = rid.split(":", 1)
    name = pre + rid
    ro = coll.get(name)
    if ro is None:
        raise _nf("Rollout", name)
    if len(rest) > 1:
        if rest[1] == "jobRuns":
            return _jobruns(store, method, name, rest[2:], query)
        raise _nf(None, "/".join(rest))
    if method == "GET" and not verb:
        return _view(ro)
    if method == "POST" and verb:
        return _action(store, ro, verb, payload)
    raise _E(405, "UNIMPLEMENTED", "Method not allowed.")


def _action(store, ro, verb, payload):
    pname, rel, target = _ctx_of(store, ro)
    st = ro["state"]
    if verb == "approve":
        if st != "PENDING_APPROVAL":
            raise _pre("Rollout '%s' is not pending approval (state=%s)." % (ro["name"], st))
        if "approved" not in payload or not isinstance(payload["approved"], bool):
            raise _bad("approved (bool) is required.")
        ro["approveTime"] = _now()
        if payload["approved"]:
            ro["approvalState"] = "APPROVED"
            _start(store, pname, rel, target, ro)
        else:
            ro["approvalState"] = "REJECTED"
            ro["state"] = "APPROVAL_REJECTED"
        return {}
    if verb == "advance":
        if st != "IN_PROGRESS":
            raise _pre("Rollout '%s' cannot be advanced in state %s." % (ro["name"], st))
        pid = payload.get("phaseId", "")
        ph = next((p for p in ro["phases"] if p["id"] == pid), None)
        if ph is None:
            raise _bad("Phase '%s' does not exist on rollout '%s'." % (pid, ro["name"]))
        if ph["state"] != "PENDING":
            raise _pre("Phase '%s' is %s; only a PENDING phase can be advanced." % (pid, ph["state"]))
        if any(p["state"] == "IN_PROGRESS" for p in ro["phases"]):
            raise _pre("Another phase is in progress.")
        if ph is not next(p for p in ro["phases"] if p["state"] == "PENDING"):
            raise _pre("Phases must be advanced in order; the next PENDING phase is '%s'." % next(p for p in ro["phases"] if p["state"] == "PENDING")["id"])
        _run_phase(store, pname, rel, target, ro, ph)
        return {}
    if verb == "cancel":
        if st not in ("IN_PROGRESS", "PENDING_APPROVAL", "PENDING"):
            raise _pre("Rollout '%s' cannot be cancelled in state %s." % (ro["name"], st))
        ro["state"] = "CANCELLED"
        for p in ro["phases"]:
            if p["state"] in ("PENDING", "IN_PROGRESS"):
                p["state"] = "ABORTED"
        return {}
    if verb in ("retryJob", "ignoreJob"):
        if st != "FAILED":
            raise _pre("Rollout '%s' has no failed job to %s (state=%s)." % (ro["name"], verb[:-3].lower(), st))
        ph = next((p for p in ro["phases"] if p["id"] == payload.get("phaseId")), None)
        if ph is None:
            raise _bad("Phase '%s' does not exist on rollout '%s'." % (payload.get("phaseId"), ro["name"]))
        job = next((j for j in ph["deploymentJobs"].values() if j["id"] == payload.get("jobId")), None)
        if job is None:
            raise _bad("Job '%s' does not exist in phase '%s'." % (payload.get("jobId"), ph["id"]))
        if job["state"] != "FAILED":
            raise _pre("Job '%s' is %s, not FAILED." % (job["id"], job["state"]))
        ro["state"] = "IN_PROGRESS"
        ro["failureReason"] = ""
        if verb == "retryJob":
            job["state"] = "PENDING"
            _run_phase(store, pname, rel, target, ro, ph)
        else:
            job["state"] = "SKIPPED"
            ph["state"] = "PENDING"
            _run_phase(store, pname, rel, target, ro, ph)
        return {}
    raise _E(404, "NOT_FOUND", "Unknown rollout method :%s." % verb)


def _jobruns(store, method, rname, rest, query):
    coll = _x(store, "jobruns")
    if method != "GET":
        raise _E(405, "UNIMPLEMENTED", "Method not allowed.")
    if not rest:
        return _page([copy.deepcopy(v) for k, v in sorted(coll.items(), key=lambda kv: kv[1]["createTime"]) if k.startswith(rname + "/jobRuns/")], query, "jobRuns")
    name = rname + "/jobRuns/" + rest[0]
    if name not in coll:
        raise _nf("JobRun", name)
    return copy.deepcopy(coll[name])


# ── rollback ──────────────────────────────────────────────────────────────────
def _rollback(store, project, loc, pname, payload):
    tid = payload.get("targetId", "")
    rbid = payload.get("rollbackId", "")
    if not tid or not rbid:
        raise _bad("targetId and rollbackId are required.")
    _id("rollback", rbid, REL_RE)
    rollouts = _x(store, "rollouts")
    mine = sorted([r for k, r in rollouts.items() if k.startswith(pname + "/") and r["targetId"] == tid], key=lambda r: r["createTime"])
    if not mine:
        raise _pre("Target '%s' has no rollouts to roll back." % tid)
    if payload.get("releaseId"):
        rel = _x(store, "releases").get(pname + "/releases/" + payload["releaseId"])
        if rel is None:
            raise _nf("Release", payload["releaseId"])
    else:
        # the most recent SUCCEEDED rollout of a release other than the one currently deployed
        succ = [r for r in mine if r["state"] == "SUCCEEDED"]
        if not succ:
            raise _pre("Target '%s' has no successful rollout to roll back to." % tid)
        cur_rel = succ[-1]["name"].split("/rollouts/")[0]
        prev = [r for r in succ if r["name"].split("/rollouts/")[0] != cur_rel and not r.get("rollbackOfRollout")] or \
               [r for r in succ[:-1] if r["name"].split("/rollouts/")[0] != cur_rel]
        if not prev:
            raise _pre("There is no previously deployed release on target '%s' to roll back to." % tid)
        rel = _x(store, "releases")[prev[-1]["name"].split("/rollouts/")[0]]
    current = next((r for r in reversed(mine) if r["state"] in ("SUCCEEDED", "FAILED", "IN_PROGRESS")), None)
    ro = _new_rollout(store, project, loc, pname, rel, tid, rbid, {"rollbackOfRollout": current["name"] if current else ""})
    if current:
        current.setdefault("rolledBackByRollouts", []).append(ro["name"])
    return {"rollbackConfig": {"rollout": _view(ro), "startingPhaseId": ro["phases"][0]["id"]}}


# ── dispatch ──────────────────────────────────────────────────────────────────
_SEG = {"deliveryPipelines": _pipelines, "targets": _targets}


def dispatch(store, method, path, query=None, headers=None, body=b""):
    query, method = dict(query or {}), method.upper()
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        return Resp(400, {"error": {"code": 400, "message": "Invalid JSON payload received.", "status": "INVALID_ARGUMENT"}})
    segs = path.split("?", 1)[0].strip("/").split("/")
    try:
        project, loc, kind, rest = segs[2], segs[4], segs[5], segs[6:]
        fn = _SEG.get(kind)
        if fn is None:
            raise _E(404, "NOT_FOUND", "%s is not simulated by Vyomi Cloud Deploy." % kind)
        if loc == "-" and method == "GET" and not rest:   # locations/- lists across every location
            out = {}
            items = [v for k, v in sorted(_x(store, "pipelines" if kind == "deliveryPipelines" else "targets").items()) if k.startswith("projects/%s/" % project)]
            out[kind] = [_pview(store, v["name"], v) if kind == "deliveryPipelines" else _view(v) for v in items]
            return Resp(200, out)
        out = fn(store, method, project, loc, rest, query, payload)
        if method != "GET" and hasattr(store, "persist"):
            try:
                store.persist()
            except Exception:
                pass
        return Resp(200, out)
    except _E as e:
        return Resp(e.status, {"error": {"code": e.status, "message": e.message, "status": e.gcp_status}})
    except (IndexError, KeyError, ValueError):
        return Resp(404, {"error": {"code": 404, "message": "Unknown path: %s" % path, "status": "NOT_FOUND"}})
