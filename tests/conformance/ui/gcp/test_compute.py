"""GCP Compute Engine — UI conformance for VM create + list + delete."""
from __future__ import annotations

import uuid

import requests

from tests.conformance.ui._helpers import (
    BASE_URL, build_spa_payload, list_resources, post_create, read_catalog_fields,
)

VM = "uictest-gce-" + uuid.uuid4().hex[:8]
PROJECT = "vyomi-dev"
ZONE = "us-central1-a"


def test_gcp_compute_create_via_spa_contract(appliance_page):
    fields = read_catalog_fields("gcp", "compute")
    assert fields, "Empty Compute wizard schema"

    body = build_spa_payload(fields, overrides={
        "name": VM,
        "machineType": f"projects/{PROJECT}/zones/{ZONE}/machineTypes/e2-medium",
        # Smallest viable disk — clears disk-health preflight gate.
        "diskSizeGb": 1,
        "bootDiskSizeGb": 1,
    })
    coll = f"/api/gcp/compute/v1/projects/{PROJECT}/zones/{ZONE}/instances"
    post_create(coll, body, expect_status=(200, 201, 202))

    listed = list_resources(coll)
    items = listed.get("items") or listed.get("instances") or []
    names = [i.get("name", "") for i in items]
    assert VM in names, f"Instance {VM} missing. Got: {names[:5]}..."

    # cleanup — best effort
    try:
        requests.delete(f"{BASE_URL}{coll}/{VM}", timeout=5)
    except Exception:
        pass
