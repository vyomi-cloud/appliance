#!/usr/bin/env python3
"""vyomi-tunnel release sync: is the version in packaging/tunnel what npm and the Homebrew tap serve?

Why: Nano's VM SSH details (Connect tab) need the tunnel to carry ``vm-tcp`` (>= 1.1.0). The source
was bumped to 1.1.0 but never published, so users on brew/npm kept 1.0.0 and the console told them to
upgrade to a version that did not exist. Release checks fail on that drift; release.yml publishes it.

  python3 scripts/tunnel_sync.py status            # human lines + exit 1 on any problem
  python3 scripts/tunnel_sync.py status --json     # machine-readable (used by the workflows)
  python3 scripts/tunnel_sync.py sha <version>     # settled sha256 of the registry tarball (3 equal fetches)

Env: TAP_FORMULA_URL overrides the tap formula location (default: raw.githubusercontent.com main).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging" / "tunnel" / "package.json"
BIN = ROOT / "packaging" / "tunnel" / "bin" / "vyomi-tunnel.mjs"
TAP = "https://raw.githubusercontent.com/vyomi-cloud/homebrew-tap/main/Formula/vyomi-tunnel.rb"
REG = "https://registry.npmjs.org/vyomi-tunnel"


def get(url: str, timeout: int = 30) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"user-agent": "vyomi-release"}), timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def settled_sha(version: str, tries: int = 6) -> str | None:
    """sha256 of the registry tarball, only once 3 consecutive fetches agree.
    (A fetch right after `npm publish` can return a different/partial body — a wrong value broke `brew reinstall`.)"""
    url = f"{REG}/-/vyomi-tunnel-{version}.tgz"
    seen: list[str] = []
    for _ in range(tries * 3):
        b = get(url)
        seen = (seen + [hashlib.sha256(b).hexdigest()])[-3:] if b else []
        if len(seen) == 3 and len(set(seen)) == 1:
            return seen[0]
        time.sleep(5)
    return None


def status() -> dict:
    pkg = json.loads(PKG.read_text())["version"]
    m = re.search(r'const VERSION = "([^"]+)"', BIN.read_text())
    binv = m.group(1) if m else None
    problems: list[str] = []
    if binv != pkg:
        problems.append(f"bin/vyomi-tunnel.mjs VERSION ({binv}) != package.json ({pkg})")
    meta = get(f"{REG}/{pkg}")
    published = meta is not None
    if not published:
        problems.append(f"vyomi-tunnel@{pkg} is not on npm — publish it (release.yml does this when NPM_TOKEN is set)")
    tap_txt = (get(__import__("os").environ.get("TAP_FORMULA_URL", TAP)) or b"").decode()
    tv = re.search(r'vyomi-tunnel-([0-9][^"]*)\.tgz"', tap_txt)
    ts = re.search(r'sha256 "([0-9a-f]{64})"', tap_txt)
    tap_ver, tap_sha = (tv.group(1) if tv else None), (ts.group(1) if ts else None)
    if tap_ver != pkg:
        problems.append(f"Homebrew tap formula is at {tap_ver}, package is {pkg} — update vyomi-cloud/homebrew-tap")
    sha = settled_sha(pkg, tries=2) if published else None
    if published and tap_ver == pkg and sha and tap_sha != sha:
        problems.append(f"tap sha256 {tap_sha} != registry tarball {sha}")
    return {"version": pkg, "npm_published": published, "tap_version": tap_ver, "tap_sha": tap_sha,
            "tarball_sha": sha, "ok": not problems, "problems": problems}


def main() -> int:
    a = sys.argv[1:] or ["status"]
    if a[0] == "sha":
        s = settled_sha(a[1])
        print(s or "")
        return 0 if s else 1
    st = status()
    if "--json" in a:
        print(json.dumps(st))
    else:
        print(f"vyomi-tunnel {st['version']}: npm {'✅' if st['npm_published'] else '❌ missing'} · tap {st['tap_version']} "
              f"{'✅' if st['tap_version'] == st['version'] else '❌'}")
        for p in st["problems"]:
            print("  ✗", p)
    return 0 if st["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
