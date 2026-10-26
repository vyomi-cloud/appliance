#!/usr/bin/env python3
"""File actionable upstream changes as GitHub issues — the conformance backlog.

Reads OUT/changes.json (from watch_upstream.py). Every actionable change
becomes one issue labelled `upstream-drift` + `cloud:<aws|gcp|azure>` +
`kind:<…>`, carrying a hidden key so it is never filed twice (keys of filed
issues are kept in OUT/state.json → `filed_keys`). At most MAX issues per run;
the rest wait in `pending` and are filed on later runs.

    OUT=out GITHUB_TOKEN=... GITHUB_REPOSITORY=vyomi-cloud/appliance python3 file_issues.py
"""
from __future__ import annotations

import json
import os
import urllib.request

OUT = os.environ.get("OUT", "out")
REPO = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GITHUB_TOKEN"]
MAX = int(os.environ.get("MAX_ISSUES", "40"))
API = f"https://api.github.com/repos/{REPO}"


def gh(method: str, path: str, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "vyomi-upstream-watch", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        t = r.read()
        return json.loads(t) if t else {}


def ensure_labels(names: set[str]) -> None:
    colors = {"upstream-drift": "b60205", "cloud:aws": "ff9900", "cloud:gcp": "4285f4", "cloud:azure": "0089d6"}
    for n in names:
        try:
            gh("POST", "/labels", {"name": n, "color": colors.get(n, "c5def5")})
        except Exception:
            pass  # already exists


def body_for(c: dict) -> str:
    lines = [f"**Upstream {c['cloud'].upper()} change** affecting `{c['service']}` — `{c['kind']}`.", ""]
    if c.get("link"):
        lines += [f"Source: {c['link']}", ""]
    if c.get("detail"):
        d = c["detail"]
        lines += ["```", (json.dumps(d, indent=1) if not isinstance(d, str) else d)[:3000], "```", ""]
    lines += ["**What to do** (conformance agent, see `tests/conformance/hourly/AGENT.md`):",
              {"operation-added": "- Implement the new operation in the simulator (offline core + Nano), matching the real API's request/response shape.",
               "operation-removed": "- Confirm the removal upstream; keep the simulator accepting it only if real SDKs still call it, otherwise remove it.",
               "operation-changed": "- Update the simulator's request/response handling to the new parameters/members.",
               "operation-deprecated": "- Keep it working, mark it deprecated where the console shows it, and add the replacement if one exists.",
               "api-version": "- Accept the new API version (endpoint/version routing) and add any new operations.",
               "spec-commit": "- Review the spec change; support the new API version and any new or changed operations.",
               "lifecycle": "- Reflect the deprecation/retirement in the simulator (warnings, defaults, console) so local behaviour matches the cloud."}.get(c["kind"], "- Review and adapt the simulator."),
              "- Add or update a conformance test that proves it (official SDK/CLI, endpoint changed only).",
              "- Reference this issue as `Fixes #<n>` in the commit subject so the daily PR closes it.",
              "", f"<!-- upstream-key: {c['key']} -->"]
    return "\n".join(lines)


def main() -> int:
    ch = json.load(open(os.path.join(OUT, "changes.json")))
    st_path = os.path.join(OUT, "state.json")
    state = json.load(open(st_path))
    filed = set(state.get("filed_keys", []))
    queue = [c for c in state.get("pending", []) if c["key"] not in filed]
    queue += [c for c in ch.get("changes", []) if c.get("actionable") and c["key"] not in filed
              and c["key"] not in {q["key"] for q in queue}]
    if queue:
        ensure_labels({"upstream-drift"} | {f"cloud:{c['cloud']}" for c in queue} | {f"kind:{c['kind']}" for c in queue})
    created = []
    for c in queue[:MAX]:
        try:
            iss = gh("POST", "/issues", {"title": f"[upstream] {c['title']}"[:240], "body": body_for(c),
                                         "labels": ["upstream-drift", f"cloud:{c['cloud']}", f"kind:{c['kind']}"]})
            filed.add(c["key"])
            created.append(iss.get("number"))
        except Exception as e:
            print(f"could not file {c['key']}: {e}")
    state["filed_keys"] = sorted(filed)[-20000:]
    state["pending"] = queue[MAX:]
    json.dump(state, open(st_path, "w"))
    print(f"filed {len(created)} issue(s): {created[:20]}; pending {len(state['pending'])}")
    with open(os.path.join(OUT, "summary.md"), "a") as f:
        f.write(f"\nFiled {len(created)} backlog issue(s) labelled `upstream-drift`; {len(state['pending'])} pending.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
