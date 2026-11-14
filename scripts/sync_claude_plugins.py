#!/usr/bin/env python3
"""Mirror integrations/claude-plugins/ (the source of truth) into a checkout of the public marketplace repo
vyomi-cloud/claude-plugins, with a version guard.

Claude Code updates an installed plugin only when its version changes, so publishing changed content under a
version that is already published would reach nobody. This script refuses that, and refuses a version lower
than the published one. Unchanged content is a no-op.

  python3 scripts/sync_claude_plugins.py <marketplace-checkout>           # report only (exit 0 = ok to sync)
  python3 scripts/sync_claude_plugins.py <marketplace-checkout> --apply   # mirror the files (no git commands)

Prints `changed=true|false` and `version=<plugin versions>` lines (also appended to $GITHUB_OUTPUT when set).
Run by tunnel-release.yml after a final vyomi-tunnel release (plugin 4.1+ runs `vyomi-tunnel mcp`).
"""
import filecmp
import json
import os
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "integrations" / "claude-plugins"


def vtuple(v):
    try:
        return tuple(int(x) for x in v.split("-")[0].split("."))
    except ValueError:
        sys.exit(f"sync_claude_plugins: not a version: {v!r}")


def versions(root):
    """{plugin name: version} from marketplace.json, checked against each plugin.json (empty if no marketplace)."""
    mp = root / ".claude-plugin" / "marketplace.json"
    if not mp.exists():
        return {}
    m = json.loads(mp.read_text())
    out = {}
    for p in m.get("plugins", []):
        pj = root / p["source"] / ".claude-plugin" / "plugin.json"
        pv = json.loads(pj.read_text()).get("version") if pj.exists() else None
        if pv and pv != p.get("version"):
            sys.exit(f"sync_claude_plugins: {root}: {p['name']} is {p.get('version')} in marketplace.json but {pv} in plugin.json")
        out[p["name"]] = p.get("version") or pv
    return out


def files(root):
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts}


def main(argv):
    if len(argv) < 2 or argv[1].startswith("-"):
        sys.exit(__doc__)
    dst, apply = pathlib.Path(argv[1]), "--apply" in argv[2:]
    src_files, dst_files = files(SRC), files(dst)
    changed = sorted(f for f in src_files & dst_files if not filecmp.cmp(SRC / f, dst / f, shallow=False))
    added, removed = sorted(src_files - dst_files), sorted(dst_files - src_files)
    new, old = versions(SRC), versions(dst)
    if not new:
        sys.exit("sync_claude_plugins: integrations/claude-plugins has no .claude-plugin/marketplace.json")

    def emit(changed_flag):
        lines = [f"changed={'true' if changed_flag else 'false'}", "version=" + " ".join(f"{k}@{v}" for k, v in sorted(new.items()))]
        print("\n".join(lines))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
                fh.write("\n".join(lines) + "\n")

    if not (changed or added or removed):
        print("marketplace already matches integrations/claude-plugins")
        emit(False)
        return 0
    for name, v in sorted(new.items()):
        if name in old and vtuple(v) < vtuple(old[name]):
            sys.exit(f"sync_claude_plugins: {name} {v} is lower than the published {old[name]}")
    stale = [n for n in new if n in old and new[n] == old[n] and any(f.startswith(f"plugins/{n}/") for f in changed + added + removed)]
    if stale:
        sys.exit("sync_claude_plugins: content changed but the version did not ("
                 + ", ".join(f"{n} {new[n]}" for n in stale)
                 + "): installed copies would never update. Bump the version in marketplace.json and plugin.json.")
    for label, fs in (("changed", changed), ("added", added), ("removed", removed)):
        for f in fs:
            print(f"  {label:8s} {f}")
    print("versions: " + ", ".join(f"{n} {old.get(n, '(new)')} -> {v}" for n, v in sorted(new.items())))
    if apply:
        for f in removed:
            (dst / f).unlink()
        for f in changed + added:
            (dst / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SRC / f, dst / f)
        for d in sorted((p for p in dst.rglob("*") if p.is_dir() and ".git" not in p.relative_to(dst).parts), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()
        print(f"mirrored into {dst}")
    emit(True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
