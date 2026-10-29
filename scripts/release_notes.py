#!/usr/bin/env python3
"""Release notes for one appliance release: CHANGELOG entry + README "Latest release".

Collects every change that ships in the release, not just the release PR's commits:
  - commits pushed straight to main since the previous tag (first-parent), and
  - the release PR's commits that were not already in the previous tag (a daily
    branch carries history from earlier releases; those are dropped),
then groups them for readers: Highlights, New services, Fixes by cloud (each tagged
Nano / offline / Nano + offline), Platform and release pipeline, How to upgrade.

    python3 scripts/release_notes.py --version 3.0.25 --prev v3.0.24 \
        [--pr-head <sha>] [--kind "Daily conformance release"] \
        [--highlights /tmp/highlights.md] [--new-services /tmp/added.md] \
        [--write-changelog] [--write-readme] [--out notes.md] [--commits-out commits.txt]

Highlights come from --highlights when given (the release workflow has Claude write
them from --commits-out); otherwise the most user-visible changes are listed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys

CLOUD_RE = [
    ("Azure", r"\bazure\b|cosmos|key ?vault|\bblob\b|\barm\b|\bapim\b|container apps|app configuration|log analytics|"
              r"monitor alert|dns zone|role definition|entra|service bus|event grid|function app"),
    ("GCP", r"\bgcp\b|\bgcs\b|pub/?sub|firestore|cloud run|\bgke\b|kubernetes engine|cloud kms|cloud sql|eventarc|"
            r"memorystore|cloud scheduler|compute engine|\bgce\b|secret manager|cloud functions|\bmtu\b|ipv4 range"),
    ("AWS", r"\baws\b|\bec2\b|\bs3\b|lambda|dynamodb|\biam\b|\bsqs\b|\bsns\b|\brds\b|\bkms\b|eventbridge|cloudwatch|"
            r"security group|internet gateway|route table|\bdhcp\b|\belb|step functions|api gateway|systems manager|\bssm\b|secrets manager|\bsts\b"),
]
PLATFORM_PREFIX = re.compile(r"^(ci|docs|chore|build|test|refactor|release)(\+[a-z]+)*(\(|:)", re.I)
SKIP = re.compile(r"^(release\(v\d|Merge |docs\(release\): release-checks placeholder|Daily conformance fixes|New service:)", re.I)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def commits(rev_range: str, first_parent: bool = False) -> list[str]:
    args = ["log", "--format=%H", "--no-merges"] + (["--first-parent"] if first_parent else []) + [rev_range]
    return [c for c in git(*args).split() if c]


def subject_and_files(sha: str) -> tuple[str, list[str]]:
    subj = git("log", "-1", "--format=%s", sha).strip()
    files = [f for f in git("show", "--name-only", "--format=", sha).split("\n") if f]
    return subj, files


def is_ancestor(sha: str, ref: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", sha, ref], capture_output=True).returncode == 0


def surface(files: list[str]) -> str:
    prod = [f for f in files if not f.startswith(("tests/", "docs/", ".github/"))
            and not f.endswith(("REPORT.md", "CHANGELOG.md", "README.md"))]
    nano = any(f.startswith("wasm/") and not f.startswith("wasm/ui-tests/") for f in prod)
    off = any(not f.startswith("wasm/") for f in prod)
    return "Nano + offline" if nano and off else "Nano" if nano else "offline" if off else ""


def clean(subj: str) -> str:
    s = re.sub(r"^conformance-agent:\s*", "", subj)
    s = re.sub(r"^[a-z]+(\+[a-z]+)*(\([^)]*\))?!?:\s*", "", s)
    s = re.sub(r"\s*\(#\d+\)$", "", s)
    return s[:1].upper() + s[1:] if s else s


def classify(subj: str, files: list[str]) -> tuple[str, str, str]:
    """→ (group, cloud, text). group: fix | platform | tests."""
    text = clean(subj)
    surf = surface(files)
    if PLATFORM_PREFIX.match(subj) and not subj.lower().startswith("conformance-agent"):
        return "platform", "", text
    if not surf:
        return "tests", "", text
    low = subj.lower()
    # The cloud named first is the one the change is about ("AWS Console Home … like
    # GCP and Azure" is AWS); the Nano tunnel and console-wide UI serve every cloud.
    if re.search(r"relay|tunnel|cursor|every clickable|all consoles", low):
        return "fix", "Shared", f"**[{surf}]** {text}"
    # Names two or more clouds explicitly ("on AWS, GCP and Azure") and isn't about
    # one cloud's page → it serves every cloud.
    lead = re.sub(r"^(nano|offline)\s+", "", text.lower())
    m = re.match(r"(aws|gcp|azure)\b", lead)
    if m:                                          # "GCP console KMS facade returned AWS ARNs" is GCP's bug
        return "fix", {"aws": "AWS", "gcp": "GCP", "azure": "Azure"}[m.group(1)], f"**[{surf}]** {text}"
    named = {c for c, w in (("AWS", r"\baws\b"), ("GCP", r"\bgcp\b"), ("Azure", r"\bazure\b")) if re.search(w, low)}
    if len(named) >= 2:
        return "fix", "Shared", f"**[{surf}]** {text}"
    hits = [(m.start(), c) for c, rx in CLOUD_RE for m in [re.search(rx, low)] if m]
    cloud = min(hits)[1] if hits else "Shared"
    return "fix", cloud, f"**[{surf}]** {text}"


def gather(prev: str, head: str, pr_head: str | None) -> list[tuple[str, str, str]]:
    seen, out = set(), []
    shas = commits(f"{prev}..{head}", first_parent=True)
    if pr_head:
        shas += [c for c in commits(f"{prev}..{pr_head}") if not is_ancestor(c, prev)]
    for sha in shas:
        subj, files = subject_and_files(sha)
        if SKIP.match(subj) or subj in seen:
            continue
        seen.add(subj)
        out.append(classify(subj, files))
    return out


def render(version: str, kind: str, items, highlights: str, new_services: str) -> str:
    fixes = [i for i in items if i[0] == "fix"]
    by_cloud = {c: [t for g, cc, t in fixes if cc == c] for c in ("AWS", "GCP", "Azure", "Shared")}
    platform = [t for g, _, t in items if g == "platform"]
    tests = [t for g, _, t in items if g == "tests"]
    nano = sum(1 for _, _, t in fixes if t.startswith("**[Nano"))
    offline = sum(1 for _, _, t in fixes if "offline]" in t.split("]")[0] + "]")
    date = dt.datetime.utcnow().strftime("%Y-%m-%d")
    counts = ", ".join(f"{'all clouds' if c == 'Shared' else c} {len(v)}" for c, v in by_cloud.items() if v)
    lines = [f"## [{version}] — {date}", "",
             f"{kind}. **{len(fixes)} product fixes** ({counts or 'none'}); {nano} reach Nano and {offline} reach the "
             f"offline appliance" + (f"; {len(tests)} test and harness improvements" if tests else "") + ".", ""]
    if not highlights:
        top = [t for _, _, t in fixes][:6]
        highlights = "\n".join(f"- {t}" for t in top)
    lines += ["### Highlights", "", highlights.strip(), ""]
    if new_services.strip():
        lines += ["### New services", "", new_services.strip(), ""]
    for c, v in by_cloud.items():
        if v:
            lines += [f"### Fixes — {c}" if c != "Shared" else "### Fixes — all clouds", ""] + [f"- {t}" for t in v] + [""]
    if platform:
        lines += ["<details><summary>Platform and release pipeline (" + str(len(platform)) + ")</summary>", ""] + \
                 [f"- {t}" for t in platform] + ["", "</details>", ""]
    if tests:
        lines += ["<details><summary>Test and harness improvements (" + str(len(tests)) + ")</summary>", ""] + \
                 [f"- {t}" for t in tests] + ["", "</details>", ""]
    lines += ["### How to upgrade", "",
              "- **Offline appliance:** `vyomi update` (Homebrew installs older than 3.0.24: run "
              "`brew trust vyomi-cloud/tap && brew upgrade vyomi-docker` once first). Docker: `docker pull vyomi/appliance:" + version + "`.",
              "- **Nano** ([vyomi.cloud](https://vyomi.cloud)): updates with this release; close all Nano tabs and reopen to load it.", ""]
    return "\n".join(lines)


def write_changelog(entry: str, version: str) -> None:
    txt = open("CHANGELOG.md", encoding="utf-8").read()
    # Replace an existing entry for this version (backfill), else insert above the first release.
    pat = re.compile(rf"^## \[{re.escape(version)}\].*?(?=^## \[|\Z)", re.S | re.M)
    if pat.search(txt):
        txt = pat.sub(entry.rstrip() + "\n\n", txt, count=1)
    else:
        i = txt.find("\n## ")
        txt = txt[: i + 1] + entry.rstrip() + "\n\n" + txt[i + 1:] if i >= 0 else entry + txt
    open("CHANGELOG.md", "w", encoding="utf-8").write(txt)


def write_readme(version: str, highlights: str, summary: str) -> None:
    txt = open("README.md", encoding="utf-8").read()
    date = dt.datetime.utcnow().strftime("%Y-%m-%d")
    block = "\n".join([
        "<!-- latest-release:start (generated by scripts/release_notes.py on every release) -->",
        f"## Latest release: v{version} ({date})", "",
        summary, "",
        highlights.strip(), "",
        f"[Full release notes](https://github.com/vyomi-cloud/appliance/releases/tag/v{version}) · "
        f"[CHANGELOG](CHANGELOG.md) · upgrade: `vyomi update` · Nano: reload [vyomi.cloud](https://vyomi.cloud)",
        "<!-- latest-release:end -->"])
    if "<!-- latest-release:start" in txt:
        txt = re.sub(r"<!-- latest-release:start.*?<!-- latest-release:end -->", lambda _: block, txt, flags=re.S)
    else:
        i = txt.find("\n## What's in v")
        txt = txt[: i + 1] + block + "\n\n" + txt[i + 1:] if i >= 0 else txt + "\n\n" + block + "\n"
    txt = re.sub(r"badge/version-[0-9.]+-green", f"badge/version-{version}-green", txt)
    txt = re.sub(r"^## What's in v[0-9.]+$", f"## What's in v{version}", txt, flags=re.M)
    txt = re.sub(r"(every capability shipped from v1\.0 through v)[0-9.]+", rf"\g<1>{version}", txt)
    first = next((l[2:].strip() for l in highlights.strip().splitlines() if l.startswith("- ")), "")
    hist = f"- **{version}** — {first}"
    m = re.search(r"(<details open><summary><b>3\.0\.x</b>[^\n]*\n\n)", txt)
    if m and f"- **{version}** —" not in txt:
        txt = txt[: m.end()] + hist + "\n" + txt[m.end():]
    open("README.md", "w", encoding="utf-8").write(txt)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--prev", required=True, help="previous release tag, e.g. v3.0.24")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--pr-head")
    ap.add_argument("--kind", default="Release")
    ap.add_argument("--highlights")
    ap.add_argument("--new-services")
    ap.add_argument("--out")
    ap.add_argument("--commits-out")
    ap.add_argument("--write-changelog", action="store_true")
    ap.add_argument("--write-readme", action="store_true")
    a = ap.parse_args()
    items = gather(a.prev, a.head, a.pr_head)
    if a.commits_out:
        open(a.commits_out, "w").write("\n".join(f"{g}\t{c}\t{t}" for g, c, t in items) + "\n")
    hl = open(a.highlights).read() if a.highlights else ""
    ns = open(a.new_services).read() if a.new_services else ""
    entry = render(a.version, a.kind, items, hl, ns)
    if a.out:
        open(a.out, "w").write(entry)
    if a.write_changelog:
        write_changelog(entry, a.version)
    if a.write_readme:
        summary = entry.split("\n")[2]
        hl_block = entry.split("### Highlights\n\n", 1)[1].split("\n\n###", 1)[0]
        write_readme(a.version, hl_block, summary)
    if not (a.out or a.write_changelog or a.write_readme):
        sys.stdout.write(entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
