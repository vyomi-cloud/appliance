"""Parametrized Azure console action tests."""
from __future__ import annotations
import pytest

from .catalog_reader import enumerate_actions
from .conftest import record_result


_SPECS = [s for s in enumerate_actions(["azure"])]
_CREATED_IDS: dict[str, str] = {}


@pytest.mark.parametrize("spec", _SPECS, ids=[s.test_id for s in _SPECS])
def test_azure_action(spec, http_session, base_url):
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
