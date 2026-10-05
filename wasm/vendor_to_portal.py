#!/usr/bin/env python3
"""Vendor the served Nano bundle from canonical appliance/wasm/ into portal/app/nano/.

WHY: appliance/wasm/ is the SINGLE SOURCE OF TRUTH for the Nano bundle — it sits
next to the conformance cores it is vendored from (see build_cores.py: core/ ->
wasm/core/). The portal serves a COPY at portal/app/nano/ (DigitalOcean builds the
portal repo, which has no access to the appliance repo, so the copy must be
committed there). This script keeps that copy in lock-step with the source so the
two never silently diverge (the "one core, never a fork" invariant).

USAGE
  python3 wasm/vendor_to_portal.py                 # --check (default): report drift, exit 1 if any
  python3 wasm/vendor_to_portal.py --apply         # copy appliance/wasm -> portal/app/nano
  python3 wasm/vendor_to_portal.py --portal <dir>  # override portal/app/nano location

Run --check in CI / a pre-commit hook to FAIL on drift.

SCOPE: only the SERVED bundle is vendored. Dev tooling (build_*.py, make_pages.py,
test_conformance.py, e2e.mjs, this script), the experimental console-next/,
screenshots (*.png) and READMEs stay appliance-only and are NEVER copied. Files
that exist only in the portal (e.g. brand assets) are left untouched.

DIRECTION IS ONE-WAY (appliance -> portal). Before the first --apply, make sure
appliance/wasm holds the latest of every bundle file (back-port any portal-ahead
edits first); --check lists exactly what differs.
"""
from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))                 # .../appliance/wasm
APPLIANCE_ROOT = os.path.dirname(HERE)                            # .../appliance
SIM_ROOT = os.path.dirname(APPLIANCE_ROOT)                        # .../simulator
DEFAULT_PORTAL = os.path.join(SIM_ROOT, "portal", "app", "nano")  # .../portal/app/nano

# Directories (relative to wasm/) that are appliance-only and never vendored.
EXCLUDE_DIRS = {"ui-tests", "console-next", "__pycache__"}
# Exact files (relative to wasm/) that are appliance-only build/dev tooling.
EXCLUDE_FILES = {
    "console-next.html", "build_cores.py", "build_fixtures.py", "make_pages.py",
    "test_conformance.py", "e2e.mjs", "README.md", "NANO-ARCHITECTURE.md",
    "vendor_to_portal.py",
}
# Suffixes never vendored (screenshots, compiled python).
EXCLUDE_SUFFIXES = (".png", ".pyc")


def in_bundle(rel: str) -> bool:
    parts = rel.split(os.sep)
    if parts[0] in EXCLUDE_DIRS:
        return False
    if rel in EXCLUDE_FILES:
        return False
    if rel.endswith(EXCLUDE_SUFFIXES):
        return False
    return True


def bundle_files(src: str) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), src)
            if in_bundle(rel):
                out.append(rel)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Vendor Nano bundle appliance/wasm -> portal/app/nano")
    ap.add_argument("--apply", action="store_true", help="copy drifting/missing files (default is check-only)")
    ap.add_argument("--portal", default=DEFAULT_PORTAL, help="portal/app/nano directory")
    args = ap.parse_args()

    src, dst = HERE, os.path.abspath(args.portal)
    if not os.path.isdir(dst):
        print(f"ERROR: portal dir not found: {dst}", file=sys.stderr)
        return 2

    files = bundle_files(src)
    in_sync, drift, missing = [], [], []
    for rel in files:
        s, d = os.path.join(src, rel), os.path.join(dst, rel)
        if not os.path.exists(d):
            missing.append(rel)
        elif filecmp.cmp(s, d, shallow=False):
            in_sync.append(rel)
        else:
            drift.append(rel)

    # portal files that aren't part of the appliance bundle (informational only)
    portal_only = []
    for dirpath, dirnames, filenames in os.walk(dst):
        dirnames[:] = [x for x in dirnames if x not in EXCLUDE_DIRS]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), dst)
            if in_bundle(rel) and not os.path.exists(os.path.join(src, rel)):
                portal_only.append(rel)

    print(f"Nano bundle vendoring  (appliance/wasm -> {dst})")
    print(f"  in sync : {len(in_sync)}")
    print(f"  drift   : {len(drift)}")
    for r in drift:
        print(f"    ~ {r}")
    print(f"  missing in portal : {len(missing)}")
    for r in missing:
        print(f"    + {r}")
    if portal_only:
        print(f"  portal-only (left untouched) : {len(portal_only)}")
        for r in sorted(portal_only):
            print(f"    · {r}")

    if args.apply:
        changed = 0
        for rel in drift + missing:
            s, d = os.path.join(src, rel), os.path.join(dst, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            changed += 1
        print(f"APPLIED: copied {changed} file(s) appliance/wasm -> portal/app/nano")
        return 0

    if drift or missing:
        print("\nDRIFT DETECTED. Re-run with --apply to vendor "
              "(after confirming appliance/wasm has the intended latest of each). "
              "check-only mode made no changes.")
        return 1
    print("\nIN SYNC. Nothing to do.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
