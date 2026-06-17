"""AWS DynamoDB — UI conformance for table create + put + get + delete."""
from __future__ import annotations

import uuid

import requests

from tests.conformance.ui._helpers import (
    build_spa_payload, delete_resource, list_contains, post_create,
    read_catalog_fields,
)

TABLE = "uictest_ddb_" + uuid.uuid4().hex[:8]


def test_aws_dynamodb_create_via_spa_contract(appliance_page):
    fields = read_catalog_fields("aws", "dynamodb")
    assert fields, "Empty DynamoDB wizard schema"

    body = build_spa_payload(fields, overrides={"name": TABLE})
    post_create("/api/dynamodb/tables", body, expect_status=(200, 201))

    assert list_contains("/api/dynamodb/tables", TABLE), (
        f"Table {TABLE} not found in list response"
    )

    delete_resource("/api/dynamodb/tables", TABLE)
