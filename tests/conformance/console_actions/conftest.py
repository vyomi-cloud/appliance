"""Pytest fixtures for the console-actions conformance suite.

Configurable via env vars (so CI and local runs share the same harness):
  VYOMI_BASE_URL — defaults to http://127.0.0.1:9000
  VYOMI_TIER     — defaults to "developer" (so tier-gated services unlock)
  VYOMI_ACK_PUBLIC — defaults to "1" to bypass first-visit pricing redirect
"""
from __future__ import annotations
import os
import time
from typing import Any
import pytest


BASE_URL = os.environ.get("VYOMI_BASE_URL", "http://127.0.0.1:9000").rstrip("/")
DEFAULT_TIER = os.environ.get("VYOMI_TIER", "developer").lower()


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def http_session():
    """Reuse a single requests session across the whole suite. The
    simulator's tier gate cookie + headers persist, which is what real
    users see."""
    import requests
    s = requests.Session()
    # Suppress first-visit /pricing redirect so /clouds and /api/* paths
    # answer cleanly even on a fresh appliance.
    s.cookies.set("cloudlearn_tier_acknowledged", "1")
    return s


@pytest.fixture(scope="session", autouse=True)
def wait_for_appliance(http_session, base_url):
    """Block at session start until the appliance answers /healthz, then
    surface the active tier. Tests that hit a tier-locked service will
    legitimately get 403; the report classifies those distinctly from
    real bugs."""
    deadline = time.time() + 60
    last_err = None
    while time.time() < deadline:
        try:
            r = http_session.get(f"{base_url}/healthz", timeout=3)
            if r.status_code == 200:
                break
        except Exception as e:
            last_err = e
        time.sleep(1.5)
    else:
        pytest.fail(f"Appliance never came up at {base_url}: {last_err}")
    # Surface live tier so the harness summary makes sense
    try:
        r = http_session.get(f"{base_url}/api/runtime/tier", timeout=5)
        if r.status_code == 200:
            tier = (r.json() or {}).get("active_tier", "unknown")
            print(f"\n[conformance] appliance tier: {tier}\n")
    except Exception:
        pass


# Services that only unlock on the named tier. A 403 with
# code='tier_*' on these is a CORRECT response, not a failure. Surface
# as "skipped (tier-gated)" in the report so 100% remains achievable
# on whatever tier the run uses.
_TIER_GATED = {
    # AWS — Free tier locks NoSQL + eventing
    "free": {"aws": {"dynamodb", "eventbridge"}},
    # Student is single-cloud (their primary_cloud only)
    "student": {
        "azure": "ALL", "gcp": "ALL",
        "aws":   {"dynamodb", "eventbridge"},
    },
}


def is_tier_gated(provider: str, service: str, tier: str) -> bool:
    rules = _TIER_GATED.get(tier.lower(), {})
    gated = rules.get(provider.lower())
    if gated is None:
        return False
    if gated == "ALL":
        return True
    return service.lower() in gated


# ── Test-run results (collected for the markdown report generator) ──────────

# Populated by the test bodies; consumed by tests/conformance/console_actions/
# generators/markdown_report.py via a pytest_terminal_summary hook.
TEST_RESULTS: list[dict[str, Any]] = []


def record_result(spec, status_code: int, ok: bool, reason: str = "") -> None:
    TEST_RESULTS.append({
        "provider": spec.provider, "service": spec.service,
        "action": spec.action, "method": spec.method, "path": spec.path,
        "status_code": status_code, "ok": ok, "reason": reason,
    })


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Write the markdown report + per-provider pass-rate at the end."""
    if not TEST_RESULTS:
        return
    from .generators.markdown_report import write_report
    report_path = os.environ.get(
        "VYOMI_CONFORMANCE_REPORT", "tests/conformance/console_actions/REPORT.md")
    summary = write_report(TEST_RESULTS, report_path)
    tr = terminalreporter
    tr.write_sep("=", "console conformance summary")
    for prov, stats in summary.items():
        rate = (stats["ok"] / stats["total"] * 100) if stats["total"] else 0
        flag = "✓" if rate == 100 else ("⚠" if rate >= 80 else "✗")
        tr.write_line(f"  {flag} {prov:<6} {stats['ok']}/{stats['total']}  ({rate:.1f}%)")
    tr.write_line(f"  Full report → {report_path}")
