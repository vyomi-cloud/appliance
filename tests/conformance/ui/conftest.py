"""Shared pytest fixtures for the UI conformance suite.

Owns:
  * Playwright lifecycle (browser + context)
  * Appliance endpoint resolution
  * Auth bypass (sets the cookie the appliance uses to skip the
    first-visit /pricing redirect, so the SPA loads immediately)
  * Multipass-VM-IP discovery for data-plane assertions
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Iterator

import pytest
from playwright.sync_api import (
    Browser,
    Page,
    Playwright,
    sync_playwright,
)
import requests


# ── Configuration ──────────────────────────────────────────────────────────

BASE_URL = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
HEADLESS = os.environ.get("PWDEBUG", "") != "1"
SLOW_MO_MS = int(os.environ.get("VYOMI_UI_SLOWMO_MS", "0"))


# ── Pre-flight: appliance must be up ───────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _appliance_healthy_and_max_tier():
    """Block at session start until the appliance answers /healthz, then
    ensure it's on the Max tier — otherwise tier gates fire on services
    outside the primary cloud (e.g. trying GCP from a Pro/aws appliance
    returns 403 tier_provider_locked instead of running the test).

    This is identical to what the existing console-actions conformance
    harness does (tests/conformance/console_actions/conftest.py)."""
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
        pytest.skip(f"Appliance not reachable at {BASE_URL} ({last_err}); "
                    "run `vyomi up` first")

    # Promote to Max so cross-cloud tests + advanced features don't 403.
    # POST /api/license/signup works in dev mode and is a no-op if already
    # on the right tier.
    try:
        cur = requests.get(f"{BASE_URL}/api/runtime/tier", timeout=5)
        active = (cur.json() or {}).get("active_tier", "") if cur.status_code == 200 else ""
        if active.lower() != "max":
            requests.post(
                f"{BASE_URL}/api/license/signup",
                json={
                    "tier": "max",
                    "user": "ui-conformance",
                    "email": "ui-conformance@vyomi.cloud",
                    "primary_cloud": "",
                    "seats": 1,
                    "period": "monthly",
                },
                timeout=10,
            )
    except Exception:
        # Tier promotion is best-effort; tests that need it will fail
        # their own assertions with clearer error messages.
        pass


# ── Multipass VM IP for data-plane assertions ──────────────────────────────

@pytest.fixture(scope="session")
def appliance_vm_ip() -> str:
    """The IP we use to psql into the appliance's bundled Postgres + reach
    other engine ports not forwarded to localhost. Pulled from multipass."""
    env_override = os.environ.get("VYOMI_VM_IP", "").strip()
    if env_override:
        return env_override
    try:
        out = subprocess.run(
            ["multipass", "info", "cloudlearn-appliance"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        for line in out.splitlines():
            if line.strip().startswith("IPv4:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "127.0.0.1"


# ── Playwright lifecycle ───────────────────────────────────────────────────

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
def appliance_page(browser: Browser) -> Iterator[Page]:
    """Fresh browser context navigated to /ui with auth-bypass cookies
    + canonical-defaults localStorage pre-seeded."""
    ctx = browser.new_context(
        viewport={"width": 1440, "height": 900},
        ignore_https_errors=True,
    )
    ctx.add_cookies([
        {"name": "cloudlearn_tier_acknowledged", "value": "1", "url": BASE_URL},
        {"name": "vyomi_tier_acknowledged", "value": "1", "url": BASE_URL},
    ])
    # Pre-seed canonical workspace defaults so tests don't depend on
    # whatever stale list a developer browser has.
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
    page.goto(f"{BASE_URL}/ui", wait_until="domcontentloaded")
    yield page
    ctx.close()


def pytest_report_header(config):
    return [
        f"  UI conformance — base url:    {BASE_URL}",
        f"  UI conformance — headless:    {HEADLESS}",
        f"  UI conformance — slowmo (ms): {SLOW_MO_MS}",
    ]
