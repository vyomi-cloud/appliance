"""Fixtures for the REAL Playwright SPA conformance suite.

Reuses the playwright lifecycle + tier-promotion patterns from the older
HTTP-based suite in tests/conformance/ui/conftest.py, but doesn't import
from it (deliberate — these tests should still pass when the older suite
is in flux).
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Iterator

import pytest
import requests
from playwright.sync_api import (
    Browser,
    Page,
    Playwright,
    sync_playwright,
)

BASE_URL = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
HEADLESS = os.environ.get("PWDEBUG", "") != "1"
SLOW_MO_MS = int(os.environ.get("VYOMI_UI_SLOWMO_MS", "0"))


@pytest.fixture(scope="session", autouse=True)
def _disk_cleanup_after_session():
    """Nuke every LXD container the test session created + docker prune
    on session exit. v2.0.4: without this, each 35-service run leaks
    10-15 GB into LXD container disks. By session end the appliance VM's
    29 GB disk is at 99%, which itself causes timeouts in the LAST few
    tests. Per-test cleanup would be cleaner but requires custom delete
    logic per service; session-level bulk nuke is the pragmatic fix.

    Runs BEFORE the next session-scope fixture so disk is reclaimed
    before pytest reports its summary.
    """
    yield
    try:
        subprocess.run(
            ["multipass", "exec", "cloudlearn-appliance", "--",
             "sudo", "bash", "-lc",
             "for c in $(sudo lxc list --format csv -c n); do "
             "sudo lxc stop \"$c\" --force 2>/dev/null; "
             "sudo lxc delete \"$c\" --force 2>/dev/null; done; "
             "docker builder prune -af >/dev/null 2>&1; "
             "docker volume prune -f >/dev/null 2>&1; "
             "df -h / | tail -1"
            ],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except Exception:
        pass  # best-effort cleanup; never fail the suite on this


@pytest.fixture(scope="session", autouse=True)
def _appliance_healthy_and_max_tier():
    """Block at session start until the appliance is up + on Max tier."""
    deadline = time.time() + 30
    last_err = None
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/healthz", timeout=3)
            if r.status_code == 200:
                break
        except Exception as e:
            last_err = e
        time.sleep(1.0)
    else:
        pytest.skip(
            f"Appliance not reachable at {BASE_URL} ({last_err}); "
            "run `vyomi up` first"
        )

    try:
        cur = requests.get(f"{BASE_URL}/api/runtime/tier", timeout=5)
        active = (cur.json() or {}).get("active_tier", "") if cur.status_code == 200 else ""
        if active.lower() != "max":
            requests.post(
                f"{BASE_URL}/api/license/signup",
                json={
                    "tier": "max",
                    "user": "ui-real-conformance",
                    "email": "ui-real@vyomi.cloud",
                    "primary_cloud": "",
                    "seats": 1,
                    "period": "monthly",
                },
                timeout=10,
            )
    except Exception:
        pass


@pytest.fixture(scope="session")
def playwright() -> Iterator[Playwright]:
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(playwright: Playwright) -> Iterator[Browser]:
    br = playwright.chromium.launch(
        headless=HEADLESS,
        slow_mo=SLOW_MO_MS,
        args=["--no-sandbox"],
    )
    yield br
    br.close()


@pytest.fixture(scope="function")
def appliance_page(browser: Browser, request) -> Iterator[Page]:
    """Fresh browser context — auth-bypass cookies + canonical-defaults
    pre-seeded so tests don't depend on stale localStorage from a
    developer browser.

    Captures browser console + API network calls. On test failure, dumps
    them + a screenshot to /tmp/vyomi-ui-real-failures/ so triage is
    "look at the screenshot + the failed POST", not "rerun with -s".
    """
    ctx = browser.new_context(
        viewport={"width": 1440, "height": 900},
        ignore_https_errors=True,
    )
    ctx.add_cookies([
        {"name": "cloudlearn_tier_acknowledged", "value": "1", "url": BASE_URL},
        {"name": "vyomi_tier_acknowledged", "value": "1", "url": BASE_URL},
    ])
    ctx.add_init_script("""
      try {
        localStorage.setItem(
          'vyomi.simulation.spaces.v2',
          JSON.stringify([
            { id: 'space-aws-default',   name: 'aws-default',   provider_id: 'aws',   status: 'active', region: 'us-east-1' },
            { id: 'space-gcp-default',   name: 'gcp-default',   provider_id: 'gcp',   status: 'active', region: 'us-central1' },
            { id: 'space-azure-default', name: 'azure-default', provider_id: 'azure', status: 'active', region: 'eastus' },
          ])
        );
      } catch (e) {}
    """)
    page = ctx.new_page()
    console_log: list[str] = []
    network_log: list[str] = []
    page.on("console", lambda msg: console_log.append(f"[{msg.type}] {msg.text}"))
    def _on_response(resp):
        if "/api/" in resp.url:
            network_log.append(f"{resp.status} {resp.request.method} {resp.url}")
    page.on("response", _on_response)
    yield page
    # Dump diagnostics on failure
    rep = getattr(request.node, "rep_call", None)
    if rep and rep.failed:
        out_dir = "/tmp/vyomi-ui-real-failures"
        import os as _os
        _os.makedirs(out_dir, exist_ok=True)
        test_id = request.node.name.replace("/", "_").replace("[", "_").replace("]", "_")
        try:
            page.screenshot(path=f"{out_dir}/{test_id}.png", full_page=True)
            print(f"\n  ↳ screenshot: {out_dir}/{test_id}.png")
        except Exception:
            pass
        if console_log:
            print(f"  ↳ browser console (last 20):")
            for line in console_log[-20:]:
                print(f"      {line}")
        if network_log:
            print(f"  ↳ /api/ calls ({len(network_log)}):")
            for line in network_log[-20:]:
                print(f"      {line}")
    ctx.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Expose test outcome to fixtures so we can dump diagnostics on fail."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, "rep_" + rep.when, rep)


def pytest_report_header(config):
    return [
        f"  UI-REAL conformance — base url:    {BASE_URL}",
        f"  UI-REAL conformance — headless:    {HEADLESS}",
        f"  UI-REAL conformance — slowmo (ms): {SLOW_MO_MS}",
    ]
