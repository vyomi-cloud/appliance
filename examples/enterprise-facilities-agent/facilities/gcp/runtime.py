"""GCP flavour of the harness: the Google SDK client factories, the contract names and the BLOCKED classification.
The PASS / BLOCKED / FAIL model, Ctx.step and Ctx.verdict come from facilities/runtime.py (shared with AWS).

Transport policy (stated in README-GCP.md):
  * Pub/Sub and Firestore use the SDK DEFAULT (gRPC), pointed at the simulator the way developers point them at an emulator:
    PUBSUB_EMULATOR_HOST / FIRESTORE_EMULATOR_HOST. With VYOMI_GCP_REAL_BACKENDS=1 the simulator runs the real emulators (lane realbackend).
  * Every other API uses the vendor client's REST transport (transport="rest" + api_endpoint) or google-genai / vertexai.Client (HTTP by design).
    The simulator front door is HTTP/1.1."""
import json, os, time
from urllib.parse import urlparse
from ..runtime import Ctx, Blocked, PASS, BLOCKED, FAIL

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "vyomi-project")

# resource names fixed by the cross-lane reference contract (GCP adaptation of the AWS names)
NAMES = dict(users="facilities-users", kb="facilities-kb", gateway="facilities-gateway", api="facilities-api", api_gateway="facilities-api-gw",
             topic="work-order-approval", inbox="approver-inbox", ledger="approval-ledger", guardrail="facilities-guardrail",
             engine="facilities_supervisor", memory="facilities_memory", keyring="facilities", key="ledger-key", armor="facilities-guardrail",
             bucket="facilities-docs", assets="assets", work_orders="work-orders", docs_topic="facilities-doc-events", docs_sub="facilities-doc-events-sub",
             mcp="facilities-tools", policy="facilities-read-only-tools", agent_sa="agent-sa")

COMPONENTS = {1: "Access and perimeter security (Identity Platform, API Gateway, Cloud Armor)", 2: "Channels and input guardrails (Model Armor), approver inbox (Pub/Sub)",
              3: "Vertex Agent Engine: supervisor + 3 sub-agents", 4: "Agent gateway: MCP tool registry + Cedar agent policy",
              5: "Actions and approval (Pub/Sub + Cloud Run function + Firestore ledger)", 6: "Knowledge search (Vertex RAG Engine)", 7: "Tools (Cloud Run functions + Firestore)",
              8: "AgentOps and observability (Trace, Logging, Monitoring)", 9: "Agent Platform Sessions + Memory Bank", 10: "Foundation models (Gemini on Vertex)",
              11: "Response generation (grounded, cited, Model Armor)", 12: "Knowledge processing pipeline (GCS, Eventarc, function, RAG import)",
              13: "Governance and security (Cloud KMS, Cloud Audit Logs)"}

LANE = dict(core="gcp-ref-corefix", sandbox="gcp-ref-sandbox", real="gcp-ref-realbackend", identity="gcp-ref-identity", model="local model", engine="agent-engine-runtime (no lane yet)")

_GRPC_DOWN = ("failed parsing http/2", "trying to connect an http1.x server", "failed to connect to all addresses", "connection refused", "socket closed",
              "statuscode.unavailable", "deadline exceeded", "stream removed", "connection reset", "handshake failed")


# error texts the simulator is known to produce for gaps another lane owns (see the lane briefs); anything else stays a FAIL
_HINTS = (("failed to parse spanid", "core"), ("cannot parse the openapi", "identity"), ("jwt verification fails", "identity"),
          ("tools.retrieval is not supported", "core"), ("notificationconfigs", "core"), ("name 'print' is not defined", "core"),
          ("does not run pickle", "engine"), ("agentengineoperation", "engine"))


def classify(e, lane):
    """The lane that owes the missing capability, or None when the app or the simulator is simply wrong (FAIL)."""
    low = f"{type(e).__name__}: {e}".lower()
    if "local llm endpoint" in low or "no model" in low or "needs a model" in low or ("503" in low and "model" in low and "not reachable" in low):
        return LANE["model"]
    if "is not available in the function sandbox" in low or "function sandbox" in low:
        return LANE["sandbox"]
    for needle, owner in _HINTS:
        if needle in low:
            return LANE[owner]
    name = type(e).__name__
    if name in ("ServiceUnavailable", "DeadlineExceeded", "RetryError", "TransportError") and any(x in low for x in _GRPC_DOWN):
        return LANE["real"]          # a gRPC channel to the simulator cannot be opened: no gRPC data plane yet
    if lane and (name in ("MethodNotAllowed", "NotImplemented", "Unimplemented", "UnknownOperationException") or "unknown path" in low or "not simulated" in low
                 or "not supported" in low or "not implemented" in low or "unsupported" in low or "http 404" in low or "404" in low.split(":")[0]):
        return lane
    return None


class GcpCtx(Ctx):
    COMPONENTS = COMPONENTS

    def __init__(self, endpoint, region="us-central1", out=print):
        super().__init__(endpoint, region, out)
        self.project = PROJECT
        self.loc = region
        self.parent = f"projects/{PROJECT}/locations/{region}"
        self.state["notes"] = []
        self._io = None
        self._creds = None
        self.local_functions = False      # DEV ONLY, set by run_e2e.py --dev-local-functions
        self.pubsub_host = os.environ.get("PUBSUB_EMULATOR_HOST") or urlparse(endpoint).netloc
        self.firestore_host = os.environ.get("FIRESTORE_EMULATOR_HOST") or urlparse(endpoint).netloc
        self.real_backends = os.environ.get("VYOMI_GCP_REAL_BACKENDS") == "1"
        # the standard emulator variables: what an unmodified google-cloud-pubsub / google-cloud-firestore client reads
        os.environ["PUBSUB_EMULATOR_HOST"] = self.pubsub_host
        os.environ["FIRESTORE_EMULATOR_HOST"] = self.firestore_host
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", PROJECT)

    @property
    def io(self):
        if self._io is None:
            from .io import GcpIO
            self._io = GcpIO(self)
        return self._io

    def note(self, text):
        if text not in self.state["notes"]:
            self.state["notes"].append(text)

    def blocked_lane(self, e, lane):
        return classify(e, lane)

    # ---- credentials and client factories --------------------------------------------------------------------------------------------------------
    def anon(self):
        from google.auth.credentials import AnonymousCredentials
        return AnonymousCredentials()

    def token_creds(self):
        """A bearer-token credential (what ADC gives a real app); the simulator accepts any token."""
        if self._creds is None:
            from google.oauth2.credentials import Credentials
            self._creds = Credentials(token="vyomi-local")
        return self._creds

    def rest(self, cls, **kw):
        """Official google-cloud client on its REST transport, pointed at the simulator with api_endpoint only."""
        from google.api_core.client_options import ClientOptions
        return cls(credentials=self.anon(), transport="rest", client_options=ClientOptions(api_endpoint=self.endpoint), **kw)

    def authed_session(self):
        """google-auth AuthorizedSession: the vendor-supported way to call a Google REST API that has no client library."""
        from google.auth.transport.requests import AuthorizedSession
        return AuthorizedSession(self.token_creds())

    def api(self, method, path, body=None, params=None, expect=(200, 201, 204)):
        r = self.authed_session().request(method, self.endpoint + path, json=body, params=params, timeout=120)
        if r.status_code not in expect:
            raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
        try:
            return r.json()
        except Exception:
            return r.text

    def genai(self):
        if "genai" not in self._c:          # keep a reference: a garbage-collected genai.Client closes its HTTP session
            from google import genai
            from google.genai import types
            self._c["genai"] = genai.Client(vertexai=True, project=self.project, location=self.loc, credentials=self.token_creds(),
                                            http_options=types.HttpOptions(base_url=self.endpoint, api_version="v1"))
        return self._c["genai"]

    def vertex(self, api_version="v1beta1"):
        key = "vertex" + api_version
        if key not in self._c:
            import vertexai
            from google.genai import types
            self._c[key] = vertexai.Client(project=self.project, location=self.loc, credentials=self.token_creds(),
                                           http_options=types.HttpOptions(base_url=self.endpoint, api_version=api_version))
        return self._c[key]

    def storage(self):
        from google.cloud import storage
        from google.api_core.client_options import ClientOptions
        return storage.Client(project=self.project, credentials=self.anon(), client_options=ClientOptions(api_endpoint=self.endpoint))

    def pubsub(self):
        """SDK default clients (gRPC); the emulator variables set in __init__ decide where they connect."""
        if "pubsub" not in self._c:
            from google.cloud import pubsub_v1
            self._c["pubsub"] = (pubsub_v1.PublisherClient(), pubsub_v1.SubscriberClient())
        return self._c["pubsub"]

    def firestore(self):
        if "firestore" not in self._c:
            from google.cloud import firestore
            self._c["firestore"] = firestore.Client(project=self.project)
        return self._c["firestore"]

    def aiplatform(self, name):
        from google.cloud import aiplatform_v1 as av
        key = "av." + name
        if key not in self._c:
            self._c[key] = self.rest(getattr(av, name))
        return self._c[key]


def is_model_missing(e):
    t = str(e).lower()
    return "local llm endpoint" in t or "not reachable" in t or "no model" in t or ("503" in t and "model" in t)


def fixture_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "fixtures")


def need_grpc(ctx, what):
    """One cheap probe of the SDK-default gRPC channel (no retry, short deadline) so a missing gRPC data plane is reported once as BLOCKED(realbackend)
    instead of every call retrying for a minute. what = 'pubsub' | 'firestore'."""
    key = f"_need_{what}"
    if key not in ctx.state:
        try:
            if what == "pubsub":
                pub, _ = ctx.pubsub()
                list(pub.list_topics(request={"project": f"projects/{ctx.project}"}, retry=None, timeout=10))
            else:
                list(ctx.firestore().collection("_probe").limit(1).stream(retry=None, timeout=10))
            ctx.state[key] = None
        except Exception as e:
            ctx.state[key] = f"{what} gRPC at {ctx.pubsub_host if what == 'pubsub' else ctx.firestore_host} is not usable: {type(e).__name__}: {str(e)[:140]}"
            ctx.note(f"{what}: SDK-default gRPC client could not reach the simulator ({ctx.state[key]}). Needs the real emulators as data plane "
                     f"(VYOMI_GCP_REAL_BACKENDS=1, lane realbackend) or PUBSUB_EMULATOR_HOST / FIRESTORE_EMULATOR_HOST pointing at emulators.")
    if ctx.state[key]:
        raise Blocked(LANE["real"], ctx.state[key])


def need_result(ctx, who):
    """Components that consume the agent run report BLOCKED (not FAIL) when the run itself could not happen because an upstream capability is missing."""
    if not ctx.state.get("result"):
        raise Blocked(ctx.state.get("agent_blocked_by", LANE["sandbox"]), f"no agent run to {who}: {ctx.state.get('agent_error', 'the agent could not run (tools unavailable)')}")
    return ctx.state["result"]


def raw_log_entries(ctx, flt):
    """Diagnostic read of Cloud Logging entries:list without the SDK's default timestamp filter (used to tell a simulator filter bug from an app bug)."""
    r = ctx.api("POST", "/v2/entries:list", {"resourceNames": [f"projects/{ctx.project}"], "filter": flt, "pageSize": 200})
    return r.get("entries", [])
