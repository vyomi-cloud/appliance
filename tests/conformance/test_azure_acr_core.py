"""Azure Container Registry — repository data-plane conformance.

Same test runs on host CPython and under Pyodide/WASM and must be green on both. It asserts the
native wire semantics real clients drive this core with: a `docker push`-shaped manifest PUT
(tag -> sha256 digest, Docker-Content-Digest header), `_catalog`/`tags/list` reads (the OCI
Distribution v2 half), and the ACR REST extension API (`/acr/v1/...`) the portal's Repositories
blade and `az acr repository` use for attributes/listing/delete.

Run on host:    python3 tests/conformance/test_azure_acr_core.py
Run in Pyodide: loaded by the wasm/ harness (same file).
"""
import json

try:
    from core.azure_acr_core import AcrRegistryStore, dispatch
except ImportError:  # pragma: no cover - Pyodide flat layout
    from azure_acr_core import AcrRegistryStore, dispatch  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _jbody(r):
    return json.loads(r.body.decode("utf-8"))


MANIFEST = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.docker.distribution.manifest.v2+json"}).encode()


def run() -> int:
    st = AcrRegistryStore()

    # 1. push a manifest by tag (the docker-push wire) -> 201 + Docker-Content-Digest
    push = dispatch(st, "PUT", "/v2/myapp/manifests/latest", {}, {"content-type": "application/vnd.docker.distribution.manifest.v2+json"}, MANIFEST)
    _check("push 201", push.status == 201)
    digest = push.headers["docker-content-digest"]
    _check("digest is sha256:...", digest.startswith("sha256:") and len(digest) == 71)

    # 2. OCI v2 reads: catalog, tags/list, pull by digest
    cat = dispatch(st, "GET", "/v2/_catalog")
    _check("v2 catalog lists repo", _jbody(cat)["repositories"] == ["myapp"])
    tags = dispatch(st, "GET", "/v2/myapp/tags/list")
    _check("v2 tags/list", _jbody(tags) == {"name": "myapp", "tags": ["latest"]})
    pulled = dispatch(st, "GET", f"/v2/myapp/manifests/{digest}")
    _check("v2 pull by digest returns exact body", pulled.status == 200 and pulled.body == MANIFEST)
    _check("v2 pull echoes Docker-Content-Digest", pulled.headers["docker-content-digest"] == digest)
    pulled_by_tag = dispatch(st, "GET", "/v2/myapp/manifests/latest")
    _check("v2 pull by tag resolves same digest", pulled_by_tag.headers["docker-content-digest"] == digest)

    # 3. ACR v1 extension API: repository attributes + tag attributes (what the portal shows)
    attrs = dispatch(st, "GET", "/acr/v1/myapp")
    a = _jbody(attrs)
    _check("acr/v1 repo attrs", attrs.status == 200 and a["imageName"] == "myapp" and a["tagCount"] == 1 and a["manifestCount"] == 1)
    tagattrs = dispatch(st, "GET", "/acr/v1/myapp/_tags")
    ta = _jbody(tagattrs)
    _check("acr/v1 tag list carries digest", ta["tags"][0]["name"] == "latest" and ta["tags"][0]["digest"] == digest)
    one_tag = dispatch(st, "GET", "/acr/v1/myapp/_tags/latest")
    _check("acr/v1 single tag", _jbody(one_tag)["tag"]["digest"] == digest)
    man = dispatch(st, "GET", "/acr/v1/myapp/_manifests")
    _check("acr/v1 manifest list", _jbody(man)["manifests"][0]["digest"] == digest)
    acr_cat = dispatch(st, "GET", "/acr/v1/_catalog")
    _check("acr/v1 catalog", _jbody(acr_cat)["repositories"] == ["myapp"])

    # 4. re-tagging: pushing a second tag to the SAME digest -> one manifest, two tags
    dispatch(st, "PUT", "/v2/myapp/manifests/v1", {}, {"content-type": "application/vnd.docker.distribution.manifest.v2+json"}, MANIFEST)
    attrs2 = _jbody(dispatch(st, "GET", "/acr/v1/myapp"))
    _check("second tag on same content shares one manifest", attrs2["manifestCount"] == 1 and attrs2["tagCount"] == 2)

    # 5. unknown repo / tag / manifest -> 404 with a Distribution-shaped error envelope
    nf = dispatch(st, "GET", "/acr/v1/nope")
    _check("unknown repo 404 NAME_UNKNOWN", nf.status == 404 and _jbody(nf)["errors"][0]["code"] == "NAME_UNKNOWN")
    nft = dispatch(st, "GET", "/acr/v1/myapp/_tags/nope")
    _check("unknown tag 404 TAG_UNKNOWN", nft.status == 404 and _jbody(nft)["errors"][0]["code"] == "TAG_UNKNOWN")

    # 6. delete one tag -> repo survives (other tag + manifest remain)
    dt = dispatch(st, "DELETE", "/acr/v1/myapp/_tags/v1")
    _check("delete tag 200", dt.status == 200)
    after_dt = _jbody(dispatch(st, "GET", "/acr/v1/myapp"))
    _check("deleting one tag keeps the other", after_dt["tagCount"] == 1 and after_dt["manifestCount"] == 1)

    # 7. delete the manifest by digest -> cascades to its remaining tag, repo disappears (empty)
    dm = dispatch(st, "DELETE", f"/v2/myapp/manifests/{digest}")
    _check("delete manifest 202", dm.status == 202)
    gone = dispatch(st, "GET", "/acr/v1/myapp")
    _check("empty repo is gone from the catalog", gone.status == 404)
    _check("gone from v2 catalog too", _jbody(dispatch(st, "GET", "/v2/_catalog"))["repositories"] == [])

    # 8. whole-repository delete
    dispatch(st, "PUT", "/v2/other/manifests/latest", {}, {"content-type": "application/vnd.docker.distribution.manifest.v2+json"}, MANIFEST)
    rd = dispatch(st, "DELETE", "/acr/v1/other")
    _check("delete repository 200", rd.status == 200)
    _check("repo gone after whole-repo delete", dispatch(st, "GET", "/acr/v1/other").status == 404)
    rd2 = dispatch(st, "DELETE", "/acr/v1/other")
    _check("deleting an already-gone repo 404", rd2.status == 404)

    # 9. blob-layer wire: a manifest referencing an un-uploaded layer is rejected ────────────
    cfg_bytes = b'{"architecture":"amd64"}'
    cfg_digest = "sha256:" + __import__("hashlib").sha256(cfg_bytes).hexdigest()
    layer_bytes = b"fake tar layer bytes"
    layer_digest = "sha256:" + __import__("hashlib").sha256(layer_bytes).hexdigest()
    real_manifest = json.dumps({
        "schemaVersion": 2, "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
        "config": {"mediaType": "application/vnd.docker.container.image.v1+json", "digest": cfg_digest, "size": len(cfg_bytes)},
        "layers": [{"mediaType": "application/vnd.docker.image.rootfs.diff.tar.gzip", "digest": layer_digest, "size": len(layer_bytes)}],
    }).encode()
    rejected = dispatch(st, "PUT", "/v2/withlayers/manifests/v1",
                         {}, {"content-type": "application/vnd.docker.distribution.manifest.v2+json"}, real_manifest)
    _check("manifest referencing an unknown blob is rejected", rejected.status == 404 and _jbody(rejected)["errors"][0]["code"] == "BLOB_UNKNOWN")

    # 10. chunked blob upload (POST init -> PATCH chunk -> PUT finalize with digest check) ───
    init = dispatch(st, "POST", "/v2/withlayers/blobs/uploads/")
    _check("blob upload init 202", init.status == 202)
    upload_url = init.headers["location"]
    _check("upload session uuid in Location", "/blobs/uploads/" in upload_url)
    uid = upload_url.rsplit("/", 1)[-1]
    patch = dispatch(st, "PATCH", f"/v2/withlayers/blobs/uploads/{uid}", {}, {}, layer_bytes)
    _check("blob upload chunk 202", patch.status == 202)
    bad_finish = dispatch(st, "PUT", f"/v2/withlayers/blobs/uploads/{uid}", {"digest": "sha256:" + "0" * 64}, {}, b"")
    _check("finalizing with a wrong digest is rejected", bad_finish.status == 400 and _jbody(bad_finish)["errors"][0]["code"] == "DIGEST_INVALID")
    finish = dispatch(st, "PUT", f"/v2/withlayers/blobs/uploads/{uid}", {"digest": layer_digest}, {}, b"")
    _check("blob upload finalize 201", finish.status == 201)
    _check("finalize echoes the real digest", finish.headers["docker-content-digest"] == layer_digest)

    # 11. monolithic upload (single POST with ?digest=... carrying the whole blob) ───────────
    mono = dispatch(st, "POST", "/v2/withlayers/blobs/uploads/", {"digest": cfg_digest}, {}, cfg_bytes)
    _check("monolithic blob upload 201", mono.status == 201)

    # 12. blob reads: HEAD/GET by digest now that both layer + config were uploaded ──────────
    head = dispatch(st, "HEAD", f"/v2/withlayers/blobs/{layer_digest}")
    _check("HEAD existing blob 200, no body", head.status == 200 and head.body == b"")
    got_blob = dispatch(st, "GET", f"/v2/withlayers/blobs/{layer_digest}")
    _check("GET existing blob returns exact bytes", got_blob.status == 200 and got_blob.body == layer_bytes)
    missing_blob = dispatch(st, "GET", "/v2/withlayers/blobs/sha256:" + "f" * 64)
    _check("GET unknown blob 404 BLOB_UNKNOWN", missing_blob.status == 404 and _jbody(missing_blob)["errors"][0]["code"] == "BLOB_UNKNOWN")

    # 13. now that both referenced blobs exist, the SAME manifest push succeeds ──────────────
    pushed_real = dispatch(st, "PUT", "/v2/withlayers/manifests/v1",
                            {}, {"content-type": "application/vnd.docker.distribution.manifest.v2+json"}, real_manifest)
    _check("manifest push succeeds once config+layers are uploaded blobs", pushed_real.status == 201)
    real_digest = pushed_real.headers["docker-content-digest"]
    pulled_real = dispatch(st, "GET", f"/v2/withlayers/manifests/{real_digest}")
    _check("pulled-back manifest round-trips the config+layers", _jbody(pulled_real)["config"]["digest"] == cfg_digest)

    # 14. deleting an uploaded blob then re-reading it 404s ─────────────────────────────────
    delb = dispatch(st, "DELETE", f"/v2/withlayers/blobs/{cfg_digest}")
    _check("delete blob 202", delb.status == 202)
    _check("deleted blob 404s on GET", dispatch(st, "GET", f"/v2/withlayers/blobs/{cfg_digest}").status == 404)

    # 15. a manifest LIST (multi-arch) has no config/layers of its own -> skips the blob dance ──
    list_manifest = json.dumps({"schemaVersion": 2, "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
                                 "manifests": [{"digest": real_digest, "platform": {"architecture": "amd64", "os": "linux"}}]}).encode()
    pushed_list = dispatch(st, "PUT", "/v2/withlayers/manifests/multiarch",
                            {}, {"content-type": "application/vnd.docker.distribution.manifest.list.v2+json"}, list_manifest)
    _check("manifest-list push skips blob-ref validation", pushed_list.status == 201)

    # 16. an upload session unknown to the registry 404s (not a silent no-op) ───────────────
    unknown_session = dispatch(st, "PATCH", "/v2/withlayers/blobs/uploads/does-not-exist", {}, {}, b"x")
    _check("unknown upload session 404", unknown_session.status == 404 and _jbody(unknown_session)["errors"][0]["code"] == "BLOB_UPLOAD_UNKNOWN")

    print("\nAzure Container Registry repository-core conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
