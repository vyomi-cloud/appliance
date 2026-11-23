"""IAM catalog (docs/architecture/v4.0/IAM-FAITHFUL-DESIGN.md): committed slices are well-formed, IDs verbatim, every in-scope prefix present."""
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def test_aws_catalog_wellformed():
    import gen_iam_catalog as g
    d = os.path.join(ROOT, "core", "iam_catalog", "aws")
    have = {f[:-5] for f in os.listdir(d) if f.endswith(".json")}
    assert set(g.AWS_PREFIXES) <= have, set(g.AWS_PREFIXES) - have
    for pre in g.AWS_PREFIXES:
        j = json.load(open(os.path.join(d, pre + ".json")))
        assert j["cloud"] == "aws" and j["service"] == pre and j["actions"]
        for name, a in j["actions"].items():
            assert re.fullmatch(r"[A-Za-z0-9*]+", name), (pre, name)          # verbatim vendor IDs, no prefix added/renamed
            assert a["l"] in ("read", "list", "write", "permissions", "tagging")
        for op, acts in j["operations"].items():
            assert acts and all(isinstance(x, str) for x in acts), (pre, op)


def test_s3_known_permissions_verbatim():
    j = json.load(open(os.path.join(ROOT, "core", "iam_catalog", "aws", "s3.json")))
    assert "GetObject" in j["actions"] and j["actions"]["PutBucketPolicy"]["l"] == "permissions"
    assert "GetObject" in j["operations"]


def test_azure_and_gcp_catalogs_verbatim():
    az = json.load(open(os.path.join(ROOT, "core", "iam_catalog", "azure", "Microsoft.Storage.json")))
    assert "Microsoft.Storage/storageAccounts/read" in az["actions"]
    assert any(k.startswith("Microsoft.Storage/storageAccounts/blobServices/containers/blobs/") for k in az["dataActions"])
    gc = json.load(open(os.path.join(ROOT, "core", "iam_catalog", "gcp", "storage.json")))
    assert "storage.objects.get" in gc["permissions"] and "roles/storage.objectViewer" in gc["roles"]
    assert "storage.objects.get" in gc["roles"]["roles/storage.objectViewer"]["permissions"]
    for cloud in ("azure", "gcp"):
        d = os.path.join(ROOT, "core", "iam_catalog", cloud)
        assert os.listdir(d)
