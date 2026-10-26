#!/usr/bin/env python3
"""File the new-service backlog as GitHub issues (label `new-service`).

One issue per not-yet-released service in services/catalog.json: all P1 first;
P2 is opened once fewer than P2_WHEN open P1 issues remain; P3 never in bulk.
Idempotent: an issue already filed for a service (open or closed) is skipped,
matched by its hidden `expansion:` marker.

    GITHUB_TOKEN=... GITHUB_REPOSITORY=vyomi-cloud/appliance python3 file_backlog.py
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
REPO, TOKEN = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
API = f"https://api.github.com/repos/{REPO}"
P2_WHEN = int(os.environ.get("P2_WHEN", "5"))
MAX = int(os.environ.get("MAX_ISSUES", "50"))


def gh(method, path, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "vyomi-expansion", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        t = r.read()
        return json.loads(t) if t else {}


def existing() -> dict[str, dict]:
    found, page = {}, 1
    while True:
        items = gh("GET", f"/issues?labels=new-service&state=all&per_page=100&page={page}")
        for it in items:
            m = re.search(r"<!-- expansion: cloud=(\w+) key=([\w.-]+)", it.get("body") or "")
            if m:
                found[f"{m.group(1)}:{m.group(2)}"] = it
        if len(items) < 100:
            return found
        page += 1


def key_of(s: dict) -> str:
    return s["id"].split("/")[0].replace("_", "-")


def body(s: dict) -> str:
    k = key_of(s)
    return "\n".join([
        f"**New service: {s['cloud'].upper()} {s['name']}** (upstream `{s['id']}`, {s['priority']}"
        + (f", {s['operations']} operations upstream" if s.get("operations") else "") + ").",
        "",
        f"Built by the expansion agent on branch `expansion/{s['cloud']}-{k}` and released only when the service gate "
        "passes (`tests/conformance/expansion/EXPANSION.md`):",
        "",
        "- [ ] Engine in `core/` (substrate-free, shared with Nano), real request/response shapes and errors",
        "- [ ] Native SDK + CLI wire (endpoint override only)",
        "- [ ] Nano: core vendored byte-identical + wired",
        "- [ ] Console UI offline + Nano (catalog, defaults, detail tabs, no blank cells, cost savings)",
        "- [ ] Java + Go SDK test beds, CLI smoke",
        "- [ ] Playwright console tests, offline + Nano",
        "- [ ] Registered in hourly suites + upstream watcher",
        "- [ ] Registry entry + manifest; gate green → release",
        "",
        f"<!-- expansion: cloud={s['cloud']} key={k} upstream={s['id']} priority={s['priority']} -->",
    ])


def ensure_labels():
    for name, color in (("new-service", "0e8a16"), ("priority:P1", "b60205"), ("priority:P2", "fbca04"),
                        ("priority:P3", "c5def5"), ("in-progress", "1d76db"), ("blocked", "000000"),
                        ("cloud:aws", "ff9900"), ("cloud:gcp", "4285f4"), ("cloud:azure", "0089d6")):
        try:
            gh("POST", "/labels", {"name": name, "color": color})
        except Exception:
            pass


def main() -> int:
    cat = json.load(open(os.path.join(ROOT, "services", "catalog.json")))
    have = existing()
    todo = [s for s in cat["services"] if s["status"] != "released" and s["priority"] in ("P1", "P2")
            and f"{s['cloud']}:{key_of(s)}" not in have]
    open_p1 = sum(1 for it in have.values() if it["state"] == "open"
                  and any(l["name"] == "priority:P1" for l in it.get("labels", [])))
    open_p1 += sum(1 for s in todo if s["priority"] == "P1")
    if open_p1 >= P2_WHEN:
        todo = [s for s in todo if s["priority"] == "P1"]
    if todo:
        ensure_labels()
    filed = []
    for s in todo[:MAX]:
        it = gh("POST", "/issues", {"title": f"[new service] {s['cloud'].upper()}: {s['name']}",
                                    "body": body(s), "labels": ["new-service", f"priority:{s['priority']}", f"cloud:{s['cloud']}"]})
        filed.append(it.get("number"))
    print(f"filed {len(filed)} new-service issue(s); already tracked {len(have)}; open P1 {open_p1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
