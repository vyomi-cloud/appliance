"""GCS bucket-configuration conformance — the parts of the GCS JSON API the v4 GCP
console's Cloud Storage pages drive (and google-cloud-storage exposes as
Bucket.labels / iam_configuration / lifecycle_rules / retention_period / patch()):

  - insert keeps labels, location (upper-cased) + derived locationType,
    iamConfiguration (uniform bucket-level access, public access prevention),
    lifecycle rule definitions and the retention policy
  - buckets.patch merges labels (null deletes a key), clears with null, bumps
    metageneration; buckets.update (PUT) replaces
  - a retention policy is ENFORCED: delete/overwrite of a younger object -> 403
    retentionPolicyNotMet
  - settings Vyomi does not model (versioning, soft delete, autoclass) are not echoed
  - bucket IAM policy get (default legacy bindings) / set round-trip
  - objects.list with delimiter -> `prefixes` (folders), placeholder object listed
    under its own prefix

Run on host:    PYTHONPATH=. python3 tests/conformance/test_gcs_bucket_config_core.py
"""
import json

try:
    from core.object_store import InMemoryObjectStore
    from core import gcp_storage_core as gcs
except ImportError:  # pragma: no cover - Pyodide flat layout
    from object_store import InMemoryObjectStore  # type: ignore
    import gcp_storage_core as gcs  # type: ignore


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  ok  {name}")


def _j(r):
    return json.loads(r.body.decode("utf-8")) if r.body else {}


def _call(st, m, p, q=None, body=None, ct="application/json"):
    raw = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else b"")
    return gcs.dispatch(st, m, p, q or {}, {"content-type": ct}, raw)


def run() -> int:
    st = InMemoryObjectStore()

    # 1. insert with console settings
    r = _call(st, "POST", "/storage/v1/b", {"project": "vyomi-project"}, {
        "name": "cfg", "location": "us-central1", "storageClass": "NEARLINE",
        "labels": {"env": "dev", "team": "core"},
        "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True}, "publicAccessPrevention": "enforced"},
        "versioning": {"enabled": True}, "softDeletePolicy": {"retentionDurationSeconds": "604800"},
        "lifecycle": {"rule": [{"action": {"type": "Delete"}, "condition": {"age": 30}}]},
    })
    b = _j(r)
    _check("insert 200", r.status == 200)
    _check("location upper-cased", b["location"] == "US-CENTRAL1")
    _check("locationType region", b["locationType"] == "region")
    _check("storageClass kept", b["storageClass"] == "NEARLINE")
    _check("labels kept", b.get("labels") == {"env": "dev", "team": "core"})
    _check("uniform access kept", b["iamConfiguration"]["uniformBucketLevelAccess"]["enabled"] is True)
    _check("public access prevention kept", b["iamConfiguration"]["publicAccessPrevention"] == "enforced")
    _check("lifecycle rule kept", b["lifecycle"]["rule"][0]["condition"]["age"] == 30)
    _check("unmodelled versioning not echoed", "versioning" not in b)
    _check("unmodelled softDeletePolicy not echoed", "softDeletePolicy" not in b)

    mr = _j(_call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "multi"}))
    _check("default location US multi-region", mr["location"] == "US" and mr["locationType"] == "multi-region")
    _check("default PAP inherited, UBLA off", mr["iamConfiguration"]["publicAccessPrevention"] == "inherited"
           and mr["iamConfiguration"]["uniformBucketLevelAccess"]["enabled"] is False)
    dr = _j(_call(st, "POST", "/storage/v1/b", {"project": "p"}, {"name": "dual", "location": "nam4"}))
    _check("dual-region locationType + rpo", dr["locationType"] == "dual-region" and dr["rpo"] == "DEFAULT")

    # 2. get round-trips
    g = _j(_call(st, "GET", "/storage/v1/b/cfg"))
    _check("get returns labels", g.get("labels", {}).get("env") == "dev")

    # 3. patch: merge labels, delete one key, metageneration bumps
    p = _call(st, "PATCH", "/storage/v1/b/cfg", body={"labels": {"env": "prod", "team": None, "new": "x"}})
    pb = _j(p)
    _check("patch 200", p.status == 200)
    _check("patch merged labels", pb["labels"] == {"env": "prod", "new": "x"})
    _check("patch bumps metageneration", int(pb["metageneration"]) == int(b["metageneration"]) + 1)
    _check("patch storageClass", _j(_call(st, "PATCH", "/storage/v1/b/cfg", body={"storageClass": "COLDLINE"}))["storageClass"] == "COLDLINE")
    cl = _j(_call(st, "PATCH", "/storage/v1/b/cfg", body={"lifecycle": None}))
    _check("patch null clears lifecycle", "lifecycle" not in cl)
    up = _j(_call(st, "PUT", "/storage/v1/b/cfg", body={"labels": {"only": "this"}}))
    _check("update (PUT) replaces labels", up["labels"] == {"only": "this"})
    _check("patch missing bucket 404", _call(st, "PATCH", "/storage/v1/b/nope", body={}).status == 404)

    # 4. retention policy is enforced
    rp = _j(_call(st, "PATCH", "/storage/v1/b/cfg", body={"retentionPolicy": {"retentionPeriod": "3600"}}))
    _check("retention policy set", rp["retentionPolicy"]["retentionPeriod"] == "3600" and "effectiveTime" in rp["retentionPolicy"])
    _call(st, "POST", "/upload/storage/v1/b/cfg/o", {"uploadType": "media", "name": "keep.txt"}, b"keep", "text/plain")
    d = _call(st, "DELETE", "/storage/v1/b/cfg/o/keep.txt")
    _check("delete under retention -> 403 retentionPolicyNotMet",
           d.status == 403 and _j(d)["error"]["errors"][0]["reason"] == "retentionPolicyNotMet")
    ow = _call(st, "POST", "/upload/storage/v1/b/cfg/o", {"uploadType": "media", "name": "keep.txt"}, b"new", "text/plain")
    _check("overwrite under retention -> 403", ow.status == 403)
    _call(st, "PATCH", "/storage/v1/b/cfg", body={"retentionPolicy": None})
    _check("retention removed -> delete 204", _call(st, "DELETE", "/storage/v1/b/cfg/o/keep.txt").status == 204)

    # 5. IAM policy
    pol = _j(_call(st, "GET", "/storage/v1/b/cfg/iam"))
    _check("default policy kind", pol["kind"] == "storage#policy")
    _check("default legacy owner binding uses project",
           any(x["role"] == "roles/storage.legacyBucketOwner" and "projectOwner:vyomi-project" in x["members"] for x in pol["bindings"]))
    pol["bindings"].append({"role": "roles/storage.objectViewer", "members": ["user:dev@example.com"]})
    sp = _call(st, "PUT", "/storage/v1/b/cfg/iam", body=pol)
    _check("set policy 200", sp.status == 200)
    again = _j(_call(st, "GET", "/storage/v1/b/cfg/iam"))
    _check("policy round-trips",
           any(x["role"] == "roles/storage.objectViewer" and x["members"] == ["user:dev@example.com"] for x in again["bindings"]))
    _check("iam on missing bucket 404", _call(st, "GET", "/storage/v1/b/nope/iam").status == 404)

    # 6. delimiter listing -> prefixes
    for n in ("top.txt", "photos/", "photos/a.png", "photos/2024/b.png", "docs/readme.md"):
        _call(st, "POST", "/upload/storage/v1/b/multi/o", {"uploadType": "media", "name": n}, b"x", "text/plain")
    root = _j(_call(st, "GET", "/storage/v1/b/multi/o", {"delimiter": "/"}))
    _check("root prefixes", root.get("prefixes") == ["docs/", "photos/"])
    _check("root items only top-level", [i["name"] for i in root.get("items", [])] == ["top.txt"])
    sub = _j(_call(st, "GET", "/storage/v1/b/multi/o", {"delimiter": "/", "prefix": "photos/"}))
    _check("sub prefixes", sub.get("prefixes") == ["photos/2024/"])
    _check("sub items incl. placeholder", [i["name"] for i in sub.get("items", [])] == ["photos/", "photos/a.png"])
    flat = _j(_call(st, "GET", "/storage/v1/b/multi/o"))
    _check("no delimiter -> flat, no prefixes", "prefixes" not in flat and len(flat["items"]) == 5)

    print("\nGCS bucket-config conformance: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
