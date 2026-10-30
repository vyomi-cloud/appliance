"""GCP Artifact Registry core — native v1 REST behaviour (shared with Nano)."""
import json

from core import gcp_artifactregistry_core as ar
from core.aws_wire_router import AwsWireRouter

B = "/v1/projects/p/locations/us-central1/repositories"
R = "projects/p/locations/us-central1/repositories/r1"


def call(st, method, path, query=None, body=None):
    r = ar.dispatch(st, method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
    return r.status, json.loads(r.body)


def test_repository_lifecycle_and_lro():
    st = ar.ArtifactRegistryStore()
    code, op = call(st, "POST", B, {"repositoryId": "r1"}, {"format": "DOCKER", "description": "d"})
    assert code == 200 and op["done"] and op["response"]["name"] == R
    assert call(st, "GET", "/v1/" + op["name"])[1]["name"] == op["name"]
    assert call(st, "POST", B, {"repositoryId": "r1"}, {"format": "DOCKER"})[1]["error"]["status"] == "ALREADY_EXISTS"
    assert call(st, "GET", B)[1]["repositories"][0]["format"] == "DOCKER"
    code, repo = call(st, "PATCH", B + "/r1", {"updateMask": "description,labels"}, {"description": "new", "labels": {"a": "b"}})
    assert repo["description"] == "new" and repo["labels"] == {"a": "b"}
    assert call(st, "DELETE", B + "/r1")[1]["done"]
    assert call(st, "GET", B + "/r1")[1]["error"]["status"] == "NOT_FOUND"


def test_validation():
    st = ar.ArtifactRegistryStore()
    assert call(st, "POST", B, {"repositoryId": "Bad_ID"}, {"format": "DOCKER"})[0] == 400
    assert call(st, "POST", B, {"repositoryId": "ok"}, {})[0] == 400          # format required
    assert call(st, "POST", B, {}, {"format": "DOCKER"})[0] == 400


def test_packages_tags_images_and_iam():
    st = ar.ArtifactRegistryStore()
    call(st, "POST", B, {"repositoryId": "r1"}, {"format": "DOCKER"})
    ver = ar.ingest_image(st, R, "app", "v1")
    digest = ver["name"].rsplit("/", 1)[-1]
    assert call(st, "GET", B + "/r1/packages")[1]["packages"][0]["displayName"] == "app"
    imgs = call(st, "GET", B + "/r1/dockerImages")[1]["dockerImages"]
    assert imgs[0]["tags"] == ["v1"] and imgs[0]["uri"].endswith("/p/r1/app@" + digest)
    assert call(st, "GET", B + f"/r1/dockerImages/app@{digest}")[0] == 200
    code, tag = call(st, "POST", B + "/r1/packages/app/tags", {"tagId": "stable"}, {"version": ver["name"]})
    assert code == 200 and tag["name"].endswith("/tags/stable")
    assert len(call(st, "GET", B + "/r1/packages/app/tags")[1]["tags"]) == 2
    assert call(st, "GET", B + "/r1/packages/app/versions")[1]["versions"][0]["relatedTags"]
    assert call(st, "GET", B + "/r1")[1]["sizeBytes"] == "5242880"
    pol = call(st, "POST", B + "/r1:setIamPolicy", None, {"policy": {"bindings": [{"role": "roles/artifactregistry.reader", "members": ["allUsers"]}]}})[1]
    assert call(st, "POST", B + "/r1:getIamPolicy")[1]["etag"] == pol["etag"]
    assert call(st, "POST", B + "/r1:testIamPermissions", None, {"permissions": ["a.b"]})[1] == {"permissions": ["a.b"]}
    call(st, "DELETE", B + "/r1/packages/app/versions/" + digest)
    assert call(st, "GET", B + "/r1/packages/app/tags")[1].get("tags") == []


def test_pagination():
    st = ar.ArtifactRegistryStore()
    for i in range(5):
        call(st, "POST", B, {"repositoryId": f"r{i}"}, {"format": "NPM"})
    code, page = call(st, "GET", B, {"pageSize": "2"})
    assert len(page["repositories"]) == 2 and page["nextPageToken"]
    assert len(call(st, "GET", B, {"pageSize": "10", "pageToken": page["nextPageToken"]})[1]["repositories"]) == 3


def test_wire_router_routes_artifactregistry():
    router = AwsWireRouter()
    rb = B.replace("/projects/p/", "/projects/nano-project/")   # the router serves ONE project
    out = router.handle("POST", rb, {"repositoryId": "w1"}, {"content-type": "application/json"},
                        json.dumps({"format": "MAVEN"}).encode())
    assert out["status"] == 200 and json.loads(out["body"])["done"]
    assert router.handle("GET", rb + "/w1", {}, {}, b"")["status"] == 200
