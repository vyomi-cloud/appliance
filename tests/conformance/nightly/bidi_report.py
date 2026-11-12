#!/usr/bin/env python3
"""Daily bi-directional run -> issue register.

Reads run_suites.py results for the UI<->API/SDK/CLI (bi-directional / round-trip) suites of a cloud and keeps
docs/architecture/v4.0/V4.0.0-KNOWN-ISSUES.md honest through lib/known_issues.py:
  * a failing check            -> add_issue()  `AUTO-<cloud>-<suite>-<check>` (idempotent: a repeat run refreshes the row)
  * a suite that crashed / timed out / ran no checks -> one `AUTO-<cloud>-<suite>-suite` row
  * a check that PASSES again  -> resolve() its row (self-healing); a fully green suite resolves all of its rows
Suites that did not run (pending, or not in the results) never resolve anything.

    bidi_report.py select --cloud azure --target offline        # comma list of suite ids for `run_suites.py --only`
    bidi_report.py report --cloud azure [--results DIR] [--file MD] [--by COMMIT] [--out changes.json]
                          [--extra SUITE_ID=LOGFILE[=SCRIPT]]...  # optional live-Mesh scripts (log of a script run by hand)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SUITES = ROOT / "tests/conformance/hourly/suites.json"
OUT = ROOT / "tests/conformance/hourly/out"
PATTERN = re.compile(r"bidirectional|roundtrip|round-trip|bidi|validation", re.I)
# Stable ids the gap-map agent registers (pending until built): bidi-<cloud>-<cli|sdk|api>-ui, validation-<cloud>-ui, crawl-<cloud>-ui.
# bidi-/validation- print [PASS]/[FAIL] checks and are mapped here; crawl-<cloud>-ui (and nano-ui-crawl) write the crawler JSON and are
# mapped by crawl_report.py, which `report` runs for you when out/ui-*-<cloud>.json exists.
CRAWL_IDS = re.compile(r"^crawl-|crawl$")
# Suites that match the pattern but cannot pass on the v4 headless image by construction (they target the legacy console);
# reported in the summary, never registered as issues. Remove an id when the suite is retargeted.
EXCLUDE = {"offline-ui-sdk-roundtrip": "targets the legacy /console/aws, not served by v4 (AWS-1 finding, test debt)"}
S1_WORDS = re.compile(r"mismatch|differs?\b|different|wrong|stale|lost|data loss|corrupt|not equal|empty list|missing data", re.I)
CHECK = re.compile(r"^\s*\[(PASS|FAIL|SKIP)\]\s*(.*)$")

_spec = importlib.util.spec_from_file_location("known_issues", HERE / "lib" / "known_issues.py")
ki = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ki)


def slug(text: str, n: int = 60) -> str:
    text = re.sub(r"\d{3,}", "N", text.lower())          # run-specific ids (bd-u542884, timestamps) must not change the key
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:n] or "check"


def suite_script(cmd: str) -> str:
    m = re.search(r"[\w./-]+\.(?:mjs|py|js)\b", cmd or "")
    return m.group(0) if m else "tests/conformance/hourly/suites.json"


def select(cloud: str, target: str | None = None) -> list[dict]:
    out = []
    for s in json.load(open(SUITES))["suites"]:
        if s["id"] in EXCLUDE:
            continue
        is_crawl = bool(CRAWL_IDS.search(s["id"])) and s.get("cloud") in (cloud, "all")
        if not is_crawl and (s.get("cloud") != cloud or not PATTERN.search(s["id"])):
            continue
        if target and s.get("target") != target:
            continue
        out.append(s)
    return out


def parse_log(text: str):
    """-> (fails: {check: detail}, passes: set(check)) from `[PASS]/[FAIL] name :: detail` lines."""
    fails, passes = {}, set()
    for line in text.splitlines():
        m = CHECK.match(line)
        if not m or m.group(1) == "SKIP":
            continue
        name, _, detail = m.group(2).partition(" :: ")
        name = name.strip()
        if m.group(1) == "PASS":
            passes.add(name)
        else:
            fails[name] = detail.strip()
    return fails, passes


def _log_of(res: dict, results_dir: Path) -> str:
    p = results_dir / "logs" / f"{res['id']}{res.get('log_suffix', '')}.log"
    if p.exists():
        return p.read_text(errors="replace")
    return res.get("tail") or ""


def report(cloud: str, results_dir: Path, md: Path, by: str, extras: list[tuple[str, str, str]]) -> dict:
    known = {s["id"]: s for s in select(cloud) if not CRAWL_IDS.search(s["id"])}
    runs = []                                  # (suite_id, script, status, log_text)
    for f in sorted(results_dir.glob(f"results-*-{cloud}.json")):
        for r in json.load(open(f)).get("suites", []):
            if r["id"] in known and r.get("status") != "pending":
                runs.append((r["id"], suite_script(known[r["id"]].get("cmd", "")), r.get("status"), _log_of(r, results_dir), r))
    for sid, logfile, script in extras:        # optional live-Mesh scripts run outside run_suites.py
        text = Path(logfile).read_text(errors="replace") if Path(logfile).exists() else ""
        f, p = parse_log(text)
        runs.append((sid, script or sid, "fail" if f or not p else "pass", text, {}))
    added, updated, resolved, skipped = [], [], [], []
    open_ids = {r["id"] for r in ki.list_open(cloud, md)}
    for sid, script, status, text, res in runs:
        fails, passes = parse_log(text)
        prefix = f"AUTO-{cloud}-{slug(sid, 40)}-"
        if not fails and not passes:
            # crashed / timed out / no checks printed: one suite-level row (never silently green)
            why = (res.get("tail") or text or "no output").strip().splitlines()
            what = f"suite `{sid}` produced no PASS/FAIL checks (crash, timeout or setup failure): " + (" | ".join(why[-3:])[:260] if why else "")
            if status != "pass":
                (added if ki.add_issue(cloud, f"{slug(sid, 40)}-suite", "S2", what, script, path=md) == "added" else updated).append(prefix + "suite")
            continue
        for name, detail in fails.items():
            key = f"{slug(sid, 40)}-{slug(name)}"
            impact = "S1" if S1_WORDS.search(name + " " + detail) else "S2"
            what = f"[{sid}] {name}" + (f": {detail[:240]}" if detail else "")
            state = ki.add_issue(cloud, key, impact, what, script, path=md)
            (added if state == "added" else updated).append(f"AUTO-{cloud}-{key}")
        healed = [i for i in open_ids if i.startswith(prefix) and i not in {f"AUTO-{cloud}-{slug(sid, 40)}-{slug(n)}" for n in fails}]
        if status == "pass" and not fails:
            targets = healed                  # fully green suite: everything it ever reported is fixed (incl. the -suite row)
        else:
            passed_keys = {f"AUTO-{cloud}-{slug(sid, 40)}-{slug(n)}" for n in passes}
            targets = [i for i in healed if i in passed_keys]
        for rid in targets:
            if ki.resolve(rid, by or "daily bi-directional run", md):
                resolved.append(rid)
    for sid, why in EXCLUDE.items():
        if sid in {s["id"] for s in json.load(open(SUITES))["suites"] if s.get("cloud") == cloud}:
            skipped.append(f"{sid}: {why}")
    return {"cloud": cloud, "suites_run": [r[0] for r in runs], "added": sorted(set(added)), "updated": sorted(set(updated)),
            "resolved": sorted(set(resolved)), "excluded": skipped}


def cli_report(cloud: str, results_json: Path, md: Path, by: str) -> dict:
    """tests/release/cli_crosscheck.py results.json -> rows `AUTO-<cloud>-bidi-cli-ui-<check>` (cloud filtered by the check's 'AWS:'/'gcp:'... prefix)."""
    names = {"aws": ("aws", "s3", "sqs", "dynamodb", "sns", "secrets"), "gcp": ("gcp", "gcloud"), "azure": ("azure", "az")}[cloud]
    added, resolved = [], []
    if not results_json.exists():
        return {"cli_checked": 0, "added": added, "resolved": resolved}
    n = 0
    open_ids = {r["id"] for r in ki.list_open(cloud, md)}
    for r in json.load(open(results_json)):
        if r.get("section") not in ("both-ways", "identity"):
            continue
        head = r["name"].split(":", 1)[0].strip().lower()
        if head not in names:
            continue
        n += 1
        key = f"bidi-cli-ui-{slug(r['name'])}"
        rid = f"AUTO-{cloud}-{key}"
        if not r.get("ok"):
            what = f"[bidi-{cloud}-cli-ui] {r['name']}" + (f": {r.get('detail','')[:200]}" if r.get("detail") else "")
            impact = "S1" if S1_WORDS.search(what) or "shows in" in r["name"] else "S2"
            ki.add_issue(cloud, key, impact, what, "tests/release/cli_crosscheck.py", path=md); added.append(rid)
        elif rid in open_ids and ki.resolve(rid, by or "daily bi-directional run", md):
            resolved.append(rid)
    return {"cli_checked": n, "added": added, "resolved": resolved}


def summary(c: dict) -> str:
    L = [f"### Bi-directional daily: {c['cloud']}", f"- suites run: {', '.join(c['suites_run']) or 'none (nothing ran: no results found)'}",
         f"- new issues: {', '.join(c['added']) or 'none'}", f"- still failing (refreshed): {', '.join(c['updated']) or 'none'}",
         f"- resolved (passing again): {', '.join(c['resolved']) or 'none'}"]
    L += [f"- excluded: {e}" for e in c["excluded"]]
    if "cli" in c:
        L.append(f"- CLI<->UI cross-check: {c['cli']['cli_checked']} checks; new {', '.join(c['cli']['added']) or 'none'}; resolved {', '.join(c['cli']['resolved']) or 'none'}")
    if "crawl" in c:
        k = c["crawl"]
        L.append(f"- UI crawl: {k['crawled']} services; new {', '.join(k['added']) or 'none'}; resolved {', '.join(k['resolved']) or 'none'}")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["select", "report"])
    ap.add_argument("--cloud", required=True, choices=["azure", "aws", "gcp"])
    ap.add_argument("--target", choices=["offline", "nano"])
    ap.add_argument("--results", default=str(OUT))
    ap.add_argument("--file", default=str(ki.DEFAULT))
    ap.add_argument("--by", default=os.environ.get("GITHUB_SHA", "")[:9])
    ap.add_argument("--out", default="")
    ap.add_argument("--require-run", action="store_true", help="exit 3 when no bi-directional suite produced results (never a silent empty run)")
    ap.add_argument("--cli-results", default="", help="tests/release/cli_crosscheck.py results.json (CLI<->UI both ways)")
    ap.add_argument("--ui", action="append", default=[], help="crawler JSON (default: out/ui-*-<cloud>.json when present)")
    ap.add_argument("--extra", action="append", default=[], help="SUITE_ID=LOGFILE[=SCRIPT]")
    a = ap.parse_args(argv)
    if a.cmd == "select":
        print(",".join(s["id"] for s in select(a.cloud, a.target)))
        return 0
    extras = [tuple((e.split("=", 2) + [""])[:3]) for e in a.extra]
    c = report(a.cloud, Path(a.results), Path(a.file), a.by, extras)
    if a.cli_results:
        c["cli"] = cli_report(a.cloud, Path(a.cli_results), Path(a.file), a.by)
    ui = a.ui or sorted(str(x) for x in Path(a.results).glob(f"ui-*-{a.cloud}.json"))
    if ui:
        spec = importlib.util.spec_from_file_location("crawl_report", HERE / "crawl_report.py")
        cr = importlib.util.module_from_spec(spec); spec.loader.exec_module(cr)
        c["crawl"] = cr.report(a.cloud, ui, Path(a.file), a.by)
        c["added"] = sorted(set(c["added"]) | set(c["crawl"]["added"]) | set(c.get("cli", {}).get("added", [])))
        c["resolved"] = sorted(set(c["resolved"]) | set(c["crawl"]["resolved"]) | set(c.get("cli", {}).get("resolved", [])))
        c["suites_run"] = c["suites_run"] + (["ui-crawl"] if c["crawl"]["crawled"] else [])
    elif "cli" in c:
        c["added"] = sorted(set(c["added"]) | set(c["cli"]["added"])); c["resolved"] = sorted(set(c["resolved"]) | set(c["cli"]["resolved"]))
    text = summary(c)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(text)
    if a.out:
        json.dump(c, open(a.out, "w"), indent=1)
    return 3 if (a.require_run and not c["suites_run"]) else 0


if __name__ == "__main__":
    sys.exit(main())
