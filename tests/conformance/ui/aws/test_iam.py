"""AWS IAM — UI conformance for user create + list + delete."""
from __future__ import annotations

import uuid

import requests

from tests.conformance.ui._helpers import (
    BASE_URL, build_spa_payload, delete_resource, list_resources,
    post_create, read_catalog_fields,
)

USER = "uictest-iam-" + uuid.uuid4().hex[:8]


def test_aws_iam_user_create_via_spa_contract(appliance_page):
    fields = read_catalog_fields("aws", "iam")
    assert fields, "Empty IAM wizard schema"

    body = build_spa_payload(fields, overrides={
        "name": USER,
    })
    post_create("/api/iam/users", body, expect_status=(200, 201))

    listed = list_resources("/api/iam/users")
    items = listed.get("Users") or listed.get("users") or listed
    names = [
        (u.get("UserName") or u.get("user_name") or u.get("name", ""))
        for u in (items if isinstance(items, list) else [])
    ]
    assert USER in names, f"User {USER} missing. Got: {names[:5]}..."

    delete_resource("/api/iam/users", USER)
