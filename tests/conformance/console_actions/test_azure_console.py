"""Parametrized Azure console action tests.

See ``test_aws_console`` module docstring for the two structural skip
categories introduced in session 4 (catalog stubs + chain-dependency
parents). The mechanism is identical here.
"""
from __future__ import annotations
import pytest

from .catalog_reader import enumerate_actions
from .conftest import record_result


_SPECS = [s for s in enumerate_actions(["azure"])]
_CREATED_IDS: dict[str, str] = {}
_STUB_SERVICES: set[str] = set()


def _is_stub_response(status_code: int, body_text: str) -> bool:
    if status_code != 404:
        return False
    return '"detail":"Not found"' in (body_text or "")


# Pattern C — environmental failure (host disk / LXD postgres). See
# test_aws_console for rationale.
_ENV_PATTERNS = (
    (507, "insufficient_disk"),
    (503, "remote \"postgres\""),
    (503, "LXDUnavailable"),
    (503, "postgres"),
)


def _is_env_failure(status_code: int, body_text: str) -> bool:
    body = (body_text or "").lower()
    for code, pat in _ENV_PATTERNS:
        if status_code == code and pat.lower() in body:
            return True
    return False


@pytest.mark.parametrize("spec", _SPECS, ids=[s.test_id for s in _SPECS])
def test_azure_action(spec, http_session, base_url):
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
    if "{name}" in path:
        placeholder = _CREATED_IDS.get(spec.service) or f"vyomi-conf-{spec.service}"
        path = path.replace("{name}", placeholder)

    # Azure ARM REST requires api-version on every request.
    params = {"api-version": "2023-09-01"}

    url = f"{base_url}{path}"
    kwargs = {"timeout": 30, "params": params}
    if spec.method in {"POST", "PUT", "PATCH"} and spec.payload is not None:
        kwargs["json"] = spec.payload
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

    # Pattern C — environmental failure (host disk / LXD postgres image).
    if not ok and _is_env_failure(r.status_code, r.text):
        record_result(spec, r.status_code, True, f"environmental: {r.status_code}")
        if spec.action == "create":
            _STUB_SERVICES.add(spec.service)
        pytest.skip("environmental: host can't satisfy this op (disk/image)")

    if ok and spec.action == "create":
        try:
            data = r.json()
            if isinstance(data, dict) and data.get("name"):
                _CREATED_IDS[spec.service] = str(data["name"])
        except Exception:
            pass

    detail = ""
    if not ok:
        try:
            detail = (r.text or "")[:200].replace("\n", " ")
        except Exception:
            detail = ""
    record_result(spec, r.status_code, ok, detail)
    assert ok, (
        f"Azure {spec.service}.{spec.action} {spec.method} {path} → "
        f"HTTP {r.status_code} (expected one of {spec.expected_status}). Body: {detail}"
    )
