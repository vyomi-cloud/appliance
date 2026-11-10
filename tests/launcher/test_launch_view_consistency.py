#!/usr/bin/env python3
"""The three launchers show the same launch view (non-negotiable: every install
path gets the same fixes and the same experience):

  packaging/docker/vyomi   Free/Lite/Pro on macOS/Linux (Homebrew, deb, rpm)
  scripts/cloud-learn      Max tier (Multipass)
  cmd/vyomi                Windows (MSI), Docker and Multipass

Fails if the dot-matrix wordmark, the tagline, the backends line, the Ready line
or the off-switches drift apart. Run: python3 tests/launcher/test_launch_view_consistency.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
LAUNCHERS = {
    "docker": ROOT / "packaging/docker/vyomi",
    "max": ROOT / "scripts/cloud-learn",
    "windows": ROOT / "cmd/vyomi/banner.go",
}
MUST_CONTAIN = [
    "local AWS · GCP · Azure — no cloud bill",                      # tagline
    "ready (S3 · KMS · SQL · NoSQL · queues · Pub/Sub · Blob)",     # backends line
    "SDK/CLI: point --endpoint-url at",                              # Ready line
    "Pro tier: launch an EC2 instance in the console, then ssh ubuntu@<ip>.",
    "/api/runtime/readiness",                                        # live N/N readiness
    "VYOMI_NO_BANNER", "NO_COLOR",                                   # off-switches
    "LAUNCH-VIEW-MATRIX", "LAUNCH-VIEW-READY",
]


def matrix(text: str) -> list[str]:
    i = text.index("LAUNCH-VIEW-MATRIX")
    return re.findall(r'"([01]{5} [01]{5} [01]{5} [01]{5} [01]{3})"', text[i:i + 1200])[:7]


def main() -> int:
    fails, rows = [], {}
    for name, path in LAUNCHERS.items():
        text = path.read_text(encoding="utf-8")
        for needle in MUST_CONTAIN:
            if needle not in text:
                fails.append(f"{name}: missing {needle!r} ({path.relative_to(ROOT)})")
        if "LAUNCH-VIEW-MATRIX" in text:
            rows[name] = matrix(text)
            if len(rows[name]) != 7:
                fails.append(f"{name}: dot matrix has {len(rows[name])} rows, expected 7")
        if not re.search(r"Ready\.", text):
            fails.append(f"{name}: no 'Ready.' line")
    ref = rows.get("docker")
    for name, r in rows.items():
        if ref and r != ref:
            fails.append(f"{name}: dot matrix differs from packaging/docker/vyomi")
    for f in fails:
        print("[FAIL]", f)
    if not fails:
        print(f"[PASS] launch view identical in {len(LAUNCHERS)} launchers: " + ", ".join(LAUNCHERS))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
