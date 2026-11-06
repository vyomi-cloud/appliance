"""ECR core — substrate-independent Amazon Elastic Container Registry engine.

Speaks the native **ECR JSON protocol** (X-Amz-Target
`AmazonEC2ContainerRegistry_V20150921.<Op>`, JSON 1.1, SigV4 signing name `ecr`) so
an unmodified aws-sdk (Java v2 / Go v2 / boto3) and the `aws ecr` CLI work with only
the endpoint changed. NO fastapi / boto3 / socket imports → loads under Pyodide, and
the SAME file runs offline (appliance) and in Nano (browser).

State lives in plain JSON-safe dicts on an `EcrStore` (`repositories`, `images`,
`layers`, …). Bind a store to an existing dict (`EcrStore(state)`) and every mutation
lands in that dict — the appliance binds it to the active space's service state so it
persists with the space; Nano uses a bare store that `nano_persist` snapshots.

Scope: repository lifecycle (Create/Describe/Delete + tag mutability, scan config,
tags), the image API (PutImage / BatchGetImage / ListImages / DescribeImages /
BatchDeleteImage), the layer-upload protocol (BatchCheckLayerAvailability /
InitiateLayerUpload / UploadLayerPart / CompleteLayerUpload /
GetDownloadUrlForLayer), GetAuthorizationToken, lifecycle + repository + registry
policies, image scanning, and registry-level config. Errors and codes follow the
botocore `ecr` model. When a real registry backs the appliance (`registry:2`), set
`store.registry_host` so repositoryUri / proxyEndpoint point at it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field

REGION = "us-east-1"
ACCOUNT_ID = "123456789012"
TARGET_PREFIX = "AmazonEC2ContainerRegistry_V20150921"
DEFAULT_MANIFEST_MT = "application/vnd.docker.distribution.manifest.v2+json"
_MANIFEST_LIST_MTS = ("application/vnd.docker.distribution.manifest.list.v2+json",
                      "application/vnd.oci.image.index.v1+json")
PART_SIZE = 20 * 1024 * 1024
_NAME_RE = re.compile(r"^(?:[a-z0-9]+(?:[._-][a-z0-9]+)*/)*[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_DIGEST_RE = re.compile(r"^[a-z0-9]+:[a-fA-F0-9]{32,}$")


@dataclass
class EcrResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class EcrStore:
    """All ECR state, in public JSON-safe dicts. `EcrStore(state)` binds to `state`."""

    def __init__(self, state: dict | None = None):
        s = state if state is not None else {}
        self.repositories = s.setdefault("repositories", {})   # name -> repo record
        self.images = s.setdefault("images", {})               # repo -> [image record]
        self.layers = s.setdefault("layers", {})               # repo -> {digest: base64}
        self.uploads = s.setdefault("uploads", {})             # uploadId -> {repo, parts:[b64]}
        self.registry = s.setdefault("registry", {})           # registry-level config
        self.account_id = ACCOUNT_ID
        self.region = REGION
        # Optional real registry host (e.g. "localhost:5000") fronting the engine.
        self.registry_host = ""

    def persist(self) -> None:  # seam hook; persistent substrates override
        pass


class _E(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _now() -> float:
    return round(time.time(), 3)


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _host(store: EcrStore) -> str:
    return store.registry_host or f"{store.account_id}.dkr.ecr.{store.region}.amazonaws.com"


def _repo_arn(store, name):
    return f"arn:aws:ecr:{store.region}:{store.account_id}:repository/{name}"


def _check_registry(store, p) -> None:
    rid = p.get("registryId")
    if rid not in (None, "", store.account_id):
        raise _E("InvalidParameterException", f"Invalid parameter at 'registryId' failed to satisfy constraint: 'Invalid registry id {rid}'")


def _repo_view(store, r) -> dict:
    out = {
        "repositoryArn": r["repositoryArn"], "registryId": store.account_id,
        "repositoryName": r["repositoryName"],
        "repositoryUri": f"{_host(store)}/{r['repositoryName']}",
        "createdAt": r["createdAt"], "imageTagMutability": r["imageTagMutability"],
        "imageScanningConfiguration": {"scanOnPush": bool(r["scanOnPush"])},
        "encryptionConfiguration": dict(r["encryptionConfiguration"]),
    }
    if r.get("imageTagMutabilityExclusionFilters"):
        out["imageTagMutabilityExclusionFilters"] = list(r["imageTagMutabilityExclusionFilters"])
    return out


def _need_repo(store, p) -> dict:
    _check_registry(store, p)
    name = p.get("repositoryName")
    if not name:
        raise _E("InvalidParameterException", "Missing required parameter in input: \"repositoryName\"")
    r = store.repositories.get(name)
    if r is None:
        raise _E("RepositoryNotFoundException",
                 f"The repository with name '{name}' does not exist in the registry with id '{store.account_id}'")
    return r


def _page(items: list, p: dict, key: str):
    """Offset pagination: nextToken is the opaque start index."""
    try:
        start = int(p.get("nextToken") or 0)
    except ValueError:
        raise _E("InvalidParameterException", "Invalid parameter at 'nextToken': invalid token")
    mx = p.get("maxResults")
    if mx is not None and not (1 <= int(mx) <= 1000):
        raise _E("InvalidParameterException", "Invalid parameter at 'maxResults' failed to satisfy constraint: Member must have value between 1 and 1000")
    n = int(mx) if mx else 1000
    out = {key: items[start:start + n]}
    if start + n < len(items):
        out["nextToken"] = str(start + n)
    return out


# ── repositories ───────────────────────────────────────────────────────────
def _create_repository(store, p):
    _check_registry(store, p)
    name = p.get("repositoryName")
    if not name:
        raise _E("InvalidParameterException", "Missing required parameter in input: \"repositoryName\"")
    if not (2 <= len(name) <= 256) or not _NAME_RE.match(name):
        raise _E("InvalidParameterException",
                 f"Invalid parameter at 'repositoryName' failed to satisfy constraint: 'must satisfy regular expression "
                 f"\"(?:[a-z0-9]+(?:[._-][a-z0-9]+)*/)*[a-z0-9]+(?:[._-][a-z0-9]+)*\"'")
    if name in store.repositories:
        raise _E("RepositoryAlreadyExistsException",
                 f"The repository with name '{name}' already exists in the registry with id '{store.account_id}'")
    mut = p.get("imageTagMutability") or "MUTABLE"
    if mut not in ("MUTABLE", "IMMUTABLE", "IMMUTABLE_WITH_EXCLUSION", "MUTABLE_WITH_EXCLUSION"):
        raise _E("InvalidParameterException", f"Invalid parameter at 'imageTagMutability' failed to satisfy constraint: '{mut}'")
    enc = p.get("encryptionConfiguration") or {"encryptionType": "AES256"}
    if enc.get("encryptionType") not in ("AES256", "KMS", "KMS_DSSE"):
        raise _E("InvalidParameterException", "Invalid parameter at 'encryptionConfiguration.encryptionType'")
    tags = p.get("tags") or []
    if len(tags) > 50:
        raise _E("TooManyTagsException", "The list of tags on the repository is over the limit. The maximum number of tags that can be applied to a repository is 50.")
    rec = {
        "repositoryName": name, "repositoryArn": _repo_arn(store, name), "createdAt": _now(),
        "imageTagMutability": mut, "scanOnPush": bool((p.get("imageScanningConfiguration") or {}).get("scanOnPush")),
        "encryptionConfiguration": dict(enc), "tags": [{"Key": t["Key"], "Value": t.get("Value", "")} for t in tags],
        "imageTagMutabilityExclusionFilters": list(p.get("imageTagMutabilityExclusionFilters") or []),
    }
    store.repositories[name] = rec
    store.images.setdefault(name, [])
    store.layers.setdefault(name, {})
    store.persist()
    return {"repository": _repo_view(store, rec)}


def _describe_repositories(store, p):
    _check_registry(store, p)
    names = p.get("repositoryNames")
    if names:
        out = []
        for n in names:
            if n not in store.repositories:
                raise _E("RepositoryNotFoundException",
                         f"The repository with name '{n}' does not exist in the registry with id '{store.account_id}'")
            out.append(store.repositories[n])
    else:
        out = [store.repositories[n] for n in sorted(store.repositories)]
    res = _page([_repo_view(store, r) for r in out], p, "repositories")
    return res


def _delete_repository(store, p):
    r = _need_repo(store, p)
    name = r["repositoryName"]
    if store.images.get(name) and not p.get("force"):
        raise _E("RepositoryNotEmptyException",
                 f"The repository with name '{name}' in registry with id '{store.account_id}' cannot be deleted because it still contains images")
    view = _repo_view(store, r)
    for d in (store.repositories, store.images, store.layers):
        d.pop(name, None)
    for uid in [u for u, v in store.uploads.items() if v["repositoryName"] == name]:
        store.uploads.pop(uid, None)
    store.persist()
    return {"repository": view}


def _put_image_tag_mutability(store, p):
    r = _need_repo(store, p)
    mut = p.get("imageTagMutability")
    if mut not in ("MUTABLE", "IMMUTABLE", "IMMUTABLE_WITH_EXCLUSION", "MUTABLE_WITH_EXCLUSION"):
        raise _E("InvalidParameterException", f"Invalid parameter at 'imageTagMutability' failed to satisfy constraint: '{mut}'")
    r["imageTagMutability"] = mut
    r["imageTagMutabilityExclusionFilters"] = list(p.get("imageTagMutabilityExclusionFilters") or [])
    store.persist()
    return {"registryId": store.account_id, "repositoryName": r["repositoryName"], "imageTagMutability": mut,
            **({"imageTagMutabilityExclusionFilters": r["imageTagMutabilityExclusionFilters"]} if r["imageTagMutabilityExclusionFilters"] else {})}


def _put_image_scanning_configuration(store, p):
    r = _need_repo(store, p)
    cfg = p.get("imageScanningConfiguration")
    if not isinstance(cfg, dict) or "scanOnPush" not in cfg:
        raise _E("InvalidParameterException", "Missing required parameter in input: \"imageScanningConfiguration\"")
    r["scanOnPush"] = bool(cfg["scanOnPush"])
    store.persist()
    return {"registryId": store.account_id, "repositoryName": r["repositoryName"],
            "imageScanningConfiguration": {"scanOnPush": r["scanOnPush"]}}


# ── tags ───────────────────────────────────────────────────────────────────
def _repo_by_arn(store, arn):
    m = re.match(r"^arn:aws:ecr:[^:]+:[^:]*:repository/(.+)$", arn or "")
    if not m or m.group(1) not in store.repositories:
        raise _E("RepositoryNotFoundException", f"The repository with name '{(m.group(1) if m else arn)}' does not exist in the registry with id '{store.account_id}'")
    return store.repositories[m.group(1)]


def _tag_resource(store, p):
    r = _repo_by_arn(store, p.get("resourceArn"))
    cur = {t["Key"]: t.get("Value", "") for t in r["tags"]}
    for t in p.get("tags") or []:
        cur[t["Key"]] = t.get("Value", "")
    if len(cur) > 50:
        raise _E("TooManyTagsException", "The list of tags on the repository is over the limit. The maximum number of tags that can be applied to a repository is 50.")
    r["tags"] = [{"Key": k, "Value": v} for k, v in cur.items()]
    store.persist()
    return {}


def _untag_resource(store, p):
    r = _repo_by_arn(store, p.get("resourceArn"))
    drop = set(p.get("tagKeys") or [])
    r["tags"] = [t for t in r["tags"] if t["Key"] not in drop]
    store.persist()
    return {}


def _list_tags_for_resource(store, p):
    return {"tags": list(_repo_by_arn(store, p.get("resourceArn"))["tags"])}


# ── images ─────────────────────────────────────────────────────────────────
def _image_id(img, tag=None) -> dict:
    d = {"imageDigest": img["digest"]}
    if tag:
        d["imageTag"] = tag
    return d


def _find_image(store, repo, image_id):
    """Resolve {imageDigest?, imageTag?} → image record (or None)."""
    imgs = store.images.get(repo, [])
    tag, dig = image_id.get("imageTag"), image_id.get("imageDigest")
    for img in imgs:
        if tag and tag not in img["tags"]:
            continue
        if dig and img["digest"] != dig:
            continue
        if tag or dig:
            return img
    return None


def _manifest_refs(manifest: dict):
    """(layer digests this manifest needs, child manifest digests, total size)."""
    layers, children, size = [], [], 0
    cfg = manifest.get("config")
    if isinstance(cfg, dict) and cfg.get("digest"):
        layers.append(cfg["digest"]); size += int(cfg.get("size") or 0)
    for l in manifest.get("layers") or []:
        if l.get("digest"):
            layers.append(l["digest"]); size += int(l.get("size") or 0)
    for m in manifest.get("manifests") or []:
        if m.get("digest"):
            children.append(m["digest"])
    return layers, children, size


def _put_image(store, p):
    r = _need_repo(store, p)
    repo = r["repositoryName"]
    text = p.get("imageManifest")
    if not text:
        raise _E("InvalidParameterException", "Missing required parameter in input: \"imageManifest\"")
    try:
        manifest = json.loads(text)
        if not isinstance(manifest, dict):
            raise ValueError
    except ValueError:
        raise _E("InvalidParameterException", "Invalid parameter at 'imageManifest' failed to satisfy constraint: 'Invalid JSON'")
    mt = p.get("imageManifestMediaType") or manifest.get("mediaType") or DEFAULT_MANIFEST_MT
    digest = _sha256(text.encode())
    if p.get("imageDigest") and p["imageDigest"] != digest:
        raise _E("ImageDigestDoesNotMatchException", "The specified image digest does not match the digest that Amazon ECR calculated for the image.")
    layers, children, size = _manifest_refs(manifest)
    have = store.layers.get(repo, {})
    missing = [d for d in layers if d not in have]
    if missing:
        raise _E("LayersNotFoundException",
                 f"The layers specified in the image manifest were not found in repository '{repo}': {', '.join(missing)}")
    known = {i["digest"] for i in store.images.get(repo, [])}
    if children and [c for c in children if c not in known]:
        raise _E("ReferencedImagesNotFoundException", "The manifest list references images that do not exist in the repository.")
    if children:
        size = sum(i["size"] for i in store.images[repo] if i["digest"] in children)
    tag = p.get("imageTag")
    imgs = store.images.setdefault(repo, [])
    existing = next((i for i in imgs if i["digest"] == digest), None)
    if tag:
        holder = next((i for i in imgs if tag in i["tags"]), None)
        if holder is not None and holder["digest"] == digest:
            raise _E("ImageAlreadyExistsException",
                     f"Image with digest '{digest}' and tag '{tag}' already exists in the repository with name '{repo}' in registry with id '{store.account_id}'")
        if holder is not None and r["imageTagMutability"] in ("IMMUTABLE", "IMMUTABLE_WITH_EXCLUSION"):
            raise _E("ImageTagAlreadyExistsException",
                     f"The image tag '{tag}' already exists in the '{repo}' repository and cannot be overwritten because the repository is immutable.")
        if holder is not None:
            holder["tags"].remove(tag)
    elif existing is not None:
        raise _E("ImageAlreadyExistsException",
                 f"Image with digest '{digest}' already exists in the repository with name '{repo}' in registry with id '{store.account_id}'")
    if existing is None:
        existing = {"digest": digest, "manifest": text, "mediaType": mt, "tags": [], "size": size,
                    "pushedAt": _now(), "lastPull": None, "scan": None}
        imgs.append(existing)
        if r["scanOnPush"]:
            _scan(existing)
    if tag and tag not in existing["tags"]:
        existing["tags"].append(tag)
    # a tag-less holder of nothing (all tags moved away) stays as an untagged image
    store.persist()
    return {"image": {"registryId": store.account_id, "repositoryName": repo, "imageId": _image_id(existing, tag),
                      "imageManifest": text, "imageManifestMediaType": mt}}


def _batch_get_image(store, p):
    r = _need_repo(store, p)
    ids = p.get("imageIds")
    if not ids:
        raise _E("InvalidParameterException", "Missing required parameter in input: \"imageIds\"")
    accepted = p.get("acceptedMediaTypes")
    images, failures = [], []
    for iid in ids:
        img = _find_image(store, r["repositoryName"], iid)
        if img is None:
            failures.append({"imageId": iid, "failureCode": "ImageNotFound",
                             "failureReason": "Requested image not found"})
            continue
        if accepted and img["mediaType"] not in accepted:
            failures.append({"imageId": iid, "failureCode": "ImageNotFound", "failureReason": "Requested image not found"})
            continue
        img["lastPull"] = _now()
        images.append({"registryId": store.account_id, "repositoryName": r["repositoryName"],
                       "imageId": _image_id(img, iid.get("imageTag")), "imageManifest": img["manifest"],
                       "imageManifestMediaType": img["mediaType"]})
    store.persist()
    return {"images": images, "failures": failures}


def _tag_filter(imgs, p):
    ts = (p.get("filter") or {}).get("tagStatus")
    if ts == "TAGGED":
        return [i for i in imgs if i["tags"]]
    if ts == "UNTAGGED":
        return [i for i in imgs if not i["tags"]]
    if ts not in (None, "ANY"):
        raise _E("InvalidParameterException", f"Invalid parameter at 'filter.tagStatus' failed to satisfy constraint: '{ts}'")
    return imgs


def _list_images(store, p):
    r = _need_repo(store, p)
    ids = []
    for img in _tag_filter(store.images.get(r["repositoryName"], []), p):
        if img["tags"]:
            ids.extend(_image_id(img, t) for t in img["tags"])
        else:
            ids.append(_image_id(img))
    return _page(ids, p, "imageIds")


def _detail(store, repo, img) -> dict:
    d = {"registryId": store.account_id, "repositoryName": repo, "imageDigest": img["digest"],
         "imageSizeInBytes": img["size"], "imagePushedAt": img["pushedAt"],
         "imageManifestMediaType": img["mediaType"], "imageStatus": "ACTIVE"}
    if img["tags"]:
        d["imageTags"] = list(img["tags"])
    if img.get("lastPull"):
        d["lastRecordedPullTime"] = img["lastPull"]
    sc = img.get("scan")
    if sc:
        d["imageScanStatus"] = {"status": sc["status"], "description": sc["description"]}
        d["imageScanFindingsSummary"] = {"imageScanCompletedAt": sc["completedAt"],
                                         "vulnerabilitySourceUpdatedAt": sc["completedAt"],
                                         "findingSeverityCounts": dict(sc["counts"])}
    return d


def _describe_images(store, p):
    r = _need_repo(store, p)
    repo = r["repositoryName"]
    imgs = _tag_filter(store.images.get(repo, []), p)
    if p.get("imageIds"):
        sel = []
        for iid in p["imageIds"]:
            img = _find_image(store, repo, iid)
            if img is None:
                raise _E("ImageNotFoundException",
                         f"The image with imageId {json.dumps(iid)} does not exist within the repository with name '{repo}' in the registry with id '{store.account_id}'")
            if img not in sel:
                sel.append(img)
        imgs = sel
    imgs = sorted(imgs, key=lambda i: i["pushedAt"])
    return _page([_detail(store, repo, i) for i in imgs], p, "imageDetails")


def _batch_delete_image(store, p):
    r = _need_repo(store, p)
    ids = p.get("imageIds")
    if not ids:
        raise _E("InvalidParameterException", "Missing required parameter in input: \"imageIds\"")
    repo = r["repositoryName"]
    done, failures = [], []
    for iid in ids:
        img = _find_image(store, repo, iid)
        if img is None:
            failures.append({"imageId": iid, "failureCode": "ImageNotFound", "failureReason": "Requested image not found"})
            continue
        tag = iid.get("imageTag")
        if tag and not iid.get("imageDigest"):
            img["tags"].remove(tag)             # deleting by tag removes just that tag…
            done.append(_image_id(img, tag))
            if not img["tags"]:                 # …and the image once no tag is left
                store.images[repo].remove(img)
        else:
            for t in img["tags"] or [None]:
                done.append(_image_id(img, t))
            store.images[repo].remove(img)
    store.persist()
    return {"imageIds": done, "failures": failures}


# ── layers ─────────────────────────────────────────────────────────────────
def _batch_check_layer_availability(store, p):
    r = _need_repo(store, p)
    digests = p.get("layerDigests")
    if not digests:
        raise _E("InvalidParameterException", "Missing required parameter in input: \"layerDigests\"")
    have = store.layers.get(r["repositoryName"], {})
    layers, failures = [], []
    for d in digests:
        if not _DIGEST_RE.match(d):
            failures.append({"layerDigest": d, "failureCode": "InvalidLayerDigest", "failureReason": "Invalid layer digest"})
        elif d in have:
            layers.append({"layerDigest": d, "layerAvailability": "AVAILABLE",
                           "layerSize": len(base64.b64decode(have[d])), "mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip"})
        else:
            layers.append({"layerDigest": d, "layerAvailability": "UNAVAILABLE"})
    return {"layers": layers, "failures": failures}


def _initiate_layer_upload(store, p):
    r = _need_repo(store, p)
    uid = str(uuid.uuid4())
    store.uploads[uid] = {"repositoryName": r["repositoryName"], "parts": []}
    store.persist()
    return {"uploadId": uid, "partSize": PART_SIZE}


def _upload_layer_part(store, p):
    r = _need_repo(store, p)
    u = store.uploads.get(p.get("uploadId"))
    if u is None or u["repositoryName"] != r["repositoryName"]:
        raise _E("UploadNotFoundException", f"The upload ID '{p.get('uploadId')}' does not exist in the repository '{r['repositoryName']}'.")
    try:
        blob = base64.b64decode(p.get("layerPartBlob") or "")
    except Exception:
        raise _E("InvalidParameterException", "Invalid parameter at 'layerPartBlob': not valid base64")
    first, last = p.get("partFirstByte"), p.get("partLastByte")
    have = sum(len(base64.b64decode(x)) for x in u["parts"])
    if first is None or last is None or int(first) != have or int(last) - int(first) + 1 != len(blob):
        raise _E("InvalidLayerPartException",
                 f"Layer part does not match the expected range; expected first byte {have}.")
    u["parts"].append(base64.b64encode(blob).decode())
    store.persist()
    return {"registryId": store.account_id, "repositoryName": r["repositoryName"], "uploadId": p["uploadId"],
            "lastByteReceived": int(last)}


def _complete_layer_upload(store, p):
    r = _need_repo(store, p)
    repo = r["repositoryName"]
    uid = p.get("uploadId")
    u = store.uploads.get(uid)
    if u is None or u["repositoryName"] != repo:
        raise _E("UploadNotFoundException", f"The upload ID '{uid}' does not exist in the repository '{repo}'.")
    if not p.get("layerDigests"):
        raise _E("InvalidParameterException", "Missing required parameter in input: \"layerDigests\"")
    data = b"".join(base64.b64decode(x) for x in u["parts"])
    if not data:
        raise _E("EmptyUploadException", f"The layer upload '{uid}' is empty.")
    digest = _sha256(data)
    if digest not in p["layerDigests"]:
        raise _E("InvalidLayerException", f"The provided layer digest does not match the calculated digest {digest}.")
    layers = store.layers.setdefault(repo, {})
    if digest in layers:
        store.uploads.pop(uid, None)
        raise _E("LayerAlreadyExistsException", f"The image layer already exists in the repository '{repo}': {digest}")
    layers[digest] = base64.b64encode(data).decode()
    store.uploads.pop(uid, None)
    store.persist()
    return {"registryId": store.account_id, "repositoryName": repo, "uploadId": uid, "layerDigest": digest}


def _get_download_url_for_layer(store, p):
    r = _need_repo(store, p)
    d = p.get("layerDigest")
    if not d or d not in store.layers.get(r["repositoryName"], {}):
        raise _E("LayersNotFoundException", f"The specified layer upload does not exist: {d}")
    return {"downloadUrl": f"https://{_host(store)}/v2/{r['repositoryName']}/blobs/{d}", "layerDigest": d}


# ── auth ───────────────────────────────────────────────────────────────────
def _get_authorization_token(store, p):
    ids = p.get("registryIds")
    if ids and any(i != store.account_id for i in ids):
        raise _E("InvalidParameterException", "Invalid parameter at 'registryIds': unknown registry id")
    tok = base64.b64encode(b"AWS:vyomi-ecr-token-" + uuid.uuid4().hex.encode()).decode()
    scheme = "http" if store.registry_host else "https"
    return {"authorizationData": [{"authorizationToken": tok, "expiresAt": _now() + 12 * 3600,
                                   "proxyEndpoint": f"{scheme}://{_host(store)}"}]}


# ── policies ───────────────────────────────────────────────────────────────
def _validate_json_doc(text, field_name):
    try:
        d = json.loads(text)
        if not isinstance(d, dict):
            raise ValueError
        return d
    except Exception:
        raise _E("InvalidParameterException", f"Invalid parameter at '{field_name}' failed to satisfy constraint: 'Invalid JSON'")


def _set_repository_policy(store, p):
    r = _need_repo(store, p)
    if not p.get("policyText"):
        raise _E("InvalidParameterException", "Missing required parameter in input: \"policyText\"")
    _validate_json_doc(p["policyText"], "policyText")
    r["policyText"] = p["policyText"]
    store.persist()
    return {"registryId": store.account_id, "repositoryName": r["repositoryName"], "policyText": r["policyText"]}


def _get_repository_policy(store, p):
    r = _need_repo(store, p)
    if "policyText" not in r:
        raise _E("RepositoryPolicyNotFoundException",
                 f"Repository policy does not exist for the repository with name '{r['repositoryName']}' in the registry with id '{store.account_id}'")
    return {"registryId": store.account_id, "repositoryName": r["repositoryName"], "policyText": r["policyText"]}


def _delete_repository_policy(store, p):
    r = _get_repository_policy(store, p)
    store.repositories[r["repositoryName"]].pop("policyText", None)
    store.persist()
    return r


def _put_lifecycle_policy(store, p):
    r = _need_repo(store, p)
    text = p.get("lifecyclePolicyText")
    if not text:
        raise _E("InvalidParameterException", "Missing required parameter in input: \"lifecyclePolicyText\"")
    doc = _validate_json_doc(text, "lifecyclePolicyText")
    rules = doc.get("rules")
    if not isinstance(rules, list) or not rules:
        raise _E("ValidationException", "Lifecycle policy validation failure: the policy must contain a non-empty \"rules\" list")
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("rulePriority"), int) or "selection" not in rule \
                or (rule.get("action") or {}).get("type") != "expire":
            raise _E("ValidationException", "Lifecycle policy validation failure: each rule needs an integer rulePriority, a selection and action.type \"expire\"")
    r["lifecyclePolicy"] = {"text": text, "lastEvaluatedAt": _now()}
    store.persist()
    return {"registryId": store.account_id, "repositoryName": r["repositoryName"], "lifecyclePolicyText": text}


def _get_lifecycle_policy(store, p):
    r = _need_repo(store, p)
    lp = r.get("lifecyclePolicy")
    if not lp:
        raise _E("LifecyclePolicyNotFoundException",
                 f"Lifecycle policy does not exist for the repository with name '{r['repositoryName']}' in the registry with id '{store.account_id}'")
    return {"registryId": store.account_id, "repositoryName": r["repositoryName"],
            "lifecyclePolicyText": lp["text"], "lastEvaluatedAt": lp["lastEvaluatedAt"]}


def _delete_lifecycle_policy(store, p):
    out = _get_lifecycle_policy(store, p)
    store.repositories[out["repositoryName"]].pop("lifecyclePolicy", None)
    store.persist()
    return out


def _put_registry_policy(store, p):
    if not p.get("policyText"):
        raise _E("InvalidParameterException", "Missing required parameter in input: \"policyText\"")
    _validate_json_doc(p["policyText"], "policyText")
    store.registry["policyText"] = p["policyText"]
    store.persist()
    return {"registryId": store.account_id, "policyText": p["policyText"]}


def _get_registry_policy(store, p):
    if "policyText" not in store.registry:
        raise _E("RegistryPolicyNotFoundException", f"Registry policy does not exist in the registry with id '{store.account_id}'")
    return {"registryId": store.account_id, "policyText": store.registry["policyText"]}


def _delete_registry_policy(store, p):
    out = _get_registry_policy(store, p)
    store.registry.pop("policyText", None)
    store.persist()
    return out


# ── scanning ───────────────────────────────────────────────────────────────
def _scan(img):
    """Deterministic scan: a clean result (no CVE database offline)."""
    img["scan"] = {"status": "COMPLETE", "description": "The scan was completed successfully.",
                   "completedAt": _now(), "counts": {}, "findings": []}


def _start_image_scan(store, p):
    r = _need_repo(store, p)
    iid = p.get("imageId") or {}
    img = _find_image(store, r["repositoryName"], iid)
    if img is None:
        raise _E("ImageNotFoundException",
                 f"The image with imageId {json.dumps(iid)} does not exist within the repository with name '{r['repositoryName']}' in the registry with id '{store.account_id}'")
    _scan(img)
    store.persist()
    return {"registryId": store.account_id, "repositoryName": r["repositoryName"], "imageId": _image_id(img, iid.get("imageTag")),
            "imageScanStatus": {"status": "IN_PROGRESS", "description": "Scan started"}}


def _describe_image_scan_findings(store, p):
    r = _need_repo(store, p)
    iid = p.get("imageId") or {}
    img = _find_image(store, r["repositoryName"], iid)
    if img is None:
        raise _E("ImageNotFoundException",
                 f"The image with imageId {json.dumps(iid)} does not exist within the repository with name '{r['repositoryName']}' in the registry with id '{store.account_id}'")
    sc = img.get("scan")
    if not sc:
        raise _E("ScanNotFoundException",
                 f"Image scan does not exist for the image with '{json.dumps(iid)}' in the repository with name '{r['repositoryName']}' in the registry with id '{store.account_id}'")
    return {"registryId": store.account_id, "repositoryName": r["repositoryName"], "imageId": _image_id(img, iid.get("imageTag")),
            "imageScanStatus": {"status": sc["status"], "description": sc["description"]},
            "imageScanFindings": {"imageScanCompletedAt": sc["completedAt"], "vulnerabilitySourceUpdatedAt": sc["completedAt"],
                                  "findingSeverityCounts": dict(sc["counts"]), "findings": list(sc["findings"])}}


# ── registry-level config ──────────────────────────────────────────────────
def _put_replication_configuration(store, p):
    cfg = p.get("replicationConfiguration")
    if not isinstance(cfg, dict) or not isinstance(cfg.get("rules"), list):
        raise _E("InvalidParameterException", "Missing required parameter in input: \"replicationConfiguration\"")
    if len(cfg["rules"]) > 1:
        raise _E("ValidationException", "Replication configuration can contain at most 1 rule")
    store.registry["replicationConfiguration"] = cfg
    store.persist()
    return {"replicationConfiguration": cfg}


def _describe_registry(store, p):
    return {"registryId": store.account_id,
            "replicationConfiguration": store.registry.get("replicationConfiguration", {"rules": []})}


def _put_registry_scanning_configuration(store, p):
    st = p.get("scanType") or "BASIC"
    if st not in ("BASIC", "ENHANCED"):
        raise _E("ValidationException", f"Invalid scanType {st}")
    store.registry["scanningConfiguration"] = {"scanType": st, "rules": list(p.get("rules") or [])}
    store.persist()
    return {"registryScanningConfiguration": store.registry["scanningConfiguration"]}


def _get_registry_scanning_configuration(store, p):
    return {"registryId": store.account_id,
            "scanningConfiguration": store.registry.get("scanningConfiguration", {"scanType": "BASIC", "rules": []})}


_OPS = {
    "CreateRepository": _create_repository, "DescribeRepositories": _describe_repositories,
    "DeleteRepository": _delete_repository, "PutImageTagMutability": _put_image_tag_mutability,
    "PutImageScanningConfiguration": _put_image_scanning_configuration,
    "TagResource": _tag_resource, "UntagResource": _untag_resource, "ListTagsForResource": _list_tags_for_resource,
    "PutImage": _put_image, "BatchGetImage": _batch_get_image, "ListImages": _list_images,
    "DescribeImages": _describe_images, "BatchDeleteImage": _batch_delete_image,
    "BatchCheckLayerAvailability": _batch_check_layer_availability, "InitiateLayerUpload": _initiate_layer_upload,
    "UploadLayerPart": _upload_layer_part, "CompleteLayerUpload": _complete_layer_upload,
    "GetDownloadUrlForLayer": _get_download_url_for_layer, "GetAuthorizationToken": _get_authorization_token,
    "SetRepositoryPolicy": _set_repository_policy, "GetRepositoryPolicy": _get_repository_policy,
    "DeleteRepositoryPolicy": _delete_repository_policy,
    "PutLifecyclePolicy": _put_lifecycle_policy, "GetLifecyclePolicy": _get_lifecycle_policy,
    "DeleteLifecyclePolicy": _delete_lifecycle_policy,
    "PutRegistryPolicy": _put_registry_policy, "GetRegistryPolicy": _get_registry_policy,
    "DeleteRegistryPolicy": _delete_registry_policy,
    "StartImageScan": _start_image_scan, "DescribeImageScanFindings": _describe_image_scan_findings,
    "PutReplicationConfiguration": _put_replication_configuration, "DescribeRegistry": _describe_registry,
    "PutRegistryScanningConfiguration": _put_registry_scanning_configuration,
    "GetRegistryScanningConfiguration": _get_registry_scanning_configuration,
}
OPERATIONS = sorted(_OPS)


def dispatch(store: EcrStore, target: str, payload: dict | None = None) -> EcrResponse:
    """Native ECR JSON router. `target` is the X-Amz-Target header, e.g.
    "AmazonEC2ContainerRegistry_V20150921.CreateRepository"."""
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    op = _OPS.get(action)
    if op is None:
        return EcrResponse(status=400, body={"__type": "UnknownOperationException", "message": f"Unknown operation {action}."})
    try:
        return EcrResponse(body=op(store, body))
    except _E as e:
        return EcrResponse(status=400, body={"__type": e.code, "message": e.message})


# ── console facade (shared by the offline routes and the Nano adapter) ─────
def _human(n: int) -> str:
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= div:
            return f"{n / div:.2f} {unit}"
    return f"{n} B"


def console_row(store: EcrStore, name: str) -> dict:
    """One fully-populated grid/detail row for a repository (never blank)."""
    r = store.repositories[name]
    imgs = store.images.get(name, [])
    total = sum(i["size"] for i in imgs)
    latest = max((i["pushedAt"] for i in imgs), default=None)
    return {
        "name": name, "repositoryName": name, "uri": f"{_host(store)}/{name}", "arn": r["repositoryArn"],
        "created": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(r["createdAt"])),
        "tag_mutability": r["imageTagMutability"],
        "scan_on_push": "Enabled" if r["scanOnPush"] else "Disabled",
        "encryption": r["encryptionConfiguration"].get("encryptionType", "AES256"),
        "image_count": len(imgs), "size": _human(total),
        "last_push": (time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(latest)) if latest else "No images yet"),
        "lifecycle_policy": "Configured" if r.get("lifecyclePolicy") else "Not configured",
        "permissions": "Custom policy" if r.get("policyText") else "Default (account only)",
        "tags": {t["Key"]: t.get("Value", "") for t in r["tags"]},
    }


def console_list(store: EcrStore) -> dict:
    rows = [console_row(store, n) for n in sorted(store.repositories)]
    return {"ok": True, "repositories": rows, "items": rows}


def console_create(store: EcrStore, p: dict) -> dict:
    name = str(p.get("name") or p.get("repositoryName") or "").strip()
    body = {"repositoryName": name,
            "imageTagMutability": p.get("tag_mutability") or p.get("imageTagMutability") or "MUTABLE",
            "imageScanningConfiguration": {"scanOnPush": str(p.get("scan_on_push", "")).lower() in ("true", "enabled", "1", "yes")},
            "encryptionConfiguration": {"encryptionType": p.get("encryption") or "AES256"}}
    r = dispatch(store, "CreateRepository", body)
    if r.status >= 400:
        return {"ok": False, "code": r.body.get("__type"), "message": r.body.get("message")}
    return {"ok": True, **console_row(store, name)}


def console_get(store: EcrStore, name: str) -> dict:
    if name not in store.repositories:
        return {"ok": False, "code": "RepositoryNotFoundException", "name": name}
    return {"ok": True, **console_row(store, name)}


def console_update(store: EcrStore, name: str, p: dict) -> dict:
    if name not in store.repositories:
        return {"ok": False, "code": "RepositoryNotFoundException", "name": name}
    if p.get("tag_mutability"):
        r = dispatch(store, "PutImageTagMutability", {"repositoryName": name, "imageTagMutability": p["tag_mutability"]})
        if r.status >= 400:
            return {"ok": False, "code": r.body.get("__type"), "message": r.body.get("message")}
    if isinstance(p.get("tags"), dict):
        store.repositories[name]["tags"] = [{"Key": k, "Value": str(v)} for k, v in p["tags"].items()]
        store.persist()
    if "scan_on_push" in p:
        dispatch(store, "PutImageScanningConfiguration", {"repositoryName": name, "imageScanningConfiguration": {
            "scanOnPush": str(p["scan_on_push"]).lower() in ("true", "enabled", "1", "yes")}})
    return {"ok": True, **console_row(store, name)}


def console_delete(store: EcrStore, name: str) -> dict:
    r = dispatch(store, "DeleteRepository", {"repositoryName": name, "force": True})
    return {"ok": r.status < 400, "code": r.body.get("__type"), "name": name}


def console_images(store: EcrStore, name: str) -> dict:
    """Image rows for the detail "Images" tab (one row per image, tags joined)."""
    if name not in store.repositories:
        return {"ok": False, "code": "RepositoryNotFoundException", "name": name}
    rows = []
    for i in sorted(store.images.get(name, []), key=lambda x: -x["pushedAt"]):
        sc = i.get("scan")
        rows.append({
            "name": i["digest"], "tags": ", ".join(i["tags"]) or "<untagged>", "digest": i["digest"],
            "type": "Image", "size": _human(i["size"]),
            "pushed": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(i["pushedAt"])),
            "scan_status": (sc["status"] if sc else "Not scanned"),
        })
    return {"ok": True, "images": rows, "items": rows}
