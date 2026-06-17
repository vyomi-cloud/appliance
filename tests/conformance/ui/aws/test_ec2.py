"""AWS EC2 — UI conformance for launch-instance + describe + terminate.

The EC2 wizard is the most complex in the catalog (memory note: EC2
uses the collapsible-sections renderer, not the stepped wizard). The
SPA payload still goes to POST /api/ec2/instances with the same
catalog-derived field shape.
"""
from __future__ import annotations

import uuid

import requests

from tests.conformance.ui._helpers import (
    BASE_URL, build_spa_payload, delete_resource, list_resources,
    post_create, read_catalog_fields,
)

INSTANCE_NAME = "uictest-ec2-" + uuid.uuid4().hex[:8]


def test_aws_ec2_create_via_spa_contract(appliance_page):
    fields = read_catalog_fields("aws", "ec2")
    assert fields, "Empty EC2 wizard schema"

    body = build_spa_payload(fields, overrides={
        "name": INSTANCE_NAME,
        # Smallest viable disk — clears the disk-health preflight gate
        # on hosts with tight free space.
        "storage_gb": 1,
    })
    created = post_create("/api/ec2/instances", body, expect_status=(200, 201))
    instance_id = (
        created.get("instance_id")
        or created.get("InstanceId")
        or created.get("id")
    )
    assert instance_id, f"No instance_id in response: {created}"

    listed = list_resources("/api/ec2/instances")
    items = listed.get("instances") or listed.get("Reservations") or listed
    if isinstance(items, dict):
        items = items.get("items", [])
    assert any(
        (i.get("instance_id") or i.get("InstanceId")) == instance_id
        for i in items
    ), f"Instance {instance_id} missing from list"

    # Cleanup
    delete_resource("/api/ec2/instances", instance_id)
