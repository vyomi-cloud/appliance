"""The service inventory the portal reads must match the console registries (rule 13). Fails when a service is added/removed
without re-running scripts/gen_service_inventory.py, and when a registry entry would be invisible to the portal."""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_inventory_is_current():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "gen_service_inventory.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr or r.stdout


def test_inventory_shape():
    inv = json.load(open(os.path.join(ROOT, "wasm", "service-inventory.json")))
    t = inv["totals"]
    assert t["services"] == sum(t["by_cloud"].values()) > 0
    ids = [(s["cloud"], s["id"]) for s in inv["services"]]
    assert len(ids) == len(set(ids)), "duplicate service id in a registry"
    assert all(s["title"] and s["category"] for s in inv["services"]), "registry entry without title/category"
