#!/usr/bin/env python3
"""Mirror integrations/claude-plugins/ (the source of truth) into a checkout of the public marketplace repo
vyomi-cloud/claude-plugins, with a version guard.

Claude Code updates an installed plugin only when its version changes, so publishing changed content under a
version that is already published would reach nobody. This script refuses that, and refuses a version lower
than the published one. Unchanged content is a no-op.

  python3 scripts/sync_claude_plugins.py <marketplace-checkout>           # report only (exit 0 = ok to sync)
  python3 scripts/sync_claude_plugins.py <marketplace-checkout> --apply   # mirror the files (no git commands)
      [--tunnel-version X.Y.Z]   pin npx to vyomi-tunnel@X.Y.Z in the mirrored copy (the release passes its version)
      [--allow-unpublished]      mirror even if that pin is not on npm yet (dry runs only: nothing is pushed)

The plugin starts its MCP with `npx -y vyomi-tunnel@<version> mcp`, so the mirror must never name a version npm does
not serve yet: with --apply the script checks registry.npmjs.org for every pinned version first and refuses otherwise.
tunnel-release.yml runs this job after npm publish, so on a release the pin is the version it just published.

Prints `changed=true|false` and `version=<plugin versions>` lines (also appended to $GITHUB_OUTPUT when set).
Run by tunnel-release.yml after a final vyomi-tunnel release (plugin 4.1+ runs `vyomi-tunnel mcp`).
"""
import json
import os
import pathlib
import re
import shutil
import sys
import time
import urllib.error
import urllib.request

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


PIN_RE = re.compile(rb"vyomi-tunnel@(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)")


def mirrored(f, pin):
    """The bytes the mirror gets for SRC/f: plugin texts with the vyomi-tunnel pin set to `pin` (when given)."""
    data = (SRC / f).read_bytes()
    if pin and f.startswith("plugins/") and f.endswith((".json", ".md")):
        data = PIN_RE.sub(b"vyomi-tunnel@" + pin.encode(), data)
    return data


def on_npm(version, tries=10, wait=30, max_errors=3):
    """True when registry.npmjs.org serves vyomi-tunnel@version. A 404 is retried (a fresh publish can take a few
    minutes to show); any other failure is retried max_errors times, then counts as not published (fail closed)."""
    url = f"https://registry.npmjs.org/vyomi-tunnel/{version}"
    errors = 0
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                return json.load(r).get("version") == version
        except urllib.error.HTTPError as e:
            if e.code != 404:
                errors += 1
                print(f"  npm: HTTP {e.code} for {url}")
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            errors += 1
            print(f"  npm: {e} for {url}")
        if errors >= max_errors:
            break
        if i + 1 < tries:
            time.sleep(wait if errors == 0 else 5)
    return False


def files(root):
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts}


def main(argv):
    if len(argv) < 2 or argv[1].startswith("-"):
        sys.exit(__doc__)
    dst, apply, allow_unpublished = pathlib.Path(argv[1]), "--apply" in argv[2:], "--allow-unpublished" in argv[2:]
    pin = argv[argv.index("--tunnel-version") + 1] if "--tunnel-version" in argv[2:] else None
    if pin is not None and not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", pin):
        sys.exit(f"sync_claude_plugins: --tunnel-version needs an exact version, got {pin!r}")
    src_files, dst_files = files(SRC), files(dst)
    changed = sorted(f for f in src_files & dst_files if mirrored(f, pin) != (dst / f).read_bytes())
    added, removed = sorted(src_files - dst_files), sorted(dst_files - src_files)
    new, old = versions(SRC), versions(dst)
    if not new:
        sys.exit("sync_claude_plugins: integrations/claude-plugins has no .claude-plugin/marketplace.json")
    # Every agent's manifest (Agent Plugins, Claude Code, Codex, Cursor) must agree before anything is published.
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_agent_plugins", pathlib.Path(__file__).with_name("check_agent_plugins.py"))
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)
    # check() returns (errors, notes): the notes are submission reminders (e.g. a developerName placeholder), not drift.
    drift, notes = cap.check(SRC)
    for n in notes:
        print(f"sync_claude_plugins: note: {n}")
    if drift:
        sys.exit("sync_claude_plugins: manifests disagree:\n  " + "\n  ".join(drift))

    def emit(changed_flag):
        lines = [f"changed={'true' if changed_flag else 'false'}", "version=" + " ".join(f"{k}@{v}" for k, v in sorted(new.items()))]
        print("\n".join(lines))
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
                fh.write("\n".join(lines) + "\n")

    # Never mirror a pin npm does not serve: the plugin would fail to start its MCP for everyone who installs it.
    pins = sorted({m.decode() for f in src_files if f.startswith("plugins/") for m in PIN_RE.findall(mirrored(f, pin))})
    for v in pins:
        if pin and v != pin:
            sys.exit(f"sync_claude_plugins: mirrored files still pin vyomi-tunnel@{v}, expected {pin}")
    if pin and any(PIN_RE.search((SRC / f).read_bytes()) and mirrored(f, pin) != (SRC / f).read_bytes() for f in src_files):
        print(f"  note: the mirror's vyomi-tunnel pin is rewritten to {pin} (the source pins another version)")
    unpublished = [] if (allow_unpublished or not apply) else [v for v in pins if not on_npm(v)]
    if unpublished:
        sys.exit("sync_claude_plugins: vyomi-tunnel " + ", ".join(unpublished) + " is not on npm; publish it first "
                 "(tunnel-release.yml does, before this step), or pass --allow-unpublished on a dry run")
    if pins:
        print("vyomi-tunnel pin: " + ", ".join(pins) + ("" if apply and not allow_unpublished else "  (npm not checked: report only / dry run)"))

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
            if pin:
                (dst / f).write_bytes(mirrored(f, pin))
        for d in sorted((p for p in dst.rglob("*") if p.is_dir() and ".git" not in p.relative_to(dst).parts), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()
        print(f"mirrored into {dst}")
    emit(True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
