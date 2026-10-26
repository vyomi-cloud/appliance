"""ECR core conformance — host CPython + Pyodide (the Nano `nano-cores` suite).

The same engine file serves the appliance and Nano. Asserts the native ECR JSON
protocol semantics through BOTH the core dispatcher and the AwsWireRouter front
door (X-Amz-Target AmazonEC2ContainerRegistry_V20150921.*, SigV4 scope `ecr`):
repository lifecycle + errors, layer upload digest verification, PutImage layer
checks, tag moves / immutability, batch delete, policies, scans, console facade.
"""
import base64
import hashlib
import json

try:
    from core import ecr_core as ecr
    from core.aws_wire_router import AwsWireRouter
except ImportError:  # pragma: no cover - Pyodide flat layout
    import ecr_core as ecr  # type: ignore
    from aws_wire_router import AwsWireRouter  # type: ignore

T = ecr.TARGET_PREFIX + "."


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _sha(b):
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _manifest(digest, size):
    return json.dumps({"schemaVersion": 2, "mediaType": ecr.DEFAULT_MANIFEST_MT,
                       "config": {"digest": digest, "size": size},
                       "layers": [{"digest": digest, "size": size}]})


def _upload(s, repo, blob):
    uid = ecr.dispatch(s, T + "InitiateLayerUpload", {"repositoryName": repo}).body["uploadId"]
    r = ecr.dispatch(s, T + "UploadLayerPart", {"repositoryName": repo, "uploadId": uid, "partFirstByte": 0,
                                                "partLastByte": len(blob) - 1,
                                                "layerPartBlob": base64.b64encode(blob).decode()})
    assert r.status == 200, r.body
    return ecr.dispatch(s, T + "CompleteLayerUpload", {"repositoryName": repo, "uploadId": uid, "layerDigests": [_sha(blob)]})


def run(store=None):
    s = store or ecr.EcrStore()

    def call(op, **kw):
        return ecr.dispatch(s, T + op, kw)

    r = call("CreateRepository", repositoryName="team/app", tags=[{"Key": "a", "Value": "b"}])
    _check("CreateRepository 200 with ARN + URI", r.status == 200 and r.body["repository"]["repositoryArn"].endswith("repository/team/app")
           and r.body["repository"]["repositoryUri"].endswith("/team/app"))
    _check("duplicate → RepositoryAlreadyExistsException", call("CreateRepository", repositoryName="team/app").body["__type"] == "RepositoryAlreadyExistsException")
    _check("bad name → InvalidParameterException", call("CreateRepository", repositoryName="Bad_Name").body["__type"] == "InvalidParameterException")
    _check("missing repo → RepositoryNotFoundException", call("DescribeRepositories", repositoryNames=["x/y"]).body["__type"] == "RepositoryNotFoundException")
    _check("unknown op → UnknownOperationException", call("Nope").body["__type"] == "UnknownOperationException")

    blob = b"layer-bytes"
    done = _upload(s, "team/app", blob)
    _check("CompleteLayerUpload returns the sha256 digest", done.status == 200 and done.body["layerDigest"] == _sha(blob))
    uid = call("InitiateLayerUpload", repositoryName="team/app").body["uploadId"]
    call("UploadLayerPart", repositoryName="team/app", uploadId=uid, partFirstByte=0, partLastByte=2,
         layerPartBlob=base64.b64encode(b"abc").decode())
    _check("wrong digest → InvalidLayerException", call("CompleteLayerUpload", repositoryName="team/app", uploadId=uid,
                                                          layerDigests=[_sha(b"zzz")]).body["__type"] == "InvalidLayerException")
    _check("PutImage with an unknown layer → LayersNotFoundException",
           call("PutImage", repositoryName="team/app", imageManifest=_manifest(_sha(b"none"), 1), imageTag="x").body["__type"] == "LayersNotFoundException")

    man = _manifest(_sha(blob), len(blob))
    put = call("PutImage", repositoryName="team/app", imageManifest=man, imageTag="v1")
    _check("PutImage returns digest + tag", put.status == 200 and put.body["image"]["imageId"]["imageDigest"] == _sha(man.encode()))
    _check("same tag + digest → ImageAlreadyExistsException",
           call("PutImage", repositoryName="team/app", imageManifest=man, imageTag="v1").body["__type"] == "ImageAlreadyExistsException")
    man2 = _manifest(_sha(blob), len(blob) + 0).replace("schemaVersion\": 2", "schemaVersion\": 2 ")
    call("PutImage", repositoryName="team/app", imageManifest=man2, imageTag="v1")   # mutable: tag moves
    ids = call("ListImages", repositoryName="team/app").body["imageIds"]
    _check("MUTABLE re-tag moves the tag (old digest left untagged)", len(ids) == 2)
    d = call("DescribeImages", repositoryName="team/app").body["imageDetails"]
    _check("DescribeImages sizes = config + layers", all(x["imageSizeInBytes"] == 2 * len(blob) for x in d))
    call("PutImageTagMutability", repositoryName="team/app", imageTagMutability="IMMUTABLE")
    _check("IMMUTABLE re-tag → ImageTagAlreadyExistsException",
           call("PutImage", repositoryName="team/app", imageManifest=man, imageTag="v1").body["__type"] == "ImageTagAlreadyExistsException")
    page = call("ListImages", repositoryName="team/app", maxResults=1).body
    _check("ListImages paginates with nextToken", len(page["imageIds"]) == 1 and "nextToken" in page)

    call("StartImageScan", repositoryName="team/app", imageId={"imageTag": "v1"})
    _check("scan findings COMPLETE", call("DescribeImageScanFindings", repositoryName="team/app", imageId={"imageTag": "v1"}).body["imageScanStatus"]["status"] == "COMPLETE")
    _check("no policy → RepositoryPolicyNotFoundException", call("GetRepositoryPolicy", repositoryName="team/app").body["__type"] == "RepositoryPolicyNotFoundException")
    call("SetRepositoryPolicy", repositoryName="team/app", policyText='{"Version":"2012-10-17","Statement":[]}')
    _check("repository policy round-trips", call("GetRepositoryPolicy", repositoryName="team/app").body["policyText"] == '{"Version":"2012-10-17","Statement":[]}')
    _check("empty lifecycle rules → ValidationException", call("PutLifecyclePolicy", repositoryName="team/app", lifecyclePolicyText='{"rules":[]}').body["__type"] == "ValidationException")
    call("TagResource", resourceArn=r.body["repository"]["repositoryArn"], tags=[{"Key": "c", "Value": "d"}])
    _check("tags merge", len(call("ListTagsForResource", resourceArn=r.body["repository"]["repositoryArn"]).body["tags"]) == 2)
    tok = call("GetAuthorizationToken").body["authorizationData"][0]
    _check("auth token is AWS:<password>", base64.b64decode(tok["authorizationToken"]).startswith(b"AWS:"))

    row = ecr.console_row(s, "team/app")
    _check("console row fills every column", all(row[k] not in ("", None) for k in
           ("name", "uri", "created", "tag_mutability", "scan_on_push", "encryption", "image_count", "size", "last_push", "lifecycle_policy", "permissions")))
    _check("DeleteRepository with images → RepositoryNotEmptyException", call("DeleteRepository", repositoryName="team/app").body["__type"] == "RepositoryNotEmptyException")
    bd = call("BatchDeleteImage", repositoryName="team/app", imageIds=[{"imageTag": "v1"}, {"imageTag": "ghost"}]).body
    _check("BatchDeleteImage removes the tag, reports the missing one", len(bd["imageIds"]) == 1 and bd["failures"][0]["failureCode"] == "ImageNotFound")
    _check("DeleteRepository force", call("DeleteRepository", repositoryName="team/app", force=True).status == 200 and not s.repositories)

    # ── the native-wire front door (what the relay / appliance root serves) ──
    rt = AwsWireRouter()
    hdr = {"x-amz-target": T + "CreateRepository",
           "authorization": "AWS4-HMAC-SHA256 Credential=AK/20260101/us-east-1/ecr/aws4_request, SignedHeaders=host, Signature=0"}
    out = rt.handle("POST", "/", {}, hdr, json.dumps({"repositoryName": "wire/app"}).encode())
    _check("router: ecr JSON 1.1 CreateRepository", out["status"] == 200 and out["headers"]["content-type"] == "application/x-amz-json-1.1"
           and json.loads(out["body"])["repository"]["repositoryName"] == "wire/app")
    out = rt.handle("POST", "/", {}, hdr, json.dumps({"repositoryName": "wire/app"}).encode())
    _check("router: error body carries __type", json.loads(out["body"])["__type"] == "RepositoryAlreadyExistsException")


def test_ecr_core():
    run()


if __name__ == "__main__":
    run()
    print("ECR core: all checks passed")
