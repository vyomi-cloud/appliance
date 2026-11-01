#!/usr/bin/env python3
"""Run the hourly conformance manifest (suites.json) and write out/results.json.

Each suite is a shell command; its pass/fail comes from the exit code plus the
PASS/FAIL (or ✓/✗, or pytest "N passed, M failed") lines it prints. UI crawl
suites are scored from their findings JSON: a service with no findings passes.

    python3 tests/conformance/hourly/run_suites.py                    # everything
    python3 tests/conformance/hourly/run_suites.py --target nano      # one target
    python3 tests/conformance/hourly/run_suites.py --only nano-ui-aws-api,offline-cli-aws
    python3 tests/conformance/hourly/run_suites.py --target offline --cloud gcp   # one detect shard
Detect shards (--target T --cloud C) run that target's suites for one cloud and
write out/results-T-C.json. The UI crawls (cloud "all") run in every cloud shard,
limited to that cloud's console (CLOUDS env) and writing ui-T-C.json; any other
"all" suite runs in the aws shard of its target. merge_shards.py joins them.

Env: VYOMI_BASE_URL (offline sim, default http://localhost:9000),
     RELAY_HTTP (Nano relay, default http://127.0.0.1:8090).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
OUT = os.path.join(HERE, "out")

PASS_RE = re.compile(r"\[(?:PASS|OK|✓)\s*\]|^\s*(?:PASS|✓)\b|\bPASS\b(?: \(|:)|\s✓\s", re.M)
FAIL_RE = re.compile(r"\[(?:FAIL|✗)\]|^\s*(?:FAIL|✗)\b|\bFAIL\b(?: \(|:)|\s✗\s", re.M)
PYTEST_RE = re.compile(r"(\d+) (passed|failed|error|errors)\b")
# Never publish anything that looks like a credential in the public page.
SECRET_RE = re.compile(r"(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16})")


def scrub(text: str) -> str:
    return SECRET_RE.sub("[redacted]", text)


def count(log: str) -> tuple[int, int]:
    py = PYTEST_RE.findall(log)
    if py:
        passed = sum(int(n) for n, k in py if k == "passed")
        failed = sum(int(n) for n, k in py if k != "passed")
        return passed, failed
    return len(PASS_RE.findall(log)), len(FAIL_RE.findall(log))


def ui_score(path: str) -> tuple[int, int, list]:
    try:
        data = json.load(open(path))
    except Exception:
        return 0, 1, [{"service": "(crawl)", "findings": [{"type": "CRAWL_ERROR", "detail": "no findings file written"}]}]
    rows = data.get("services", [])
    broken = [r for r in rows if r.get("status") != "ok"]
    return len(rows) - len(broken), len(broken), broken


CLOUDS = ("aws", "gcp", "azure")
SHARD_HOME = "aws"   # cloud-less suites (other than the crawls) run in this cloud's shard


def is_crawl(s: dict) -> bool:
    return s["kind"] == "ui" and "ui_crawler" in s["cmd"]


def in_shard(s: dict, cloud: str) -> bool:
    """Whether suite `s` belongs to the `cloud` shard of its target."""
    if s.get("cloud") in CLOUDS:
        return s["cloud"] == cloud
    return is_crawl(s) or cloud == SHARD_HOME


def for_shard(s: dict, cloud: str) -> dict:
    """A crawl split per cloud: its console filter and its own output file."""
    if not is_crawl(s):
        return s
    s = dict(s)
    s["cmd"] = re.sub(r"OUT=(\S+?)\.json", lambda m: f"OUT={m.group(1)}-{cloud}.json", s["cmd"])
    s["cmd"] = f"CLOUDS={cloud} " + s["cmd"]
    s["log_suffix"] = f".{cloud}"
    return s


_PROJECT = {}


def gcp_project(endpoint: str) -> str:
    """The GCP space's project id. Only it (or its number) reaches the project:
    any other id (gcp-dev, cloudlearn, a suite's own default) is "project not
    found", as on real GCP. Suites read it from $PROJECT."""
    if endpoint not in _PROJECT:
        try:
            import urllib.request
            with urllib.request.urlopen(endpoint + "/v1/projects", timeout=10) as r:
                _PROJECT[endpoint] = json.load(r)["projects"][0]["projectId"]
        except Exception:
            _PROJECT[endpoint] = ""
    return _PROJECT[endpoint]


def run_suite(s: dict, subs: dict) -> dict:
    cmd = s["cmd"]
    env = dict(os.environ)
    if s.get("cloud") == "gcp" and s.get("target") == "offline" and subs.get("ENDPOINT"):
        proj = gcp_project(subs["ENDPOINT"])
        if proj:
            env.setdefault("PROJECT", proj)
    for k, v in subs.items():
        cmd = cmd.replace("{" + k + "}", v)
    cwd = os.path.join(ROOT, s.get("cwd", ""))
    os.makedirs(os.path.join(OUT, "logs"), exist_ok=True)
    log_path = os.path.join(OUT, "logs", f"{s['id']}{s.get('log_suffix', '')}.log")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True,
                           timeout=s.get("timeout", 600), executable="/bin/bash", env=env)
        log, code = (p.stdout or "") + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired as e:
        log = ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) + "\nTIMEOUT"
        code = 124
    log = scrub(log)
    open(log_path, "w").write(log)

    res = {k: s.get(k) for k in ("id", "target", "cloud", "kind")}
    res["duration_s"] = round(time.time() - t0, 1)
    res["exit_code"] = code
    if is_crawl(s):
        m = re.search(r"OUT=(\S+)", s["cmd"])
        passed, failed, broken = ui_score(os.path.join(ROOT, m.group(1)) if m else "")
        res["broken_services"] = broken
    else:
        passed, failed = count(log)
        if code != 0 and failed == 0:
            failed = 1  # crashed / non-zero without printing a FAIL line
        if passed == 0 and failed == 0:
            failed = 1  # nothing was checked: never report an empty run as green
            log += "\nNO CHECKS RAN (no PASS/FAIL lines recognised)"
    res["passed"], res["failed"] = passed, failed
    res["status"] = "pass" if failed == 0 and (code == 0 or s["kind"] == "ui") else "fail"
    res["tail"] = "\n".join(log.strip().splitlines()[-30:])[-3000:]
    print(f"  {res['status'].upper():4} {s['id']:<28} {passed} passed, {failed} failed ({res['duration_s']}s)", flush=True)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="all", choices=["all", "offline", "nano"])
    ap.add_argument("--only", default="")
    ap.add_argument("--cloud", default="all", choices=["all", *CLOUDS],
                    help="one detect shard: needs --target offline|nano")
    a = ap.parse_args()
    if a.cloud != "all" and a.target == "all":
        ap.error("--cloud needs --target offline or nano")

    endpoint = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
    u = urlparse(endpoint)
    subs = {"ENDPOINT": endpoint, "ENDPOINT_HOSTPORT": u.netloc,
            "RELAY": os.environ.get("RELAY_HTTP", "http://127.0.0.1:8090")}

    suites = json.load(open(os.path.join(HERE, "suites.json")))["suites"]
    only = {x for x in a.only.split(",") if x}
    suites = [s for s in suites if (a.target == "all" or s["target"] == a.target) and (not only or s["id"] in only)]
    if a.cloud != "all":
        suites = [for_shard(s, a.cloud) for s in suites if in_shard(s, a.cloud)]

    # Two lanes, one per target, each sequential: offline suites share the
    # appliance's active space (the offline crawl creates resources and checks
    # cost-savings deltas), so they must not overlap each other; Nano suites run
    # in their own headless browser stores and never touch the appliance. Run as
    # one queue, 105 suites (two ~20-min crawls) overran the detect job.
    lanes = [[s for s in suites if s["target"] == t] for t in ("offline", "nano")]
    lanes.append([s for s in suites if s["target"] not in ("offline", "nano")])
    done: dict = {}
    with ThreadPoolExecutor(max_workers=len(lanes)) as pool:
        for part in pool.map(lambda lane: {s["id"]: run_suite(s, subs) for s in lane}, lanes):
            done |= part
    results = [done[s["id"]] for s in suites]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    out = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "commit": commit, "suites": results}
    os.makedirs(OUT, exist_ok=True)
    # A partial re-run (--only / --target, e.g. the agent verifying a fix) must
    # not overwrite the full hour's results the report is built from.
    if a.cloud != "all":
        name = f"results-{a.target}-{a.cloud}.json"   # a detect shard (merge_shards.py joins them)
    else:
        name = "results.json" if (a.target == "all" and not only) else "results-partial.json"
    json.dump(out, open(os.path.join(OUT, name), "w"), indent=1)
    bad = [r["id"] for r in results if r["status"] != "pass"]
    print(f"\n{len(results) - len(bad)}/{len(results)} suites green" + (f"; failing: {', '.join(bad)}" if bad else ""))
    return 0  # the agent and the page decide what to do with failures


if __name__ == "__main__":
    sys.exit(main())
