"""Shared harness for the Azure reference-architecture probes (step 1 of REFERENCE-ARCH-GCP-AZURE.md).
Plain Azure SDK calls against the simulator; nothing mocked. Each probe is a list of steps; a step PASSes only if the real call returned
the expected thing. Causes for a non-PASS: (a) simulator missing the API, (b) simulator wrong behaviour, (c) needs a model, (d) probe/SDK usage mistake."""
import json, os, socket, sys, tempfile, threading, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SUB = "00000000-0000-0000-0000-cloudlearn01"
RG = "rg-probe"
LOC = "eastus"


def repo_root():
    r = os.environ.get("VYOMI_REPO") or HERE
    while r != "/" and not os.path.exists(os.path.join(r, "core", "wire_ingress.py")):
        r = os.path.dirname(r)
    return r


def start_in_process():
    """Run the REAL appliance app (server.py: wire ingress + /azure-data/* routes + the Service Bus AMQP listener) inside this process
    on a free port, fresh state per run. facilities/server.py uses only core.wire_ingress for AWS; the Azure data planes the probe needs
    (Functions invoke, APIM gateway, AMQP) are mounted by server.py, so we start that instead."""
    root = repo_root()
    work = tempfile.mkdtemp(prefix="azprobe-")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    s = socket.socket(); s.bind(("127.0.0.1", 0)); amqp = s.getsockname()[1]; s.close()
    os.environ.update({"CLOUDLEARN_STATE_FILE": os.path.join(work, "state.sqlite3"), "VYOMI_AZSB_DB": os.path.join(work, "azsb.sqlite"),
                       "VYOMI_DATA_DIR": work, "VYOMI_AMQP_PORT": str(amqp), "VYOMI_AMQPS_PORT": "0", "CLOUDLEARN_TIER_ENFORCE": "0", "VYOMI_AMQP_HOST": "127.0.0.1"})
    os.environ["VYOMI_PROBE_AMQP_PORT"] = str(amqp)
    sys.path.insert(0, root)
    os.chdir(root)
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
    return f"http://127.0.0.1:{port}"


def amqp_port():
    return int(os.environ["VYOMI_PROBE_AMQP_PORT"])


def sb_conn(port):
    return "Endpoint=sb://localhost:%d;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=probe;UseDevelopmentEmulator=true" % port


def endpoint():
    return os.environ.get("VYOMI_ENDPOINT") or start_in_process()


class Cred:
    """Fake Entra credential: the simulator does not validate the bearer token."""
    def get_token(self, *a, **k):
        from azure.core.credentials import AccessToken
        return AccessToken("vyomi-test-token", 4102444800)


def arm(cls, base, **kw):
    from azure.core.pipeline.policies import SansIOHTTPPolicy
    return cls(Cred(), SUB, base_url=base, authentication_policy=SansIOHTTPPolicy(), polling_interval=0, **kw)


def ensure_rg(base):
    from azure.mgmt.resource.resources import ResourceManagementClient
    arm(ResourceManagementClient, base).resource_groups.create_or_update(RG, {"location": LOC})


class Probe:
    def __init__(self, num, name, title):
        self.num, self.name, self.title, self.steps = num, name, title, []
        self.base = None

    def step(self, name, fn, cause_on_fail="a", blocked=None):
        """fn() returns evidence (str/obj) or raises. blocked='no model' marks a step the environment cannot satisfy (still runs fn
        to prove the API surface; its failure is BLOCKED, not FAIL)."""
        t = time.time()
        try:
            ev = fn()
            rec = {"step": name, "status": "PASS", "evidence": _short(ev)}
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            rec = {"step": name, "status": "BLOCKED" if blocked else "FAIL", "error": _short(msg, 1500),
                   "cause": ("c" if blocked == "no model" else "d" if blocked else cause_on_fail)}
            if blocked:
                rec["blocked_reason"] = blocked
        rec["seconds"] = round(time.time() - t, 2)
        self.steps.append(rec)
        print(f"  [{rec['status']}] {name} {rec.get('evidence') or rec.get('error') or ''}"[:int(os.environ.get("W", "300"))], flush=True)
        return rec["status"] == "PASS"

    def note(self, name, text, status="PASS"):
        self.steps.append({"step": name, "status": status, "evidence": text})
        print(f"  [{status}] {name} {text}"[:int(os.environ.get("W", "300"))], flush=True)

    @property
    def status(self):
        s = {x["status"] for x in self.steps}
        return "FAIL" if "FAIL" in s else "BLOCKED" if "BLOCKED" in s else "PASS"

    def finish(self):
        out = {"component": self.num, "name": self.name, "title": self.title, "status": self.status, "steps": self.steps}
        print("RESULT " + json.dumps(out), flush=True)
        os._exit(0 if self.status == "PASS" else 1)


def _short(x, n=240):
    s = x if isinstance(x, str) else json.dumps(x, default=str)
    return s if len(s) <= n else s[:n] + "..."


def http_shim_transport(host_port):
    """azure-core transport that sends https://<host_port>/... as plain http. Some SDKs (azure-servicebus management, azure-keyvault,
    azure-search) hard-code https; the simulator listens on plain http locally. Nothing else is altered."""
    from azure.core.pipeline.transport import RequestsTransport

    class _T(RequestsTransport):
        def send(self, request, **kw):
            if request.url.startswith("https://" + host_port):
                request.url = "http://" + request.url[len("https://"):]
            return super().send(request, **kw)
    return _T()


def sb_seed(topic=None, sub=None, queue=None):
    """HARNESS SHORTCUT (reported as a gap in probe_02): create Service Bus entities directly in the runtime store the AMQP listener
    reads (core.azure_servicebus_runtime.get_store), because neither ARM (azure-mgmt-servicebus) nor the wire PUT reaches that store."""
    from core import azure_servicebus_core as sb
    from core.azure_servicebus_runtime import get_store
    st = get_store()
    for name in (topic, queue):
        if name:
            sb.dispatch(st, "PUT", f"/{name}")
    if topic and sub:
        sb.dispatch(st, "PUT", f"/{topic}/subscriptions/{sub}")


def aoai(base, api_version="2024-10-21"):
    from openai import AzureOpenAI
    return AzureOpenAI(azure_endpoint=base, api_key="local-key", api_version=api_version, max_retries=0, timeout=60)


def ensure_openai(base, account="aoai1"):
    """ARM: an OpenAI account with a chat and an embedding deployment."""
    from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient
    c = arm(CognitiveServicesManagementClient, base)
    c.accounts.begin_create(RG, account, {"location": LOC, "kind": "OpenAI", "sku": {"name": "S0"}, "properties": {"customSubDomainName": account}}).result()
    for n, m, v in (("chat", "gpt-4o", "2024-11-20"), ("embed", "text-embedding-3-small", "1")):
        c.deployments.begin_create_or_update(RG, account, n, {"sku": {"name": "Standard", "capacity": 1}, "properties": {"model": {"format": "OpenAI", "name": m, "version": v}}}).result()
    return c
