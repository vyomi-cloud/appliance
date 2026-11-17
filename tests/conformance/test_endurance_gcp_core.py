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


def run():
    t_f300()


if __name__ == "__main__":
    run()
    print("OK")
