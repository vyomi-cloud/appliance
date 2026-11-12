"""EC2 Image Builder via AwsWireRouter (hermetic: the container runner is stubbed; the no-builder path is the real default).

Run: PYTHONPATH=. ../appliance/.venv/bin/python tests/conformance/test_imagebuilder_core.py
"""
import json
from urllib.parse import quote

from core.aws_wire_router import AwsWireRouter
from core import imagebuilder_core as ib

AUTH = "AWS4-HMAC-SHA256 Credential=T/20261105/us-east-1/imagebuilder/aws4_request, SignedHeaders=host, Signature=0"
EC2 = "AWS4-HMAC-SHA256 Credential=T/20261105/us-east-1/ec2/aws4_request, SignedHeaders=host, Signature=0"


def _check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} {detail}")
    print(f"  ok  {name}")


def call(r, method, op, body=None, query=None):
    out = r.handle(method, "/" + op, query or {}, {"authorization": AUTH, "content-type": "application/json"}, json.dumps(body or {}).encode())
    return out["status"], (json.loads(out["body"]) if out["body"] else {})


DOC = """name: install-nginx
description: Install nginx
schemaVersion: 1.0
parameters:
  - greeting:
      type: string
      default: hello
phases:
  - name: build
    steps:
      - name: Install
        action: ExecuteBash
        inputs:
          commands:
            - apt-get update
            - echo {{ greeting }} > /etc/motd
  - name: validate
    steps:
      - name: Check
        action: ExecuteBash
        inputs:
          commands:
            - test -f /etc/motd
"""
# the YAML `parameters:` shape real docs use is `- name: greeting` maps; use that form for the real test
DOC = DOC.replace("  - greeting:\n      type: string\n      default: hello", "  - name: greeting\n    type: string\n    default: hello")


def main():
    r = AwsWireRouter()
    # --- document parsing / validation
    d = ib.parse_document(DOC)
    _check("yaml parsed", d["phases"][0]["steps"][0]["inputs"]["commands"][1] == "echo {{ greeting }} > /etc/motd" and d["parameters"][0]["default"] == "hello")
    _check("block scalar", ib.parse_document("a: |\n  x\n  y\nb: 1\n") == {"a": "x\ny\n", "b": 1})
    s, o = call(r, "PUT", "CreateComponent", {"name": "bad", "semanticVersion": "1.0", "platform": "Linux", "data": DOC})
    _check("bad semver", s == 400 and "major.minor.patch" in o["message"])
    s, o = call(r, "PUT", "CreateComponent", {"name": "bad", "semanticVersion": "1.0.0", "platform": "Linux", "data": "schemaVersion: 1.0\nphases:\n  - name: build\n    steps:\n      - name: x\n        action: Nope\n"})
    _check("unknown action rejected", s == 400 and "unknown action" in o["message"])
    s, o = call(r, "PUT", "CreateComponent", {"name": "bad", "semanticVersion": "1.0.0", "platform": "Linux", "data": "schemaVersion: 1.0\nphases:\n  - name: build\n    steps:\n      - name: x\n        action: ExecuteBash\n"})
    _check("ExecuteBash needs commands", s == 400)
    s, o = call(r, "PUT", "CreateComponent", {"name": "Install-Nginx", "semanticVersion": "1.0.0", "platform": "Linux", "data": DOC, "tags": {"team": "a"}})
    carn = o["componentBuildVersionArn"]
    _check("create component", s == 200 and carn == "arn:aws:imagebuilder:us-east-1:123456789012:component/install-nginx/1.0.0/1")
    s, o = call(r, "PUT", "CreateComponent", {"name": "install-nginx", "semanticVersion": "1.0.0", "platform": "Linux", "data": DOC})
    _check("duplicate version", o.get("__type") == "ResourceAlreadyExistsException")
    s, o = call(r, "GET", "GetComponent", query={"componentBuildVersionArn": carn})
    _check("get component", o["component"]["name"] == "Install-Nginx" and "ExecuteBash" in o["component"]["data"])
    s, o = call(r, "POST", "ListComponents", {"owner": "Self"})
    _check("list self", [c["name"] for c in o["componentVersionList"]] == ["Install-Nginx"])
    s, o = call(r, "POST", "ListComponents", {"owner": "Amazon"})
    _check("list amazon-managed", {c["name"] for c in o["componentVersionList"]} == {"update-linux", "reboot-linux", "simple-boot-test-linux"})

    # --- recipe
    s, o = call(r, "PUT", "CreateImageRecipe", {"name": "web", "semanticVersion": "1.0.0", "parentImage": "arn:aws:imagebuilder:us-east-1:aws:image/ubuntu-server-22-lts-x86/x.x.x",
                                                "components": [{"componentArn": "arn:aws:imagebuilder:us-east-1:123456789012:component/missing/1.0.0/1"}]})
    _check("recipe with missing component", s == 404)
    s, o = call(r, "PUT", "CreateImageRecipe", {"name": "web", "semanticVersion": "1.0.0", "parentImage": "arn:aws:imagebuilder:us-east-1:aws:image/ubuntu-server-22-lts-x86/x.x.x",
                                                "components": [{"componentArn": "arn:aws:imagebuilder:us-east-1:aws:component/update-linux/x.x.x"},
                                                               {"componentArn": carn, "parameters": [{"name": "greeting", "value": ["hi"]}]}]})
    rarn = o["imageRecipeArn"]
    _check("create recipe", s == 200 and rarn.endswith("image-recipe/web/1.0.0"))
    s, o = call(r, "PUT", "CreateImageRecipe", {"name": "web2", "semanticVersion": "1.0.0", "parentImage": "ubuntu", "components": [{"componentArn": carn, "parameters": [{"name": "nope", "value": ["x"]}]}]})
    _check("unknown component parameter", s == 400)
    s, o = call(r, "DELETE", "DeleteComponent", query={"componentBuildVersionArn": carn})
    _check("component in use", o.get("__type") == "ResourceDependencyException")

    # --- infra + dist
    s, o = call(r, "PUT", "CreateInfrastructureConfiguration", {"name": "infra", "instanceTypes": ["t3.medium"]})
    _check("infra needs profile", s == 400)
    s, o = call(r, "PUT", "CreateInfrastructureConfiguration", {"name": "infra", "instanceProfileName": "ib-profile", "instanceTypes": ["t3.medium"], "securityGroupIds": ["sg-1"]})
    _check("sg needs subnet", s == 400)
    s, o = call(r, "PUT", "CreateInfrastructureConfiguration", {"name": "infra", "instanceProfileName": "ib-profile", "instanceTypes": ["t3.medium"]})
    iarn = o["infrastructureConfigurationArn"]
    _check("create infra", s == 200)
    s, o = call(r, "PUT", "CreateDistributionConfiguration", {"name": "dist", "distributions": [{"region": "us-east-1", "amiDistributionConfiguration": {
        "name": "web-{{ imagebuilder:buildDate }}", "amiTags": {"built-by": "imagebuilder"}, "launchPermission": {"userIds": ["111122223333"]}}}]})
    darn = o["distributionConfigurationArn"]
    _check("create dist", s == 200)

    # --- build with NO container builder (the Nano / no-docker default): honest FAILED, no AMI
    s, o = call(r, "PUT", "CreateImage", {"imageRecipeArn": rarn, "infrastructureConfigurationArn": iarn, "distributionConfigurationArn": darn})
    iarn1 = o["imageBuildVersionArn"]
    s, o = call(r, "GET", "GetImage", query={"imageBuildVersionArn": iarn1})
    _check("no builder -> FAILED with reason", o["image"]["state"]["status"] == "FAILED" and "No container builder" in o["image"]["state"]["reason"])
    _check("no AMI registered on failure", not o["image"].get("outputResources"))

    # --- build with a stubbed container runner
    seen = {}

    def runner(st, spec):
        seen["df"] = spec["dockerfile"]
        return {"ok": True, "tag": spec["tag"], "digest": "sha256:abc", "size": 123456789, "log": ["stub build ok"]}
    ib.set_runner(runner)
    s, o = call(r, "PUT", "CreateImage", {"imageRecipeArn": rarn, "infrastructureConfigurationArn": iarn, "distributionConfigurationArn": darn, "tags": {"k": "v"}})
    iarn2 = o.get("imageBuildVersionArn", "")
    _check("second build is build 2", iarn2.endswith(":image/web/1.0.0/2"), o)
    s, o = call(r, "GET", "GetImage", query={"imageBuildVersionArn": iarn2})
    img = o["image"]
    _check("AVAILABLE with AMI output", img["state"]["status"] == "AVAILABLE" and img["outputResources"]["amis"][0]["image"].startswith("ami-"))
    _check("Dockerfile compiled from components", seen["df"].startswith("FROM ubuntu:22.04") and "apt-get -y upgrade" in seen["df"] and "base64 -d | sh" in seen["df"])
    _check("parameter override baked in", "echo hi > /etc/motd" in __import__("base64").b64decode(
        [l for l in seen["df"].splitlines() if l.startswith("RUN echo ")][0].split()[2]).decode())
    ami = img["outputResources"]["amis"][0]["image"]
    out = r.handle("POST", "/", {}, {"authorization": EC2, "content-type": "application/x-www-form-urlencoded"}, f"Action=DescribeImages&Version=2016-11-15&ImageId.1={ami}".encode())
    body = out["body"].decode() if isinstance(out["body"], bytes) else out["body"]
    _check("AMI visible in EC2 DescribeImages with distribution name/tags/permissions", ami in body and "web-20" in body and "imagebuilder" in body and "111122223333" in body, body[:300])
    s, o = call(r, "GET", "VyomiGetImageBuildLog", query={"imageBuildVersionArn": iarn2})
    _check("build log kept", any("stub build ok" in l for l in o["log"]))

    # --- unsupported action fails honestly
    s, o = call(r, "PUT", "CreateComponent", {"name": "dl", "semanticVersion": "1.0.0", "platform": "Linux",
                                              "data": "schemaVersion: 1.0\nphases:\n  - name: build\n    steps:\n      - name: dl\n        action: WebDownload\n        inputs:\n          - source: https://x\n            destination: /tmp/x\n"})
    s, o = call(r, "PUT", "CreateImageRecipe", {"name": "dlr", "semanticVersion": "1.0.0", "parentImage": "ami-123", "components": [{"componentArn": "arn:aws:imagebuilder:us-east-1:123456789012:component/dl/1.0.0/1"}]})
    s, o = call(r, "PUT", "CreateImage", {"imageRecipeArn": o["imageRecipeArn"], "infrastructureConfigurationArn": iarn})
    s, o = call(r, "GET", "GetImage", query={"imageBuildVersionArn": o["imageBuildVersionArn"]})
    _check("unsupported action -> FAILED", o["image"]["state"]["status"] == "FAILED" and "WebDownload" in o["image"]["state"]["reason"])

    # --- failing build
    ib.set_runner(lambda st, spec: {"ok": False, "log": ["RUN failed"], "error": "BuildKit build failed (exit 1)"})
    s, o = call(r, "PUT", "CreateImage", {"imageRecipeArn": rarn, "infrastructureConfigurationArn": iarn})
    s, o = call(r, "GET", "GetImage", query={"imageBuildVersionArn": o["imageBuildVersionArn"]})
    _check("failed build surfaced", o["image"]["state"] == {"status": "FAILED", "reason": "BuildKit build failed (exit 1)"})

    # --- pipeline
    ib.set_runner(runner)
    bad = {"name": "pipe", "imageRecipeArn": rarn, "infrastructureConfigurationArn": iarn, "schedule": {"scheduleExpression": "every day"}}
    _check("bad schedule", call(r, "PUT", "CreateImagePipeline", bad)[0] == 400)
    s, o = call(r, "PUT", "CreateImagePipeline", {**bad, "schedule": {"scheduleExpression": "cron(0 0 * * ? *)"}, "distributionConfigurationArn": darn, "tags": {"p": "1"}})
    parn = o["imagePipelineArn"]
    _check("create pipeline", s == 200 and parn.endswith("image-pipeline/pipe"))
    _check("duplicate pipeline", call(r, "PUT", "CreateImagePipeline", {**bad, "schedule": {"scheduleExpression": "cron(0 0 * * ? *)"}})[1].get("__type") == "ResourceAlreadyExistsException")
    s, o = call(r, "PUT", "StartImagePipelineExecution", {"imagePipelineArn": parn})
    _check("pipeline execution builds an image", s == 200 and o["imageBuildVersionArn"].endswith("/web/1.0.0/4"))
    s, o = call(r, "POST", "ListImagePipelineImages", {"imagePipelineArn": parn})
    _check("pipeline images", len(o["imageSummaryList"]) == 1 and o["imageSummaryList"][0]["state"]["status"] == "AVAILABLE")
    call(r, "PUT", "UpdateImagePipeline", {"imagePipelineArn": parn, "imageRecipeArn": rarn, "infrastructureConfigurationArn": iarn, "status": "DISABLED"})
    s, o = call(r, "PUT", "StartImagePipelineExecution", {"imagePipelineArn": parn})
    _check("disabled pipeline refuses", o.get("__type") == "InvalidRequestException")
    s, o = call(r, "DELETE", "DeleteImageRecipe", query={"imageRecipeArn": rarn})
    _check("recipe in use by pipeline", o.get("__type") == "ResourceDependencyException")
    s, o = call(r, "DELETE", "DeleteInfrastructureConfiguration", query={"infrastructureConfigurationArn": iarn})
    _check("infra in use", o.get("__type") == "ResourceDependencyException")

    # --- tags + lists + cancel + delete
    s, o = call(r, "POST", "tags/" + quote(parn, safe=""), {"tags": {"env": "dev"}})
    s, o = call(r, "GET", "tags/" + quote(parn, safe=""))
    _check("tags round-trip", o["tags"] == {"p": "1", "env": "dev"})
    _check("cancel finished build refused", call(r, "PUT", "CancelImageCreation", {"imageBuildVersionArn": iarn2})[1].get("__type") == "InvalidRequestException")
    s, o = call(r, "POST", "ListImages", {})
    _check("ListImages versions", [i["name"] for i in o["imageVersionList"]] == ["dlr", "web"])
    s, o = call(r, "POST", "ListImageBuildVersions", {"imageVersionArn": "arn:aws:imagebuilder:us-east-1:123456789012:image/web/1.0.0"})
    _check("ListImageBuildVersions", len(o["imageSummaryList"]) == 4)
    _check("delete image", call(r, "DELETE", "DeleteImage", query={"imageBuildVersionArn": iarn1})[0] == 200 and call(r, "GET", "GetImage", query={"imageBuildVersionArn": iarn1})[0] == 404)
    _check("delete pipeline", call(r, "DELETE", "DeleteImagePipeline", query={"imagePipelineArn": parn})[0] == 200)
    ib.set_runner(None)
    print("imagebuilder: all ok")


if __name__ == "__main__":
    main()
