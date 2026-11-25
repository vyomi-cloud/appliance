"""GCP IAM catalog completeness (branch v4/iam-catalog-complete): every page of Google's predefined-roles reference is a shard, each
permission carries Google's published custom-roles support level as `stage`, roles carry descriptions, `_index.json` lists the shards.
Offline: reads only the committed catalog."""
import glob, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = os.path.join(ROOT, "core", "iam_catalog", "gcp")
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def _shards():
    return {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(os.path.join(D, "[a-z]*.json"))}


def test_counts_and_shape():
    sh = _shards()
    perms, roles = {}, {}
    for j in sh.values():
        for p, v in j["permissions"].items():
            assert set(v) <= {"stage"}, (p, v)
            if v: assert v["stage"] in ("SUPPORTED", "TESTING", "NOT_SUPPORTED"), (p, v)
            perms[p] = perms.get(p) or v.get("stage")
        roles.update(j["roles"])
    assert len(sh) >= 359 and len(perms) >= 14400, (len(sh), len(perms))      # real GCP: ~14.5k permissions (was 8082)
    assert len(roles) >= 1800                                                  # was 477
    assert sum(1 for r in roles.values() if r["desc"]) >= 0.99 * len(roles)    # was 124/477
    stages = {s for s in perms.values() if s}
    assert stages == {"SUPPORTED", "TESTING", "NOT_SUPPORTED"}
    assert sum(1 for s in perms.values() if s == "TESTING") > 300


def test_known_stage_and_description():
    sh = _shards()
    assert sh["storage"]["permissions"]["storage.objects.get"]["stage"] == "SUPPORTED"
    assert sh["storage"]["roles"]["roles/storage.admin"]["desc"].startswith("Grants full control of objects and buckets")
    assert sh["accessapproval"]["roles"]["roles/accessapproval.admin"]["desc"] == "Admin role for Access Approval"


def test_index_matches_shards_and_floor_services_present():
    import gen_iam_catalog as g
    idx = json.load(open(os.path.join(D, "_index.json")))
    sh = _shards()
    assert set(idx["services"]) == set(sh) and idx["stages"] == list(g.GCP_STAGES)
    for s, n in idx["services"].items():
        assert n == {"permissions": len(sh[s]["permissions"]), "roles": len(sh[s]["roles"])}, s
    assert set(g.GCP_SLUGS) <= set(sh)


def test_shard_sizes_sane():
    for f in glob.glob(os.path.join(D, "[a-z]*.json")):
        assert os.path.getsize(f) < 2_000_000, f


def test_aws_reference_has_no_descriptions():
    """Documented skip: the AWS Service Reference JSON has no per-action description field (descriptions only exist in the HTML Service
    Authorization Reference, AWS-copyrighted docs). If AWS adds one to the JSON, this fails and the skip should be revisited."""
    assert os.path.exists(os.path.join(ROOT, "core", "iam_catalog", "aws", "sqs.json"))
    j = json.load(open(os.path.join(ROOT, "core", "iam_catalog", "aws", "sqs.json")))
    assert all(set(a) <= {"l", "r", "k", "d"} for a in j["actions"].values())
