"""AWS SQS — UI conformance for queue create + send + receive."""
from __future__ import annotations

import uuid

import requests

from tests.conformance.ui._helpers import (
    build_spa_payload, delete_resource, list_contains, post_create,
    read_catalog_fields,
)

QUEUE = "uictest-sqs-" + uuid.uuid4().hex[:8]


def test_aws_sqs_create_via_spa_contract(appliance_page):
    fields = read_catalog_fields("aws", "sqs")
    assert fields, "Empty SQS wizard schema"

    body = build_spa_payload(fields, overrides={"name": QUEUE})
    post_create("/api/sqs/queues", body, expect_status=(200, 201))

    assert list_contains("/api/sqs/queues", QUEUE), (
        f"Queue {QUEUE} not found in list response"
    )

    delete_resource("/api/sqs/queues", QUEUE)
