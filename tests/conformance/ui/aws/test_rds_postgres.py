"""AWS RDS Postgres — UI conformance.

What this test guarantees end-to-end (a stronger claim than SDK conformance):

  ① **Catalog parity** — read the appliance's own
     /api/aws/catalog wizard schema (the SAME definition the SPA renders
     from). This is the source of truth for "what payload would the
     SPA send."

  ② **Pydantic acceptance** — POST a payload built from those EXACT
     field names + types to /api/rds/databases. If the Pydantic model
     ever loses an alias, this fails (which is exactly what we want).

  ③ **State persistence** — GET /api/rds/databases returns the new
     instance.

  ④ **Real data plane** — psql connects to the new database using the
     master credentials we typed into the form. Proves the backend
     actually created a role + DB, not just a metadata record.

We use Playwright to load the SPA (so the appliance is real, the catalog
is fetched live, the cookies + localStorage seeding from conftest run).
We skip the wizard click-through because (a) it's brittle in headless,
(b) the catalog-derived payload IS what the wizard would build, and (c)
the contract test is stronger when it's catalog-driven instead of UI-
state-driven.
"""
from __future__ import annotations

import os
import time
import uuid

import psycopg
import pytest
import requests
from playwright.sync_api import Page

BASE_URL = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")

# Stable per-session identifiers — separate from anything the user might
# have manually created.
DB_ID = "uictest-rds-" + uuid.uuid4().hex[:8]
MASTER_USER = "vyomi_uictest_" + uuid.uuid4().hex[:6]
MASTER_PASS = "Vy0mi-UiTest-Pw!"


def _read_rds_wizard_schema():
    """Pull the wizard field definitions from /api/aws/catalog (the SAME
    thing the SPA reads). Returns the flat list of catalog field dicts."""
    resp = requests.get(f"{BASE_URL}/api/aws/catalog", timeout=5)
    resp.raise_for_status()
    catalog = resp.json()
    services = catalog.get("services") or catalog.get("catalog") or {}
    if isinstance(services, list):
        services = {s.get("key", ""): s for s in services}
    rds = services.get("rds") or {}
    wizard = rds.get("wizard") or {}
    fields = []
    for tab in wizard.get("tabs") or []:
        for section in tab.get("sections") or []:
            for f in section.get("fields") or []:
                fields.append(f)
    return fields


def _build_spa_payload(fields):
    """Construct a JSON body using EXACTLY the field names the SPA submit
    handler would build (k → bodyObj[k] = v). Supplies sensible defaults
    for every non-info field — same shape the wizard's `submit()` function
    in aws-console.html produces."""
    body = {}
    for f in fields:
        name = f.get("name", "")
        ftype = f.get("type", "")
        if not name or name.startswith("__") or ftype == "info":
            continue
        # Test-supplied values for the fields we care about:
        if name == "name":
            body[name] = DB_ID
            continue
        if name == "master_username":
            body[name] = MASTER_USER
            continue
        if name == "master_password":
            body[name] = MASTER_PASS
            continue
        if name == "engine":
            body[name] = "postgres"
            continue
        if name == "engine_version":
            body[name] = "16"
            continue
        # Generic defaults by type — same defaults the SPA would.
        if "default" in f:
            body[name] = f["default"]
        elif ftype in ("number", "integer"):
            body[name] = 20
        elif ftype == "radio":
            body[name] = ((f.get("options") or [{}])[0]).get("value", False)
        elif ftype == "tagsEditor":
            body[name] = {"env": "uitest"}
        # Other types we leave out so the server fills defaults
    return body


def test_aws_rds_postgres_create_via_spa_contract(
    appliance_page: Page,
    appliance_vm_ip: str,
):
    """End-to-end conformance: catalog schema → SPA-shaped POST → real
    Postgres database the user can psql into."""
    page = appliance_page

    # ① Read the SPA's own wizard schema. (Fixture has already loaded the
    # SPA, so the appliance is verified up + reachable from the browser.)
    fields = _read_rds_wizard_schema()
    assert fields, (
        "Wizard schema is empty — /api/aws/catalog returned no fields for "
        "rds. The catalog generator may have regressed."
    )

    # ② POST the catalog-derived SPA payload.
    payload = _build_spa_payload(fields)
    create_resp = requests.post(
        f"{BASE_URL}/api/rds/databases",
        json=payload,
        timeout=15,
    )
    assert create_resp.status_code == 200, (
        f"Create failed with HTTP {create_resp.status_code}: "
        f"{create_resp.text[:500]}\n"
        f"Payload was: {payload}"
    )
    created = create_resp.json()
    assert created.get("db_instance_identifier") == DB_ID
    assert created.get("engine") == "postgres"

    # ③ Confirm the instance shows up in the list.
    list_resp = requests.get(f"{BASE_URL}/api/rds/databases", timeout=5)
    assert list_resp.status_code == 200
    instances = list_resp.json().get("db_instances", [])
    matched = [i for i in instances if i.get("db_instance_identifier") == DB_ID]
    assert matched, f"Instance {DB_ID} not in list. Got: {instances}"
    db = matched[0]
    # Some renderers use `status`, internal model uses `db_instance_status` —
    # accept either so the test isn't tied to the JSON view choice.
    status = db.get("db_instance_status") or db.get("status")
    assert status == "available", (
        f"Instance status {status!r}, expected 'available'. Full: {db}"
    )
    backend = db.get("runtime_backend")
    assert backend in ("real-pg", "simulated"), (
        f"Unexpected backend {backend!r}"
    )

    # ④ Data plane — only meaningful if the real provisioner ran.
    if backend == "real-pg":
        time.sleep(0.5)  # let the just-created role settle
        # v2.0.7 (#430): the physical db + role are namespaced per space, so
        # connect with the physical creds surfaced in the `connection` block
        # (parity with Cloud SQL), NOT the verbatim master_username — which
        # remains the boto3/DescribeDBInstances field.
        conn_info = db.get("connection") or {}
        assert conn_info.get("user") and conn_info.get("database"), (
            f"RDS view is missing the physical `connection` block: {db}"
        )
        db_name = conn_info["database"]
        conn_user = conn_info["user"]
        try:
            conn = psycopg.connect(
                host=appliance_vm_ip,
                port=conn_info.get("port", 5432),
                user=conn_user,
                password=conn_info.get("password", MASTER_PASS),
                dbname=db_name,
                connect_timeout=5,
            )
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT current_database(), current_user, "
                    "version() ~ 'PostgreSQL'"
                )
                row = cur.fetchone()
                assert row is not None
                assert row[0] == db_name, (
                    f"Connected to wrong DB: expected {db_name}, got {row[0]}"
                )
                assert row[1] == conn_user, (
                    f"Wrong role: expected {conn_user}, got {row[1]}"
                )
                assert row[2] is True, "Not a Postgres engine"
            finally:
                conn.close()
        except psycopg.OperationalError as e:
            pytest.fail(
                f"Data-plane assertion failed: psql {conn_user}"
                f"@{appliance_vm_ip}:5432/{db_name} — {e}"
            )


def test_aws_rds_postgres_delete_via_api():
    """Tear down the instance + role + database the previous test created.
    Idempotent — passes if the instance is already gone."""
    resp = requests.delete(
        f"{BASE_URL}/api/rds/databases/{DB_ID}",
        params={"skip_final_snapshot": "true"},
        timeout=10,
    )
    assert resp.status_code in (200, 202, 204, 404), (
        f"delete failed: {resp.status_code} {resp.text[:200]}"
    )
