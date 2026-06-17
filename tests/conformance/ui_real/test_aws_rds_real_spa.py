"""Real Playwright RDS round-trip test.

This is the test that WOULD HAVE caught the `db_instances` envelope
bug shipped in v2.0.0-v2.0.3. The flow:

  1. Open https://localhost:9000/console/aws  (Playwright browser)
  2. Click into RDS via the rail
  3. Click "Create database"
  4. Walk each wizard tab in turn — fill that tab's fields, click Next
  5. On the final tab: click submit
  6. Wait for the SPA to navigate back to the list view
  7. **Assert a table row containing the new DB identifier is visible**

Step 7 is the contractual gap the old API-only tests had. The old test
only asserted `requests.get(/api/rds/databases)` returned the resource
in JSON — which it did, but the SPA didn't display it. Now we assert
what the user sees.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import Page

from tests.conformance.ui_real._spa_helpers import (
    assert_list_contains,
    assert_no_error_toast,
    click_create,
    fetch_catalog,
    navigate_to_console,
    navigate_to_service,
    walk_wizard_and_submit,
    wizard_tabs_with_fields,
)


def test_aws_rds_real_browser_round_trip(appliance_page: Page):
    """Click-driven RDS create + assert DOM row visible."""
    identifier = f"realtest-rds-{uuid.uuid4().hex[:6]}"

    # 1. Load AWS console
    navigate_to_console(appliance_page, "aws")

    # 2. Click into RDS service via rail navigation
    navigate_to_service(appliance_page, "aws", "rds")

    # 3. Open the create wizard
    click_create(appliance_page)

    # 4-5. Walk every wizard tab — fill the visible fields, click Next,
    #      until the last tab where we submit. Catalog-schema-driven —
    #      as the wizard schema evolves the test follows automatically.
    cat = fetch_catalog("aws")
    tabs = wizard_tabs_with_fields(cat.get("rds") or {})
    walk_wizard_and_submit(
        appliance_page, tabs, identifier,
        overrides={
            "name": identifier,
            "db_instance_identifier": identifier,
            "master_username": "realtest",
            "master_user_password": "RealTest-Pw!23",
        },
    )

    # 6. SPA's submit handler does:
    #       toast(name + " created")  →  navigate({view:"list"})
    #    The list view fetches /api/rds/databases and renders rows.
    #
    # 7. ASSERT THE ROW IS VISIBLE. THIS IS THE WHOLE POINT.
    assert_list_contains(appliance_page, identifier)

    # 8. No error toast — the JSON contract might be green but a 422
    #    error toast firing would still be a bug.
    assert_no_error_toast(appliance_page)
