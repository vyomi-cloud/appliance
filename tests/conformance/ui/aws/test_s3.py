"""AWS S3 — UI conformance for bucket create + object PUT/GET.

S3 uses the **wire protocol** for bucket lifecycle (PUT /<bucket>) and
object lifecycle (PUT /<bucket>/<key>) — not a REST collection endpoint.
The SPA's S3 console wizard does the same. We mirror that here so the
test exercises the same path real boto3 + the SPA both use.
"""
from __future__ import annotations

import os
import uuid

import requests

BASE_URL = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")
BUCKET = "uictest-s3-" + uuid.uuid4().hex[:8]


def test_aws_s3_create_via_spa_contract(appliance_page):
    # ① Bucket via S3 wire PUT (same path SPA + boto3 + aws-cli use)
    put = requests.put(f"{BASE_URL}/{BUCKET}", timeout=10)
    assert put.status_code in (200, 204), (
        f"PUT /{BUCKET} → HTTP {put.status_code}: {put.text[:200]}"
    )

    # ② List buckets and verify it's there
    listed = requests.get(f"{BASE_URL}/", timeout=10)
    assert listed.status_code == 200
    assert BUCKET in listed.text, (
        f"Bucket {BUCKET} not in list buckets response (first 300 chars: "
        f"{listed.text[:300]}...)"
    )

    # ③ Real S3 PUT/GET round-trip via MinIO backend
    put_url = f"{BASE_URL}/{BUCKET}/conformance-probe.txt"
    payload = b"vyomi-ui-conformance"
    put_obj = requests.put(put_url, data=payload, timeout=10)
    assert put_obj.status_code in (200, 204), (
        f"PUT object → {put_obj.status_code}: {put_obj.text[:200]}"
    )
    get_obj = requests.get(put_url, timeout=10)
    assert get_obj.status_code == 200
    assert get_obj.content == payload, "Real bytes round-trip failed"

    # ④ Cleanup
    requests.delete(put_url, timeout=5)
    requests.delete(f"{BASE_URL}/{BUCKET}", timeout=5)
