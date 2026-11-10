#!/usr/bin/env python3
"""Close every issue a published release fixed, saying where it shipped.

Scans the commits between the previous release tag and this one (subjects and
bodies, so a squash-merged release PR's per-commit messages count) for GitHub
closing keywords ("Fixes #N", "Closes #N", "Resolves #N"), then for each issue:
comments "Shipped in vX.Y.Z" with the release link — thanking the reporter by name
for issues filed under a person's account, generically for anonymous/bot reports —
and closes it as completed. Idempotent: an issue that already carries the shipped
comment for this version is left alone.

    GH_TOKEN=… python3 scripts/close_shipped_issues.py --version 3.0.25 --prev v3.0.24 \
        [--repo vyomi-cloud/appliance] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

KEYWORDS = re.compile(r"\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\b[:\s]+((?:#\d+(?:\s*,\s*|\s+and\s+|\s*/\s*)?)+)", re.I)
BOTS = re.compile(r"(\[bot\]$|-bot$|^github-actions)", re.I)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def gh(*args: str, check: bool = True) -> str:
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def fixed_issues(prev: str, tag: str) -> list[int]:
    text = git("log", "--format=%B%n", f"{prev}..{tag}")
    nums: set[int] = set()
    for m in KEYWORDS.finditer(text):
        nums |= {int(n) for n in re.findall(r"#(\d+)", m.group(1))}
    return sorted(nums)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--prev", required=True)
    ap.add_argument("--repo", default="vyomi-cloud/appliance")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    tag = f"v{a.version}"
    url = f"https://github.com/{a.repo}/releases/tag/{tag}"
    marker = f"<!-- shipped:{tag} -->"
    done = 0
    for n in fixed_issues(a.prev, tag):
        try:
            it = json.loads(gh("api", f"repos/{a.repo}/issues/{n}"))
        except (RuntimeError, ValueError):
            continue                                    # not visible / doesn't exist
        if it.get("pull_request"):
            continue                                    # "Fixes #N" pointing at a PR
        comments = json.loads(gh("api", f"repos/{a.repo}/issues/{n}/comments?per_page=100") or "[]")
        if any(marker in (c.get("body") or "") for c in comments):
            continue
        it["state"] = it.get("state", "").upper()
        author = (it.get("user") or {}).get("login", "")
        labels = {l["name"] for l in it.get("labels", [])}
        named = author and not BOTS.search(author)
        thanks = f"Thanks for the report, @{author}!" if named else "Thanks to everyone who reported it."
        body = (f"{marker}\n**Shipped in [{tag}]({url}).** {thanks}\n\n"
                + ("Update with `vyomi update` (offline / sandbox). Nano at vyomi.cloud has it now: "
                   "close all Nano tabs and reopen." if "user-reported" in labels or named else
                   "The fix is in this release."))
        print(f"#{n} ({'named @' + author if named else 'bot/anonymous'}, {it['state']}) → shipped in {tag}")
        if a.dry_run:
            continue
        gh("issue", "comment", str(n), "-R", a.repo, "--body", body)
        if it["state"] == "OPEN":
            gh("issue", "close", str(n), "-R", a.repo, "--reason", "completed")
        done += 1
    print(f"{done} issue(s) marked shipped in {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
