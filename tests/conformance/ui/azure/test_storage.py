"""Azure Storage Account / Blob — UI conformance."""
from __future__ import annotations

import uuid

from tests.conformance.ui._helpers import (
    build_spa_payload, post_create, read_catalog_fields,
)

NAME = "uictestaz" + uuid.uuid4().hex[:8]  # Azure storage names must be alphanumeric only
RG = "vyomi-rg"
SUB = "00000000-0000-0000-0000-000000000000"


def test_azure_storage_create_via_spa_contract(appliance_page):
    fields = read_catalog_fields("azure", "storage")
    if not fields:
        import pytest
        pytest.skip("Azure Storage wizard schema not yet present in catalog")

    body = build_spa_payload(fields, overrides={"name": NAME})
    coll = (
        f"/subscriptions/{SUB}/resourceGroups/{RG}"
        f"/providers/Microsoft.Storage/storageAccounts/{NAME}"
    )
    post_create(coll, body, method="PUT", expect_status=(200, 201, 202))
