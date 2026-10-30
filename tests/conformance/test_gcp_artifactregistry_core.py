"""GCP Artifact Registry core — native v1 REST behaviour (shared with Nano).

Run:  PYTHONPATH=. python3 tests/conformance/test_gcp_artifactregistry_core.py
"""
import json
import sys

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
    out = router.handle("POST", B, {"repositoryId": "w1"}, {"content-type": "application/json"},
                        json.dumps({"format": "MAVEN"}).encode())
    assert out["status"] == 200 and json.loads(out["body"])["done"]
    assert router.handle("GET", B + "/w1", {}, {}, b"")["status"] == 200


def test_list_across_locations():
    st = ar.ArtifactRegistryStore()
    call(st, "POST", "/v1/projects/p/locations/us-central1/repositories", {"repositoryId": "r1"}, {"format": "DOCKER"})
    call(st, "POST", "/v1/projects/p/locations/europe-west1/repositories", {"repositoryId": "r2"}, {"format": "NPM"})
    code, page = call(st, "GET", "/v1/projects/p/locations/-/repositories")
    names = {r["name"].rsplit("/", 1)[-1] for r in page["repositories"]}
    assert code == 200 and names == {"r1", "r2"}


def test_project_settings():
    st = ar.ArtifactRegistryStore()
    code, s = call(st, "GET", "/v1/projects/p/projectSettings")
    assert code == 200 and s["name"] == "projects/p/projectSettings" and s["legacyRedirectionState"] == "REDIRECTION_FROM_GCR_IO_UNSPECIFIED"
    code, s = call(st, "PATCH", "/v1/projects/p/projectSettings", None, {"legacyRedirectionState": "REDIRECTION_FROM_GCR_IO_ENABLED"})
    assert code == 200 and s["legacyRedirectionState"] == "REDIRECTION_FROM_GCR_IO_ENABLED"
    assert call(st, "GET", "/v1/projects/p/projectSettings")[1]["legacyRedirectionState"] == "REDIRECTION_FROM_GCR_IO_ENABLED"
    assert call(st, "PATCH", "/v1/projects/p/projectSettings", None, {"legacyRedirectionState": "BOGUS"})[0] == 400


def test_push_sample_verb_and_cleanup_vuln_config():
    st = ar.ArtifactRegistryStore()
    call(st, "POST", B, {"repositoryId": "r1"}, {"format": "DOCKER"})
    code, out = call(st, "POST", B + "/r1:pushSample", None, {"image": "demo-app", "tag": "v1"})
    assert code == 200 and out["version"].endswith("/versions/" + out["version"].rsplit("/", 1)[-1])
    imgs = call(st, "GET", B + "/r1/dockerImages")[1]["dockerImages"]
    assert imgs and imgs[0]["tags"] == ["v1"]
    assert call(st, "POST", B + "/bogus:pushSample", None, {})[0] == 404
    code, repo = call(st, "PATCH", B + "/r1", {"updateMask": "cleanupPolicyDryRun,vulnerabilityScanningConfig"},
                      {"cleanupPolicyDryRun": True, "vulnerabilityScanningConfig": {"enablementConfig": "DISABLED"}})
    assert code == 200 and repo["cleanupPolicyDryRun"] is True and repo["vulnerabilityScanningConfig"]["enablementConfig"] == "DISABLED"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = []
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            failed.append(t.__name__)
            print(f"FAIL {t.__name__}: {e!r}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
