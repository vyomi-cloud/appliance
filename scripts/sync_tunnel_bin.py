#!/usr/bin/env python3
"""Keep the tunnel's two copies of each module identical: wasm/relay/<name>.mjs (what the relay tests import) and
packaging/tunnel/bin/<name>.mjs (what npm and Homebrew ship). Version stamps may differ; nothing else may.

  python3 scripts/sync_tunnel_bin.py                    # check (CI): exit 1 and list the files that differ
  python3 scripts/sync_tunnel_bin.py --to-package NAME  # copy wasm/relay/NAME over the packaged copy (version stamps kept)
  python3 scripts/sync_tunnel_bin.py --to-relay NAME    # copy the packaged copy over wasm/relay/NAME

The one file only in the package is vyomi-tunnel.mjs (hand-derived from wasm/relay/local-relay.mjs: no hosted-relay hubs).
Any other file that exists on one side only is an error.
"""
import difflib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RELAY = ROOT / "wasm" / "relay"
PKG = ROOT / "packaging" / "tunnel" / "bin"
PACKAGE_ONLY = {"vyomi-tunnel.mjs"}
VERSION = re.compile(r"\b\d+\.\d+\.\d+(?:-rc\.\d+)?\b")


def norm(text):
    return VERSION.sub("X.Y.Z", text)


def stamps(text):
    """The version strings a release stamps (see tunnel-release.yml), in order, so a copy keeps the target's."""
    return re.findall(r'(?:const VERSION = "|vyomi-tunnel |version = "|VYOMI_TUNNEL_VERSION_NUM \|\| ")(\d+\.\d+\.\d+(?:-rc\.\d+)?)', text)


def copy(src, dst):
    s, keep = src.read_text(), stamps(dst.read_text()) if dst.exists() else []
    if keep and len(set(keep)) == 1:   # one version throughout the target: stamp it into the copied text
        s = re.sub(r'(const VERSION = "|vyomi-tunnel |version = "|VYOMI_TUNNEL_VERSION_NUM \|\| ")\d+\.\d+\.\d+(?:-rc\.\d+)?', lambda m: m.group(1) + keep[0], s)
    dst.write_text(s)
    print(f"copied {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")


def main(argv):
    if len(argv) == 3 and argv[1] in ("--to-package", "--to-relay"):
        name = argv[2] if argv[2].endswith(".mjs") else argv[2] + ".mjs"
        src, dst = (RELAY / name, PKG / name) if argv[1] == "--to-package" else (PKG / name, RELAY / name)
        if not src.exists():
            sys.exit(f"no {src.relative_to(ROOT)}")
        copy(src, dst)
        return 0
    if len(argv) > 1:
        sys.exit(__doc__)
    bad = []
    for p in sorted(PKG.glob("*.mjs")):
        r = RELAY / p.name
        if p.name in PACKAGE_ONLY:
            continue
        if not r.exists():
            bad.append(f"{p.name}: only in packaging/tunnel/bin (add it to wasm/relay, or to PACKAGE_ONLY with the reason)")
        elif norm(r.read_text()) != norm(p.read_text()):
            n = sum(1 for l in difflib.unified_diff(norm(r.read_text()).splitlines(), norm(p.read_text()).splitlines(), n=0)
                    if l[:1] in "+-" and not l.startswith(("+++", "---")))
            bad.append(f"{p.name}: the two copies differ beyond version stamps (~{n} lines). Make the change in both, or run "
                       f"`python3 scripts/sync_tunnel_bin.py --to-package {p.stem}` / `--to-relay {p.stem}`")
    if bad:
        print("tunnel copies out of sync:\n  " + "\n  ".join(bad))
        return 1
    print("tunnel copies in sync (wasm/relay vs packaging/tunnel/bin, version stamps aside)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
