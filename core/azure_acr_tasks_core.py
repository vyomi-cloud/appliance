"""ACR Tasks `scheduleRun` (substrate-free): quick builds and task runs on the shared CI seam (core/ci_core.py).

``POST .../registries/{r}/scheduleRun`` accepts (like Azure):

* ``DockerBuildRequest`` -- {sourceLocation, dockerFilePath, imageNames, buildArguments, isPushEnabled}
* ``TaskRunRequest``     -- {taskName | taskId} runs a stored task (``registries/tasks``: properties.step.{contextPath,
  dockerFilePath, imageNames}); the task must exist and be enabled.

Source: ``sourceLocation``/``contextPath`` is a https://github.com/{owner}/{repo}[#branch] URL (fetched with the user's
own PAT when one is set via ``properties.vyomiAccessToken``/the connection), or -- a Vyomi extension for a self-contained
quick build -- inline ``vyomiFiles`` {path: text}. ``FileTaskRunRequest``/``EncodedTaskRunRequest`` (multi-step YAML
tasks) are rejected as not supported.

The run is a real ``registries/runs`` ARM record (Queued->Succeeded/Failed) with the build log in
``properties.vyomiLogs`` and ``outputImages`` ONLY when an image was really built. Image builds run through BuildKit on
the offline appliance; on Nano (no container runtime) they fail with that reason. The built image lives in the host
docker engine under its tag; it is NOT pushed into the simulated registry's repository store (limited, see capability JSON).
"""
from __future__ import annotations

import datetime
import re

try:
    from core import ci_core as ci
except ImportError:                                    # Pyodide flat layout
    import ci_core as ci                               # type: ignore

_TYPES = ("DockerBuildRequest", "TaskRunRequest")
_IMG = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*(:[\w][\w.-]{0,127})?$")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _err(status, code, message):
    return {"status": status, "headers": {}, "body": {"error": {"code": code, "message": message}}}


def _source(db, run_id, ctx, files, ref_default="main"):
    """Return the repo name holding the build context in the seam."""
    repo = f"run-{run_id}"
    if files:
        if not isinstance(files, dict) or not all(isinstance(k, str) for k in files):
            raise ci.CiError("InvalidRequest", "vyomiFiles must be an object {path: text}.")
        ci.create_repo(db, repo)
        ci.commit_files(db, repo, ref_default, dict(files), "inline build context", "acr-task")
        return repo, ref_default
    url, _, ref = str(ctx or "").partition("#")
    if not url:
        raise ci.CiError("InvalidRequest", "sourceLocation (a https://github.com/{owner}/{repo}[#branch] URL) or vyomiFiles is required.")
    ci.create_repo(db, repo)
    ci.import_external(db, repo, url, ref or ref_default, branch=ref or ref_default, message=f"context {url}", ctx=None)
    return repo, ref or ref_default


def schedule_run(state, reg_rid, reg_rec, payload, sub, rg):
    p = payload if isinstance(payload, dict) else {}
    typ = p.get("type")
    if typ in ("FileTaskRunRequest", "EncodedTaskRunRequest"):
        return _err(400, "NotSupported", f"{typ} (multi-step YAML tasks) is not supported; use DockerBuildRequest or a Docker-step task.")
    if typ not in _TYPES:
        return _err(400, "InvalidRunRequest", f"type must be one of {', '.join(_TYPES)}.")
    tier = (reg_rec.get("sku") or {}).get("name") or (reg_rec.get("sku") or {}).get("tier")
    task = None
    if typ == "TaskRunRequest":
        if tier == "Basic":
            return _err(400, "BadRequest", "Tasks require a Standard or Premium registry.")
        tname = p.get("taskName") or str(p.get("taskId") or "").rsplit("/", 1)[-1]
        task = state.get(f"{reg_rid}/tasks/{tname}".lower())
        if not tname or not task:
            return _err(404, "ResourceNotFound", f"Task '{tname}' was not found on registry '{reg_rec['name']}'.")
        if (task.get("properties") or {}).get("status") == "Disabled":
            return _err(400, "TaskDisabled", f"Task '{tname}' is disabled.")
        step = (task.get("properties") or {}).get("step") or {}
        ctx, df, images, args = step.get("contextPath"), step.get("dockerFilePath"), step.get("imageNames"), [
            f"{a.get('name')}={a.get('value')}" for a in step.get("arguments") or []]
        if p.get("overrideTaskStepProperties"):
            o = p["overrideTaskStepProperties"]
            ctx, df, images = o.get("contextPath", ctx), o.get("file", df), o.get("imageNames", images)
    else:
        ctx, df, images = p.get("sourceLocation"), p.get("dockerFilePath"), p.get("imageNames")
        args = [f"{a.get('name')}={a.get('value')}" for a in p.get("arguments") or p.get("buildArguments") or []]
    df = df or "Dockerfile"
    images = images if isinstance(images, list) else ([images] if images else [])
    db = ci.get_db(reg_rec)
    run_id = "ca" + str(db["seq"] + 1)
    images = [i.replace("{{.Run.ID}}", run_id) if isinstance(i, str) else i for i in images]
    if not all(isinstance(i, str) and _IMG.match(i) for i in images):
        return _err(400, "InvalidImageName", "imageNames must be repository[:tag] (lowercase, e.g. samples/app:{{.Run.ID}}).")
    db["seq"] += 1
    rid = f"{reg_rid}/runs/{run_id}"
    started = _now()
    props = {"runId": run_id, "status": "Running", "runType": "QuickBuild" if typ == "DockerBuildRequest" else "QuickRun",
             "createTime": started, "startTime": started, "taskName": task and task["name"], "platform": p.get("platform") or {"os": "Linux", "architecture": "amd64"},
             "isArchiveEnabled": False, "provisioningState": "Succeeded", "vyomiLogs": [], "outputImages": []}
    try:
        repo, ref = _source(db, run_id, ctx, p.get("vyomiFiles"))
        tree = ci.tree(db, repo, ref)
        if df not in tree:
            raise ci.CiError("DockerfileNotFound", f"'{df}' was not found in the build context.")
        if df != "Dockerfile":
            tree = dict(tree); tree["Dockerfile"] = tree[df]
        tag = images[0] if images else f"vyomi-acr/{reg_rec['name'].lower()}/run:{run_id}"
        job = ci.submit_job(db, repo, ref, {"kind": "image", "tag": f"{reg_rec['name'].lower()}.azurecr.io/{tag}" if images else tag,
                                            "buildArgs": args}, trigger="acr:" + props["runType"])
        props["vyomiLogs"] = [l["message"] for l in job["logs"]]
        if job["status"] == "Succeeded":
            props["status"] = "Succeeded"
            for img in images or [tag]:
                r, _, t = img.partition(":")
                props["outputImages"].append({"registry": f"{reg_rec['name'].lower()}.azurecr.io", "repository": r, "tag": t or "latest",
                                              "digest": job["artifact"]["digest"]})
            props["vyomiNote"] = "Image is in the host docker engine under its tag; it was not pushed to the simulated registry's repository store."
        else:
            props["status"], props["errorMessage"] = "Failed", job["error"]
    except ci.CiError as e:
        props["status"], props["errorMessage"] = "Failed", e.message
        props["vyomiLogs"].append(f"Run failed: {e.message}")
    props["finishTime"] = _now()
    props["lastUpdatedTime"] = props["finishTime"]
    state[rid.lower()] = {"id": rid, "name": run_id, "type": "Microsoft.ContainerRegistry/registries/runs", "location": reg_rec.get("location"),
                         "tags": {}, "properties": props, "_type": "Microsoft.ContainerRegistry/registries/runs", "_sub": sub, "_rg": rg,
                         "_created": started, "systemData": {"createdAt": started, "lastModifiedAt": props["finishTime"]}}
    return {"status": 200, "headers": {}, "body": {"id": rid, "name": run_id, "type": "Microsoft.ContainerRegistry/registries/runs", "properties": props}}
