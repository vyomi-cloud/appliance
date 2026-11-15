#!/usr/bin/env python3
"""vyomi-endurance coverage reporter + gate.

Joins manifest.json (every capability) with estate/coverage-map.json (what the estate claims) and
reports, per cloud and service, which capabilities are covered, excused, or UNCOVERED.

coverage-map.json: {"<capability-id>": {"stage": "...", "tf": ["aws_sqs_queue.orders"],
    "verify": ["sdk","cli","ui"], "substrate": ["mesh","nano"]}  |  {"excuse": "reason"}}
An entry may only be an excuse when the reason is written down; stale ids (not in the manifest) fail.

    python3 tests/endurance/coverage.py                # report
    python3 tests/endurance/coverage.py --gate         # exit 1 if any capability is uncovered/stale
    python3 tests/endurance/coverage.py --gate --ratchet N   # allow at most N uncovered (CI ratchet)
"""
import collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERIFY = {"sdk", "cli", "ui"}


def main():
    manifest = json.load(open(os.path.join(HERE, "manifest.json")))
    mp = os.path.join(HERE, "estate", "coverage-map.json")
    cmap = json.load(open(mp)) if os.path.exists(mp) else {}
    ids = {r["id"] for r in manifest["rows"]}
    problems = [f"stale map entry (not in manifest): {k}" for k in cmap if k not in ids]
    stat = collections.defaultdict(lambda: collections.Counter())
    unc = []
    for r in manifest["rows"]:
        e = cmap.get(r["id"])
        key = (r["cloud"], r["service"])
        if not e:
            stat[key]["uncovered"] += 1; unc.append(r["id"]); continue
        if "excuse" in e:
            if not str(e["excuse"]).strip():
                problems.append(f"empty excuse: {r['id']}")
            stat[key]["excused"] += 1; continue
        miss = VERIFY - set(e.get("verify", []))
        if not e.get("stage") or not e.get("tf") and not e.get("verify"):
            problems.append(f"incomplete entry: {r['id']}")
        stat[key]["covered"] += 1
    tot = collections.Counter()
    for cloud in ("aws", "gcp", "azure"):
        c = collections.Counter()
        print(f"\n{cloud.upper()}")
        for (cl, svc), s in sorted(stat.items()):
            if cl != cloud: continue
            n = sum(s.values()); c.update(s)
            print(f"  {svc:22} {n:4}  covered {s['covered']:4}  excused {s['excused']:3}  uncovered {s['uncovered']:4}")
        print(f"  {'TOTAL':22} {sum(c.values()):4}  covered {c['covered']:4}  excused {c['excused']:3}  uncovered {c['uncovered']:4}")
        tot.update(c)
    n = sum(tot.values())
    pct = 100.0 * (tot["covered"] + tot["excused"]) / n if n else 0
    print(f"\nENDURANCE COVERAGE: {tot['covered']} covered + {tot['excused']} excused of {n} = {pct:.1f}%  (uncovered {tot['uncovered']})")
    for p in problems: print("PROBLEM:", p)
    if "--gate" in sys.argv:
        allow = int(sys.argv[sys.argv.index("--ratchet") + 1]) if "--ratchet" in sys.argv else 0
        if tot["uncovered"] > allow or problems:
            sys.exit(1)


if __name__ == "__main__":
    main()
