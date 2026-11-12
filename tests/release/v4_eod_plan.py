#!/usr/bin/env python3
"""Decision logic of the end-of-day v4 release (pure, stdlib, tested). The workflow feeds it facts; it returns what to do.

    python3 tests/release/v4_eod_plan.py plan --version-file VERSION --last-tag v4.0.0 --commits-since 7 \
        --existing-tags v4.0.0 --cloud-status azure=ok --cloud-status aws=red:suite X failed --md <known-issues.md> \
        [--busy "v4-known-issues-hourly"] [--paused] [--auto-release] [--dry-run] [--out plan.json]
    python3 tests/release/v4_eod_plan.py delta --old <md> --new <md>        # known-issues rows added / resolved (for the release notes)

decision: skip (nothing to do / paused / busy / v4 not cut yet) | blocked (a cloud is red, S1 open, tag clash)
        | dry-run (would release) | release (V4_AUTO_RELEASE on and not a dry run)
Exit code is 0 for every decision: a blocked day is a normal outcome, not a workflow failure.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("known_issues", ROOT / "tests/conformance/nightly/lib/known_issues.py")
ki = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ki)
CLOUDS = ("azure", "aws", "gcp")


def next_patch(version: str) -> str | None:
    m = re.fullmatch(r"\s*(\d+)\.(\d+)\.(\d+)\s*", version or "")
    return f"{m.group(1)}.{m.group(2)}.{int(m.group(3)) + 1}" if m else None


def decide(version, commits_since, existing_tags, cloud_status, md, busy=(), paused=False, auto_release=False, dry_run=False):
    reasons, clouds = [], {}
    out = {"decision": "skip", "reasons": reasons, "version": (version or "").strip(), "next_version": None, "clouds": clouds}
    if paused:
        reasons.append("V4_RELEASE_PAUSE is set"); return out
    v = (version or "").strip()
    if not v.startswith("4."):
        reasons.append(f"VERSION is {v or 'empty'}: v4.0.0 has not been cut yet (the owner cuts it; EOD releases are patches after it)"); return out
    if busy:
        reasons.append("workflow(s) still running: " + ", ".join(busy)); return out
    if commits_since <= 0:
        reasons.append("no commit on v4-on-main since the last tag"); return out
    nxt = next_patch(v)
    out["next_version"] = nxt
    blocked = False
    for c in CLOUDS:
        st = cloud_status.get(c, "missing")
        s1 = [r["id"] for r in ki.list_open(c, md) if r["impact"].strip().upper().startswith("S1")]
        clouds[c] = {"status": st, "open_s1": s1}
        if st != "ok":
            blocked = True; reasons.append(f"{c}: {st}")
        if s1:
            blocked = True; reasons.append(f"{c}: open S1 row(s) {', '.join(s1)}")
    if nxt is None or f"v{nxt}" in set(existing_tags):
        blocked = True; reasons.append(f"tag v{nxt} already exists or VERSION is unreadable")
    if blocked:
        out["decision"] = "blocked"; return out
    if dry_run or not auto_release:
        out["decision"] = "dry-run"
        reasons.append("dry run" if dry_run else "V4_AUTO_RELEASE is not 'true'")
        return out
    out["decision"] = "release"; reasons.append("all clouds green, no open S1, auto-release armed")
    return out


def delta(old: str, new: str):
    ids = lambda t: {r["id"] for r in _rows(t)}
    a, b = ids(old), ids(new)
    return {"added": sorted(b - a), "resolved": sorted(a - b)}


def _rows(text):
    for _, rid, cells in ki._rows(text):
        yield {"id": rid}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--version-file", required=True); p.add_argument("--last-tag", default="")
    p.add_argument("--commits-since", type=int, default=0); p.add_argument("--existing-tags", default="")
    p.add_argument("--cloud-status", action="append", default=[]); p.add_argument("--md", default=str(ki.DEFAULT))
    p.add_argument("--busy", default=""); p.add_argument("--paused", action="store_true")
    p.add_argument("--auto-release", action="store_true"); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--out")
    d = sub.add_parser("delta"); d.add_argument("--old", required=True); d.add_argument("--new", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "delta":
        r = delta(Path(a.old).read_text(), Path(a.new).read_text())
        print(json.dumps(r)); return 0
    cs = {}
    for x in a.cloud_status:
        k, _, v = x.partition("="); cs[k] = v or "missing"
    r = decide(Path(a.version_file).read_text(), a.commits_since, [t for t in a.existing_tags.replace(",", " ").split() if t], cs,
               a.md, [b for b in a.busy.split(",") if b.strip()], a.paused, a.auto_release, a.dry_run)
    s = json.dumps(r, indent=1)
    if a.out:
        Path(a.out).write_text(s + "\n")
    print(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
