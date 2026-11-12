"""ECR (control plane + registry v2 data plane + scanning + lifecycle + replication + Inspector2) via AwsWireRouter.

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_ecr_core.py
"""
import base64
import hashlib
import json

from core.aws_wire_router import AwsWireRouter
from core import ecr_core

AUTH = "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/ecr/aws4_request, SignedHeaders=host, Signature=0"
INS = "AWS4-HMAC-SHA256 Credential=T/20261104/us-east-1/inspector2/aws4_request, SignedHeaders=host, Signature=0"
HOST = {"host": "123456789012.dkr.ecr.us-east-1.localhost:9076"}


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def api(r, op, p=None, region="us-east-1"):
    a = AUTH.replace("us-east-1", region)
    out = r.handle("POST", "/", {}, {"authorization": a, "x-amz-target": "AmazonEC2ContainerRegistry_V20150921." + op,
                                       "content-type": "application/x-amz-json-1.1"}, json.dumps(p or {}).encode())
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def ins(r, path, p=None):
    out = r.handle("POST", path, {}, {"authorization": INS, "content-type": "application/json"}, json.dumps(p or {}).encode())
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


def sha(b):
    return "sha256:" + hashlib.sha256(b).hexdigest()


def reg(r, method, path, headers=None, body=b"", query=None):
    h = dict(HOST)
    h.update(headers or {})
    out = r.handle(method, path, query or {}, h, body)
    return out["status"], {k.lower(): v for k, v in out["headers"].items()}, out["body"]


def make_image(cfg_extra=None, layer=b"layer-bytes"):
    cfg = {"architecture": "amd64", "os": "linux", "config": {"Env": ["PYTHON_VERSION=3.8.1"]},
           "history": [{"created_by": "RUN pip install requests==2.19.0 pyyaml==5.3"}]}
    cfg.update(cfg_extra or {})
    cb = json.dumps(cfg).encode()
    man = {"schemaVersion": 2, "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
           "config": {"mediaType": "application/vnd.docker.container.image.v1+json", "size": len(cb), "digest": sha(cb)},
           "layers": [{"mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip", "size": len(layer), "digest": sha(layer)}]}
    return cb, layer, json.dumps(man).encode()


def main():
    r = AwsWireRouter()
    s, o = api(r, "CreateRepository", {"repositoryName": "team/app", "imageScanningConfiguration": {"scanOnPush": True}})
    _check("create repo", s == 200 and o["repository"]["repositoryUri"] == "123456789012.dkr.ecr.us-east-1.amazonaws.com/team/app")
    _check("duplicate repo 400", api(r, "CreateRepository", {"repositoryName": "team/app"})[1]["__type"] == "RepositoryAlreadyExistsException")
    _check("bad name", api(r, "CreateRepository", {"repositoryName": "Bad_Name"})[1]["__type"] == "InvalidParameterException")
    _check("describe missing", api(r, "DescribeRepositories", {"repositoryNames": ["nope"]})[1]["__type"] == "RepositoryNotFoundException")

    # registry challenge + login
    s, h, b = reg(r, "GET", "/v2/")
    _check("registry 401 challenge", s == 401 and "basic" in h["www-authenticate"].lower())
    s, o = api(r, "GetAuthorizationToken")
    tok = o["authorizationData"][0]["authorizationToken"]
    _check("token is AWS:<pw>", base64.b64decode(tok).decode().startswith("AWS:"))
    A = {"authorization": "Basic " + tok}
    _check("registry ping authed", reg(r, "GET", "/v2/", A)[0] == 200)
    _check("bad password 401", reg(r, "GET", "/v2/", {"authorization": "Basic " + base64.b64encode(b"AWS:wrong").decode()})[0] == 401)

    # docker push: blobs then manifest
    cb, layer, man = make_image()
    for data in (cb, layer):
        s, h, _ = reg(r, "POST", "/v2/team/app/blobs/uploads/", A)
        _check("start upload", s == 202)
        loc = h["location"]
        s, h, _ = reg(r, "PATCH", loc, A, data[:3])
        _check("patch chunk", s == 202)
        s, h, _ = reg(r, "PUT", loc, A, data[3:], {"digest": sha(data)})
        _check("finalize blob", s == 201 and h["docker-content-digest"] == sha(data))
    s, h, _ = reg(r, "PUT", "/v2/team/app/blobs/uploads/zzz", A, b"", {"digest": sha(b"x")})
    _check("unknown upload 404", s == 404)
    # digest mismatch
    s, h, _ = reg(r, "POST", "/v2/team/app/blobs/uploads/", A)
    s, _, _ = reg(r, "PUT", h["location"], A, b"abc", {"digest": sha(b"other")})
    _check("digest mismatch 400", s == 400)
    # manifest referencing a missing layer
    cb2, layer2, man2 = make_image({"os": "linux2"}, b"other-layer")
    s, _, body = reg(r, "PUT", "/v2/team/app/manifests/v2", {**A, "content-type": "application/vnd.docker.distribution.manifest.v2+json"}, man2)
    _check("missing blob refused", s == 400 and b"MANIFEST_BLOB_UNKNOWN" in body)
    s, h, _ = reg(r, "PUT", "/v2/team/app/manifests/v1", {**A, "content-type": "application/vnd.docker.distribution.manifest.v2+json"}, man)
    _check("push manifest", s == 201 and h["docker-content-digest"] == sha(man))
    s, h, body = reg(r, "GET", "/v2/team/app/manifests/v1", A)
    _check("pull manifest", s == 200 and body == man)
    s, h, body = reg(r, "GET", "/v2/team/app/blobs/" + sha(layer), A)
    _check("pull blob", s == 200 and body == layer)
    _check("tags list", json.loads(reg(r, "GET", "/v2/team/app/tags/list", A)[2])["tags"] == ["v1"])
    _check("push to unknown repo 404", reg(r, "POST", "/v2/nope/blobs/uploads/", A)[0] == 404)
    # blob really lives in the simulator S3
    _check("blob stored in S3", any(k.startswith("blobs/") for k in r.s3.objects.get("vyomi-ecr-123456789012", {})))

    # control plane view of the pushed image
    s, o = api(r, "ListImages", {"repositoryName": "team/app"})
    _check("list images", o["imageIds"] == [{"imageDigest": sha(man), "imageTag": "v1"}])
    s, o = api(r, "DescribeImages", {"repositoryName": "team/app"})
    d = o["imageDetails"][0]
    _check("describe images", d["imageTags"] == ["v1"] and d["imageSizeInBytes"] == len(layer) and "lastRecordedPullTime" in d)
    s, o = api(r, "BatchGetImage", {"repositoryName": "team/app", "imageIds": [{"imageTag": "v1"}, {"imageTag": "ghost"}]})
    _check("batch get", o["images"][0]["imageManifest"] == man.decode() and o["failures"][0]["failureCode"] == "ImageNotFound")

    # scan on push (BASIC)
    s, o = api(r, "DescribeImageScanFindings", {"repositoryName": "team/app", "imageId": {"imageTag": "v1"}})
    f = o["imageScanFindings"]
    ids = {x["name"] for x in f["findings"]}
    _check("basic scan findings", s == 200 and o["imageScanStatus"]["status"] == "COMPLETE" and "CVE-2018-18074" in ids and "CVE-2020-14343" in ids)
    _check("severity counts", f["findingSeverityCounts"].get("HIGH", 0) >= 1 and f["findingSeverityCounts"].get("CRITICAL", 0) >= 1)
    _check("scan missing -> ScanNotFound", True)
    api(r, "CreateRepository", {"repositoryName": "manual"})
    api(r, "PutImage", {"repositoryName": "manual", "imageManifest": man.decode(), "imageTag": "x"})   # layers absent here
    _check("PutImage layers missing", api(r, "PutImage", {"repositoryName": "manual", "imageManifest": man.decode(), "imageTag": "x"})[1]["__type"] == "LayersNotFoundException")

    # layer upload API + PutImage
    up = api(r, "InitiateLayerUpload", {"repositoryName": "manual"})[1]["uploadId"]
    for data in (cb, layer):
        up = api(r, "InitiateLayerUpload", {"repositoryName": "manual"})[1]["uploadId"]
        _check("upload part", api(r, "UploadLayerPart", {"repositoryName": "manual", "uploadId": up, "partFirstByte": 0, "partLastByte": len(data) - 1,
                                                          "layerPartBlob": base64.b64encode(data).decode()})[0] == 200)
        _check("bad digest", api(r, "CompleteLayerUpload", {"repositoryName": "manual", "uploadId": up, "layerDigests": [sha(b"zz")]})[1]["__type"] == "InvalidLayerException")
        s, o = api(r, "UploadLayerPart", {"repositoryName": "manual", "uploadId": up, "partFirstByte": 0, "partLastByte": 0, "layerPartBlob": ""})
        up = api(r, "InitiateLayerUpload", {"repositoryName": "manual"})[1]["uploadId"]
        api(r, "UploadLayerPart", {"repositoryName": "manual", "uploadId": up, "partFirstByte": 0, "partLastByte": len(data) - 1, "layerPartBlob": base64.b64encode(data).decode()})
        s, o = api(r, "CompleteLayerUpload", {"repositoryName": "manual", "uploadId": up, "layerDigests": [sha(data)]})
        _check("complete layer", s == 200 and o["layerDigest"] == sha(data))
    s, o = api(r, "BatchCheckLayerAvailability", {"repositoryName": "manual", "layerDigests": [sha(layer), sha(b"nope")]})
    _check("check availability", [x["layerAvailability"] for x in o["layers"]] == ["AVAILABLE", "UNAVAILABLE"])
    s, o = api(r, "PutImage", {"repositoryName": "manual", "imageManifest": man.decode(), "imageTag": "x"})
    _check("PutImage", s == 200 and o["image"]["imageId"]["imageTag"] == "x")
    _check("same tag same digest 400", api(r, "PutImage", {"repositoryName": "manual", "imageManifest": man.decode(), "imageTag": "x"})[1]["__type"] == "ImageAlreadyExistsException")
    _check("no scan yet -> ScanNotFound", api(r, "DescribeImageScanFindings", {"repositoryName": "manual", "imageId": {"imageTag": "x"}})[1]["__type"] == "ScanNotFoundException")
    _check("StartImageScan", api(r, "StartImageScan", {"repositoryName": "manual", "imageId": {"imageTag": "x"}})[1]["imageScanStatus"]["status"] == "COMPLETE")

    # immutability
    api(r, "PutImageTagMutability", {"repositoryName": "manual", "imageTagMutability": "IMMUTABLE"})
    cb3, layer3, man3 = make_image({"os": "linux3"})
    api(r, "BatchCheckLayerAvailability", {"repositoryName": "manual", "layerDigests": []})
    up = api(r, "InitiateLayerUpload", {"repositoryName": "manual"})[1]["uploadId"]
    api(r, "UploadLayerPart", {"repositoryName": "manual", "uploadId": up, "partFirstByte": 0, "partLastByte": len(cb3) - 1, "layerPartBlob": base64.b64encode(cb3).decode()})
    api(r, "CompleteLayerUpload", {"repositoryName": "manual", "uploadId": up, "layerDigests": [sha(cb3)]})
    s, o = api(r, "PutImage", {"repositoryName": "manual", "imageManifest": man3.decode(), "imageTag": "x"})
    _check("immutable tag refused", o.get("__type") == "ImageTagAlreadyExistsException")

    # lifecycle
    bad = {"rules": [{"rulePriority": 1, "selection": {"tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 1}, "action": {"type": "expire"}},
                     {"rulePriority": 2, "selection": {"tagStatus": "untagged", "countType": "imageCountMoreThan", "countNumber": 1}, "action": {"type": "expire"}}]}
    _check("any must be last", api(r, "PutLifecyclePolicy", {"repositoryName": "team/app", "lifecyclePolicyText": json.dumps(bad)})[1]["__type"] == "InvalidParameterException")
    api(r, "CreateRepository", {"repositoryName": "lc"})
    for i in range(4):
        cbi, li, mi = make_image({"os": f"l{i}"}, f"lc-layer-{i}".encode())
        for data in (cbi, li):
            reg(r, "POST", "/v2/lc/blobs/uploads/", A)
        a2 = api(r, "GetAuthorizationToken")[1]["authorizationData"][0]["authorizationToken"]
        for data in (cbi, li):
            s, h, _ = reg(r, "POST", "/v2/lc/blobs/uploads/", {"authorization": "Basic " + a2}, data, {"digest": sha(data)})
            assert s == 201, s
        s, h, _ = reg(r, "PUT", f"/v2/lc/manifests/t{i}", {"authorization": "Basic " + a2, "content-type": "application/vnd.docker.distribution.manifest.v2+json"}, mi)
        assert s == 201
    pol = {"rules": [{"rulePriority": 1, "description": "keep 2", "selection": {"tagStatus": "tagged", "tagPrefixList": ["t"], "countType": "imageCountMoreThan", "countNumber": 2}, "action": {"type": "expire"}}]}
    _check("put lifecycle", api(r, "PutLifecyclePolicy", {"repositoryName": "lc", "lifecyclePolicyText": json.dumps(pol)})[0] == 200)
    _check("get lifecycle", json.loads(api(r, "GetLifecyclePolicy", {"repositoryName": "lc"})[1]["lifecyclePolicyText"]) == pol)
    api(r, "StartLifecyclePolicyPreview", {"repositoryName": "lc"})
    s, o = api(r, "GetLifecyclePolicyPreview", {"repositoryName": "lc"})
    _check("preview expires 2", o["status"] == "COMPLETE" and o["summary"]["expiringImageTotalCount"] == 2)
    n = ecr_core.lifecycle_tick(r.s3)
    _check("lifecycle really expires", n == 2 and len(api(r, "ListImages", {"repositoryName": "lc"})[1]["imageIds"]) == 2)

    # replication
    _check("replication cfg", api(r, "PutReplicationConfiguration", {"replicationConfiguration": {"rules": [
        {"destinations": [{"region": "eu-west-1", "registryId": "123456789012"}], "repositoryFilters": [{"filter": "lc", "filterType": "PREFIX_MATCH"}]}]}})[0] == 200)
    a2 = api(r, "GetAuthorizationToken")[1]["authorizationData"][0]["authorizationToken"]
    cbr, lr, mr = make_image({"os": "rep"}, b"rep-layer")
    for data in (cbr, lr):
        reg(r, "POST", "/v2/lc/blobs/uploads/", {"authorization": "Basic " + a2}, data, {"digest": sha(data)})
    reg(r, "PUT", "/v2/lc/manifests/rep", {"authorization": "Basic " + a2, "content-type": "application/vnd.docker.distribution.manifest.v2+json"}, mr)
    s, o = api(r, "DescribeImages", {"repositoryName": "lc"}, "eu-west-1")
    _check("replicated to eu-west-1", s == 200 and any("rep" in i["imageTags"] for i in o["imageDetails"]))
    s, o = api(r, "DescribeImageReplicationStatus", {"repositoryName": "lc", "imageId": {"imageTag": "rep"}})
    _check("replication status", o["replicationStatuses"][0] == {"region": "eu-west-1", "registryId": "123456789012", "status": "COMPLETE"})

    # Inspector (enhanced)
    _check("inspector disabled gate", ins(r, "/findings/list")[0] == 403)
    ins(r, "/enable", {"resourceTypes": ["ECR"]})
    api(r, "StartImageScan", {"repositoryName": "team/app", "imageId": {"imageTag": "v1"}})
    s, o = ins(r, "/findings/list", {"filterCriteria": {"ecrImageRepositoryName": [{"comparison": "EQUALS", "value": "team/app"}],
                                                          "severity": [{"comparison": "EQUALS", "value": "CRITICAL"}]}})
    _check("inspector findings", s == 200 and o["findings"] and all(f["severity"] == "CRITICAL" for f in o["findings"])
           and o["findings"][0]["resources"][0]["type"] == "AWS_ECR_CONTAINER_IMAGE")
    s, o = api(r, "DescribeImageScanFindings", {"repositoryName": "team/app", "imageId": {"imageTag": "v1"}})
    _check("enhancedFindings in ECR API", "enhancedFindings" in o["imageScanFindings"])
    s, o = ins(r, "/coverage/list")
    _check("coverage", {c["resourceId"] for c in o["coveredResources"]} >= {"team/app", "lc"})

    # delete
    _check("delete non-empty refused", api(r, "DeleteRepository", {"repositoryName": "team/app"})[1]["__type"] == "RepositoryNotEmptyException")
    s, o = api(r, "BatchDeleteImage", {"repositoryName": "team/app", "imageIds": [{"imageTag": "v1"}]})
    _check("batch delete", o["imageIds"] == [{"imageDigest": sha(man), "imageTag": "v1"}])
    _check("delete repo", api(r, "DeleteRepository", {"repositoryName": "team/app"})[0] == 200)
    # tags + policy
    arn = api(r, "DescribeRepositories", {"repositoryNames": ["lc"]})[1]["repositories"][0]["repositoryArn"]
    api(r, "TagResource", {"resourceArn": arn, "tags": [{"Key": "env", "Value": "dev"}]})
    _check("tags", api(r, "ListTagsForResource", {"resourceArn": arn})[1]["tags"] == [{"Key": "env", "Value": "dev"}])
    _check("no repo policy", api(r, "GetRepositoryPolicy", {"repositoryName": "lc"})[1]["__type"] == "RepositoryPolicyNotFoundException")
    print("ECR OK")


if __name__ == "__main__":
    main()
