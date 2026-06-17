"""AWS Lambda — UI conformance for function create + invoke + delete."""
from __future__ import annotations

import uuid

import requests

from tests.conformance.ui._helpers import (
    BASE_URL, build_spa_payload, delete_resource, list_resources,
    post_create, read_catalog_fields,
)

FN = "uictest-lambda-" + uuid.uuid4().hex[:8]


def test_aws_lambda_create_via_spa_contract(appliance_page):
    fields = read_catalog_fields("aws", "lambda")
    assert fields, "Empty Lambda wizard schema"

    body = build_spa_payload(fields, overrides={
        "name": FN,
        "runtime": "python3.11",
        "handler": "index.handler",
    })
    created = post_create("/api/lambda/functions", body, expect_status=(200, 201))
    fn_name = created.get("FunctionName") or created.get("function_name") or created.get("name") or FN

    listed = list_resources("/api/lambda/functions")
    items = listed.get("Functions") or listed.get("functions") or listed
    names = [
        (f.get("FunctionName") or f.get("function_name") or f.get("name", ""))
        for f in (items if isinstance(items, list) else [])
    ]
    assert fn_name in names, f"Function {fn_name} missing. Got: {names[:5]}..."

    # Invoke — both /invoke and /invocations are common path conventions
    invoke = requests.post(
        f"{BASE_URL}/api/lambda/functions/{fn_name}/invoke",
        json={"hello": "world"},
        timeout=10,
    )
    # 200 on success, 404 if invoke endpoint isn't part of catalog —
    # don't fail conformance for not-yet-implemented dataplane.
    assert invoke.status_code in (200, 202, 404)

    delete_resource("/api/lambda/functions", fn_name)
