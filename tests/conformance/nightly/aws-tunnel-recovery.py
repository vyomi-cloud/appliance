#!/usr/bin/env python3
"""Check 6 for AWS: tunnel conformance + auto-recovery (uses lib/tunnel_recovery.run_recovery).

Run by the nightly workflow's Codespace leg (needs NIGHTLY_CODESPACES_PAT and a running AWS-pinned Codespace
behind the tunnel). Without that it prints `NOT RUN: <why>` and exits 0 with NO PASS line, so it can never score green.

Env:
  VYOMI_BASE_URL                  tunnel address the client uses (default http://127.0.0.1:9000)
  NIGHTLY_TUNNEL_FAULTS=1         explicit opt-in: the faults below break the link, never run them on a dev laptop's live tunnel
  NIGHTLY_FAULT_KILL_RELAY        shell command that kills the local relay
  NIGHTLY_FAULT_DROP_SSH          shell command that drops the SSH session to the Codespace
  NIGHTLY_FAULT_RESTART_APPLIANCE shell command that restarts the appliance inside the Codespace
  NIGHTLY_RECOVERY_DEADLINE       seconds to wait for each recovery (default 120)
Each fault command is optional; only the ones set are exercised. At least one is required for a real run.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
from tests.conformance.nightly.lib.tunnel_recovery import run_recovery  # noqa: E402

FAULT_ENV = {
    "kill the relay": "NIGHTLY_FAULT_KILL_RELAY",
    "drop the SSH session": "NIGHTLY_FAULT_DROP_SSH",
    "restart the appliance in the Codespace": "NIGHTLY_FAULT_RESTART_APPLIANCE",
}


def base_url() -> str:
    return os.environ.get("VYOMI_BASE_URL", "http://127.0.0.1:9000").rstrip("/")


def not_run_reason(env=os.environ) -> str:
    if env.get("NIGHTLY_TUNNEL_FAULTS") != "1":
        return "NIGHTLY_TUNNEL_FAULTS=1 not set (faults are opt-in)"
    if not any(env.get(v) for v in FAULT_ENV.values()):
        return "no NIGHTLY_FAULT_* command configured"
    return ""


def build_faults(env=os.environ) -> dict:
    def sh(cmd: str):
        def run() -> None:
            subprocess.run(cmd, shell=True, check=True, timeout=120)
        return run
    return {label: sh(env[v]) for label, v in FAULT_ENV.items() if env.get(v)}


def link_ok() -> bool:
    try:
        with urllib.request.urlopen(base_url() + "/healthz", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _s3():
    import boto3
    return boto3.client("s3", endpoint_url=base_url(), region_name="us-east-1",
                        aws_access_key_id="test", aws_secret_access_key="test")


def write_marker() -> str:
    name = f"nightly-tunnel-{int(time.time())}"
    _s3().create_bucket(Bucket=name)          # a real resource created THROUGH the tunnel
    return name


def marker_ok(name: str) -> bool:
    try:
        return name in [b["Name"] for b in _s3().list_buckets().get("Buckets", [])]
    except Exception:
        return False


def main() -> int:
    why = not_run_reason()
    if why:
        print(f"NOT RUN: aws tunnel recovery ({why})")
        return 0
    failures = run_recovery(link_ok, write_marker, marker_ok, build_faults(),
                            deadline=float(os.environ.get("NIGHTLY_RECOVERY_DEADLINE", "120")))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
