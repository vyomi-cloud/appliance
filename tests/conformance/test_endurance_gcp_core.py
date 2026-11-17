"""vyomi-endurance GCP estate regressions (F300-F399). Host + Pyodide where the core is shared.

    PYTHONPATH=. python3 tests/conformance/test_endurance_gcp_core.py
"""
import asyncio
import json


def _check(name, cond):
    if not cond:
        raise AssertionError(name)
    print(f"  [PASS] {name}")


class _Req:
    def __init__(self, path, method="GET"):
        self.scope = {"path": path, "raw_path": path.encode(), "query_string": b"", "headers": []}
        self.method = method
        self.headers = {}


def t_f300():
    from core import middleware
    r = _Req("/v1/v1/locations/us-central1/keyRings/k/cryptoKeys/c/cryptoKeyVersions")
    middleware._collapse_doubled_version(r)
    _check("F300 /v1/v1/ (provider client appends the version to a custom endpoint) collapses to /v1/",
           r.scope["path"].startswith("/v1/locations/") and not r.scope["path"].startswith("/v1/v1"))


def t_router():
    from core import gcp_compute_core as c
    r = {"project": "p", "region": "r", "name": "x", "id": "1", "networkName": "n", "creationTimestamp": "t", "nats": []}
    _check("F301 router without bgp has no bgp block", "bgp" not in c._router_view(r))
    nats = c._norm_nats("p", "r", [{"name": "n1", "natIps": ["u"], "natIpAllocateOption": "MANUAL_ONLY"}])
    _check("F302 NAT keeps natIps and omits an unset logConfig", nats[0]["natIps"] == ["u"] and "logConfig" not in nats[0])
    nats = c._norm_nats("p", "r", [{"name": "n1", "logConfig": {"enable": True, "filter": "ERRORS_ONLY"}}])
    _check("F302 NAT keeps a set logConfig", nats[0]["logConfig"]["filter"] == "ERRORS_ONLY")


def run():
    t_f300()
    t_router()


if __name__ == "__main__":
    run()
    print("OK")
