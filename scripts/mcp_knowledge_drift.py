#!/usr/bin/env python3
"""Is a vyomi-tunnel release due because capabilities changed?

The vyomi MCP's capability knowledge (core/capabilities -> cmd/vyomi/mcp_caps.json.gz, via scripts/gen_mcp_matrix.py)
is baked into the vyomi-mcp binaries bundled in vyomi-tunnel. This regenerates the knowledge for the current tree and
compares it, capability by capability, with the knowledge at the tag of npm's `latest` vyomi-tunnel.

  python3 scripts/mcp_knowledge_drift.py [--latest X.Y.Z]     # markdown report on stdout; always exits 0 unless broken

Run by release.yml after each appliance release (into the run summary). Informational only.
"""
import gzip
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAPS = "cmd/vyomi/mcp_caps.json.gz"


def sh(*a, **k):
    return subprocess.run(a, cwd=ROOT, capture_output=True, text=k.pop("text", True), **k)


def latest_tunnel(argv):
    if "--latest" in argv:
        return argv[argv.index("--latest") + 1]
    r = sh("npm", "view", "vyomi-tunnel", "version")
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    tags = [t[len("tunnel-v"):] for t in sh("git", "tag", "-l", "tunnel-v*").stdout.split() if re.fullmatch(r"tunnel-v\d+\.\d+\.\d+", t)]
    return max(tags, key=lambda v: tuple(map(int, v.split(".")))) if tags else None


def index(caps):
    return {c["id"]: c for cloud in caps["clouds"].values() for svc in cloud.values() for c in svc.get("capabilities", [])}


def main(argv):
    ver = latest_tunnel(argv)
    print("## MCP knowledge vs vyomi-tunnel")
    if not ver:
        print("- no vyomi-tunnel release found (npm or tunnel-v* tags); nothing to compare")
        return 0
    if tuple(map(int, ver.split("-")[0].split("."))) < (1, 3, 0):
        print(f"- npm `latest` vyomi-tunnel is {ver}, which has no bundled MCP: release vyomi-tunnel 1.3.0+ to ship it")
        return 0
    tag = f"tunnel-v{ver}"
    old = sh("git", "show", f"{tag}:{CAPS}", text=False)
    if old.returncode != 0:
        print(f"- cannot read `{CAPS}` at tag `{tag}` (fetch tags: `git fetch --tags`); nothing compared")
        return 0
    gen = sh(sys.executable, "scripts/gen_mcp_matrix.py")
    if gen.returncode != 0:
        print(f"- the generator failed, nothing compared:\n```\n{(gen.stderr or gen.stdout)[-1500:]}\n```")
        return 0
    a = index(json.loads(gzip.decompress(old.stdout)))
    b = index(json.loads(gzip.decompress((ROOT / CAPS).read_bytes())))
    added = sorted(set(b) - set(a))
    removed = sorted(set(a) - set(b))
    level = sorted(i for i in set(a) & set(b) if a[i].get("level") != b[i].get("level"))
    other = sorted(i for i in set(a) & set(b) if i not in level and a[i] != b[i])
    if not (added or removed or level or other):
        print(f"- up to date: the capabilities in this tree match vyomi-tunnel {ver} (`{tag}`)")
        return 0
    print(f"- **a vyomi-tunnel release is due**: agents using vyomi-tunnel {ver} answer from older capability data")
    print(f"- since `{tag}`: {len(added)} added, {len(removed)} removed, {len(level)} level changes, {len(other)} other edits"
          " (limitations, titles, tests)")
    for label, ids, show in (("Added", added, lambda i: b[i]), ("Level changed", level, None), ("Removed", removed, lambda i: a[i])):
        if not ids:
            continue
        print(f"\n**{label}**\n")
        for i in ids[:40]:
            if show:
                c = show(i)
                print(f"- `{i}` {c.get('title', '')} (nano {c['level'].get('nano')}, offline {c['level'].get('offline')})")
            else:
                print(f"- `{i}`: nano {a[i]['level'].get('nano')} -> {b[i]['level'].get('nano')},"
                      f" offline {a[i]['level'].get('offline')} -> {b[i]['level'].get('offline')}")
        if len(ids) > 40:
            print(f"- ... and {len(ids) - 40} more")
    print("\nTo ship it: bump `packaging/tunnel/package.json` (and the bin version strings) on a branch, then tag"
          " `tunnel-vX.Y.Z` (tunnel-release.yml gates and publishes it).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
