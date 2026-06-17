"""Azure VM — UI conformance for VM create.

Azure ARM paths are nested under resource groups. We use a sensible
default RG/location combination from the catalog defaults.
"""
from __future__ import annotations

import uuid

from tests.conformance.ui._helpers import (
    BASE_URL, build_spa_payload, get_service_meta, list_resources,
    post_create, read_catalog_fields,
)

VM = "uictest-azvm-" + uuid.uuid4().hex[:8]
RG = "vyomi-rg"
SUB = "00000000-0000-0000-0000-000000000000"


def test_azure_vm_create_via_spa_contract(appliance_page):
    fields = read_catalog_fields("azure", "vm")
    if not fields:
        # Azure catalog still being filled in — skip gracefully so we
        # don't claim a regression that's just a missing wizard schema.
        import pytest
        pytest.skip("Azure VM wizard schema not yet present in catalog")

    body = build_spa_payload(fields, overrides={"name": VM})
    # Azure ARM endpoint convention: /subscriptions/.../providers/Microsoft.Compute/virtualMachines
    coll = (
        f"/subscriptions/{SUB}/resourceGroups/{RG}"
        f"/providers/Microsoft.Compute/virtualMachines/{VM}"
    )
    # Azure VM create uses PUT not POST per ARM convention.
    post_create(coll, body, method="PUT", expect_status=(200, 201, 202))
