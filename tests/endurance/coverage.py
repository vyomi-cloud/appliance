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
    python3 tests/endurance/coverage.py --require-verified   # RELEASE gate: every non-excused row must be status=verified

Each entry has a `status`: "planned" (mapped to a stage + checks, not yet proven by a green run) or "verified" (a green
estate run proved it). A mapping is never proof; only the release gate (--require-verified) treats it as done.
"""
import collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERIFY = {"sdk", "cli", "ui"}


def token(cap_id):
    p = cap_id.split(".")
    return p[1] if p[0] in ("aws", "gcp", "azure") else p[0]


def main():
    manifest = json.load(open(os.path.join(HERE, "manifest.json")))
    mp = os.path.join(HERE, "estate", "coverage-map.json")
    cmap = json.load(open(mp)) if os.path.exists(mp) else {}
    ids = {r["id"] for r in manifest["rows"]}
    problems = [f"stale map entry (not in manifest): {k}" for k in cmap if k not in ids]
    stages = json.load(open(os.path.join(HERE, "estate", "stages.json")))["stages"]
    stage_of = {t: st for st, ts in stages.items() for t in ts}
    for r in manifest["rows"]:
        if token(r["id"]) not in stage_of:
            problems.append(f"no estate stage for service token '{token(r['id'])}' ({r['id']})")
    by_stage = collections.defaultdict(collections.Counter)
    stat = collections.defaultdict(lambda: collections.Counter())
    unc = []
    for r in manifest["rows"]:
        e = cmap.get(r["id"])
        key = (r["cloud"], r["service"])
        st = stage_of.get(token(r["id"]), "unstaged")
        by_stage[st][r["cloud"]] += 1
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
        if e.get("status") not in ("planned", "verified"):
            problems.append(f"entry needs status planned|verified: {r['id']}")
        elif e["status"] == "verified":
            stat[key]["verified"] += 1
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
    print(f"VERIFIED (green estate run): {tot['verified']} of {n}")
    print(f"\nENDURANCE COVERAGE: {tot['covered']} covered + {tot['excused']} excused of {n} = {pct:.1f}%  (uncovered {tot['uncovered']})")
    print("\nBY STAGE (capabilities to wrap: aws / gcp / azure)")
    for st in sorted(by_stage):
        b = by_stage[st]
        print(f"  {st:22} {b['aws']:4} / {b['gcp']:4} / {b['azure']:4}")
    for p in sorted(set(problems)): print("PROBLEM:", p)
    if "--require-verified" in sys.argv:
        if tot["verified"] + tot["excused"] < n or problems:
            print(f"RELEASE GATE FAILED: {n - tot['verified'] - tot['excused']} capabilities are not verified")
            sys.exit(1)
    if "--gate" in sys.argv:
        allow = int(sys.argv[sys.argv.index("--ratchet") + 1]) if "--ratchet" in sys.argv else 0
        if tot["uncovered"] > allow or problems:
            sys.exit(1)


if __name__ == "__main__":
    main()
