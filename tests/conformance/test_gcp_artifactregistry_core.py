"""GCP Artifact Registry core — native v1 REST behaviour (shared with Nano).

Run:  PYTHONPATH=. python3 tests/conformance/test_gcp_artifactregistry_core.py
"""
import json
import sys

from core import gcp_artifactregistry_core as ar
from core.aws_wire_router import AwsWireRouter

B = "/v1/projects/p/locations/us-central1/repositories"
R = "projects/p/locations/us-central1/repositories/r1"


def call(st, method, path, query=None, body=None, headers=None):
    r = ar.dispatch(st, method, path, query or {}, headers or {}, json.dumps(body).encode() if body is not None else b"")
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
    # testIamPermissions narrows the request to what the policy actually grants: "allUsers"
    # holds the reader role (get/list/downloadArtifacts), not an arbitrary made-up permission —
    # from a non-owner caller's perspective (the owner/no-header caller always sees everything).
    perms = call(st, "POST", B + "/r1:testIamPermissions", None,
                {"permissions": ["artifactregistry.repositories.get", "a.b"]},
                headers={"X-Cloudlearn-Principal": "someone@example.com"})[1]
    assert perms == {"permissions": ["artifactregistry.repositories.get"]}, perms
    call(st, "DELETE", B + "/r1/packages/app/versions/" + digest)
    # Deleting a package's last version drops the (now-empty) package too.
    assert call(st, "GET", B + "/r1/packages/app/tags")[0] == 404
    assert call(st, "GET", B + "/r1/packages")[1]["packages"] == []


def test_iam_policy_enforced_on_mutations():
    st = ar.ArtifactRegistryStore()
    call(st, "POST", B, {"repositoryId": "r1"}, {"format": "DOCKER"})
    ar.ingest_image(st, R, "app", "v1")
    OWNER = {}   # no X-Cloudlearn-Principal header: owner bypass, used to set the policy up
    call(st, "POST", B + "/r1:setIamPolicy", None,
        {"policy": {"bindings": [{"role": "roles/artifactregistry.repoAdmin", "members": ["user:admin@example.com"]},
                                 {"role": "roles/artifactregistry.reader", "members": ["user:viewer@example.com"]}]}},
        headers=OWNER)
    DENIED = {"X-Cloudlearn-Principal": "someone-else@example.com"}
    READER = {"X-Cloudlearn-Principal": "viewer@example.com"}
    ADMIN = {"X-Cloudlearn-Principal": "admin@example.com"}

    # Update: denied for an ungranted principal and a reader, allowed for the repoAdmin.
    assert call(st, "PATCH", B + "/r1", {"updateMask": "description"}, {"description": "x"}, DENIED)[0] == 403
    assert call(st, "PATCH", B + "/r1", {"updateMask": "description"}, {"description": "x"}, READER)[0] == 403
    code, repo = call(st, "PATCH", B + "/r1", {"updateMask": "description"}, {"description": "x"}, ADMIN)
    assert code == 200 and repo["description"] == "x"

    # pushSample (upload) and tag creation: denied for the reader, allowed for the repoAdmin.
    assert call(st, "POST", B + "/r1:pushSample", None, {"image": "app", "tag": "v2"}, READER)[0] == 403
    code, out = call(st, "POST", B + "/r1:pushSample", None, {"image": "app", "tag": "v2"}, ADMIN)
    assert code == 200, out
    ver = call(st, "GET", B + "/r1/packages/app/versions")[1]["versions"][0]["name"]
    assert call(st, "POST", B + "/r1/packages/app/tags", {"tagId": "t1"}, {"version": ver}, READER)[0] == 403
    assert call(st, "POST", B + "/r1/packages/app/tags", {"tagId": "t1"}, {"version": ver}, ADMIN)[0] == 200

    # Version/tag/package deletion: denied for the reader, allowed for the repoAdmin.
    assert call(st, "DELETE", B + "/r1/packages/app/tags/t1", None, None, READER)[0] == 403
    assert call(st, "DELETE", B + "/r1/packages/app/tags/t1", None, None, ADMIN)[0] == 200
    assert call(st, "DELETE", B + "/r1/packages/app", None, None, READER)[0] == 403
    assert call(st, "DELETE", B + "/r1/packages/app", None, None, ADMIN)[0] == 200

    # Repository delete: denied for the reader, allowed for the repoAdmin.
    assert call(st, "DELETE", B + "/r1", None, None, READER)[0] == 403
    assert call(st, "DELETE", B + "/r1", None, None, ADMIN)[0] == 200


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


def test_cleanup_policies_delete_matching_versions_enforced():
    st = ar.ArtifactRegistryStore()
    call(st, "POST", B, {"repositoryId": "r1"}, {"format": "DOCKER"})
    old = ar.ingest_image(st, R, "app", "old")
    fresh = ar.ingest_image(st, R, "app", "fresh")
    # Backdate the "old" version the way a real version would age — the engine has no
    # other way to fast-forward time.
    old["createTime"] = "2000-01-01T00:00:00.000000Z"
    # Reject malformed policies before they ever reach the store.
    assert call(st, "PATCH", B + "/r1", {"updateMask": "cleanupPolicies"},
                {"cleanupPolicies": {"p1": {"action": "BOGUS"}}})[0] == 400
    code, repo = call(st, "PATCH", B + "/r1", {"updateMask": "cleanupPolicies"},
                      {"cleanupPolicies": {"p1": {"action": "DELETE", "condition": {"olderThan": "86400s"}}}})
    assert code == 200 and repo["cleanupPolicies"]["p1"]["action"] == "DELETE"
    versions = call(st, "GET", B + "/r1/packages/app/versions")[1]["versions"]
    ids = {v["name"].rsplit("/", 1)[-1] for v in versions}
    assert ids == {fresh["name"].rsplit("/", 1)[-1]}, f"old version should have been swept: {ids}"

    # Dry run accepts the policy but enforces nothing.
    st2 = ar.ArtifactRegistryStore()
    call(st2, "POST", B, {"repositoryId": "r1"}, {"format": "DOCKER"})
    old2 = ar.ingest_image(st2, R, "app", "old")
    old2["createTime"] = "2000-01-01T00:00:00.000000Z"
    call(st2, "PATCH", B + "/r1", {"updateMask": "cleanupPolicies,cleanupPolicyDryRun"},
         {"cleanupPolicies": {"p1": {"action": "DELETE", "condition": {"olderThan": "86400s"}}}, "cleanupPolicyDryRun": True})
    versions2 = call(st2, "GET", B + "/r1/packages/app/versions")[1]["versions"]
    assert len(versions2) == 1, "dry run must not delete anything despite the matching policy"

    # A KEEP policy protects a version a DELETE policy would otherwise catch.
    st3 = ar.ArtifactRegistryStore()
    call(st3, "POST", B, {"repositoryId": "r1"}, {"format": "DOCKER"})
    protected = ar.ingest_image(st3, R, "app", "pinned")
    protected["createTime"] = "2000-01-01T00:00:00.000000Z"
    call(st3, "PATCH", B + "/r1", {"updateMask": "cleanupPolicies"},
         {"cleanupPolicies": {
             "del": {"action": "DELETE", "condition": {"olderThan": "86400s"}},
             "keep": {"action": "KEEP", "condition": {"tagState": "TAGGED"}}}})
    versions3 = call(st3, "GET", B + "/r1/packages/app/versions")[1]["versions"]
    assert len(versions3) == 1, "KEEP policy should have protected the tagged version"


def test_virtual_repository_aggregates_upstreams_read_only():
    st = ar.ArtifactRegistryStore()
    call(st, "POST", B, {"repositoryId": "std1"}, {"format": "DOCKER"})
    call(st, "POST", B, {"repositoryId": "std2"}, {"format": "DOCKER"})
    ar.ingest_image(st, "projects/p/locations/us-central1/repositories/std1", "shared", "v1")
    ar.ingest_image(st, "projects/p/locations/us-central1/repositories/std1", "only-in-std1", "v1")
    ar.ingest_image(st, "projects/p/locations/us-central1/repositories/std2", "shared", "v2")

    code, op = call(st, "POST", B, {"repositoryId": "virt1"}, {
        "format": "DOCKER", "mode": "VIRTUAL_REPOSITORY",
        "virtualRepositoryConfig": {"upstreamPolicies": [
            {"id": "a", "repository": "projects/p/locations/us-central1/repositories/std1", "priority": 10},
            {"id": "b", "repository": "projects/p/locations/us-central1/repositories/std2", "priority": 5}]}})
    assert code == 200, op

    names = {p["displayName"] for p in call(st, "GET", B + "/virt1/packages")[1]["packages"]}
    assert names == {"shared", "only-in-std1"}
    # std1 has higher priority: its version of the "shared" package wins the collision.
    assert len(call(st, "GET", B + "/virt1/packages/shared/versions")[1]["versions"]) == 1
    tags = {t["name"].rsplit("/", 1)[-1] for t in call(st, "GET", B + "/virt1/packages/shared/tags")[1]["tags"]}
    assert tags == {"v1"}, f"the higher-priority upstream (std1, tag v1) should win, got {tags}"

    # Virtual repositories are read-only: no direct pushes or deletes.
    assert call(st, "POST", B + "/virt1:pushSample", None, {"image": "x", "tag": "y"})[0] == 400
    assert call(st, "DELETE", B + "/virt1/packages/shared")[0] == 400

    # Validation: can't reference a non-existent or a virtual upstream, or cross locations.
    assert call(st, "POST", B, {"repositoryId": "virt2"}, {
        "format": "DOCKER", "mode": "VIRTUAL_REPOSITORY",
        "virtualRepositoryConfig": {"upstreamPolicies": [{"id": "a", "repository": "projects/p/locations/us-central1/repositories/bogus", "priority": 1}]}})[0] == 400
    assert call(st, "POST", B, {"repositoryId": "virt3"}, {
        "format": "DOCKER", "mode": "VIRTUAL_REPOSITORY",
        "virtualRepositoryConfig": {"upstreamPolicies": [{"id": "a", "repository": "projects/p/locations/us-central1/repositories/virt1", "priority": 1}]}})[0] == 400


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
