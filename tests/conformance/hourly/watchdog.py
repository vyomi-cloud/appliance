#!/usr/bin/env python3
"""Start the next conformance cycle when it's due; raise the alarm when cycles stall.

A cycle (conformance-hourly.yml: prepare → detect shards → collect → fix → publish)
takes as long as it needs. The next one starts COOLDOWN minutes after the last one
finished, never while one is queued or running. Run by conformance-watchdog.yml
every 15 minutes and right after each cycle hands over.

Stall alarm: an issue titled "Conformance cycle stalled" is opened (or commented on)
when a cycle has been running longer than STALL minutes, or the last two cycles
ended cancelled or failed; it is closed when a cycle succeeds.

    GH_TOKEN=… REPO=owner/name python3 tests/conformance/hourly/watchdog.py
Env: COOLDOWN_MIN (60), STALL_MIN (240), GRACE_MIN (5: a handover that waited the
cooldown still starts even though the cycle finished a minute after it asked),
DRY_RUN=1 (decide and print, change nothing).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

WORKFLOW = "conformance-hourly.yml"
ISSUE_TITLE = "Conformance cycle stalled"
ACTIVE = {"queued", "in_progress", "pending", "waiting", "requested"}
BAD = {"cancelled", "failure", "timed_out", "startup_failure"}


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def decide(runs: list[dict], now: datetime, cooldown: int, stall: int, grace: int = 5) -> dict:
    """runs: newest first, as `gh run list --json status,conclusion,createdAt,startedAt,updatedAt,databaseId`."""
    active = [r for r in runs if r.get("status") in ACTIVE]
    done = sorted((r for r in runs if r.get("status") == "completed"), key=lambda r: r["updatedAt"], reverse=True)
    out = {"start": False, "stall": None, "healthy": bool(done) and done[0].get("conclusion") == "success",
           "reason": ""}
    if len(done) >= 2 and all(r.get("conclusion") in BAD for r in done[:2]):
        out["stall"] = (f"the last two cycles ended {done[0]['conclusion']} (run {done[0]['databaseId']}) "
                        f"and {done[1]['conclusion']} (run {done[1]['databaseId']})")
    if active:
        running = [r for r in active if r.get("status") == "in_progress"]
        for r in running:
            mins = (now - _ts(r.get("startedAt") or r["createdAt"])).total_seconds() / 60
            if mins > stall:
                out["stall"] = f"cycle {r['databaseId']} has been running for {int(mins)} min (limit {stall})"
        out["reason"] = f"a cycle is {'running' if running else 'queued'} (run {active[0]['databaseId']})"
        return out
    if not done:
        out.update(start=True, reason="no previous cycle")
        return out
    idle = (now - _ts(done[0]["updatedAt"])).total_seconds() / 60
    if idle >= cooldown - grace:
        out.update(start=True, reason=f"last cycle finished {int(idle)} min ago (cooldown {cooldown})")
    else:
        out["reason"] = f"cooling down: last cycle finished {int(idle)} min ago, next in {int(cooldown - idle)} min"
    return out


def gh(*args: str, check: bool = True) -> str:
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"gh {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout


def main() -> int:
    repo = os.environ["REPO"]
    dry = os.environ.get("DRY_RUN") == "1"
    cooldown = int(os.environ.get("COOLDOWN_MIN") or 60)
    stall = int(os.environ.get("STALL_MIN") or 240)
    grace = int(os.environ.get("GRACE_MIN") or 5)
    runs = json.loads(gh("run", "list", "-R", repo, "--workflow", WORKFLOW, "-L", "20", "--json",
                         "databaseId,status,conclusion,createdAt,startedAt,updatedAt") or "[]")
    d = decide(runs, datetime.now(timezone.utc), cooldown, stall, grace)
    print(json.dumps(d))

    issue = gh("issue", "list", "-R", repo, "--state", "open", "--search", f'"{ISSUE_TITLE}" in:title',
               "--json", "number,title", "-q", f'[.[] | select(.title == "{ISSUE_TITLE}")][0].number // empty',
               check=False).strip()
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/workflows/{WORKFLOW}"
    if d["stall"] and not dry:
        body = f"Conformance cycle stalled: {d['stall']}.\n\nRuns: {run_url}"
        if issue:
            # One comment per distinct stall, not one every 15-minute tick.
            seen = gh("issue", "view", issue, "-R", repo, "--json", "body,comments",
                      "-q", "[.body] + [.comments[].body] | join(\"\\n\")", check=False)
            if d["stall"] not in seen:
                gh("issue", "comment", issue, "-R", repo, "--body", body)
        else:
            gh("issue", "create", "-R", repo, "--title", ISSUE_TITLE, "--body", body)
    elif d["healthy"] and issue and not dry:
        gh("issue", "close", issue, "-R", repo, "--comment", "A conformance cycle succeeded; closing.")

    if d["start"] and not dry:
        before = {r["databaseId"] for r in runs}
        gh("workflow", "run", WORKFLOW, "-R", repo, "--ref", "main")
        print(f"Started the next cycle: {d['reason']}.")
        # Hold the tick's concurrency lock until GitHub lists the new run, so the
        # next tick sees it as active and can't start a second cycle.
        for _ in range(12):
            time.sleep(5)
            now_ids = {r["databaseId"] for r in json.loads(gh("run", "list", "-R", repo, "--workflow", WORKFLOW,
                                                               "-L", "5", "--json", "databaseId") or "[]")}
            if now_ids - before:
                break
    else:
        print(f"{'DRY RUN, would ' + ('start' if d['start'] else 'wait') if dry else 'Not starting'}: {d['reason']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
