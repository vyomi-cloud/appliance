"""Activity log feed filters (Microsoft.Insights/eventtypes/management/values)."""
from core.azure_arm_core import AzureArm

SUB = "00000000-0000-0000-0000-cloudlearn01"
EV = f"/subscriptions/{SUB}/providers/Microsoft.Insights/eventtypes/management/values"


def _arm():
    a = AzureArm(); a._base = "http://x"
    a.handle("PUT", f"/subscriptions/{SUB}/resourcegroups/rg1", {"api-version": "2021-04-01"}, {"location": "eastus"})
    a.handle("PUT", f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/v1", {"api-version": "2023-04-01"}, {"location": "eastus", "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}}})
    return a


def _q(a, flt):
    r = a.handle("GET", EV, {"api-version": "2015-04-01", "$filter": flt})
    assert r["status"] == 200
    return r["body"]["value"]


def test_resource_scope_and_status_level_caller_filters():
    a = _arm()
    rid = f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/v1"
    rows = _q(a, f"resourceUri eq '{rid}'")
    assert rows and all(r["resourceId"].lower() == rid.lower() for r in rows)
    assert _q(a, f"resourceUri eq '{rid}' and status eq 'Succeeded'") == rows
    assert _q(a, f"resourceUri eq '{rid}' and status eq 'Failed'") == []
    assert _q(a, f"resourceUri eq '{rid}' and level eq 'Error'") == []
    assert _q(a, f"resourceUri eq '{rid}' and level eq 'informational'") == rows
    assert _q(a, f"resourceUri eq '{rid}' and caller eq 'nobody@x'") == []
    assert _q(a, f"resourceUri eq '{rid}' and caller eq '{rows[0]['caller']}'") == rows
    assert _q(a, f"resourceUri eq '{rid}' and eventTimestamp ge '2999-01-01T00:00:00Z'") == []


if __name__ == "__main__":
    import sys
    _fails = 0
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_") and callable(_f):
            try:
                _f()
                print("PASS", _n)
            except Exception as _e:  # noqa: BLE001
                _fails += 1
                print("FAIL", _n, repr(_e))
    sys.exit(1 if _fails else 0)
