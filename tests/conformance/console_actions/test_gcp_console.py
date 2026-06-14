"""Parametrized GCP console action tests. Same shape as test_aws_console."""
from __future__ import annotations
import pytest

from .catalog_reader import enumerate_actions
from .conftest import record_result


_SPECS = [s for s in enumerate_actions(["gcp"])]
_CREATED_IDS: dict[str, str] = {}


@pytest.mark.parametrize("spec", _SPECS, ids=[s.test_id for s in _SPECS])
def test_gcp_action(spec, http_session, base_url):
    path = spec.path
    if "{name}" in path:
        placeholder = _CREATED_IDS.get(spec.service) or f"vyomi-conf-{spec.service}"
        path = path.replace("{name}", placeholder)
    path = (path.replace("{project}", "cloudlearn")
                .replace("{region}", "us-central1")
                .replace("{zone}", "us-central1-a")
                .replace("{location}", "us-central1")
                .replace("{database}", "(default)"))
    url = f"{base_url}{path}"
    kwargs = {"timeout": 30}
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
        f"GCP {spec.service}.{spec.action} {spec.method} {path} → "
        f"HTTP {r.status_code} (expected one of {spec.expected_status}). Body: {detail}"
    )
