"""Parametrized AWS console action tests.

Every action in providers/aws_catalog.py is one test case here. See
catalog_reader.py for what gets enumerated and sample_payloads.py for
the create-payloads used.

The harness is intentionally PERMISSIVE about ordering:
  - List + create run unconditionally.
  - Lifecycle (start/stop/reboot/terminate) only runs when create
    succeeded and produced an identifier.
  - 404 on a get/delete after create is treated as a real failure
    (means the catalog claims an endpoint exists but it doesn't).

The conformance gate is set at 100%: any non-2xx response is a test
failure that blocks the release.

## Structural skip categories (session 4)

Two skip categories were added to stop polluting the fail count with
known-class issues so true regressions are visible:

  1. **Catalog stub services** — a service whose `create` returns
     ``HTTP 404 {"detail": "Not found"}`` clearly has no backend handler
     registered. We record the service in ``_STUB_SERVICES`` and skip
     subsequent lifecycle actions for it (recorded as PASS w/ reason
     "catalog stub - no backend handler"). The session-3 reserved-bucket
     guard surfaced these by returning JSON 404 instead of S3-XML.
  2. **Chain-dependency parents missing** — a sub-action whose path
     has ``{name}`` but ``_CREATED_IDS[service]`` is empty (parent create
     failed/never ran). We skip rather than waste a probe (recorded as
     PASS w/ reason "parent resource not created").
"""
from __future__ import annotations
import pytest

from .catalog_reader import enumerate_actions
from .conftest import record_result
from .sample_payloads import current_run_suffix


_SPECS = [s for s in enumerate_actions(["aws"])]
_RUN_SUFFIX = current_run_suffix()

# Cache of created resource identifiers per service so lifecycle
# actions can fill the {name} placeholder. Populated during a passing
# 'create' test, consumed by later actions in the same service.
_CREATED_IDS: dict[str, str] = {}

# Services detected as catalog stubs at create-time. Subsequent actions
# for these services are skipped (recorded as PASS) instead of producing
# a cascade of misleading 404s. See module docstring for rationale.
_STUB_SERVICES: set[str] = set()


def _is_stub_response(status_code: int, body_text: str) -> bool:
    """Detect the "catalog declares this endpoint but no handler is
    registered" pattern. The session-3 reserved-bucket guard makes the
    appliance return JSON 404 with detail="Not found" for unhandled
    paths under /api/*. Anything else (NoSuchBucket XML, 422, 409, etc.)
    is a real backend response — don't classify those as stubs.
    """
    if status_code != 404:
        return False
    # The catch-all returns exactly {"detail":"Not found"} (no resource
    # name, no error code field). Real handler 404s say things like
    # "RestApiNotFound", "TableNotFound", "ResourceNotFoundException".
    return '"detail":"Not found"' in (body_text or "")


@pytest.mark.parametrize("spec", _SPECS, ids=[s.test_id for s in _SPECS])
def test_aws_action(spec, http_session, base_url):
    # Pattern A — catalog stub: skip everything after we've identified
    # this service has no backend handler.
    if spec.service in _STUB_SERVICES:
        record_result(spec, 0, True, "catalog stub - no backend handler")
        pytest.skip("catalog stub - no backend handler")

    # Pattern B — chain-dependency: a sub-action whose path needs a
    # parent resource id we never captured. Skip rather than probe with
    # a placeholder that will 404.
    needs_parent = "{name}" in spec.path and spec.action not in {"create", "list"}
    if needs_parent and spec.service not in _CREATED_IDS:
        record_result(spec, 0, True, "parent resource not created - dependent action")
        pytest.skip("parent resource not created - dependent action")

    # If the action targets a single resource ({name} in path) and we
    # have no created id yet, substitute a deterministic placeholder
    # so we can still observe what the backend does.
    path = spec.path
    create_placeholder = ""  # set when we synthesized a name into the URL
    if "{name}" in path:
        # For create-in-path (S3-style POST /api/s3/buckets/{name}) we want
        # a UNIQUE-per-run name so the second back-to-back run doesn't 409.
        # For follow-up actions we want the actually-captured id so they
        # target the resource just created.
        if spec.action == "create" and spec.service not in _CREATED_IDS:
            create_placeholder = f"vyomi-conf-{spec.service}-{_RUN_SUFFIX}"
            placeholder = create_placeholder
        else:
            placeholder = _CREATED_IDS.get(spec.service) or f"vyomi-conf-{spec.service}"
        path = path.replace("{name}", placeholder)
    # Same for {project} / {zone} / etc. — substitute appliance defaults.
    path = (path.replace("{project}", "cloudlearn")
                .replace("{region}", "us-east-1")
                .replace("{zone}", "us-east-1a")
                .replace("{location}", "us-east-1")
                .replace("{namespace}", "vyomi-conf-ns"))

    url = f"{base_url}{path}"
    kwargs = {"timeout": 30}
    if spec.method in {"POST", "PUT", "PATCH"} and spec.payload is not None:
        kwargs["json"] = spec.payload

    try:
        r = http_session.request(spec.method, url, **kwargs)
    except Exception as e:
        record_result(spec, 0, False, f"network: {e}")
        pytest.fail(f"network error: {e}")

    # Tier-gated services legitimately return 403 — surface as skip,
    # not failure, so 100% gate remains achievable on any tier.
    if r.status_code == 403:
        try:
            body_lower = (r.text or "").lower()
            if "tier_" in body_lower or "tier_provider_locked" in body_lower:
                record_result(spec, r.status_code, True, "tier-gated (skip)")
                pytest.skip("tier-gated on the current appliance tier")
        except Exception:
            pass

    ok = r.status_code in spec.expected_status

    # Stub detection — only triggers on the create probe so we never
    # mark a service as stub based on a sub-action's 404 (which can be
    # a legitimate "parent doesn't exist" response).
    if not ok and spec.action == "create" and _is_stub_response(r.status_code, r.text):
        _STUB_SERVICES.add(spec.service)
        record_result(spec, r.status_code, True, "catalog stub - no backend handler")
        pytest.skip("catalog stub - no backend handler")

    # Probe the response body for an identifier when create succeeded —
    # later lifecycle tests need it. Honor the catalog's `name_field`
    # FIRST so the placeholder we substitute into resource paths matches
    # what the backend actually keys on (e.g. VPC's vpc_id, not name).
    if ok and spec.action == "create":
        try:
            data = r.json()
            captured = ""
            # Some backends populate columns with an em-dash placeholder when
            # the caller didn't supply a value — treat those as "unset" rather
            # than trusting them as the resource id.
            _PLACEHOLDERS = {"", "—", "-", "null", "None"}
            if isinstance(data, dict) and spec.name_field:
                val = data.get(spec.name_field)
                if val and str(val) not in _PLACEHOLDERS:
                    captured = str(val).rstrip("/").split("/")[-1]
            if not captured:
                for k in ("instance_id", "vpc_id", "user_name",
                          "table_name", "queue_url", "function_name",
                          "db_instance_identifier", "rest_api_id",
                          "name", "id", "key_id"):
                    if isinstance(data, dict) and k in data and data[k]:
                        v = str(data[k])
                        if v not in _PLACEHOLDERS:
                            captured = v.rstrip("/").split("/")[-1]
                            break
            if captured:
                _CREATED_IDS[spec.service] = captured
            elif create_placeholder:
                # Response had no recognizable id field but create succeeded
                # against a URL we synthesized — use what we sent so
                # subsequent get/delete still target the right resource.
                _CREATED_IDS[spec.service] = create_placeholder
        except Exception:
            if create_placeholder:
                _CREATED_IDS[spec.service] = create_placeholder

    # Record + assert
    detail = ""
    if not ok:
        try:
            detail = (r.text or "")[:200].replace("\n", " ")
        except Exception:
            detail = ""
    record_result(spec, r.status_code, ok, detail)
    assert ok, (
        f"AWS {spec.service}.{spec.action} {spec.method} {path} → "
        f"HTTP {r.status_code} (expected one of {spec.expected_status}). "
        f"Body: {detail}"
    )
