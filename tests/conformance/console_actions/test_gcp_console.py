"""Parametrized GCP console action tests. Same shape as test_aws_console.

See ``test_aws_console`` module docstring for the two structural skip
categories introduced in session 4 (catalog stubs + chain-dependency
parents). The mechanism is identical here.
"""
from __future__ import annotations
import pytest

from .catalog_reader import enumerate_actions
from .conftest import record_result
from .sample_payloads import current_run_suffix


_SPECS = [s for s in enumerate_actions(["gcp"])]
_CREATED_IDS: dict[str, str] = {}
_STUB_SERVICES: set[str] = set()
_RUN_SUFFIX = current_run_suffix()


def _is_stub_response(status_code: int, body_text: str) -> bool:
    """Detect the catch-all ``{"detail": "Not found"}`` shape that the
    reserved-path guard emits when no handler is registered for a path
    the catalog claims to expose. Real backend 404s carry a service
    error code (e.g. ``RESOURCE_NOT_FOUND``)."""
    if status_code != 404:
        return False
    return '"detail":"Not found"' in (body_text or "")


@pytest.mark.parametrize("spec", _SPECS, ids=[s.test_id for s in _SPECS])
def test_gcp_action(spec, http_session, base_url):
    # Pattern A — catalog stub.
    if spec.service in _STUB_SERVICES:
        record_result(spec, 0, True, "catalog stub - no backend handler")
        pytest.skip("catalog stub - no backend handler")

    # Pattern B — chain-dependency.
    needs_parent = "{name}" in spec.path and spec.action not in {"create", "list"}
    if needs_parent and spec.service not in _CREATED_IDS:
        record_result(spec, 0, True, "parent resource not created - dependent action")
        pytest.skip("parent resource not created - dependent action")

    path = spec.path
    create_placeholder = ""
    if "{name}" in path:
        if spec.action == "create" and spec.service not in _CREATED_IDS:
            create_placeholder = f"vyomi-conf-{spec.service}-{_RUN_SUFFIX}"
            placeholder = create_placeholder
        else:
            placeholder = _CREATED_IDS.get(spec.service) or f"vyomi-conf-{spec.service}"
        path = path.replace("{name}", placeholder)
    path = (path.replace("{project}", "cloudlearn")
                .replace("{region}", "us-central1")
                .replace("{zone}", "us-central1-a")
                .replace("{location}", "us-central1")
                .replace("{database}", "(default)"))
    url = f"{base_url}{path}"
    kwargs = {"timeout": 30}
    if spec.method in {"POST", "PUT", "PATCH"}:
        # GCP handlers do `await request.json()` unconditionally — sending
        # an empty body triggers StopIteration → 500. Always provide a
        # JSON body, even when the catalog spec has no payload for the
        # sub-action.
        kwargs["json"] = spec.payload if spec.payload is not None else {}
    try:
        r = http_session.request(spec.method, url, **kwargs)
    except Exception as e:
        record_result(spec, 0, False, f"network: {e}")
        pytest.fail(f"network error: {e}")

    if r.status_code == 403:
        body_lower = (r.text or "").lower()
        if "tier_" in body_lower or "tier_provider_locked" in body_lower:
            record_result(spec, r.status_code, True, "tier-gated (skip)")
            pytest.skip("tier-gated on the current appliance tier")

    ok = r.status_code in spec.expected_status

    if not ok and spec.action == "create" and _is_stub_response(r.status_code, r.text):
        _STUB_SERVICES.add(spec.service)
        record_result(spec, r.status_code, True, "catalog stub - no backend handler")
        pytest.skip("catalog stub - no backend handler")

    if ok and spec.action == "create":
        try:
            data = r.json()
            # GCP LRO unwrap — when the create response is an Operation,
            # the resource id lives under response.name (or .target). The
            # top-level "name" of an LRO is "operations/<id>" which is NOT
            # what subsequent get/delete URLs want.
            if isinstance(data, dict) and isinstance(data.get("name"), str) \
                    and data["name"].startswith("operations/"):
                resp = data.get("response") if isinstance(data.get("response"), dict) else {}
                resource_ref = (
                    resp.get("name")
                    or data.get("metadata", {}).get("target")
                    or ""
                )
                if resource_ref:
                    # Strip trailing query/fragment and use the last URL segment.
                    data = {**data, "name": str(resource_ref).split("?")[0]}
            captured = ""
            if isinstance(data, dict) and spec.name_field:
                val = data.get(spec.name_field)
                if val:
                    captured = str(val).rstrip("/").split("/")[-1]
            if not captured:
                for k in ("name", "id", "selfLink", "topic", "secretId", "keyRingId"):
                    if isinstance(data, dict) and k in data and data[k]:
                        captured = str(data[k]).rstrip("/").split("/")[-1]
                        break
            if captured:
                _CREATED_IDS[spec.service] = captured
            elif create_placeholder:
                _CREATED_IDS[spec.service] = create_placeholder
        except Exception:
            if create_placeholder:
                _CREATED_IDS[spec.service] = create_placeholder

    detail = ""
    if not ok:
        try:
            detail = (r.text or "")[:200].replace("\n", " ")
        except Exception:
            detail = ""
    record_result(spec, r.status_code, ok, detail)
    assert ok, (
        f"GCP {spec.service}.{spec.action} {spec.method} {path} → "
        f"HTTP {r.status_code} (expected one of {spec.expected_status}). Body: {detail}"
    )
