"""GW-1: Eventarc httpEndpoint delivery on a runtime with no sockets (Nano/Pyodide) goes through the awaited gateway bridge.
`sys.platform` is forced to "emscripten" and urllib is booby-trapped; the bridge is a fake async hook.
Run: PYTHONPATH=. python tests/conformance/test_eventarc_nano_http.py"""
import asyncio
import base64
import json
import sys
import urllib.request

from core.aws_wire_router import AwsWireRouter
from core import gateway_common as gc


def main():
    AwsWireRouter.STRICT_GCP_PROJECT = False
    r = AwsWireRouter()
    seen, codes = [], [503, 200]

    async def hook(fwd):
        seen.append((fwd.method, fwd.url, fwd.headers.get("ce-type"), json.loads(fwd.body)["type"]))
        return codes.pop(0) if len(codes) > 1 else codes[0], {}, b""

    r.async_backend_fetch = hook

    def boom(*a, **k):
        raise AssertionError("urllib used on Nano")
    real_platform, real_open = sys.platform, urllib.request.urlopen
    sys.platform, urllib.request.urlopen = "emscripten", boom
    try:
        P, L = "demo", "us-central1"
        T = f"/v1/projects/{P}/locations/{L}/triggers"

        async def call(method, path, body=None, query=None):
            out = await r.ahandle(method, path, query or {}, {}, json.dumps(body).encode() if body is not None else b"")
            return out["status"], json.loads(out["body"] or b"{}")
        flt = [{"attribute": "type", "value": "google.cloud.pubsub.topic.v1.messagePublished"}]

        async def run():
            s, e = await call("POST", T, {"eventFilters": flt, "destination": {"httpEndpoint": {"uri": "https://hook.example.com/ev"}},
                                          "retryPolicy": {"maxAttempts": 3, "minRetryDelay": "0.1s", "maxRetryDelay": "0.2s"}}, {"triggerId": "h"})
            assert s == 200, e
            topic = e["response"]["transport"]["pubsub"]["topic"]
            await call("POST", f"/v1/{topic}:publish", {"messages": [{"data": base64.b64encode(b"x").decode()}]})
            assert seen and seen[0][1] == "https://hook.example.com/ev", seen
            for _ in range(30):
                await asyncio.sleep(0.1)
                s, d = await call("GET", f"{T}/h/deliveries")
                if d["delivered"]:
                    break
            return d
        d = asyncio.run(run())
    finally:
        sys.platform, urllib.request.urlopen = real_platform, real_open
    dl = d["deliveries"][0]
    assert d["delivered"] == 1 and dl["attemptCount"] == 2 and [a["ok"] for a in dl["attempts"]] == [False, True], d
    assert len(seen) == 2 and seen[0][3] == "google.cloud.pubsub.topic.v1.messagePublished"
    print("eventarc nano http delivery: ok (RETRYING after 503, DELIVERED after retry, via the bridge)")


if __name__ == "__main__":
    main()
