"""Azure APIM gateway whose backend is served by the SAME event loop (the sweep's `serviceUrl: http://127.0.0.1:9000`).
The router's async door must run the blocking outbound call off the loop, or the loop waits on itself and the gateway answers
502 "TimeoutError: timed out" (offline-sweepA-azure "APIM valid key proxies to the backend").
Run: PYTHONPATH=. python3 tests/conformance/test_azure_apim_self_backend.py
"""
import asyncio
import sys

from core.aws_wire_router import AwsWireRouter
from core.azure_arm_core import AzureArm, DEFAULT_SUBSCRIPTION as SUB

AzureArm.STRICT_SUBSCRIPTION = False
fails = 0


def check(name, ok, extra=""):
    global fails
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else " :: " + str(extra)[:300]))
    fails += 0 if ok else 1


async def main():
    async def serve(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{\"ok\":true}\n")
        await writer.drain()
        writer.close()
    srv = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    rt = AwsWireRouter()
    a = rt.az_arm
    Q = {"api-version": "2022-08-01"}
    S = f"/subscriptions/{SUB}/resourceGroups/sb-rg"
    base = "/providers/Microsoft.ApiManagement/service/sbsvc"
    put = lambda p, b: a.handle("PUT", S + p, Q, b)
    put("", {"location": "eastus"})
    put(base, {"location": "eastus", "sku": {"name": "Developer", "capacity": 1}, "properties": {"publisherEmail": "a@b.c", "publisherName": "x"}})
    put(base + "/apis/echo", {"properties": {"displayName": "Echo", "path": "echo", "serviceUrl": f"http://127.0.0.1:{port}", "subscriptionRequired": False}})
    put(base + "/apis/echo/operations/h", {"properties": {"displayName": "h", "method": "GET", "urlTemplate": "/healthz"}})
    r = await asyncio.wait_for(rt.ahandle("GET", "/azure-data/apim/sbsvc/echo/healthz", {}, {"x-vyomi-rg": "sb-rg"}, b""), 30)
    check("APIM gateway proxies to a backend on the same event loop", r["status"] == 200 and b"ok" in r["body"], (r["status"], r["body"][:120]))
    srv.close()

asyncio.run(main())
sys.exit(1 if fails else 0)
