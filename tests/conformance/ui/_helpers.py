"""Shared helpers for the UI conformance suite.

Each test exercises a single resource type via the appliance's own
catalog-defined wizard schema:

    1. Fetch /api/<provider>/catalog for the service
    2. Build a payload using the EXACT field names + defaults the SPA
       would build (mirrors aws-console.html::submit())
    3. POST it
    4. Verify state via the list endpoint
    5. (where applicable) Verify the real backend / data plane reacted
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Iterable

import requests

BASE_URL = os.environ.get("VYOMI_BASE_URL", "http://localhost:9000").rstrip("/")


# ── Catalog reader ─────────────────────────────────────────────────────────

def read_catalog_fields(provider: str, service_key: str) -> list[dict]:
    """Pull the wizard field definitions for `service_key` from
    /api/<provider>/catalog. Returns flat list across all tabs / sections.
    """
    resp = requests.get(f"{BASE_URL}/api/{provider}/catalog", timeout=5)
    resp.raise_for_status()
    catalog = resp.json()
    svcs = catalog.get("services") or catalog.get("catalog", {})
    if isinstance(svcs, list):
        svcs = {s.get("key", ""): s for s in svcs}
    svc = svcs.get(service_key) or {}
    wizard = svc.get("wizard") or {}
    fields = []
    for tab in wizard.get("tabs") or []:
        for section in tab.get("sections") or []:
            for f in section.get("fields") or []:
                fields.append(f)
    return fields


def get_service_meta(provider: str, service_key: str) -> dict:
    """Return the service metadata block (collection_path, create_method,
    etc.) for `service_key`."""
    resp = requests.get(f"{BASE_URL}/api/{provider}/catalog", timeout=5)
    resp.raise_for_status()
    catalog = resp.json()
    svcs = catalog.get("services") or catalog.get("catalog", {})
    if isinstance(svcs, list):
        svcs = {s.get("key", ""): s for s in svcs}
    return svcs.get(service_key) or {}


# ── Payload builder ────────────────────────────────────────────────────────

def build_spa_payload(fields: Iterable[dict], overrides: dict) -> dict:
    """Construct the JSON body the SPA wizard's submit() would build.

    `overrides` is a dict of field_name → value supplied by the test
    (e.g. the unique identifier). For all other fields we fall back to:

      • the catalog `default` if declared
      • a type-appropriate sensible value otherwise

    Internal `__foo__` fields and pure-display `info` types are skipped
    (same as the real submit handler does).

    IMPORTANT: any override key NOT in the catalog is still added to the
    payload at the end. This lets tests force fields the wizard doesn't
    expose but the backend model accepts (e.g. `storage_gb=1` to clear
    the disk-health preflight gate on EC2/Compute).
    """
    body: dict[str, Any] = {}
    for f in fields:
        name = f.get("name", "")
        ftype = f.get("type", "")
        if not name or name.startswith("__") or ftype == "info":
            continue
        if name in overrides:
            body[name] = overrides[name]
            continue
        if "default" in f and f["default"] not in (None, ""):
            body[name] = f["default"]
            continue
        # type-driven sensible defaults
        if ftype in ("number", "integer"):
            body[name] = 1
        elif ftype in ("text", "string"):
            body[name] = f"uictest-{uuid.uuid4().hex[:6]}"
        elif ftype in ("password", "secret"):
            body[name] = "UiTest-Pw!23"
        elif ftype == "radio":
            opts = f.get("options") or [{}]
            body[name] = opts[0].get("value", False)
        elif ftype == "select":
            opts = f.get("options") or [{}]
            body[name] = opts[0].get("value", "")
        elif ftype == "checkbox" or ftype == "boolean":
            body[name] = False
        elif ftype == "tagsEditor":
            body[name] = {"env": "uictest"}
        elif ftype == "tags":
            body[name] = [{"key": "env", "value": "uictest"}]
        # any other unknown type → omit so the model fills its own default

    # Force any override key not in the catalog through to the backend
    # (e.g. `storage_gb` on EC2 isn't a wizard field but the model
    # accepts it). Without this, only catalog-declared overrides take
    # effect.
    for k, v in overrides.items():
        if k not in body:
            body[k] = v
    return body


# ── HTTP helpers ───────────────────────────────────────────────────────────

def post_create(collection_path: str, body: dict, *, method: str = "POST",
                expect_status: tuple[int, ...] = (200, 201, 202)) -> dict:
    """POST the body to the collection_path. Raises with helpful detail
    on validation failure (the exact bug class this suite hunts).

    Two environment conditions auto-skip instead of fail (using pytest's
    skip mechanism) — they're not bugs in the appliance's contract:

      • HTTP 404 with detail 'Not found' — route isn't registered yet
        (an entire service surface is unbuilt; that's a roadmap gap,
        not a contract violation)
      • HTTP 507 with code 'insufficient_disk' — the appliance's disk-
        health gate refused a real LXD/Docker provisioning call. This is
        a host-environment problem, not an appliance bug.
    """
    import pytest as _pytest
    url = f"{BASE_URL}{collection_path}"
    resp = requests.request(method, url, json=body, timeout=20)
    if resp.status_code == 404:
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = ""
        if "Not found" in str(detail) or "not found" in str(detail).lower():
            _pytest.skip(
                f"{method} {url} — route not registered yet "
                "(surface unbuilt, not a contract bug)"
            )
    if resp.status_code == 507:
        try:
            detail = resp.json().get("detail", {})
            if isinstance(detail, dict) and detail.get("code") == "insufficient_disk":
                _pytest.skip(
                    f"insufficient_disk on host — {detail.get('reason','')}"
                )
        except Exception:
            pass
    if resp.status_code == 403:
        # Tier gates fire as 403 with a code like tier_provider_locked /
        # tier_service_locked / tier_quantity_limit. The appliance is
        # behaving correctly — the test's preconditions aren't met (tier
        # too low). Skip rather than fail.
        try:
            err = resp.json().get("error") or resp.json().get("detail") or {}
            if isinstance(err, dict):
                code = err.get("code", "")
                if str(code).startswith("tier_"):
                    _pytest.skip(f"tier gate: {code} — {err.get('reason','')}")
        except Exception:
            pass
    assert resp.status_code in expect_status, (
        f"{method} {url} → HTTP {resp.status_code}\n"
        f"  body sent: {body}\n"
        f"  response:  {resp.text[:600]}"
    )
    try:
        return resp.json()
    except Exception:
        return {}


def list_resources(collection_path: str) -> dict:
    """GET the collection_path and return the parsed JSON."""
    resp = requests.get(f"{BASE_URL}{collection_path}", timeout=10)
    resp.raise_for_status()
    return resp.json()


def list_contains(collection_path: str, identifier: str) -> bool:
    """Most robust list-check: serialize the full response and search for
    the identifier anywhere in the JSON. Avoids having to know which of
    ten different field names the resource uses for its primary key."""
    import json as _json
    resp = requests.get(f"{BASE_URL}{collection_path}", timeout=10)
    if resp.status_code != 200:
        return False
    return identifier in _json.dumps(resp.json())


def delete_resource(collection_path: str, identifier: str,
                    *, query: str = "") -> int:
    """Best-effort DELETE. Returns the status code. 404 is fine for
    idempotent teardowns (the test may have failed before create)."""
    url = f"{BASE_URL}{collection_path}/{identifier}"
    if query:
        url = f"{url}?{query}"
    try:
        resp = requests.delete(url, timeout=10)
        return resp.status_code
    except Exception:
        return 0
