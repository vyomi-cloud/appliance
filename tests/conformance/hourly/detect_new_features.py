#!/usr/bin/env python3
"""Find features the conformance suites don't cover yet.

Two lists go to out/new_features.json:
  - new:       API routes / console pages / Nano cores added or changed since the
               last hourly run (BASE_COMMIT env, read from the published history)
  - uncovered: every /api route in the appliance that no test file mentions

The hourly agent writes conformance for "new" first, then works down "uncovered".

    BASE_COMMIT=<sha> python3 tests/conformance/hourly/detect_new_features.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
ROUTE_RE = re.compile(r"""@(?:app|router)\.(get|post|put|patch|delete|api_route)\(\s*["']([^"']+)["']""")
WATCH = ("routes/", "providers/", "core/", "server.py", "static/", "wasm/core/", "wasm/")
TEST_DIRS = ("tests", "wasm/ui-tests", "samples")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def routes_in(text: str) -> set[tuple[str, str]]:
    return {(m.group(1).upper(), m.group(2)) for m in ROUTE_RE.finditer(text)}


def all_routes() -> dict[tuple[str, str], str]:
    found = {}
    for path in ["server.py", *[os.path.join("routes", f) for f in os.listdir(os.path.join(ROOT, "routes")) if f.endswith(".py")]]:
        try:
            for r in routes_in(open(os.path.join(ROOT, path), encoding="utf-8", errors="replace").read()):
                found.setdefault(r, path)
        except OSError:
            pass
    return found


def test_corpus() -> str:
    chunks = []
    for d in TEST_DIRS:
        for base, _, files in os.walk(os.path.join(ROOT, d)):
            if "/out" in base or "node_modules" in base or "/target" in base:
                continue
            for f in files:
                if f.endswith((".py", ".mjs", ".js", ".go", ".java", ".sh", ".json")):
                    try:
                        chunks.append(open(os.path.join(base, f), encoding="utf-8", errors="replace").read())
                    except OSError:
                        pass
    return "\n".join(chunks)


def covered(path: str, corpus: str) -> bool:
    # Match the literal prefix up to the first path parameter, e.g.
    # /api/s3/buckets/{name} → "/api/s3/buckets".
    stem = path.split("{")[0].rstrip("/")
    return bool(stem) and stem in corpus


def main() -> None:
    base = os.environ.get("BASE_COMMIT", "").strip()
    corpus = test_corpus()
    routes = all_routes()

    new = []
    if base and git("cat-file", "-t", base).strip() == "commit":
        changed = [f for f in git("diff", "--name-only", f"{base}..HEAD").split() if f.startswith(WATCH)]
        diff = git("diff", "-U0", f"{base}..HEAD", "--", "server.py", "routes/")
        added = routes_in("\n".join(l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")))
        for method, path in sorted(added):
            new.append({"kind": "api", "method": method, "path": path, "covered": covered(path, corpus)})
        for f in changed:
            if re.search(r"(console|clouds)[^/]*\.html$", f):
                new.append({"kind": "ui", "file": f, "covered": False, "note": "console page changed: re-crawl and extend UI tests"})
            elif f.startswith("wasm/core/") or (f.startswith("core/") and f.endswith("_core.py")):
                name = os.path.basename(f).replace(".py", "")
                new.append({"kind": "core", "file": f, "covered": f"test_{name}" in corpus or name in corpus})
    uncovered = [{"method": m, "path": p, "file": src} for (m, p), src in sorted(routes.items())
                 if p.startswith("/api/") and not covered(p, corpus)]

    out = {"base_commit": base, "head": git("rev-parse", "HEAD").strip(),
           "routes_total": len([r for r in routes if r[1].startswith("/api/")]),
           "routes_uncovered": len(uncovered), "new": new, "uncovered": uncovered}
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "out", "new_features.json"), "w"), indent=1)
    print(f"API routes: {out['routes_total']} total, {out['routes_uncovered']} with no test; "
          f"{len(new)} new/changed since {base[:8] or 'start'} ({sum(1 for n in new if not n['covered'])} uncovered)")


if __name__ == "__main__":
    main()
