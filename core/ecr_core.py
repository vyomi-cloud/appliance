"""Amazon ECR (JSON 1.1, SigV4 signing name `ecr`, X-Amz-Target AmazonEC2ContainerRegistry_V20150921.*) + the ECR
registry data plane (OCI / Docker Registry HTTP API v2 on `<acct>.dkr.ecr.<region>.amazonaws.com`) + an Inspector2-style
findings view (`inspector2`) — substrate-independent, state in `store.account["ecr"]` of the S3 ObjectStore.

Real behaviour: repositories (name rules, mutability, scanOnPush, encryption, policy, tags), images with real
manifests whose config/layer blobs are stored in the simulator's own S3 (bucket `vyomi-ecr-<account>`, keys
`blobs/<sha256>` and `manifests/<digest>`), the layer-upload API (Initiate/UploadPart/Complete/BatchCheck) and the
registry v2 wire (`docker push`/`pull` after `aws ecr get-login-password | docker login`), tag immutability,
lifecycle policies (validated; preview + real expiry on tick) and cross-region replication to the same account.
Scanning runs core/vuln_scan_core over the image's stored config blob (BASIC findings via DescribeImageScanFindings,
ENHANCED findings in the Inspector2 shape via DescribeImageScanFindings.enhancedFindings and inspector2 ListFindings).

Honest limits: layer tarballs are never unpacked or executed; findings come from the bundled advisory snapshot
(or Trivy on the offline appliance), not Amazon's feed; replication stays inside this simulator account (other
registry ids report FAILED); no pull-through cache; GetDownloadUrlForLayer returns the registry blob URL, not a
presigned S3 URL. Pure Python — no fastapi / boto3, loads under Pyodide.
"""
from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field

ACCOUNT = "123456789012"
DEFAULT_REGION = "us-east-1"
_NAME_RE = re.compile(r"^(?:[a-z0-9]+(?:[._-][a-z0-9]+)*/)*[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_INDEX_TYPES = ("application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json")
_SEV_BASIC = {"CRITICAL": "CRITICAL", "HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW", "UNKNOWN": "UNDEFINED"}
_SEV_INSPECTOR = {"CRITICAL": "CRITICAL", "HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW", "UNKNOWN": "UNTRIAGED"}
_TOKEN_TTL = 12 * 3600


@dataclass
class Resp:
    status: int = 200
    body: object = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class _Err(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def _vs():
    try:
        from core import vuln_scan_core as m
    except ImportError:                                     # Pyodide flat layout
        import vuln_scan_core as m                          # type: ignore
    return m


def _s3c():
    try:
        from core import s3_object_core as m
    except ImportError:
        import s3_object_core as m                          # type: ignore
    return m


# ── state ─────────────────────────────────────────────────────────────────────────────
def _st(store) -> dict:
    s = store.account.setdefault("ecr", {})
    s.setdefault("regions", {})
    s.setdefault("blobs", {})            # digest -> size  (content lives in S3)
    s.setdefault("uploads", {})
    s.setdefault("tokens", {})           # sha256(password) -> expiry
    s.setdefault("replication", {"rules": []})
    s.setdefault("scanning", {"scanType": "BASIC", "rules": []})
    s.setdefault("registryPolicy", None)
    s.setdefault("lifecycleLog", [])
    return s


def _bucket(store) -> str:
    b = f"vyomi-ecr-{ACCOUNT}"
    store.create_bucket(b)
    return b


def _s3_put(store, key, data: bytes):
    r = _s3c().dispatch(store, "PUT", f"/{_bucket(store)}/{key}", {}, {"content-type": "application/octet-stream"}, bytes(data))
    if r.status >= 300:
        raise _Err("ServerException", f"object store write failed ({r.status})", 500)


def _s3_get(store, key):
    r = _s3c().dispatch(store, "GET", f"/{_bucket(store)}/{key}", {}, {}, b"")
    return bytes(r.body) if r.status == 200 else None


def _s3_del(store, key):
    _s3c().dispatch(store, "DELETE", f"/{_bucket(store)}/{key}", {}, {}, b"")


def _repos(st, region) -> dict:
    return st["regions"].setdefault(region, {})


def _now() -> float:
    return round(time.time(), 3)


def _uri(name, region):
    return f"{ACCOUNT}.dkr.ecr.{region}.amazonaws.com/{name}"


def _repo_arn(name, region):
    return f"arn:aws:ecr:{region}:{ACCOUNT}:repository/{name}"


def _sha(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _chk_registry(p):
    rid = p.get("registryId")
    if rid and rid != ACCOUNT:
        raise _Err("InvalidParameterException", f"Invalid parameter at 'registryId' failed to satisfy constraint: registry {rid} is not this account")


def _get_repo(st, region, p):
    _chk_registry(p)
    name = p.get("repositoryName")
    if not name:
        raise _Err("InvalidParameterException", "Missing required parameter: repositoryName")
    r = _repos(st, region).get(name)
    if not r:
        raise _Err("RepositoryNotFoundException",
                   f"The repository with name '{name}' does not exist in the registry with id '{ACCOUNT}'")
    return r


def _repo_view(r, region):
    d = {"repositoryArn": _repo_arn(r["name"], region), "registryId": ACCOUNT, "repositoryName": r["name"],
         "repositoryUri": _uri(r["name"], region), "createdAt": r["createdAt"], "imageTagMutability": r["mutability"],
         "imageScanningConfiguration": {"scanOnPush": r["scanOnPush"]}, "encryptionConfiguration": r["encryption"]}
    return d


# ── images ────────────────────────────────────────────────────────────────────────────
def _manifest_refs(body: bytes):
    """(mediaType, config digest|None, [layer digests]|None for indexes) — parse errors -> _Err."""
    try:
        man = json.loads(body.decode("utf-8"))
    except Exception:
        raise _Err("InvalidParameterException", "Invalid parameter at 'imageManifest' failed to satisfy constraint: not valid JSON")
    if not isinstance(man, dict):
        raise _Err("InvalidParameterException", "Invalid parameter at 'imageManifest' failed to satisfy constraint: not an object")
    mt = man.get("mediaType") or ("application/vnd.oci.image.manifest.v1+json" if man.get("config") else "")
    if mt in _INDEX_TYPES or "manifests" in man:
        return mt or _INDEX_TYPES[0], None, None
    cfg = (man.get("config") or {}).get("digest")
    layers = [l.get("digest") for l in man.get("layers") or []]
    if not cfg:
        raise _Err("ImageInvalidException", "Invalid image manifest: missing config")
    return mt, cfg, layers


def _image_size(st, body: bytes) -> int:
    try:
        man = json.loads(body.decode())
        return sum(int(l.get("size") or st["blobs"].get(l.get("digest"), 0)) for l in man.get("layers") or [])
    except Exception:
        return len(body)


def _tag_ok(tag):
    if not _TAG_RE.match(tag or ""):
        raise _Err("InvalidParameterException", f"Invalid parameter at 'imageTag' failed to satisfy constraint: '{tag}'")


def _put_manifest(store, st, region, repo, body: bytes, tag, media_type=None, via_registry=False):
    mt, cfg, layers = _manifest_refs(body)
    media_type = media_type or mt
    if layers is not None:
        missing = [d for d in ([cfg] + layers) if d not in st["blobs"] or d not in repo["layers"]]
        if missing:
            raise _Err("LayersNotFoundException", f"Layer(s) not found: {', '.join(sorted(set(missing)))}")
    digest = _sha(body)
    if tag:
        _tag_ok(tag)
        cur = repo["tags"].get(tag)
        if cur and cur != digest and repo["mutability"] == "IMMUTABLE":
            raise _Err("ImageTagAlreadyExistsException",
                       f"The image tag '{tag}' already exists in the '{repo['name']}' repository and cannot be overwritten because the repository is immutable.")
        if cur == digest:
            raise _Err("ImageAlreadyExistsException",
                       f"Image with digest '{digest}' and tag '{tag}' already exists in the repository with name '{repo['name']}' in registry with id '{ACCOUNT}'")
    img = repo["images"].get(digest)
    if not img:
        _s3_put(store, f"manifests/{digest.split(':')[1]}", body)
        img = repo["images"][digest] = {"digest": digest, "mediaType": media_type, "size": _image_size(st, body),
                                        "pushedAt": _now(), "lastPull": None, "scan": None, "isIndex": layers is None}
    if tag:
        old = repo["tags"].get(tag)
        repo["tags"][tag] = digest
        if old and old != digest:
            _maybe_drop_untagged_ref(repo, old)
    _after_push(store, st, region, repo, digest, tag)
    return digest


def _maybe_drop_untagged_ref(repo, digest):   # an overwritten tag leaves the old image untagged (kept, as in ECR)
    return


def _tags_of(repo, digest):
    return sorted(t for t, d in repo["tags"].items() if d == digest)


def _image_id(repo, digest, tag=None):
    d = {"imageDigest": digest}
    if tag:
        d["imageTag"] = tag
    return d


def _delete_image(store, repo, digest):
    repo["images"].pop(digest, None)
    for t in [t for t, d in repo["tags"].items() if d == digest]:
        repo["tags"].pop(t)
    if not any(i for r2 in [repo] for i in r2["images"]):
        pass
    # manifest object is dropped only when no repository in any region still references it
    st = store.account.get("ecr") or {}
    still = any(digest in r["images"] for reg in st.get("regions", {}).values() for r in reg.values())
    if not still:
        _s3_del(store, f"manifests/{digest.split(':')[1]}")


def _resolve(repo, iid):
    if iid.get("imageDigest"):
        d = iid["imageDigest"]
        if d not in repo["images"]:
            return None
        if iid.get("imageTag") and repo["tags"].get(iid["imageTag"]) != d:
            return None
        return d
    if iid.get("imageTag"):
        return repo["tags"].get(iid["imageTag"])
    return None


# ── scanning ──────────────────────────────────────────────────────────────────────────
def _scan_mode(st, repo):
    """(scan_type, frequency) the registry config + repo flag say applies to this repo."""
    cfg = st["scanning"]
    if cfg.get("scanType") == "ENHANCED":
        for rule in cfg.get("rules") or []:
            for f in rule.get("repositoryFilters") or []:
                if fnmatch.fnmatchcase(repo["name"], f.get("filter", "")) or f.get("filter") == "*":
                    return "ENHANCED", rule.get("scanFrequency", "SCAN_ON_PUSH")
        return "ENHANCED", "MANUAL"
    return "BASIC", ("SCAN_ON_PUSH" if repo["scanOnPush"] else "MANUAL")


def _config_blob(store, st, repo, digest):
    body = _s3_get(store, f"manifests/{digest.split(':')[1]}")
    if body is None:
        return None
    try:
        cfgd = (json.loads(body.decode()).get("config") or {}).get("digest")
    except Exception:
        return None
    blob = _s3_get(store, f"blobs/{cfgd.split(':')[1]}") if cfgd else None
    try:
        return json.loads(blob.decode()) if blob else None
    except Exception:
        return None


def _run_scan(store, st, repo, digest, kind, trivy_report=None):
    img = repo["images"][digest]
    tag = (_tags_of(repo, digest) or [""])[0]
    cfg = _config_blob(store, st, repo, digest)
    res = _vs().scan_image(cfg, repo["name"], tag, trivy_report)
    now = _now()
    counts = {}
    for f in res["findings"]:
        k = (_SEV_BASIC if kind == "BASIC" else _SEV_INSPECTOR).get(f["severity"], "UNDEFINED")
        counts[k] = counts.get(k, 0) + 1
    first = (img.get("scan") or {}).get("firstObservedAt", now)
    img["scan"] = {"kind": kind, "completedAt": now, "firstObservedAt": first, "result": res, "counts": counts,
                   "engine": res.get("engine"), "snapshot": res.get("advisorySnapshot")}


def _after_push(store, st, region, repo, digest, tag):
    img = repo["images"][digest]
    if not img.get("isIndex"):
        kind, freq = _scan_mode(st, repo)
        if freq in ("SCAN_ON_PUSH", "CONTINUOUS_SCAN"):
            _run_scan(store, st, repo, digest, kind)
    _replicate(store, st, region, repo, digest, tag)


def _enhanced_findings(repo, region, digest, scan):
    out = []
    img_arn = f"arn:aws:ecr:{region}:{ACCOUNT}:repository/{repo['name']}/{digest}"
    for f in scan["result"]["findings"]:
        fid = _vs().finding_id(digest, f["vulnerabilityId"], f["package"])
        out.append({
            "awsAccountId": ACCOUNT, "description": f["title"], "findingArn": f"arn:aws:inspector2:{region}:{ACCOUNT}:finding/{fid}",
            "firstObservedAt": scan["firstObservedAt"], "lastObservedAt": scan["completedAt"], "updatedAt": scan["completedAt"],
            "inspectorScore": f["cvss"], "inspectorScoreDetails": {"adjustedCvss": {"score": f["cvss"], "scoreSource": f["vulnerabilityId"], "scoringVector": ""}},
            "packageVulnerabilityDetails": {
                "vulnerabilityId": f["vulnerabilityId"], "source": "NVD" if f["source"] != "trivy" else "TRIVY",
                "sourceUrl": f"https://nvd.nist.gov/vuln/detail/{f['vulnerabilityId']}",
                "cvss": [{"baseScore": f["cvss"], "scoringVector": "", "source": "NVD", "version": "3.1"}],
                "vulnerablePackages": [{"name": f["package"], "version": f["installedVersion"], "fixedInVersion": f["fixedVersion"] or "",
                                        "packageManager": {"pypi": "PYTHONPKG", "npm": "NODEPKG", "maven": "JAR"}.get(f["ecosystem"], "OS"),
                                        "remediation": f"Upgrade {f['package']} to {f['fixedVersion']}" if f["fixedVersion"] else "No fix available"}],
                "referenceUrls": [], "relatedVulnerabilities": []},
            "remediation": {"recommendation": {"text": f"Upgrade {f['package']} to {f['fixedVersion']}" if f["fixedVersion"] else "No fixed version available"}},
            "resources": [{"id": img_arn, "type": "AWS_ECR_CONTAINER_IMAGE", "region": region, "partition": "aws",
                           "details": {"awsEcrContainerImage": {"repositoryName": repo["name"], "imageHash": digest,
                                                                "imageTags": _tags_of(repo, digest), "registry": ACCOUNT,
                                                                "pushedAt": repo["images"][digest]["pushedAt"]}}}],
            "severity": _SEV_INSPECTOR.get(f["severity"], "UNTRIAGED"), "status": "ACTIVE", "title": f"{f['vulnerabilityId']} - {f['package']}",
            "type": "PACKAGE_VULNERABILITY", "fixAvailable": "YES" if f["fixedVersion"] else "NO", "exploitAvailable": "NO"})
    return out


def _basic_findings(scan):
    out = []
    for f in scan["result"]["findings"]:
        out.append({"name": f["vulnerabilityId"], "description": f["title"], "uri": f"https://nvd.nist.gov/vuln/detail/{f['vulnerabilityId']}",
                    "severity": _SEV_BASIC.get(f["severity"], "UNDEFINED"),
                    "attributes": [{"key": "package_name", "value": f["package"]}, {"key": "package_version", "value": f["installedVersion"]},
                                   {"key": "CVSS3_SCORE", "value": str(f["cvss"])}] + ([{"key": "fixed_in_version", "value": f["fixedVersion"]}] if f["fixedVersion"] else [])})
    return out


# ── replication ───────────────────────────────────────────────────────────────────────
def _replicate(store, st, region, repo, digest, tag):
    img = repo["images"][digest]
    img["replication"] = []
    for rule in st["replication"].get("rules") or []:
        filters = rule.get("repositoryFilters") or []
        if filters and not any(repo["name"].startswith(f["filter"]) for f in filters):
            continue
        for d in rule.get("destinations") or []:
            dreg, drid = d.get("region"), d.get("registryId") or ACCOUNT
            if drid != ACCOUNT:
                img["replication"].append({"region": dreg, "registryId": drid, "status": "FAILED", "failureCode": "REPLICATION_NOT_SUPPORTED"})
                continue
            if dreg == region:
                continue
            drepos = _repos(st, dreg)
            dr = drepos.setdefault(repo["name"], _new_repo(repo["name"], repo["mutability"], repo["scanOnPush"], repo["encryption"]))
            for ld in repo["layers"]:
                if ld not in dr["layers"]:
                    dr["layers"].append(ld)
            if digest not in dr["images"]:
                dr["images"][digest] = {k: v for k, v in img.items() if k not in ("scan", "replication")}
                dr["images"][digest]["scan"] = None
            if tag:
                dr["tags"][tag] = digest
            img["replication"].append({"region": dreg, "registryId": ACCOUNT, "status": "COMPLETE"})


# ── lifecycle ─────────────────────────────────────────────────────────────────────────
def _validate_lifecycle(text):
    try:
        doc = json.loads(text)
    except Exception:
        raise _Err("InvalidParameterException", "Invalid parameter at 'LifecyclePolicyText' failed to satisfy constraint: Invalid JSON")
    rules = doc.get("rules") if isinstance(doc, dict) else None
    if not isinstance(rules, list) or not rules:
        raise _Err("InvalidParameterException", "Invalid parameter at 'LifecyclePolicyText' failed to satisfy constraint: Lifecycle policy validation failure: \"rules\" is required")
    prios = set()
    any_prio, max_prio = None, 0
    for r in rules:
        pr = r.get("rulePriority")
        if not isinstance(pr, int) or pr < 1:
            raise _Err("InvalidParameterException", "Invalid parameter at 'LifecyclePolicyText' failed to satisfy constraint: Lifecycle policy validation failure: rulePriority must be a positive integer")
        if pr in prios:
            raise _Err("InvalidParameterException", f"Invalid parameter at 'LifecyclePolicyText' failed to satisfy constraint: Lifecycle policy validation failure: duplicate rulePriority {pr}")
        prios.add(pr)
        max_prio = max(max_prio, pr)
        sel = r.get("selection") or {}
        ts = sel.get("tagStatus")
        if ts not in ("tagged", "untagged", "any"):
            raise _Err("InvalidParameterException", "Invalid parameter at 'LifecyclePolicyText' failed to satisfy constraint: Lifecycle policy validation failure: tagStatus must be tagged, untagged or any")
        if ts == "tagged" and not (sel.get("tagPrefixList") or sel.get("tagPatternList")):
            raise _Err("InvalidParameterException", "Invalid parameter at 'LifecyclePolicyText' failed to satisfy constraint: Lifecycle policy validation failure: tagPrefixList or tagPatternList is required when tagStatus is tagged")
        ct = sel.get("countType")
        if ct not in ("imageCountMoreThan", "sinceImagePushed"):
            raise _Err("InvalidParameterException", "Invalid parameter at 'LifecyclePolicyText' failed to satisfy constraint: Lifecycle policy validation failure: countType must be imageCountMoreThan or sinceImagePushed")
        if not isinstance(sel.get("countNumber"), int) or sel["countNumber"] < 1:
            raise _Err("InvalidParameterException", "Invalid parameter at 'LifecyclePolicyText' failed to satisfy constraint: Lifecycle policy validation failure: countNumber must be a positive integer")
        if ct == "sinceImagePushed" and sel.get("countUnit") != "days":
            raise _Err("InvalidParameterException", "Invalid parameter at 'LifecyclePolicyText' failed to satisfy constraint: Lifecycle policy validation failure: countUnit must be days for sinceImagePushed")
        if (r.get("action") or {}).get("type") != "expire":
            raise _Err("InvalidParameterException", "Invalid parameter at 'LifecyclePolicyText' failed to satisfy constraint: Lifecycle policy validation failure: action type must be expire")
        if ts == "any":
            any_prio = pr
    if any_prio is not None and any_prio != max_prio:
        raise _Err("InvalidParameterException", "Invalid parameter at 'LifecyclePolicyText' failed to satisfy constraint: Lifecycle policy validation failure: a rule with tagStatus any must have the highest rulePriority")
    return doc


def _match_tags(sel, tags):
    ts = sel["tagStatus"]
    if ts == "any":
        return True
    if ts == "untagged":
        return not tags
    if not tags:
        return False
    pats = sel.get("tagPatternList")
    if pats:
        return any(fnmatch.fnmatchcase(t, p) for t in tags for p in pats)
    return any(t.startswith(p) for t in tags for p in sel.get("tagPrefixList") or [])


def _lifecycle_eval(repo, doc, now=None):
    now = now or _now()
    expired = {}
    for rule in sorted(doc["rules"], key=lambda r: r["rulePriority"]):
        sel = rule["selection"]
        cand = [(i["pushedAt"], d) for d, i in repo["images"].items()
                if d not in expired and _match_tags(sel, _tags_of(repo, d))]
        cand.sort(reverse=True)
        if sel["countType"] == "imageCountMoreThan":
            victims = cand[sel["countNumber"]:]
        else:
            cutoff = now - sel["countNumber"] * 86400
            victims = [c for c in cand if c[0] < cutoff]
        for _, d in victims:
            expired[d] = rule["rulePriority"]
    return expired


def lifecycle_tick(store, now=None) -> int:
    """Run every repository's lifecycle policy for real (ECR evaluates asynchronously, ~daily). Returns images expired."""
    st = _st(store)
    n = 0
    for region, repos in st["regions"].items():
        for repo in repos.values():
            if not repo.get("lifecycle"):
                continue
            doc = json.loads(repo["lifecycle"]["text"])
            for d, prio in _lifecycle_eval(repo, doc, now).items():
                st["lifecycleLog"].append({"repository": repo["name"], "region": region, "imageDigest": d,
                                           "tags": _tags_of(repo, d), "rulePriority": prio, "expiredAt": _now()})
                _delete_image(store, repo, d)
                n += 1
            repo["lifecycle"]["lastEvaluatedAt"] = _now()
    del st["lifecycleLog"][:-500]
    return n


def rescan_continuous(store) -> int:
    """CONTINUOUS_SCAN (Inspector enhanced) rescans every matching image against the current advisory snapshot."""
    st = _st(store)
    n = 0
    for repos in st["regions"].values():
        for repo in repos.values():
            kind, freq = _scan_mode(st, repo)
            if freq == "CONTINUOUS_SCAN":
                for d, img in repo["images"].items():
                    if not img.get("isIndex"):
                        _run_scan(store, st, repo, d, kind)
                        n += 1
    return n


# ── JSON API ──────────────────────────────────────────────────────────────────────────
def _page(items, p, key="nextToken", limit_key="maxResults", default=100):
    start = int(p.get(key) or 0) if str(p.get(key) or "0").isdigit() else 0
    lim = int(p.get(limit_key) or default)
    page = items[start:start + lim]
    nxt = str(start + lim) if start + lim < len(items) else None
    return page, nxt


def op_CreateRepository(store, st, region, p):
    _chk_registry(p)
    name = p.get("repositoryName") or ""
    if not (2 <= len(name) <= 256) or not _NAME_RE.match(name):
        raise _Err("InvalidParameterException", f"Invalid parameter at 'repositoryName' failed to satisfy constraint: '{name}'")
    if p.get("imageTagMutability", "MUTABLE") not in ("MUTABLE", "IMMUTABLE"):
        raise _Err("InvalidParameterException", "Invalid parameter at 'imageTagMutability' failed to satisfy constraint")
    enc = p.get("encryptionConfiguration") or {"encryptionType": "AES256"}
    if enc.get("encryptionType") not in ("AES256", "KMS"):
        raise _Err("InvalidParameterException", "Invalid parameter at 'encryptionConfiguration.encryptionType' failed to satisfy constraint")
    if name in _repos(st, region):
        raise _Err("RepositoryAlreadyExistsException",
                   f"The repository with name '{name}' already exists in the registry with id '{ACCOUNT}'")
    r = _new_repo(name, p.get("imageTagMutability", "MUTABLE"), bool((p.get("imageScanningConfiguration") or {}).get("scanOnPush")), enc)
    r["tags_res"] = {t["Key"]: t.get("Value", "") for t in p.get("tags") or []}
    _repos(st, region)[name] = r
    return {"repository": _repo_view(r, region)}


def _new_repo(name, mutability, scan_on_push, enc):
    return {"name": name, "createdAt": _now(), "mutability": mutability, "scanOnPush": scan_on_push,
            "encryption": enc or {"encryptionType": "AES256"}, "policy": None, "lifecycle": None, "layers": [],
            "images": {}, "tags": {}, "tags_res": {}, "preview": None}


def op_DescribeRepositories(store, st, region, p):
    _chk_registry(p)
    repos = _repos(st, region)
    names = p.get("repositoryNames")
    if names:
        for n in names:
            if n not in repos:
                raise _Err("RepositoryNotFoundException", f"The repository with name '{n}' does not exist in the registry with id '{ACCOUNT}'")
        sel = [repos[n] for n in names]
    else:
        sel = [repos[n] for n in sorted(repos)]
    page, nxt = _page(sel, p)
    out = {"repositories": [_repo_view(r, region) for r in page]}
    if nxt:
        out["nextToken"] = nxt
    return out


def op_DeleteRepository(store, st, region, p):
    r = _get_repo(st, region, p)
    if r["images"] and not p.get("force"):
        raise _Err("RepositoryNotEmptyException",
                   f"The repository with name '{r['name']}' in registry with id '{ACCOUNT}' cannot be deleted because it still contains images")
    for d in list(r["images"]):
        _delete_image(store, r, d)
    del _repos(st, region)[r["name"]]
    return {"repository": _repo_view(r, region)}


def op_PutImage(store, st, region, p):
    r = _get_repo(st, region, p)
    body = (p.get("imageManifest") or "").encode()
    if not body:
        raise _Err("InvalidParameterException", "Missing required parameter: imageManifest")
    digest = _put_manifest(store, st, region, r, body, p.get("imageTag"), p.get("imageManifestMediaType"))
    if p.get("imageDigest") and p["imageDigest"] != digest:
        raise _Err("InvalidParameterException", "imageDigest does not match the manifest")
    return {"image": {"registryId": ACCOUNT, "repositoryName": r["name"], "imageId": _image_id(r, digest, p.get("imageTag")),
                      "imageManifest": body.decode(), "imageManifestMediaType": r["images"][digest]["mediaType"]}}


def op_BatchGetImage(store, st, region, p):
    r = _get_repo(st, region, p)
    imgs, fails = [], []
    for iid in p.get("imageIds") or []:
        d = _resolve(r, iid)
        if not d:
            fails.append({"imageId": iid, "failureCode": "ImageNotFound",
                          "failureReason": "Requested image not found"})
            continue
        body = _s3_get(store, f"manifests/{d.split(':')[1]}") or b""
        r["images"][d]["lastPull"] = _now()
        imgs.append({"registryId": ACCOUNT, "repositoryName": r["name"], "imageId": _image_id(r, d, iid.get("imageTag")),
                     "imageManifest": body.decode(), "imageManifestMediaType": r["images"][d]["mediaType"]})
    return {"images": imgs, "failures": fails}


def op_BatchDeleteImage(store, st, region, p):
    r = _get_repo(st, region, p)
    ok, fails = [], []
    ids = p.get("imageIds") or []
    if not ids:
        raise _Err("InvalidParameterException", "Invalid parameter at 'imageIds' failed to satisfy constraint: Member must have length greater than or equal to 1")
    for iid in ids:
        d = _resolve(r, iid)
        if not d:
            fails.append({"imageId": iid, "failureCode": "ImageNotFound", "failureReason": "Requested image not found"})
            continue
        if iid.get("imageTag") and not iid.get("imageDigest"):
            r["tags"].pop(iid["imageTag"], None)
            if not _tags_of(r, d):
                _delete_image(store, r, d)
            ok.append({"imageDigest": d, "imageTag": iid["imageTag"]})
        else:
            tags = _tags_of(r, d)
            _delete_image(store, r, d)
            ok.extend([{"imageDigest": d, "imageTag": t} for t in tags] or [{"imageDigest": d}])
    return {"imageIds": ok, "failures": fails}


def op_ListImages(store, st, region, p):
    r = _get_repo(st, region, p)
    ts = (p.get("filter") or {}).get("tagStatus")
    if ts not in (None, "TAGGED", "UNTAGGED", "ANY"):
        raise _Err("InvalidParameterException", "Invalid parameter at 'filter.tagStatus' failed to satisfy constraint")
    ids = []
    for d in sorted(r["images"], key=lambda x: r["images"][x]["pushedAt"]):
        tags = _tags_of(r, d)
        if tags and ts != "UNTAGGED":
            ids.extend({"imageDigest": d, "imageTag": t} for t in tags)
        elif not tags and ts != "TAGGED":
            ids.append({"imageDigest": d})
    page, nxt = _page(ids, p)
    out = {"imageIds": page}
    if nxt:
        out["nextToken"] = nxt
    return out


def _scan_status(img):
    s = img.get("scan")
    if not s:
        return None
    return {"status": "COMPLETE", "description": "The scan was completed successfully."}


def op_DescribeImages(store, st, region, p):
    r = _get_repo(st, region, p)
    if p.get("imageIds"):
        digs = []
        for iid in p["imageIds"]:
            d = _resolve(r, iid)
            if not d:
                raise _Err("ImageNotFoundException", f"The image with imageId {json.dumps(iid)} does not exist within the repository with name '{r['name']}' in the registry with id '{ACCOUNT}'")
            digs.append(d)
    else:
        digs = sorted(r["images"], key=lambda x: r["images"][x]["pushedAt"])
    ts = (p.get("filter") or {}).get("tagStatus")
    out = []
    for d in digs:
        img, tags = r["images"][d], _tags_of(r, d)
        if (ts == "TAGGED" and not tags) or (ts == "UNTAGGED" and tags):
            continue
        row = {"registryId": ACCOUNT, "repositoryName": r["name"], "imageDigest": d, "imageTags": tags, "imageSizeInBytes": img["size"],
               "imagePushedAt": img["pushedAt"], "imageManifestMediaType": img["mediaType"]}
        if img.get("lastPull"):
            row["lastRecordedPullTime"] = img["lastPull"]
        if img.get("scan"):
            row["imageScanStatus"] = _scan_status(img)
            row["imageScanFindingsSummary"] = {"imageScanCompletedAt": img["scan"]["completedAt"],
                                               "vulnerabilitySourceUpdatedAt": img["scan"]["completedAt"],
                                               "findingSeverityCounts": img["scan"]["counts"]}
        out.append(row)
    page, nxt = _page(out, p)
    res = {"imageDetails": page}
    if nxt:
        res["nextToken"] = nxt
    return res


def op_StartImageScan(store, st, region, p):
    r = _get_repo(st, region, p)
    iid = p.get("imageId") or {}
    d = _resolve(r, iid)
    if not d:
        raise _Err("ImageNotFoundException", f"The image with imageId {json.dumps(iid)} does not exist within the repository with name '{r['name']}' in the registry with id '{ACCOUNT}'")
    if r["images"][d].get("isIndex"):
        raise _Err("UnsupportedImageTypeException", "The image is unsupported for image scanning (multi-architecture index)")
    kind, _ = _scan_mode(st, r)
    _run_scan(store, st, r, d, kind)
    return {"registryId": ACCOUNT, "repositoryName": r["name"], "imageId": iid, "imageScanStatus": _scan_status(r["images"][d])}


def op_DescribeImageScanFindings(store, st, region, p):
    r = _get_repo(st, region, p)
    iid = p.get("imageId") or {}
    d = _resolve(r, iid)
    if not d:
        raise _Err("ImageNotFoundException", f"The image with imageId {json.dumps(iid)} does not exist within the repository with name '{r['name']}' in the registry with id '{ACCOUNT}'")
    scan = r["images"][d].get("scan")
    if not scan:
        raise _Err("ScanNotFoundException", f"Image scan does not exist for the image with '{json.dumps(iid)}' in the repository with name '{r['name']}' in the registry with id '{ACCOUNT}'")
    out = {"registryId": ACCOUNT, "repositoryName": r["name"], "imageId": {"imageDigest": d, **({"imageTag": iid["imageTag"]} if iid.get("imageTag") else {})},
           "imageScanStatus": _scan_status(r["images"][d])}
    if scan["kind"] == "ENHANCED":
        ef = _enhanced_findings(r, region, d, scan)
        page, nxt = _page(ef, p)
        out["imageScanFindings"] = {"imageScanCompletedAt": scan["completedAt"], "vulnerabilitySourceUpdatedAt": scan["completedAt"],
                                    "findingSeverityCounts": scan["counts"], "enhancedFindings": page}
    else:
        bf = _basic_findings(scan)
        page, nxt = _page(bf, p)
        out["imageScanFindings"] = {"imageScanCompletedAt": scan["completedAt"], "vulnerabilitySourceUpdatedAt": scan["completedAt"],
                                    "findingSeverityCounts": scan["counts"], "findings": page}
    if nxt:
        out["nextToken"] = nxt
    out["imageScanFindings"]["engine"] = scan.get("engine")
    return out


def op_PutImageScanningConfiguration(store, st, region, p):
    r = _get_repo(st, region, p)
    if "scanOnPush" not in (p.get("imageScanningConfiguration") or {}):
        raise _Err("InvalidParameterException", "Missing required parameter: imageScanningConfiguration.scanOnPush")
    r["scanOnPush"] = bool(p["imageScanningConfiguration"]["scanOnPush"])
    return {"registryId": ACCOUNT, "repositoryName": r["name"], "imageScanningConfiguration": {"scanOnPush": r["scanOnPush"]}}


def op_PutImageTagMutability(store, st, region, p):
    r = _get_repo(st, region, p)
    if p.get("imageTagMutability") not in ("MUTABLE", "IMMUTABLE"):
        raise _Err("InvalidParameterException", "Invalid parameter at 'imageTagMutability' failed to satisfy constraint")
    r["mutability"] = p["imageTagMutability"]
    return {"registryId": ACCOUNT, "repositoryName": r["name"], "imageTagMutability": r["mutability"]}


def op_SetRepositoryPolicy(store, st, region, p):
    r = _get_repo(st, region, p)
    try:
        doc = json.loads(p.get("policyText") or "")
        assert isinstance(doc, dict) and doc.get("Statement")
    except Exception:
        raise _Err("InvalidParameterException", "Invalid repository policy provided")
    r["policy"] = p["policyText"]
    return {"registryId": ACCOUNT, "repositoryName": r["name"], "policyText": r["policy"]}


def op_GetRepositoryPolicy(store, st, region, p):
    r = _get_repo(st, region, p)
    if not r["policy"]:
        raise _Err("RepositoryPolicyNotFoundException", f"Repository policy does not exist for the repository with name '{r['name']}' in the registry with id '{ACCOUNT}'")
    return {"registryId": ACCOUNT, "repositoryName": r["name"], "policyText": r["policy"]}


def op_DeleteRepositoryPolicy(store, st, region, p):
    r = _get_repo(st, region, p)
    if not r["policy"]:
        raise _Err("RepositoryPolicyNotFoundException", f"Repository policy does not exist for the repository with name '{r['name']}' in the registry with id '{ACCOUNT}'")
    text, r["policy"] = r["policy"], None
    return {"registryId": ACCOUNT, "repositoryName": r["name"], "policyText": text}


def op_PutLifecyclePolicy(store, st, region, p):
    r = _get_repo(st, region, p)
    _validate_lifecycle(p.get("lifecyclePolicyText") or "")
    r["lifecycle"] = {"text": p["lifecyclePolicyText"], "lastEvaluatedAt": None}
    return {"registryId": ACCOUNT, "repositoryName": r["name"], "lifecyclePolicyText": p["lifecyclePolicyText"]}


def op_GetLifecyclePolicy(store, st, region, p):
    r = _get_repo(st, region, p)
    if not r["lifecycle"]:
        raise _Err("LifecyclePolicyNotFoundException", f"Lifecycle policy does not exist for the repository with name '{r['name']}' in the registry with id '{ACCOUNT}'")
    out = {"registryId": ACCOUNT, "repositoryName": r["name"], "lifecyclePolicyText": r["lifecycle"]["text"]}
    if r["lifecycle"]["lastEvaluatedAt"]:
        out["lastEvaluatedAt"] = r["lifecycle"]["lastEvaluatedAt"]
    return out


def op_DeleteLifecyclePolicy(store, st, region, p):
    r = _get_repo(st, region, p)
    if not r["lifecycle"]:
        raise _Err("LifecyclePolicyNotFoundException", f"Lifecycle policy does not exist for the repository with name '{r['name']}' in the registry with id '{ACCOUNT}'")
    text, r["lifecycle"] = r["lifecycle"]["text"], None
    return {"registryId": ACCOUNT, "repositoryName": r["name"], "lifecyclePolicyText": text}


def op_StartLifecyclePolicyPreview(store, st, region, p):
    r = _get_repo(st, region, p)
    text = p.get("lifecyclePolicyText") or (r["lifecycle"] or {}).get("text")
    if not text:
        raise _Err("LifecyclePolicyNotFoundException", f"Lifecycle policy does not exist for the repository with name '{r['name']}' in the registry with id '{ACCOUNT}'")
    doc = _validate_lifecycle(text)
    if r["preview"] and r["preview"].get("status") == "IN_PROGRESS":
        raise _Err("LifecyclePolicyPreviewInProgressException", "The previous lifecycle policy preview request is still in progress")
    res = []
    for d, prio in sorted(_lifecycle_eval(r, doc).items(), key=lambda x: r["images"][x[0]]["pushedAt"]):
        row = {"imageDigest": d, "imagePushedAt": r["images"][d]["pushedAt"], "action": {"type": "EXPIRE"}, "appliedRulePriority": prio}
        if _tags_of(r, d):
            row["imageTags"] = _tags_of(r, d)
        res.append(row)
    r["preview"] = {"status": "COMPLETE", "text": text, "results": res}
    return {"registryId": ACCOUNT, "repositoryName": r["name"], "lifecyclePolicyText": text, "status": "IN_PROGRESS"}


def op_GetLifecyclePolicyPreview(store, st, region, p):
    r = _get_repo(st, region, p)
    if not r["preview"]:
        raise _Err("LifecyclePolicyPreviewNotFoundException", f"Lifecycle policy preview does not exist for the repository with name '{r['name']}' in the registry with id '{ACCOUNT}'")
    pv = r["preview"]
    page, nxt = _page(pv["results"], p)
    out = {"registryId": ACCOUNT, "repositoryName": r["name"], "lifecyclePolicyText": pv["text"], "status": pv["status"],
           "previewResults": page, "summary": {"expiringImageTotalCount": len(pv["results"])}}
    if nxt:
        out["nextToken"] = nxt
    return out


def op_GetAuthorizationToken(store, st, region, p):
    pw = hashlib.sha256(f"{uuid.uuid4()}".encode()).hexdigest() + hashlib.sha256(f"{time.time()}".encode()).hexdigest()[:24]
    now = _now()
    st["tokens"] = {k: v for k, v in st["tokens"].items() if v > now}
    if len(st["tokens"]) > 100:
        st["tokens"] = dict(sorted(st["tokens"].items(), key=lambda kv: kv[1])[-50:])
    st["tokens"][hashlib.sha256(pw.encode()).hexdigest()] = now + _TOKEN_TTL
    tok = base64.b64encode(f"AWS:{pw}".encode()).decode()
    return {"authorizationData": [{"authorizationToken": tok, "expiresAt": now + _TOKEN_TTL,
                                   "proxyEndpoint": f"https://{ACCOUNT}.dkr.ecr.{region}.amazonaws.com"}]}


def op_InitiateLayerUpload(store, st, region, p):
    r = _get_repo(st, region, p)
    uid = str(uuid.uuid4())
    st["uploads"][uid] = {"repo": r["name"], "region": region, "size": 0}
    _s3_put(store, f"uploads/{uid}", b"")
    return {"uploadId": uid, "partSize": 10485760}


def _upload(st, p):
    u = st["uploads"].get(p.get("uploadId") or "")
    if not u:
        raise _Err("UploadNotFoundException", f"The upload with upload id '{p.get('uploadId')}' does not exist in the repository with name '{p.get('repositoryName')}' in the registry with id '{ACCOUNT}'")
    return u


def op_UploadLayerPart(store, st, region, p):
    r = _get_repo(st, region, p)
    u = _upload(st, p)
    try:
        part = base64.b64decode(p.get("layerPartBlob") or "")
    except Exception:
        raise _Err("InvalidLayerPartException", "layerPartBlob is not valid base64")
    first, last = p.get("partFirstByte"), p.get("partLastByte")
    if first != u["size"] or last is None or last - first + 1 != len(part):
        raise _Err("InvalidLayerPartException", f"Invalid layer part: expected first byte {u['size']}", 400)
    cur = _s3_get(store, f"uploads/{p['uploadId']}") or b""
    _s3_put(store, f"uploads/{p['uploadId']}", cur + part)
    u["size"] += len(part)
    return {"registryId": ACCOUNT, "repositoryName": r["name"], "uploadId": p["uploadId"], "lastByteReceived": u["size"] - 1}


def _finish_blob(store, st, repo, data: bytes, digest):
    if _sha(data) != digest:
        raise _Err("InvalidLayerException", f"The computed digest of the layer does not match the provided digest {digest}")
    if digest not in st["blobs"]:
        _s3_put(store, f"blobs/{digest.split(':')[1]}", data)
        st["blobs"][digest] = len(data)
    if digest not in repo["layers"]:
        repo["layers"].append(digest)


def op_CompleteLayerUpload(store, st, region, p):
    r = _get_repo(st, region, p)
    u = _upload(st, p)
    digs = p.get("layerDigests") or []
    if len(digs) != 1:
        raise _Err("InvalidParameterException", "layerDigests must contain exactly one digest")
    data = _s3_get(store, f"uploads/{p['uploadId']}") or b""
    _finish_blob(store, st, r, data, digs[0])
    _s3_del(store, f"uploads/{p['uploadId']}")
    st["uploads"].pop(p["uploadId"], None)
    return {"registryId": ACCOUNT, "repositoryName": r["name"], "uploadId": p["uploadId"], "layerDigest": digs[0]}


def op_BatchCheckLayerAvailability(store, st, region, p):
    r = _get_repo(st, region, p)
    layers, fails = [], []
    for d in p.get("layerDigests") or []:
        if not _DIGEST_RE.match(d):
            fails.append({"layerDigest": d, "failureCode": "InvalidLayerDigest", "failureReason": "Invalid digest"})
        elif d in r["layers"] and d in st["blobs"]:
            layers.append({"layerDigest": d, "layerAvailability": "AVAILABLE", "layerSize": st["blobs"][d],
                           "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip"})
        else:
            layers.append({"layerDigest": d, "layerAvailability": "UNAVAILABLE"})
    return {"layers": layers, "failures": fails}


def op_GetDownloadUrlForLayer(store, st, region, p):
    r = _get_repo(st, region, p)
    d = p.get("layerDigest") or ""
    if d not in r["layers"]:
        raise _Err("LayersNotFoundException", f"Layer not found: {d}")
    return {"downloadUrl": f"https://{ACCOUNT}.dkr.ecr.{region}.amazonaws.com/v2/{r['name']}/blobs/{d}", "layerDigest": d}


def op_PutReplicationConfiguration(store, st, region, p):
    cfg = p.get("replicationConfiguration") or {}
    rules = cfg.get("rules")
    if rules is None or len(rules) > 10:
        raise _Err("InvalidParameterException", "Invalid parameter at 'replicationConfiguration.rules' failed to satisfy constraint: at most 10 rules")
    for r in rules:
        ds = r.get("destinations") or []
        if not ds or len(ds) > 25:
            raise _Err("InvalidParameterException", "Invalid parameter at 'replicationConfiguration.rules.destinations' failed to satisfy constraint: 1 to 25 destinations")
        for d in ds:
            if not d.get("region") or not d.get("registryId"):
                raise _Err("InvalidParameterException", "Each destination needs region and registryId")
        for f in r.get("repositoryFilters") or []:
            if f.get("filterType") != "PREFIX_MATCH" or not f.get("filter"):
                raise _Err("InvalidParameterException", "repositoryFilters need filterType PREFIX_MATCH and a filter")
    st["replication"] = {"rules": rules}
    return {"replicationConfiguration": {"rules": rules}}


def op_DescribeRegistry(store, st, region, p):
    return {"registryId": ACCOUNT, "replicationConfiguration": {"rules": st["replication"]["rules"]}}


def op_DescribeImageReplicationStatus(store, st, region, p):
    r = _get_repo(st, region, p)
    d = _resolve(r, p.get("imageId") or {})
    if not d:
        raise _Err("ImageNotFoundException", "The image does not exist within the repository")
    rep = r["images"][d].get("replication")
    if rep is None:
        raise _Err("ReplicationConfigurationNotFoundException", "The replication configuration was not found")
    return {"repositoryName": r["name"], "imageId": {"imageDigest": d}, "replicationStatuses": rep}


def op_PutRegistryPolicy(store, st, region, p):
    try:
        assert isinstance(json.loads(p.get("policyText") or ""), dict)
    except Exception:
        raise _Err("InvalidParameterException", "Invalid registry policy provided")
    st["registryPolicy"] = p["policyText"]
    return {"registryId": ACCOUNT, "policyText": p["policyText"]}


def op_GetRegistryPolicy(store, st, region, p):
    if not st["registryPolicy"]:
        raise _Err("RegistryPolicyNotFoundException", f"Registry policy does not exist in the registry with id '{ACCOUNT}'")
    return {"registryId": ACCOUNT, "policyText": st["registryPolicy"]}


def op_DeleteRegistryPolicy(store, st, region, p):
    op_GetRegistryPolicy(store, st, region, p)
    text, st["registryPolicy"] = st["registryPolicy"], None
    return {"registryId": ACCOUNT, "policyText": text}


def op_PutRegistryScanningConfiguration(store, st, region, p):
    if p.get("scanType", "BASIC") not in ("BASIC", "ENHANCED"):
        raise _Err("InvalidParameterException", "Invalid parameter at 'scanType' failed to satisfy constraint")
    for rule in p.get("rules") or []:
        if rule.get("scanFrequency") not in ("SCAN_ON_PUSH", "CONTINUOUS_SCAN", "MANUAL"):
            raise _Err("InvalidParameterException", "Invalid parameter at 'rules.scanFrequency' failed to satisfy constraint")
        for f in rule.get("repositoryFilters") or []:
            if f.get("filterType") != "WILDCARD":
                raise _Err("InvalidParameterException", "repositoryFilters filterType must be WILDCARD")
    st["scanning"] = {"scanType": p.get("scanType", "BASIC"), "rules": p.get("rules") or []}
    return {"registryScanningConfiguration": st["scanning"]}


def op_GetRegistryScanningConfiguration(store, st, region, p):
    return {"registryId": ACCOUNT, "scanningConfiguration": st["scanning"]}


def _by_arn(st, arn):
    m = re.match(r"^arn:aws:ecr:([^:]+):\d{12}:repository/(.+)$", arn or "")
    if not m or m.group(2) not in _repos(st, m.group(1)):
        raise _Err("RepositoryNotFoundException", f"The repository with name '{(m.group(2) if m else arn)}' does not exist in the registry with id '{ACCOUNT}'")
    return _repos(st, m.group(1))[m.group(2)]


def op_TagResource(store, st, region, p):
    r = _by_arn(st, p.get("resourceArn"))
    if len(r["tags_res"]) + len(p.get("tags") or []) > 50:
        raise _Err("TooManyTagsException", "The list of tags on the repository is over the limit. The maximum number of tags that can be applied to a repository is 50.")
    for t in p.get("tags") or []:
        r["tags_res"][t["Key"]] = t.get("Value", "")
    return {}


def op_UntagResource(store, st, region, p):
    r = _by_arn(st, p.get("resourceArn"))
    for k in p.get("tagKeys") or []:
        r["tags_res"].pop(k, None)
    return {}


def op_ListTagsForResource(store, st, region, p):
    r = _by_arn(st, p.get("resourceArn"))
    return {"tags": [{"Key": k, "Value": v} for k, v in sorted(r["tags_res"].items())]}


_OPS = {n[3:]: f for n, f in list(globals().items()) if n.startswith("op_")}


def dispatch(store, target: str, payload: dict, region: str = DEFAULT_REGION) -> Resp:
    """JSON 1.1 control plane. `target` is the X-Amz-Target value (prefix optional)."""
    op = (target or "").rsplit(".", 1)[-1]
    fn = _OPS.get(op)
    if fn is None:
        return Resp(400, {"__type": "UnknownOperationException", "message": f"Unknown operation {op}"})
    try:
        return Resp(200, fn(store, _st(store), region or DEFAULT_REGION, payload or {}))
    except _Err as e:
        return Resp(e.status, {"__type": e.code, "message": e.message})


# ── registry data plane (Docker Registry HTTP API v2) ─────────────────────────────────
def _rerr(status, code, msg, headers=None):
    return Resp(status, json.dumps({"errors": [{"code": code, "message": msg}]}).encode(),
                {"content-type": "application/json", **(headers or {})})


def _authed(st, headers) -> bool:
    a = headers.get("authorization") or ""
    if not a.lower().startswith("basic "):
        return False
    try:
        user, _, pw = base64.b64decode(a[6:]).decode().partition(":")
    except Exception:
        return False
    exp = st["tokens"].get(hashlib.sha256(pw.encode()).hexdigest())
    return user == "AWS" and bool(exp) and exp > _now()


def is_registry_request(headers: dict, path: str) -> bool:
    """True when a /v2/... request is for the ECR data plane (ECR host name, or AWS:<token> basic auth)."""
    lh = {(k or "").lower(): v for k, v in (headers or {}).items()}
    if ".dkr.ecr." in (lh.get("host") or "").lower():
        return True
    a = lh.get("authorization") or ""
    if a.lower().startswith("basic "):
        try:
            return base64.b64decode(a[6:]).decode().startswith("AWS:")
        except Exception:
            return False
    return False


def registry_dispatch(store, method: str, path: str, query: dict | None, headers: dict | None, body: bytes, region: str | None = None) -> Resp:
    st = _st(store)
    query = query or {}
    lh = {(k or "").lower(): v for k, v in (headers or {}).items()}
    host = lh.get("host") or ""
    m = re.search(r"\.dkr\.ecr\.([a-z0-9-]+)\.", host)
    region = region or (m.group(1) if m else DEFAULT_REGION)
    method = method.upper()
    challenge = {"www-authenticate": f'Basic realm="https://{ACCOUNT}.dkr.ecr.{region}.amazonaws.com/",service="ecr.amazonaws.com"'}
    if not _authed(st, lh):
        return _rerr(401, "UNAUTHORIZED", "Not Authorized", challenge)
    segs = [s for s in path.split("?", 1)[0].split("/") if s]
    rest = segs[1:]
    if not rest:
        return Resp(200, b"{}", {"content-type": "application/json"})
    if rest == ["_catalog"]:
        return Resp(200, json.dumps({"repositories": sorted(_repos(st, region))}).encode(), {"content-type": "application/json"})
    if len(rest) < 3:
        return _rerr(404, "NAME_UNKNOWN", "unknown path")
    kind_i = None
    for i in range(len(rest) - 1, 0, -1):
        if rest[i] in ("blobs", "manifests", "tags"):
            kind_i = i
            break
    if kind_i is None:
        return _rerr(404, "NAME_UNKNOWN", "unknown path")
    name, kind, tail = "/".join(rest[:kind_i]), rest[kind_i], rest[kind_i + 1:]
    repo = _repos(st, region).get(name)
    if not repo:
        return _rerr(404, "NAME_UNKNOWN", f"The repository with name '{name}' does not exist in the registry with id '{ACCOUNT}'")
    try:
        if kind == "tags" and tail == ["list"]:
            return Resp(200, json.dumps({"name": name, "tags": sorted(repo["tags"])}).encode(), {"content-type": "application/json"})
        if kind == "blobs":
            return _reg_blobs(store, st, repo, method, tail, query, body)
        if kind == "manifests" and len(tail) == 1:
            return _reg_manifests(store, st, region, repo, method, tail[0], lh, body)
    except _Err as e:
        return _rerr(e.status, {"ImageTagAlreadyExistsException": "TAG_INVALID", "LayersNotFoundException": "MANIFEST_BLOB_UNKNOWN",
                                "ImageInvalidException": "MANIFEST_INVALID"}.get(e.code, e.code), e.message)
    return _rerr(404, "NAME_UNKNOWN", "unknown path")


def _reg_blobs(store, st, repo, method, tail, query, body):
    name = repo["name"]
    if tail and tail[0] == "uploads":
        if not tail[1:]:
            if method != "POST":
                return _rerr(405, "UNSUPPORTED", "Method not allowed")
            dg = query.get("digest")
            if dg:   # monolithic upload
                _finish_blob(store, st, repo, bytes(body), dg)
                return Resp(201, b"", {"location": f"/v2/{name}/blobs/{dg}", "docker-content-digest": dg})
            uid = str(uuid.uuid4())
            st["uploads"][uid] = {"repo": name, "size": 0}
            _s3_put(store, f"uploads/{uid}", b"")
            return Resp(202, b"", {"location": f"/v2/{name}/blobs/uploads/{uid}", "docker-upload-uuid": uid, "range": "0-0"})
        uid = tail[1]
        u = st["uploads"].get(uid)
        if not u or u["repo"] != name:
            return _rerr(404, "BLOB_UPLOAD_UNKNOWN", "blob upload unknown to registry")
        if method == "PATCH":
            cur = _s3_get(store, f"uploads/{uid}") or b""
            _s3_put(store, f"uploads/{uid}", cur + bytes(body))
            u["size"] += len(body)
            return Resp(202, b"", {"location": f"/v2/{name}/blobs/uploads/{uid}", "docker-upload-uuid": uid, "range": f"0-{max(u['size'] - 1, 0)}"})
        if method == "PUT":
            dg = query.get("digest")
            if not dg or not _DIGEST_RE.match(dg):
                return _rerr(400, "DIGEST_INVALID", "digest query parameter missing or invalid")
            data = (_s3_get(store, f"uploads/{uid}") or b"") + bytes(body)
            try:
                _finish_blob(store, st, repo, data, dg)
            except _Err:
                return _rerr(400, "DIGEST_INVALID", "provided digest did not match uploaded content")
            _s3_del(store, f"uploads/{uid}")
            st["uploads"].pop(uid, None)
            return Resp(201, b"", {"location": f"/v2/{name}/blobs/{dg}", "docker-content-digest": dg})
        if method == "DELETE":
            _s3_del(store, f"uploads/{uid}")
            st["uploads"].pop(uid, None)
            return Resp(204, b"")
        return _rerr(405, "UNSUPPORTED", "Method not allowed")
    if len(tail) != 1 or not _DIGEST_RE.match(tail[0]):
        return _rerr(400, "DIGEST_INVALID", "invalid digest")
    dg = tail[0]
    if dg not in repo["layers"] or dg not in st["blobs"]:
        return _rerr(404, "BLOB_UNKNOWN", "blob unknown to registry")
    if method == "DELETE":
        repo["layers"].remove(dg)
        return Resp(202, b"")
    data = _s3_get(store, f"blobs/{dg.split(':')[1]}") or b""
    h = {"docker-content-digest": dg, "content-length": str(len(data)), "content-type": "application/octet-stream"}
    return Resp(200, b"" if method == "HEAD" else data, h)


def _reg_manifests(store, st, region, repo, method, ref, lh, body):
    name = repo["name"]
    if method == "PUT":
        is_digest = bool(_DIGEST_RE.match(ref))
        mt = lh.get("content-type") or None
        digest = _put_manifest(store, st, region, repo, bytes(body), None if is_digest else ref, mt, True) \
            if not _tag_exists_same(repo, ref, body) else _sha(bytes(body))
        if is_digest and digest != ref:
            return _rerr(400, "DIGEST_INVALID", "manifest digest does not match reference")
        return Resp(201, b"", {"location": f"/v2/{name}/manifests/{digest}", "docker-content-digest": digest})
    digest = ref if _DIGEST_RE.match(ref) else repo["tags"].get(ref)
    if method == "DELETE":
        if not digest or digest not in repo["images"]:
            return _rerr(404, "MANIFEST_UNKNOWN", "manifest unknown")
        _delete_image(store, repo, digest)
        return Resp(202, b"")
    if not digest or digest not in repo["images"]:
        return _rerr(404, "MANIFEST_UNKNOWN", f"Requested image not found")
    data = _s3_get(store, f"manifests/{digest.split(':')[1]}") or b""
    if method == "GET":
        repo["images"][digest]["lastPull"] = _now()
    return Resp(200, b"" if method == "HEAD" else data,
                {"content-type": repo["images"][digest]["mediaType"], "docker-content-digest": digest, "content-length": str(len(data))})


def _tag_exists_same(repo, ref, body):
    """Re-pushing the identical manifest under the same tag is idempotent on the registry wire (docker does it)."""
    return repo["tags"].get(ref) == _sha(bytes(body))


# ── Inspector2 view over the same scans ───────────────────────────────────────────────
def _all_findings(store, st):
    out = []
    for region, repos in st["regions"].items():
        for repo in repos.values():
            kind, _ = _scan_mode(st, repo)
            if kind != "ENHANCED":
                continue
            for d, img in repo["images"].items():
                if img.get("scan") and img["scan"]["kind"] == "ENHANCED":
                    out.extend(_enhanced_findings(repo, region, d, img["scan"]))
    return out


def _fmatch(f, crit):
    def ok(vals, getter):
        if not vals:
            return True
        got = getter(f)
        got = got if isinstance(got, list) else [got]
        for v in vals:
            comp, val = v.get("comparison"), v.get("value")
            for g in got:
                if (comp == "EQUALS" and g == val) or (comp == "PREFIX" and str(g).startswith(str(val))) or (comp == "NOT_EQUALS" and g != val):
                    return True
        return False
    res = f["resources"][0]["details"]["awsEcrContainerImage"]
    return (ok(crit.get("severity"), lambda x: x["severity"]) and ok(crit.get("findingStatus"), lambda x: x["status"])
            and ok(crit.get("vulnerabilityId"), lambda x: x["packageVulnerabilityDetails"]["vulnerabilityId"])
            and ok(crit.get("ecrImageRepositoryName"), lambda x: res["repositoryName"])
            and ok(crit.get("ecrImageTags"), lambda x: res["imageTags"])
            and ok(crit.get("findingType"), lambda x: x["type"])
            and ok(crit.get("vulnerablePackages") and [{"comparison": c.get("name", {}).get("comparison"), "value": c.get("name", {}).get("value")} for c in crit["vulnerablePackages"]],
                   lambda x: [v["name"] for v in x["packageVulnerabilityDetails"]["vulnerablePackages"]]))


def inspector_dispatch(store, method: str, path: str, body: bytes, region: str = DEFAULT_REGION) -> Resp:
    """Inspector2 (rest-json): POST /findings/list, /coverage/list, /enable, /status/batch/get, /findings/aggregation/list."""
    st = _st(store)
    try:
        p = json.loads(body.decode() or "{}") if body else {}
    except ValueError:
        return Resp(400, {"__type": "ValidationException", "message": "Body must be JSON"})
    path = path.split("?", 1)[0].rstrip("/")
    ins = st.setdefault("inspector", {"enabled": False})
    if method != "POST":
        return Resp(404, {"__type": "ResourceNotFoundException", "message": f"{method} {path}"})
    if path == "/enable":
        ins["enabled"] = True
        st["scanning"] = {"scanType": "ENHANCED", "rules": st["scanning"].get("rules") or [{"scanFrequency": "SCAN_ON_PUSH", "repositoryFilters": [{"filter": "*", "filterType": "WILDCARD"}]}]}
        return Resp(200, {"accounts": [{"accountId": ACCOUNT, "resourceStatus": {"ecr": "ENABLED", "ec2": "DISABLED", "lambda": "DISABLED"}, "status": "ENABLED"}], "failedAccounts": []})
    if path == "/status/batch/get":
        s = "ENABLED" if ins["enabled"] else "DISABLED"
        return Resp(200, {"accounts": [{"accountId": ACCOUNT, "state": {"status": s}, "resourceState": {"ecr": {"status": s}}}], "failedAccounts": []})
    if not ins["enabled"] and path in ("/findings/list", "/coverage/list", "/findings/aggregation/list"):
        return Resp(403, {"__type": "AccessDeniedException", "message": "Inspector is not enabled for this account. Call Enable first."})
    if path == "/findings/list":
        fs = [f for f in _all_findings(store, st) if _fmatch(f, p.get("filterCriteria") or {})]
        fs.sort(key=lambda f: -f["inspectorScore"])
        page, nxt = _page(fs, p, "nextToken", "maxResults", 100)
        out = {"findings": page}
        if nxt:
            out["nextToken"] = nxt
        return Resp(200, out)
    if path == "/findings/aggregation/list":
        by = {}
        for f in _all_findings(store, st):
            k = f["resources"][0]["details"]["awsEcrContainerImage"]["repositoryName"]
            a = by.setdefault(k, {"repository": k, "severityCounts": {"all": 0, "critical": 0, "high": 0, "medium": 0}, "affectedImages": set()})
            a["severityCounts"]["all"] += 1
            if f["severity"].lower() in a["severityCounts"]:
                a["severityCounts"][f["severity"].lower()] += 1
            a["affectedImages"].add(f["resources"][0]["details"]["awsEcrContainerImage"]["imageHash"])
        resp = [{"repositoryAggregation": {"repository": a["repository"], "severityCounts": a["severityCounts"], "affectedImages": len(a["affectedImages"]), "accountId": ACCOUNT}} for a in by.values()]
        return Resp(200, {"aggregationType": p.get("aggregationType", "REPOSITORY"), "responses": resp})
    if path == "/coverage/list":
        rows = []
        for region_, repos in st["regions"].items():
            for repo in repos.values():
                rows.append({"accountId": ACCOUNT, "resourceId": repo["name"], "resourceType": "AWS_ECR_REPOSITORY", "scanType": "PACKAGE",
                             "scanStatus": {"statusCode": "ACTIVE", "reason": "SUCCESSFUL"}, "scanMode": "EC2_AGENTLESS" if False else None,
                             "lastScannedAt": max([i["scan"]["completedAt"] for i in repo["images"].values() if i.get("scan")] or [repo["createdAt"]])})
        for r in rows:
            r.pop("scanMode")
        page, nxt = _page(rows, p, "nextToken", "maxResults", 100)
        return Resp(200, {"coveredResources": page, **({"nextToken": nxt} if nxt else {})})
    return Resp(404, {"__type": "ResourceNotFoundException", "message": f"Unknown path {path}"})
