"""Shared helper for the Azure data-plane SDK tests: starts the REAL appliance app (server.py) in this process on a free
port with fresh state (CLOUDLEARN_TIER_ENFORCE=0 so Max-tier services such as Cosmos are reachable; the tier gate itself
is covered elsewhere). Env must be set BEFORE the first call (the real-backend flag is read when server.py is imported)."""
import os
import socket
import sys
import tempfile
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
SUB = "00000000-0000-0000-0000-cloudlearn01"
FAILS: list = []


def ok(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (f" -> {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def freeport():
    k = socket.socket()
    k.bind(("127.0.0.1", 0))
    p = k.getsockname()[1]
    k.close()
    return p


def start_sim() -> str:
    work = tempfile.mkdtemp(prefix="azdata-")
    os.environ.update({"CLOUDLEARN_STATE_FILE": os.path.join(work, "state.sqlite3"), "VYOMI_AZSB_DB": os.path.join(work, "azsb.sqlite"),
                       "VYOMI_DATA_DIR": work, "VYOMI_AMQP_PORT": str(freeport()), "VYOMI_AMQPS_PORT": "0",
                       "CLOUDLEARN_TIER_ENFORCE": "0", "VYOMI_AMQP_HOST": "127.0.0.1"})
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import uvicorn
    import server
    try:
        from core import azure_arm_core
        azure_arm_core.AzureArm.STRICT_SUBSCRIPTION = False
    except Exception:
        pass
    port = freeport()
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    t0 = time.time()
    while not srv.started:
        if time.time() - t0 > 180:
            raise SystemExit("appliance did not start")
        time.sleep(0.1)
    time.sleep(1.0)
    return f"http://127.0.0.1:{port}"


def table_cs(base: str) -> str:
    return f"DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey={KEY};TableEndpoint={base}/devstoreaccount1;"


class Cred:
    def get_token(self, *a, **k):
        from azure.core.credentials import AccessToken
        return AccessToken("vyomi-test-token", 4102444800)


def arm(cls, base, **kw):
    from azure.core.pipeline.policies import SansIOHTTPPolicy
    return cls(Cred(), SUB, base_url=base, authentication_policy=SansIOHTTPPolicy(), polling_interval=0, **kw)
