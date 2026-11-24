"""IAM onboarding gate (rule 14, docs/architecture/v4.0/V4-BRANCH-ARCHITECTURE.md): a service is not done until it is IAM-onboarded.

Fails with the exact command / edit that fixes it."""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

MAP = os.path.join(ROOT, "core", "iam_catalog", "service_map.json")
HOWTO = ("IAM onboarding: add the service to core/iam_catalog/service_map.json (services.<cloud>.<id> = {\"catalog\": [slice, ...], \"floor\": 0} "
         "or {\"catalog\": \"none\", \"reason\": \"...\", \"floor\": 0}); add any new slice to scripts/gen_iam_catalog.py and run "
         "`python3 scripts/gen_iam_catalog.py <cloud>`; then `python3 scripts/gen_iam_coverage.py --bump-floors` and commit "
         "wasm/iam-coverage.json + docs/architecture/v4.0/IAM-COVERAGE.md.")


def _j(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return json.load(f)


def test_every_inventory_service_is_in_the_service_map():
    smap = _j("core", "iam_catalog", "service_map.json")["services"]
    missing = ["%s/%s" % (s["cloud"], s["id"]) for s in _j("wasm", "service-inventory.json")["services"] if s["id"] not in smap.get(s["cloud"], {})]
    assert not missing, "services in wasm/service-inventory.json with no IAM onboarding: %s. %s" % (missing, HOWTO)
    inv = {(s["cloud"], s["id"]) for s in _j("wasm", "service-inventory.json")["services"]}
    stale = ["%s/%s" % (c, i) for c, d in smap.items() for i in d if (c, i) not in inv]
    assert not stale, "service_map.json lists services that are not in the inventory (remove them): %s" % stale
    for c, d in smap.items():
        for i, e in d.items():
            if e["catalog"] == "none":
                assert e.get("reason"), "%s/%s: catalog 'none' needs a reason in service_map.json" % (c, i)


def test_coverage_file_is_fresh():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "gen_iam_coverage.py"), "--check"], cwd=ROOT, capture_output=True, text=True,
                       env=dict(os.environ, PYTHONPATH=ROOT + os.pathsep + os.path.join(ROOT, "core")))
    assert r.returncode == 0, (r.stdout + r.stderr).strip()


def test_coverage_never_drops_below_the_recorded_floor():
    cov = _j("wasm", "iam-coverage.json")
    smap = _j("core", "iam_catalog", "service_map.json")["services"]
    low = []
    for r in cov["services"]:
        assert r["floor"] == smap[r["cloud"]][r["id"]].get("floor", 0)
        if r["mapped_pct"] is not None and r["mapped_pct"] < r["floor"]:
            low.append("%s/%s %.1f%% < floor %d%%" % (r["cloud"], r["id"], r["mapped_pct"], r["floor"]))
    assert not low, ("request-map coverage regressed: %s. Fix the map (core/iam_engine/map_<cloud>.py) so these requests map again; "
                     "never lower a floor. When coverage improved, raise floors with `python3 scripts/gen_iam_coverage.py --bump-floors`." % low)


def test_every_catalog_slice_in_the_generator_has_a_committed_file():
    import gen_iam_catalog as g
    want = {"aws": g.AWS_PREFIXES, "gcp": g.GCP_SLUGS, "azure": g.az_providers()}
    missing = []
    for c, names in want.items():
        for n in names:
            if not os.path.exists(os.path.join(ROOT, "core", "iam_catalog", c, n + ".json")):
                missing.append("%s/%s" % (c, n))
    # Azure providers the reference has no page for are reported by the generator ("not in the Azure permissions reference"); only flag
    # slices that are neither committed nor recorded as known-absent.
    absent = set(_j("core", "iam_catalog", "service_map.json").get("known_absent_slices", []))
    missing = [m for m in missing if m not in absent]
    assert not missing, "catalog slices listed in scripts/gen_iam_catalog.py without a committed file: %s. Run `python3 scripts/gen_iam_catalog.py <aws|gcp|azure>` and commit core/iam_catalog/." % missing


def test_mapped_slices_exist_and_are_in_the_generator():
    import gen_iam_catalog as g
    smap = _j("core", "iam_catalog", "service_map.json")["services"]
    gen = {"aws": set(g.AWS_PREFIXES), "gcp": set(g.GCP_SLUGS), "azure": set(g.az_providers())}
    bad = []
    for c, d in smap.items():
        for i, e in d.items():
            for sl in ([] if e["catalog"] == "none" else e["catalog"]):
                if sl not in gen[c]:
                    bad.append("%s/%s -> %s not in scripts/gen_iam_catalog.py" % (c, i, sl))
                elif not os.path.exists(os.path.join(ROOT, "core", "iam_catalog", c, sl + ".json")):
                    bad.append("%s/%s -> core/iam_catalog/%s/%s.json missing" % (c, i, c, sl))
    assert not bad, "%s. %s" % (bad, HOWTO)
