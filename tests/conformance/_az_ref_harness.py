"""Shared harness for the Azure reference-architecture lane tests: the REAL appliance app (server.py: ARM, the /azure-data wires and the
Service Bus AMQP 1.0 listener) in-process on free ports with fresh state, driven by the unmodified Azure SDKs.
Importing this module has the side effect of setting the env the app reads, so import it BEFORE `server`."""
import os
import socket
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SUB = "00000000-0000-0000-0000-cloudlearn01"
RG = "rg-ref"
LOC = "eastus"
FAILS = []


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def start():
    """-> (http base url, amqp port). Fresh state per process."""
    work = tempfile.mkdtemp(prefix="azref-")
    port, amqp = _free_port(), _free_port()
    os.environ.update({"CLOUDLEARN_STATE_FILE": os.path.join(work, "state.sqlite3"), "VYOMI_AZSB_DB": os.path.join(work, "azsb.sqlite"),
                       "VYOMI_DATA_DIR": work, "VYOMI_AMQP_PORT": str(amqp), "VYOMI_AMQPS_PORT": "0", "VYOMI_AMQP_HOST": "127.0.0.1",
                       "CLOUDLEARN_TIER_ENFORCE": "0"})
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    import uvicorn
    import server
    try:
        from core import azure_arm_core
        azure_arm_core.AzureArm.STRICT_SUBSCRIPTION = False
    except Exception:
        pass
    srv = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    t0 = time.time()
    while not srv.started:
        if time.time() - t0 > 180:
            raise SystemExit("appliance did not start")
        time.sleep(0.1)
    time.sleep(1.0)
    return f"http://127.0.0.1:{port}", amqp


def sb_conn(port):
    return f"Endpoint=sb://localhost:{port};SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=k;UseDevelopmentEmulator=true"


class Cred:
    def get_token(self, *a, **k):
        from azure.core.credentials import AccessToken
        return AccessToken("vyomi-test-token", 4102444800)


def arm(cls, base, **kw):
    from azure.core.pipeline.policies import SansIOHTTPPolicy
    return cls(Cred(), SUB, base_url=base, authentication_policy=SansIOHTTPPolicy(), polling_interval=0, **kw)


def ensure_rg(base, rg=RG):
    from azure.mgmt.resource.resources import ResourceManagementClient
    arm(ResourceManagementClient, base).resource_groups.create_or_update(rg, {"location": LOC})


def ok(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""), flush=True)
    if not cond:
        FAILS.append(name)
    return cond


def run_cases(cases):
    """cases: [(name, fn)]; fn returns normally or raises = FAIL. Exits the process (the in-process server threads are daemons)."""
    for name, fn in cases:
        try:
            fn()
            ok(name, True)
        except Exception as e:  # noqa: BLE001
            ok(name, False, f"{type(e).__name__}: {str(e)[:300]}")
    print("\n" + ("ALL PASS" if not FAILS else f"FAILED: {FAILS}"), flush=True)
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
