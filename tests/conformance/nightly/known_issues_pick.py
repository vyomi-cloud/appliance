#!/usr/bin/env python3
"""Pick the ONE open known-issue row a cloud's fixer should take this cycle (stdlib only, deterministic).

    known_issues_pick.py --cloud azure [--state attempts.json] [--now 2026-11-12T10:17:00Z] [--file KI.md]   -> prints the row id (or nothing)
    known_issues_pick.py --cloud azure --record AZ-4 --state attempts.json                                     -> remember the attempt

Rules: only rows `known_issues.list_open(cloud)` returns; rows that clearly need the owner, a real backend, an environment we do not
have, the portal or another cloud are NOT fixable in code and are skipped; highest impact first (S1 > S2 > S3), then id order;
a row attempted in the last 24 h is skipped (so a row the agent cannot fix does not block the rest). Prints nothing when there
is no fixable row: the workflow then ends as a no-op.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import known_issues as ki  # noqa: E402

COOLDOWN = timedelta(hours=24)
# text that marks a row as not fixable by an agent in code
SKIP = re.compile(
    r"by design|owner decision|owner'?s call|needs (you|the owner)|your call|you or the portal|portal session|vendor_to_portal"
    r"|needs (docker|azurite|postgres|a real|the docker)|no `?azure`? python module|scheduled for 4\.0\.1|real backend"
    r"|not a bug|not an issue|accepted by owner|hosted relay|wrangler|private network access|needs a backend the codespace can reach"
    r"|tested only against a fake|sandbox pr|publish the image|rebuild the image",
    re.I)
RANK = {"S1": 0, "S2": 1, "S3": 2}


def fixable(row: dict) -> bool:
    return not SKIP.search(" ".join((row.get("what", ""), row.get("workaround", ""))))


def _load(state: str | None) -> dict:
    if state and Path(state).exists():
        try:
            return json.loads(Path(state).read_text())
        except ValueError:
            return {}
    return {}


def pick(cloud: str, state: str | None = None, now: datetime | None = None, path: Path = ki.DEFAULT) -> str:
    now = now or datetime.now(timezone.utc)
    seen = _load(state)
    cands = []
    for r in ki.list_open(cloud, path):
        if not fixable(r):
            continue
        t = seen.get(r["id"])
        if t and now - datetime.fromisoformat(t.replace("Z", "+00:00")) < COOLDOWN:
            continue
        cands.append(r)
    cands.sort(key=lambda r: (RANK.get(r["impact"], 9), r["id"]))
    return cands[0]["id"] if cands else ""


def record(rid: str, state: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    seen = _load(state)
    seen[rid] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    Path(state).write_text(json.dumps(seen, indent=1, sort_keys=True) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud", required=True, choices=list(ki.PREFIX))
    ap.add_argument("--state"); ap.add_argument("--file", default=str(ki.DEFAULT))
    ap.add_argument("--now"); ap.add_argument("--record")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else None
    if a.record:
        if not a.state:
            ap.error("--record needs --state")
        record(a.record, a.state, now); return 0
    out = pick(a.cloud, a.state, now, Path(a.file))
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
