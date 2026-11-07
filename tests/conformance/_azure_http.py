"""Self-contained HTTP front for the Azure wire (the SAME AwsWireRouter code Nano runs in the browser): lets the REAL Azure SDKs
(azure-mgmt-*, azure-storage-blob) and `az rest` talk to it with only the endpoint changed. start() -> (base_url, router)."""
import socket
import threading
import time

import uvicorn
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route

from core.aws_wire_router import AwsWireRouter


def start(router=None, port=0):
    r = router or AwsWireRouter()
    if hasattr(r.az_arm, "STRICT_SUBSCRIPTION"):
        type(r.az_arm).STRICT_SUBSCRIPTION = False

    async def handle(request):
        body = await request.body()
        host = request.headers.get("host", "")
        out = r.handle(request.method, request.url.path, dict(request.query_params), dict(request.headers), body)
        if hasattr(r.az_arm, "_base") and host:
            r.az_arm._base = f"http://{host}"
        hdrs = {k: v for k, v in (out.get("headers") or {}).items() if k.lower() not in ("content-length", "transfer-encoding")}
        b = out.get("body") or b""
        if not isinstance(b, (bytes, bytearray)):
            import json
            b = json.dumps(b).encode()
            hdrs.setdefault("content-type", "application/json")
        return Response(content=bytes(b), status_code=out["status"], headers=hdrs)

    app = Starlette(routes=[Route("/{p:path}", handle, methods=["GET", "PUT", "POST", "DELETE", "PATCH", "HEAD", "OPTIONS"])])
    if not port:
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", r


if __name__ == "__main__":      # python -m tests.conformance._azure_http [port]  -> serve until killed (for az / curl)
    import sys
    base, _ = start(port=int(sys.argv[1]) if len(sys.argv) > 1 else 9311)
    print(base, flush=True)
    while True:
        time.sleep(3600)
