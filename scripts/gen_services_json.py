#!/usr/bin/env python3
"""Build the released-service registry the portal reads (services.json) from the ONE catalogue, wasm/service-inventory.json (rule 13).

    python3 scripts/gen_services_json.py <version> [out.json]     # release.yml attaches the result to the GitHub Release

The portal's service_catalog.py renders total / per-cloud counts / the service list from this file, so every "N services" on the site follows the
v4 consoles with no hand-typed number. services/registry.json (the v3 expansion registry) is no longer the source of the count."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOUDS = ("aws", "gcp", "azure")


def build(version, inventory=None):
    inv = inventory or json.load(open(os.path.join(ROOT, "wasm", "service-inventory.json")))
    live = [s for s in inv["services"] if s.get("v4")]
    counts = {c: sum(1 for s in live if s["cloud"] == c) for c in CLOUDS}
    return {"version": version, "total": sum(counts.values()), "counts": counts, "features": sum(s.get("features") or 0 for s in live),
            "services": [{"cloud": s["cloud"], "key": s["id"], "name": s["title"], "upstream": s.get("category", ""), "released_in": version} for s in live]}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: gen_services_json.py <version> [out.json]")
    out = build(sys.argv[1])
    path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "dist", "services.json")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    json.dump(out, open(path, "w"), indent=1)
    print("services.json: %d services %s" % (out["total"], out["counts"]))
