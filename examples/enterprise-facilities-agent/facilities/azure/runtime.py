"""Azure flavour of the harness: the Azure SDK client factories, the contract names and the BLOCKED classification.
The PASS / BLOCKED / FAIL model, Ctx.step and Ctx.verdict come from facilities/runtime.py (shared with AWS and GCP).

Transport policy (stated in README-AZURE.md):
  * The in-process harness serves the simulator on https://localhost:<port> with a local CA exported through REQUESTS_CA_BUNDLE / SSL_CERT_FILE, so the SDKs
    that refuse bearer tokens over plain http (azure-identity, azure-keyvault-*, azure-monitor-query, azure-ai-agents) run UNMODIFIED. No transport shim.
  * Against a plain-http endpoint (--endpoint http://...) the management clients use the documented emulator mode (no bearer policy); the TLS-only SDKs
    then report BLOCKED with that reason, never a pass.
  * Service Bus data plane: azure-servicebus over AMQP 1.0 with the vendor `UseDevelopmentEmulator=true` connection string.
  * Storage Table / Blob: connection string with an explicit TableEndpoint / BlobEndpoint (the Azurite connection-string form)."""
import json, os, time
from urllib.parse import urlparse
from ..runtime import Ctx, Blocked, PASS, BLOCKED, FAIL

SUB = "00000000-0000-0000-0000-cloudlearn01"      # the simulator's one subscription per space (core/azure_arm_core.DEFAULT_SUBSCRIPTION)
RG = "rg-facilities"
LOC = "eastus"
TENANT = "facilities-tenant"
ACCOUNT_KEY = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="     # the public Azurite development key
STORAGE = "devstoreaccount1"

# resource names fixed by the cross-lane reference contract
NAMES = dict(users="facilities-users", apim="facilities-apim", project="facilities-project", bus="facilities-bus", topic="work-order-approval",
             inbox="approver-inbox", ledger="approvalledger", search="facilities-search", index="facilities-kb", vault="facilities-kv", key="ledger-key",
             guardrail="facilities-guardrail", functions="facilities-tools", capp="facilities-supervisor", docs_account="facilitiesdocs", container="docs",
             assets="assets", work_orders="workorders", memory="longtermmemory", openai="facilities-openai", workspace="facilities-law", insights="facilities-ai",
             supervisor="facilities_supervisor", chat="chat", embed="embed", waf="facilitieswaf", capp_env="facilities-env")

COMPONENTS = {1: "Access and perimeter security (Entra ID, APIM validate-jwt, WAF)", 2: "Channels and input guardrails (content filter), approver inbox (Service Bus)",
              3: "Agent runtime: Foundry Agents + LangGraph app on Container Apps", 4: "Gateway: APIM tool / MCP front + policy (no Cedar on Azure)",
              5: "Actions and approval (Service Bus + Function App + Table ledger)", 6: "Knowledge search (Azure AI Search)", 7: "Tools (Function App + Table storage)",
              8: "AgentOps and observability (Application Insights, Log Analytics, Monitor)", 9: "Memory: Assistants threads + app-level long-term pattern",
              10: "Foundation models (Azure OpenAI chat + embeddings)", 11: "Response generation (grounded, cited, content filter)",
              12: "Knowledge processing pipeline (Blob, Event Grid, Function, AI Search indexer)", 13: "Governance and security (Key Vault, Activity Log)"}

LANE = dict(ai="az-ref-ai", messaging="az-ref-messaging", data="az-ref-data", gateway="az-ref-gateway", runtime="az-ref-runtime", model="local model",
            host="container-app-host (no lane owns running container images)", kv="keyvault-dataplane (no lane owns the vault host / kid form)")


def classify(e, lane):
    """The lane that owes the missing capability, or None when the app or the simulator is simply wrong (FAIL).
    Only 'API is absent / not routed' shapes are blocked on a lane; assertion failures about behaviour stay FAIL unless the step raises Blocked itself."""
    low = f"{type(e).__name__}: {e}".lower()
    if "local llm endpoint" in low or "no model" in low or ("503" in low and "model" in low):
        return LANE["model"]
    if "vaultnotfound" in low and "'_'" in low:
        return LANE["kv"]                # the key id returned by Key Vault carries no vault, so crypto operations cannot find the vault (path-form vault_uri)
    if "http 500" in low and "function " in low and ("no module named 'azure" in low or "modulenotfounderror" in low):
        return LANE["runtime"]           # the Function App sandbox cannot import the Azure SDKs next to azure.functions (the shim shadows the azure namespace)
    if lane:
        name = type(e).__name__
        if (name in ("ResourceNotFoundError", "HttpResponseError", "ServiceRequestError", "NotFoundError", "ResourceNotFound", "MessagingEntityNotFoundError", "DecodeError",
                     "ClientAuthenticationError", "BadRequestError", "InternalServerError", "APIConnectionError", "CosmosHttpResponseError", "CosmosResourceNotFoundError")
                or any(x in low for x in ("404", "405", "not found", "not simulated", "unsupported", "not supported", "not implemented", "nosuchbucket", "methodnotallowed",
                                          "unknown search service operation", "unauthorized", "not a jwt"))):
            return lane
    return None


class StaticToken:
    """A TokenCredential that hands back one bearer token: the Entra access token when component 1 got one, else a fixed development token
    (the simulator accepts any bearer for control planes)."""
    def __init__(self, ctx):
        self.ctx = ctx

    def get_token(self, *scopes, **kw):
        from azure.core.credentials import AccessToken
        return AccessToken(self.ctx.state.get("access_token") or "vyomi-local", int(time.time()) + 3600)


class AzCtx(Ctx):
    COMPONENTS = COMPONENTS

    def __init__(self, endpoint, region=LOC, out=print, http_endpoint=None, amqp_port=None):
        super().__init__(endpoint, region, out)
        self.sub, self.rg, self.loc = SUB, RG, region
        self.http = http_endpoint or endpoint                   # plain-http address of the same simulator (call-backs, AMQP host)
        self.tls = endpoint.startswith("https")
        self.host = urlparse(endpoint).hostname or "localhost"
        self.amqp_port = int(amqp_port or os.environ.get("VYOMI_AMQP_PORT") or 5672)
        self.state["notes"] = []
        self.local_functions = False
        self.real_backends = os.environ.get("VYOMI_AZURE_REAL_BACKENDS") == "1"
        os.environ.setdefault("AZURE_SUBSCRIPTION_ID", SUB)

    @property
    def io(self):
        if "io" not in self._c:
            from .io import AzureIO
            self._c["io"] = AzureIO(self)
        return self._c["io"]

    def note(self, text):
        if text not in self.state["notes"]:
            self.state["notes"].append(text)

    def blocked_lane(self, e, lane):
        return classify(e, lane)

    # ---- credentials and client factories ---------------------------------------------------------------------------------------------------------
    def cred(self):
        return StaticToken(self)

    def arm(self, cls, **kw):
        """Azure management client (azure-mgmt-*) pointed at the simulator with base_url only. Over https the normal bearer policy runs; over plain http the
        documented emulator mode (no bearer policy) is used."""
        key = "arm." + cls.__name__
        if key not in self._c:
            extra = {}
            if not self.tls:
                from azure.core.pipeline.policies import SansIOHTTPPolicy
                extra["authentication_policy"] = SansIOHTTPPolicy()
            self._c[key] = cls(self.cred(), SUB, base_url=self.endpoint, polling_interval=0, **extra, **kw)
        return self._c[key]

    def ensure_rg(self):
        from azure.mgmt.resource.resources import ResourceManagementClient
        self.arm(ResourceManagementClient).resource_groups.create_or_update(RG, {"location": LOC})

    def rid(self, provider, kind, name):
        return f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/{provider}/{kind}/{name}"

    def aoai(self, api_version="2024-10-21"):
        key = "aoai" + api_version
        if key not in self._c:
            from openai import AzureOpenAI
            self._c[key] = AzureOpenAI(azure_endpoint=self.endpoint, api_key="vyomi-local", api_version=api_version, max_retries=0,
                                       timeout=int(os.environ.get("FACILITIES_READ_TIMEOUT", "120")))
        return self._c[key]

    def agents(self):
        """azure-ai-agents (the Foundry Agents SDK) at the project endpoint <endpoint>/api/projects/<project>."""
        if "agents" not in self._c:
            from azure.ai.agents import AgentsClient
            kw = {}
            if not self.tls:
                from azure.core.pipeline.policies import SansIOHTTPPolicy
                kw["authentication_policy"] = SansIOHTTPPolicy()
            self._c["agents"] = AgentsClient(endpoint=f"{self.endpoint}/api/projects/{NAMES['project']}", credential=self.cred(), **kw)
        return self._c["agents"]

    def _storage_cs(self, svc):
        proto = "https" if self.tls else "http"
        return f"DefaultEndpointsProtocol={proto};AccountName={STORAGE};AccountKey={ACCOUNT_KEY};{svc}Endpoint={self.endpoint}/{STORAGE};"

    def tables(self):
        """azure-data-tables (Storage Table service). With VYOMI_AZURE_REAL_BACKENDS=1 the simulator's Table service is backed by real Azurite."""
        if "tables" not in self._c:
            from azure.data.tables import TableServiceClient
            self._c["tables"] = TableServiceClient.from_connection_string(self._storage_cs("Table"))
        return self._c["tables"]

    def table(self, name):
        return self.tables().create_table_if_not_exists(name)

    def blob(self):
        if "blob" not in self._c:
            from azure.storage.blob import BlobServiceClient
            self._c["blob"] = BlobServiceClient.from_connection_string(self._storage_cs("Blob"))
        return self._c["blob"]

    def sb_conn(self):
        """Service Bus data plane (AMQP 1.0): the vendor emulator connection string; same string on real Azure minus UseDevelopmentEmulator."""
        return f"Endpoint=sb://{self.host}:{self.amqp_port};SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=vyomi;UseDevelopmentEmulator=true"

    def servicebus(self):
        from azure.servicebus import ServiceBusClient
        return ServiceBusClient.from_connection_string(self.sb_conn())

    def search_endpoint(self):
        """The data-plane URL of the AI Search service: what ARM advertises when the simulator serves it, else the ARM-extension path form it serves today."""
        if "search_endpoint" not in self.state:
            adv = ""
            try:
                from azure.mgmt.search import SearchManagementClient
                adv = self.arm(SearchManagementClient).services.get(RG, NAMES["search"]).endpoint or ""
            except Exception:
                pass
            if adv and (urlparse(adv).hostname or "") in (self.host, "localhost", "127.0.0.1"):
                self.state["search_endpoint"] = adv.rstrip("/")
            else:
                self.state["search_endpoint"] = f"{self.endpoint}/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Search/searchServices/{NAMES['search']}"
                if adv:
                    self.note(f"AI Search: ARM advertises {adv}, which this simulator does not serve; the SDKs use the simulator's ARM-extension path form instead.")
        return self.state["search_endpoint"]

    def search_key(self):
        if "search_key" not in self.state:
            from azure.mgmt.search import SearchManagementClient
            self.state["search_key"] = self.arm(SearchManagementClient).admin_keys.get(RG, NAMES["search"]).primary_key
        return self.state["search_key"]

    def func_url(self, app, fn):
        """HTTP trigger URL of a function: https://<app>.azurewebsites.net/api/<fn> on Azure; the simulator serves it under /azure-data/functions/<app>/api/<fn>."""
        return f"{self.endpoint}/azure-data/functions/{app}/api/{fn}"

    def apim_url(self, path=""):
        """APIM gateway data plane: https://<service>.azure-api.net/<api path> on Azure; /azure-data/apim/<service>/<api path> on the simulator."""
        return f"{self.endpoint}/azure-data/apim/{NAMES['apim']}/{path.lstrip('/')}"


def is_model_missing(e):
    t = str(e).lower()
    return "local llm endpoint" in t or "not reachable" in t or "no model" in t or ("503" in t and "model" in t)


def fixture_dir():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "fixtures")


def need_result(ctx, who):
    """Components that consume the agent run report BLOCKED (not FAIL) when the run itself could not happen because an upstream capability is missing."""
    if not ctx.state.get("result"):
        raise Blocked(ctx.state.get("agent_blocked_by", LANE["runtime"]), f"no agent run to {who}: {ctx.state.get('agent_error', 'the agent could not run (tools unavailable)')}")
    return ctx.state["result"]
