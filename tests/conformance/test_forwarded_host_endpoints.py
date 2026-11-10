"""Endpoints the simulator advertises must use the address the client reaches it at (X-Forwarded-Host from the user's vyomi-tunnel),
not the in-Codespace service name `simulator:9000`.  Run: PYTHONPATH=. python3 tests/conformance/test_forwarded_host_endpoints.py (or pytest)"""
import os
import sys
import tempfile

os.environ.setdefault("CLOUDLEARN_STATE_DIR", tempfile.mkdtemp(prefix="fwd-host-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from core.app_context import request_host  # noqa: E402
from providers.azure_services import _public_base  # noqa: E402


class _Req:
    def __init__(self, headers, netloc="127.0.0.1:9000", scheme="http"):
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.url = type("U", (), {"netloc": netloc, "scheme": scheme})()


def test_forwarded_host_wins_over_the_service_name():
    r = _Req({"host": "simulator:9000", "x-forwarded-host": "127.0.0.1:9000", "x-forwarded-proto": "http"})
    assert _public_base(r) == "http://127.0.0.1:9000"


def test_without_the_header_the_host_is_used_as_before():
    assert _public_base(_Req({"host": "simulator:9000"})) == "http://simulator:9000"
    assert _public_base(_Req({"host": "localhost:9000", "x-forwarded-proto": "https"})) == "https://localhost:9000"


def test_only_a_plain_host_port_is_accepted():
    for bad in ("evil.com/x", "a b", "h:99999x", "http://x", "x@y", ""):
        assert request_host({"host": "simulator:9000", "x-forwarded-host": bad}) == "simulator:9000", bad
    assert request_host({"host": "h", "x-forwarded-host": "10.0.0.1:19000, proxy"}) == "10.0.0.1:19000"
    assert request_host({"host": "h", "x-forwarded-host": "[::1]:9000"}) == "[::1]:9000"


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("[PASS]", n)
