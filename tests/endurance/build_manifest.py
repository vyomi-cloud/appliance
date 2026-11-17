#!/usr/bin/env python3
"""vyomi-endurance Phase 0: build the ground-truth manifest.

Every capability id in core/capabilities/<cloud>/<service>.json is one row the Endurance estate must
exercise (or explicitly excuse). The manifest is GENERATED, never hand-edited, so a new capability
added to the registry shows up as an uncovered row and the coverage gate (coverage.py) fails.

    python3 tests/endurance/build_manifest.py            # write manifest.json
    python3 tests/endurance/build_manifest.py --check    # fail if manifest.json is stale
"""
import glob, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.json")
CLOUDS = ("aws", "gcp", "azure")


def build():
    rows = []
    for cloud in CLOUDS:
        for f in sorted(glob.glob(os.path.join(ROOT, "core/capabilities", cloud, "*.json"))):
            svc = os.path.basename(f)[:-5]
            for cid, v in json.load(open(f)).items():
                if cid.startswith("$") or not isinstance(v, dict) or "level" not in v:
                    continue
                rows.append({
                    "id": cid, "cloud": cloud, "service": svc, "title": v.get("title", ""),
                    "level": v["level"],  # per substrate: full | limited | config_only | not_simulated
                    "tier": v.get("tier", "free"), "mesh": bool(v.get("mesh")),
                    "limitations": len(v.get("limitations") or []),
                    "tests": v.get("tests") or [],
                    "has_api": bool(v.get("api")),
                })
    # An id defined in two files (e.g. a service file and panels.json) is ONE row: the service file wins,
    # and the clash is recorded so the registry owner can clean it up.
    by_id, dups = {}, {}
    for r in rows:
        old = by_id.get(r["id"])
        if old is None:
            by_id[r["id"]] = r
            continue
        # prefer the service file over panels.json
        keep, drop = (r, old) if old["service"] == "panels" else (old, r)
        by_id[r["id"]] = keep
        dups.setdefault(r["id"], []).append(drop["service"])
    rows = sorted(by_id.values(), key=lambda r: (r["cloud"], r["service"], r["id"]))
    return {"generated_from": "core/capabilities/*/*.json", "count": len(rows),
            "duplicate_ids_in_registry": dups, "rows": rows}


def main():
    m = build()
    text = json.dumps(m, indent=1, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        cur = open(OUT).read() if os.path.exists(OUT) else ""
        if cur != text:
            sys.exit("manifest.json is stale: run tests/endurance/build_manifest.py")
        print(f"manifest ok: {m['count']} capabilities")
        return
    open(OUT, "w").write(text)
    print(f"wrote {OUT}: {m['count']} capabilities")


if __name__ == "__main__":
    main()
