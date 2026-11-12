#!/usr/bin/env python3
"""v4 release checklist: deterministic checks that must be green before a v4.x release is cut, per cloud.

Stdlib only; runs locally and in CI (.github/workflows/v4-release-checklist.yml).

    python3 tests/release/v4_checklist.py --cloud azure [--version 4.0.0] [--sha <sha>] [--results DIR] [--out DIR]
    python3 tests/release/v4_checklist.py --cloud all

Every check returns PASS, FAIL, SKIPPED (with the reason it could not run) or WAIVED (a FAIL the caller accepted with --waive ID=reason,
shown in the report). Nothing passes silently: a check that cannot run is SKIPPED, never PASS. Exit code 1 if any check FAILs
(--strict-skips: SKIPPED also fails). Reports: report.json + report.md in --out, markdown also on stdout.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CLOUDS = ("azure", "aws", "gcp")
PREFIX = {"azure": ("AZ-", "AUTO-azure-"), "aws": ("AWS-", "AUTO-aws-"), "gcp": ("GCP-", "GW-", "AUTO-gcp-")}
GLOBAL_PREFIX = ("CI-", "NANO-", "MESH-")
KI_PATH = "docs/architecture/v4.0/V4.0.0-KNOWN-ISSUES.md"
SUITES_PATH = "tests/conformance/hourly/suites.json"
REPO = "vyomi-cloud/appliance"

PASS, FAIL, SKIPPED, WAIVED = "PASS", "FAIL", "SKIPPED", "WAIVED"


def R(cid, scope, status, reason):
    return {"id": cid, "scope": scope, "status": status, "reason": reason}


def run(cmd, cwd, timeout=300, env=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ── known issues ────────────────────────────────────────────────────────────
_ROW = re.compile(r"^\|\s*([A-Z][A-Z0-9]*-[A-Za-z0-9_.-]+)\s*\|")


def open_rows(root: Path):
    """[(id, impact, what)] for rows outside the 'Resolved' section."""
    p = root / KI_PATH
    if not p.exists():
        return None
    rows, head = [], ""
    for line in p.read_text().splitlines():
        if line.startswith("## "):
            head = line.strip()
        m = _ROW.match(line)
        if m and head != "## Resolved after the cut":
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.append((m.group(1), cells[1] if len(cells) > 1 else "", cells[2] if len(cells) > 2 else ""))
    return rows


def check_known_issues(root: Path, cloud: str | None):
    scope = cloud or "global"
    rows = open_rows(root)
    if rows is None:
        return R("known-issues-no-open-S1", scope, FAIL, f"{KI_PATH} is missing")
    pre = PREFIX[cloud] if cloud else GLOBAL_PREFIX
    mine = [r for r in rows if r[0].startswith(pre)]
    s1 = [r[0] for r in mine if re.match(r"^S1\b", r[1])]
    if s1:
        return R("known-issues-no-open-S1", scope, FAIL, f"open S1 (data loss / wrong answer): {', '.join(s1)}")
    return R("known-issues-no-open-S1", scope, PASS, f"{len(mine)} open row(s) for {scope}, none S1")


# ── wasm/core sync, loaders, pyodide ───────────────────────────────────────
_SKIP_DIRS = {"vm", "v4", "assets", "parquet", "docs", "vendor", "node_modules", "ui-tests", "videos"}


def _copy_for_build(root: Path, dst: Path):
    shutil.copytree(root / "core", dst / "core", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(root / "wasm", dst / "wasm",
                    ignore=lambda d, names: [n for n in names if n in _SKIP_DIRS or n == "__pycache__" or n.endswith((".pyc", ".bak"))]
                    if Path(d) == root / "wasm" else [n for n in names if n in ("__pycache__", "node_modules")])


def _diff_trees(a: Path, b: Path):
    out = []
    cmp = filecmp.dircmp(a, b)
    out += [f"only in repo: {a.name}/{n}" for n in cmp.left_only if n != "__pycache__"]
    out += [f"missing in repo: {a.name}/{n}" for n in cmp.right_only if n != "__pycache__"]
    out += [f"differs: {a.name}/{n}" for n in cmp.diff_files]
    for sub in cmp.common_dirs:
        if sub != "__pycache__":
            out += _diff_trees(a / sub, b / sub)
    return out


def check_wasm_core_sync(root: Path):
    cid = "wasm-core-in-sync"
    if not (root / "wasm/build_cores.py").exists():
        return R(cid, "global", SKIPPED, "wasm/build_cores.py not present")
    tmp = Path(tempfile.mkdtemp(prefix="v4chk-"))
    try:
        _copy_for_build(root, tmp)
        rc, out = run([sys.executable, "wasm/build_cores.py"], tmp)
        if rc != 0:
            return R(cid, "global", FAIL, "build_cores.py failed in a clean copy: " + out.strip().splitlines()[-1][:200])
        diffs = _diff_trees(root / "wasm/core", tmp / "wasm/core")
        nb_a, nb_b = root / "wasm/fixtures/nano-backends.json", tmp / "wasm/fixtures/nano-backends.json"
        if nb_a.exists() and nb_b.exists() and not filecmp.cmp(nb_a, nb_b, shallow=False):
            diffs.append("differs: wasm/fixtures/nano-backends.json")
        if diffs:
            return R(cid, "global", FAIL, f"wasm/core is stale vs core/ ({len(diffs)} file(s)): " + "; ".join(diffs[:6])
                     + " -> run `python3 wasm/build_cores.py` and commit")
        return R(cid, "global", PASS, "re-vendoring core/ into a clean copy produces no diff")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_loader_lists(root: Path):
    cid = "nano-loaders-complete"
    if not (root / "wasm/build_cores.py").exists():
        return R(cid, "global", SKIPPED, "wasm/build_cores.py not present")
    rc, out = run([sys.executable, "wasm/build_cores.py", "--check"], root)
    if rc != 0:
        return R(cid, "global", FAIL, "build_cores.py --check: " + " | ".join(l.strip() for l in out.splitlines() if l.strip())[:300])
    # the main Nano loader (nano-boot.js) is not in build_cores' relay list: apply the same import-closure rule to it
    import importlib.util
    spec = importlib.util.spec_from_file_location("v4chk_build_cores", root / "wasm/build_cores.py")
    bc = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(bc)
    except Exception as exc:
        return R(cid, "global", SKIPPED, f"could not import build_cores.py to check nano-boot.js: {exc}")
    boot = root / "wasm/nano-boot.js"
    listed = bc._cores_in(boot.read_text()) if boot.exists() else set()
    if not listed:
        return R(cid, "global", SKIPPED, "nano-boot.js has no `const CORES` list to check")
    missing = []
    for mod in sorted(listed):
        if (root / "core" / mod).exists():
            missing += [f"{mod} -> {d}" for d in sorted(bc._deps_of(mod) - listed) if (root / "core" / d).exists()]
    if missing:
        return R(cid, "global", FAIL, "nano-boot.js CORES is not import-closed (browser boot would ImportError): " + "; ".join(missing[:6]))
    return R(cid, "global", PASS, f"relay loaders + CORE_PKGS + nano-boot.js ({len(listed)} cores) are import-closed")


def check_pyodide(root: Path):
    cid = "pyodide-source-consistent"
    f = root / "wasm/pyodide-source.json"
    if not f.exists():
        return R(cid, "global", FAIL, "wasm/pyodide-source.json missing (loaders would probe a path that 404s)")
    try:
        local = bool(json.loads(f.read_text()).get("local"))
    except Exception as exc:
        return R(cid, "global", FAIL, f"wasm/pyodide-source.json is not valid JSON: {exc}")
    have = (root / "wasm/vendor/pyodide/pyodide.mjs").exists()
    if local and not have:
        return R(cid, "global", FAIL, "pyodide-source.json says local:true but wasm/vendor/pyodide/pyodide.mjs is absent (404 at runtime)")
    if have and not local:
        return R(cid, "global", FAIL, "wasm/vendor/pyodide is present but pyodide-source.json says local:false (runtime would be ignored); run wasm/fetch_pyodide.py")
    return R(cid, "global", PASS, "local:true with the runtime vendored" if local else "local:false (CDN) and no vendored runtime: consistent")


def check_no_bak(root: Path):
    cid = "no-stray-bak-in-wasm"
    bad = [str(p.relative_to(root)) for p in (root / "wasm").rglob("*.bak")] if (root / "wasm").exists() else []
    return R(cid, "global", FAIL, f"{len(bad)} *.bak under wasm/ (the portal sync would copy them): {', '.join(bad[:5])}") if bad \
        else R(cid, "global", PASS, "no *.bak under wasm/")


# ── suites ─────────────────────────────────────────────────────────────────
def _suites(root: Path):
    d = json.loads((root / SUITES_PATH).read_text())
    return d["suites"] if isinstance(d, dict) else d


def check_suites_valid(root: Path):
    cid = "suites-json-valid"
    try:
        ss = _suites(root)
    except Exception as exc:
        return R(cid, "global", FAIL, f"{SUITES_PATH} unreadable: {exc}")
    ids, bad = set(), []
    for s in ss:
        i = s.get("id")
        if not i or i in ids:
            bad.append(f"duplicate/missing id {i!r}")
        ids.add(i)
        if "pending" in s:
            if not (isinstance(s["pending"], str) and s["pending"].strip()):
                bad.append(f"{i}: pending without a reason")
        elif not s.get("cmd"):
            bad.append(f"{i}: no cmd and not pending")
    return R(cid, "global", FAIL, "; ".join(bad[:6])) if bad else R(cid, "global", PASS, f"{len(ss)} suites; ids unique; every pending has a reason")


def check_suites_registered(root: Path, cloud: str):
    cid = "suites-registered"
    try:
        ss = [s for s in _suites(root) if s.get("cloud") in (cloud, "all")]
    except Exception as exc:
        return R(cid, cloud, FAIL, f"{SUITES_PATH} unreadable: {exc}")
    live = lambda t: [s for s in ss if s.get("target") == t and "pending" not in s]
    off, nano = live("offline"), live("nano")
    if not off or not nano:
        return R(cid, cloud, FAIL, f"live suites: offline={len(off)} nano={len(nano)} (need both)")
    bidi = [s["id"] for s in ss if "pending" not in s and re.search(r"bidirectional|bi-directional|roundtrip", s["id"])]
    if not [b for b in bidi if cloud in b]:
        return R(cid, cloud, FAIL, f"no live bi-directional/roundtrip suite registered for {cloud}")
    pend = [s["id"] for s in ss if "pending" in s]
    return R(cid, cloud, PASS, f"offline={len(off)} nano={len(nano)} live; bi-directional: {', '.join(b for b in bidi if cloud in b)}; "
                                f"{len(pend)} pending (reported, not gating)")


def check_results(root: Path, cloud: str, results: Path | None):
    cid = "suite-results"
    if not results:
        return R(cid, cloud, SKIPPED, "no --results DIR given (run `run_suites.py --target offline|nano --cloud <c> --strict` first)")
    files = sorted(results.glob(f"results-*-{cloud}.json"))
    if not files:
        return R(cid, cloud, FAIL, f"no results-*-{cloud}.json in {results}")
    tot = fail = 0
    red = []
    targets = set()
    for f in files:
        targets.add(f.name.split("-")[1])
        for s in json.loads(f.read_text()).get("suites", []):
            tot += 1
            if s.get("status") in ("fail", "FAIL", "failed") or s.get("failed"):
                fail += 1
                red.append(s.get("id", "?"))
    need = {"offline", "nano"} - targets
    if need:
        return R(cid, cloud, FAIL, f"results missing for target(s): {', '.join(sorted(need))}")
    if fail:
        return R(cid, cloud, FAIL, f"{fail}/{tot} suites failed: {', '.join(red[:8])}")
    return R(cid, cloud, PASS, f"{tot} suites, 0 failed (offline + nano)")


def check_console_bundle(root: Path, cloud: str):
    cid = "v4-console-bundle"
    d = root / "wasm/v4" / cloud
    missing = [n for n in ("index.html", "main.js") if not (d / n).exists() or (d / n).stat().st_size == 0]
    return R(cid, cloud, FAIL, f"wasm/v4/{cloud}/ lacks {', '.join(missing)}") if missing else R(cid, cloud, PASS, f"wasm/v4/{cloud}/ has index.html + main.js")


# ── release plumbing ───────────────────────────────────────────────────────
def check_image_published(root: Path, sha: str | None):
    cid = "image-published"
    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")) or not shutil.which("gh"):
        return R(cid, "global", SKIPPED, "needs `gh` and GH_TOKEN to read the docker-publish runs")
    try:
        rc, out = run(["gh", "run", "list", "-R", REPO, "--workflow", "docker-publish.yml", "--limit", "20",
                       "--json", "conclusion,headSha,createdAt"], root, 60)
        runs = json.loads(out) if rc == 0 else None
    except Exception as exc:
        return R(cid, "global", SKIPPED, f"could not query docker-publish runs: {exc}")
    if runs is None:
        return R(cid, "global", SKIPPED, "gh run list failed: " + out.strip()[:160])
    rc, head = run(["git", "rev-parse", sha or "HEAD"], root)
    want = head.strip()
    for r in runs:
        if r.get("conclusion") != "success":
            continue
        # the image built from this sha or from any later commit contains it
        if r["headSha"] == want or run(["git", "merge-base", "--is-ancestor", want, r["headSha"]], root)[0] == 0:
            return R(cid, "global", PASS, f"docker-publish succeeded at {r['headSha'][:9]} (contains {want[:9]}, {r['createdAt']})")
    return R(cid, "global", FAIL, f"no successful docker-publish run contains {want[:9]} in the last 20 runs")


def check_tunnel_sync(root: Path):
    cid = "tunnel-version-sync"
    pj, rb = root / "packaging/tunnel/package.json", root / "packaging/brew/vyomi-tunnel.rb"
    if not pj.exists() or not rb.exists():
        return R(cid, "global", SKIPPED, "packaging/tunnel/package.json or packaging/brew/vyomi-tunnel.rb not present")
    ver = json.loads(pj.read_text()).get("version", "")
    m = re.search(r"vyomi-tunnel-(\d+\.\d+\.\d+)\.tgz", rb.read_text())
    if not m:
        return R(cid, "global", FAIL, "no vyomi-tunnel-<ver>.tgz url in the Homebrew formula")
    if m.group(1) != ver:
        return R(cid, "global", FAIL, f"packaging/tunnel is {ver} but the Homebrew formula serves {m.group(1)} (publish + update url/sha256, or waive if the tunnel ships bundled)")
    ts = root / "scripts/tunnel_sync.py"
    if ts.exists():
        rc, out = run([sys.executable, str(ts), "status"], root, 90)
        if rc != 0:
            if re.search(r"urlopen error|Name or service|timed out|Temporary failure|Network is unreachable", out):
                return R(cid, "global", SKIPPED, f"formula/package agree at {ver}; the npm/tap registry check needs network: " + out.strip().splitlines()[-1][:120])
            return R(cid, "global", FAIL, "scripts/tunnel_sync.py status: " + out.strip().splitlines()[-1][:200])
        return R(cid, "global", PASS, f"package.json, formula and registry agree at {ver}")
    return R(cid, "global", PASS, f"package.json and the Homebrew formula agree at {ver} (registry check skipped: scripts/tunnel_sync.py not present)")


def check_branch_doc(root: Path, branch: str | None):
    cid = "branch-document"
    if not branch:
        return R(cid, "global", SKIPPED, "no --branch given")
    if not branch.startswith("v4/"):
        return R(cid, "global", SKIPPED, f"{branch}: the pre-push hook only asks topic branches (v4/<topic>) for a document")
    topic = branch.split("/", 1)[1]
    cand = [root / f"docs/architecture/v4.0/branches/{topic}.md", root / f"docs/branches/{topic}.md"]
    return R(cid, "global", PASS, f"found {next(str(c.relative_to(root)) for c in cand if c.exists())}") if any(c.exists() for c in cand) \
        else R(cid, "global", FAIL, f"no docs/architecture/v4.0/branches/{topic}.md (pre-push hook asks for one)")


# ── driver ─────────────────────────────────────────────────────────────────
def run_checks(root: Path, cloud: str, version: str | None, sha: str | None, results: Path | None, branch: str | None):
    out = [check_known_issues(root, None), check_wasm_core_sync(root), check_loader_lists(root), check_pyodide(root),
           check_no_bak(root), check_suites_valid(root), check_image_published(root, sha), check_tunnel_sync(root),
           check_branch_doc(root, branch)]
    for c in (CLOUDS if cloud == "all" else (cloud,)):
        out += [check_known_issues(root, c), check_suites_registered(root, c), check_results(root, c, results),
                check_console_bundle(root, c)]
    return out


def apply_waivers(checks, waive):
    for c in checks:
        key = f"{c['id']}" if f"{c['id']}" in waive else f"{c['scope']}:{c['id']}"
        if c["status"] == FAIL and (c["id"] in waive or key in waive):
            c["status"], c["reason"] = WAIVED, f"WAIVED ({waive.get(c['id']) or waive.get(key)}): {c['reason']}"
    return checks


def markdown(checks, cloud, version, sha):
    n = lambda s: sum(c["status"] == s for c in checks)
    lines = [f"# v4 release checklist: {cloud} {version or ''} {('@ ' + sha[:9]) if sha else ''}".strip(), "",
             f"**{n(PASS)} PASS, {n(FAIL)} FAIL, {n(SKIPPED)} SKIPPED, {n(WAIVED)} WAIVED**", "",
             "| Scope | Check | Status | Detail |", "|---|---|---|---|"]
    mark = {PASS: "PASS", FAIL: "**FAIL**", SKIPPED: "SKIPPED", WAIVED: "WAIVED"}
    for c in checks:
        lines.append(f"| {c['scope']} | {c['id']} | {mark[c['status']]} | {c['reason'].replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cloud", choices=list(CLOUDS) + ["all"], required=True)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--version"); ap.add_argument("--sha"); ap.add_argument("--branch")
    ap.add_argument("--results", help="dir with the run_suites.py results-<target>-<cloud>.json files")
    ap.add_argument("--out", help="write report.json + report.md here")
    ap.add_argument("--waive", action="append", default=[], metavar="ID=reason", help="accept a FAIL; shown as WAIVED in the report")
    ap.add_argument("--strict-skips", action="store_true", help="SKIPPED also fails the run")
    a = ap.parse_args(argv)
    waive = dict(w.split("=", 1) for w in a.waive if "=" in w)
    root = Path(a.root)
    checks = apply_waivers(run_checks(root, a.cloud, a.version, a.sha, Path(a.results) if a.results else None, a.branch), waive)
    md = markdown(checks, a.cloud, a.version, a.sha)
    print(md)
    if a.out:
        o = Path(a.out); o.mkdir(parents=True, exist_ok=True)
        (o / "report.json").write_text(json.dumps({"cloud": a.cloud, "version": a.version, "sha": a.sha, "checks": checks}, indent=1))
        (o / "report.md").write_text(md)
    bad = [c for c in checks if c["status"] == FAIL or (a.strict_skips and c["status"] == SKIPPED)]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
