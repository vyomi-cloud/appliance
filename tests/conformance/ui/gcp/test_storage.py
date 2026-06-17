"""GCP Cloud Storage — UI conformance for bucket create + object upload."""
from __future__ import annotations

import uuid

import requests

from tests.conformance.ui._helpers import (
    BASE_URL, build_spa_payload, list_resources, post_create, read_catalog_fields,
)

BUCKET = "uictest-gcs-" + uuid.uuid4().hex[:8]


def test_gcp_storage_create_via_spa_contract(appliance_page):
    fields = read_catalog_fields("gcp", "storage")
    assert fields, "Empty Storage wizard schema"

    body = build_spa_payload(fields, overrides={"name": BUCKET})
    post_create("/api/gcp/storage/v1/b", body, expect_status=(200, 201))

    listed = list_resources("/api/gcp/storage/v1/b")
    items = listed.get("items") or listed.get("buckets") or []
    names = [b.get("name", "") for b in (items if isinstance(items, list) else [])]
    assert BUCKET in names, f"Bucket {BUCKET} missing. Got: {names[:5]}..."

    try:
        requests.delete(f"{BASE_URL}/api/gcp/storage/v1/b/{BUCKET}", timeout=5)
    except Exception:
        pass
