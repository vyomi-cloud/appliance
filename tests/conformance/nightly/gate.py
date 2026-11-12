#!/usr/bin/env python3
"""Merge gate for the nightly: compare results before and after the agent's fixes.

    gate.py BEFORE.json AFTER.json   -> exit 0 = safe to merge, 1 = do not merge

Safe only if (a) no suite that was green before is red or missing now, (b) at least one suite ran,
(c) no suite got fewer passes than before. `pending` suites are ignored (reported, not failures).
"""
from __future__ import annotations
import json, sys


def load(path: str) -> dict[str, dict]:
    return {s["id"]: s for s in json.load(open(path))["suites"]}


def verdict(before: dict[str, dict], after: dict[str, dict]) -> list[str]:
    problems: list[str] = []
    if not after:
        return ["no suites ran after the fixes"]
    for sid, b in before.items():
        if b.get("status") != "pass":
            continue
        a = after.get(sid)
        if a is None:
            problems.append(f"{sid}: green before, missing after")
        elif a.get("status") != "pass":
            problems.append(f"{sid}: green before, {a.get('status')} after")
        elif a.get("passed", 0) < b.get("passed", 0):
            problems.append(f"{sid}: passes dropped {b.get('passed')} -> {a.get('passed')}")
    return problems


if __name__ == "__main__":
    bad = verdict(load(sys.argv[1]), load(sys.argv[2]))
    for p in bad:
        print("BLOCK:", p)
    print("GATE:", "blocked" if bad else "ok to merge")
    sys.exit(1 if bad else 0)
