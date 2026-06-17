"""Azure SQL (Microsoft.Sql/servers/databases) — UI conformance."""
from __future__ import annotations

import uuid

from tests.conformance.ui._helpers import (
    build_spa_payload, post_create, read_catalog_fields,
)

SERVER = "uictest-azsrv-" + uuid.uuid4().hex[:6]
DB = "uictest-azdb-" + uuid.uuid4().hex[:6]
RG = "vyomi-rg"
SUB = "00000000-0000-0000-0000-000000000000"


def test_azure_sql_create_via_spa_contract(appliance_page):
    fields = read_catalog_fields("azure", "sql")
    if not fields:
        import pytest
        pytest.skip("Azure SQL wizard schema not yet present in catalog")

    body = build_spa_payload(fields, overrides={"name": DB})
    coll = (
        f"/subscriptions/{SUB}/resourceGroups/{RG}"
        f"/providers/Microsoft.Sql/servers/{SERVER}/databases/{DB}"
    )
    post_create(coll, body, method="PUT", expect_status=(200, 201, 202))
