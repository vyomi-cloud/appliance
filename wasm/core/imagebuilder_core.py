# GENERATED — vendored from core/ by wasm/build_cores.py. DO NOT EDIT.
# Edit the canonical core/ source, then re-run: python3 wasm/build_cores.py
"""EC2 Image Builder (service `imagebuilder`, SigV4 signing name `imagebuilder`, rest-json) — substrate-independent.

Components (real YAML/JSON component documents, validated phase by phase), image recipes, infrastructure configurations,
distribution configurations, image pipelines and image build versions, with the real operation shapes and ARNs
(Create/Get/List/Update/Delete for each, StartImagePipelineExecution, CancelImageCreation, tags). State lives in
``s3_store.account["imagebuilder"]``; AMIs are registered into the shared EC2 model (``vpc_core._model``).

A build is REAL when a container builder is present (the offline appliance's BuildKit, via ``core/ci_core``): the recipe's
components are compiled into a Dockerfile (``FROM <parent image base>`` + every ``ExecuteBash``/``UpdateOS`` step of the
build, then validate/test phases when image tests are enabled), built through ``ci_core.submit_job(kind="image")``, and the
resulting image is the "instance snapshot" the AMI points at. A step that fails fails the build, with the real log.
The runner is injectable (``set_runner``) for hermetic tests.

Honest limits: no container builder on Nano (and on an appliance without Docker) -> every build ends FAILED with that reason,
never a fake AVAILABLE; the AMI is a record whose source is the built container image (it is not a bootable machine image);
only ExecuteBash / UpdateOS / Reboot (no-op in a container) / CreateFile actions execute, any other action fails the build;
builds run synchronously inside the CreateImage / StartImagePipelineExecution call; pipeline schedules are stored but not
triggered automatically; AWS-managed components are a small built-in set (update-linux, reboot-linux, simple-boot-test-linux).
"""
from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import unquote

ACCT = "123456789012"
REGION = "us-east-1"
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_NAME = re.compile(r"^[-_A-Za-z0-9][-_A-Za-z0-9 ]{1,126}$")
_ACTIONS = {"ExecuteBash", "ExecuteBinary", "ExecutePowerShell", "Reboot", "UpdateOS", "SetRegistry", "CreateFile", "DeleteFile",
            "CopyFile", "MoveFile", "CreateFolder", "DeleteFolder", "CopyFolder", "MoveFolder", "SetFileEncoding", "SetFileOwner",
            "SetFilePermissions", "CreateSymlink", "AppendFile", "ReadFile", "S3Download", "S3Upload", "WebDownload",
            "InstallMSI", "UninstallMSI", "Assert", "CreateProcess"}
_PHASES = {"build", "validate", "test"}
_MANAGED = {"update-linux": ("Linux", "UpdateOS"), "reboot-linux": ("Linux", "Reboot"), "simple-boot-test-linux": ("Linux", "ExecuteBash")}
_BASES = (("ubuntu-server-22", "ubuntu:22.04"), ("ubuntu-server-20", "ubuntu:20.04"), ("ubuntu-server-24", "ubuntu:24.04"), ("ubuntu", "ubuntu:24.04"), ("amazon-linux-2023", "amazonlinux:2023"), ("amazon-linux", "amazonlinux:2"),
          ("amzn2023", "amazonlinux:2023"), ("debian", "debian:12"), ("centos", "centos:7"), ("rhel", "redhat/ubi9"))


class _Err(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def _bad(msg):
    return _Err("InvalidParameterValueException", msg, 400)


def _nf(kind, arn):
    return _Err("ResourceNotFoundException", f"Resource {arn} of type {kind} does not exist", 404)


def _ts(dt=None):
    return (dt or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _arn(kind, name, *ver, acct=ACCT):
    return f"arn:aws:imagebuilder:{REGION}:{acct}:{kind}/{name.lower()}" + "".join(f"/{v}" for v in ver)


def _state(s3_store) -> dict:
    st = s3_store.account.setdefault("imagebuilder", {})
    for k in ("components", "recipes", "infra", "dist", "pipelines", "images", "tags"):
        st.setdefault(k, {})
    st.setdefault("seq", 0)
    return st


# ── runner seam ───────────────────────────────────────────────────────────────────────────────
_runner = None


def set_runner(fn):
    """fn(st, spec) -> {"ok": bool, "tag"?, "digest"?, "size"?, "log": [str], "error"?}. None restores the ci_core seam."""
    global _runner
    _runner = fn


def _ci():
    try:
        from core import ci_core as m
    except ImportError:
        import ci_core as m  # type: ignore
    return m


def _ci_runner(st, spec):
    ci = _ci()
    be = ci.backends()
    if not be.get("containers"):
        return {"ok": False, "log": [f"Builder '{be.get('builder')}' cannot run containers."],
                "error": "No container builder on this substrate (BuildKit is only available on the offline appliance with Docker); "
                         "the recipe was validated but no image was built."}
    db = ci.get_db(st)
    repo = "imagebuilder"
    ci.ensure_repo(db, repo)
    ci.commit_files(db, repo, "main", {"Dockerfile": spec["dockerfile"]}, message=f"image build {spec['name']}")
    job = ci.submit_job(db, repo, "main", {"kind": "image", "tag": spec["tag"]})
    log = [x["message"] for x in job["logs"]]
    if job["status"] != "Succeeded":
        return {"ok": False, "log": log, "error": job.get("error") or "build failed"}
    a = job["artifact"]
    return {"ok": True, "log": log, "tag": a.get("tag"), "digest": a.get("digest"), "size": a.get("size", 0)}


# ── component documents (YAML subset or JSON) ─────────────────────────────────────────────────
def _scalar(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(x) for x in inner.split(",")] if inner else []
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~", ""):
        return None
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return s


def _strip_comment(line):
    out, q = [], None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def parse_document(text):
    """JSON, else the YAML subset component documents use (maps, lists, scalars, flow lists, | and > block scalars)."""
    t = (text or "").strip()
    if not t:
        raise _bad("The component document is empty.")
    if t[0] in "{[":
        try:
            return json.loads(t)
        except ValueError as e:
            raise _bad(f"The component document is not valid JSON: {e}")
    raw = text.replace("\t", "  ").split("\n")
    lines = [(len(l) - len(l.lstrip(" ")), l.strip(), i) for i, l in enumerate(raw) if _strip_comment(l).strip() and not l.strip().startswith("---")]

    pos = [0]

    def block_scalar(indent, folded):
        i = pos[0]
        buf = []
        rawpos = lines[i - 1][2] + 1 if i else 0
        j = rawpos
        while j < len(raw):
            l = raw[j]
            if l.strip() and (len(l) - len(l.lstrip(" "))) <= indent:
                break
            buf.append(l)
            j += 1
        while pos[0] < len(lines) and lines[pos[0]][2] < j:
            pos[0] += 1
        ind = min((len(l) - len(l.lstrip(" ")) for l in buf if l.strip()), default=0)
        body = [l[ind:] for l in buf]
        while body and not body[-1].strip():
            body.pop()
        return (" ".join(body) if folded else "\n".join(body)) + "\n"

    def value_of(rest, indent):
        rest = rest.strip()
        if rest in ("|", "|-", "|+", ">", ">-"):
            return block_scalar(indent, rest.startswith(">"))
        if rest == "":
            if pos[0] < len(lines) and (lines[pos[0]][0] > indent or (lines[pos[0]][0] == indent and lines[pos[0]][1].startswith("- "))):
                return parse_block(lines[pos[0]][0])
            return None
        return _scalar(_strip_comment(rest))

    def parse_block(indent):
        if lines[pos[0]][1].startswith("- ") or lines[pos[0]][1] == "-":
            out = []
            while pos[0] < len(lines) and lines[pos[0]][0] == indent and (lines[pos[0]][1].startswith("- ") or lines[pos[0]][1] == "-"):
                _, txt, _n = lines[pos[0]]
                rest = txt[1:].strip()
                if re.match(r"^[^\s\"'\[{][^:]*:(\s|$)", rest) and not rest.startswith("["):
                    lines[pos[0]] = (indent + 2, rest, lines[pos[0]][2])      # `- key: v` -> a map item at deeper indent
                    out.append(parse_block(indent + 2))
                else:
                    pos[0] += 1
                    out.append(value_of(rest, indent))
            return out
        out = {}
        while pos[0] < len(lines) and lines[pos[0]][0] == indent and not lines[pos[0]][1].startswith("- "):
            _, txt, _n = lines[pos[0]]
            m = re.match(r"^(\"[^\"]*\"|'[^']*'|[^:]+?):(?:\s+(.*))?$", txt)
            if not m:
                raise _bad(f"The component document is not valid YAML near: {txt[:60]}")
            pos[0] += 1
            out[_scalar(m.group(1))] = value_of(m.group(2) or "", indent)
        if pos[0] < len(lines) and lines[pos[0]][0] > indent:
            raise _bad(f"The component document has inconsistent indentation near: {lines[pos[0]][1][:60]}")
        return out

    try:
        return parse_block(lines[0][0])
    except _Err:
        raise
    except Exception as e:
        raise _bad(f"The component document is not valid YAML: {e}")


def validate_document(doc, platform):
    if not isinstance(doc, dict):
        raise _bad("The component document must be a mapping.")
    if str(doc.get("schemaVersion")) != "1.0":
        raise _bad("The component document must declare schemaVersion: 1.0.")
    phases = doc.get("phases")
    if not isinstance(phases, list) or not phases:
        raise _bad("The component document must define at least one phase.")
    seen = set()
    declared = {p.get("name") for p in doc.get("parameters") or [] if isinstance(p, dict)}
    for ph in phases:
        if not isinstance(ph, dict) or ph.get("name") not in _PHASES:
            raise _bad(f"Phase name must be one of build, validate, test (got {ph.get('name') if isinstance(ph, dict) else ph!r}).")
        if ph["name"] in seen:
            raise _bad(f"Phase '{ph['name']}' is defined more than once.")
        seen.add(ph["name"])
        steps = ph.get("steps")
        if not isinstance(steps, list) or not steps:
            raise _bad(f"Phase '{ph['name']}' must define at least one step.")
        names = set()
        for s in steps:
            if not isinstance(s, dict) or not s.get("name") or not s.get("action"):
                raise _bad(f"Every step in phase '{ph['name']}' needs a name and an action.")
            if s["name"] in names:
                raise _bad(f"Duplicate step name '{s['name']}' in phase '{ph['name']}'.")
            names.add(s["name"])
            if s["action"] not in _ACTIONS:
                raise _bad(f"Step '{s['name']}' uses unknown action '{s['action']}'.")
            inp = s.get("inputs") or {}
            if s["action"] in ("ExecuteBash", "ExecutePowerShell"):
                cmds = inp.get("commands") if isinstance(inp, dict) else None
                if not isinstance(cmds, list) or not cmds:
                    raise _bad(f"Step '{s['name']}' ({s['action']}) needs inputs.commands.")
                if s["action"] == "ExecuteBash" and platform == "Windows":
                    raise _bad(f"Step '{s['name']}': ExecuteBash is not available on Windows components.")
                if s["action"] == "ExecutePowerShell" and platform == "Linux":
                    raise _bad(f"Step '{s['name']}': ExecutePowerShell is not available on Linux components.")
            for ref in re.findall(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", json.dumps(s)):
                if ref not in declared:
                    raise _bad(f"Step '{s['name']}' references undeclared parameter '{ref}'.")
    return doc


# ── resolution helpers ────────────────────────────────────────────────────────────────────────
def _find_component(st, arn):
    m = re.match(r"^arn:aws:imagebuilder:[^:]+:(\d{12}|aws):component/([^/]+)/([^/]+)(?:/(\d+))?$", arn or "")
    if not m:
        raise _bad(f"Invalid component ARN: {arn}")
    acct, name, ver, build = m.groups()
    if acct == "aws":
        if name not in _MANAGED:
            raise _nf("component", arn)
        plat, action = _MANAGED[name]
        return {"name": name, "version": "1.0.0", "build": 1, "platform": plat, "owner": "Amazon", "arn": arn, "managedAction": action}
    versions = st["components"].get(name, {})
    if ver == "x.x.x":
        ver = max(versions, key=lambda v: tuple(map(int, v.split(".")))) if versions else ver
    b = versions.get(ver)
    if not b:
        raise _nf("component", arn)
    bn = int(build) if build else max(b)
    c = b.get(bn)
    if not c:
        raise _nf("component", arn)
    return c


def _comp_view(c, full=False):
    out = {"arn": c["arn"], "name": c["name"], "version": c["version"], "type": "BUILD", "platform": c["platform"], "owner": c["owner"],
           "dateCreated": c["created"], "supportedOsVersions": c.get("supportedOsVersions", []), "description": c.get("description", "")}
    if full:
        out.update({"data": c.get("data", ""), "changeDescription": c.get("changeDescription", ""), "encrypted": True, "tags": c.get("tags", {}),
                    "parameters": c.get("parameters", [])})
    return out


def _managed_doc(name):
    plat, action = _MANAGED[name]
    inp = {"commands": ["echo 'Boot test passed'"]} if action == "ExecuteBash" else {}
    return {"schemaVersion": "1.0", "phases": [{"name": "build", "steps": [{"name": name, "action": action, "inputs": inp}]}]}


def _base_image(st, parent):
    low = (parent or "").lower()
    if parent and parent.startswith("ami-"):
        for img in _vpc_model_images(st).values():
            if img["id"] == parent and img.get("container_image"):
                return img["container_image"]
    for key, base in _BASES:
        if key in low:
            return base
    return "ubuntu:24.04"


_vpc_ref = {"store": None}


def _vpc_model_images(st):
    s = _vpc_ref["store"]
    if s is None:
        return {}
    try:
        from core import vpc_core
    except ImportError:
        import vpc_core  # type: ignore
    return vpc_core._model(s)["images"]


def _compile(st, recipe, tests_enabled):
    """Recipe -> (Dockerfile text, [unsupported reasons])."""
    lines = [f"FROM {_base_image(st, recipe['parentImage'])}"]
    notes = []
    wd = recipe.get("workingDirectory")
    if wd:
        lines.append(f"WORKDIR {wd}")
    for phase in ("build", "validate", "test"):
        if phase != "build" and not tests_enabled:
            continue
        for ref in recipe["components"]:
            c = _find_component(st, ref["componentArn"])
            doc = _managed_doc(c["name"]) if c.get("managedAction") else parse_document(c["data"])
            params = {p["name"]: (p.get("value") or [None])[0] for p in ref.get("parameters") or []}
            for p in doc.get("parameters") or []:
                params.setdefault(p["name"], p.get("default"))
            for ph in doc["phases"]:
                if ph["name"] != phase:
                    continue
                for s in ph["steps"]:
                    act, inp = s["action"], s.get("inputs") or {}
                    sub = lambda t: re.sub(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", lambda m: str(params.get(m.group(1), m.group(0))), t)
                    tag = f"{c['name']}:{phase}:{s['name']}"
                    if act == "ExecuteBash":
                        script = "set -e\n" + "\n".join(sub(str(x)) for x in inp["commands"]) + "\n"
                        lines.append(f"# {tag}")
                        lines.append("RUN echo " + base64.b64encode(script.encode()).decode() + " | base64 -d | sh")
                    elif act == "UpdateOS":
                        lines.append(f"# {tag}")
                        lines.append("RUN if command -v apt-get >/dev/null; then apt-get update && apt-get -y upgrade; "
                                     "elif command -v dnf >/dev/null; then dnf -y update; elif command -v yum >/dev/null; then yum -y update; fi")
                    elif act == "Reboot":
                        lines.append(f"# {tag}: reboot is a no-op in a container build")
                    elif act == "CreateFile":
                        for f in inp if isinstance(inp, list) else [inp]:
                            body = base64.b64encode(sub(str(f.get("content", ""))).encode()).decode()
                            lines.append(f"# {tag}")
                            lines.append(f"RUN mkdir -p \"$(dirname '{f['path']}')\" && echo {body} | base64 -d > '{f['path']}'")
                    else:
                        notes.append(f"{tag}: action {act} is not supported by the container builder")
    return "\n".join(lines) + "\n", notes


# ── builds ────────────────────────────────────────────────────────────────────────────────────
def _expand_name(tmpl, ver):
    return (tmpl or "{{ imagebuilder:buildDate }}").replace("{{ imagebuilder:buildDate }}", time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())) \
        .replace("{{imagebuilder:buildDate}}", time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())) \
        .replace("{{ imagebuilder:buildVersion }}", ver)


def _register_ami(st, vpc_store, name, region, recipe, dist, tagset, tag, size, build_arn):
    try:
        from core import vpc_core
    except ImportError:
        import vpc_core  # type: ignore
    m = vpc_core._model(vpc_store)
    import uuid
    image_id = "ami-" + uuid.uuid4().hex[:17]
    snap = "snap-" + uuid.uuid4().hex[:17]
    gb = max(1, -(-int(size or 0) // (1 << 30)))
    m["snapshots"][snap] = {"id": snap, "volume_id": "vol-imagebuilder", "volume_size": max(gb, 8), "description": f"Created by EC2 Image Builder for {image_id}",
                            "state": "completed", "progress": "100%", "started": vpc_core._now(), "encrypted": False, "kms_key_id": "",
                            "owner_id": vpc_core.OWNER_ID, "tags": {}}
    desc = (dist or {}).get("description") or f"Image Builder build of {recipe['name']} {recipe['version']}"
    perms = [str(a) for a in ((dist or {}).get("launchPermission") or {}).get("userIds", [])]
    m["images"][image_id] = {
        "id": image_id, "name": name, "description": desc, "owner_id": vpc_core.OWNER_ID, "public": False, "state": "available",
        "architecture": "x86_64", "platform": "windows" if recipe.get("platform") == "Windows" else "", "root_device_type": "ebs",
        "root_device_name": "/dev/xvda", "virtualization_type": "hvm", "creation_date": vpc_core._now(), "source": "imagebuilder",
        "tags": dict(tagset), "launch_permissions": perms,
        "block_devices": [{"device_name": "/dev/xvda", "snapshot_id": snap, "size": max(gb, 8), "volume_type": "gp3", "delete_on_termination": True}],
        "container_image": tag, "imagebuilder_arn": build_arn}
    return image_id


def _run_build(st, vpc_store, img):
    recipe = st["recipes"][img["recipeName"]][img["recipeVersion"]]
    infra = st["infra"].get(img["infraName"])
    dist = st["dist"].get(img["distName"]) if img.get("distName") else None
    tests = (img.get("imageTestsConfiguration") or {}).get("imageTestsEnabled", True)
    log = [f"Image build {img['arn']} started", f"Recipe {recipe['name']} {recipe['version']}, parent image {recipe['parentImage']}"]
    img["state"] = {"status": "BUILDING"}
    try:
        dockerfile, notes = _compile(st, recipe, tests)
    except _Err as e:
        img["state"] = {"status": "FAILED", "reason": e.message}
        img["log"] = log + [e.message]
        return
    if notes:
        reason = "; ".join(notes)
        img["state"] = {"status": "FAILED", "reason": reason}
        img["log"] = log + notes
        return
    st["seq"] += 1
    tag = f"vyomi-imagebuilder/{recipe['name'].lower()}:{recipe['version']}-{img['build']}"
    spec = {"name": recipe["name"], "dockerfile": dockerfile, "tag": tag, "recipe": recipe, "infra": infra}
    log.append("Dockerfile:")
    log += ["  " + x for x in dockerfile.splitlines()]
    try:
        res = (_runner or _ci_runner)(st, spec)
    except Exception as e:                                # a crashing runner is a failed build
        res = {"ok": False, "log": [], "error": f"builder error: {e}"}
    log += res.get("log") or []
    if not res["ok"]:
        img["state"] = {"status": "FAILED", "reason": res.get("error", "build failed")}
        img["log"] = log
        return
    dists = (dist or {}).get("distributions") or [{"region": REGION}]
    amis = []
    for d in dists:
        ac = d.get("amiDistributionConfiguration") or {}
        nm = _expand_name(ac.get("name") or f"{recipe['name']} {{{{ imagebuilder:buildDate }}}}", recipe["version"])
        iid = _register_ami(st, vpc_store, nm, d.get("region", REGION), recipe, ac, {**(img.get("tags") or {}), **(ac.get("amiTags") or {})},
                            res["tag"], res.get("size"), img["arn"])
        amis.append({"region": d.get("region", REGION), "image": iid, "name": nm, "description": ac.get("description", ""), "accountId": ACCT})
        log.append(f"Registered AMI {iid} ({nm}) in {d.get('region', REGION)} from container image {res['tag']}")
    img["outputResources"] = {"amis": amis}
    img["containerImage"] = res["tag"]
    img["state"] = {"status": "AVAILABLE"}
    img["log"] = log


def _create_image(st, vpc_store, p, pipeline=None):
    if pipeline:
        rname, rver = pipeline["recipeName"], pipeline["recipeVersion"]
        infra_n, dist_n, tests = pipeline["infraName"], pipeline.get("distName"), pipeline.get("imageTestsConfiguration")
    else:
        rname, rver = _split_recipe(st, p.get("imageRecipeArn"))
        infra_n = _name_of(st["infra"], p.get("infrastructureConfigurationArn"), "infrastructure-configuration")
        dist_n = _name_of(st["dist"], p["distributionConfigurationArn"], "distribution-configuration") if p.get("distributionConfigurationArn") else None
        tests = p.get("imageTestsConfiguration")
    builds = st["images"].setdefault(rname, {}).setdefault(rver, {})
    n = max(builds, default=0) + 1
    arn = _arn("image", rname, rver, n)
    img = {"arn": arn, "name": rname, "version": rver, "build": n, "type": "AMI", "recipeName": rname, "recipeVersion": rver, "infraName": infra_n,
           "distName": dist_n, "imageTestsConfiguration": tests or {"imageTestsEnabled": True, "timeoutMinutes": 720},
           "dateCreated": _ts(), "tags": dict(p.get("tags") or {}), "pipeline": pipeline["arn"] if pipeline else None,
           "enhancedImageMetadataEnabled": True, "state": {"status": "PENDING"}, "log": []}
    builds[n] = img
    _run_build(st, vpc_store, img)
    return img


def _img_view(st, img):
    r = st["recipes"].get(img["recipeName"], {}).get(img["recipeVersion"])
    inf = st["infra"].get(img["infraName"])
    ds = st["dist"].get(img["distName"]) if img.get("distName") else None
    out = {"arn": img["arn"], "type": "AMI", "name": img["name"], "version": f"{img['version']}/{img['build']}", "platform": (r or {}).get("platform", "Linux"),
           "enhancedImageMetadataEnabled": True, "osVersion": (r or {}).get("parentImage", ""), "state": img["state"],
           "imageRecipe": _recipe_view(r) if r else None, "infrastructureConfiguration": _infra_view(inf) if inf else None,
           "distributionConfiguration": _dist_view(ds) if ds else None, "imageTestsConfiguration": img["imageTestsConfiguration"],
           "dateCreated": img["dateCreated"], "outputResources": img.get("outputResources", {}), "tags": img.get("tags", {}), "buildType": "USER_INITIATED"}
    if img.get("pipeline"):
        out["sourcePipelineArn"] = img["pipeline"]
        out["sourcePipelineName"] = img["pipeline"].rsplit("/", 1)[-1]
    return {k: v for k, v in out.items() if v is not None}


# ── CRUD pieces ───────────────────────────────────────────────────────────────────────────────
def _need(p, *keys):
    for k in keys:
        if p.get(k) in (None, "", []):
            raise _bad(f"Missing required parameter: {k}")


def _chk_name(n, what):
    if not _NAME.match(n or ""):
        raise _bad(f"Invalid {what} name '{n}': 2-127 characters, letters, digits, hyphens, underscores (and spaces).")


def _chk_ver(v, what="semanticVersion"):
    if not _SEMVER.match(v or ""):
        raise _bad(f"Invalid {what} '{v}': expected major.minor.patch.")


def _recipe_view(r):
    return {"arn": r["arn"], "type": "AMI", "name": r["name"], "description": r.get("description", ""), "platform": r["platform"], "owner": ACCT,
            "version": r["version"], "components": r["components"], "parentImage": r["parentImage"], "blockDeviceMappings": r.get("blockDeviceMappings", []),
            "dateCreated": r["created"], "tags": r.get("tags", {}), "workingDirectory": r.get("workingDirectory", "")}


def _infra_view(i):
    return {k: v for k, v in {"arn": i["arn"], "name": i["name"], "description": i.get("description", ""), "instanceTypes": i.get("instanceTypes", ["t3.medium"]),
            "instanceProfileName": i["instanceProfileName"], "securityGroupIds": i.get("securityGroupIds", []), "subnetId": i.get("subnetId"),
            "logging": i.get("logging"), "keyPair": i.get("keyPair"), "terminateInstanceOnFailure": i.get("terminateInstanceOnFailure", True),
            "snsTopicArn": i.get("snsTopicArn"), "resourceTags": i.get("resourceTags", {}), "dateCreated": i["created"], "dateUpdated": i.get("updated"),
            "tags": i.get("tags", {})}.items() if v is not None}


def _dist_view(d):
    return {"arn": d["arn"], "name": d["name"], "description": d.get("description", ""), "distributions": d["distributions"], "timeoutMinutes": 0,
            "dateCreated": d["created"], "dateUpdated": d.get("updated"), "tags": d.get("tags", {})}


def _pipe_view(p):
    return {k: v for k, v in {"arn": p["arn"], "name": p["name"], "description": p.get("description", ""), "platform": p.get("platform", "Linux"),
            "imageRecipeArn": p["imageRecipeArn"], "infrastructureConfigurationArn": p["infrastructureConfigurationArn"],
            "distributionConfigurationArn": p.get("distributionConfigurationArn"), "imageTestsConfiguration": p["imageTestsConfiguration"],
            "schedule": p.get("schedule"), "status": p["status"], "dateCreated": p["created"], "dateUpdated": p.get("updated"),
            "dateLastRun": p.get("lastRun"), "dateNextRun": p.get("nextRun"), "tags": p.get("tags", {}),
            "enhancedImageMetadataEnabled": True}.items() if v is not None}


def _name_of(coll, arn, kind):
    m = re.match(rf"^arn:aws:imagebuilder:[^:]+:\d{{12}}:{kind}/([^/]+)$", arn or "")
    if not m or m.group(1) not in coll:
        raise _nf(kind.replace("-", " "), arn)
    return m.group(1)


def _split_recipe(st, arn):
    m = re.match(r"^arn:aws:imagebuilder:[^:]+:\d{12}:image-recipe/([^/]+)/([^/]+)$", arn or "")
    if not m or m.group(2) not in st["recipes"].get(m.group(1), {}):
        raise _nf("image recipe", arn)
    return m.group(1), m.group(2)


def _tags_in(p):
    t = p.get("tags") or {}
    if not isinstance(t, dict) or len(t) > 50:
        raise _bad("tags must be a map of at most 50 entries.")
    return dict(t)


def op_CreateComponent(st, vp, p, q):
    _need(p, "name", "semanticVersion", "platform")
    _chk_name(p["name"], "component")
    _chk_ver(p["semanticVersion"])
    if p["platform"] not in ("Linux", "Windows", "macOS"):
        raise _bad("platform must be Linux, Windows or macOS.")
    if not p.get("data") and not p.get("uri"):
        raise _bad("Exactly one of data or uri is required.")
    if p.get("data") and p.get("uri"):
        raise _bad("Exactly one of data or uri is required.")
    if p.get("uri"):
        raise _bad("Component documents from uri (S3) are not supported by this build; pass data.")
    doc = validate_document(parse_document(p["data"]), p["platform"])
    versions = st["components"].setdefault(p["name"].lower(), {})
    builds = versions.setdefault(p["semanticVersion"], {})
    if builds:
        raise _Err("ResourceAlreadyExistsException", f"The component {p['name']} version {p['semanticVersion']} already exists.", 400)
    arn = _arn("component", p["name"], p["semanticVersion"], 1)
    builds[1] = {"arn": arn, "name": p["name"], "version": p["semanticVersion"], "build": 1, "platform": p["platform"], "owner": ACCT, "data": p["data"],
                 "description": p.get("description", ""), "changeDescription": p.get("changeDescription", ""), "created": _ts(),
                 "supportedOsVersions": p.get("supportedOsVersions", []), "tags": _tags_in(p), "parameters": doc.get("parameters") or []}
    return {"componentBuildVersionArn": arn}


def _comps_flat(st):
    return [c for vs in st["components"].values() for bs in vs.values() for c in bs.values()]


def op_ListComponents(st, vp, p, q):
    owner = p.get("owner", "Self")
    rows = []
    if owner == "Self":
        seen = {}
        for c in _comps_flat(st):
            k = (c["name"], c["version"])
            if k not in seen or seen[k]["build"] < c["build"]:
                seen[k] = c
        rows = [{**_comp_view(c), "arn": c["arn"].rsplit("/", 1)[0]} for c in seen.values()]
    elif owner == "Amazon":
        rows = [{"arn": f"arn:aws:imagebuilder:{REGION}:aws:component/{n}/x.x.x", "name": n, "version": "1.0.0", "platform": pl, "type": "BUILD", "owner": "Amazon",
                 "dateCreated": "2021-01-01T00:00:00.000Z", "supportedOsVersions": []} for n, (pl, _a) in _MANAGED.items()]
    else:
        rows = []
    for f in p.get("filters") or []:
        if f.get("name") == "name":
            rows = [r for r in rows if r["name"] in f.get("values", [])]
        elif f.get("name") == "platform":
            rows = [r for r in rows if r["platform"] in f.get("values", [])]
    if p.get("byName"):
        pass
    return {"componentVersionList": sorted(rows, key=lambda r: (r["name"], r["version"]))}


def op_ListComponentBuildVersions(st, vp, p, q):
    m = re.match(r"^arn:aws:imagebuilder:[^:]+:\d{12}:component/([^/]+)/([^/]+)$", p.get("componentVersionArn") or "")
    if not m:
        raise _bad("Invalid componentVersionArn.")
    bs = st["components"].get(m.group(1), {}).get(m.group(2), {})
    return {"componentSummaryList": [_comp_view(c) for c in bs.values()]}


def op_GetComponent(st, vp, p, q):
    arn = q.get("componentBuildVersionArn") or p.get("componentBuildVersionArn")
    c = _find_component(st, arn)
    out = _comp_view(c, full=True)
    if c.get("managedAction"):
        out["data"] = json.dumps(_managed_doc(c["name"]))
    return {"component": out}


def op_DeleteComponent(st, vp, p, q):
    arn = q.get("componentBuildVersionArn") or p.get("componentBuildVersionArn")
    c = _find_component(st, arn)
    if c.get("managedAction"):
        raise _bad("AWS-managed components cannot be deleted.")
    for vs in st["recipes"].values():
        for r in vs.values():
            for ref in r["components"]:
                if _find_component_safe(st, ref["componentArn"]) is c:
                    raise _Err("ResourceDependencyException", f"Component {arn} is used by image recipe {r['arn']}", 400)
    del st["components"][c["name"]][c["version"]][c["build"]]
    if not st["components"][c["name"]][c["version"]]:
        del st["components"][c["name"]][c["version"]]
    return {"componentBuildVersionArn": arn}


def _find_component_safe(st, arn):
    try:
        return _find_component(st, arn)
    except _Err:
        return None


def op_CreateImageRecipe(st, vp, p, q):
    _need(p, "name", "semanticVersion", "components", "parentImage")
    _chk_name(p["name"], "image recipe")
    _chk_ver(p["semanticVersion"])
    if p["semanticVersion"] in st["recipes"].get(p["name"].lower(), {}):
        raise _Err("ResourceAlreadyExistsException", f"The image recipe {p['name']} version {p['semanticVersion']} already exists.", 400)
    plats = set()
    for ref in p["components"]:
        if not isinstance(ref, dict) or not ref.get("componentArn"):
            raise _bad("Each component needs a componentArn.")
        c = _find_component(st, ref["componentArn"])
        plats.add(c["platform"])
        declared = {x["name"] for x in (c.get("parameters") or [])}
        for prm in ref.get("parameters") or []:
            if c.get("managedAction") or prm.get("name") not in declared:
                raise _bad(f"Component {ref['componentArn']} has no parameter '{prm.get('name')}'.")
    if len(plats) > 1:
        raise _bad("All components of a recipe must target the same platform.")
    for bd in p.get("blockDeviceMappings") or []:
        if not bd.get("deviceName"):
            raise _bad("blockDeviceMappings entries need a deviceName.")
    arn = _arn("image-recipe", p["name"], p["semanticVersion"])
    st["recipes"].setdefault(p["name"].lower(), {})[p["semanticVersion"]] = {
        "arn": arn, "name": p["name"], "version": p["semanticVersion"], "platform": plats.pop() if plats else "Linux", "components": p["components"],
        "parentImage": p["parentImage"], "description": p.get("description", ""), "blockDeviceMappings": p.get("blockDeviceMappings", []),
        "workingDirectory": p.get("workingDirectory", ""), "created": _ts(), "tags": _tags_in(p)}
    return {"imageRecipeArn": arn}


def _all_recipes(st):
    return [r for vs in st["recipes"].values() for r in vs.values()]


def op_ListImageRecipes(st, vp, p, q):
    rows = [{"arn": r["arn"], "name": r["name"], "platform": r["platform"], "owner": ACCT, "parentImage": r["parentImage"], "dateCreated": r["created"],
             "tags": r.get("tags", {})} for r in _all_recipes(st)]
    return {"imageRecipeSummaryList": sorted(rows, key=lambda r: r["name"])}


def op_GetImageRecipe(st, vp, p, q):
    n, v = _split_recipe(st, q.get("imageRecipeArn") or p.get("imageRecipeArn"))
    return {"imageRecipe": _recipe_view(st["recipes"][n][v])}


def op_DeleteImageRecipe(st, vp, p, q):
    arn = q.get("imageRecipeArn") or p.get("imageRecipeArn")
    n, v = _split_recipe(st, arn)
    for pl in st["pipelines"].values():
        if pl["imageRecipeArn"] == arn:
            raise _Err("ResourceDependencyException", f"Image recipe {arn} is used by image pipeline {pl['arn']}", 400)
    if st["images"].get(n, {}).get(v):
        raise _Err("ResourceDependencyException", f"Image recipe {arn} is used by image {_arn('image', n, v)}", 400)
    del st["recipes"][n][v]
    return {"imageRecipeArn": arn}


def _infra_fields(p, cur=None):
    out = dict(cur or {})
    for k in ("description", "instanceTypes", "instanceProfileName", "securityGroupIds", "subnetId", "logging", "keyPair", "terminateInstanceOnFailure",
              "snsTopicArn", "resourceTags"):
        if k in p:
            out[k] = p[k]
    if not out.get("instanceProfileName"):
        raise _bad("Missing required parameter: instanceProfileName")
    if out.get("securityGroupIds") and not out.get("subnetId"):
        raise _bad("A subnetId is required when securityGroupIds are specified.")
    for t in out.get("instanceTypes") or []:
        if not re.match(r"^[a-z][a-z0-9-]*\d[a-z0-9-]*\.[a-z0-9]+$", t):
            raise _bad(f"Invalid instance type '{t}'.")
    return out


def op_CreateInfrastructureConfiguration(st, vp, p, q):
    _need(p, "name", "instanceProfileName")
    _chk_name(p["name"], "infrastructure configuration")
    if p["name"].lower() in st["infra"]:
        raise _Err("ResourceAlreadyExistsException", f"The infrastructure configuration {p['name']} already exists.", 400)
    arn = _arn("infrastructure-configuration", p["name"])
    st["infra"][p["name"].lower()] = {"arn": arn, "name": p["name"], "created": _ts(), "tags": _tags_in(p), **_infra_fields(p)}
    return {"infrastructureConfigurationArn": arn}


def op_ListInfrastructureConfigurations(st, vp, p, q):
    return {"infrastructureConfigurationSummaryList": [{"arn": i["arn"], "name": i["name"], "description": i.get("description", ""), "dateCreated": i["created"],
                                                        "dateUpdated": i.get("updated"), "instanceTypes": i.get("instanceTypes", []), "instanceProfileName": i["instanceProfileName"],
                                                        "tags": i.get("tags", {})} for i in st["infra"].values()]}


def op_GetInfrastructureConfiguration(st, vp, p, q):
    return {"infrastructureConfiguration": _infra_view(st["infra"][_name_of(st["infra"], q.get("infrastructureConfigurationArn") or p.get("infrastructureConfigurationArn"), "infrastructure-configuration")])}


def op_UpdateInfrastructureConfiguration(st, vp, p, q):
    n = _name_of(st["infra"], p.get("infrastructureConfigurationArn"), "infrastructure-configuration")
    st["infra"][n] = {**st["infra"][n], **_infra_fields(p, st["infra"][n]), "updated": _ts()}
    return {"infrastructureConfigurationArn": p["infrastructureConfigurationArn"]}


def op_DeleteInfrastructureConfiguration(st, vp, p, q):
    arn = q.get("infrastructureConfigurationArn") or p.get("infrastructureConfigurationArn")
    n = _name_of(st["infra"], arn, "infrastructure-configuration")
    for pl in st["pipelines"].values():
        if pl["infrastructureConfigurationArn"] == arn:
            raise _Err("ResourceDependencyException", f"Infrastructure configuration {arn} is used by image pipeline {pl['arn']}", 400)
    del st["infra"][n]
    return {"infrastructureConfigurationArn": arn}


def _dists(p):
    ds = p.get("distributions")
    if not isinstance(ds, list) or not ds:
        raise _bad("distributions must contain at least one entry.")
    for d in ds:
        if not d.get("region"):
            raise _bad("Each distribution needs a region.")
        ac = d.get("amiDistributionConfiguration") or {}
        if ac.get("name") and len(ac["name"]) > 127:
            raise _bad("amiDistributionConfiguration.name is too long (max 127).")
        for u in (ac.get("launchPermission") or {}).get("userIds", []):
            if not re.fullmatch(r"\d{12}", str(u)):
                raise _bad(f"Invalid launch permission account id '{u}'.")
    return ds


def op_CreateDistributionConfiguration(st, vp, p, q):
    _need(p, "name")
    _chk_name(p["name"], "distribution configuration")
    if p["name"].lower() in st["dist"]:
        raise _Err("ResourceAlreadyExistsException", f"The distribution configuration {p['name']} already exists.", 400)
    arn = _arn("distribution-configuration", p["name"])
    st["dist"][p["name"].lower()] = {"arn": arn, "name": p["name"], "description": p.get("description", ""), "distributions": _dists(p), "created": _ts(), "tags": _tags_in(p)}
    return {"distributionConfigurationArn": arn}


def op_ListDistributionConfigurations(st, vp, p, q):
    return {"distributionConfigurationSummaryList": [{"arn": d["arn"], "name": d["name"], "description": d.get("description", ""), "dateCreated": d["created"],
                                                      "dateUpdated": d.get("updated"), "regions": [x["region"] for x in d["distributions"]], "tags": d.get("tags", {})}
                                                     for d in st["dist"].values()]}


def op_GetDistributionConfiguration(st, vp, p, q):
    return {"distributionConfiguration": _dist_view(st["dist"][_name_of(st["dist"], q.get("distributionConfigurationArn") or p.get("distributionConfigurationArn"), "distribution-configuration")])}


def op_UpdateDistributionConfiguration(st, vp, p, q):
    n = _name_of(st["dist"], p.get("distributionConfigurationArn"), "distribution-configuration")
    d = st["dist"][n]
    d["distributions"] = _dists(p)
    if "description" in p:
        d["description"] = p["description"]
    d["updated"] = _ts()
    return {"distributionConfigurationArn": p["distributionConfigurationArn"]}


def op_DeleteDistributionConfiguration(st, vp, p, q):
    arn = q.get("distributionConfigurationArn") or p.get("distributionConfigurationArn")
    n = _name_of(st["dist"], arn, "distribution-configuration")
    for pl in st["pipelines"].values():
        if pl.get("distributionConfigurationArn") == arn:
            raise _Err("ResourceDependencyException", f"Distribution configuration {arn} is used by image pipeline {pl['arn']}", 400)
    del st["dist"][n]
    return {"distributionConfigurationArn": arn}


_CRON = re.compile(r"^cron\(\S+( \S+){5,6}\)$")


def _pipe_fields(st, p, cur=None):
    out = dict(cur or {})
    _need({**out, **p}, "imageRecipeArn", "infrastructureConfigurationArn")
    rn, rv = _split_recipe(st, p.get("imageRecipeArn", out.get("imageRecipeArn")))
    _name_of(st["infra"], p.get("infrastructureConfigurationArn", out.get("infrastructureConfigurationArn")), "infrastructure-configuration")
    if p.get("distributionConfigurationArn"):
        _name_of(st["dist"], p["distributionConfigurationArn"], "distribution-configuration")
    for k in ("description", "imageRecipeArn", "infrastructureConfigurationArn", "distributionConfigurationArn", "imageTestsConfiguration", "schedule", "status"):
        if k in p:
            out[k] = p[k]
    sch = out.get("schedule")
    if sch:
        if not _CRON.match(sch.get("scheduleExpression", "")):
            raise _bad("schedule.scheduleExpression must be a cron(...) expression.")
        if sch.get("pipelineExecutionStartCondition", "EXPRESSION_MATCH_AND_DEPENDENCY_UPDATES_AVAILABLE") not in (
                "EXPRESSION_MATCH_ONLY", "EXPRESSION_MATCH_AND_DEPENDENCY_UPDATES_AVAILABLE"):
            raise _bad("Invalid pipelineExecutionStartCondition.")
    out["status"] = out.get("status", "ENABLED")
    if out["status"] not in ("ENABLED", "DISABLED"):
        raise _bad("status must be ENABLED or DISABLED.")
    out.setdefault("imageTestsConfiguration", {"imageTestsEnabled": True, "timeoutMinutes": 720})
    out["recipeName"], out["recipeVersion"] = rn, rv
    out["infraName"] = _name_of(st["infra"], out["infrastructureConfigurationArn"], "infrastructure-configuration")
    out["distName"] = _name_of(st["dist"], out["distributionConfigurationArn"], "distribution-configuration") if out.get("distributionConfigurationArn") else None
    out["platform"] = st["recipes"][rn][rv]["platform"]
    return out


def op_CreateImagePipeline(st, vp, p, q):
    _need(p, "name")
    _chk_name(p["name"], "image pipeline")
    if p["name"].lower() in st["pipelines"]:
        raise _Err("ResourceAlreadyExistsException", f"The image pipeline {p['name']} already exists.", 400)
    arn = _arn("image-pipeline", p["name"])
    st["pipelines"][p["name"].lower()] = {"arn": arn, "name": p["name"], "created": _ts(), "tags": _tags_in(p), **_pipe_fields(st, p)}
    return {"imagePipelineArn": arn}


def _pipe_name(st, arn):
    return _name_of(st["pipelines"], arn, "image-pipeline")


def op_ListImagePipelines(st, vp, p, q):
    return {"imagePipelineList": [_pipe_view(x) for x in st["pipelines"].values()]}


def op_GetImagePipeline(st, vp, p, q):
    return {"imagePipeline": _pipe_view(st["pipelines"][_pipe_name(st, q.get("imagePipelineArn") or p.get("imagePipelineArn"))])}


def op_UpdateImagePipeline(st, vp, p, q):
    n = _pipe_name(st, p.get("imagePipelineArn"))
    st["pipelines"][n] = {**st["pipelines"][n], **_pipe_fields(st, p, st["pipelines"][n]), "updated": _ts()}
    return {"imagePipelineArn": p["imagePipelineArn"]}


def op_DeleteImagePipeline(st, vp, p, q):
    arn = q.get("imagePipelineArn") or p.get("imagePipelineArn")
    del st["pipelines"][_pipe_name(st, arn)]
    return {"imagePipelineArn": arn}


def op_StartImagePipelineExecution(st, vp, p, q):
    pl = st["pipelines"][_pipe_name(st, p.get("imagePipelineArn"))]
    if pl["status"] != "ENABLED":
        raise _Err("InvalidRequestException", "The image pipeline is disabled.", 400)
    img = _create_image(st, vp, {"tags": pl.get("tags")}, pipeline=pl)
    pl["lastRun"] = _ts()
    return {"imageBuildVersionArn": img["arn"]}


def op_ListImagePipelineImages(st, vp, p, q):
    pl = st["pipelines"][_pipe_name(st, p.get("imagePipelineArn"))]
    return {"imageSummaryList": [_img_summary(i) for i in _all_images(st) if i.get("pipeline") == pl["arn"]]}


def op_CreateImage(st, vp, p, q):
    _need(p, "imageRecipeArn", "infrastructureConfigurationArn")
    return {"imageBuildVersionArn": _create_image(st, vp, p)["arn"]}


def _all_images(st):
    return [b for vs in st["images"].values() for bs in vs.values() for b in bs.values()]


def _img_summary(i):
    return {"arn": i["arn"], "name": i["name"], "type": "AMI", "version": f"{i['version']}/{i['build']}", "state": i["state"], "dateCreated": i["dateCreated"],
            "outputResources": i.get("outputResources", {}), "tags": i.get("tags", {}), "owner": ACCT}


def _find_image(st, arn):
    m = re.match(r"^arn:aws:imagebuilder:[^:]+:\d{12}:image/([^/]+)/([^/]+)/(\d+)$", arn or "")
    if not m:
        raise _bad(f"Invalid imageBuildVersionArn: {arn}")
    img = st["images"].get(m.group(1), {}).get(m.group(2), {}).get(int(m.group(3)))
    if not img:
        raise _nf("image", arn)
    return img


def op_GetImage(st, vp, p, q):
    return {"image": _img_view(st, _find_image(st, q.get("imageBuildVersionArn") or p.get("imageBuildVersionArn")))}


def op_ListImages(st, vp, p, q):
    seen = {}
    for i in _all_images(st):
        k = (i["name"], i["version"])
        seen.setdefault(k, i)
    return {"imageVersionList": [{"arn": _arn("image", n, v), "name": n, "type": "AMI", "version": v, "owner": ACCT,
                                  "dateCreated": i["dateCreated"]} for (n, v), i in sorted(seen.items())]}


def op_ListImageBuildVersions(st, vp, p, q):
    m = re.match(r"^arn:aws:imagebuilder:[^:]+:\d{12}:image/([^/]+)/([^/]+)$", p.get("imageVersionArn") or "")
    if not m:
        raise _bad("Invalid imageVersionArn.")
    return {"imageSummaryList": [_img_summary(i) for i in st["images"].get(m.group(1), {}).get(m.group(2), {}).values()]}


def op_DeleteImage(st, vp, p, q):
    arn = q.get("imageBuildVersionArn") or p.get("imageBuildVersionArn")
    img = _find_image(st, arn)
    if img["state"]["status"] == "BUILDING":
        raise _Err("ResourceDependencyException", "The image is still building.", 400)
    del st["images"][img["name"]][img["version"]][img["build"]]
    return {"imageBuildVersionArn": arn}


def op_CancelImageCreation(st, vp, p, q):
    img = _find_image(st, p.get("imageBuildVersionArn"))
    if img["state"]["status"] not in ("BUILDING", "PENDING"):
        raise _Err("InvalidRequestException", f"Image creation can only be cancelled while the build is in progress (state: {img['state']['status']}).", 400)
    img["state"] = {"status": "CANCELLED"}
    return {"imageBuildVersionArn": img["arn"]}


def op_VyomiGetImageBuildLog(st, vp, p, q):
    img = _find_image(st, q.get("imageBuildVersionArn") or p.get("imageBuildVersionArn"))
    return {"imageBuildVersionArn": img["arn"], "log": img.get("log", []), "containerImage": img.get("containerImage")}


def _tag_target(st, arn):
    m = re.match(r"^arn:aws:imagebuilder:[^:]+:\d{12}:([a-z-]+)/(.+)$", arn or "")
    if not m:
        raise _bad(f"Invalid resource ARN: {arn}")
    kind, rest = m.groups()
    parts = rest.split("/")
    try:
        if kind == "component":
            return st["components"][parts[0]][parts[1]][int(parts[2])]
        if kind == "image-recipe":
            return st["recipes"][parts[0]][parts[1]]
        if kind == "infrastructure-configuration":
            return st["infra"][parts[0]]
        if kind == "distribution-configuration":
            return st["dist"][parts[0]]
        if kind == "image-pipeline":
            return st["pipelines"][parts[0]]
        if kind == "image":
            return st["images"][parts[0]][parts[1]][int(parts[2])]
    except (KeyError, IndexError, ValueError):
        pass
    raise _nf(kind.replace("-", " "), arn)


def _tags_op(st, method, arn, p, q):
    t = _tag_target(st, arn)
    tg = t.setdefault("tags", {})
    if method == "GET":
        return {"tags": tg}
    if method == "POST":
        new = p.get("tags") or {}
        if len(tg) + len([k for k in new if k not in tg]) > 50:
            raise _bad("A resource can have at most 50 tags.")
        tg.update(new)
        return {}
    keys = q.get("tagKeys")
    for k in ([keys] if isinstance(keys, str) else keys or []):
        tg.pop(k, None)
    return {}


_OPS = {("PUT", "CreateComponent"): op_CreateComponent, ("POST", "ListComponents"): op_ListComponents,
        ("POST", "ListComponentBuildVersions"): op_ListComponentBuildVersions, ("GET", "GetComponent"): op_GetComponent, ("DELETE", "DeleteComponent"): op_DeleteComponent,
        ("PUT", "CreateImageRecipe"): op_CreateImageRecipe, ("POST", "ListImageRecipes"): op_ListImageRecipes, ("GET", "GetImageRecipe"): op_GetImageRecipe,
        ("DELETE", "DeleteImageRecipe"): op_DeleteImageRecipe,
        ("PUT", "CreateInfrastructureConfiguration"): op_CreateInfrastructureConfiguration, ("POST", "ListInfrastructureConfigurations"): op_ListInfrastructureConfigurations,
        ("GET", "GetInfrastructureConfiguration"): op_GetInfrastructureConfiguration, ("PUT", "UpdateInfrastructureConfiguration"): op_UpdateInfrastructureConfiguration,
        ("DELETE", "DeleteInfrastructureConfiguration"): op_DeleteInfrastructureConfiguration,
        ("PUT", "CreateDistributionConfiguration"): op_CreateDistributionConfiguration, ("POST", "ListDistributionConfigurations"): op_ListDistributionConfigurations,
        ("GET", "GetDistributionConfiguration"): op_GetDistributionConfiguration, ("PUT", "UpdateDistributionConfiguration"): op_UpdateDistributionConfiguration,
        ("DELETE", "DeleteDistributionConfiguration"): op_DeleteDistributionConfiguration,
        ("PUT", "CreateImagePipeline"): op_CreateImagePipeline, ("POST", "ListImagePipelines"): op_ListImagePipelines, ("GET", "GetImagePipeline"): op_GetImagePipeline,
        ("PUT", "UpdateImagePipeline"): op_UpdateImagePipeline, ("DELETE", "DeleteImagePipeline"): op_DeleteImagePipeline,
        ("PUT", "StartImagePipelineExecution"): op_StartImagePipelineExecution, ("POST", "ListImagePipelineImages"): op_ListImagePipelineImages,
        ("PUT", "CreateImage"): op_CreateImage, ("POST", "ListImages"): op_ListImages, ("POST", "ListImageBuildVersions"): op_ListImageBuildVersions,
        ("GET", "GetImage"): op_GetImage, ("DELETE", "DeleteImage"): op_DeleteImage, ("PUT", "CancelImageCreation"): op_CancelImageCreation,
        ("GET", "VyomiGetImageBuildLog"): op_VyomiGetImageBuildLog}


def _resp(status, doc, err=None):
    h = {"content-type": "application/json"}
    if err:
        h["x-amzn-errortype"] = err
    return {"status": status, "headers": h, "body": json.dumps(doc).encode()}


def dispatch(s3_store, vpc_store, method, path, query, body):
    """rest-json entry point -> {"status","headers","body"}. `vpc_store` holds the shared EC2 model (AMIs are registered there)."""
    method = method.upper()
    st = _state(s3_store)
    _vpc_ref["store"] = vpc_store
    path = "/" + (path or "").strip("/")
    q = {k: (v[0] if isinstance(v, list) and len(v) == 1 else v) for k, v in (query or {}).items()}
    try:
        p = json.loads(body) if body else {}
        if not isinstance(p, dict):
            raise ValueError
    except ValueError:
        return _resp(400, {"__type": "InvalidParameterValueException", "message": "The request body must be a JSON object."}, "InvalidParameterValueException")
    try:
        if path.startswith("/tags/"):
            return _resp(200, _tags_op(st, method, unquote(path[6:]), p, q))
        fn = _OPS.get((method, path.lstrip("/")))
        if fn is None:
            return _resp(404, {"__type": "UnknownOperationException", "message": f"Unknown operation {method} {path}"}, "UnknownOperationException")
        out = fn(st, vpc_store, p, q)
        if method in ("PUT", "DELETE", "POST"):
            try:
                s3_store.persist()
            except Exception:
                pass
        return _resp(200, out)
    except _Err as e:
        return _resp(e.status, {"__type": e.code, "message": e.message}, e.code)
    except KeyError as e:                                 # a dangling name inside an ARN we already shape-checked
        return _resp(404, {"__type": "ResourceNotFoundException", "message": f"Resource {e} does not exist"}, "ResourceNotFoundException")
