"""The portal's service count comes from wasm/service-inventory.json (rule 13), not from the v3 services/registry.json or a typed number."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import gen_services_json  # noqa: E402


def test_services_json_matches_inventory():
    inv = json.load(open(os.path.join(ROOT, "wasm", "service-inventory.json")))
    out = gen_services_json.build("0.0.0")
    assert out["total"] == inv["totals"]["services"] == len(out["services"])
    assert out["counts"] == inv["totals"]["by_cloud"]
    assert out["features"] == inv["totals"]["features"]


def test_services_json_is_what_the_portal_accepts():
    out = gen_services_json.build("0.0.0")        # service_catalog._valid(): int total > 0, dict counts, list services
    assert isinstance(out["total"], int) and out["total"] > 0 and isinstance(out["counts"], dict) and isinstance(out["services"], list)
    assert all({"cloud", "key", "name"} <= set(s) for s in out["services"])


def test_release_workflow_uses_the_inventory_not_the_legacy_registry():
    wf = open(os.path.join(ROOT, ".github", "workflows", "release.yml")).read()
    assert "gen_services_json.py" in wf and 'open("services/registry.json")' not in wf
