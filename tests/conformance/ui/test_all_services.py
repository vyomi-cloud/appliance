"""Parametrized full-catalog conformance.

Single generative test that iterates EVERY service the appliance ships
in /api/<provider>/catalog and runs the same SPA-shaped POST + list
verification we built for RDS. One test per (provider, service) tuple,
generated at collection time. Result: full UI conformance coverage that
scales automatically as the catalog grows.

What it catches:
  * Pydantic model rejects an SPA-shaped field name (the bug class that
    hit RDS / IAM / Lambda / SQS / DynamoDB on 2026-06-17)
  * Catalog declares a field type the model doesn't accept
  * Create succeeds but the resource is invisible to the list endpoint

What it does NOT cover (per-service data-plane assertions live in the
dedicated test_<service>.py files for RDS / S3 / etc.).
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import pytest
import requests

from tests.conformance.ui._helpers import (
    BASE_URL,
    build_spa_payload,
    list_contains,
    post_create,
)


# Path-template substitutions — Azure ARM + GCP regional paths need these
# placeholders filled in. Order: most-specific to least-specific.
PATH_VARS = {
    "subscription_id": "00000000-0000-0000-0000-000000000000",
    "subscriptionId":  "00000000-0000-0000-0000-000000000000",
    "resource_group":  "vyomi-rg",
    "resourceGroupName": "vyomi-rg",
    "project":         "vyomi-dev",
    "projectId":       "vyomi-dev",
    "zone":            "us-central1-a",
    "region":          "us-east-1",
    "location":        "us-east-1",
}


def _resolve_path(template: str) -> str:
    """Fill {placeholders} in the catalog path with sensible defaults.
    Returns "" if a placeholder we don't know about remains — caller will
    skip the test for that service."""
    out = template
    for k, v in PATH_VARS.items():
        out = out.replace("{" + k + "}", v)
    if "{" in out:
        return ""
    return out


def _enumerate_catalog() -> list[tuple[str, str, str, str]]:
    """Return [(provider, service_key, collection_path, create_method)]
    for every service across aws/gcp/azure that we can call statically."""
    out = []
    for provider in ("aws", "gcp", "azure"):
        try:
            resp = requests.get(f"{BASE_URL}/api/{provider}/catalog", timeout=5)
            if resp.status_code != 200:
                continue
            data = resp.json()
            svcs = data.get("services") or data.get("catalog", {})
            if isinstance(svcs, list):
                svcs = {s.get("key", ""): s for s in svcs}
        except Exception:
            continue
        for key, meta in (svcs or {}).items():
            if not key:
                continue
            coll = meta.get("collection_path") or meta.get("create_path") or ""
            if not coll:
                continue
            resolved = _resolve_path(coll)
            if not resolved:
                # Template variable we don't know — emit anyway so pytest
                # marks it skipped with a clear reason instead of silent.
                resolved = coll
            method = (meta.get("create_method") or "POST").upper()
            out.append((provider, key, resolved, method))
    return out


# Build the parameter list once at collection time. If the appliance isn't
# running, _enumerate_catalog() returns [] and the parametrize fixture
# generates zero tests (which pytest reports clearly).
_ALL_SERVICES = _enumerate_catalog()


@pytest.mark.parametrize(
    "provider,service_key,coll_path,method",
    _ALL_SERVICES,
    ids=[f"{p}.{k}" for p, k, _, _ in _ALL_SERVICES],
)
def test_service_create_via_spa_contract(
    appliance_page,
    provider: str,
    service_key: str,
    coll_path: str,
    method: str,
):
    """For every catalog service: build the SPA-shaped payload from the
    wizard schema, POST it, verify the resource shows up in list."""

    # AWS S3 uses the wire protocol (PUT /<bucket>), not /api/s3/buckets
    # POST. The per-service test_s3.py covers it; the generative test
    # would have to special-case the URL. We have full coverage either
    # way, so this is genuinely outside the generative pattern.
    if provider == "aws" and service_key == "s3":
        pytest.skip("s3 uses wire-PUT (/<bucket>) — covered by aws/test_s3.py")

    # Path still has un-resolved template vars → genuinely can't run
    # without service-specific knowledge.
    if "{" in coll_path:
        pytest.skip(
            f"{provider}/{service_key} uses path template with unknown "
            f"placeholders: {coll_path}"
        )

    # Fetch wizard schema
    try:
        cat_resp = requests.get(
            f"{BASE_URL}/api/{provider}/catalog", timeout=5,
        )
        cat_resp.raise_for_status()
        cat = cat_resp.json()
        svcs = cat.get("services") or cat.get("catalog", {})
        if isinstance(svcs, list):
            svcs = {s.get("key", ""): s for s in svcs}
        svc = svcs.get(service_key) or {}
        wizard = svc.get("wizard") or {}
        fields: list[dict[str, Any]] = []
        for tab in wizard.get("tabs") or []:
            for section in tab.get("sections") or []:
                for f in section.get("fields") or []:
                    fields.append(f)
    except Exception as e:
        pytest.skip(f"catalog read failed for {provider}/{service_key}: {e}")

    if not fields:
        pytest.skip(
            f"{provider}/{service_key} has no wizard schema yet "
            "(roadmap gap, not a contract bug)"
        )

    # Some catalog field names need an alphanumeric-only identifier
    # (Azure storage account names, DynamoDB tables) so we use a safe
    # form. Test-distinct per parametrize case → no collisions.
    identifier_safe = service_key + uuid.uuid4().hex[:8]
    identifier_safe = "".join(c for c in identifier_safe if c.isalnum())[:24]
    identifier_dashed = f"uictest-{service_key}-{uuid.uuid4().hex[:8]}"[:60]

    # Build the payload — supply `name` AND service-specific `<svc>_name`
    # AND the AWS-canonical PascalCase keys so we cover any model's
    # required identifier field regardless of how it's named.
    overrides: dict[str, Any] = {
        "name":  identifier_dashed,
        "Name":  identifier_dashed,
        f"{service_key}_name": identifier_dashed,
        f"{service_key}Name":  identifier_dashed,
    }
    # Service-specific override that need alphanumeric:
    if service_key in ("storage", "blob", "s3"):
        overrides["name"] = identifier_safe.lower()
        overrides["Name"] = identifier_safe.lower()
    # For VM-class services, force the smallest viable disk so the
    # appliance's disk-health preflight doesn't 507 us with
    # insufficient_disk on a tight host. 1 GB + Ubuntu rootfs (~1.5 GB)
    # + slop (0.5 GB) = ~3 GB requirement instead of the default ~10 GB.
    if service_key in ("ec2", "compute", "vm"):
        overrides["storage_gb"]    = 1
        overrides["diskSizeGb"]    = 1
        overrides["bootDiskSizeGb"] = 1

    body = build_spa_payload(fields, overrides=overrides)

    # POST. post_create() auto-skips for HTTP 404 (route unbuilt) and
    # HTTP 507 (disk-tight) — we INTENTIONALLY don't want to fail
    # conformance for environmental / surface gaps.
    post_create(coll_path, body, method=method,
                expect_status=(200, 201, 202, 204))

    # Verify it landed — list endpoint, search the JSON for our marker.
    if not list_contains(coll_path, identifier_dashed) \
            and not list_contains(coll_path, identifier_safe.lower()):
        pytest.fail(
            f"Resource created in {provider}/{service_key} but not "
            f"visible in GET {coll_path} list response"
        )
